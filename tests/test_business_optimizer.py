"""Golden tests for scripts/optimize_business.py (plan 22C).

Mirrors the consumer golden-test style: synthetic cards exercise each business
mechanic in isolation with exact expected numbers; a handful of dataset-level
tests pin behavior against the real business corpus. Every test is
deterministic (fixed as_of, fixed profiles)."""

import copy
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "optimize_business", ROOT / "scripts" / "optimize_business.py")
opt = importlib.util.module_from_spec(spec)
sys.modules["optimize_business"] = opt
spec.loader.exec_module(opt)

AS_OF = date(2026, 7, 17)

DATASET = opt.load_dataset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(spend, merchant_spend=None, company=None, personal=None,
                 exclude_cards=None, dataset=None, **user):
    raw = {
        "spend": spend,
        "company": {"entity_type": "llc",
                    "accepts_personal_guarantee": True,
                    "owner_fico_tier": "excellent",
                    **(company or {})},
        "user": dict(user),
    }
    if merchant_spend:
        raw["merchant_spend"] = merchant_spend
    if personal:
        raw["personal"] = personal
    if exclude_cards:
        raw["exclude_cards"] = exclude_cards
    return opt.parse_business_profile(raw, dataset or DATASET)


def synth_card(**overrides):
    card = {
        "id": "synth", "name": "Synthetic", "issuer": "test-bank",
        "network": "visa",
        "currency": {"type": "cash", "program": "cash"}, "base_rate": 1,
        "category_rewards": [], "merchant_rewards": [], "credits": [],
        "signup_bonus": None,
        "pricing": {"model": "annual_fee", "annual_fee_usd": 0,
                    "foreign_transaction_pct": 0},
        "business_approval": {"personal_guarantee": True,
                              "min_personal_fico_tier": "good",
                              "entity_types": ["sole_prop", "llc", "corp"]},
        "employee_cards": {"fee_usd": 0},
        "payment_type": "revolving",
        "benefit_flags": [],
        "sources": [], "notes": "",
        "verification": {"last_verified_date": "2026-07-17",
                         "verified_by": "test", "confidence": "high"},
    }
    card.update(overrides)
    return card


def synth_dataset(cards, issuer_rules=None, programs=None):
    ds = {
        "categories": DATASET["categories"],
        "merchants": DATASET["merchants"],
        "programs": programs or DATASET["programs"],
        "cards": sorted(cards, key=lambda c: c["id"]),
        "usage_questions": DATASET["usage_questions"],
        "usage_keys": DATASET["usage_keys"],
        "single_fee_keys": DATASET["single_fee_keys"],
        "issuer_rules": {"test-bank": {}, **(issuer_rules or {})},
    }
    return ds


def score(cards, profile, dataset=None):
    ds = dataset or synth_dataset(cards)
    buckets = opt.build_buckets(profile, ds["merchants"], ds["categories"])
    return opt.score_portfolio(cards, profile, ds["programs"], buckets, AS_OF)


# ---------------------------------------------------------------------------
# Profile parsing
# ---------------------------------------------------------------------------

def test_profile_requires_company_block():
    with pytest.raises(opt.InputError, match="company"):
        opt.parse_business_profile({"spend": {"shipping": 1000}, "user": {}},
                                   DATASET)


def test_profile_rejects_unknown_category_and_company_keys():
    with pytest.raises(opt.InputError, match="unknown category 'groceries'"):
        make_profile({"groceries": 100})
    with pytest.raises(opt.InputError, match="company: unknown key"):
        make_profile({"shipping": 100}, company={"vibes": 1})


def test_profile_requires_owner_tier_with_pg():
    with pytest.raises(opt.InputError, match="owner_fico_tier"):
        make_profile({"shipping": 100},
                     company={"owner_fico_tier": None})


def test_profile_no_pg_company_needs_no_tier():
    p = make_profile({"shipping": 100},
                     company={"accepts_personal_guarantee": False,
                              "owner_fico_tier": None,
                              "cash_balance_usd": 100000})
    assert p["company"]["owner_fico_tier"] is None


def test_profile_large_txn_share_range():
    with pytest.raises(opt.InputError, match="large_txn_share"):
        make_profile({"shipping": 100}, company={"large_txn_share": 1.5})


def test_profile_has_ein_defaults_by_entity():
    llc = make_profile({"shipping": 100})
    sole = make_profile({"shipping": 100},
                        company={"entity_type": "sole_prop"})
    assert llc["company"]["has_ein"] is True
    assert sole["company"]["has_ein"] is False


def test_profile_personal_defaults_and_validation():
    p = make_profile({"shipping": 100})
    assert p["personal"] == {"five24_count": 0, "amex_credit_cards": 0,
                             "premium_cards_held": []}
    with pytest.raises(opt.InputError, match="premium_cards_held"):
        make_profile({"shipping": 100},
                     personal={"premium_cards_held": ["platinum_card"]})


def test_profile_merchant_carveout_cannot_exceed_category():
    with pytest.raises(opt.InputError, match="carve-outs"):
        make_profile({"wholesale": 100},
                     merchant_spend={"amazon_business": 200})


# ---------------------------------------------------------------------------
# Approval filter and issuer rules
# ---------------------------------------------------------------------------

def test_filter_pg_refusal_excludes_pg_cards():
    card = synth_card()
    profile = make_profile({"shipping": 1000},
                           company={"accepts_personal_guarantee": False,
                                    "owner_fico_tier": None,
                                    "cash_balance_usd": 1_000_000})
    eligible, excluded = opt.filter_cards([card], profile, DATASET["programs"],
                                          {"test-bank": {}})
    assert eligible == []
    assert "personal guarantee" in excluded[0]["reason"]


def test_filter_fico_tier():
    card = synth_card(business_approval={
        "personal_guarantee": True, "min_personal_fico_tier": "excellent",
        "entity_types": ["llc"]})
    profile = make_profile({"shipping": 1000},
                           company={"owner_fico_tier": "good"})
    eligible, excluded = opt.filter_cards([card], profile, DATASET["programs"],
                                          {"test-bank": {}})
    assert eligible == []
    assert "excellent" in excluded[0]["reason"]


def test_filter_entity_type():
    card = synth_card(business_approval={
        "personal_guarantee": False, "entity_types": ["llc", "corp"]})
    profile = make_profile({"shipping": 1000},
                           company={"entity_type": "sole_prop",
                                    "owner_fico_tier": None,
                                    "accepts_personal_guarantee": False})
    eligible, excluded = opt.filter_cards([card], profile, DATASET["programs"],
                                          {"test-bank": {}})
    assert eligible == []
    assert "sole_prop" in excluded[0]["reason"]


def test_filter_fintech_thresholds_any_path_qualifies():
    card = synth_card(business_approval={
        "personal_guarantee": False, "entity_types": ["llc", "corp"],
        "requires_ein": True, "min_cash_balance_usd": 50000,
        "min_annual_revenue_usd": 500000, "funding_qualifies": True})
    base = {"accepts_personal_guarantee": False, "owner_fico_tier": None}
    poor = make_profile({"shipping": 1000}, company=base)
    rich = make_profile({"shipping": 1000},
                        company={**base, "cash_balance_usd": 60000})
    funded = make_profile({"shipping": 1000},
                          company={**base, "has_funding": True})
    rules = {"test-bank": {}}
    assert opt.filter_cards([card], poor, DATASET["programs"], rules)[0] == []
    assert opt.filter_cards([card], rich, DATASET["programs"], rules)[0] != []
    assert opt.filter_cards([card], funded, DATASET["programs"], rules)[0] != []


def test_filter_524_gate():
    card = synth_card(issuer="chase-like")
    rules = {"chase-like": {"gate_524": True}}
    over = make_profile({"shipping": 1000},
                        personal={"five24_count": 5})
    under = make_profile({"shipping": 1000},
                         personal={"five24_count": 4})
    assert opt.filter_cards([card], over, DATASET["programs"], rules)[0] == []
    assert opt.filter_cards([card], under, DATASET["programs"], rules)[0] != []


def test_amex_limit_counts_revolving_only_plus_personal():
    # personal.amex_credit_cards is keyed to the literal 'amex' issuer.
    rules = {"amex": {"credit_card_limit": 5, "charge_exempt": True}}
    revolving = [synth_card(id=f"r{i}", issuer="amex") for i in range(4)]
    charge = synth_card(id="charge", issuer="amex", payment_type="charge")
    profile = make_profile({"shipping": 1000},
                           personal={"amex_credit_cards": 1})
    # 4 revolving + 1 held personal = 5 → at limit, ok.
    assert opt.amex_limit_ok(revolving, profile, rules)
    # Adding a charge card is exempt → still ok.
    assert opt.amex_limit_ok(revolving + [charge], profile, rules)
    # A fifth revolving busts the limit.
    fifth = synth_card(id="r9", issuer="amex")
    assert not opt.amex_limit_ok(revolving + [fifth], profile, rules)


def test_application_notes_mention_524_and_velocity():
    cards = [synth_card(id="a", issuer="chase-like")]
    rules = {"chase-like": {"gate_524": True, "velocity_note": "pace yourself"}}
    profile = make_profile({"shipping": 1000}, personal={"five24_count": 3})
    notes = opt.application_notes(cards, profile, rules)
    assert any("5/24" in n and "3/5" in n for n in notes)
    assert any("pace yourself" in n for n in notes)


def test_application_notes_adds_to_524_exceptions():
    cards = [synth_card(id="normal", issuer="cap-like"),
             synth_card(id="exempt", issuer="cap-like")]
    rules = {"cap-like": {"adds_to_524": True,
                          "adds_to_524_exceptions": ["exempt"]}}
    profile = make_profile({"shipping": 1000})
    notes = opt.application_notes(cards, profile, rules)
    assert any(n.startswith("normal:") and "ADDS" in n for n in notes)
    assert not any(n.startswith("exempt:") for n in notes)


# ---------------------------------------------------------------------------
# Value model: business mechanics
# ---------------------------------------------------------------------------

def test_base_rate_cap_splits_at_threshold():
    # 2% on the first $50k of ALL spend, then 1% (Blue Business Cash shape).
    card = synth_card(base_rate=2, base_rate_cap={
        "period": "annual", "max_spend_usd": 50000, "fallback_rate": 1})
    profile = make_profile({"shipping": 80000})
    s = score([card], profile)
    by_kind = {a["kind"]: a for a in s["assignments"]}
    assert by_kind["base"]["usd_assigned"] == pytest.approx(50000)
    assert by_kind["base"]["usd_value"] == pytest.approx(1000.0)
    assert by_kind["base_fallback"]["usd_assigned"] == pytest.approx(30000)
    assert by_kind["base_fallback"]["usd_value"] == pytest.approx(300.0)
    assert s["earnings"] == pytest.approx(1300.0)


def test_shared_cap_pool_drains_across_categories():
    # Ink Cash shape: 5% office supplies + telecom on ONE $25k pool.
    pool = {"period": "annual", "max_spend_usd": 25000, "fallback_rate": 1,
            "shared_cap_id": "essentials"}
    card = synth_card(category_rewards=[
        {"category": "office_supplies", "rate": 5, "cap": dict(pool)},
        {"category": "telecom", "rate": 5, "cap": dict(pool)}])
    profile = make_profile({"office_supplies": 20000, "telecom": 15000})
    s = score([card], profile)
    bonus_5x = sum(a["usd_assigned"] for a in s["assignments"]
                   if a["rate"] == 5)
    assert bonus_5x == pytest.approx(25000)  # one pool, not 25k each
    fallback = sum(a["usd_assigned"] for a in s["assignments"]
                   if a["kind"] == "fallback")
    assert fallback == pytest.approx(10000)
    assert s["earnings"] == pytest.approx(25000 * 0.05 + 10000 * 0.01)


def test_min_transaction_category_line_uses_large_txn_share():
    card = synth_card(category_rewards=[
        {"category": "contractors_materials", "rate": 3,
         "min_transaction_usd": 5000}])
    profile = make_profile({"contractors_materials": 100000},
                           company={"large_txn_share": 0.3})
    s = score([card], profile)
    by_kind = {a["kind"]: a for a in s["assignments"]}
    assert by_kind["category"]["usd_assigned"] == pytest.approx(30000)
    assert by_kind["base"]["usd_assigned"] == pytest.approx(70000)
    assert s["earnings"] == pytest.approx(30000 * 0.03 + 70000 * 0.01)


def test_large_purchase_rate_category_agnostic_with_shared_pool():
    # Amex Business Platinum shape: 2x on $5k+ purchases sharing a pool with a
    # 2x category line.
    pool = {"period": "annual", "max_spend_usd": 50000, "fallback_rate": 1,
            "shared_cap_id": "bigpool"}
    card = synth_card(
        category_rewards=[{"category": "shipping", "rate": 2,
                           "cap": dict(pool)}],
        large_purchase_rate={"rate": 2, "min_transaction_usd": 5000,
                             "cap": dict(pool), "note": "any $5k+ purchase"})
    profile = make_profile({"shipping": 40000, "utilities": 100000},
                           company={"large_txn_share": 0.5})
    s = score([card], profile)
    # Shipping takes 40k of the pool at 2x; the large-purchase line can then
    # take only 10k more (pool), within the 50k qualifying utilities spend.
    lp = [a for a in s["assignments"] if a["kind"] == "large_purchase"]
    assert sum(a["usd_assigned"] for a in lp) == pytest.approx(10000)
    at_2x = sum(a["usd_assigned"] for a in s["assignments"] if a["rate"] == 2)
    assert at_2x == pytest.approx(50000)
    assert s["earnings"] == pytest.approx(50000 * 0.02 + 90000 * 0.01)


def test_large_purchase_zero_share_emits_no_line():
    card = synth_card(large_purchase_rate={
        "rate": 2.5, "min_transaction_usd": 5000, "note": "n"})
    profile = make_profile({"shipping": 100000})  # large_txn_share defaults 0
    s = score([card], profile)
    assert all(a["kind"] != "large_purchase" for a in s["assignments"])
    assert s["earnings"] == pytest.approx(1000.0)


def test_fraction_budget_shared_between_min_txn_lines():
    # A category min-txn line and the card-level large-purchase line may not
    # double-dip the same qualifying transactions of one bucket.
    card = synth_card(
        category_rewards=[{"category": "shipping", "rate": 3,
                           "min_transaction_usd": 5000}],
        large_purchase_rate={"rate": 2, "min_transaction_usd": 5000,
                             "note": "n"})
    profile = make_profile({"shipping": 100000},
                           company={"large_txn_share": 0.2})
    s = score([card], profile)
    qualifying = sum(a["usd_assigned"] for a in s["assignments"]
                     if a["kind"] in ("category", "large_purchase"))
    assert qualifying == pytest.approx(20000)  # 20% once, not twice
    assert s["earnings"] == pytest.approx(20000 * 0.03 + 80000 * 0.01)


def test_adaptive_top_n_picks_highest_spend_categories():
    # Business Gold shape: 4x top-2 of a menu, one $150k pool, then 1x.
    card = synth_card(adaptive_top_n={
        "n": 2, "rate": 4,
        "eligible_categories": ["advertising", "fuel_fleet", "dining",
                                "telecom"],
        "cap": {"period": "annual", "max_spend_usd": 150000,
                "fallback_rate": 1},
        "note": "top-2 each cycle"})
    profile = make_profile({"advertising": 90000, "dining": 50000,
                            "fuel_fleet": 20000, "shipping": 30000})
    s = score([card], profile)
    adaptive = {a["bucket"]: a for a in s["assignments"]
                if a["kind"] == "adaptive"}
    assert sorted(adaptive) == ["advertising", "dining"]  # top-2 by spend
    assert adaptive["advertising"]["rate"] == 4
    # fuel_fleet (not chosen) and shipping (not eligible) earn base.
    base = {a["bucket"] for a in s["assignments"] if a["kind"] == "base"}
    assert {"fuel_fleet", "shipping"} <= base
    assert s["earnings"] == pytest.approx(
        140000 * 0.04 + 50000 * 0.01)


def test_adaptive_top_n_pool_overflows_to_fallback():
    card = synth_card(adaptive_top_n={
        "n": 2, "rate": 4,
        "eligible_categories": ["advertising", "dining", "telecom"],
        "cap": {"period": "annual", "max_spend_usd": 100000,
                "fallback_rate": 1},
        "note": "top-2"})
    profile = make_profile({"advertising": 90000, "dining": 50000})
    s = score([card], profile)
    at_4x = sum(a["usd_assigned"] for a in s["assignments"] if a["rate"] == 4)
    assert at_4x == pytest.approx(100000)  # one pool across both lines
    assert s["earnings"] == pytest.approx(100000 * 0.04 + 40000 * 0.01)


# ---------------------------------------------------------------------------
# Fees: pricing models, seats, refunds
# ---------------------------------------------------------------------------

def test_annual_fee_and_first_year_waived():
    card = synth_card(pricing={"model": "annual_fee", "annual_fee_usd": 150,
                               "first_year_waived": True,
                               "foreign_transaction_pct": 0})
    profile = make_profile({"shipping": 10000})
    s = score([card], profile)
    assert s["ongoing_fee"] == pytest.approx(150.0)
    assert s["year1_fee"] == pytest.approx(0.0)


def test_fee_refund_spend_threshold():
    card = synth_card(pricing={"model": "annual_fee", "annual_fee_usd": 150,
                               "fee_refund_spend_usd": 150000,
                               "foreign_transaction_pct": 0})
    low = make_profile({"shipping": 100000})
    high = make_profile({"shipping": 200000})
    assert score([card], low)["ongoing_fee"] == pytest.approx(150.0)
    s = score([card], high)
    assert s["ongoing_fee"] == pytest.approx(0.0)
    assert s["fees"]["synth"]["fee_refunded"] is True


def test_per_seat_free_tier_scores_zero():
    card = synth_card(pricing={"model": "per_seat", "free_tier": True,
                               "per_seat_monthly_usd": 15,
                               "platform_fee_note": "paid tier buys software",
                               "foreign_transaction_pct": 0})
    profile = make_profile({"shipping": 50000},
                           company={"employee_card_seats": 10})
    s = score([card], profile)
    assert s["ongoing_fee"] == pytest.approx(0.0)
    assert s["year1_fee"] == pytest.approx(0.0)


def test_seat_fees_charged_on_workhorse_only():
    # Two cards with paid seats; seats sit on the card winning the most spend.
    big = synth_card(id="big", base_rate=2,
                     employee_cards={"fee_usd": 95})
    small = synth_card(id="small", base_rate=1,
                       employee_cards={"fee_usd": 400})
    profile = make_profile({"shipping": 100000},
                           company={"employee_card_seats": 3})
    s = score([big, small], profile)
    assert s["workhorse_id"] == "big"
    assert s["fees"]["big"]["seat_fees_usd"] == pytest.approx(3 * 95)
    assert s["fees"]["small"]["seat_fees_usd"] == pytest.approx(0.0)
    assert s["ongoing_fee"] == pytest.approx(285.0)


# ---------------------------------------------------------------------------
# Pooling, gateways, cpp
# ---------------------------------------------------------------------------

def test_personal_premium_card_unlocks_transfers():
    card = synth_card(currency={"type": "points", "program": "chase_ur"})
    without = make_profile({"shipping": 10000})
    with_sapphire = make_profile({"shipping": 10000},
                                 personal={"premium_cards_held":
                                           ["sapphire_preferred"]})
    s0 = score([card], without)
    s1 = score([card], with_sapphire)
    # Floor 1.0cpp standalone; avg 1.5cpp once the personal Sapphire unlocks.
    assert s0["earnings"] == pytest.approx(10000 * 0.01)
    assert s1["earnings"] == pytest.approx(10000 * 0.015)


def test_business_gateway_unlocks_sibling_card():
    earner = synth_card(id="earner",
                        currency={"type": "points", "program": "chase_ur"})
    gateway = synth_card(id="gateway", unlocks_transfers=True,
                         currency={"type": "points", "program": "chase_ur"},
                         base_rate=0.5)
    profile = make_profile({"shipping": 10000})
    s = score([earner, gateway], profile)
    earner_earn = sum(a["usd_value"] for a in s["assignments"]
                      if a["card_id"] == "earner")
    assert earner_earn == pytest.approx(10000 * 0.015)


def test_pooling_break_stays_at_floor_even_with_gateway():
    # Ink Premier shape: UR-denominated, program_combinable false.
    broken = synth_card(id="broken",
                        currency={"type": "points", "program": "chase_ur"},
                        base_rate=2,
                        pooling={"program_combinable": False,
                                 "note": "cannot combine or transfer"})
    profile = make_profile({"shipping": 10000},
                           personal={"premium_cards_held":
                                     ["sapphire_preferred"]})
    s = score([broken], profile)
    # 2x at the 1.0 floor, never 1.5 avg.
    assert s["earnings"] == pytest.approx(10000 * 0.02)


def test_pooling_break_gateway_grants_nothing():
    broken_gateway = synth_card(
        id="bg", unlocks_transfers=True,
        currency={"type": "points", "program": "chase_ur"},
        pooling={"program_combinable": False, "note": "n"})
    profile = make_profile({"shipping": 1000})
    assert opt.unlocked_programs([broken_gateway], profile) == frozenset()


# ---------------------------------------------------------------------------
# Bonuses and credits
# ---------------------------------------------------------------------------

def test_bonus_feasibility_uses_routed_spend():
    card = synth_card(signup_bonus={"value": {"usd": 1000},
                                    "spend_requirement_usd": 8000,
                                    "window_months": 3})
    thin = make_profile({"shipping": 20000})    # 5k in 3mo < 8k
    thick = make_profile({"shipping": 40000})   # 10k in 3mo >= 8k
    assert score([card], thin)["bonuses"]["synth"]["value"] == 0.0
    assert score([card], thick)["bonuses"]["synth"]["value"] == pytest.approx(1000.0)


def test_bonus_seat_exclusion_note_when_flag_false():
    card = synth_card(signup_bonus={"value": {"usd": 500},
                                    "spend_requirement_usd": 1000,
                                    "window_months": 3},
                      employee_cards={"fee_usd": 0,
                                      "spend_counts_toward_bonus": False})
    profile = make_profile({"shipping": 100000},
                           company={"employee_card_seats": 5})
    b = score([card], profile)["bonuses"]["synth"]
    assert b["value"] == pytest.approx(500.0)
    assert "excludes employee-card spend" in b["note"]


def test_bonus_tiers_cumulative():
    card = synth_card(signup_bonus={
        "value": {"usd": 500}, "spend_requirement_usd": 3000,
        "window_months": 6,
        "tiers": [{"value": {"usd": 250}, "spend_requirement_usd": 6000}]})
    mid = make_profile({"shipping": 8000})    # 4k in window: base only
    high = make_profile({"shipping": 16000})  # 8k in window: both
    assert score([card], mid)["bonuses"]["synth"]["value"] == pytest.approx(500.0)
    assert score([card], high)["bonuses"]["synth"]["value"] == pytest.approx(750.0)


def test_single_fee_credit_claimed_once_per_portfolio():
    credit = {"name": "Global Entry credit", "amount_usd": 120,
              "period": "every_4_years", "usage_keys": ["global_entry_tsa"],
              "realistic_capture_rate_note": "n"}
    a = synth_card(id="a", credits=[dict(credit)])
    b = synth_card(id="b", credits=[dict(credit)])
    profile = make_profile({"shipping": 10000},
                           confirmed_usage=["global_entry_tsa"])
    s = score([a, b], profile)
    values = sorted(c["value"] for c in s["credits"])
    assert values[0] == 0.0 and values[1] > 0.0
    assert any("once per person" in c["note"] for c in s["credits"])


def test_unlock_spend_credit_gates_on_card_routed_spend():
    card = synth_card(credits=[{
        "name": "Flight credit", "amount_usd": 200, "period": "annual",
        "usage_keys": ["delta"], "unlock_spend_usd": 10000,
        "realistic_capture_rate_note": "n"}])
    thin = make_profile({"shipping": 5000}, confirmed_usage=["delta"])
    thick = make_profile({"shipping": 20000}, confirmed_usage=["delta"])
    assert score([card], thin)["credits"][0]["value"] == 0.0
    assert score([card], thick)["credits"][0]["value"] == pytest.approx(
        200 * 0.95)


# ---------------------------------------------------------------------------
# Reporting: blended rate, float, output shape
# ---------------------------------------------------------------------------

def test_blended_rate_and_float_summary():
    card = synth_card(base_rate=2,
                      float_days={"grace_days": 60, "note": "60-day terms"})
    profile = make_profile({"shipping": 100000})
    ds = synth_dataset([card])
    buckets = opt.build_buckets(profile, ds["merchants"], ds["categories"])
    p = opt.assemble_portfolio({"cards": ["synth"]}, {"synth": card}, profile,
                               ds["programs"], buckets, ds["issuer_rules"],
                               AS_OF)
    assert p["blended_rate_pct"] == pytest.approx(2.0)
    assert p["float_days"]["cards"][0]["grace_days"] == 60
    assert p["float_days"]["spend_weighted_avg_days"] == pytest.approx(60.0)
    assert p["workhorse_card"] == "synth"


def test_fee_breakdown_in_bundle():
    card = synth_card(pricing={"model": "annual_fee", "annual_fee_usd": 95,
                               "foreign_transaction_pct": 0},
                      employee_cards={"fee_usd": 95})
    profile = make_profile({"shipping": 50000},
                           company={"employee_card_seats": 2})
    ds = synth_dataset([card])
    buckets = opt.build_buckets(profile, ds["merchants"], ds["categories"])
    p = opt.assemble_portfolio({"cards": ["synth"]}, {"synth": card}, profile,
                               ds["programs"], buckets, ds["issuer_rules"],
                               AS_OF)
    fees = p["per_card"]["synth"]["fees"]
    assert fees["annual_fee_usd"] == 95
    assert fees["seat_fees_usd"] == pytest.approx(190.0)
    assert fees["ongoing_usd"] == pytest.approx(285.0)
    assert any("employee seat" in n for n in fees["notes"])
    assert p["ongoing_net"] == pytest.approx(50000 * 0.01 - 285.0)


# ---------------------------------------------------------------------------
# Search, evaluate, augment
# ---------------------------------------------------------------------------

def test_search_respects_amex_limit():
    rules = {"amex": {"credit_card_limit": 5, "charge_exempt": True},
             "test-bank": {}}
    cards = [synth_card(id=f"r{i}", issuer="amex", base_rate=2 + i * 0.1)
             for i in range(3)]
    ds = synth_dataset(cards, issuer_rules=rules)
    profile = make_profile({"shipping": 10000},
                           personal={"amex_credit_cards": 3}, max_cards=3)
    ranked = opt.search(cards, profile, ds["programs"], ds["merchants"],
                        ds["categories"], ds["issuer_rules"], AS_OF)
    # 3 held + at most 2 recommended revolving Amex cards → no 3-card combos.
    assert all(len(r["cards"]) <= 2 for r in ranked)


def test_run_bundle_shape_and_determinism():
    profile_kwargs = dict(
        spend={"advertising": 240000, "shipping": 120000,
               "software_saas": 60000, "travel_flights": 30000,
               "travel_hotels": 24000, "dining": 18000,
               "office_supplies": 12000, "telecom": 9000, "other": 87000},
        company={"employee_card_seats": 4, "large_txn_share": 0.2},
        personal={"five24_count": 2, "amex_credit_cards": 1,
                  "premium_cards_held": ["sapphire_preferred"]},
        max_cards=3)
    b1 = opt.run(DATASET, make_profile(**profile_kwargs), AS_OF, top=3)
    b2 = opt.run(DATASET, make_profile(**profile_kwargs), AS_OF, top=3)
    assert opt.render_json(b1) == opt.render_json(b2)
    for key in ("as_of", "company", "personal", "cpp_table",
                "policy_constants", "cards_total", "cards_eligible",
                "excluded", "best_by_size", "portfolios"):
        assert key in b1
    p = b1["portfolios"][0]
    for key in ("cards", "ongoing_net", "year1_net", "blended_rate_pct",
                "workhorse_card", "float_days", "application_notes",
                "per_card"):
        assert key in p
    json.loads(opt.render_json(b1))  # valid JSON
    opt.render_text(b1)              # renders without raising


def test_run_golden_dtc_top_portfolio():
    """Golden: DTC-heavy $600k profile with a personal Sapphire. Pins the
    rank-1 portfolio and its headline numbers against the real corpus
    (as of 2026-07-17). Update deliberately when the corpus changes."""
    profile = make_profile(
        spend={"advertising": 240000, "shipping": 120000,
               "software_saas": 60000, "travel_flights": 30000,
               "travel_hotels": 24000, "dining": 18000,
               "office_supplies": 12000, "telecom": 9000, "other": 87000},
        company={"employee_card_seats": 4, "large_txn_share": 0.2},
        personal={"five24_count": 2, "amex_credit_cards": 1,
                  "premium_cards_held": ["sapphire_preferred"]},
        max_cards=3)
    bundle = opt.run(DATASET, profile, AS_OF, top=1)
    p = bundle["portfolios"][0]
    assert p["cards"] == ["ink-business-cash", "ink-business-unlimited",
                          "sapphire-reserve-for-business"]
    assert p["ongoing_net"] == pytest.approx(23737.50)
    assert p["year1_net"] == pytest.approx(28737.50)
    assert p["blended_rate_pct"] == pytest.approx(3.96)


def test_run_golden_saas_startup_no_pg():
    """Golden: SaaS startup that refuses a personal guarantee — only the
    no-PG fintech tier survives the approval filter."""
    profile = make_profile(
        spend={"software_saas": 120000, "advertising": 60000,
               "dining": 12000, "travel_flights": 20000},
        company={"accepts_personal_guarantee": False, "owner_fico_tier": None,
                 "entity_type": "corp", "cash_balance_usd": 120000,
                 "has_funding": True},
        max_cards=2)
    bundle = opt.run(DATASET, profile, AS_OF, top=1)
    eligible_ids = {c["id"] for c in DATASET["cards"]} - {
        e["id"] for e in bundle["excluded"]}
    assert eligible_ids == {"bill-divvy-card", "brex-card",
                            "ramp-corporate-card"}
    # Divvy's weekly 7x dining / 2x software tier wins outright; its 1.5x base
    # ties Ramp's flat 1.5%, so adding Ramp adds nothing and the deterministic
    # tie-break (smaller card tuple) keeps the single-card portfolio on top.
    assert bundle["portfolios"][0]["cards"] == ["bill-divvy-card"]


def test_run_golden_524_blocked_chase():
    """Golden: an owner at 5/24 loses every Chase card."""
    profile = make_profile(
        spend={"shipping": 50000, "advertising": 50000},
        personal={"five24_count": 5}, max_cards=2)
    bundle = opt.run(DATASET, profile, AS_OF, top=1)
    excluded_524 = {e["id"] for e in bundle["excluded"]
                    if "5/24" in e["reason"]}
    chase_active = {c["id"] for c in DATASET["cards"]
                    if c["issuer"] == "chase"
                    and c.get("availability", "active") != "discontinued"}
    assert excluded_524 == chase_active
    assert not any(c.startswith("ink") or "sapphire" in c
                   for c in bundle["portfolios"][0]["cards"])


def test_evaluate_scores_hand_picked_set_bypassing_filters():
    # A no-PG company can still hand-score a PG card in Manual mode.
    profile = make_profile(
        {"shipping": 50000},
        company={"accepts_personal_guarantee": False, "owner_fico_tier": None,
                 "cash_balance_usd": 30000})
    bundle = opt.evaluate(DATASET, profile, AS_OF,
                          ["ink-business-unlimited", "ramp-corporate-card"])
    assert bundle["portfolios"][0]["cards"] == ["ink-business-unlimited",
                                                "ramp-corporate-card"]
    assert bundle["best_by_size"][0]["size"] == 2


def test_evaluate_rejects_bad_input():
    profile = make_profile({"shipping": 1000})
    with pytest.raises(opt.InputError):
        opt.evaluate(DATASET, profile, AS_OF, [])
    with pytest.raises(opt.InputError):
        opt.evaluate(DATASET, profile, AS_OF, ["nope"])
    with pytest.raises(opt.InputError):
        opt.evaluate(DATASET, profile, AS_OF,
                     ["ink-business-cash", "ink-business-cash"])


def test_augment_returns_added_card_honoring_filters():
    profile = make_profile(
        {"advertising": 100000, "shipping": 50000},
        personal={"premium_cards_held": ["sapphire_preferred"]}, max_cards=3)
    bundle = opt.augment(DATASET, profile, AS_OF, ["ink-business-unlimited"])
    assert "added_card" in bundle
    assert bundle["added_card"] != "ink-business-unlimited"
    assert bundle["added_card"] in {c["id"] for c in DATASET["cards"]}
    assert len(bundle["portfolios"][0]["cards"]) == 2


def test_exclude_cards_veto():
    profile = make_profile(
        spend={"advertising": 240000, "shipping": 120000,
               "software_saas": 60000, "travel_flights": 30000,
               "travel_hotels": 24000, "dining": 18000,
               "office_supplies": 12000, "telecom": 9000, "other": 87000},
        company={"employee_card_seats": 4, "large_txn_share": 0.2},
        personal={"five24_count": 2, "amex_credit_cards": 1,
                  "premium_cards_held": ["sapphire_preferred"]},
        exclude_cards=["sapphire-reserve-for-business"], max_cards=3)
    bundle = opt.run(DATASET, profile, AS_OF, top=1)
    assert "sapphire-reserve-for-business" not in bundle["portfolios"][0]["cards"]
    assert any(e["id"] == "sapphire-reserve-for-business"
               and "excluded by you" in e["reason"]
               for e in bundle["excluded"])


def test_search_budget_guard():
    cards = [synth_card(id=f"c{i:03d}") for i in range(300)]
    ds = synth_dataset(cards)
    profile = make_profile({"shipping": 1000}, max_cards=5)
    with pytest.raises(opt.DataError, match="MAX_SCORED_SUBSETS"):
        opt.search(cards, profile, ds["programs"], ds["merchants"],
                   ds["categories"], ds["issuer_rules"], AS_OF)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("spend: {}\n")
    assert opt.main(["--profile", str(bad)]) == 1
    good = tmp_path / "good.yaml"
    good.write_text(
        "spend: {shipping: 50000}\n"
        "company: {entity_type: llc, accepts_personal_guarantee: true, "
        "owner_fico_tier: excellent}\n")
    assert opt.main(["--profile", str(good), "--as-of", "2026-07-17",
                     "--top", "1", "--json"]) == 0
    out = capsys.readouterr().out
    bundle = json.loads(out)
    assert bundle["as_of"] == "2026-07-17"
    assert bundle["portfolios"]
