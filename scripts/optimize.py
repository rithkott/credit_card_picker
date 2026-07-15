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
# direct booking, eroding the headline multiplier). Applied to every
# portal_only line: a user is assumed to book through the portal of whatever
# card they hold, so portal rates need no questionnaire confirmation.
PORTAL_RATE_MULT = 0.75

# Categories that historically appear in rotating quarters (Freedom Flex,
# Discover it). A given category is featured roughly 1/N of the year (one
# category per quarter, uniform over the pool). Rotating is a *neutered* /
# deprecated archetype (plan 19): rather than split a category across cards
# (the featured 1/N on the rotating card, the rest elsewhere), a rotating
# reward competes for the WHOLE category at a blended annual rate —
#   blended = (1/N) * bonus_rate + (1 - 1/N) * fallback_rate
# — so the entire category is assigned to a single card. The steering rule is
# that a category is never suggested on two cards (a user won't split it
# perfectly IRL); the only allowed split is a hard earning cap. The quarterly
# spend cap is intentionally dropped here (see build_lines): honoring it would
# reintroduce a room limit and hence a split. It only binds at absurd
# single-category spend, so the blend is exact for realistic profiles.
ROTATING_ELIGIBLE = ["dining", "drugstores", "gas", "groceries",
                     "online_shopping", "streaming"]

# Always-on redemption caveat for transfer_gateway_required currencies (see
# point-valuations.yaml): the card's points redeem only at the cash floor unless
# the holder ALSO carries a gateway card (unlocks_transfers) in the same program.
# Surfaced in the results subtitle for every such card, standalone or paired, so
# a Freedom-family card never reads as if its points transfer on their own.
POINTS_GATEWAY_CAVEAT = {
    "chase_ur": "Points need a Chase Sapphire card to transfer to travel partners",
    "citi_typ": "Points need a premium Citi ThankYou card (Strata Premier / Elite) to transfer",
    "wells_fargo_rewards": "Points need the Wells Fargo Autograph Journey card to transfer",
}

TIER_ORDER = ["building", "fair", "good", "very_good", "excellent"]

# Reward kinds a user may ask for (user.reward_preferences / --rewards). Concrete
# kinds filter candidates by the program-level redeems_for classification in
# data/meta/point-valuations.yaml; 'total_value' disables the filter entirely.
# The user-facing vocabulary is deliberately just two kinds — cashback and
# points — while the registry's redeems_for taxonomy stays fine-grained
# (cashback / flights / hotels). 'points' is the umbrella for travel/transferable
# value: it expands to {flights, hotels} for filtering (see expand_reward_prefs).
REWARD_KINDS = ["cashback", "points"]
REWARD_PREF_CHOICES = REWARD_KINDS + ["total_value"]

# redeems_for tokens each user-facing reward kind covers. 'points' spans every
# travel redemption path (airline + hotel programs both redeem into it).
REWARD_KIND_REDEEMS = {"cashback": {"cashback"}, "points": {"flights", "hotels"}}


def expand_reward_prefs(prefs):
    """Map user-facing reward_preferences (cashback / points) to the redeems_for
    tokens used by point-valuations.yaml. Returns None when 'total_value' is
    present (filter disabled), else the union of covered tokens."""
    prefs = set(prefs)
    if "total_value" in prefs:
        return None
    tokens = set()
    for p in prefs:
        tokens |= REWARD_KIND_REDEEMS.get(p, set())
    return tokens

# Exhaustive search scores every subset; each score_portfolio call costs
# ~35-55 µs in pure Python. 2M subsets ≈ one to two minutes — the tolerable
# ceiling for an interactive CLI. At max_cards=3 this admits ~229 variants
# (C(229,3) ≈ 2M), matching 02-optimizer.md §6's ~200-card horizon.
MAX_SCORED_SUBSETS = 2_000_000

# Manual mode (v1.7): the user hand-picks the portfolio instead of the optimizer
# searching for it. Scores a single hand-picked subset (no combinatorial search),
# so there is no card cap — the subset-budget blowout only applies to Auto's search.

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
        # Documented formula, not a number: a rotating category is assumed
        # featured ~1/N of the year (N = len(ROTATING_ELIGIBLE)), so the
        # rotating line may earn its rate on at most 1/N of each eligible
        # bucket's spend, still capped at the annualized quarterly cap; the
        # remainder earns the fallback rate.
        "ROTATING_COVERAGE": "rotating rate applies to 1/len(ROTATING_ELIGIBLE) "
                             "of each eligible bucket's spend, capped at the "
                             "annualized quarterly cap; remainder earns fallback",
        "ROTATING_ELIGIBLE": ROTATING_ELIGIBLE,
        "TIER_ORDER": TIER_ORDER,
        "STALE_DAYS": STALE_DAYS,
        "MAX_SCORED_SUBSETS": MAX_SCORED_SUBSETS,
        # Documented formula, not a number: points are valued at the mean of
        # floor_cpp and optimistic_cpp, dropping to floor_cpp when a loyalty
        # or transfer-gateway gate is unconfirmed (plan 08).
        "CPP_MODEL": "avg = (floor_cpp + optimistic_cpp) / 2; floor when gated & unconfirmed",
        # Documented rule, not a number: categories flagged explicit_only in
        # data/meta/categories.yaml (housing = rent/mortgage) can't go on a
        # normal card without a ~3% processor fee, so they earn $0 unless a
        # card carries an explicit category reward for them (Bilt), never the
        # base rate — and they don't count toward signup-bonus or credit-unlock
        # spend feasibility (those windows measure card-payable spend).
        "EXPLICIT_ONLY_CATEGORIES": "explicit_only categories (housing) earn only "
                                    "via explicit category rewards — no base rate, "
                                    "excluded from bonus/unlock spend feasibility",
        # Documented rule, not a number: an earn_ratio reward (Bilt housing)
        # earns a multiplier that is a step function of the Everyday Spend Ratio
        # = everyday-spend-on-this-card / housing-on-this-card. A post-assignment
        # steering pass routes everyday spend onto the card up to the tier that
        # maximizes net value, then re-prices housing at that multiplier (or the
        # per-cycle points floor). earn_ratio cards are context-dependent, so
        # dominance pruning never drops them or prunes via their max tier rate.
        "EARN_RATIO_STEERING": "housing multiplier = step function of everyday/"
                               "housing ratio on the card; steering routes everyday "
                               "spend to the best-net tier, then prices at that rate "
                               "or the per-cycle points floor",
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
    # Items flagged single_fee reimburse one external fee (Global Entry / TSA
    # PreCheck): a portfolio claims the credit at most once (see score_credits).
    single_fee_keys = {key for group in usage_questions.values()
                       for key, item in (group.get("items") or {}).items()
                       if (item or {}).get("single_fee")}
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
            "usage_questions": usage_questions, "usage_keys": usage_keys,
            "single_fee_keys": single_fee_keys}


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
            "profile: user.uses_travel_portal was removed — issuer-portal use is "
            "now assumed for every held card, so portal_only rates apply "
            "automatically (discounted by PORTAL_RATE_MULT); drop the key")
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
    user["assumed_usage"] = assumed_usage(user, dataset["usage_questions"])
    # Derived, never a profile input: registry keys whose credits a portfolio
    # may claim only once (see load_dataset / score_credits).
    user["single_fee_keys"] = sorted(dataset.get("single_fee_keys") or [])

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


def assumed_usage(user: dict, usage_questions: dict) -> list:
    """Usage keys assumed usable without explicit confirmation (derived, never
    a profile input). Brand-loyalty groups in usage-questions.yaml carry
    assumed_reward_kind (airlines→flights, hotels→hotels): asking for 'points'
    (or 'total_value') declares the user takes travel value, and they're assumed
    to book whichever brand gives the best value. Assumed keys unlock usage-gated
    credits at the conservative CREDIT_CAPTURE haircut; only explicit
    confirmation (brand loyalty) unlocks loyalty-gated optimistic cpp and the
    softer CONFIRMED_CREDIT_CAPTURE."""
    redeems = expand_reward_prefs(user["reward_preferences"])  # None = total_value
    keys = set()
    for group in usage_questions.values():
        kind = (group or {}).get("assumed_reward_kind")
        if kind and (redeems is None or kind in redeems):
            keys.update(group.get("items") or {})
    return sorted(keys)


# ---------------------------------------------------------------------------
# Reward-line model and spend assignment (spec §5)
# ---------------------------------------------------------------------------

def build_buckets(profile: dict, merchants: dict, categories: dict) -> dict:
    """Partition the user's spend: one bucket per merchant carve-out, plus one
    residual bucket per category (category total minus its carve-outs).
    Buckets whose category is flagged explicit_only in categories.yaml
    (housing) carry the flag: base-rate lines skip them, so they earn only
    through an explicit category reward (see EXPLICIT_ONLY_CATEGORIES)."""
    def explicit_only(cat):
        return bool((categories.get(cat) or {}).get("explicit_only"))
    buckets = {}
    carved = {}
    for m, amount in profile["merchant_spend"].items():
        cat = merchants[m]["category"]
        buckets[m] = {"key": m, "kind": "merchant", "category": cat,
                      "amount": float(amount), "explicit_only": explicit_only(cat),
                      # Warehouse-club carve-outs (Costco): excluded from
                      # issuers' category bonus rates, and payable only on the
                      # registry's accepted card networks (see build_lines).
                      "exclude_from_category_bonus":
                          bool(merchants[m].get("exclude_from_category_bonus")),
                      "accepted_networks": merchants[m].get("accepted_networks")}
        carved[cat] = carved.get(cat, 0.0) + float(amount)
    for cat, amount in profile["spend"].items():
        buckets[cat] = {"key": cat, "kind": "category", "category": cat,
                        "amount": float(amount) - carved.get(cat, 0.0),
                        "explicit_only": explicit_only(cat)}
    return buckets


def unlocked_programs(cards: list) -> frozenset:
    """Programs whose transfer partners the portfolio can reach: a gateway card
    (unlocks_transfers) unlocks its own program for every card in the subset."""
    return frozenset(c["currency"]["program"] for c in cards
                     if c.get("unlocks_transfers"))


def gateway_names(cards: list) -> dict:
    """Program -> sorted names of gateway cards (unlocks_transfers) among
    `cards`. Names the concrete pairing (e.g. chase_ur -> Sapphire Preferred /
    Sapphire Reserve) in valuation and pairing notes."""
    out = {}
    for c in cards:
        if c.get("unlocks_transfers"):
            out.setdefault(c["currency"]["program"], set()).add(c["name"])
    return {p: sorted(names) for p, names in out.items()}


def avg_cpp(prog: dict) -> float:
    """The single engaged valuation (plan 08): the mean of the registry's
    conservative floor and its transfer-partner optimistic value — a realistic
    middle instead of a user-chosen floor|optimistic mode."""
    return (prog["floor_cpp"] + prog["optimistic_cpp"]) / 2.0


def is_cashback_only(profile: dict) -> bool:
    """True when the user asked for cashback and nothing else — cashback is a
    reward preference, points is not, and it isn't the everything-run
    (total_value). Under this mode points are only ever redeemed for cash, so
    every program is valued at its floor_cpp (see effective_cpp)."""
    prefs = profile["user"].get("reward_preferences") or []
    return "cashback" in prefs and "points" not in prefs and "total_value" not in prefs


def effective_cpp(card: dict, programs: dict, confirmed: set,
                  unlocked: frozenset = frozenset(),
                  gateways: dict = None, cashback_only: bool = False) -> tuple:
    """Context-aware cents-per-point: (cpp, note-or-None). Points are valued
    at the program's engaged average (avg_cpp) — mean of floor and optimistic —
    except when a gate mechanically limits redemption to the cash floor:
      - cashback-only: the user redeems points only for cash (is_cashback_only),
        so every program is worth its floor_cpp cash-out rate — this gate wins
        over the loyalty/transfer gates because none of that upside is reachable.
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
    if cashback_only:
        note = (None if prog["floor_cpp"] == prog["optimistic_cpp"]
                else f"cashback-only: points valued at floor {prog['floor_cpp']}cpp "
                     f"(cash redemption)")
        return prog["floor_cpp"], note
    loyalty = prog.get("loyalty_keys") or []
    if loyalty and not (set(loyalty) & confirmed):
        return prog["floor_cpp"], (
            f"points valued at floor {prog['floor_cpp']}cpp — no confirmed loyalty "
            f"to {prog.get('label', card['currency']['program'])} "
            f"(confirm one of: {', '.join(loyalty)} in user.confirmed_usage)")
    if (prog.get("transfer_gateway_required")
            and not card.get("unlocks_transfers")
            and card["currency"]["program"] not in unlocked):
        gates = (gateways or {}).get(card["currency"]["program"])
        pair_with = " or ".join(gates) if gates else "a gateway card (unlocks_transfers)"
        return prog["floor_cpp"], (
            f"points worth {prog['floor_cpp']}cpp as cash on their own — pair with "
            f"{pair_with} to unlock "
            f"{prog.get('label', card['currency']['program'])} transfer partners "
            f"(valued at {avg_cpp(prog)}cpp)")
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
    cpp, _ = effective_cpp(card, programs, confirmed, unlocked,
                           cashback_only=is_cashback_only(profile))
    closed = set(card.get("closed_loop", {}).get("merchants", []))
    lines = []

    def add(kind, key, rate, eligible, room, note="", room_key=None,
            fraction=None):
        eligible = [b for b in eligible if b in buckets]
        # Network gate: a bucket that only accepts certain card networks
        # (merchants.yaml accepted_networks, e.g. Costco = Visa-only) is
        # ineligible on every line of a card on any other network.
        eligible = [b for b in eligible
                    if not buckets[b].get("accepted_networks")
                    or card["network"] in buckets[b]["accepted_networks"]]
        if closed:
            eligible = [b for b in eligible
                        if buckets[b]["kind"] == "merchant" and b in closed]
        lines.append({"card_id": card["id"], "kind": kind, "key": key,
                      "rate": rate, "cpp": cpp,
                      "effective_rate": rate * cpp / 100.0,
                      "room": room, "room_key": room_key,
                      "eligible_fraction": fraction, "earn_ratio": None,
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
            bonus_rate = cr["rate"] if activated else cap["fallback_rate"]
            fallback_rate = cap["fallback_rate"]
            n = len(ROTATING_ELIGIBLE)
            fraction = 1.0 / n
            # Neutered/deprecated rotating (plan 19): one blended WHOLE-category
            # line, never a featured-quarter split. The category is featured
            # ~1/N of the year at the bonus rate and earns the fallback rate the
            # rest of the year, so the realistic annual blend is:
            #   blended = (1/N) * bonus_rate + (1 - 1/N) * fallback_rate
            # Emitted as an uncapped `category` line so greedy assignment routes
            # the entire category onto the single best card — no spill to a
            # second card. The quarterly cap is intentionally not modeled (a room
            # limit would reintroduce a split); it only binds at unrealistic
            # single-category spend.
            blended = fraction * bonus_rate + (1 - fraction) * fallback_rate
            eligible = [b for b, bk in buckets.items()
                        if bk["category"] in ROTATING_ELIGIBLE
                        and not bk.get("exclude_from_category_bonus")]
            note = (f"rotating (blended): featured ~1/{n} of the year at "
                    f"{bonus_rate:g}x, otherwise {fallback_rate:g}x → "
                    f"{blended:.2f}x whole-category")
            if rotation.get("requires_activation") and not activated:
                note += " (not activated → fallback rate)"
            add("category", cat, blended, eligible, None, note)
            continue

        er = cr.get("earn_ratio")
        if er is not None:
            # Variable earn on an explicit_only category (Bilt housing). Emit the
            # line at the MAX tier rate for ordering/pruning; the true multiplier
            # is resolved after assignment by steer_earn_ratio, since it depends
            # on how much everyday spend the portfolio routes onto this card. The
            # housing bucket is the only thing eligible here (explicit_only).
            eligible = [cat] if cat in buckets else []
            add("category", cat, cr["rate"], eligible, None,
                "housing — multiplier set by Everyday Spend Ratio (steering)")
            lines[-1]["earn_ratio"] = er
            continue

        rate = cr["rate"]
        notes = ["chosen category"] if cr.get("_chosen") else []
        if cr.get("portal_only"):
            # Portal use is assumed for any held card (the questionnaire no
            # longer asks); the multiplier still discounts portal price premiums.
            rate = rate * PORTAL_RATE_MULT
            notes.append(f"portal ×{PORTAL_RATE_MULT} ({card['portal']}, use assumed)")
        note = "; ".join(notes)
        eligible = [cat] if cat in buckets else []
        # Merchant carve-outs ride their category's bonus line — except buckets
        # flagged exclude_from_category_bonus (warehouse clubs): issuers exclude
        # them from the category, so they earn only via an explicit
        # merchant_rewards line or the base rate.
        eligible += [b for b, bk in buckets.items()
                     if bk["kind"] == "merchant" and bk["category"] == cat
                     and b not in merchant_line_keys
                     and not bk.get("exclude_from_category_bonus")]
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
    # explicit_only buckets (housing) never fall through to the base rate: the
    # spend isn't card-payable without a fee, so only an explicit category
    # reward (already claimed above, e.g. Bilt housing) may earn on it.
    # Buckets flagged exclude_from_category_bonus that no explicit merchant
    # line claimed get their own noted base line, so the display says why the
    # category bonus rate didn't apply.
    fallthrough = [b for b in buckets
                   if b not in claimed and not buckets[b]["explicit_only"]]
    for b in [b for b in fallthrough
              if buckets[b].get("exclude_from_category_bonus")]:
        add("base", b, card["base_rate"], [b], None,
            f"{b}: warehouse club — issuers' {buckets[b]['category']} bonus "
            f"rates don't apply (base rate)")
    add("base", "base", card["base_rate"],
        [b for b in fallthrough
         if not buckets[b].get("exclude_from_category_bonus")],
        None)
    return lines


def assign_spend(lines: list, buckets: dict) -> tuple:
    """Greedy assignment over all lines of all candidate cards, in descending
    effective USD rate, with deterministic tie-breaks (spec §5.5). Exact for the
    current structure (at most one capped wildcard per card, uncapped base lines
    guarantee coverage); beyond that it is a documented heuristic — a tiny-LP
    solver is the named future upgrade, but v1 stays stdlib + pyyaml only.
    Lines carrying eligible_fraction (rotating coverage model) may take at most
    that fraction of each bucket's original spend — the featured-quarter share —
    in addition to any room/pool limit."""
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
            if ln.get("eligible_fraction") is not None:
                # Coverage model: the line's rate applies only while the bucket's
                # category is featured (~fraction of the year), measured against
                # the bucket's original spend, not what other lines left over.
                take = min(take, ln["eligible_fraction"] * buckets[b]["amount"])
            if take <= EPS:
                continue
            remaining[b] -= take
            room_left -= take
            assignments.append({"card_id": ln["card_id"], "bucket": b,
                                "usd_assigned": take, "rate": ln["rate"],
                                "cpp": ln["cpp"], "kind": ln["kind"],
                                "usd_value": take * ln["effective_rate"],
                                "eligible_fraction": ln.get("eligible_fraction"),
                                "note": ln["note"]})
        if pool_key:
            pools[pool_key] = room_left
    unassigned = {b: amt for b, amt in sorted(remaining.items()) if amt > EPS}
    return assignments, unassigned


# ---------------------------------------------------------------------------
# Value model (spec §4)
# ---------------------------------------------------------------------------

def score_credits(cards: list, profile: dict, programs: dict,
                  as_of: date, per_card_spend: dict) -> list:
    """Value every credit across the portfolio against a shared per-category
    remaining-spend tracker, so stacked credits can never exceed the user's real
    spend. Draw order is deterministic: file order within a card, card-id order
    across the portfolio.

    Gate order per credit (plan 07): expires → usage gate → unlock_spend_usd →
    valuation. The usage gate: a credit with usage_keys is $0 unless the user
    confirmed at least one key (anyOf) in user.confirmed_usage — or the key is
    in the derived assumed_usage set (brand-loyalty groups whose reward kind is
    in reward_preferences; see assumed_usage()). Confirmed credits use the
    softer CONFIRMED_CREDIT_CAPTURE table (the questionnaire answered "do they
    use it at all"; the haircut covers residual breakage); merely-assumed
    credits and keyless credits keep the conservative CREDIT_CAPTURE.

    Credit variants beyond the classic USD statement credit:
      - unlock_spend_usd: the credit is $0 unless the spend the optimizer
        actually routes onto THIS card (per_card_spend, from the finalized
        assignments) reaches the unlock threshold — not portfolio-wide volume.
        assign_spend is greedy per-bucket and never chases unlock thresholds, so
        these credits fire only when the card wins the required spend on raw earn
        rate; otherwise the credit is surfaced as an uncounted locked perk
        (value 0 + potential_value). Same per-card rule as signup bonuses.
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

    Every result carries two figures: `value` — the capture-haircut/spend-capped
    amount that feeds ranking and the internal net (score_portfolio) — and
    `face_value`, the full annual face the card advertises. The display layer
    (assemble_portfolio) surfaces `face_value` so the user sees the headline
    number, while the optimizer keeps selecting portfolios on the realistic
    `value`. Genuinely-$0 credits (expired / no-spend / unlock-unreachable /
    single-fee loser) set face_value 0.0 too, so they still show $0.
    """
    tracker = {cat: float(v) for cat, v in profile["spend"].items()}
    confirmed = set(profile["user"]["confirmed_usage"])
    assumed = set(profile["user"].get("assumed_usage", []))
    unlocked = unlocked_programs(cards)
    cashback_only = is_cashback_only(profile)
    results = []
    for card in sorted(cards, key=lambda c: c["id"]):
        cpp, _ = effective_cpp(card, programs, confirmed, unlocked,
                               cashback_only=cashback_only)
        # unlock_spend_usd gates on the spend actually routed onto THIS card, not
        # portfolio-wide volume (see docstring + score_portfolio.per_card_spend).
        card_spend = per_card_spend.get(card["id"], 0.0)
        for credit in card["credits"]:
            if "expires" in credit and date.fromisoformat(credit["expires"]) < as_of:
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0, "face_value": 0.0,
                                "note": f"$0 — promo expired {credit['expires']}"})
                continue
            keys = credit.get("usage_keys")
            keys_confirmed = set(keys or []) & confirmed
            keys_assumed = set(keys or []) & assumed
            periods = PERIODS_PER_YEAR[credit["period"]]
            if keys and not keys_confirmed and not keys_assumed:
                # Usage-gated but the user hasn't confirmed the merchant/brand, so
                # this is worth $0 to the optimizer (value stays 0.0 — never enters
                # any total or ranking). We still surface the full annual FACE value
                # as potential_value: the frontend lists it as a perk they'd get
                # anyway and would likely use if they held the card. Face only —
                # no capture haircut. Scoped to THIS gate; the other $0 branches
                # (expired / unlock-unreachable / no-spend) omit potential_value
                # because the user genuinely would not receive them.
                if "amount_points" in credit:
                    potential = credit["amount_points"] * periods * cpp / 100.0
                else:
                    potential = credit["amount_usd"] * periods
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0, "face_value": 0.0,
                                "potential_value": round(potential, 2),
                                "note": f"$0 — requires confirmed use of one of: "
                                        f"{', '.join(keys)} (user.confirmed_usage)"})
                continue
            capture = (CONFIRMED_CREDIT_CAPTURE if keys_confirmed else CREDIT_CAPTURE)[credit["period"]]
            if keys_confirmed:
                usage_note = f"; confirmed: {', '.join(sorted(keys_confirmed))}"
            elif keys_assumed:
                usage_note = (f"; assumed usable: {', '.join(sorted(keys_assumed))} "
                              f"(reward preferences imply you'd book the best-value "
                              f"brand; confirm loyalty for fuller capture)")
            else:
                usage_note = ""
            in_kind = credit.get("kind") == "in_kind"

            unlock = credit.get("unlock_spend_usd")
            if unlock is not None and card_spend / periods < unlock - EPS:
                # Not enough spend routed onto this card to unlock it. Surface the
                # full annual face as a locked perk (potential_value, uncounted) so
                # the user still sees the benefit and its unlock condition.
                if "amount_points" in credit:
                    potential = credit["amount_points"] * periods * cpp / 100.0
                else:
                    potential = credit["amount_usd"] * periods
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0, "face_value": 0.0,
                                "potential_value": round(potential, 2),
                                "note": f"$0 — needs ${unlock:,.0f}/{credit['period']} on "
                                        f"this card (only ${card_spend:,.0f} routed here)"})
                continue
            unlock_note = f"; unlocked (${unlock:,.0f}/{credit['period']} spend)" if unlock is not None else ""

            if "amount_points" in credit:
                face = credit["amount_points"] * periods * cpp / 100.0
                value = face * capture if in_kind else face
                note = (f"{credit['amount_points'] * periods:,.0f} pts/yr × {cpp}cpp"
                        + (f" × capture {capture}" if in_kind else "")
                        + unlock_note + usage_note)
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": value, "face_value": face, "note": note})
                continue

            face = credit["amount_usd"] * periods
            cat = credit.get("category")
            if cat is None:
                if in_kind:
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face * capture, "face_value": face,
                                    "note": f"in-kind est. ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}"})
                elif keys:
                    # A confirmed merchant coupon (Oura, StubHub, Walmart+) —
                    # spendable only at that merchant, so never full face.
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face * capture, "face_value": face,
                                    "note": f"face ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}"})
                else:
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face, "face_value": face,
                                    "note": f"automatic — full face value{unlock_note}"})
                continue
            available = tracker.get(cat, 0.0)
            if available <= EPS:
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0, "face_value": 0.0,
                                "note": f"$0 — no remaining spend in '{cat}'"})
                continue
            haircut = face * capture
            value = min(haircut, available)
            tracker[cat] = available - value
            kind_label = "in-kind est." if in_kind else "face"
            note = f"{kind_label} ${face:,.2f}/yr × capture {capture}{unlock_note}{usage_note}"
            if haircut > available:
                note += f" (capped by remaining '{cat}' spend)"
            results.append({"card_id": card["id"], "name": credit["name"],
                            "value": value, "face_value": face, "note": note})
    # Once-per-portfolio fee credits (single_fee usage keys, e.g. Global Entry /
    # TSA PreCheck): the credit reimburses one external fee, so a portfolio can
    # claim it once. Every credit yields exactly one result in this same
    # deterministic (card-id, file) order, so a parallel walk recovers each
    # result's usage_keys without threading them through 8 append sites. For
    # each single-fee key, keep the highest-valued positive instance (tie-break:
    # card id asc — results are already in card-id order) and zero the rest,
    # rewriting their note; zeroing the scored results keeps display and net in
    # agreement by construction.
    single_fee = set(profile["user"].get("single_fee_keys") or [])
    if single_fee:
        keysets = [set(cr.get("usage_keys") or [])
                   for card in sorted(cards, key=lambda c: c["id"])
                   for cr in card["credits"]]
        names = {c["id"]: c["name"] for c in cards}
        for key in sorted(single_fee):
            claimants = [r for r, ks in zip(results, keysets)
                         if key in ks and r["value"] > EPS]
            if len(claimants) < 2:
                continue
            winner = max(claimants, key=lambda r: r["value"])
            for r in claimants:
                if r is winner:
                    continue
                r["value"] = 0.0
                r["face_value"] = 0.0
                r["note"] = (f"$0 — fee reimbursable once per person; counted "
                             f"on {names.get(winner['card_id'], winner['card_id'])}")
    return results


def score_bonus(card: dict, profile: dict, programs: dict, as_of: date,
                card_earnings: float = 0.0,
                unlocked: frozenset = frozenset(),
                card_spend: float = 0.0) -> dict:
    """Signup-bonus value — counted once, year-1 only. A bonus's `value` may mix
    points and usd (both summed); `tiers` add tranches whose cumulative spend
    requirements are checked with the same feasibility rule as the base;
    `first_year_match` (Discover) is valued as the card's own computed
    first-year earnings. The spend requirement is feasibility-tested against
    `card_spend` — the spend the optimizer actually routes onto this card — not
    portfolio-wide volume, so a bonus counts only if this card wins the spend to
    earn it."""
    bonus = card["signup_bonus"]
    if bonus is None:
        return {"value": 0.0, "note": "no signup bonus", "floor_value": 0.0}
    if "expires" in bonus and date.fromisoformat(bonus["expires"]) < as_of:
        return {"value": 0.0, "note": f"$0 — offer expired {bonus['expires']}",
                "floor_value": 0.0}
    if bonus.get("first_year_match"):
        # Match is valued as this card's own computed earnings (already at the
        # card's effective cpp); the worst-case earnings drop is applied to the
        # per-assignment values, so the match tracks them — no separate floor.
        return {"value": card_earnings, "floor_value": card_earnings,
                "note": f"first-year match of this card's computed earnings (${card_earnings:,.2f})"}
    # Spend-requirement feasibility measures the spend actually routed onto this
    # card (card_spend from the finalized assignments) — a bonus counts only if
    # this card wins enough spend to hit the requirement in the window.
    wm = bonus["window_months"]
    window_spend = card_spend * wm / 12.0
    if window_spend < bonus["spend_requirement_usd"] - EPS:
        req = bonus["spend_requirement_usd"]
        return {"value": 0.0,
                "note": (f"$0 — spend requirement ${req:,.0f} in {wm:g} mo "
                         f"(≈${req * 12.0 / wm:,.0f}/yr pace) unreachable by the "
                         f"${card_spend:,.0f}/yr routed onto this card"),
                "floor_value": 0.0}
    cpp, _ = effective_cpp(card, programs,
                           set(profile["user"]["confirmed_usage"]), unlocked,
                           cashback_only=is_cashback_only(profile))
    # Worst-case (cash-out) valuation of bonus points: the program's floor_cpp.
    # For cash bonuses (usd only) and fixed-value programs (floor == effective)
    # this equals the normal value, so floor_value never exceeds value.
    floor_cpp = programs.get(card["currency"]["program"], {}).get("floor_cpp", cpp)

    def usd_of(value):
        """(worth at effective cpp, worth at floor cpp, human note). The floor
        worth re-prices only the points portion; usd portions are unchanged."""
        parts, worth, floor_worth = [], 0.0, 0.0
        if "points" in value:
            worth += value["points"] * cpp / 100.0
            floor_worth += value["points"] * floor_cpp / 100.0
            parts.append(f"{value['points']:,.0f} points × {cpp}cpp")
        if "usd" in value:
            worth += float(value["usd"])
            floor_worth += float(value["usd"])
            parts.append(f"${value['usd']:,.0f} cash")
        return worth, floor_worth, " + ".join(parts)

    total, floor_total, note = usd_of(bonus["value"])
    tiers = bonus.get("tiers", [])
    reached = [t for t in tiers if window_spend >= t["spend_requirement_usd"] - EPS]
    for tier in reached:
        worth, floor_worth, desc = usd_of(tier["value"])
        total += worth
        floor_total += floor_worth
        t_req = tier["spend_requirement_usd"]
        note += (f"; +tier at ${t_req:,.0f} in {wm:g} mo "
                 f"(≈${t_req * 12.0 / wm:,.0f}/yr pace) ({desc})")
    for tier in tiers:
        if tier in reached:
            continue
        t_req = tier["spend_requirement_usd"]
        note += (f"; tier at ${t_req:,.0f} in {wm:g} mo unreachable "
                 f"(needs ≈${t_req * 12.0 / wm:,.0f}/yr on this card; "
                 f"${card_spend:,.0f}/yr routed)")
    return {"value": total, "note": note, "floor_value": floor_total}


def membership_fee(card: dict) -> float:
    """Annual cost of a required membership that exists solely for the card
    (required_membership.card_exclusive, e.g. Robinhood Gold). Memberships with
    standalone value (Costco, Prime, Sam's Club) stay unscored — the optimizer
    assumes the user already holds those."""
    rm = card.get("required_membership") or {}
    if rm.get("card_exclusive"):
        return float(rm.get("annual_cost_usd") or 0)
    return 0.0


def _tier_rate(tiers: list, ratio: float) -> float:
    """Highest earn_ratio tier rate whose min_ratio <= ratio (tiers ascending)."""
    rate = 0.0
    for t in tiers:
        if ratio >= t["min_ratio"] - EPS:
            rate = t["rate"]
        else:
            break
    return rate


def steer_earn_ratio(cards: list, lines: list, assignments: list,
                     unassigned: dict, buckets: dict, programs: dict,
                     profile: dict) -> None:
    """Resolve a Bilt-style earn_ratio housing reward (plan 05) — mutates
    `assignments` and `unassigned` in place.

    Housing is explicit_only, so its bucket is assigned only to the card's
    housing line (priced at the max tier rate by build_lines) and never competes
    with everyday buckets. The real housing multiplier is a step function of the
    Everyday Spend Ratio = (everyday spend charged to this card) / (housing on
    this card). A rational cardholder routes everyday spend onto the card until
    the next tier no longer pays for the everyday rate given up, so we:

      1. read the greedy baseline (E0 = everyday already on the card),
      2. build the cheapest-first pool of everyday dollars not yet on the card
         (each dollar's cost = what it earns now minus what it would earn here),
      3. evaluate net value at E0 and at each reachable tier threshold — the
         optimum is one of these points because housing value is a step function
         and sacrifice is increasing — and pick the best,
      4. move the chosen everyday dollars onto the card and re-price the housing
         line at the resulting multiplier (or the per-cycle points floor).

    Second-order effects of moved dollars (freeing a capped line elsewhere) are
    treated as negligible — the same documented-heuristic footing as the greedy
    assignment. Guard: with >1 earn_ratio card, only the one that actually holds
    the housing spend is steered; the other has no denominator and is a no-op."""
    er_cards = {c["id"]: c for c in cards
                if any(cr.get("earn_ratio") for cr in c["category_rewards"])}
    if not er_cards:
        return
    for cid, card in sorted(er_cards.items()):
        cr = next(cr for cr in card["category_rewards"] if cr.get("earn_ratio"))
        er = cr["earn_ratio"]
        den_cat = er["denominator_category"]
        # Housing assignment(s) for this card (the denominator bucket).
        house_as = [a for a in assignments if a["card_id"] == cid
                    and buckets[a["bucket"]]["category"] == den_cat]
        housing = sum(a["usd_assigned"] for a in house_as)
        if housing <= EPS:
            continue  # no housing on this card → nothing to resolve
        cpp = house_as[0]["cpp"]
        floor_year = er["floor_points_per_cycle"] * er["cycles_per_year"]

        def housing_value(everyday_on_card):
            mult = _tier_rate(er["tiers"], everyday_on_card / housing)
            pts = max(mult * housing, floor_year)
            return mult, pts * cpp / 100.0

        # This card's best everyday effective rate per bucket (its non-housing
        # lines), plus the winning line's display fields for moved dollars.
        my_lines = [ln for ln in lines if ln["card_id"] == cid
                    and ln["earn_ratio"] is None]
        best_line = {}
        for ln in my_lines:
            for b in ln["eligible"]:
                cur = best_line.get(b)
                if cur is None or ln["effective_rate"] > cur["effective_rate"]:
                    best_line[b] = ln

        E0 = sum(a["usd_assigned"] for a in assignments
                 if a["card_id"] == cid and not buckets[a["bucket"]]["explicit_only"])

        # Cheapest-first pool of everyday dollars NOT on this card: other cards'
        # everyday assignments and unassigned everyday spend. Each chunk carries
        # its per-dollar sacrifice = source effective rate − our rate here.
        pool = []
        for a in assignments:
            if a["card_id"] == cid or buckets[a["bucket"]]["explicit_only"]:
                continue
            b = a["bucket"]
            if b not in best_line:
                continue  # we can't earn on it at all → can't move it here
            src_eff = a["usd_value"] / a["usd_assigned"] if a["usd_assigned"] else 0.0
            here_eff = best_line[b]["effective_rate"]
            pool.append({"src": a, "bucket": b, "dollars": a["usd_assigned"],
                         "sacrifice": src_eff - here_eff})
        for b, amt in unassigned.items():
            if buckets[b]["explicit_only"] or b not in best_line or amt <= EPS:
                continue
            pool.append({"src": None, "bucket": b, "dollars": amt,
                         "sacrifice": -best_line[b]["effective_rate"]})
        pool.sort(key=lambda c: (c["sacrifice"], c["bucket"]))
        movable = sum(c["dollars"] for c in pool)

        def sacrifice_to(target_x):
            need, cost = target_x, 0.0
            for c in pool:
                if need <= EPS:
                    break
                take = min(need, c["dollars"])
                cost += take * c["sacrifice"]
                need -= take
            return cost

        base_mult, base_val = housing_value(E0)
        # Candidate everyday-on-card totals: stay put, or reach a tier threshold.
        thresholds = sorted({t["min_ratio"] * housing for t in er["tiers"]
                             if t["min_ratio"] * housing > E0 + EPS
                             and t["min_ratio"] * housing <= E0 + movable + EPS})
        best = (0.0, E0, base_mult, base_val)  # (net_delta, E, mult, value)
        for E in thresholds:
            mult, val = housing_value(E)
            net = (val - base_val) - sacrifice_to(E - E0)
            if net > best[0] + EPS:
                best = (net, E, mult, val)
        _, E_star, mult, house_val = best

        # Apply: move (E_star − E0) cheapest everyday dollars onto this card.
        need = E_star - E0
        for c in pool:
            if need <= EPS:
                break
            take = min(need, c["dollars"])
            need -= take
            src = c["src"]
            if src is not None:
                frac = take / src["usd_assigned"]
                src["usd_value"] *= (1 - frac)
                src["usd_assigned"] -= take
            else:
                unassigned[c["bucket"]] -= take
            bl = best_line[c["bucket"]]
            existing = next((a for a in assignments if a["card_id"] == cid
                             and a["bucket"] == c["bucket"] and a["kind"] == bl["kind"]),
                            None)
            add_val = take * bl["effective_rate"]
            if existing is not None:
                existing["usd_assigned"] += take
                existing["usd_value"] += add_val
            else:
                assignments.append({"card_id": cid, "bucket": c["bucket"],
                                    "usd_assigned": take, "rate": bl["rate"],
                                    "cpp": bl["cpp"], "kind": bl["kind"],
                                    "usd_value": add_val,
                                    "note": bl["note"] or "steered onto this card to lift housing rate"})
        # Re-price the housing line at the resolved multiplier. When the points
        # floor binds, express it as an effective points-per-$ so the displayed
        # rate × spend × cpp still reconciles to the value.
        ratio_pct = 100.0 * E_star / housing
        floored = mult * housing < floor_year - EPS
        total_pts = house_val * 100.0 / cpp if cpp else 0.0
        eff_rate = round(total_pts / housing, 4) if housing else 0.0
        note = (f"everyday ${E_star:,.0f} ÷ rent ${housing:,.0f} = {ratio_pct:.0f}% "
                f"→ {mult}× housing points")
        if floored:
            note += (f"; below 25% — {er['floor_points_per_cycle']:.0f} pts/cycle "
                     f"floor applies (~{eff_rate}×)")
        for a in house_as:
            share = a["usd_assigned"] / housing
            a["rate"] = eff_rate
            a["usd_value"] = house_val * share
            a["note"] = note
        # Drop any everyday assignments emptied by the move.
    assignments[:] = [a for a in assignments if a["usd_assigned"] > EPS]


def score_portfolio(cards: list, profile: dict, programs: dict,
                    buckets: dict, as_of: date) -> dict:
    """Jointly score a card subset: one shared spend assignment over all the
    subset's lines, plus credits (shared tracker), plus eligible signup bonuses
    (year-1 only), minus fees."""
    unlocked = unlocked_programs(cards)
    lines = []
    for card in cards:
        lines += build_lines(card, profile, programs, buckets, unlocked)
    assignments, unassigned = assign_spend(lines, buckets)
    # Resolve any Bilt-style earn_ratio housing reward: re-prices the housing
    # line by the Everyday Spend Ratio and may route everyday spend onto the card
    # (plan 05). No-op for portfolios without an earn_ratio card.
    steer_earn_ratio(cards, lines, assignments, unassigned, buckets, programs, profile)
    # Card-payable spend the optimizer actually routes onto each card, from the
    # finalized assignments. Spend-linked rewards (unlock_spend_usd credits,
    # signup-bonus spend requirements) gate on this per-card figure — never
    # portfolio-wide volume — so a card is credited a threshold reward only when
    # it wins the spend to earn it. explicit_only (housing) assignments are
    # excluded: rent isn't "everyday spend" for unlock/bonus purposes, matching
    # the prior card-payable-volume rule.
    per_card_spend = {card["id"]: 0.0 for card in cards}
    for a in assignments:
        if not buckets[a["bucket"]]["explicit_only"]:
            per_card_spend[a["card_id"]] += a["usd_assigned"]
    credits = score_credits(cards, profile, programs, as_of, per_card_spend)
    # Portal credits stack (v2.2.0 policy): each issuer portal's credit is
    # spendable independently, so the net counts them all. They stay bounded by
    # the shared per-category spend tracker and capture haircuts inside
    # score_credits, so stacked credits can never exceed the user's real spend.
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
    bonuses = {card["id"]: score_bonus(card, profile, programs, as_of,
                                       per_card_earnings[card["id"]], unlocked,
                                       per_card_spend[card["id"]])
               for card in cards}
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
                         merchants: dict, categories: dict, as_of: date) -> dict:
    """Single-card scoring (spec §4.2) — the portfolio scorer with this card as
    the only candidate."""
    buckets = build_buckets(profile, merchants, categories)
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
    kind_filter = expand_reward_prefs(prefs)  # None when total_value; else redeems tokens
    accepts_lockin = profile["user"]["accepts_brand_lockin"]
    eligible, excluded = [], []
    for card in sorted(cards, key=lambda c: c["id"]):
        program = card["currency"]["program"]
        redeems = set(programs[program].get("redeems_for", []))
        if card.get("availability", "active") == "discontinued":
            excluded.append({"id": card["id"],
                             "reason": "discontinued — no longer open to new applicants; "
                                       "select it in Custom mode to score a card you already hold"})
        elif TIER_ORDER.index(card["approval"]["credit_tier"]) > user_rank:
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
                                       f"{', '.join(sorted(prefs))}"})
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
    # approval.notes are curator credit_tier-inference bookkeeping ("estimated
    # from the card's positioning — NEEDS human verification"), not actionable
    # approval odds — never surfaced as a card warning (dropped at the source
    # rather than filtered in the UI, so no surface can resurrect them).
    return warnings


def prune_dominated_variants(variants: list, profile: dict,
                             programs: dict, merchants: dict,
                             categories: dict) -> tuple:
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
    buckets = build_buckets(profile, merchants, categories)
    NEG = float("-inf")

    def context_dependent(v):
        prog = programs[v["currency"]["program"]]
        # earn_ratio cards (Bilt housing) price their housing line at the max
        # tier rate here; the real value depends on the portfolio's everyday
        # assignment (steering), so — like transfer-gateway cards — never let
        # them be pruned or prune others on that inflated rate.
        if any(cr.get("earn_ratio") for cr in v["category_rewards"]):
            return True
        return bool(prog.get("transfer_gateway_required")
                    and not v.get("unlocks_transfers"))

    tables = {}
    for v in variants:
        best_any, best_uncapped = {}, {}
        for ln in build_lines(v, profile, programs, buckets):
            for b in ln["eligible"]:
                if buckets[b]["amount"] <= EPS:
                    continue
                r = ln["effective_rate"]
                if r > best_any.get(b, NEG):
                    best_any[b] = r
                if ln["room"] is None and r > best_uncapped.get(b, NEG):
                    best_uncapped[b] = r
        fees = v["fees"]
        tables[v["id"]] = {
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
    for cid, t in tables.items():
        by_base.setdefault(t["base_id"], []).append(cid)

    def covers(b_id, a_id):
        """Conditions (a), (c), (d), (g) for one candidate dominator (or one of
        its siblings) b_id versus plain variant a_id."""
        A, B = tables[a_id], tables[b_id]
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
            for b, rate_m in tables[m_id]["best_any"].items():
                if (B["best_any"].get(b, NEG) > rate_m - EPS  # B out-rates M (ties count)
                        and A["best_uncapped"].get(b, NEG) < rate_m - EPS):  # A didn't already
                    return False
        return True

    def dominates(b_id, a_id):
        A, B = tables[a_id], tables[b_id]
        for sib in by_base[B["base_id"]]:  # (s) — includes b_id itself
            if sib != a_id and not covers(sib, a_id):
                return False
        strict = (B["fee"] < A["fee"] - EPS or B["year1_fee"] < A["year1_fee"] - EPS
                  or any(B["best_uncapped"].get(b, NEG) > rate_a + EPS
                         for b, rate_a in A["best_any"].items()))
        return strict or b_id < a_id  # (e) exact clones: smaller id survives

    ids = sorted(tables)
    pruned = []
    for a_id in ids:
        if not tables[a_id]["plain"]:  # (b)
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
           merchants: dict, categories: dict, as_of: date) -> list:
    """Exhaustive over all subsets of eligible card variants, sizes
    1..max_cards. Two variants of the same physical card (same base_id) are
    mutually exclusive — you can only configure a choose-your-own card one way.
    Returns (cards, ongoing_net, year1_net) tuples, ranked."""
    buckets = build_buckets(profile, merchants, categories)
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
    for k in range(1, max_cards + 1):
        for combo in itertools.combinations(ids, k):
            if len({base_of[c] for c in combo}) < k:
                continue  # two configurations of the same physical card
            scored = score_portfolio([by_id[i] for i in combo], profile,
                                     programs, buckets, as_of)
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
                       buckets: dict, as_of: date, gateways: dict = None) -> dict:
    """Full detail for one ranked entry — the per-portfolio output block.
    `gateways` is gateway_names() over the FULL dataset, so a standalone
    Freedom Flex can name the Sapphires even when they're filtered out."""
    cards = [by_id[i] for i in entry["cards"]]
    scored = score_portfolio(cards, profile, programs, buckets, as_of)
    unlocked = unlocked_programs(cards)
    per_card = {}
    for card in cards:
        cid = card["id"]
        prog_key = card["currency"]["program"]
        prog = programs[prog_key]
        per_card[cid] = {
            "name": card["name"],
            "currency": {"kind": card["currency"]["type"], "program": prog_key,
                         "label": prog.get("label", prog_key)},
            "assignments": [
                {"bucket": a["bucket"], "usd_assigned": _round2(a["usd_assigned"]),
                 "rate": a["rate"], "cpp": a["cpp"],
                 "usd_value": _round2(a["usd_value"]), "note": a["note"],
                 # Rotating (featured-quarter) lines carry the ~1/N dilution so the
                 # UI can show the FULL eligible spend and apply ×fraction to the
                 # points/value it earns; null on every non-rotating line.
                 **({"eligible_fraction": a["eligible_fraction"]}
                    if a.get("eligible_fraction") is not None else {})}
                for a in scored["assignments"] if a["card_id"] == cid],
            # Displayed credit value is the FULL annual face (face_value), not the
            # capture-haircut value that drives ranking: the user sees the headline
            # number the card advertises, while the optimizer still selected this
            # portfolio on the realistic haircut value (score_portfolio). The note
            # spells out the capture applied internally. Genuinely-$0 credits carry
            # face_value 0.0, so the displayed total and net stay honest for them.
            "credits": [
                {"name": c["name"], "value": _round2(c["face_value"]), "note": c["note"],
                 **({"potential_value": _round2(c["potential_value"])}
                    if "potential_value" in c else {})}
                for c in scored["credits"] if c["card_id"] == cid],
            "bonus": {"value": _round2(scored["bonuses"][cid]["value"]),
                      "note": scored["bonuses"][cid]["note"],
                      # Worst-case (cash-out) valuation of any bonus points; the
                      # UI subtracts (value − floor_value) when the worst-case
                      # toggle is on. Equals value for cash/fixed-value bonuses.
                      "floor_value": _round2(scored["bonuses"][cid]["floor_value"])},
            "fees": {"annual_fee_usd": card["fees"]["annual_fee_usd"],
                     "first_year_waived": bool(card["fees"].get("first_year_waived"))},
            "warnings": card_warnings(card, as_of),
        }
        _, valuation_note = effective_cpp(
            card, programs, set(profile["user"]["confirmed_usage"]),
            unlocked, gateways, cashback_only=is_cashback_only(profile))
        # Always-on redemption caveat: a transfer-gateway card (Freedom family)
        # must show, up front, that its points need a gateway card (Sapphire) —
        # independent of whether one is currently in the scored portfolio.
        if (prog.get("transfer_gateway_required")
                and not card.get("unlocks_transfers")
                and prog_key in POINTS_GATEWAY_CAVEAT):
            per_card[cid]["points_gateway_caveat"] = POINTS_GATEWAY_CAVEAT[prog_key]
        if valuation_note:
            per_card[cid]["valuation_note"] = valuation_note
        elif (prog.get("transfer_gateway_required")
                and not card.get("unlocks_transfers")
                and prog_key in unlocked):
            # Paired direction of the gateway note: this card's points are only
            # worth avg_cpp because a gateway card sits in the same portfolio.
            partners = gateway_names(cards).get(prog_key, [])
            per_card[cid]["pairing_note"] = (
                f"points pooled with {' / '.join(partners)} — valued at "
                f"{_round2(avg_cpp(prog))}cpp (avg of {prog['floor_cpp']}cpp cash "
                f"floor and {prog['optimistic_cpp']}cpp transfer value)")
        if membership_fee(card):
            per_card[cid]["fees"]["membership_fee_usd"] = _round2(membership_fee(card))
            per_card[cid]["fees"]["membership_name"] = card["required_membership"]["name"]
        else:
            # Non-card-exclusive required membership (Costco, Sam's Club,
            # Prime): assumed already held, so its cost is disclosed but never
            # deducted from any net (see membership_fee).
            rm = card.get("required_membership") or {}
            if rm and rm.get("annual_cost_usd"):
                per_card[cid]["fees"]["assumed_membership_name"] = rm["name"]
                per_card[cid]["fees"]["assumed_membership_usd"] = _round2(
                    float(rm["annual_cost_usd"]))
        if cid in scored["reward_cap_clamps"]:
            per_card[cid]["reward_cap_clamp"] = _round2(scored["reward_cap_clamps"][cid])
        if "choice_category" in card:
            per_card[cid]["choice_category"] = card["choice_category"]
    # Displayed totals are derived from the ROUNDED display lines, so the sum
    # of what the user sees always reconciles exactly with the reported nets
    # (ranking upstream keeps the unrounded internals). Clamps and fees are
    # subtracted at their rounded/display values too.
    earnings_disp = _round2(
        sum(a["usd_value"] for c in per_card.values() for a in c["assignments"])
        - sum(c.get("reward_cap_clamp", 0.0) for c in per_card.values()))
    credits_disp = sum(cr["value"] for c in per_card.values() for cr in c["credits"])
    bonus_disp = sum(c["bonus"]["value"] for c in per_card.values())
    membership_disp = sum(c["fees"].get("membership_fee_usd", 0.0)
                          for c in per_card.values())
    ongoing_fee_disp = sum(c["fees"]["annual_fee_usd"]
                           for c in per_card.values()) + membership_disp
    year1_fee_disp = sum(0 if c["fees"]["first_year_waived"]
                         else c["fees"]["annual_fee_usd"]
                         for c in per_card.values()) + membership_disp

    # Unassignable-spend notes: name the reason when a network gate is why no
    # card in this portfolio can take a bucket (e.g. Costco is Visa-only).
    unassigned_notes = {}
    for b in scored["unassigned"]:
        nets = buckets.get(b, {}).get("accepted_networks")
        if nets and not any(c["network"] in nets for c in cards):
            label = buckets[b].get("key", b)
            unassigned_notes[b] = (
                f"{label} accepts only {'/'.join(nets)} — no card in this "
                f"portfolio is on that network")
    return {
        "cards": entry["cards"],
        "ongoing_net": _round2(earnings_disp + credits_disp - ongoing_fee_disp),
        "year1_net": _round2(earnings_disp + credits_disp + bonus_disp
                             - year1_fee_disp),
        "earnings": earnings_disp,
        "unassigned_spend": {b: _round2(v) for b, v in scored["unassigned"].items()},
        **({"unassigned_notes": unassigned_notes} if unassigned_notes else {}),
        "per_card": per_card,
    }


def run(dataset: dict, profile: dict, as_of: date, top: int) -> dict:
    """Produce the full output bundle rendered by render_text / render_json."""
    # Recompute here (parse_profile also sets it) so CLI --rewards overrides
    # applied after parsing can never leave a stale derived set.
    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]
    eligible, excluded = filter_cards(dataset["cards"], profile, programs)
    expanded = expand_choice_variants(eligible, profile)
    variants, pruned = prune_dominated_variants(expanded, profile,
                                                programs, merchants, categories)
    ranked = search(variants, profile, programs, merchants, categories, as_of)

    by_id = {c["id"]: c for c in variants}
    buckets = build_buckets(profile, merchants, categories)
    gateways = gateway_names(dataset["cards"])
    portfolios = [assemble_portfolio(entry, by_id, profile, programs, buckets,
                                     as_of, gateways)
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
                                                  gateways)})
    best_by_size.sort(key=lambda b: b["size"])

    return {
        "as_of": as_of.isoformat(),
        "optimize_for": profile["user"]["optimize_for"],
        "max_cards": profile["user"]["max_cards"],
        "reward_preferences": list(profile["user"]["reward_preferences"]),
        "confirmed_usage": list(profile["user"]["confirmed_usage"]),
        "assumed_usage": list(profile["user"]["assumed_usage"]),
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


def _best_variant_combo(ordered_bases: list, by_var_base: dict, profile: dict,
                        programs: dict, buckets: dict, as_of: date) -> list:
    """For a fixed set of physical cards, pick the single best choose-your-own
    configuration. Auto's search() optimizes the config while choosing the set;
    here the set is fixed, so we only optimize over each card's live variants.
    Scores whole combos (variants interact through points pooling) and ranks
    them exactly like search(): primary metric, then year1_net, then card ids."""
    primary = "ongoing_net" if profile["user"]["optimize_for"] == "ongoing" else "year1_net"
    groups = [by_var_base[b] for b in ordered_bases]
    scored = []
    for combo in itertools.product(*groups):
        ids = [v["id"] for v in combo]
        s = score_portfolio(list(combo), profile, programs, buckets, as_of)
        scored.append((s["ongoing_net"], s["year1_net"], ids))
    scored.sort(key=lambda r: (-(r[0] if primary == "ongoing_net" else r[1]),
                               -r[1], tuple(r[2])))
    return scored[0][2]


def evaluate(dataset: dict, profile: dict, as_of: date, card_ids: list) -> dict:
    """Manual mode (v1.7): score exactly the user-selected cards, bypassing the
    filter/prune/search that Auto mode uses to *pick* the best set. The value
    engine (assemble_portfolio) and the output bundle shape are identical to
    run(), so the web results view renders it unchanged — best_by_size just
    carries a single entry. Selection overrides every Auto filter: a manually
    chosen card is scored even if credit tier / brand-lockin / reward-preference
    filters would have excluded it in Auto mode. No card cap — the set is scored
    as-is (v1.10 removed the old 5-card manual limit)."""
    if not isinstance(card_ids, list) or not card_ids:
        raise InputError("evaluate: 'cards' must be a non-empty list of card ids")
    if any(not isinstance(c, str) for c in card_ids):
        raise InputError(f"evaluate: 'cards' must be a list of card-id strings, got {card_ids!r}")
    if len(set(card_ids)) != len(card_ids):
        raise InputError(f"evaluate: 'cards' has duplicate ids: {card_ids}")
    by_base = {c["id"]: c for c in dataset["cards"]}
    unknown = [c for c in card_ids if c not in by_base]
    if unknown:
        raise InputError(f"evaluate: unknown card id(s): {sorted(unknown)}")

    # Recompute assumed_usage here (parse_profile also sets it) so any override
    # applied after parsing can never leave a stale derived set — mirrors run().
    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]

    chosen = [by_base[c] for c in card_ids]
    variants = expand_choice_variants(chosen, profile)
    buckets = build_buckets(profile, merchants, categories)
    by_var_base = {}
    for v in variants:
        by_var_base.setdefault(v.get("base_id", v["id"]), []).append(v)
    # Preserve the user's selection order so the results card-stack is stable.
    resolved = _best_variant_combo(card_ids, by_var_base, profile, programs,
                                   buckets, as_of)

    by_id = {v["id"]: v for v in variants}
    gateways = gateway_names(dataset["cards"])
    portfolio = assemble_portfolio({"cards": resolved}, by_id, profile, programs,
                                   buckets, as_of, gateways)

    return {
        "as_of": as_of.isoformat(),
        "optimize_for": profile["user"]["optimize_for"],
        "max_cards": profile["user"]["max_cards"],
        "reward_preferences": list(profile["user"]["reward_preferences"]),
        "confirmed_usage": list(profile["user"]["confirmed_usage"]),
        "assumed_usage": list(profile["user"]["assumed_usage"]),
        "accepts_brand_lockin": profile["user"]["accepts_brand_lockin"],
        "cpp_table": {p: {"floor_cpp": v["floor_cpp"],
                          "optimistic_cpp": v["optimistic_cpp"],
                          "avg_cpp": _round2(avg_cpp(v))}
                      for p, v in sorted(programs.items())},
        "policy_constants": policy_constants(),
        "cards_total": len(dataset["cards"]),
        "cards_eligible": len(card_ids),
        "card_variants": len(variants),
        "card_variants_pruned": 0,
        "pruned": [],
        "excluded": [],
        "best_by_size": [{"size": len(resolved), **portfolio}],
        "portfolios": [portfolio],
    }


def augment(dataset: dict, profile: dict, as_of: date, held_ids: list) -> dict:
    """Best-additional-card (v1.10): given the user's held Manual-mode set, find the
    single card whose addition maximizes the active metric, then return the full
    evaluate() bundle for held + that card, with an extra `added_card` key naming the
    pick. Uses the joint scorer for every candidate, so inter-card interactions
    (points pooling, transfer-gateway unlocks, portal-credit de-dup) shape the choice
    — the same reason Auto's search scores whole subsets rather than single cards."""
    if not isinstance(held_ids, list) or not held_ids:
        raise InputError("augment: 'cards' must be a non-empty list of card ids")
    if any(not isinstance(c, str) for c in held_ids):
        raise InputError(f"augment: 'cards' must be a list of card-id strings, got {held_ids!r}")
    if len(set(held_ids)) != len(held_ids):
        raise InputError(f"augment: 'cards' has duplicate ids: {held_ids}")
    by_base = {c["id"]: c for c in dataset["cards"]}
    unknown = [c for c in held_ids if c not in by_base]
    if unknown:
        raise InputError(f"augment: unknown card id(s): {sorted(unknown)}")
    held_set = set(held_ids)

    # Mirror evaluate(): recompute assumed_usage so no override leaves a stale set.
    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]

    # The suggested card is a RECOMMENDATION, so it must honor the same candidate
    # filters Auto's search uses: credit tier, brand-lock-in opt-in, and reward
    # preference (filter_cards). Held cards were hand-picked and keep bypassing
    # the filter — evaluate() scores them regardless — but we never ADD a card the
    # user's preferences exclude (e.g. a brand-locked card when accepts_brand_lockin
    # is false, or one that doesn't redeem for the reward kinds they asked for).
    eligible, _ = filter_cards(dataset["cards"], profile, programs)
    candidates = [c["id"] for c in eligible if c["id"] not in held_set]
    if not candidates:
        raise InputError("augment: no eligible cards left to add")

    buckets = build_buckets(profile, merchants, categories)
    primary = "ongoing_net" if profile["user"]["optimize_for"] == "ongoing" else "year1_net"

    # Score held + each candidate, resolving choose-your-own variants per combo
    # exactly like evaluate(). Rank like search()/_best_variant_combo: primary metric,
    # then year1_net, then candidate id — deterministic, no ties left to chance.
    scored = []
    for cand in candidates:
        combo_bases = held_ids + [cand]
        chosen = [by_base[c] for c in combo_bases]
        variants = expand_choice_variants(chosen, profile)
        by_var_base = {}
        for v in variants:
            by_var_base.setdefault(v.get("base_id", v["id"]), []).append(v)
        resolved_ids = _best_variant_combo(combo_bases, by_var_base, profile,
                                           programs, buckets, as_of)
        by_id = {v["id"]: v for v in variants}
        s = score_portfolio([by_id[i] for i in resolved_ids], profile, programs,
                            buckets, as_of)
        metric = s["ongoing_net"] if primary == "ongoing_net" else s["year1_net"]
        scored.append((metric, s["year1_net"], cand))
    scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
    best_id = scored[0][2]

    return {**evaluate(dataset, profile, as_of, held_ids + [best_id]),
            "added_card": best_id}


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
                  "none — merchant/loyalty-gated value counts $0 "
                  "(see data/meta/usage-questions.yaml)"))
    out.append("Assumed usage (reward preferences imply best-value airline/hotel "
               "booking; loyalty still unconfirmed): "
               + (", ".join(bundle["assumed_usage"]) or "none"))
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
            if "pairing_note" in d:
                out.append(f"      ✓ {d['pairing_note']}")
            for a in d["assignments"]:
                note = f"   [{a['note']}]" if a["note"] else ""
                out.append(f"      earn: {a['bucket']:<16} ${a['usd_assigned']:>10,.2f} "
                           f"@ {a['rate']}x × {a['cpp']}cpp = ${a['usd_value']:,.2f}{note}")
            if "reward_cap_clamp" in d:
                out.append(f"      ⚠ card-wide reward cap (max_annual_rewards_usd): "
                           f"earnings above clamped by ${d['reward_cap_clamp']:,.2f}")
            for c in d["credits"]:
                face = (f"   (face ${c['potential_value']:,.2f}/yr you'd get anyway)"
                        if "potential_value" in c else "")
                out.append(f"      credit: {c['name']} = ${c['value']:,.2f}   [{c['note']}]{face}")
            bonus = d["bonus"]
            out.append(f"      bonus (year 1 only): ${bonus['value']:,.2f}   [{bonus['note']}]")
            fee = d["fees"]
            waived = " (first year waived)" if fee["first_year_waived"] else ""
            out.append(f"      annual fee: ${fee['annual_fee_usd']:,.2f}{waived}")
            if "membership_fee_usd" in fee:
                out.append(f"      required membership ({fee['membership_name']}): "
                           f"-${fee['membership_fee_usd']:,.2f}/yr")
            if "assumed_membership_usd" in fee:
                out.append(f"      assumes {fee['assumed_membership_name']} membership "
                           f"(${fee['assumed_membership_usd']:,.2f}/yr) — assumed "
                           f"already held, not deducted")
            for w in d["warnings"]:
                out.append(f"      ⚠ {w}")
        for b, v in p["unassigned_spend"].items():
            why = p.get("unassigned_notes", {}).get(
                b, "no card in this portfolio can earn on it")
            out.append(f"    ⚠ ${v:,.2f} of '{b}' spend is unassignable "
                       f"({why}) and earns $0")
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
