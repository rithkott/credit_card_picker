#!/usr/bin/env python3
"""Deterministic credit-card portfolio optimizer.

Implements docs/plans/02-optimizer.md: builds every subset of eligible cards
(sizes 1..max_cards), scores each jointly against a user-authored spend profile,
and ranks portfolios by net annual value. Choose-your-own-category cards expand
into one variant per option (mutually exclusive in a portfolio), so the search
also picks each such card's best configuration per combination (spec §10).
The optimizer is a pure function:

    recommendations = f(dataset, spend_profile, policy_constants, as_of_date)

Identical inputs produce byte-identical output. `--as-of` (default: today) is the
only time input, used for signup-bonus expiry, promotional-credit expiry, and
staleness warnings.

Usage:
  python3 scripts/optimize.py --profile PATH
      [--max-cards N] [--rewards KIND[,KIND...]] [--top N] [--json]
      [--as-of YYYY-MM-DD]

Flags override the profile's `user:` fields. Exit codes: 0 ok, 1 input
(profile/CLI) error, 2 dataset error.
"""

import argparse
import copy
import itertools
import json
import math
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assign_exact

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "data" / "cards"
META_DIR = ROOT / "data" / "meta"
STALE_DAYS = 183  # matches scripts/validate_cards.py

# ---------------------------------------------------------------------------
# Policy constants — every judgment call lives here and is echoed into every
# output, so a user can always see the assumptions behind a recommendation.
# ---------------------------------------------------------------------------

# Fraction of a credit's face value a typical user captures. Haircut scales with
# redemption friction: monthly use-it-or-lose-it coupons are easy to miss;
# annual credits are hard to miss. Applies to credits WITHOUT usage_keys —
# generic category-gated credits where no confirmation signal exists.
CREDIT_CAPTURE = {"monthly": 0.5, "quarterly": 0.7, "semiannual": 0.8,
                  "annual": 0.9, "every_4_years": 0.9, "every_5_years": 0.9}

# Capture for credits whose usage the user explicitly CONFIRMED (a usage_keys
# entry appears in user.confirmed_usage): the "do they use this service at all"
# risk is answered by the questionnaire, so the residual haircut covers only
# breakage — forgetting a monthly coupon, timing windows. Monthly 0.8 (even
# loyal users miss ~2 of 12 windows a year), annual+ 0.95 (once a year for a
# service you already use is near-automatic).
CONFIRMED_CREDIT_CAPTURE = {"monthly": 0.8, "quarterly": 0.85, "semiannual": 0.9,
                            "annual": 0.95, "every_4_years": 0.95, "every_5_years": 0.95}

PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "semiannual": 2,
                    "annual": 1, "every_4_years": 0.25, "every_5_years": 0.2}

CAP_PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "annual": 1}

# Deterministic proxy for portal price premiums (portal fares often run above
# direct booking, eroding the headline multiplier).
PORTAL_RATE_MULT = 0.75

# Fraction of a rotating card's theoretical annual cap room assumed usable,
# reflecting quarters whose categories don't match the user's spend.
ROTATING_OVERLAP = 0.75

# Categories that historically appear in rotating quarters (Freedom Flex,
# Discover it). The rotating wildcard line may draw only from these.
ROTATING_ELIGIBLE = ["dining", "drugstores", "gas", "groceries",
                     "online_shopping", "streaming"]

TIER_ORDER = ["building", "fair", "good", "very_good", "excellent"]

# Reward kinds a user may ask for (user.reward_preferences / --rewards). Concrete
# kinds filter candidates by the program-level redeems_for classification in
# data/meta/point-valuations.yaml; 'total_value' disables the filter entirely.
REWARD_KINDS = ["cashback", "flights", "hotels"]
REWARD_PREF_CHOICES = REWARD_KINDS + ["total_value"]

# Exhaustive search scores every subset; each score_portfolio call costs
# ~35-55 µs in pure Python. 2M subsets ≈ one to two minutes — the tolerable
# ceiling for an interactive CLI. At max_cards=3 this admits ~229 variants
# (C(229,3) ≈ 2M), matching 02-optimizer.md §6's ~200-card horizon.
MAX_SCORED_SUBSETS = 2_000_000

KIND_RANK = {"merchant": 0, "category": 1, "rotating": 2, "fallback": 3, "base": 4}

USER_DEFAULTS = {"max_cards": 3,
                 "optimize_for": "ongoing", "activates_rotating": True,
                 "confirmed_usage": [],
                 "accepts_brand_lockin": False,
                 "reward_preferences": ["total_value"]}

EPS = 1e-9


class InputError(Exception):
    """Bad profile or CLI input — exit 1."""


class DataError(Exception):
    """Dataset problem or scale limit — exit 2."""


def policy_constants() -> dict:
    return {
        "CREDIT_CAPTURE": CREDIT_CAPTURE,
        "CONFIRMED_CREDIT_CAPTURE": CONFIRMED_CREDIT_CAPTURE,
        "PERIODS_PER_YEAR": PERIODS_PER_YEAR,
        "CAP_PERIODS_PER_YEAR": CAP_PERIODS_PER_YEAR,
        "PORTAL_RATE_MULT": PORTAL_RATE_MULT,
        "ROTATING_OVERLAP": ROTATING_OVERLAP,
        "ROTATING_ELIGIBLE": ROTATING_ELIGIBLE,
        "TIER_ORDER": TIER_ORDER,
        "STALE_DAYS": STALE_DAYS,
        "MAX_SCORED_SUBSETS": MAX_SCORED_SUBSETS,
        # Documented formula, not a number: points are valued at the mean of
        # floor_cpp and optimistic_cpp, dropping to floor_cpp when a loyalty
        # or transfer-gateway gate is unconfirmed (plan 08).
        "CPP_MODEL": "avg = (floor_cpp + optimistic_cpp) / 2; floor when gated & unconfirmed",
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_yaml(path: Path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_dataset() -> dict:
    """Load registries and all card files. Assumes the dataset already passes
    scripts/validate_cards.py; nothing structural is re-checked here."""
    try:
        categories = load_yaml(META_DIR / "categories.yaml")["categories"]
        merchants = load_yaml(META_DIR / "merchants.yaml")["merchants"]
        programs = load_yaml(META_DIR / "point-valuations.yaml")["programs"]
        usage_questions = load_yaml(META_DIR / "usage-questions.yaml")["groups"]
    except (OSError, yaml.YAMLError, KeyError) as e:
        raise DataError(f"cannot load data/meta/ registries: {e}")
    usage_keys = {key for group in usage_questions.values()
                  for key in (group.get("items") or {})}
    overlap = set(categories) & set(merchants)
    if overlap:
        raise DataError(f"registry keys shared by categories and merchants: {sorted(overlap)}")
    card_files = sorted(CARDS_DIR.glob("*/*.yaml"))
    if not card_files:
        raise DataError(f"no card files found under {CARDS_DIR}")
    try:
        cards = [load_yaml(p) for p in card_files]
    except yaml.YAMLError as e:
        raise DataError(f"invalid card YAML: {e}")
    cards.sort(key=lambda c: c["id"])
    return {"categories": categories, "merchants": merchants,
            "programs": programs, "cards": cards,
            "usage_questions": usage_questions, "usage_keys": usage_keys}


def load_profile(path: Path, dataset: dict) -> dict:
    try:
        raw = load_yaml(path)
    except OSError as e:
        raise InputError(f"cannot read profile: {e}")
    except yaml.YAMLError as e:
        raise InputError(f"profile is not valid YAML: {e}")
    return parse_profile(raw, dataset)


def _require_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise InputError(f"profile: {what} must be a number >= 0, got {value!r}")


def parse_profile(raw, dataset: dict) -> dict:
    """Validate a raw profile mapping; hand-rolled checks in the style of
    validate_cards.py's registry checks. Raises InputError on any violation."""
    if not isinstance(raw, dict):
        raise InputError("profile must be a YAML mapping")
    unknown = sorted(set(raw) - {"spend", "merchant_spend", "user"})
    if unknown:
        raise InputError(f"profile: unknown top-level key(s): {unknown}")

    spend = raw.get("spend")
    if not isinstance(spend, dict) or not spend:
        raise InputError("profile: 'spend' must be a non-empty mapping of category: annual USD")
    categories = dataset["categories"]
    for cat, amount in spend.items():
        if cat not in categories:
            raise InputError(f"profile: spend: unknown category '{cat}' (see data/meta/categories.yaml)")
        if categories[cat].get("pseudo"):
            raise InputError(f"profile: spend: '{cat}' is a pseudo-category and may not appear in a spend profile")
        _require_number(amount, f"spend[{cat}]")

    merchant_spend = raw.get("merchant_spend") or {}
    if not isinstance(merchant_spend, dict):
        raise InputError("profile: 'merchant_spend' must be a mapping of merchant: annual USD")
    merchants = dataset["merchants"]
    carved = {}
    for m, amount in merchant_spend.items():
        if m not in merchants:
            raise InputError(f"profile: merchant_spend: unknown merchant '{m}' (see data/meta/merchants.yaml)")
        _require_number(amount, f"merchant_spend[{m}]")
        cat = merchants[m]["category"]
        carved[cat] = carved.get(cat, 0) + amount
    for cat, total in sorted(carved.items()):
        if total > spend.get(cat, 0) + EPS:
            raise InputError(
                f"profile: merchant carve-outs for category '{cat}' total ${total:,.2f}, "
                f"exceeding spend[{cat}] = ${spend.get(cat, 0):,.2f} — carve-outs are "
                f"sub-buckets of their category, never additive")

    user_raw = raw.get("user")
    if not isinstance(user_raw, dict):
        raise InputError("profile: 'user' must be a mapping and include credit_tier")
    if "uses_travel_portal" in user_raw:
        raise InputError(
            "profile: user.uses_travel_portal was removed — list the issuer portals "
            "you actually book through in user.confirmed_usage instead "
            "(see data/meta/usage-questions.yaml, travel_portals group)")
    if "valuation_mode" in user_raw:
        raise InputError(
            "profile: user.valuation_mode was removed — points are now valued at "
            "a single realistic average per program: (floor_cpp + optimistic_cpp)/2, "
            "dropping to floor_cpp when a loyalty/transfer gate is unconfirmed "
            "(docs/plans/08-simplified-valuation.md)")
    unknown = sorted(set(user_raw) - (set(USER_DEFAULTS) | {"credit_tier"}))
    if unknown:
        raise InputError(f"profile: user: unknown key(s): {unknown}")
    if "credit_tier" not in user_raw:
        raise InputError("profile: user.credit_tier is required")
    user = {**USER_DEFAULTS, **user_raw}
    validate_user(user, dataset["usage_keys"])

    return {"spend": dict(sorted(spend.items())),
            "merchant_spend": dict(sorted(merchant_spend.items())),
            "user": user}


def validate_user(user: dict, usage_keys: set) -> None:
    if user["credit_tier"] not in TIER_ORDER:
        raise InputError(f"profile: user.credit_tier must be one of {TIER_ORDER}, got {user['credit_tier']!r}")
    mc = user["max_cards"]
    if isinstance(mc, bool) or not isinstance(mc, int) or not 1 <= mc <= 5:
        raise InputError(f"profile: user.max_cards must be an integer 1-5, got {mc!r}")
    if user["optimize_for"] not in ("ongoing", "year1"):
        raise InputError(f"profile: user.optimize_for must be 'ongoing' or 'year1', got {user['optimize_for']!r}")
    for flag in ("activates_rotating", "accepts_brand_lockin"):
        if not isinstance(user[flag], bool):
            raise InputError(f"profile: user.{flag} must be true or false, got {user[flag]!r}")
    confirmed = user["confirmed_usage"]
    if (not isinstance(confirmed, list)
            or any(not isinstance(k, str) for k in confirmed)
            or len(set(confirmed)) != len(confirmed)):
        raise InputError(
            f"profile: user.confirmed_usage must be a list of unique usage-question "
            f"item keys (see data/meta/usage-questions.yaml), got {confirmed!r}")
    bad = sorted(set(confirmed) - usage_keys)
    if bad:
        raise InputError(
            f"profile: user.confirmed_usage: unknown key(s) {bad} — valid keys are "
            f"the items of data/meta/usage-questions.yaml")
    user["confirmed_usage"] = sorted(confirmed)  # canonical order for determinism
    prefs = user["reward_preferences"]
    if (not isinstance(prefs, list) or not prefs
            or any(p not in REWARD_PREF_CHOICES for p in prefs)
            or len(set(prefs)) != len(prefs)):
        raise InputError(
            f"profile: user.reward_preferences must be a non-empty list of unique "
            f"values from {REWARD_PREF_CHOICES}, got {prefs!r}")


# ---------------------------------------------------------------------------
# Reward-line model and spend assignment (spec §5)
# ---------------------------------------------------------------------------

def build_buckets(profile: dict, merchants: dict) -> dict:
    """Partition the user's spend: one bucket per merchant carve-out, plus one
    residual bucket per category (category total minus its carve-outs)."""
    buckets = {}
    carved = {}
    for m, amount in profile["merchant_spend"].items():
        cat = merchants[m]["category"]
        buckets[m] = {"key": m, "kind": "merchant", "category": cat, "amount": float(amount)}
        carved[cat] = carved.get(cat, 0.0) + float(amount)
    for cat, amount in profile["spend"].items():
        buckets[cat] = {"key": cat, "kind": "category", "category": cat,
                        "amount": float(amount) - carved.get(cat, 0.0)}
    return buckets


def unlocked_programs(cards: list) -> frozenset:
    """Programs whose transfer partners the portfolio can reach: a gateway card
    (unlocks_transfers) unlocks its own program for every card in the subset."""
    return frozenset(c["currency"]["program"] for c in cards
                     if c.get("unlocks_transfers"))


def avg_cpp(prog: dict) -> float:
    """The single engaged valuation (plan 08): the mean of the registry's
    conservative floor and its transfer-partner optimistic value — a realistic
    middle instead of a user-chosen floor|optimistic mode."""
    return (prog["floor_cpp"] + prog["optimistic_cpp"]) / 2.0


def effective_cpp(card: dict, programs: dict, confirmed: set,
                  unlocked: frozenset = frozenset()) -> tuple:
    """Context-aware cents-per-point: (cpp, note-or-None). Points are valued
    at the program's engaged average (avg_cpp) — mean of floor and optimistic —
    except when a gate mechanically limits redemption to the cash floor:
      - loyalty: lock-in currencies (no cashback path, loyalty_keys in
        data/meta/point-valuations.yaml) require confirmed loyalty in
        user.confirmed_usage.
      - transfer gateway: currencies marked transfer_gateway_required reach
        their partners only through a gateway card (unlocks_transfers) — e.g.
        Freedom-family UR is pure 1cpp cash unless the scored portfolio also
        holds a Sapphire. `unlocked` is the portfolio's unlocked_programs().
    Cash and fixed-value currencies have floor == optimistic, so the average
    is a no-op for them."""
    prog = programs[card["currency"]["program"]]
    loyalty = prog.get("loyalty_keys") or []
    if loyalty and not (set(loyalty) & confirmed):
        return prog["floor_cpp"], (
            f"points valued at floor {prog['floor_cpp']}cpp — no confirmed loyalty "
            f"to {prog.get('label', card['currency']['program'])} "
            f"(confirm one of: {', '.join(loyalty)} in user.confirmed_usage)")
    if (prog.get("transfer_gateway_required")
            and not card.get("unlocks_transfers")
            and card["currency"]["program"] not in unlocked):
        return prog["floor_cpp"], (
            f"points valued at floor {prog['floor_cpp']}cpp — "
            f"{prog.get('label', card['currency']['program'])} transfer partners "
            f"need a gateway card (unlocks_transfers) in the portfolio")
    return avg_cpp(prog), None


def build_lines(card: dict, profile: dict, programs: dict, buckets: dict,
                unlocked: frozenset = frozenset()) -> list:
    """All reward lines of one card, with effective USD rates and bucket
    eligibility. Issuer precedence (merchant beats category beats base) is
    encoded in the eligibility sets, not chosen by the optimizer. `unlocked` is
    the scoring portfolio's unlocked_programs() — the default (empty) prices
    the card standalone."""
    user = profile["user"]
    confirmed = set(user["confirmed_usage"])
    cpp, _ = effective_cpp(card, programs, confirmed, unlocked)
    closed = set(card.get("closed_loop", {}).get("merchants", []))
    lines = []

    def add(kind, key, rate, eligible, room, note="", room_key=None):
        eligible = [b for b in eligible if b in buckets]
        if closed:
            eligible = [b for b in eligible
                        if buckets[b]["kind"] == "merchant" and b in closed]
        lines.append({"card_id": card["id"], "kind": kind, "key": key,
                      "rate": rate, "cpp": cpp,
                      "effective_rate": rate * cpp / 100.0,
                      "room": room, "room_key": room_key,
                      "eligible": sorted(eligible), "note": note})

    def cap_room(cap):
        """Annualized spend room and, for shared caps, the pool key uniting the
        entries that draw from one combined pool (validator guarantees members
        agree on period + max_spend_usd)."""
        room = cap["max_spend_usd"] * CAP_PERIODS_PER_YEAR[cap["period"]]
        shared = cap.get("shared_cap_id")
        room_key = f"{card['id']}|{shared}" if shared else None
        note = f"capped at ${room:,.0f}/yr" + (f" (shared pool '{shared}')" if shared else "")
        return room, room_key, note

    merchant_line_keys = {mr["merchant"] for mr in card["merchant_rewards"]}
    for mr in card["merchant_rewards"]:
        cap = mr.get("cap")
        if cap:
            room, room_key, cap_note = cap_room(cap)
            add("merchant", mr["merchant"], mr["rate"], [mr["merchant"]], room,
                cap_note, room_key)
            add("fallback", mr["merchant"], cap["fallback_rate"], [mr["merchant"]],
                None, "above-cap fallback")
        else:
            add("merchant", mr["merchant"], mr["rate"], [mr["merchant"]], None)

    for cr in card["category_rewards"]:
        cat = cr["category"]
        if cat == "choice":
            raise DataError(f"{card['id']}: unexpanded 'choice' reward reached "
                            "build_lines — expand_choice_variants must run first")
        if cat == "rotating":
            cap = cr.get("cap")
            if cap is None:
                raise DataError(f"{card['id']}: rotating reward has no cap — the "
                                "optimizer models rotating as a capped wildcard line")
            rotation = cr.get("rotation") or {}
            activated = (not rotation.get("requires_activation", False)) or user["activates_rotating"]
            rate = cr["rate"] if activated else cap["fallback_rate"]
            room = cap["max_spend_usd"] * 4 * ROTATING_OVERLAP
            eligible = [b for b, bk in buckets.items() if bk["category"] in ROTATING_ELIGIBLE]
            note = f"rotating room ${room:,.0f}"
            if rotation.get("requires_activation"):
                note += " ×activation" if activated else " (not activated → fallback rate)"
            add("rotating", cat, rate, eligible, room, note)
            add("fallback", cat, cap["fallback_rate"], eligible, None, "above-cap fallback")
            continue

        rate = cr["rate"]
        notes = ["chosen category"] if cr.get("_chosen") else []
        if cr.get("portal_only"):
            if card.get("portal") not in confirmed:
                continue  # portal unconfirmed — dropped; spend falls through to the next line
            rate = rate * PORTAL_RATE_MULT
            notes.append(f"portal ×{PORTAL_RATE_MULT} ({card['portal']} confirmed)")
        note = "; ".join(notes)
        eligible = [cat] if cat in buckets else []
        eligible += [b for b, bk in buckets.items()
                     if bk["kind"] == "merchant" and bk["category"] == cat
                     and b not in merchant_line_keys]
        cap = cr.get("cap")
        if cap:
            room, room_key, cap_note = cap_room(cap)
            add("category", cat, rate, eligible, room,
                f"{note}; {cap_note}" if note else cap_note, room_key)
            add("fallback", cat, cap["fallback_rate"], eligible, None, "above-cap fallback")
        else:
            add("category", cat, rate, eligible, None, note)

    claimed = set()
    for ln in lines:
        claimed.update(ln["eligible"])
    add("base", "base", card["base_rate"], [b for b in buckets if b not in claimed], None)
    return lines


def assign_spend(lines: list, buckets: dict, greedy_exact=None) -> tuple:
    """Exact spend assignment (plan 10 §2): the greedy regret rule scores every
    subset first; when the conservative detector says its exactness argument
    does not apply (competing capped units, multi-line shared pools), the
    deterministic flow solver computes the true LP optimum, and its solution is
    adopted only when it strictly beats greedy — otherwise the greedy
    assignment is kept verbatim for byte-stable output. `greedy_exact` lets
    score_portfolio pass the RunTables bitmask verdict instead of re-deriving
    it per subset."""
    assignments, unassigned = assign_spend_greedy(lines, buckets)
    if greedy_exact is None:
        greedy_exact = assign_exact.greedy_is_exact(lines, buckets)
    if not greedy_exact:
        greedy_total = sum(a["usd_value"] for a in assignments)
        optimal_total, flows = assign_exact.solve_assignment(lines, buckets)
        if optimal_total > greedy_total + assign_exact.VALUE_EPS:
            assignments, unassigned = _flow_assignments(lines, buckets, flows)
    return assignments, unassigned


def _flow_assignments(lines: list, buckets: dict, flows: dict) -> tuple:
    """Render a flow-solver solution in the greedy emission order (descending
    effective rate, then card/kind/key, then bucket) so adopted-LP output is
    deterministic and shaped exactly like greedy output."""
    order = sorted(range(len(lines)),
                   key=lambda i: (-lines[i]["effective_rate"], lines[i]["card_id"],
                                  KIND_RANK[lines[i]["kind"]], lines[i]["key"]))
    remaining = {b: bk["amount"] for b, bk in buckets.items()}
    assignments = []
    for i in order:
        ln = lines[i]
        for b in sorted(ln["eligible"]):
            take = flows.get((i, b), 0.0)
            if take <= EPS:
                continue
            remaining[b] -= take
            assignments.append({"card_id": ln["card_id"], "bucket": b,
                                "usd_assigned": take, "rate": ln["rate"],
                                "cpp": ln["cpp"], "kind": ln["kind"],
                                "usd_value": take * ln["effective_rate"],
                                "note": ln["note"]})
    unassigned = {b: amt for b, amt in sorted(remaining.items()) if amt > EPS}
    return assignments, unassigned


def assign_spend_greedy(lines: list, buckets: dict) -> tuple:
    """Greedy assignment over all lines of all candidate cards, in descending
    effective USD rate, with deterministic tie-breaks (spec §5.5). Exact when
    assign_exact.greedy_is_exact holds — capped units competing for the same
    buckets or splitting a shared pool across lines fall to the flow solver
    via the assign_spend dispatcher (plan 10 §2)."""
    remaining = {b: bk["amount"] for b, bk in buckets.items()}
    order = sorted(lines, key=lambda ln: (-ln["effective_rate"], ln["card_id"],
                                          KIND_RANK[ln["kind"]], ln["key"]))
    # Shared-cap pools: lines carrying the same room_key draw down one combined
    # spend pool (e.g. "2x on gas + groceries, combined, up to $5,000/yr").
    pools = {}
    for ln in order:
        if ln["room"] is not None and ln.get("room_key"):
            pools.setdefault(ln["room_key"], ln["room"])
    assignments = []
    for i, ln in enumerate(order):
        eligible = [b for b in ln["eligible"] if remaining[b] > EPS]
        if not eligible:
            continue
        if ln["room"] is not None and len(eligible) > 1:
            # Regret rule: a capped multi-bucket line steals spend where
            # displacement costs least — buckets in ascending order of their
            # best alternative effective rate among remaining (later) lines.
            later = order[i + 1:]
            def best_alternative(b):
                return max((l2["effective_rate"] for l2 in later if b in l2["eligible"]),
                           default=0.0)
            eligible.sort(key=lambda b: (best_alternative(b), b))
        else:
            eligible.sort()
        pool_key = ln.get("room_key") if ln["room"] is not None else None
        room_left = (float("inf") if ln["room"] is None
                     else pools[pool_key] if pool_key else ln["room"])
        for b in eligible:
            if room_left <= EPS:
                break
            take = min(room_left, remaining[b])
            if take <= EPS:
                continue
            remaining[b] -= take
            room_left -= take
            assignments.append({"card_id": ln["card_id"], "bucket": b,
                                "usd_assigned": take, "rate": ln["rate"],
                                "cpp": ln["cpp"], "kind": ln["kind"],
                                "usd_value": take * ln["effective_rate"],
                                "note": ln["note"]})
        if pool_key:
            pools[pool_key] = room_left
    unassigned = {b: amt for b, amt in sorted(remaining.items()) if amt > EPS}
    return assignments, unassigned


# ---------------------------------------------------------------------------
# Value model (spec §4)
# ---------------------------------------------------------------------------

def score_credits(cards: list, profile: dict, programs: dict,
                  as_of: date, tables=None) -> list:
    """Value every credit across the portfolio against a shared per-category
    remaining-spend tracker, so stacked credits can never exceed the user's real
    spend. Draw order is deterministic: file order within a card, card-id order
    across the portfolio.

    Gate order per credit (plan 07): expires → usage gate → unlock_spend_usd →
    valuation. The usage gate: a credit with usage_keys is $0 unless the user
    confirmed at least one key (anyOf) in user.confirmed_usage; confirmed
    credits use the softer CONFIRMED_CREDIT_CAPTURE table (the questionnaire
    answered "do they use it at all"; the haircut covers residual breakage),
    keyless credits keep the conservative CREDIT_CAPTURE.

    Credit variants beyond the classic USD statement credit:
      - unlock_spend_usd: the credit is $0 unless the user's per-period total
        spend can plausibly reach the unlock threshold (same optimistic
        feasibility rule as signup bonuses — all spend could go on this card).
      - amount_points: points-denominated drops (anniversary miles), valued via
        the card's loyalty-aware program cpp; they don't offset spend, so no
        tracker draw.
      - kind: in_kind: amount_usd is a curator estimate (free nights, companion
        certificates), so the capture haircut always applies, even uncategorized.
      - expires: promotional credits are $0 once past the as-of date, mirroring
        the signup-bonus expiry rule.
      - usage_keys × category: both gates stack — a confirmed Uber credit with
        no transit spend is still $0 via the tracker.
      - uncategorized + usage_keys (confirmed): face × capture — a merchant
        coupon, not near-cash. Full face value is reserved for automatic
        credits (no keys, no category; anniversary points/cash).

    With `tables` (a RunTables), the per-credit gates/arithmetic come from the
    per-run cache (credit_parts) and only the tracker draws run per subset —
    same arithmetic, same strings, byte-identical output (plan 10 §1).
    """
    tracker = {cat: float(v) for cat, v in profile["spend"].items()}
    confirmed = set(profile["user"]["confirmed_usage"])
    unlocked = unlocked_programs(cards)
    results = []
    for card in sorted(cards, key=lambda c: c["id"]):
        if tables is not None:
            parts = tables.credit_parts[card["id"]][tables.ctx(card, unlocked)]
        else:
            cpp, _ = effective_cpp(card, programs, confirmed, unlocked)
            parts = credit_parts(card, cpp, profile, as_of)
        for part in parts:
            if part[0] == "final":
                results.append(part[1])
                continue
            _, name, haircut, cat, note = part
            available = tracker.get(cat, 0.0)
            if available <= EPS:
                results.append({"card_id": card["id"], "name": name,
                                "value": 0.0,
                                "note": f"$0 — no remaining spend in '{cat}'"})
                continue
            value = min(haircut, available)
            tracker[cat] = available - value
            if haircut > available:
                note += f" (capped by remaining '{cat}' spend)"
            results.append({"card_id": card["id"], "name": name,
                            "value": value, "note": note})
    return results


def credit_parts(card, cpp: float, profile: dict, as_of: date) -> list:
    """The portfolio-independent pieces of score_credits for one card (plan 10
    §1): every gate, capture table, face value, and note string except the
    shared-tracker draw. Each entry is ("final", result_dict) for credits whose
    value is already settled, or ("draw", name, haircut, category, note) for
    categorized credits that must still draw from the per-portfolio tracker.
    `cpp` must be the card's effective cpp for the scoring context (locked or
    gateway-unlocked)."""
    total_spend = sum(profile["spend"].values())
    confirmed = set(profile["user"]["confirmed_usage"])
    parts = []

    def final(name, value, note):
        parts.append(("final", {"card_id": card["id"], "name": name,
                                "value": value, "note": note}))

    for credit in card["credits"]:
        if "expires" in credit and date.fromisoformat(credit["expires"]) < as_of:
            final(credit["name"], 0.0, f"$0 — promo expired {credit['expires']}")
            continue
        keys = credit.get("usage_keys")
        if keys and not (set(keys) & confirmed):
            final(credit["name"], 0.0,
                  f"$0 — requires confirmed use of one of: "
                  f"{', '.join(keys)} (user.confirmed_usage)")
            continue
        periods = PERIODS_PER_YEAR[credit["period"]]
        capture = (CONFIRMED_CREDIT_CAPTURE if keys else CREDIT_CAPTURE)[credit["period"]]
        usage_note = (f"; confirmed: {', '.join(sorted(set(keys) & confirmed))}"
                      if keys else "")
        in_kind = credit.get("kind") == "in_kind"

        unlock = credit.get("unlock_spend_usd")
        if unlock is not None and total_spend / periods < unlock - EPS:
            final(credit["name"], 0.0,
                  f"$0 — unlock spend ${unlock:,.0f}/{credit['period']} unreachable at your volume")
            continue
        unlock_note = f"; unlocked (${unlock:,.0f}/{credit['period']} spend)" if unlock is not None else ""

        if "amount_points" in credit:
            face = credit["amount_points"] * periods * cpp / 100.0
            value = face * capture if in_kind else face
            note = (f"{credit['amount_points'] * periods:,.0f} pts/yr × {cpp}cpp"
                    + (f" × capture {capture}" if in_kind else "")
                    + unlock_note + usage_note)
            final(credit["name"], value, note)
            continue

        face = credit["amount_usd"] * periods
        cat = credit.get("category")
        if cat is None:
            if in_kind:
                final(credit["name"], face * capture,
                      f"in-kind est. ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}")
            elif keys:
                # A confirmed merchant coupon (Oura, StubHub, Walmart+) —
                # spendable only at that merchant, so never full face.
                final(credit["name"], face * capture,
                      f"face ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}")
            else:
                final(credit["name"], face,
                      f"automatic — full face value{unlock_note}")
            continue
        haircut = face * capture
        kind_label = "in-kind est." if in_kind else "face"
        note = f"{kind_label} ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}"
        parts.append(("draw", credit["name"], haircut, cat, note))
    return parts


def score_bonus(card: dict, profile: dict, programs: dict, as_of: date,
                card_earnings: float = 0.0,
                unlocked: frozenset = frozenset()) -> dict:
    """Signup-bonus value — counted once, year-1 only. A bonus's `value` may mix
    points and usd (both summed); `tiers` add tranches whose cumulative spend
    requirements are checked with the same feasibility rule as the base;
    `first_year_match` (Discover) is valued as the card's own computed
    first-year earnings."""
    bonus = card["signup_bonus"]
    if bonus is None:
        return {"value": 0.0, "note": "no signup bonus"}
    if "expires" in bonus and date.fromisoformat(bonus["expires"]) < as_of:
        return {"value": 0.0, "note": f"$0 — offer expired {bonus['expires']}"}
    if bonus.get("first_year_match"):
        return _match_bonus(card_earnings)
    total_spend = sum(profile["spend"].values())
    window_spend = total_spend * bonus["window_months"] / 12.0
    if window_spend < bonus["spend_requirement_usd"] - EPS:
        return {"value": 0.0, "note": "$0 — spend requirement unreachable at your volume"}
    cpp, _ = effective_cpp(card, programs,
                           set(profile["user"]["confirmed_usage"]), unlocked)

    def usd_of(value):
        parts, worth = [], 0.0
        if "points" in value:
            worth += value["points"] * cpp / 100.0
            parts.append(f"{value['points']:,.0f} points × {cpp}cpp")
        if "usd" in value:
            worth += float(value["usd"])
            parts.append(f"${value['usd']:,.0f} cash")
        return worth, " + ".join(parts)

    total, note = usd_of(bonus["value"])
    tiers = bonus.get("tiers", [])
    reached = [t for t in tiers if window_spend >= t["spend_requirement_usd"] - EPS]
    for tier in reached:
        worth, desc = usd_of(tier["value"])
        total += worth
        note += f"; +tier at ${tier['spend_requirement_usd']:,.0f} spend ({desc})"
    if len(reached) < len(tiers):
        note += f"; {len(tiers) - len(reached)} tier(s) unreachable at your volume"
    return {"value": total, "note": note}


def _match_bonus(card_earnings: float) -> dict:
    return {"value": card_earnings,
            "note": f"first-year match of this card's computed earnings (${card_earnings:,.2f})"}


def bonus_static(card: dict, profile: dict, programs: dict, as_of: date,
                 unlocked: frozenset) -> tuple:
    """Portfolio-independent signup-bonus scoring (plan 10 §1). Returns
    ("static", result) when the bonus value is settled without knowing the
    card's in-portfolio earnings, or ("match",) for a live first_year_match
    bonus, which score_portfolio finishes via _match_bonus."""
    bonus = card["signup_bonus"]
    if (bonus is not None and bonus.get("first_year_match")
            and not ("expires" in bonus
                     and date.fromisoformat(bonus["expires"]) < as_of)):
        return ("match",)
    return ("static", score_bonus(card, profile, programs, as_of, 0.0, unlocked))


class RunTables:
    """Per-run cache of everything score_portfolio needs that does not depend
    on which other cards share the portfolio (plan 10 §1). The only binary
    context is the transfer-gateway cpp: a card whose program is
    transfer_gateway_required (and which is not itself a gateway) scores at
    floor cpp standalone and at avg cpp when the subset holds a gateway — so
    each card gets at most two precomputed variants, keyed False (locked) and
    True (unlocked). Lines/parts are read-only downstream; entries are shared
    across subsets, never mutated."""

    def __init__(self, variants: list, profile: dict, programs: dict,
                 buckets: dict, as_of: date):
        confirmed = set(profile["user"]["confirmed_usage"])
        self.lines = {}
        self.credit_parts = {}
        self.bonus_static = {}
        self.unit_masks = {}
        self._gated_program = {}  # card id -> program key when ctx matters, else None
        # Live buckets are run-static, so each card's binding capped units
        # reduce to bitmasks and the per-subset exactness detector becomes a
        # few integer ANDs (assign_exact.masks_compatible).
        bucket_bit = {b: 1 << i for i, b in enumerate(sorted(
            b for b, bk in buckets.items() if bk["amount"] > EPS))}
        for card in variants:
            cid = card["id"]
            prog = card["currency"]["program"]
            gated = bool(programs[prog].get("transfer_gateway_required")
                         and not card.get("unlocks_transfers"))
            self._gated_program[cid] = prog if gated else None
            contexts = {False: frozenset()}
            if gated:
                contexts[True] = frozenset({prog})
            lines_by, parts_by, bonus_by, masks_by = {}, {}, {}, {}
            for ctx, unlocked in contexts.items():
                cpp, _ = effective_cpp(card, programs, confirmed, unlocked)
                lines_by[ctx] = build_lines(card, profile, programs, buckets, unlocked)
                parts_by[ctx] = credit_parts(card, cpp, profile, as_of)
                bonus_by[ctx] = bonus_static(card, profile, programs, as_of, unlocked)
                masks_by[ctx] = assign_exact.unit_masks(lines_by[ctx], buckets,
                                                        bucket_bit)
            if not gated:
                lines_by[True] = lines_by[False]
                parts_by[True] = parts_by[False]
                bonus_by[True] = bonus_by[False]
                masks_by[True] = masks_by[False]
            self.lines[cid] = lines_by
            self.credit_parts[cid] = parts_by
            self.bonus_static[cid] = bonus_by
            self.unit_masks[cid] = masks_by

    def ctx(self, card: dict, unlocked: frozenset) -> bool:
        """The scoring context of one card inside a subset whose gateway
        programs are `unlocked` — mirrors effective_cpp's gateway condition."""
        prog = self._gated_program[card["id"]]
        return prog is not None and prog in unlocked

    def greedy_exact_hint(self, cards: list, unlocked: frozenset) -> bool:
        """Subset-level greedy-exactness verdict from the per-card bitmasks —
        the same answer assign_exact.greedy_is_exact would give, in a few
        integer ANDs."""
        masks = []
        for card in cards:
            cm = self.unit_masks[card["id"]][self.ctx(card, unlocked)]
            if cm is False:
                return False
            masks.extend(cm)
        return assign_exact.masks_compatible(masks)


def membership_fee(card: dict) -> float:
    """Annual cost of a required membership that exists solely for the card
    (required_membership.card_exclusive, e.g. Robinhood Gold). Memberships with
    standalone value (Costco, Prime, Sam's Club) stay unscored — the optimizer
    assumes the user already holds those."""
    rm = card.get("required_membership") or {}
    if rm.get("card_exclusive"):
        return float(rm.get("annual_cost_usd") or 0)
    return 0.0


def score_portfolio(cards: list, profile: dict, programs: dict,
                    buckets: dict, as_of: date, tables=None) -> dict:
    """Jointly score a card subset: one shared spend assignment over all the
    subset's lines, plus credits (shared tracker), plus eligible signup bonuses
    (year-1 only), minus fees. With `tables` (a RunTables built once per run),
    the per-card lines/credit-parts/bonus-parts come from the cache instead of
    being rebuilt per subset — identical arithmetic, byte-identical output
    (plan 10 §1)."""
    unlocked = unlocked_programs(cards)
    lines = []
    for card in cards:
        if tables is not None:
            lines += tables.lines[card["id"]][tables.ctx(card, unlocked)]
        else:
            lines += build_lines(card, profile, programs, buckets, unlocked)
    hint = (tables.greedy_exact_hint(cards, unlocked)
            if tables is not None else None)
    assignments, unassigned = assign_spend(lines, buckets, greedy_exact=hint)
    credits = score_credits(cards, profile, programs, as_of, tables=tables)
    credits_total = sum(c["value"] for c in credits)
    per_card_earnings = {card["id"]: 0.0 for card in cards}
    for a in assignments:
        per_card_earnings[a["card_id"]] += a["usd_value"]
    # Card-wide annual reward caps (e.g. Sam's Cash $5,000/yr): clamp the
    # card's spend earnings; bonuses/credits are unaffected.
    reward_cap_clamps = {}
    for card in cards:
        cap = card.get("max_annual_rewards_usd")
        cid = card["id"]
        if cap is not None and per_card_earnings[cid] > cap:
            reward_cap_clamps[cid] = round(per_card_earnings[cid] - cap, 2)
            per_card_earnings[cid] = cap
    earnings = sum(per_card_earnings.values())
    bonuses = {}
    for card in cards:
        cid = card["id"]
        if tables is not None:
            static = tables.bonus_static[cid][tables.ctx(card, unlocked)]
            bonuses[cid] = (_match_bonus(per_card_earnings[cid])
                            if static[0] == "match" else static[1])
        else:
            bonuses[cid] = score_bonus(card, profile, programs, as_of,
                                       per_card_earnings[cid], unlocked)
    bonus_total = sum(b["value"] for b in bonuses.values())
    # Card-exclusive membership costs (Robinhood Gold) count in both metrics —
    # a fee waiver never covers the separate membership.
    membership = sum(membership_fee(c) for c in cards)
    ongoing_fee = sum(c["fees"]["annual_fee_usd"] for c in cards) + membership
    year1_fee = sum(0 if c["fees"].get("first_year_waived") else c["fees"]["annual_fee_usd"]
                    for c in cards) + membership
    return {
        "cards": sorted(c["id"] for c in cards),
        "ongoing_net": earnings + credits_total - ongoing_fee,
        "year1_net": earnings + credits_total + bonus_total - year1_fee,
        "earnings": earnings,
        "assignments": assignments,
        "unassigned": unassigned,
        "credits": credits,
        "bonuses": bonuses,
        "reward_cap_clamps": reward_cap_clamps,
        "ongoing_fee": ongoing_fee,
        "year1_fee": year1_fee,
    }


def compute_annual_value(card: dict, profile: dict, programs: dict,
                         merchants: dict, as_of: date) -> dict:
    """Single-card scoring (spec §4.2) — the portfolio scorer with this card as
    the only candidate."""
    buckets = build_buckets(profile, merchants)
    return score_portfolio([card], profile, programs, buckets, as_of)


# ---------------------------------------------------------------------------
# Choose-your-own-category expansion (spec §10 addendum)
# ---------------------------------------------------------------------------

def expand_choice_variants(cards: list, profile: dict) -> list:
    """Expand each choose-your-own-category card into one virtual card per
    choice option the profile actually spends in; the subset search then picks
    the best configuration per combination. Variants carry `base_id` so the
    search can keep two configurations of the same physical card out of one
    portfolio. A card whose options match no profile spend keeps its id, with
    the choice line dropped (it would earn nothing anyway)."""
    variants = []
    for card in cards:
        choice_rewards = [cr for cr in card["category_rewards"] if cr["category"] == "choice"]
        if not choice_rewards:
            variants.append(card)
            continue
        if len(choice_rewards) > 1:
            raise DataError(f"{card['id']}: {len(choice_rewards)} 'choice' rewards — "
                            "the optimizer supports at most one per card")
        reward = choice_rewards[0]
        options = (reward.get("choice") or {}).get("options") or []
        if not options:
            raise DataError(f"{card['id']}: 'choice' reward has no choice.options list")
        index = card["category_rewards"].index(reward)
        spend_cats = {c for c, v in profile["spend"].items() if v > EPS}
        live = sorted(set(options) & spend_cats)
        if not live:
            variant = copy.deepcopy(card)
            del variant["category_rewards"][index]
            variant["base_id"] = card["id"]
            variants.append(variant)
            continue
        for option in live:
            variant = copy.deepcopy(card)
            concrete = {k: v for k, v in variant["category_rewards"][index].items()
                        if k != "choice"}
            concrete["category"] = option
            concrete["_chosen"] = True
            variant["category_rewards"][index] = concrete
            variant["base_id"] = card["id"]
            variant["id"] = f"{card['id']}[{option}]"
            variant["choice_category"] = option
            variants.append(variant)
    return variants


# ---------------------------------------------------------------------------
# Filters and search (spec §6–7)
# ---------------------------------------------------------------------------

def filter_cards(cards: list, profile: dict, programs: dict) -> tuple:
    """Approval-tier filter, brand-lock-in filter, and reward-preference filter.

    Brand lock-in (plan 07 addendum): currencies with no cashback path (the
    loyalty_keys programs — airline/hotel/merchant-restricted) tie their whole
    reward value to one company. Unless the user opted in with
    user.accepts_brand_lockin, those cards are excluded outright — being
    willing to be restricted to a brand is a preference, distinct from
    confirming you already use that brand (confirmed_usage).

    Reward preference: when the user asks for concrete reward kinds (no
    'total_value'), a card survives only if its currency's redeems_for
    (data/meta/point-valuations.yaml) intersects them."""
    user_rank = TIER_ORDER.index(profile["user"]["credit_tier"])
    prefs = set(profile["user"]["reward_preferences"])
    kind_filter = prefs if "total_value" not in prefs else None
    accepts_lockin = profile["user"]["accepts_brand_lockin"]
    eligible, excluded = [], []
    for card in sorted(cards, key=lambda c: c["id"]):
        program = card["currency"]["program"]
        redeems = set(programs[program].get("redeems_for", []))
        if TIER_ORDER.index(card["approval"]["credit_tier"]) > user_rank:
            excluded.append({"id": card["id"],
                             "reason": f"requires credit tier '{card['approval']['credit_tier']}'"})
        elif not accepts_lockin and "cashback" not in redeems:
            excluded.append({"id": card["id"],
                             "reason": f"currency '{program}' locks rewards to a single "
                                       f"company — set user.accepts_brand_lockin: true "
                                       f"to consider brand-restricted cards"})
        elif kind_filter is not None and not (redeems & kind_filter):
            excluded.append({"id": card["id"],
                             "reason": f"currency '{program}' does not redeem for any of: "
                                       f"{', '.join(sorted(kind_filter))}"})
        else:
            eligible.append(card)
    return eligible, excluded


def card_warnings(card: dict, as_of: date) -> list:
    warnings = []
    if card["verification"]["confidence"] == "low":
        warnings.append("UNVERIFIED DATA — confidence: low; needs human verification against issuer terms")
    verified = date.fromisoformat(card["verification"]["last_verified_date"])
    if (as_of - verified).days > STALE_DAYS:
        warnings.append(f"stale verification — last verified {verified} (> {STALE_DAYS} days before as-of date)")
    bonus = card["signup_bonus"]
    if bonus is not None and "expires" in bonus and date.fromisoformat(bonus["expires"]) < as_of:
        warnings.append(f"signup bonus offer expired {bonus['expires']} — valued at $0")
    if card["approval"].get("notes"):
        warnings.append(f"approval: {card['approval']['notes']}")
    return warnings


def prune_dominated_variants(variants: list, profile: dict,
                             programs: dict, merchants: dict,
                             tables=None) -> tuple:
    """Exact pre-search pass (plan 02.5 §2): drop variants provably unable to
    appear in an optimal portfolio. B dominates A only when A is plain (no
    credits, no signup bonus), every live bucket A can win is covered by an
    *uncapped* B line at >= rate, B's fees are <= in both metrics, B carries no
    card-wide reward clamp, swapping A->B cannot newly out-rate any
    first_year_match card (guard g), and every sibling variant of B passes the
    same checks (rule s). Exact ties prune only the lexicographically larger id
    (rule e), so the reported rank-1 portfolio is unchanged. Profile-aware and
    time-free: rates come from build_lines under this profile, and an expired
    bonus still blocks pruning. Returns (kept, pruned) where pruned is an
    id-sorted list of {"id", "reason"} dicts.

    Transfer-gateway safety (plan 07 addendum): a variant whose cpp is
    context-dependent — transfer_gateway_required program, not
    itself a gateway — is priced here at its standalone floor, but its rates
    rise when a gateway card joins the subset, so it is never pruned. Tables
    are built with unlocked=∅ (build_lines default), which keeps every
    DOMINATOR at its minimum rates — a safe under-statement. If a
    first_year_match card were ever context-dependent its guard threshold
    would be understated, so pruning bails out entirely (none exist today:
    match cards are cash-back)."""
    buckets = build_buckets(profile, merchants)
    NEG = float("-inf")

    def context_dependent(v):
        prog = programs[v["currency"]["program"]]
        return bool(prog.get("transfer_gateway_required")
                    and not v.get("unlocks_transfers"))

    rate_tables = {}
    for v in variants:
        best_any, best_uncapped = {}, {}
        v_lines = (tables.lines[v["id"]][False] if tables is not None
                   else build_lines(v, profile, programs, buckets))
        for ln in v_lines:
            for b in ln["eligible"]:
                if buckets[b]["amount"] <= EPS:
                    continue
                r = ln["effective_rate"]
                if r > best_any.get(b, NEG):
                    best_any[b] = r
                if ln["room"] is None and r > best_uncapped.get(b, NEG):
                    best_uncapped[b] = r
        fees = v["fees"]
        rate_tables[v["id"]] = {
            "best_any": best_any, "best_uncapped": best_uncapped,
            "fee": fees["annual_fee_usd"] + membership_fee(v),
            "year1_fee": (0 if fees.get("first_year_waived") else fees["annual_fee_usd"])
                         + membership_fee(v),
            "plain": (not v["credits"] and v["signup_bonus"] is None
                      and not context_dependent(v)),
            "clamped": v.get("max_annual_rewards_usd") is not None,
            "base_id": v.get("base_id", v["id"]),
        }
    match_ids = [v["id"] for v in variants
                 if (v["signup_bonus"] or {}).get("first_year_match")]
    if any(context_dependent(v) for v in variants
           if (v["signup_bonus"] or {}).get("first_year_match")):
        return list(variants), []  # guard thresholds would be understated
    by_base = {}
    for cid, t in rate_tables.items():
        by_base.setdefault(t["base_id"], []).append(cid)

    def covers(b_id, a_id):
        """Conditions (a), (c), (d), (g) for one candidate dominator (or one of
        its siblings) b_id versus plain variant a_id."""
        A, B = rate_tables[a_id], rate_tables[b_id]
        if B["clamped"]:  # (d)
            return False
        if B["fee"] > A["fee"] + EPS or B["year1_fee"] > A["year1_fee"] + EPS:  # (c)
            return False
        for b, rate_a in A["best_any"].items():  # (a) uncapped pointwise cover
            if B["best_uncapped"].get(b, NEG) < rate_a - EPS:
                return False
        for m_id in match_ids:  # (g) match-interception guard
            if m_id in (a_id, b_id):
                continue
            for b, rate_m in rate_tables[m_id]["best_any"].items():
                if (B["best_any"].get(b, NEG) > rate_m - EPS  # B out-rates M (ties count)
                        and A["best_uncapped"].get(b, NEG) < rate_m - EPS):  # A didn't already
                    return False
        return True

    def dominates(b_id, a_id):
        A, B = rate_tables[a_id], rate_tables[b_id]
        for sib in by_base[B["base_id"]]:  # (s) — includes b_id itself
            if sib != a_id and not covers(sib, a_id):
                return False
        strict = (B["fee"] < A["fee"] - EPS or B["year1_fee"] < A["year1_fee"] - EPS
                  or any(B["best_uncapped"].get(b, NEG) > rate_a + EPS
                         for b, rate_a in A["best_any"].items()))
        return strict or b_id < a_id  # (e) exact clones: smaller id survives

    ids = sorted(rate_tables)
    pruned = []
    for a_id in ids:
        if not rate_tables[a_id]["plain"]:  # (b)
            continue
        for b_id in ids:  # ascending: first hit is the smallest dominator
            if b_id != a_id and dominates(b_id, a_id):
                pruned.append({"id": a_id, "reason": f"dominated by {b_id}"})
                break
    pruned_ids = {p["id"] for p in pruned}
    kept = [v for v in variants if v["id"] not in pruned_ids]
    return kept, pruned


def subset_budget(n_variants: int, max_cards: int) -> int:
    """Upper bound on scored subsets: sum of C(n, k) for k = 1..max_cards.
    Ignores the same-base_id exclusion (a small documented over-count)."""
    return sum(math.comb(n_variants, k) for k in range(1, max_cards + 1))


def search(variants: list, profile: dict, programs: dict,
           merchants: dict, as_of: date, tables=None) -> list:
    """Exhaustive over all subsets of eligible card variants, sizes
    1..max_cards. Two variants of the same physical card (same base_id) are
    mutually exclusive — you can only configure a choose-your-own card one way.
    Returns (cards, ongoing_net, year1_net) tuples, ranked."""
    buckets = build_buckets(profile, merchants)
    by_id = {c["id"]: c for c in variants}
    base_of = {cid: by_id[cid].get("base_id", cid) for cid in by_id}
    ids = sorted(by_id)
    results = []
    max_cards = min(profile["user"]["max_cards"], len(set(base_of.values())))
    budget = subset_budget(len(ids), max_cards)
    if budget > MAX_SCORED_SUBSETS:
        raise DataError(
            f"{len(ids)} eligible card variants at max_cards={max_cards} means "
            f"{budget:,} subsets to score, over the exhaustive-search budget "
            f"MAX_SCORED_SUBSETS = {MAX_SCORED_SUBSETS:,}; lower user.max_cards "
            "(or --max-cards) to bring the search back under budget")
    if tables is None:  # after the budget gate: no per-card work on refusal
        tables = RunTables(variants, profile, programs, buckets, as_of)
    for k in range(1, max_cards + 1):
        for combo in itertools.combinations(ids, k):
            if len({base_of[c] for c in combo}) < k:
                continue  # two configurations of the same physical card
            scored = score_portfolio([by_id[i] for i in combo], profile,
                                     programs, buckets, as_of, tables=tables)
            results.append({"cards": list(combo),
                            "ongoing_net": scored["ongoing_net"],
                            "year1_net": scored["year1_net"]})
    primary = "ongoing_net" if profile["user"]["optimize_for"] == "ongoing" else "year1_net"
    results.sort(key=lambda r: (-r[primary], -r["year1_net"], tuple(r["cards"])))
    return results


# ---------------------------------------------------------------------------
# Output contract (spec §8)
# ---------------------------------------------------------------------------

def _round2(x: float) -> float:
    return round(x + 0.0, 2)


def assemble_portfolio(entry: dict, by_id: dict, profile: dict, programs: dict,
                       buckets: dict, as_of: date, tables=None) -> dict:
    """Full detail for one ranked entry — the per-portfolio output block."""
    cards = [by_id[i] for i in entry["cards"]]
    scored = score_portfolio(cards, profile, programs, buckets, as_of,
                             tables=tables)
    per_card = {}
    for card in cards:
        cid = card["id"]
        per_card[cid] = {
            "name": card["name"],
            "assignments": [
                {"bucket": a["bucket"], "usd_assigned": _round2(a["usd_assigned"]),
                 "rate": a["rate"], "cpp": a["cpp"],
                 "usd_value": _round2(a["usd_value"]), "note": a["note"]}
                for a in scored["assignments"] if a["card_id"] == cid],
            "credits": [
                {"name": c["name"], "value": _round2(c["value"]), "note": c["note"]}
                for c in scored["credits"] if c["card_id"] == cid],
            "bonus": {"value": _round2(scored["bonuses"][cid]["value"]),
                      "note": scored["bonuses"][cid]["note"]},
            "fees": {"annual_fee_usd": card["fees"]["annual_fee_usd"],
                     "first_year_waived": bool(card["fees"].get("first_year_waived"))},
            "warnings": card_warnings(card, as_of),
        }
        _, valuation_note = effective_cpp(
            card, programs, set(profile["user"]["confirmed_usage"]),
            unlocked_programs(cards))
        if valuation_note:
            per_card[cid]["valuation_note"] = valuation_note
        if membership_fee(card):
            per_card[cid]["fees"]["membership_fee_usd"] = _round2(membership_fee(card))
            per_card[cid]["fees"]["membership_name"] = card["required_membership"]["name"]
        if cid in scored["reward_cap_clamps"]:
            per_card[cid]["reward_cap_clamp"] = _round2(scored["reward_cap_clamps"][cid])
        if "choice_category" in card:
            per_card[cid]["choice_category"] = card["choice_category"]
    return {
        "cards": entry["cards"],
        "ongoing_net": _round2(scored["ongoing_net"]),
        "year1_net": _round2(scored["year1_net"]),
        "earnings": _round2(scored["earnings"]),
        "unassigned_spend": {b: _round2(v) for b, v in scored["unassigned"].items()},
        "per_card": per_card,
    }


def run(dataset: dict, profile: dict, as_of: date, top: int) -> dict:
    """Produce the full output bundle rendered by render_text / render_json."""
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    eligible, excluded = filter_cards(dataset["cards"], profile, programs)
    expanded = expand_choice_variants(eligible, profile)
    buckets = build_buckets(profile, merchants)
    tables = RunTables(expanded, profile, programs, buckets, as_of)
    variants, pruned = prune_dominated_variants(expanded, profile,
                                                programs, merchants,
                                                tables=tables)
    ranked = search(variants, profile, programs, merchants, as_of,
                    tables=tables)

    by_id = {c["id"]: c for c in variants}
    portfolios = [assemble_portfolio(entry, by_id, profile, programs, buckets,
                                     as_of, tables=tables)
                  for entry in ranked[:top]]

    # Best portfolio per exact size 1..max_cards (plan 08): the ranked list is
    # already sorted, so the first entry of each size is that size's best. The
    # product UI shows size k only when it beats the previous shown size; the
    # bundle carries all of them so nothing is hidden.
    best_by_size = []
    seen_sizes = set()
    for entry in ranked:
        size = len(entry["cards"])
        if size in seen_sizes:
            continue
        seen_sizes.add(size)
        best_by_size.append({"size": size,
                             **assemble_portfolio(entry, by_id, profile,
                                                  programs, buckets, as_of,
                                                  tables=tables)})
    best_by_size.sort(key=lambda b: b["size"])

    return {
        "as_of": as_of.isoformat(),
        "optimize_for": profile["user"]["optimize_for"],
        "max_cards": profile["user"]["max_cards"],
        "reward_preferences": list(profile["user"]["reward_preferences"]),
        "confirmed_usage": list(profile["user"]["confirmed_usage"]),
        "accepts_brand_lockin": profile["user"]["accepts_brand_lockin"],
        "cpp_table": {p: {"floor_cpp": v["floor_cpp"],
                          "optimistic_cpp": v["optimistic_cpp"],
                          "avg_cpp": _round2(avg_cpp(v))}
                      for p, v in sorted(programs.items())},
        "policy_constants": policy_constants(),
        "cards_total": len(dataset["cards"]),
        "cards_eligible": len(eligible),
        "card_variants": len(expanded),
        "card_variants_pruned": len(pruned),
        "pruned": pruned,
        "excluded": excluded,
        "best_by_size": best_by_size,
        "portfolios": portfolios,
    }


def render_json(bundle: dict) -> str:
    return json.dumps(bundle, sort_keys=True, indent=2) + "\n"


def render_text(bundle: dict) -> str:
    out = []
    out.append(f"Credit-card portfolio optimizer — as of {bundle['as_of']}")
    out.append(f"Optimizing for: "
               f"{bundle['optimize_for']} | max cards: {bundle['max_cards']} | "
               f"rewards wanted: {', '.join(bundle['reward_preferences'])} | "
               f"brand lock-in ok: {'yes' if bundle['accepts_brand_lockin'] else 'no'}")
    out.append("Confirmed usage: "
               + (", ".join(bundle["confirmed_usage"]) or
                  "none — merchant/portal/loyalty-gated value counts $0 "
                  "(see data/meta/usage-questions.yaml)"))
    cpp = ", ".join(f"{p} {v['avg_cpp']}" for p, v in bundle["cpp_table"].items())
    out.append(f"Point valuations (avg_cpp = mean of floor and optimistic; "
               f"floor applies when a loyalty/gateway gate is unconfirmed): {cpp}")
    out.append("Policy constants: " + json.dumps(bundle["policy_constants"], sort_keys=True))
    excluded = "; ".join(f"{e['id']}: {e['reason']}" for e in bundle["excluded"]) or "none"
    out.append(f"Cards: {bundle['cards_total']} in dataset, {bundle['cards_eligible']} "
               f"eligible ({bundle['card_variants']} variants after choose-your-own-"
               f"category expansion, {bundle['card_variants_pruned']} pruned as "
               f"dominated), {len(bundle['excluded'])} excluded ({excluded})")
    if bundle["pruned"]:
        out.append("Pruned: " + "; ".join(f"{p['id']} ({p['reason']})"
                                          for p in bundle["pruned"]))
    if bundle["best_by_size"]:
        best = "; ".join(
            f"{b['size']} card{'s' if b['size'] > 1 else ''}: "
            f"{' + '.join(b['cards'])} (ongoing ${b['ongoing_net']:,.2f}, "
            f"year-1 ${b['year1_net']:,.2f})"
            for b in bundle["best_by_size"])
        out.append(f"Best by size: {best}")
    out.append("")

    for rank, p in enumerate(bundle["portfolios"], 1):
        out.append(f"#{rank}  {' + '.join(p['cards'])}")
        out.append(f"    ongoing net: ${p['ongoing_net']:,.2f}/yr   "
                   f"year-1 net: ${p['year1_net']:,.2f}")
        for cid in p["cards"]:
            d = p["per_card"][cid]
            chosen = (f" — choice category set to: {d['choice_category']}"
                      if "choice_category" in d else "")
            out.append(f"    {cid} — {d['name']}{chosen}")
            if "valuation_note" in d:
                out.append(f"      ⚠ {d['valuation_note']}")
            for a in d["assignments"]:
                note = f"   [{a['note']}]" if a["note"] else ""
                out.append(f"      earn: {a['bucket']:<16} ${a['usd_assigned']:>10,.2f} "
                           f"@ {a['rate']}x × {a['cpp']}cpp = ${a['usd_value']:,.2f}{note}")
            if "reward_cap_clamp" in d:
                out.append(f"      ⚠ card-wide reward cap (max_annual_rewards_usd): "
                           f"earnings above clamped by ${d['reward_cap_clamp']:,.2f}")
            for c in d["credits"]:
                out.append(f"      credit: {c['name']} = ${c['value']:,.2f}   [{c['note']}]")
            bonus = d["bonus"]
            out.append(f"      bonus (year 1 only): ${bonus['value']:,.2f}   [{bonus['note']}]")
            fee = d["fees"]
            waived = " (first year waived)" if fee["first_year_waived"] else ""
            out.append(f"      annual fee: ${fee['annual_fee_usd']:,.2f}{waived}")
            if "membership_fee_usd" in fee:
                out.append(f"      required membership ({fee['membership_name']}): "
                           f"-${fee['membership_fee_usd']:,.2f}/yr")
            for w in d["warnings"]:
                out.append(f"      ⚠ {w}")
        for b, v in p["unassigned_spend"].items():
            out.append(f"    ⚠ ${v:,.2f} of '{b}' spend is unassignable "
                       "(closed-loop-only portfolio) and earns $0")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors are input errors → exit 1
        self.print_usage(sys.stderr)
        print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(1)


def main(argv=None) -> int:
    parser = _Parser(description="Deterministic credit-card portfolio optimizer "
                                 "(see docs/plans/02-optimizer.md)")
    parser.add_argument("--profile", required=True, help="path to a spend-profile YAML")
    parser.add_argument("--max-cards", type=int,
                        help="override the profile's user.max_cards (1-5)")
    parser.add_argument("--rewards", metavar="KIND[,KIND...]",
                        help="override the profile's user.reward_preferences — "
                             "comma-separated from: " + ", ".join(REWARD_PREF_CHOICES))
    parser.add_argument("--confirm", metavar="KEY[,KEY...]",
                        help="override the profile's user.confirmed_usage — "
                             "comma-separated usage-questions item keys "
                             "(data/meta/usage-questions.yaml)")
    parser.add_argument("--top", type=int, default=5,
                        help="number of ranked portfolios to show (default 5)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output with sorted keys")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="the only time input: signup-bonus expiry, promo-"
                             "credit expiry, and staleness warnings (default: today)")
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset()
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(Path(args.profile), dataset)
        if args.max_cards is not None:
            profile["user"]["max_cards"] = args.max_cards
        if args.rewards is not None:
            profile["user"]["reward_preferences"] = [
                s.strip() for s in args.rewards.split(",") if s.strip()]
        if args.confirm is not None:
            profile["user"]["confirmed_usage"] = [
                s.strip() for s in args.confirm.split(",") if s.strip()]
        validate_user(profile["user"], dataset["usage_keys"])
        if args.top < 1:
            raise InputError(f"--top must be >= 1, got {args.top}")
        if args.as_of is not None:
            try:
                as_of = date.fromisoformat(args.as_of)
            except ValueError:
                raise InputError(f"--as-of must be YYYY-MM-DD, got {args.as_of!r}")
        else:
            as_of = date.today()
    except InputError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        bundle = run(dataset, profile, as_of, args.top)
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    sys.stdout.write(render_json(bundle) if args.json else render_text(bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())
