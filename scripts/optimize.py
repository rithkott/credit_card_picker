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
only time input, used solely for signup-bonus expiry and staleness warnings.

Usage:
  python3 scripts/optimize.py --profile PATH [--mode floor|optimistic]
      [--max-cards N] [--top N] [--json] [--as-of YYYY-MM-DD]

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
# annual credits are hard to miss.
CREDIT_CAPTURE = {"monthly": 0.5, "quarterly": 0.7, "semiannual": 0.8,
                  "annual": 0.9, "every_4_years": 0.9, "every_5_years": 0.9}

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

# Exhaustive search scores every subset; each score_portfolio call costs
# ~35-55 µs in pure Python. 2M subsets ≈ one to two minutes — the tolerable
# ceiling for an interactive CLI. At max_cards=3 this admits ~229 variants
# (C(229,3) ≈ 2M), matching 02-optimizer.md §6's ~200-card horizon.
MAX_SCORED_SUBSETS = 2_000_000

KIND_RANK = {"merchant": 0, "category": 1, "rotating": 2, "fallback": 3, "base": 4}

USER_DEFAULTS = {"valuation_mode": "floor", "max_cards": 3,
                 "optimize_for": "ongoing", "activates_rotating": True,
                 "uses_travel_portal": False}

EPS = 1e-9


class InputError(Exception):
    """Bad profile or CLI input — exit 1."""


class DataError(Exception):
    """Dataset problem or scale limit — exit 2."""


def policy_constants() -> dict:
    return {
        "CREDIT_CAPTURE": CREDIT_CAPTURE,
        "PERIODS_PER_YEAR": PERIODS_PER_YEAR,
        "CAP_PERIODS_PER_YEAR": CAP_PERIODS_PER_YEAR,
        "PORTAL_RATE_MULT": PORTAL_RATE_MULT,
        "ROTATING_OVERLAP": ROTATING_OVERLAP,
        "ROTATING_ELIGIBLE": ROTATING_ELIGIBLE,
        "TIER_ORDER": TIER_ORDER,
        "STALE_DAYS": STALE_DAYS,
        "MAX_SCORED_SUBSETS": MAX_SCORED_SUBSETS,
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
    except (OSError, yaml.YAMLError, KeyError) as e:
        raise DataError(f"cannot load data/meta/ registries: {e}")
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
            "programs": programs, "cards": cards}


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
    unknown = sorted(set(user_raw) - (set(USER_DEFAULTS) | {"credit_tier"}))
    if unknown:
        raise InputError(f"profile: user: unknown key(s): {unknown}")
    if "credit_tier" not in user_raw:
        raise InputError("profile: user.credit_tier is required")
    user = {**USER_DEFAULTS, **user_raw}
    validate_user(user)

    return {"spend": dict(sorted(spend.items())),
            "merchant_spend": dict(sorted(merchant_spend.items())),
            "user": user}


def validate_user(user: dict) -> None:
    if user["credit_tier"] not in TIER_ORDER:
        raise InputError(f"profile: user.credit_tier must be one of {TIER_ORDER}, got {user['credit_tier']!r}")
    if user["valuation_mode"] not in ("floor", "optimistic"):
        raise InputError(f"profile: user.valuation_mode must be 'floor' or 'optimistic', got {user['valuation_mode']!r}")
    mc = user["max_cards"]
    if isinstance(mc, bool) or not isinstance(mc, int) or not 1 <= mc <= 5:
        raise InputError(f"profile: user.max_cards must be an integer 1-5, got {mc!r}")
    if user["optimize_for"] not in ("ongoing", "year1"):
        raise InputError(f"profile: user.optimize_for must be 'ongoing' or 'year1', got {user['optimize_for']!r}")
    for flag in ("activates_rotating", "uses_travel_portal"):
        if not isinstance(user[flag], bool):
            raise InputError(f"profile: user.{flag} must be true or false, got {user[flag]!r}")


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


def build_lines(card: dict, profile: dict, mode: str, programs: dict, buckets: dict) -> list:
    """All reward lines of one card, with effective USD rates and bucket
    eligibility. Issuer precedence (merchant beats category beats base) is
    encoded in the eligibility sets, not chosen by the optimizer."""
    user = profile["user"]
    cpp = programs[card["currency"]["program"]][mode + "_cpp"]
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
            if not user["uses_travel_portal"]:
                continue  # dropped entirely; spend falls through to the next line
            rate = rate * PORTAL_RATE_MULT
            notes.append(f"portal ×{PORTAL_RATE_MULT}")
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


def assign_spend(lines: list, buckets: dict) -> tuple:
    """Greedy assignment over all lines of all candidate cards, in descending
    effective USD rate, with deterministic tie-breaks (spec §5.5). Exact for the
    current structure (at most one capped wildcard per card, uncapped base lines
    guarantee coverage); beyond that it is a documented heuristic — a tiny-LP
    solver is the named future upgrade, but v1 stays stdlib + pyyaml only."""
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

def score_credits(cards: list, profile: dict, mode: str, programs: dict) -> list:
    """Value every credit across the portfolio against a shared per-category
    remaining-spend tracker, so stacked credits can never exceed the user's real
    spend. Draw order is deterministic: file order within a card, card-id order
    across the portfolio.

    Credit variants beyond the classic USD statement credit:
      - unlock_spend_usd: the credit is $0 unless the user's per-period total
        spend can plausibly reach the unlock threshold (same optimistic
        feasibility rule as signup bonuses — all spend could go on this card).
      - amount_points: points-denominated drops (anniversary miles), valued via
        the card's program cpp; they don't offset spend, so no tracker draw.
      - kind: in_kind: amount_usd is a curator estimate (free nights, companion
        certificates), so the capture haircut always applies, even uncategorized.
    """
    tracker = {cat: float(v) for cat, v in profile["spend"].items()}
    total_spend = sum(profile["spend"].values())
    results = []
    for card in sorted(cards, key=lambda c: c["id"]):
        cpp = programs[card["currency"]["program"]][mode + "_cpp"]
        for credit in card["credits"]:
            periods = PERIODS_PER_YEAR[credit["period"]]
            capture = CREDIT_CAPTURE[credit["period"]]
            in_kind = credit.get("kind") == "in_kind"

            unlock = credit.get("unlock_spend_usd")
            if unlock is not None and total_spend / periods < unlock - EPS:
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0,
                                "note": f"$0 — unlock spend ${unlock:,.0f}/{credit['period']} unreachable at your volume"})
                continue
            unlock_note = f"; unlocked (${unlock:,.0f}/{credit['period']} spend)" if unlock is not None else ""

            if "amount_points" in credit:
                face = credit["amount_points"] * periods * cpp / 100.0
                value = face * capture if in_kind else face
                note = (f"{credit['amount_points'] * periods:,.0f} pts/yr × {cpp}cpp"
                        + (f" × capture {capture}" if in_kind else "") + unlock_note)
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": value, "note": note})
                continue

            face = credit["amount_usd"] * periods
            cat = credit.get("category")
            if cat is None:
                if in_kind:
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face * capture,
                                    "note": f"in-kind est. ${face:,.2f}/yr × capture {capture}{unlock_note}"})
                else:
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face,
                                    "note": f"automatic (no category) — full face value{unlock_note}"})
                continue
            available = tracker.get(cat, 0.0)
            if available <= EPS:
                results.append({"card_id": card["id"], "name": credit["name"],
                                "value": 0.0,
                                "note": f"$0 — no remaining spend in '{cat}'"})
                continue
            haircut = face * capture
            value = min(haircut, available)
            tracker[cat] = available - value
            kind_label = "in-kind est." if in_kind else "face"
            note = f"{kind_label} ${face:,.2f}/yr × capture {capture}{unlock_note}"
            if haircut > available:
                note += f" (capped by remaining '{cat}' spend)"
            results.append({"card_id": card["id"], "name": credit["name"],
                            "value": value, "note": note})
    return results


def score_bonus(card: dict, profile: dict, mode: str, programs: dict, as_of: date,
                card_earnings: float = 0.0) -> dict:
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
        return {"value": card_earnings,
                "note": f"first-year match of this card's computed earnings (${card_earnings:,.2f})"}
    total_spend = sum(profile["spend"].values())
    window_spend = total_spend * bonus["window_months"] / 12.0
    if window_spend < bonus["spend_requirement_usd"] - EPS:
        return {"value": 0.0, "note": "$0 — spend requirement unreachable at your volume"}
    cpp = programs[card["currency"]["program"]][mode + "_cpp"]

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


def score_portfolio(cards: list, profile: dict, mode: str, programs: dict,
                    buckets: dict, as_of: date) -> dict:
    """Jointly score a card subset: one shared spend assignment over all the
    subset's lines, plus credits (shared tracker), plus eligible signup bonuses
    (year-1 only), minus fees."""
    lines = []
    for card in cards:
        lines += build_lines(card, profile, mode, programs, buckets)
    assignments, unassigned = assign_spend(lines, buckets)
    credits = score_credits(cards, profile, mode, programs)
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
    bonuses = {card["id"]: score_bonus(card, profile, mode, programs, as_of,
                                       per_card_earnings[card["id"]])
               for card in cards}
    bonus_total = sum(b["value"] for b in bonuses.values())
    ongoing_fee = sum(c["fees"]["annual_fee_usd"] for c in cards)
    year1_fee = sum(0 if c["fees"].get("first_year_waived") else c["fees"]["annual_fee_usd"]
                    for c in cards)
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


def compute_annual_value(card: dict, profile: dict, mode: str, programs: dict,
                         merchants: dict, as_of: date) -> dict:
    """Single-card scoring (spec §4.2) — the portfolio scorer with this card as
    the only candidate."""
    buckets = build_buckets(profile, merchants)
    return score_portfolio([card], profile, mode, programs, buckets, as_of)


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

def filter_cards(cards: list, profile: dict) -> tuple:
    user_rank = TIER_ORDER.index(profile["user"]["credit_tier"])
    eligible, excluded = [], []
    for card in sorted(cards, key=lambda c: c["id"]):
        if TIER_ORDER.index(card["approval"]["credit_tier"]) > user_rank:
            excluded.append({"id": card["id"],
                             "reason": f"requires credit tier '{card['approval']['credit_tier']}'"})
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


def prune_dominated_variants(variants: list, profile: dict, mode: str,
                             programs: dict, merchants: dict) -> tuple:
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
    id-sorted list of {"id", "reason"} dicts."""
    buckets = build_buckets(profile, merchants)
    NEG = float("-inf")
    tables = {}
    for v in variants:
        best_any, best_uncapped = {}, {}
        for ln in build_lines(v, profile, mode, programs, buckets):
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
            "fee": fees["annual_fee_usd"],
            "year1_fee": 0 if fees.get("first_year_waived") else fees["annual_fee_usd"],
            "plain": not v["credits"] and v["signup_bonus"] is None,
            "clamped": v.get("max_annual_rewards_usd") is not None,
            "base_id": v.get("base_id", v["id"]),
        }
    match_ids = [v["id"] for v in variants
                 if (v["signup_bonus"] or {}).get("first_year_match")]
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


def search(variants: list, profile: dict, mode: str, programs: dict,
           merchants: dict, as_of: date) -> list:
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
    for k in range(1, max_cards + 1):
        for combo in itertools.combinations(ids, k):
            if len({base_of[c] for c in combo}) < k:
                continue  # two configurations of the same physical card
            scored = score_portfolio([by_id[i] for i in combo], profile, mode,
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


def run(dataset: dict, profile: dict, as_of: date, top: int) -> dict:
    """Produce the full output bundle rendered by render_text / render_json."""
    mode = profile["user"]["valuation_mode"]
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    eligible, excluded = filter_cards(dataset["cards"], profile)
    expanded = expand_choice_variants(eligible, profile)
    variants, pruned = prune_dominated_variants(expanded, profile, mode,
                                                programs, merchants)
    ranked = search(variants, profile, mode, programs, merchants, as_of)

    by_id = {c["id"]: c for c in variants}
    buckets = build_buckets(profile, merchants)
    portfolios = []
    for entry in ranked[:top]:
        cards = [by_id[i] for i in entry["cards"]]
        scored = score_portfolio(cards, profile, mode, programs, buckets, as_of)
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
            if "choice_category" in card:
                per_card[cid]["choice_category"] = card["choice_category"]
        portfolios.append({
            "cards": entry["cards"],
            "ongoing_net": _round2(scored["ongoing_net"]),
            "year1_net": _round2(scored["year1_net"]),
            "earnings": _round2(scored["earnings"]),
            "unassigned_spend": {b: _round2(v) for b, v in scored["unassigned"].items()},
            "per_card": per_card,
        })

    return {
        "as_of": as_of.isoformat(),
        "valuation_mode": mode,
        "optimize_for": profile["user"]["optimize_for"],
        "max_cards": profile["user"]["max_cards"],
        "cpp_table": {p: {"floor_cpp": v["floor_cpp"], "optimistic_cpp": v["optimistic_cpp"]}
                      for p, v in sorted(programs.items())},
        "policy_constants": policy_constants(),
        "cards_total": len(dataset["cards"]),
        "cards_eligible": len(eligible),
        "card_variants": len(expanded),
        "card_variants_pruned": len(pruned),
        "pruned": pruned,
        "excluded": excluded,
        "portfolios": portfolios,
    }


def render_json(bundle: dict) -> str:
    return json.dumps(bundle, sort_keys=True, indent=2) + "\n"


def render_text(bundle: dict) -> str:
    out = []
    out.append(f"Credit-card portfolio optimizer — as of {bundle['as_of']}")
    out.append(f"Valuation mode: {bundle['valuation_mode']} | optimizing for: "
               f"{bundle['optimize_for']} | max cards: {bundle['max_cards']}")
    cpp_key = bundle["valuation_mode"] + "_cpp"
    cpp = ", ".join(f"{p} {v[cpp_key]}" for p, v in bundle["cpp_table"].items())
    out.append(f"Point valuations ({cpp_key}): {cpp}")
    out.append("Policy constants: " + json.dumps(bundle["policy_constants"], sort_keys=True))
    excluded = "; ".join(f"{e['id']}: {e['reason']}" for e in bundle["excluded"]) or "none"
    out.append(f"Cards: {bundle['cards_total']} in dataset, {bundle['cards_eligible']} "
               f"eligible ({bundle['card_variants']} variants after choose-your-own-"
               f"category expansion, {bundle['card_variants_pruned']} pruned as "
               f"dominated), {len(bundle['excluded'])} excluded ({excluded})")
    if bundle["pruned"]:
        out.append("Pruned: " + "; ".join(f"{p['id']} ({p['reason']})"
                                          for p in bundle["pruned"]))
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
            for a in d["assignments"]:
                note = f"   [{a['note']}]" if a["note"] else ""
                out.append(f"      earn: {a['bucket']:<16} ${a['usd_assigned']:>10,.2f} "
                           f"@ {a['rate']}x × {a['cpp']}cpp = ${a['usd_value']:,.2f}{note}")
            for c in d["credits"]:
                out.append(f"      credit: {c['name']} = ${c['value']:,.2f}   [{c['note']}]")
            bonus = d["bonus"]
            out.append(f"      bonus (year 1 only): ${bonus['value']:,.2f}   [{bonus['note']}]")
            fee = d["fees"]
            waived = " (first year waived)" if fee["first_year_waived"] else ""
            out.append(f"      annual fee: ${fee['annual_fee_usd']:,.2f}{waived}")
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
    parser.add_argument("--mode", choices=["floor", "optimistic"],
                        help="override the profile's user.valuation_mode")
    parser.add_argument("--max-cards", type=int,
                        help="override the profile's user.max_cards (1-5)")
    parser.add_argument("--top", type=int, default=5,
                        help="number of ranked portfolios to show (default 5)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output with sorted keys")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="the only time input: signup-bonus expiry and "
                             "staleness warnings (default: today)")
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset()
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(Path(args.profile), dataset)
        if args.mode:
            profile["user"]["valuation_mode"] = args.mode
        if args.max_cards is not None:
            profile["user"]["max_cards"] = args.max_cards
        validate_user(profile["user"])
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
