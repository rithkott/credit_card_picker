#!/usr/bin/env python3
"""Deterministic BUSINESS credit-card portfolio optimizer (plan 22C).

The business-side sibling of scripts/optimize.py: builds every subset of
eligible business cards (sizes 1..max_cards), scores each jointly against a
company-authored spend profile, and ranks portfolios by net annual value.
The engine skeleton (buckets → lines → greedy assignment → credits → bonus →
exhaustive subset search) is adapted from the consumer optimizer; this file is
authoritative for business math and never imports from optimize.py (and the
consumer engine never imports from here).

Business-specific mechanics (docs/plans/22-business-cards-build-design.md):
  - business_approval eligibility (entity type, personal-guarantee acceptance,
    owner FICO tier when guaranteed, cash/revenue/funding thresholds, EIN),
  - issuer application rules (data/business/meta/issuer-rules.yaml): the Chase
    5/24 gate, the Amex credit-card limit with charge-lineage exemption,
    informational velocity/once-per-lifetime application notes,
  - base_rate_cap (flat-rate cards capped on ALL spend, then fallback),
  - min_transaction_usd lines and card-level large_purchase_rate priced by the
    profile's large_txn_share (fraction of spend in qualifying transactions),
  - adaptive_top_n (Amex Business Gold-style): the profile's top-n eligible
    categories by spend materialize as capped category lines at scoring time,
  - shared cap pools (cap.shared_cap_id) across category/large-purchase lines,
  - pricing models: annual_fee (+ fee_refund_spend_usd refunds) and per_seat
    fintech SaaS pricing (free tier scored $0),
  - employee-card seat fees charged on the portfolio's workhorse card,
  - transfer gateways unlockable by PERSONAL premium cards the owner already
    holds (profile personal.premium_cards_held) as well as portfolio cards,
  - pooling.program_combinable: false cards (Ink Business Premier) neither
    grant nor receive program pooling,
  - reporting: per-portfolio blended_rate, float-days summary, fee-model and
    application notes.

The optimizer is a pure function: identical inputs produce byte-identical
output. `--as-of` is the only time input.

Usage:
  python3 scripts/optimize_business.py --profile PATH
      [--max-cards N] [--rewards KIND[,KIND...]] [--top N] [--json]
      [--as-of YYYY-MM-DD]

Exit codes: 0 ok, 1 input (profile/CLI) error, 2 dataset error.
"""

import argparse
import itertools
import json
import math
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "data" / "business" / "cards"
META_DIR = ROOT / "data" / "business" / "meta"
STALE_DAYS = 183  # matches scripts/validate_business_cards.py

# ---------------------------------------------------------------------------
# Policy constants — every judgment call lives here and is echoed into every
# output, so a user can always see the assumptions behind a recommendation.
# Tables shared with the consumer engine are copied, not imported (the business
# file is authoritative for business math).
# ---------------------------------------------------------------------------

CREDIT_CAPTURE = {"monthly": 0.5, "quarterly": 0.7, "semiannual": 0.8,
                  "annual": 0.9, "every_4_years": 0.9, "every_5_years": 0.9}

CONFIRMED_CREDIT_CAPTURE = {"monthly": 0.8, "quarterly": 0.85, "semiannual": 0.9,
                            "annual": 0.95, "every_4_years": 0.95, "every_5_years": 0.95}

PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "semiannual": 2,
                    "annual": 1, "every_4_years": 0.25, "every_5_years": 0.2}

CAP_PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "annual": 1}

# Deterministic proxy for portal price premiums, same rationale as consumer.
PORTAL_RATE_MULT = 0.75

TIER_ORDER = ["good", "very_good", "excellent"]  # business_approval FICO tiers

ENTITY_TYPES = ["sole_prop", "llc", "corp"]

# Personal premium cards the owner may already hold (profile
# personal.premium_cards_held) and the program each one gateways. A held
# gateway unlocks its program's transfer partners for every business card in
# the scored portfolio — the personal half of the FULL interaction model.
PERSONAL_GATEWAYS = {
    "sapphire_preferred": "chase_ur",
    "sapphire_reserve": "chase_ur",
    "ink_preferred": "chase_ur",
    "amex_platinum": "amex_mr",
    "amex_gold": "amex_mr",
}

REWARD_KINDS = ["cashback", "points"]
REWARD_PREF_CHOICES = REWARD_KINDS + ["total_value"]
REWARD_KIND_REDEEMS = {"cashback": {"cashback"}, "points": {"flights", "hotels"}}


def expand_reward_prefs(prefs):
    """Map user-facing reward_preferences to redeems_for tokens; None when
    'total_value' is present (filter disabled)."""
    prefs = set(prefs)
    if "total_value" in prefs:
        return None
    tokens = set()
    for p in prefs:
        tokens |= REWARD_KIND_REDEEMS.get(p, set())
    return tokens


MAX_SCORED_SUBSETS = 2_000_000

KIND_RANK = {"merchant": 0, "category": 1, "adaptive": 2, "large_purchase": 3,
             "fallback": 4, "base": 5, "base_fallback": 6}

USER_DEFAULTS = {"max_cards": 3, "optimize_for": "ongoing",
                 "confirmed_usage": [], "accepts_brand_lockin": False,
                 "reward_preferences": ["total_value"]}

COMPANY_DEFAULTS = {"owner_fico_tier": None, "cash_balance_usd": 0,
                    "annual_revenue_usd": 0, "has_funding": False,
                    "employee_card_seats": 0, "large_txn_share": 0.0}

PERSONAL_DEFAULTS = {"five24_count": 0, "amex_credit_cards": 0,
                     "premium_cards_held": []}

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
        "TIER_ORDER": TIER_ORDER,
        "STALE_DAYS": STALE_DAYS,
        "MAX_SCORED_SUBSETS": MAX_SCORED_SUBSETS,
        "PERSONAL_GATEWAYS": PERSONAL_GATEWAYS,
        "CPP_MODEL": "avg = (floor_cpp + optimistic_cpp) / 2; floor when gated & unconfirmed",
        # Documented rule, not a number: lines gated on transaction size
        # (min_transaction_usd, large_purchase_rate) earn their rate on each
        # eligible bucket's spend × company.large_txn_share — the profile's
        # single global estimate of the spend fraction in qualifying
        # transactions; the remainder falls through to lower lines.
        "LARGE_TXN_MODEL": "min-transaction lines earn on bucket spend × "
                           "company.large_txn_share; remainder falls through",
        # Documented rule, not a number: adaptive_top_n cards earn their rate
        # on the profile's n highest-spend eligible categories (deterministic
        # stand-in for the issuer's own per-cycle selection), all drawing from
        # the block's one cap pool.
        "ADAPTIVE_TOP_N": "top-n = the profile's n highest-spend eligible "
                          "categories; one shared cap pool for the block",
        # Documented rule, not a number: employee seats are equipped on the
        # portfolio's workhorse card (highest assigned spend, card-id
        # tie-break); seat fees = seats × that card's employee_cards.fee_usd.
        "SEAT_PLACEMENT": "employee seats sit on the portfolio's workhorse "
                          "card (highest assigned spend); seat fees = seats × "
                          "that card's per-seat fee",
        # per_seat pricing (fintech SaaS): the free tier covers card issuance,
        # so the optimizer scores $0; paid tiers buy software, not card
        # economics, and are disclosed in fee notes only.
        "PER_SEAT_PRICING": "per_seat cards score $0 at the free tier; paid "
                            "tiers are disclosure only",
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_yaml(path: Path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_dataset() -> dict:
    """Load business registries and all business card files. Assumes the
    dataset already passes scripts/validate_business_cards.py."""
    try:
        categories = load_yaml(META_DIR / "categories.yaml")["categories"]
        merchants = load_yaml(META_DIR / "merchants.yaml")["merchants"]
        programs = load_yaml(META_DIR / "point-valuations.yaml")["programs"]
        usage_questions = load_yaml(META_DIR / "usage-questions.yaml")["groups"]
        issuer_rules = load_yaml(META_DIR / "issuer-rules.yaml")["issuers"]
    except (OSError, yaml.YAMLError, KeyError) as e:
        raise DataError(f"cannot load data/business/meta/ registries: {e}")
    usage_keys = {key for group in usage_questions.values()
                  for key in (group.get("items") or {})}
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
            "single_fee_keys": single_fee_keys, "issuer_rules": issuer_rules}


def load_profile(path: Path, dataset: dict) -> dict:
    try:
        raw = load_yaml(path)
    except OSError as e:
        raise InputError(f"cannot read profile: {e}")
    except yaml.YAMLError as e:
        raise InputError(f"profile is not valid YAML: {e}")
    return parse_business_profile(raw, dataset)


def _require_number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise InputError(f"profile: {what} must be a number >= 0, got {value!r}")


def _require_int(value, what, lo=0, hi=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < lo \
            or (hi is not None and value > hi):
        rng = f"{lo}-{hi}" if hi is not None else f">= {lo}"
        raise InputError(f"profile: {what} must be an integer {rng}, got {value!r}")


def _require_bool(value, what):
    if not isinstance(value, bool):
        raise InputError(f"profile: {what} must be true or false, got {value!r}")


def parse_business_profile(raw, dataset: dict) -> dict:
    """Validate a raw business profile mapping. Raises InputError on any
    violation. Contract (plan 22 §profile):

        spend:      {<business_category>: annual_usd}   (required, non-empty)
        merchant_spend: {<merchant>: annual_usd}        (optional carve-outs)
        company:    {entity_type, accepts_personal_guarantee, owner_fico_tier,
                     has_ein, cash_balance_usd, annual_revenue_usd, has_funding,
                     employee_card_seats, large_txn_share}
        personal:   {five24_count, amex_credit_cards, premium_cards_held}
        user:       {max_cards, optimize_for, reward_preferences,
                     accepts_brand_lockin, confirmed_usage}
        exclude_cards: [...]
    """
    if not isinstance(raw, dict):
        raise InputError("profile must be a YAML mapping")
    unknown = sorted(set(raw) - {"spend", "merchant_spend", "company",
                                 "personal", "user", "exclude_cards"})
    if unknown:
        raise InputError(f"profile: unknown top-level key(s): {unknown}")

    exclude_cards = raw.get("exclude_cards") or []
    if (not isinstance(exclude_cards, list)
            or any(not isinstance(c, str) for c in exclude_cards)
            or len(set(exclude_cards)) != len(exclude_cards)):
        raise InputError(
            f"profile: exclude_cards must be a list of unique card-id strings, "
            f"got {exclude_cards!r}")
    known_ids = {c["id"] for c in dataset["cards"]}
    bad = sorted(set(exclude_cards) - known_ids)
    if bad:
        raise InputError(f"profile: exclude_cards: unknown card id(s): {bad}")

    spend = raw.get("spend")
    if not isinstance(spend, dict) or not spend:
        raise InputError("profile: 'spend' must be a non-empty mapping of "
                         "category: annual USD")
    categories = dataset["categories"]
    for cat, amount in spend.items():
        if cat not in categories:
            raise InputError(f"profile: spend: unknown category '{cat}' "
                             f"(see data/business/meta/categories.yaml)")
        _require_number(amount, f"spend[{cat}]")

    merchant_spend = raw.get("merchant_spend") or {}
    if not isinstance(merchant_spend, dict):
        raise InputError("profile: 'merchant_spend' must be a mapping of merchant: annual USD")
    merchants = dataset["merchants"]
    carved = {}
    for m, amount in merchant_spend.items():
        if m not in merchants:
            raise InputError(f"profile: merchant_spend: unknown merchant '{m}' "
                             f"(see data/business/meta/merchants.yaml)")
        _require_number(amount, f"merchant_spend[{m}]")
        cat = merchants[m]["category"]
        carved[cat] = carved.get(cat, 0) + amount
    for cat, total in sorted(carved.items()):
        if total > spend.get(cat, 0) + EPS:
            raise InputError(
                f"profile: merchant carve-outs for category '{cat}' total ${total:,.2f}, "
                f"exceeding spend[{cat}] = ${spend.get(cat, 0):,.2f} — carve-outs are "
                f"sub-buckets of their category, never additive")

    company_raw = raw.get("company")
    if not isinstance(company_raw, dict):
        raise InputError("profile: 'company' must be a mapping and include "
                         "entity_type and accepts_personal_guarantee")
    unknown = sorted(set(company_raw)
                     - (set(COMPANY_DEFAULTS)
                        | {"entity_type", "accepts_personal_guarantee", "has_ein"}))
    if unknown:
        raise InputError(f"profile: company: unknown key(s): {unknown}")
    for req in ("entity_type", "accepts_personal_guarantee"):
        if req not in company_raw:
            raise InputError(f"profile: company.{req} is required")
    company = {**COMPANY_DEFAULTS, **company_raw}
    if company["entity_type"] not in ENTITY_TYPES:
        raise InputError(f"profile: company.entity_type must be one of "
                         f"{ENTITY_TYPES}, got {company['entity_type']!r}")
    _require_bool(company["accepts_personal_guarantee"],
                  "company.accepts_personal_guarantee")
    # EIN default: registered entities have one; sole props usually apply on
    # SSN alone. Overridable (sole props may hold an EIN).
    if "has_ein" not in company_raw:
        company["has_ein"] = company["entity_type"] in ("llc", "corp")
    _require_bool(company["has_ein"], "company.has_ein")
    tier = company["owner_fico_tier"]
    if company["accepts_personal_guarantee"]:
        if tier not in TIER_ORDER:
            raise InputError(
                f"profile: company.owner_fico_tier must be one of {TIER_ORDER} "
                f"when accepts_personal_guarantee is true, got {tier!r}")
    elif tier is not None and tier not in TIER_ORDER:
        raise InputError(f"profile: company.owner_fico_tier must be one of "
                         f"{TIER_ORDER} or null, got {tier!r}")
    _require_number(company["cash_balance_usd"], "company.cash_balance_usd")
    _require_number(company["annual_revenue_usd"], "company.annual_revenue_usd")
    _require_bool(company["has_funding"], "company.has_funding")
    _require_int(company["employee_card_seats"], "company.employee_card_seats",
                 lo=0, hi=999)
    lts = company["large_txn_share"]
    if isinstance(lts, bool) or not isinstance(lts, (int, float)) or not 0 <= lts <= 1:
        raise InputError(f"profile: company.large_txn_share must be a number "
                         f"0-1 (the fraction of spend in qualifying large "
                         f"transactions), got {lts!r}")
    company["large_txn_share"] = float(lts)

    personal_raw = raw.get("personal") or {}
    if not isinstance(personal_raw, dict):
        raise InputError("profile: 'personal' must be a mapping")
    unknown = sorted(set(personal_raw) - set(PERSONAL_DEFAULTS))
    if unknown:
        raise InputError(f"profile: personal: unknown key(s): {unknown}")
    personal = {**PERSONAL_DEFAULTS, **personal_raw}
    _require_int(personal["five24_count"], "personal.five24_count", lo=0, hi=99)
    _require_int(personal["amex_credit_cards"], "personal.amex_credit_cards",
                 lo=0, hi=99)
    held = personal["premium_cards_held"]
    if (not isinstance(held, list)
            or any(not isinstance(k, str) for k in held)
            or len(set(held)) != len(held)):
        raise InputError(
            f"profile: personal.premium_cards_held must be a list of unique "
            f"values from {sorted(PERSONAL_GATEWAYS)}, got {held!r}")
    bad = sorted(set(held) - set(PERSONAL_GATEWAYS))
    if bad:
        raise InputError(
            f"profile: personal.premium_cards_held: unknown card(s) {bad} — "
            f"valid values: {sorted(PERSONAL_GATEWAYS)}")
    personal["premium_cards_held"] = sorted(held)

    user_raw = raw.get("user") or {}
    if not isinstance(user_raw, dict):
        raise InputError("profile: 'user' must be a mapping")
    unknown = sorted(set(user_raw) - set(USER_DEFAULTS))
    if unknown:
        raise InputError(f"profile: user: unknown key(s): {unknown}")
    user = {**USER_DEFAULTS, **user_raw}
    validate_user(user, dataset["usage_keys"])
    user["assumed_usage"] = assumed_usage(user, dataset["usage_questions"])
    user["single_fee_keys"] = sorted(dataset.get("single_fee_keys") or [])

    return {"spend": dict(sorted(spend.items())),
            "merchant_spend": dict(sorted(merchant_spend.items())),
            "company": company,
            "personal": personal,
            "user": user,
            "exclude_cards": sorted(exclude_cards)}


def validate_user(user: dict, usage_keys: set) -> None:
    mc = user["max_cards"]
    if isinstance(mc, bool) or not isinstance(mc, int) or not 1 <= mc <= 5:
        raise InputError(f"profile: user.max_cards must be an integer 1-5, got {mc!r}")
    if user["optimize_for"] not in ("ongoing", "year1"):
        raise InputError(f"profile: user.optimize_for must be 'ongoing' or "
                         f"'year1', got {user['optimize_for']!r}")
    _require_bool(user["accepts_brand_lockin"], "user.accepts_brand_lockin")
    confirmed = user["confirmed_usage"]
    if (not isinstance(confirmed, list)
            or any(not isinstance(k, str) for k in confirmed)
            or len(set(confirmed)) != len(confirmed)):
        raise InputError(
            f"profile: user.confirmed_usage must be a list of unique "
            f"usage-question item keys "
            f"(see data/business/meta/usage-questions.yaml), got {confirmed!r}")
    bad = sorted(set(confirmed) - usage_keys)
    if bad:
        raise InputError(
            f"profile: user.confirmed_usage: unknown key(s) {bad} — valid keys "
            f"are the items of data/business/meta/usage-questions.yaml")
    user["confirmed_usage"] = sorted(confirmed)
    prefs = user["reward_preferences"]
    if (not isinstance(prefs, list) or not prefs
            or any(p not in REWARD_PREF_CHOICES for p in prefs)
            or len(set(prefs)) != len(prefs)):
        raise InputError(
            f"profile: user.reward_preferences must be a non-empty list of "
            f"unique values from {REWARD_PREF_CHOICES}, got {prefs!r}")


def assumed_usage(user: dict, usage_questions: dict) -> list:
    """Usage keys assumed usable without explicit confirmation — same
    brand-loyalty rule as the consumer engine: a group carrying
    assumed_reward_kind (airlines→flights, hotels→hotels) is assumed usable
    when the user's reward preferences cover that kind."""
    redeems = expand_reward_prefs(user["reward_preferences"])
    keys = set()
    for group in usage_questions.values():
        kind = (group or {}).get("assumed_reward_kind")
        if kind and (redeems is None or kind in redeems):
            keys.update(group.get("items") or {})
    return sorted(keys)


# ---------------------------------------------------------------------------
# Reward-line model and spend assignment
# ---------------------------------------------------------------------------

def build_buckets(profile: dict, merchants: dict, categories: dict) -> dict:
    """Partition company spend: one bucket per merchant carve-out plus one
    residual bucket per category. The business enum has no explicit_only or
    pseudo categories — every bucket is ordinary card-payable spend."""
    buckets = {}
    carved = {}
    for m, amount in profile["merchant_spend"].items():
        cat = merchants[m]["category"]
        buckets[m] = {"key": m, "kind": "merchant", "category": cat,
                      "amount": float(amount),
                      "exclude_from_category_bonus":
                          bool(merchants[m].get("exclude_from_category_bonus")),
                      "accepted_networks": merchants[m].get("accepted_networks")}
        carved[cat] = carved.get(cat, 0.0) + float(amount)
    for cat, amount in profile["spend"].items():
        buckets[cat] = {"key": cat, "kind": "category", "category": cat,
                        "amount": float(amount) - carved.get(cat, 0.0)}
    return buckets


def combinable(card: dict) -> bool:
    """False for cards that break their program's pooling (Ink Business
    Premier): they neither grant nor receive program pooling/transfers."""
    pooling = card.get("pooling")
    return pooling is None or pooling.get("program_combinable", True)


def unlocked_programs(cards: list, profile: dict) -> frozenset:
    """Programs whose transfer partners the portfolio can reach: a business
    gateway card (unlocks_transfers) in the subset, or a PERSONAL premium card
    the owner already holds (personal.premium_cards_held). Pooling-broken
    cards never grant."""
    unlocked = {c["currency"]["program"] for c in cards
                if c.get("unlocks_transfers") and combinable(c)}
    for held in profile["personal"]["premium_cards_held"]:
        unlocked.add(PERSONAL_GATEWAYS[held])
    return frozenset(unlocked)


def gateway_names(cards: list, profile: dict) -> dict:
    """Program -> sorted human names of available gateways (business cards +
    held personal premium cards) for pairing/valuation notes."""
    out = {}
    for c in cards:
        if c.get("unlocks_transfers") and combinable(c):
            out.setdefault(c["currency"]["program"], set()).add(c["name"])
    labels = {"sapphire_preferred": "Chase Sapphire Preferred (personal)",
              "sapphire_reserve": "Chase Sapphire Reserve (personal)",
              "ink_preferred": "Ink Business Preferred (already held)",
              "amex_platinum": "Amex Platinum (personal)",
              "amex_gold": "Amex Gold (personal)"}
    for held in profile["personal"]["premium_cards_held"]:
        out.setdefault(PERSONAL_GATEWAYS[held], set()).add(labels[held])
    return {p: sorted(names) for p, names in out.items()}


def avg_cpp(prog: dict) -> float:
    return (prog["floor_cpp"] + prog["optimistic_cpp"]) / 2.0


def is_cashback_only(profile: dict) -> bool:
    prefs = profile["user"].get("reward_preferences") or []
    return "cashback" in prefs and "points" not in prefs and "total_value" not in prefs


def effective_cpp(card: dict, programs: dict, confirmed: set,
                  unlocked: frozenset = frozenset(),
                  gateways: dict = None, cashback_only: bool = False) -> tuple:
    """Context-aware cents-per-point: (cpp, note-or-None). Same valuation
    model as the consumer engine, with one business addition: a pooling-broken
    card (program_combinable false) is always priced at its floor — its points
    can't reach the program's transfer partners no matter what else is held."""
    prog = programs[card["currency"]["program"]]
    if cashback_only:
        note = (None if prog["floor_cpp"] == prog["optimistic_cpp"]
                else f"cashback-only: points valued at floor {prog['floor_cpp']}cpp "
                     f"(cash redemption)")
        return prog["floor_cpp"], note
    if not combinable(card):
        note = (None if prog["floor_cpp"] == prog["optimistic_cpp"]
                else f"points valued at floor {prog['floor_cpp']}cpp — this card's "
                     f"rewards cannot combine with other "
                     f"{prog.get('label', card['currency']['program'])} cards or "
                     f"transfer to partners")
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


def adaptive_categories(card: dict, profile: dict) -> list:
    """Deterministic stand-in for the issuer's own top-n selection: the
    profile's n highest-spend eligible categories (spend desc, category-key
    tie-break). Categories with zero profile spend never enter."""
    block = card.get("adaptive_top_n")
    if not block:
        return []
    spend = profile["spend"]
    live = [(c, spend.get(c, 0.0)) for c in block["eligible_categories"]
            if spend.get(c, 0.0) > EPS]
    live.sort(key=lambda t: (-t[1], t[0]))
    return [c for c, _ in live[:block["n"]]]


def build_lines(card: dict, profile: dict, programs: dict, buckets: dict,
                unlocked: frozenset = frozenset()) -> list:
    """All reward lines of one card, with effective USD rates and bucket
    eligibility. Business mechanics vs the consumer builder: min_transaction
    lines and large_purchase_rate take at most large_txn_share of each
    bucket's original spend (eligible_fraction); adaptive_top_n materializes
    the profile's top-n categories into one shared pool; base_rate_cap emits a
    capped base line plus an uncapped base fallback."""
    user = profile["user"]
    confirmed = set(user["confirmed_usage"])
    cpp, _ = effective_cpp(card, programs, confirmed, unlocked,
                           cashback_only=is_cashback_only(profile))
    large_share = profile["company"]["large_txn_share"]
    lines = []

    def add(kind, key, rate, eligible, room, note="", room_key=None,
            fraction=None):
        eligible = [b for b in eligible if b in buckets]
        eligible = [b for b in eligible
                    if not buckets[b].get("accepted_networks")
                    or card["network"] in buckets[b]["accepted_networks"]]
        lines.append({"card_id": card["id"], "kind": kind, "key": key,
                      "rate": rate, "cpp": cpp,
                      "effective_rate": rate * cpp / 100.0,
                      "room": room, "room_key": room_key,
                      "eligible_fraction": fraction,
                      "eligible": sorted(eligible), "note": note})

    def cap_room(cap, default_pool=None):
        room = cap["max_spend_usd"] * CAP_PERIODS_PER_YEAR[cap["period"]]
        shared = cap.get("shared_cap_id") or default_pool
        room_key = f"{card['id']}|{shared}" if shared else None
        note = f"capped at ${room:,.0f}/yr" + (f" (shared pool '{shared}')" if shared else "")
        return room, room_key, note

    def min_txn_note(mt):
        return (f"only on purchases ≥ ${mt:,.0f} — assumed "
                f"{large_share:.0%} of this spend qualifies "
                f"(company.large_txn_share)")

    merchant_line_keys = {mr["merchant"] for mr in card["merchant_rewards"]}
    for mr in card["merchant_rewards"]:
        cap = mr.get("cap")
        mt = mr.get("min_transaction_usd")
        fraction = large_share if mt is not None else None
        notes = [min_txn_note(mt)] if mt is not None else []
        if cap:
            room, room_key, cap_note = cap_room(cap)
            notes.append(cap_note)
            add("merchant", mr["merchant"], mr["rate"], [mr["merchant"]], room,
                "; ".join(notes), room_key, fraction)
            add("fallback", mr["merchant"], cap["fallback_rate"], [mr["merchant"]],
                None, "above-cap fallback")
        else:
            add("merchant", mr["merchant"], mr["rate"], [mr["merchant"]], None,
                "; ".join(notes), None, fraction)

    for cr in card["category_rewards"]:
        cat = cr["category"]
        rate = cr["rate"]
        notes = []
        mt = cr.get("min_transaction_usd")
        fraction = large_share if mt is not None else None
        if mt is not None:
            notes.append(min_txn_note(mt))
        if cr.get("portal_only"):
            rate = rate * PORTAL_RATE_MULT
            notes.append(f"portal ×{PORTAL_RATE_MULT} ({card['portal']}, use assumed)")
        eligible = [cat] if cat in buckets else []
        eligible += [b for b, bk in buckets.items()
                     if bk["kind"] == "merchant" and bk["category"] == cat
                     and b not in merchant_line_keys
                     and not bk.get("exclude_from_category_bonus")]
        cap = cr.get("cap")
        if cap:
            room, room_key, cap_note = cap_room(cap)
            notes.append(cap_note)
            add("category", cat, rate, eligible, room, "; ".join(notes),
                room_key, fraction)
            add("fallback", cat, cap["fallback_rate"], eligible, None,
                "above-cap fallback")
        else:
            add("category", cat, rate, eligible, None, "; ".join(notes),
                None, fraction)

    # Adaptive top-n (Amex Business Gold / Hyatt Business / US Bank Leverage):
    # materialize the profile's top-n eligible categories as category lines
    # drawing from the block's ONE cap pool.
    block = card.get("adaptive_top_n")
    if block:
        chosen = adaptive_categories(card, profile)
        room, room_key, cap_note = cap_room(block["cap"], default_pool="adaptive_top_n")
        for cat in chosen:
            eligible = [cat] if cat in buckets else []
            eligible += [b for b, bk in buckets.items()
                         if bk["kind"] == "merchant" and bk["category"] == cat
                         and b not in merchant_line_keys
                         and not bk.get("exclude_from_category_bonus")]
            add("adaptive", cat, block["rate"], eligible, room,
                f"top-{block['n']} category (your #{chosen.index(cat) + 1} "
                f"eligible spend); {cap_note}", room_key)
        if chosen and block["cap"]["fallback_rate"] > 0:
            for cat in chosen:
                eligible = [cat] if cat in buckets else []
                add("fallback", cat, block["cap"]["fallback_rate"], eligible,
                    None, "above-cap fallback")

    # Card-level large-purchase rate (category-agnostic): earns on every
    # bucket's spend × large_txn_share, optionally sharing a pool with
    # category lines (Amex Business Platinum's $2M pool).
    lp = card.get("large_purchase_rate")
    if lp and large_share > EPS:
        cap = lp.get("cap")
        note = min_txn_note(lp["min_transaction_usd"])
        all_buckets = sorted(buckets)
        if cap:
            room, room_key, cap_note = cap_room(cap)
            add("large_purchase", "large_purchase", lp["rate"], all_buckets,
                room, f"{note}; {cap_note}", room_key, large_share)
        else:
            add("large_purchase", "large_purchase", lp["rate"], all_buckets,
                None, note, None, large_share)

    claimed = set()
    for ln in lines:
        claimed.update(ln["eligible"])
    fallthrough = sorted(buckets)
    # The base rate is eligible for EVERY bucket (unlike the consumer builder's
    # fallthrough-only base line): min-transaction and adaptive lines cover
    # only a fraction/subset, so the base line must be able to absorb the rest.
    brc = card.get("base_rate_cap")
    if brc:
        room = brc["max_spend_usd"] * CAP_PERIODS_PER_YEAR[brc["period"]]
        add("base", "base", card["base_rate"], fallthrough, room,
            f"base rate capped at ${room:,.0f}/yr, then "
            f"{brc['fallback_rate']:g}x", f"{card['id']}|base_rate_cap")
        add("base_fallback", "base", brc["fallback_rate"], fallthrough, None,
            "above-cap base fallback")
    else:
        add("base", "base", card["base_rate"], fallthrough, None)
    return lines


def assign_spend(lines: list, buckets: dict) -> tuple:
    """Greedy assignment over all lines of all candidate cards, in descending
    effective USD rate, deterministic tie-breaks — the consumer engine's
    documented heuristic, with the eligible_fraction mechanism reused for
    min-transaction lines (a line may take at most fraction × the bucket's
    original spend)."""
    remaining = {b: bk["amount"] for b, bk in buckets.items()}
    order = sorted(lines, key=lambda ln: (-ln["effective_rate"], ln["card_id"],
                                          KIND_RANK[ln["kind"]], ln["key"]))
    pools = {}
    for ln in order:
        if ln["room"] is not None and ln.get("room_key"):
            pools.setdefault(ln["room_key"], ln["room"])
    # Fraction lines (min-transaction / large-purchase) draw from a per-bucket
    # qualifying-transaction budget: at most large_txn_share of each bucket's
    # ORIGINAL spend is in qualifying transactions, shared across every
    # fraction line that touches the bucket.
    fraction_budget = {}
    for ln in order:
        if ln.get("eligible_fraction") is not None:
            for b in ln["eligible"]:
                fraction_budget.setdefault(
                    b, ln["eligible_fraction"] * buckets[b]["amount"])
    assignments = []
    for i, ln in enumerate(order):
        eligible = [b for b in ln["eligible"] if remaining[b] > EPS]
        if not eligible:
            continue
        if ln["room"] is not None and len(eligible) > 1:
            later = order[i + 1:]

            def best_alternative(b):
                return max((l2["effective_rate"] for l2 in later
                            if b in l2["eligible"]), default=0.0)
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
                take = min(take, fraction_budget.get(b, 0.0))
            if take <= EPS:
                continue
            remaining[b] -= take
            room_left -= take
            if ln.get("eligible_fraction") is not None:
                fraction_budget[b] -= take
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
# Value model
# ---------------------------------------------------------------------------

def score_credits(cards: list, profile: dict, programs: dict,
                  as_of: date, per_card_spend: dict,
                  unlocked: frozenset) -> list:
    """Value every credit across the portfolio — same gate order, capture
    tables, tracker, and single-fee de-dup as the consumer engine."""
    tracker = {cat: float(v) for cat, v in profile["spend"].items()}
    confirmed = set(profile["user"]["confirmed_usage"])
    assumed = set(profile["user"].get("assumed_usage", []))
    cashback_only = is_cashback_only(profile)
    results = []
    for card in sorted(cards, key=lambda c: c["id"]):
        cpp, _ = effective_cpp(card, programs, confirmed, unlocked,
                               cashback_only=cashback_only)
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
            capture = (CONFIRMED_CREDIT_CAPTURE if keys_confirmed
                       else CREDIT_CAPTURE)[credit["period"]]
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
            unlock_note = (f"; unlocked (${unlock:,.0f}/{credit['period']} spend)"
                           if unlock is not None else "")

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
                                    "note": f"in-kind est. ${face:,.2f}/yr × capture "
                                            f"{capture}{unlock_note}{usage_note}"})
                elif keys:
                    results.append({"card_id": card["id"], "name": credit["name"],
                                    "value": face * capture, "face_value": face,
                                    "note": f"face ${face:,.2f}/yr × capture "
                                            f"{capture}{unlock_note}{usage_note}"})
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
            result = {"card_id": card["id"], "name": credit["name"],
                      "value": value, "face_value": face, "note": note}
            if credit.get("notes"):
                result["disclaimer"] = credit["notes"]
            results.append(result)
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
                unlocked: frozenset = frozenset(),
                card_spend: float = 0.0) -> dict:
    """Signup-bonus value — counted once, year-1 only, feasibility-tested
    against the spend the optimizer routes onto THIS card. When the card's
    employee_cards.spend_counts_toward_bonus is false, the profile has no
    owner/employee split, so feasibility still uses total routed spend and a
    note flags the issuer's exclusion (documented V1 simplification)."""
    bonus = card["signup_bonus"]
    if bonus is None:
        return {"value": 0.0, "note": "no signup bonus", "floor_value": 0.0}
    if "expires" in bonus and date.fromisoformat(bonus["expires"]) < as_of:
        return {"value": 0.0, "note": f"$0 — offer expired {bonus['expires']}",
                "floor_value": 0.0}
    wm = bonus["window_months"]
    window_spend = card_spend * wm / 12.0
    seat_note = ""
    ec = card.get("employee_cards") or {}
    if ec.get("spend_counts_toward_bonus") is False \
            and profile["company"]["employee_card_seats"] > 0:
        seat_note = ("; issuer excludes employee-card spend from the bonus "
                     "requirement — feasibility shown against total company "
                     "spend (no owner/employee split in the profile)")
    if window_spend < bonus["spend_requirement_usd"] - EPS:
        req = bonus["spend_requirement_usd"]
        return {"value": 0.0,
                "note": (f"$0 — spend requirement ${req:,.0f} in {wm:g} mo "
                         f"(≈${req * 12.0 / wm:,.0f}/yr pace) unreachable by the "
                         f"${card_spend:,.0f}/yr routed onto this card{seat_note}"),
                "floor_value": 0.0}
    cpp, _ = effective_cpp(card, programs,
                           set(profile["user"]["confirmed_usage"]), unlocked,
                           cashback_only=is_cashback_only(profile))
    floor_cpp = programs.get(card["currency"]["program"], {}).get("floor_cpp", cpp)

    def usd_of(value):
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
    return {"value": total, "note": note + seat_note, "floor_value": floor_total}


def card_fees(card: dict, profile: dict, per_card_spend: dict,
              workhorse_id: str) -> dict:
    """Fees for one card under the business pricing models.

    annual_fee: the card fee (first_year_waived honored for year 1), refunded
    when fee_refund_spend_usd is met by the spend routed onto the card, plus
    employee seat fees when this card is the portfolio's workhorse (see
    SEAT_PLACEMENT policy).
    per_seat: the free tier is scored $0 (validator guarantees free_tier);
    the paid tier is disclosure only."""
    pricing = card["pricing"]
    seats = profile["company"]["employee_card_seats"]
    notes = []
    seat_fee = 0.0
    ec = card.get("employee_cards") or {}
    per_seat_fee = float(ec.get("fee_usd", 0.0))
    if seats > 0 and card["id"] == workhorse_id and per_seat_fee > 0:
        seat_fee = seats * per_seat_fee
        notes.append(f"{seats} employee seat(s) × ${per_seat_fee:,.0f} = "
                     f"${seat_fee:,.0f}/yr (seats assumed on this card — the "
                     f"portfolio's workhorse)")
        if ec.get("free_expense_card_variant"):
            notes.append("a $0 employee expense-card variant exists with fewer "
                         "benefits — V1 prices the paid variant")
    if pricing["model"] == "per_seat":
        base = 0.0
        year1 = 0.0
        tier = pricing.get("per_seat_monthly_usd")
        notes.append("free-tier SaaS pricing — the card itself costs $0"
                     + (f"; paid tier ${tier:g}/user/mo buys software, not "
                        f"card economics" if tier else ""))
        if pricing.get("platform_fee_note"):
            notes.append(pricing["platform_fee_note"])
        return {"ongoing": base + seat_fee, "year1": year1 + seat_fee,
                "annual_fee_usd": 0.0, "first_year_waived": False,
                "seat_fees_usd": seat_fee, "fee_refunded": False,
                "notes": notes}
    fee = float(pricing["annual_fee_usd"])
    refunded = False
    refund_at = pricing.get("fee_refund_spend_usd")
    if refund_at is not None:
        if per_card_spend.get(card["id"], 0.0) >= refund_at - EPS:
            refunded = True
            notes.append(f"${fee:,.0f} fee refunded — ${refund_at:,.0f}+ of "
                         f"annual spend routed onto this card")
        else:
            notes.append(f"fee refunds at ${refund_at:,.0f}/yr card spend "
                         f"(only ${per_card_spend.get(card['id'], 0.0):,.0f} "
                         f"routed here)")
    ongoing = (0.0 if refunded else fee) + seat_fee
    year1 = ((0.0 if (refunded or pricing.get("first_year_waived")) else fee)
             + seat_fee)
    return {"ongoing": ongoing, "year1": year1,
            "annual_fee_usd": fee,
            "first_year_waived": bool(pricing.get("first_year_waived")),
            "seat_fees_usd": seat_fee, "fee_refunded": refunded,
            "notes": notes}


def score_portfolio(cards: list, profile: dict, programs: dict,
                    buckets: dict, as_of: date) -> dict:
    """Jointly score a card subset: one shared spend assignment over all the
    subset's lines, plus credits (shared tracker), plus eligible signup
    bonuses (year-1 only), minus fees under the business pricing models."""
    unlocked = unlocked_programs(cards, profile)
    lines = []
    for card in cards:
        lines += build_lines(card, profile, programs, buckets, unlocked)
    assignments, unassigned = assign_spend(lines, buckets)
    per_card_spend = {card["id"]: 0.0 for card in cards}
    for a in assignments:
        per_card_spend[a["card_id"]] += a["usd_assigned"]
    credits = score_credits(cards, profile, programs, as_of, per_card_spend,
                            unlocked)
    credits_total = sum(c["value"] for c in credits)
    per_card_earnings = {card["id"]: 0.0 for card in cards}
    for a in assignments:
        per_card_earnings[a["card_id"]] += a["usd_value"]
    reward_cap_clamps = {}
    for card in cards:
        cap = card.get("max_annual_rewards_usd")
        cid = card["id"]
        if cap is not None and per_card_earnings[cid] > cap:
            reward_cap_clamps[cid] = round(per_card_earnings[cid] - cap, 2)
            per_card_earnings[cid] = cap
    earnings = sum(per_card_earnings.values())
    bonuses = {card["id"]: score_bonus(card, profile, programs, as_of,
                                       unlocked, per_card_spend[card["id"]])
               for card in cards}
    bonus_total = sum(b["value"] for b in bonuses.values())
    # Workhorse: the card carrying the most assigned spend (card-id
    # tie-break) — employee seats are assumed equipped there (SEAT_PLACEMENT).
    workhorse_id = min(sorted(per_card_spend),
                       key=lambda cid: (-per_card_spend[cid], cid))
    fees = {c["id"]: card_fees(c, profile, per_card_spend, workhorse_id)
            for c in cards}
    ongoing_fee = sum(f["ongoing"] for f in fees.values())
    year1_fee = sum(f["year1"] for f in fees.values())
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
        "fees": fees,
        "workhorse_id": workhorse_id,
        "per_card_spend": per_card_spend,
        "ongoing_fee": ongoing_fee,
        "year1_fee": year1_fee,
    }


# ---------------------------------------------------------------------------
# Eligibility filter and search
# ---------------------------------------------------------------------------

def _approval_reason(card: dict, company: dict) -> str:
    """Empty string when the company satisfies business_approval; else the
    human reason for exclusion."""
    ba = card["business_approval"]
    if company["entity_type"] not in ba["entity_types"]:
        return (f"issuer accepts {'/'.join(ba['entity_types'])} entities — "
                f"not {company['entity_type']}")
    if ba["personal_guarantee"]:
        if not company["accepts_personal_guarantee"]:
            return ("requires a personal guarantee — set "
                    "company.accepts_personal_guarantee: true to consider it")
        tier = ba.get("min_personal_fico_tier")
        if tier and TIER_ORDER.index(company["owner_fico_tier"]) < TIER_ORDER.index(tier):
            return f"requires owner credit tier '{tier}'"
    if ba.get("requires_ein") and not company["has_ein"]:
        return "requires an EIN (company.has_ein is false)"
    paths = []
    qualified = True
    cash = ba.get("min_cash_balance_usd")
    rev = ba.get("min_annual_revenue_usd")
    funding = ba.get("funding_qualifies")
    if cash is not None or rev is not None or funding:
        qualified = False
        if cash is not None:
            paths.append(f"${cash:,.0f}+ cash balance")
            if company["cash_balance_usd"] >= cash - EPS:
                qualified = True
        if rev is not None:
            paths.append(f"${rev:,.0f}+ annual revenue")
            if company["annual_revenue_usd"] >= rev - EPS:
                qualified = True
        if funding:
            paths.append("equity funding")
            if company["has_funding"]:
                qualified = True
    if not qualified:
        return f"underwriting needs one of: {', '.join(paths)}"
    return ""


def filter_cards(cards: list, profile: dict, programs: dict,
                 issuer_rules: dict) -> tuple:
    """User-veto, availability, business-approval, issuer 5/24 gate,
    brand-lock-in, and reward-preference filters."""
    prefs = set(profile["user"]["reward_preferences"])
    kind_filter = expand_reward_prefs(prefs)
    accepts_lockin = profile["user"]["accepts_brand_lockin"]
    vetoed = set(profile.get("exclude_cards") or [])
    five24 = profile["personal"]["five24_count"]
    eligible, excluded = [], []
    for card in sorted(cards, key=lambda c: c["id"]):
        program = card["currency"]["program"]
        redeems = set(programs[program].get("redeems_for", []))
        rules = issuer_rules.get(card["issuer"]) or {}
        approval_reason = _approval_reason(card, profile["company"])
        if card["id"] in vetoed:
            excluded.append({"id": card["id"],
                             "reason": "excluded by you — un-exclude it in the "
                                       "card list to consider it again"})
        elif card.get("availability", "active") == "discontinued":
            excluded.append({"id": card["id"],
                             "reason": "discontinued — no longer open to new applicants; "
                                       "select it in Custom mode to score a card you already hold"})
        elif approval_reason:
            excluded.append({"id": card["id"], "reason": approval_reason})
        elif rules.get("gate_524") and five24 >= 5:
            excluded.append({"id": card["id"],
                             "reason": f"{card['issuer']} applies the 5/24 rule and "
                                       f"you report {five24} personal openings in "
                                       f"24 months — under 5 required"})
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
        warnings.append("UNVERIFIED DATA — confidence: low; needs human "
                        "verification against issuer terms")
    verified = date.fromisoformat(card["verification"]["last_verified_date"])
    if (as_of - verified).days > STALE_DAYS:
        warnings.append(f"stale verification — last verified {verified} "
                        f"(> {STALE_DAYS} days before as-of date)")
    bonus = card["signup_bonus"]
    if bonus is not None and "expires" in bonus \
            and date.fromisoformat(bonus["expires"]) < as_of:
        warnings.append(f"signup bonus offer expired {bonus['expires']} — valued at $0")
    return warnings


def amex_limit_ok(cards: list, profile: dict, issuer_rules: dict) -> bool:
    """Issuer credit-card limits (Amex 5): portfolio REVOLVING cards from a
    limited issuer + the owner's existing personal count must stay within the
    limit; charge-lineage cards are exempt when the issuer flags
    charge_exempt."""
    for issuer, rules in issuer_rules.items():
        limit = rules.get("credit_card_limit")
        if limit is None:
            continue
        counted = sum(
            1 for c in cards
            if c["issuer"] == issuer
            and not (rules.get("charge_exempt") and c.get("payment_type") == "charge"))
        held = (profile["personal"]["amex_credit_cards"]
                if issuer == "amex" else 0)
        if counted + held > limit:
            return False
    return True


def subset_budget(n_variants: int, max_cards: int) -> int:
    return sum(math.comb(n_variants, k) for k in range(1, max_cards + 1))


def search(cards: list, profile: dict, programs: dict, merchants: dict,
           categories: dict, issuer_rules: dict, as_of: date) -> list:
    """Exhaustive over all subsets of eligible cards, sizes 1..max_cards,
    honoring issuer credit-card limits. No choose-your-own variants exist in
    the business corpus (adaptive_top_n resolves deterministically inside
    build_lines), so no variant expansion or dominance pruning is needed —
    the corpus stays comfortably under MAX_SCORED_SUBSETS."""
    buckets = build_buckets(profile, merchants, categories)
    by_id = {c["id"]: c for c in cards}
    ids = sorted(by_id)
    results = []
    max_cards = min(profile["user"]["max_cards"], len(ids))
    budget = subset_budget(len(ids), max_cards)
    if budget > MAX_SCORED_SUBSETS:
        raise DataError(
            f"{len(ids)} eligible cards at max_cards={max_cards} means "
            f"{budget:,} subsets to score, over the exhaustive-search budget "
            f"MAX_SCORED_SUBSETS = {MAX_SCORED_SUBSETS:,}; lower user.max_cards "
            "(or --max-cards) to bring the search back under budget")
    for k in range(1, max_cards + 1):
        for combo in itertools.combinations(ids, k):
            subset = [by_id[i] for i in combo]
            if not amex_limit_ok(subset, profile, issuer_rules):
                continue
            scored = score_portfolio(subset, profile, programs, buckets, as_of)
            results.append({"cards": list(combo),
                            "ongoing_net": scored["ongoing_net"],
                            "year1_net": scored["year1_net"]})
    primary = ("ongoing_net" if profile["user"]["optimize_for"] == "ongoing"
               else "year1_net")
    results.sort(key=lambda r: (-r[primary], -r["year1_net"], tuple(r["cards"])))
    return results


# ---------------------------------------------------------------------------
# Reporting additions (plan 22 §7)
# ---------------------------------------------------------------------------

def application_notes(cards: list, profile: dict, issuer_rules: dict) -> list:
    """Informational application-sequencing notes for a portfolio — velocity
    rules, 5/24 interactions, personal-credit reporting, once-per-lifetime
    bonus rules. Presentation only, never a constraint."""
    notes = []
    issuers = sorted({c["issuer"] for c in cards})
    five24 = profile["personal"]["five24_count"]
    for issuer in issuers:
        rules = issuer_rules.get(issuer) or {}
        issuer_cards = [c for c in cards if c["issuer"] == issuer]
        if rules.get("gate_524"):
            notes.append(
                f"{issuer}: applications are gated by 5/24 (you report "
                f"{five24}/5 personal openings); business cards here do NOT "
                f"add to your 5/24 count once opened")
        if rules.get("adds_to_524"):
            exceptions = set(rules.get("adds_to_524_exceptions") or [])
            adders = [c["id"] for c in issuer_cards if c["id"] not in exceptions]
            for cid in adders:
                notes.append(
                    f"{cid}: reports to personal credit — opening it ADDS to "
                    f"your 5/24 count (currently {five24})")
        if rules.get("credit_card_limit"):
            held = (profile["personal"]["amex_credit_cards"]
                    if issuer == "amex" else 0)
            counted = sum(1 for c in issuer_cards
                          if not (rules.get("charge_exempt")
                                  and c.get("payment_type") == "charge"))
            if counted:
                notes.append(
                    f"{issuer}: counts {counted} revolving card(s) here toward "
                    f"its {rules['credit_card_limit']}-card limit (you already "
                    f"hold {held} — charge-lineage cards are exempt)")
        if rules.get("once_per_lifetime_bonus"):
            notes.append(f"{issuer}: welcome bonuses are once per product per "
                         f"person — prior bonuses on these products disqualify")
        if rules.get("velocity_note"):
            notes.append(f"{issuer}: {rules['velocity_note']}")
    return notes


def float_summary(cards: list, per_card_spend: dict) -> dict:
    """Working-capital float per portfolio: each card's grace_days, plus the
    assigned-spend-weighted average across cards that publish one. Reported,
    never scored (V1)."""
    entries = []
    weighted = 0.0
    weight = 0.0
    for c in sorted(cards, key=lambda c: c["id"]):
        fd = c.get("float_days")
        if not fd or fd.get("grace_days") is None:
            continue
        spend = per_card_spend.get(c["id"], 0.0)
        entries.append({"card_id": c["id"], "grace_days": fd["grace_days"],
                        "note": fd["note"]})
        weighted += fd["grace_days"] * spend
        weight += spend
    return {"cards": entries,
            "spend_weighted_avg_days":
                round(weighted / weight, 1) if weight > EPS else None}


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

def _round2(x: float) -> float:
    return round(x + 0.0, 2)


def assemble_portfolio(entry: dict, by_id: dict, profile: dict, programs: dict,
                       buckets: dict, issuer_rules: dict, as_of: date,
                       gateways: dict = None) -> dict:
    """Full detail for one ranked entry — the per-portfolio output block."""
    cards = [by_id[i] for i in entry["cards"]]
    scored = score_portfolio(cards, profile, programs, buckets, as_of)
    unlocked = unlocked_programs(cards, profile)
    total_spend = sum(bk["amount"] for bk in buckets.values())
    per_card = {}
    for card in cards:
        cid = card["id"]
        prog_key = card["currency"]["program"]
        prog = programs[prog_key]
        fee = scored["fees"][cid]
        per_card[cid] = {
            "name": card["name"],
            "currency": {"kind": card["currency"]["type"], "program": prog_key,
                         "label": prog.get("label", prog_key)},
            "assignments": [
                {"bucket": a["bucket"], "usd_assigned": _round2(a["usd_assigned"]),
                 "rate": a["rate"], "cpp": a["cpp"],
                 "usd_value": _round2(a["usd_value"]), "note": a["note"],
                 **({"eligible_fraction": a["eligible_fraction"]}
                    if a.get("eligible_fraction") is not None else {})}
                for a in scored["assignments"] if a["card_id"] == cid],
            "credits": [
                {"name": c["name"], "value": _round2(c["face_value"]), "note": c["note"],
                 **({"potential_value": _round2(c["potential_value"])}
                    if "potential_value" in c else {}),
                 **({"disclaimer": c["disclaimer"]} if "disclaimer" in c else {})}
                for c in scored["credits"] if c["card_id"] == cid],
            "bonus": {"value": _round2(scored["bonuses"][cid]["value"]),
                      "note": scored["bonuses"][cid]["note"],
                      "floor_value": _round2(scored["bonuses"][cid]["floor_value"])},
            "fees": {"annual_fee_usd": fee["annual_fee_usd"],
                     "first_year_waived": fee["first_year_waived"],
                     "seat_fees_usd": _round2(fee["seat_fees_usd"]),
                     "fee_refunded": fee["fee_refunded"],
                     "ongoing_usd": _round2(fee["ongoing"]),
                     "year1_usd": _round2(fee["year1"]),
                     "notes": fee["notes"]},
            "payment_type": card.get("payment_type"),
            "integrations": sorted(card.get("integrations") or []),
            "virtual_cards": bool(card.get("virtual_cards")),
            "warnings": card_warnings(card, as_of),
        }
        _, valuation_note = effective_cpp(
            card, programs, set(profile["user"]["confirmed_usage"]),
            unlocked, gateways, cashback_only=is_cashback_only(profile))
        if valuation_note:
            per_card[cid]["valuation_note"] = valuation_note
        elif (prog.get("transfer_gateway_required")
                and not card.get("unlocks_transfers")
                and combinable(card)
                and prog_key in unlocked):
            partners = gateway_names(cards, profile).get(prog_key, [])
            per_card[cid]["pairing_note"] = (
                f"points pooled with {' / '.join(partners)} — valued at "
                f"{_round2(avg_cpp(prog))}cpp (avg of {prog['floor_cpp']}cpp cash "
                f"floor and {prog['optimistic_cpp']}cpp transfer value)")
        if cid in scored["reward_cap_clamps"]:
            per_card[cid]["reward_cap_clamp"] = _round2(scored["reward_cap_clamps"][cid])
    earnings_disp = _round2(
        sum(a["usd_value"] for c in per_card.values() for a in c["assignments"])
        - sum(c.get("reward_cap_clamp", 0.0) for c in per_card.values()))
    credits_disp = sum(cr["value"] for c in per_card.values() for cr in c["credits"])
    bonus_disp = sum(c["bonus"]["value"] for c in per_card.values())
    ongoing_fee_disp = _round2(sum(c["fees"]["ongoing_usd"] for c in per_card.values()))
    year1_fee_disp = _round2(sum(c["fees"]["year1_usd"] for c in per_card.values()))

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
        # Headline blended reward rate: portfolio spend earnings ÷ total
        # profile spend (credits/bonuses excluded — this is the earn engine's
        # rate, the number a CFO compares to a flat 2% card).
        "blended_rate_pct": (_round2(100.0 * earnings_disp / total_spend)
                             if total_spend > EPS else None),
        "workhorse_card": scored["workhorse_id"],
        "float_days": float_summary(cards, scored["per_card_spend"]),
        "application_notes": application_notes(cards, profile, issuer_rules),
        "unassigned_spend": {b: _round2(v) for b, v in scored["unassigned"].items()},
        **({"unassigned_notes": unassigned_notes} if unassigned_notes else {}),
        "per_card": per_card,
    }


def _bundle_header(dataset: dict, profile: dict, as_of: date) -> dict:
    programs = dataset["programs"]
    return {
        "as_of": as_of.isoformat(),
        "optimize_for": profile["user"]["optimize_for"],
        "max_cards": profile["user"]["max_cards"],
        "reward_preferences": list(profile["user"]["reward_preferences"]),
        "confirmed_usage": list(profile["user"]["confirmed_usage"]),
        "assumed_usage": list(profile["user"]["assumed_usage"]),
        "accepts_brand_lockin": profile["user"]["accepts_brand_lockin"],
        "company": {k: profile["company"][k]
                    for k in sorted(profile["company"])},
        "personal": {k: profile["personal"][k]
                     for k in sorted(profile["personal"])},
        "cpp_table": {p: {"floor_cpp": v["floor_cpp"],
                          "optimistic_cpp": v["optimistic_cpp"],
                          "avg_cpp": _round2(avg_cpp(v))}
                      for p, v in sorted(programs.items())},
        "policy_constants": policy_constants(),
        "cards_total": len(dataset["cards"]),
    }


def run(dataset: dict, profile: dict, as_of: date, top: int) -> dict:
    """Produce the full output bundle rendered by render_text / render_json."""
    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]
    issuer_rules = dataset["issuer_rules"]
    eligible, excluded = filter_cards(dataset["cards"], profile, programs,
                                      issuer_rules)
    ranked = search(eligible, profile, programs, merchants, categories,
                    issuer_rules, as_of)

    by_id = {c["id"]: c for c in eligible}
    buckets = build_buckets(profile, merchants, categories)
    gateways = gateway_names(dataset["cards"], profile)
    portfolios = [assemble_portfolio(entry, by_id, profile, programs, buckets,
                                     issuer_rules, as_of, gateways)
                  for entry in ranked[:top]]

    best_by_size = []
    seen_sizes = set()
    for entry in ranked:
        size = len(entry["cards"])
        if size in seen_sizes:
            continue
        seen_sizes.add(size)
        best_by_size.append({"size": size,
                             **assemble_portfolio(entry, by_id, profile,
                                                  programs, buckets,
                                                  issuer_rules, as_of,
                                                  gateways)})
    best_by_size.sort(key=lambda b: b["size"])

    return {
        **_bundle_header(dataset, profile, as_of),
        "cards_eligible": len(eligible),
        "excluded": excluded,
        "best_by_size": best_by_size,
        "portfolios": portfolios,
    }


def evaluate(dataset: dict, profile: dict, as_of: date, card_ids: list) -> dict:
    """Manual mode: score exactly the user-selected cards, bypassing the
    filter/search that Auto mode uses to pick the set. Selection overrides
    every Auto filter (approval, 5/24, lock-in, preferences) — a hand-picked
    card is scored as-is. The issuer credit-card limit is also bypassed (the
    user asserts they can hold the set); application_notes still flag it."""
    if not isinstance(card_ids, list) or not card_ids:
        raise InputError("evaluate: 'cards' must be a non-empty list of card ids")
    if any(not isinstance(c, str) for c in card_ids):
        raise InputError(f"evaluate: 'cards' must be a list of card-id strings, "
                         f"got {card_ids!r}")
    if len(set(card_ids)) != len(card_ids):
        raise InputError(f"evaluate: 'cards' has duplicate ids: {card_ids}")
    by_id = {c["id"]: c for c in dataset["cards"]}
    unknown = [c for c in card_ids if c not in by_id]
    if unknown:
        raise InputError(f"evaluate: unknown card id(s): {sorted(unknown)}")

    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]
    issuer_rules = dataset["issuer_rules"]

    buckets = build_buckets(profile, merchants, categories)
    gateways = gateway_names(dataset["cards"], profile)
    portfolio = assemble_portfolio({"cards": list(card_ids)}, by_id, profile,
                                   programs, buckets, issuer_rules, as_of,
                                   gateways)
    return {
        **_bundle_header(dataset, profile, as_of),
        "cards_eligible": len(card_ids),
        "excluded": [],
        "best_by_size": [{"size": len(card_ids), **portfolio}],
        "portfolios": [portfolio],
    }


def augment(dataset: dict, profile: dict, as_of: date, held_ids: list) -> dict:
    """Best-additional-card: given the held set, find the single eligible card
    whose addition maximizes the active metric, then return the evaluate()
    bundle for held + that card with an `added_card` key. Candidates honor the
    Auto filters AND the issuer credit-card limit; held cards bypass both."""
    if not isinstance(held_ids, list) or not held_ids:
        raise InputError("augment: 'cards' must be a non-empty list of card ids")
    if any(not isinstance(c, str) for c in held_ids):
        raise InputError(f"augment: 'cards' must be a list of card-id strings, "
                         f"got {held_ids!r}")
    if len(set(held_ids)) != len(held_ids):
        raise InputError(f"augment: 'cards' has duplicate ids: {held_ids}")
    by_id = {c["id"]: c for c in dataset["cards"]}
    unknown = [c for c in held_ids if c not in by_id]
    if unknown:
        raise InputError(f"augment: unknown card id(s): {sorted(unknown)}")
    held_set = set(held_ids)

    profile["user"]["assumed_usage"] = assumed_usage(
        profile["user"], dataset.get("usage_questions") or {})
    programs = dataset["programs"]
    merchants = dataset["merchants"]
    categories = dataset["categories"]
    issuer_rules = dataset["issuer_rules"]

    eligible, _ = filter_cards(dataset["cards"], profile, programs, issuer_rules)
    candidates = [c["id"] for c in eligible if c["id"] not in held_set]
    if not candidates:
        raise InputError("augment: no eligible cards left to add")

    buckets = build_buckets(profile, merchants, categories)
    primary = ("ongoing_net" if profile["user"]["optimize_for"] == "ongoing"
               else "year1_net")
    scored = []
    for cand in candidates:
        subset = [by_id[c] for c in held_ids + [cand]]
        if not amex_limit_ok(subset, profile, issuer_rules):
            continue
        s = score_portfolio(subset, profile, programs, buckets, as_of)
        metric = s["ongoing_net"] if primary == "ongoing_net" else s["year1_net"]
        scored.append((metric, s["year1_net"], cand))
    if not scored:
        raise InputError("augment: no eligible cards left to add within issuer "
                         "card limits")
    scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
    best_id = scored[0][2]

    return {**evaluate(dataset, profile, as_of, held_ids + [best_id]),
            "added_card": best_id}


def render_json(bundle: dict) -> str:
    return json.dumps(bundle, sort_keys=True, indent=2) + "\n"


def render_text(bundle: dict) -> str:
    out = []
    out.append(f"Business credit-card portfolio optimizer — as of {bundle['as_of']}")
    out.append(f"Optimizing for: {bundle['optimize_for']} | max cards: "
               f"{bundle['max_cards']} | rewards wanted: "
               f"{', '.join(bundle['reward_preferences'])} | brand lock-in ok: "
               f"{'yes' if bundle['accepts_brand_lockin'] else 'no'}")
    co = bundle["company"]
    out.append(f"Company: {co['entity_type']} | PG ok: "
               f"{'yes' if co['accepts_personal_guarantee'] else 'no'} | "
               f"owner tier: {co['owner_fico_tier'] or 'n/a'} | seats: "
               f"{co['employee_card_seats']} | large-txn share: "
               f"{co['large_txn_share']:.0%}")
    pe = bundle["personal"]
    out.append(f"Personal: 5/24 count {pe['five24_count']} | Amex credit cards "
               f"{pe['amex_credit_cards']} | premium held: "
               f"{', '.join(pe['premium_cards_held']) or 'none'}")
    out.append("Confirmed usage: "
               + (", ".join(bundle["confirmed_usage"]) or
                  "none — merchant/loyalty-gated value counts $0"))
    out.append("Assumed usage: " + (", ".join(bundle["assumed_usage"]) or "none"))
    cpp = ", ".join(f"{p} {v['avg_cpp']}" for p, v in bundle["cpp_table"].items())
    out.append(f"Point valuations (avg_cpp; floor when gated & unconfirmed): {cpp}")
    out.append("Policy constants: " + json.dumps(bundle["policy_constants"],
                                                 sort_keys=True))
    excluded = "; ".join(f"{e['id']}: {e['reason']}" for e in bundle["excluded"]) or "none"
    out.append(f"Cards: {bundle['cards_total']} in dataset, "
               f"{bundle['cards_eligible']} eligible, "
               f"{len(bundle['excluded'])} excluded ({excluded})")
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
                   f"year-1 net: ${p['year1_net']:,.2f}   "
                   f"blended earn rate: "
                   + (f"{p['blended_rate_pct']:.2f}%"
                      if p["blended_rate_pct"] is not None else "n/a"))
        for cid in p["cards"]:
            d = p["per_card"][cid]
            out.append(f"    {cid} — {d['name']}")
            if "valuation_note" in d:
                out.append(f"      ⚠ {d['valuation_note']}")
            if "pairing_note" in d:
                out.append(f"      ✓ {d['pairing_note']}")
            for a in d["assignments"]:
                note = f"   [{a['note']}]" if a["note"] else ""
                out.append(f"      earn: {a['bucket']:<24} ${a['usd_assigned']:>12,.2f} "
                           f"@ {a['rate']}x × {a['cpp']}cpp = ${a['usd_value']:,.2f}{note}")
            if "reward_cap_clamp" in d:
                out.append(f"      ⚠ card-wide reward cap (max_annual_rewards_usd): "
                           f"earnings above clamped by ${d['reward_cap_clamp']:,.2f}")
            for c in d["credits"]:
                face = (f"   (face ${c['potential_value']:,.2f}/yr you'd get anyway)"
                        if "potential_value" in c else "")
                out.append(f"      credit: {c['name']} = ${c['value']:,.2f}   "
                           f"[{c['note']}]{face}")
            bonus = d["bonus"]
            out.append(f"      bonus (year 1 only): ${bonus['value']:,.2f}   "
                       f"[{bonus['note']}]")
            fee = d["fees"]
            waived = " (first year waived)" if fee["first_year_waived"] else ""
            refunded = " (refunded by spend)" if fee["fee_refunded"] else ""
            out.append(f"      annual fee: ${fee['annual_fee_usd']:,.2f}"
                       f"{waived}{refunded}"
                       + (f" + seat fees ${fee['seat_fees_usd']:,.2f}"
                          if fee["seat_fees_usd"] else ""))
            for n in fee["notes"]:
                out.append(f"        · {n}")
            for w in d["warnings"]:
                out.append(f"      ⚠ {w}")
        fd = p["float_days"]
        if fd["cards"]:
            days = "; ".join(f"{e['card_id']}: {e['grace_days']}d" for e in fd["cards"])
            avg = (f" (spend-weighted avg {fd['spend_weighted_avg_days']}d)"
                   if fd["spend_weighted_avg_days"] is not None else "")
            out.append(f"    float: {days}{avg} — reported, not scored")
        for n in p["application_notes"]:
            out.append(f"    ℹ {n}")
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
    parser = _Parser(description="Deterministic BUSINESS credit-card portfolio "
                                 "optimizer (plan 22C)")
    parser.add_argument("--profile", required=True,
                        help="path to a business spend-profile YAML")
    parser.add_argument("--max-cards", type=int,
                        help="override the profile's user.max_cards (1-5)")
    parser.add_argument("--rewards", metavar="KIND[,KIND...]",
                        help="override the profile's user.reward_preferences — "
                             "comma-separated from: " + ", ".join(REWARD_PREF_CHOICES))
    parser.add_argument("--confirm", metavar="KEY[,KEY...]",
                        help="override the profile's user.confirmed_usage — "
                             "comma-separated usage-questions item keys "
                             "(data/business/meta/usage-questions.yaml)")
    parser.add_argument("--top", type=int, default=5,
                        help="number of ranked portfolios to show (default 5)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output with sorted keys")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="the only time input (default: today)")
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
