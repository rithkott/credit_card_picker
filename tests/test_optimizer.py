"""Golden tests for scripts/optimize.py (spec: docs/plans/02-optimizer.md §9).

All expected values are hand-computed from the seed card data and the policy
constants; if a policy constant or seed card changes, these numbers change too.
Run: python3 -m unittest discover tests
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import optimize as opt

# Frozen copy of the 8-seed-card dataset (tests/fixtures/data/, taken from the
# last revision where the goldens were hand-computed) — dataset growth must
# never invalidate these numbers again (plan 02.5 §5). Assigning the module
# paths also routes opt.main() (TestDeterminism) through the fixture.
FIXTURE_DATA = Path(__file__).resolve().parent / "fixtures" / "data"
opt.CARDS_DIR = FIXTURE_DATA / "cards"
opt.META_DIR = FIXTURE_DATA / "meta"

AS_OF = date(2026, 7, 3)  # matches seed-card verification dates: no staleness
DATASET = opt.load_dataset()


def make_profile(spend, merchant_spend=None, **user):
    raw = {"spend": spend, "user": {"credit_tier": "excellent", **user}}
    if merchant_spend:
        raw["merchant_spend"] = merchant_spend
    return opt.parse_profile(raw, DATASET)


def seed_card(card_id):
    return next(c for c in DATASET["cards"] if c["id"] == card_id)


def score(cards, profile):
    cards = [seed_card(c) if isinstance(c, str) else c for c in cards]
    buckets = opt.build_buckets(profile, DATASET["merchants"], DATASET["categories"])
    return opt.score_portfolio(cards, profile, DATASET["programs"], buckets, AS_OF)


def synth_card(**overrides):
    card = {
        "id": "synth", "name": "Synthetic", "issuer": "test", "network": "visa",
        "currency": {"type": "cash", "program": "cash"}, "base_rate": 1,
        "category_rewards": [], "merchant_rewards": [], "credits": [],
        "signup_bonus": None,
        "fees": {"annual_fee_usd": 0, "foreign_transaction_pct": 0},
        "approval": {"credit_tier": "good"}, "benefit_flags": [],
        "verification": {"last_verified_date": "2026-07-03",
                         "verified_by": "test", "confidence": "high"},
    }
    card.update(overrides)
    return card


# $30,000/yr profile from spec §4.3 — the first golden test.
P30K = {"groceries": 8000, "dining": 5000, "other": 17000}

# The Gold fixture card's four credit services, confirmed (plan 07).
GOLD_KEYS = ["dunkin", "grubhub", "resy", "uber"]


class TestSingleCardGolden(unittest.TestCase):
    """All 7 seed cards single-card, both modes (spec §9)."""

    def test_double_cash_worked_example(self):
        # Spec §4.3: ongoing $600, year-1 $800. citi_typ is
        # transfer_gateway_required and no premium TY card is in the portfolio,
        # so standalone Double Cash stays at floor 1.0cpp — its avg-cpp upside
        # needs a Strata Premier/Elite pairing (plan 08).
        prof = make_profile(P30K)
        r = score(["double-cash"], prof)
        self.assertAlmostEqual(r["ongoing_net"], 600.0)
        self.assertAlmostEqual(r["year1_net"], 800.0)

    def test_active_cash(self):
        # Flat 2% cash: 30000*2% = 600; +$200 bonus year 1. Identical both modes.
        prof = make_profile(P30K)
        r = score(["active-cash"], prof)
        self.assertAlmostEqual(r["ongoing_net"], 600.0)
        self.assertAlmostEqual(r["year1_net"], 800.0)

    def test_blue_cash_preferred(self):
        # groceries 6% on 6000 cap = 360, 1% fallback on 2000 = 20,
        # base 1% on dining+other 22000 = 220 → 600 earn; Disney credit $0
        # (no streaming spend); ongoing 600-95=505; year1 600+250-0(waived)=850.
        prof = make_profile(P30K)
        r = score(["blue-cash-preferred"], prof)
        self.assertAlmostEqual(r["ongoing_net"], 505.0)
        self.assertAlmostEqual(r["year1_net"], 850.0)
        disney = [c for c in r["credits"] if "Disney" in c["name"]][0]
        self.assertEqual(disney["value"], 0.0)

    def test_blue_cash_preferred_grocery_cap(self):
        # 10000 groceries: 6000@6% + 4000@1% = 400; ongoing 400-95 = 305.
        prof = make_profile({"groceries": 10000})
        r = score(["blue-cash-preferred"], prof)
        self.assertAlmostEqual(r["earnings"], 400.0)
        self.assertAlmostEqual(r["ongoing_net"], 305.0)

    def test_amex_gold(self):
        # amex_mr avg cpp (0.6+1.9)/2 = 1.25 (transfers natively — no gate):
        # dining 5000*4*.0125=250, groceries 8000*4*.0125=400,
        # other 17000*.0125=212.5 → 862.5 earn.
        # All four credit services confirmed → CONFIRMED_CREDIT_CAPTURE.
        # Credits vs dining tracker 5000: dining 10*12*.8=96, Uber $0 (no transit
        # spend), Resy 50*2*.9=90, Dunkin 7*12*.8=67.2 → 253.2.
        # ongoing 862.5+253.2-325=790.7; bonus 60000*.0125=750 → year1 1540.7.
        prof = make_profile(P30K, confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof)
        self.assertAlmostEqual(r["earnings"], 862.5)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 253.2)
        self.assertAlmostEqual(r["ongoing_net"], 790.7)
        self.assertAlmostEqual(r["year1_net"], 1540.7)

    def test_amex_gold_unconfirmed(self):
        # No confirmed usage: every merchant credit is $0 with an explicit
        # reason — the card is just its earn minus the fee.
        prof = make_profile(P30K)
        r = score(["gold"], prof)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 0.0)
        for c in r["credits"]:
            self.assertIn("requires confirmed use", c["note"])
        self.assertAlmostEqual(r["ongoing_net"], 862.5 - 325.0)

    def test_sapphire_preferred_portal_assumed(self):
        # Portal use is assumed (no questionnaire gate): the portal-only 5x
        # travel_other line applies at 5*0.75=3.75x. CSP is its own UR
        # gateway → avg cpp (1.0+2.0)/2 = 1.5: earnings 447.5*1.5 = 671.25.
        # The hotel credit is keyless (category-gated only) → conservative
        # CREDIT_CAPTURE: min(50*0.9, 2000)=45; ongoing 671.25+45-95=621.25;
        # bonus 60000*.015=900 → year1 1521.25.
        prof = make_profile({"dining": 4000, "groceries": 6000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 7000})
        r = score(["sapphire-preferred"], prof)
        self.assertAlmostEqual(r["earnings"], 671.25)
        self.assertAlmostEqual(r["ongoing_net"], 621.25)
        self.assertAlmostEqual(r["year1_net"], 1521.25)
        notes = "; ".join(a.get("note", "") for a in r["assignments"])
        self.assertIn("use assumed", notes)

    def test_freedom_flex_rotating_activated(self):
        # Coverage model: a rotating category is featured ~1/6 of the year
        # (N = len(ROTATING_ELIGIBLE)), so the 5x line may take only 1/6 of
        # each eligible bucket, within the $1,500*4 = $6,000/yr cap room:
        # gas 2000/6 + groceries 6000/6 + dining 4000/6 = $2,000 @5% = $100.
        # Dining 3x on the remaining 4000*5/6 = 10000/3 → $100; rotating
        # fallback 1x on groceries 5000 + gas 5000/3 → $200/3; base other
        # 8000@1% = $80. earnings = 1040/3 ≈ 346.67. Bonus $200 → year1
        # 1640/3 ≈ 546.67.
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000})
        r = score(["freedom-flex"], prof)
        rotating = {a["bucket"]: a["usd_assigned"] for a in r["assignments"]
                    if a["kind"] == "rotating"}
        self.assertEqual(set(rotating), {"dining", "gas", "groceries"})
        self.assertAlmostEqual(rotating["gas"], 2000 / 6)
        self.assertAlmostEqual(rotating["groceries"], 1000.0)
        self.assertAlmostEqual(rotating["dining"], 4000 / 6)
        self.assertAlmostEqual(r["earnings"], 1040 / 3)
        self.assertAlmostEqual(r["ongoing_net"], 1040 / 3)
        self.assertAlmostEqual(r["year1_net"], 1040 / 3 + 200)

    def test_freedom_flex_rotating_not_activated(self):
        # Rotating line drops to fallback 1x. The 1x spend now splits between
        # the diluted rotating line (1/6 of each bucket) and the above-cap
        # fallback line at the same rate, so the total is unchanged:
        # groceries+gas 8000@1% + dining 4000@3% + other 8000@1% = 280.
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000},
                            activates_rotating=False)
        r = score(["freedom-flex"], prof)
        self.assertAlmostEqual(r["ongoing_net"], 280.0)

    def test_freedom_flex_rotating_cap_binds(self):
        # When 1/6 of a bucket exceeds the annualized cap, the $6,000/yr room
        # wins: groceries 60000/6 = 10000 → clamped to 6000 @5% = $300; the
        # above-cap fallback earns 1% on the other 54000 = $540 → 840 total.
        prof = make_profile({"groceries": 60000})
        r = score(["freedom-flex"], prof)
        rotating = [a for a in r["assignments"] if a["kind"] == "rotating"]
        self.assertEqual([(a["bucket"], a["usd_assigned"]) for a in rotating],
                         [("groceries", 6000.0)])
        self.assertAlmostEqual(r["earnings"], 840.0)

    def test_venture_x_portal_assumed(self):
        # Portal use is assumed; avg cpp 1.1: hotels 2000@10*0.75=7.5x*.011=165,
        # flights 3000@5*0.75=3.75x*.011=123.75, base 15000@2.2%=330 → 618.75.
        # Credits: the travel credit is keyless (category-gated only) →
        # CREDIT_CAPTURE: min(300*0.9, travel_other 1000)=270, plus automatic
        # anniversary 100 = 370. ongoing 618.75+370-395=593.75;
        # bonus 75000*.011=825 → year1 1418.75.
        prof = make_profile({"travel_flights": 3000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 14000})
        r = score(["venture-x"], prof)
        self.assertAlmostEqual(r["earnings"], 618.75)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 370.0)
        self.assertAlmostEqual(r["ongoing_net"], 593.75)
        self.assertAlmostEqual(r["year1_net"], 1418.75)


class TestCreditsAndBonus(unittest.TestCase):
    def test_credit_gating_no_dining_spend(self):
        # Even with every service confirmed, the category gate still applies:
        # without dining/transit spend all four Gold credits are $0 with reasons.
        prof = make_profile({"groceries": 8000, "other": 22000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 0.0)
        for c in r["credits"]:
            self.assertIn("no remaining spend", c["note"])

    def test_stacked_credits_capped_by_real_spend(self):
        # Only $150 of dining spend, all services confirmed: file order draws
        # dining min(10*12*.8=96, 150)=96, then Resy min(50*2*.9=90,
        # remaining 54)=54, then Dunkin $0.
        prof = make_profile({"dining": 150, "other": 30000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof)
        by_name = {c["name"]: c["value"] for c in r["credits"]}
        self.assertAlmostEqual(by_name["Dining credit (Grubhub, Cheesecake Factory, etc.)"], 96.0)
        self.assertAlmostEqual(by_name["Resy dining credit"], 54.0)
        self.assertAlmostEqual(by_name["Dunkin' credit"], 0.0)

    def test_bonus_infeasible_at_low_volume(self):
        # Gold needs 6000 in 6 months; 1000/yr * 0.5 = 500 < 6000 → $0.
        prof = make_profile({"other": 1000})
        r = score(["gold"], prof)
        self.assertEqual(r["bonuses"]["gold"]["value"], 0.0)
        self.assertIn("unreachable", r["bonuses"]["gold"]["note"])

    def test_bonus_expiry(self):
        bonus = {"value": {"usd": 100}, "spend_requirement_usd": 0,
                 "window_months": 3, "expires": "2026-01-01"}
        prof = make_profile({"other": 10000})
        expired = score([synth_card(signup_bonus=bonus)], prof)
        self.assertEqual(expired["bonuses"]["synth"]["value"], 0.0)
        self.assertIn("expired", expired["bonuses"]["synth"]["note"])
        live = dict(bonus, expires="2026-12-31")
        ok = score([synth_card(signup_bonus=live)], prof)
        self.assertEqual(ok["bonuses"]["synth"]["value"], 100.0)


class TestSyntheticFixtures(unittest.TestCase):
    """merchant_rewards and closed_loop — no seed card uses them (spec §9)."""

    def test_merchant_line_beats_same_card_category_line(self):
        card = synth_card(
            merchant_rewards=[{"merchant": "amazon", "rate": 5}],
            category_rewards=[{"category": "online_shopping", "rate": 2}])
        prof = make_profile({"online_shopping": 4000, "other": 1000},
                            merchant_spend={"amazon": 3000})
        r = score([card], prof)
        # amazon 3000@5% + residual 1000@2% + other 1000@1% = 150+20+10 = 180
        self.assertAlmostEqual(r["earnings"], 180.0)

    def test_category_line_covers_carveout_without_merchant_line(self):
        card = synth_card(category_rewards=[{"category": "online_shopping", "rate": 3}])
        prof = make_profile({"online_shopping": 4000, "other": 1000},
                            merchant_spend={"amazon": 3000})
        r = score([card], prof)
        # (3000 carve-out + 1000 residual)@3% + 1000@1% = 130
        self.assertAlmostEqual(r["earnings"], 130.0)

    def test_closed_loop_restriction_and_unassigned_spend(self):
        card = synth_card(base_rate=2, closed_loop={"merchants": ["costco"]})
        prof = make_profile({"groceries": 5000, "other": 1000},
                            merchant_spend={"costco": 3000})
        r = score([card], prof)
        # Only the costco carve-out is assignable: 3000@2% = 60.
        self.assertAlmostEqual(r["earnings"], 60.0)
        self.assertEqual(r["unassigned"], {"groceries": 2000.0, "other": 1000.0})


class TestSharedCaps(unittest.TestCase):
    """shared_cap_id: multiple reward entries drawing one combined spend pool."""

    def shared_cap_card(self, **cap_extra):
        cap = {"period": "annual", "max_spend_usd": 5000, "fallback_rate": 1, **cap_extra}
        return synth_card(category_rewards=[
            {"category": "gas", "rate": 2, "cap": dict(cap)},
            {"category": "groceries", "rate": 2, "cap": dict(cap)}])

    def test_shared_pool_limits_combined_spend(self):
        # gas 3000@2% drains the pool to 2000; groceries gets 2000@2%, the
        # remaining 2000 groceries falls back to 1%; other 1000@1%.
        card = self.shared_cap_card(shared_cap_id="gas_grocery")
        prof = make_profile({"gas": 3000, "groceries": 4000, "other": 1000})
        r = score([card], prof)
        self.assertAlmostEqual(r["earnings"], 130.0)

    def test_independent_caps_do_not_share(self):
        # Same card without the shared id: each category gets its own $5,000
        # room, so all 7000 elevated spend earns 2%.
        card = self.shared_cap_card()
        prof = make_profile({"gas": 3000, "groceries": 4000, "other": 1000})
        r = score([card], prof)
        self.assertAlmostEqual(r["earnings"], 150.0)


class TestCreditVariants(unittest.TestCase):
    def test_unlock_spend_reachable_and_not(self):
        credit = {"name": "flight credit", "amount_usd": 200, "period": "annual",
                  "unlock_spend_usd": 10000, "realistic_capture_rate_note": "x"}
        card = synth_card(credits=[credit])
        r = score([card], make_profile({"other": 12000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 200.0)  # no category → face
        r = score([card], make_profile({"other": 8000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 0.0)
        self.assertIn("unreachable", r["credits"][0]["note"])

    def test_unlock_spend_is_per_period(self):
        # $10/month unlocked at $1,000/month: $6,000/yr total = $500/month < $1,000.
        credit = {"name": "monthly credit", "amount_usd": 10, "period": "monthly",
                  "unlock_spend_usd": 1000, "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 6000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 0.0)

    def test_points_credit_valued_by_cpp(self):
        credit = {"name": "anniversary points", "amount_points": 10000,
                  "period": "annual", "realistic_capture_rate_note": "automatic"}
        # unlocks_transfers: the card is its own UR gateway, so the avg
        # (1.0+2.0)/2 = 1.5cpp applies standalone; without the gateway flag
        # the same credit floors at 1.0cpp.
        card = synth_card(currency={"type": "points", "program": "chase_ur"},
                          unlocks_transfers=True, credits=[credit])
        prof = make_profile({"other": 5000})
        self.assertAlmostEqual(score([card], prof)["credits"][0]["value"], 150.0)
        gated = synth_card(currency={"type": "points", "program": "chase_ur"},
                           credits=[credit])
        self.assertAlmostEqual(score([gated], prof)["credits"][0]["value"], 100.0)

    def test_expired_credit_valued_zero(self):
        # Promo credits carry `expires`; past the as-of date they are $0 with
        # an explanatory note, mirroring the signup-bonus expiry rule.
        credit = {"name": "promo credit", "amount_usd": 10, "period": "monthly",
                  "category": "streaming", "expires": "2026-12-31",
                  "realistic_capture_rate_note": "x"}
        card = synth_card(credits=[credit])
        prof = make_profile({"streaming": 1200, "other": 5000})
        live = score([card], prof)  # AS_OF 2026-07-03: promo still live
        self.assertAlmostEqual(live["credits"][0]["value"], 60.0)  # 120 face × 0.5 capture
        buckets = opt.build_buckets(prof, DATASET["merchants"], DATASET["categories"])
        expired = opt.score_portfolio([card], prof, DATASET["programs"],
                                      buckets, date(2027, 1, 1))
        self.assertEqual(expired["credits"][0]["value"], 0.0)
        self.assertIn("expired 2026-12-31", expired["credits"][0]["note"])

    def test_in_kind_credit_always_haircut(self):
        # Uncategorized statement credits pay full face; in_kind gets the
        # period capture haircut even without a category (annual = 0.9).
        credit = {"name": "free night", "kind": "in_kind", "amount_usd": 150,
                  "period": "annual", "realistic_capture_rate_note": "estimate"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 135.0)


class TestConfirmedUsage(unittest.TestCase):
    """Plan 07: usage-gated credits and loyalty-aware point valuation."""

    def test_unconfirmed_usage_keys_credit_is_zero(self):
        credit = {"name": "ride credit", "amount_usd": 10, "period": "monthly",
                  "usage_keys": ["uber", "lyft"], "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertEqual(r["credits"][0]["value"], 0.0)
        self.assertIn("requires confirmed use of one of: uber, lyft",
                      r["credits"][0]["note"])

    def test_confirmed_uncategorized_coupon_gets_capture_not_face(self):
        # A confirmed merchant coupon is spendable only at that merchant —
        # face × CONFIRMED capture (annual 0.95), never the full-face path.
        credit = {"name": "gear credit", "amount_usd": 200, "period": "annual",
                  "usage_keys": ["lyft"], "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])],
                  make_profile({"other": 5000}, confirmed_usage=["lyft"]))
        self.assertAlmostEqual(r["credits"][0]["value"], 190.0)  # 200 × 0.95
        self.assertIn("confirmed: lyft", r["credits"][0]["note"])

    def test_any_one_confirmed_key_unlocks(self):
        credit = {"name": "ride credit", "amount_usd": 10, "period": "monthly",
                  "usage_keys": ["uber", "lyft"], "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])],
                  make_profile({"other": 5000}, confirmed_usage=["lyft"]))
        self.assertAlmostEqual(r["credits"][0]["value"], 96.0)  # 120 × 0.8

    def test_confirmed_credit_still_gated_by_category_spend(self):
        # Both gates stack: confirmed Uber credit with no transit spend is $0.
        credit = {"name": "uber credit", "amount_usd": 10, "period": "monthly",
                  "usage_keys": ["uber"], "category": "transit",
                  "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])],
                  make_profile({"other": 5000}, confirmed_usage=["uber"]))
        self.assertEqual(r["credits"][0]["value"], 0.0)
        self.assertIn("no remaining spend", r["credits"][0]["note"])

    def test_automatic_credit_pays_full_face(self):
        credit = {"name": "anniversary credit", "amount_usd": 100, "period": "annual",
                  "automatic": True, "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 100.0)
        self.assertIn("automatic", r["credits"][0]["note"])

    def test_confirmed_in_kind_uses_confirmed_capture(self):
        credit = {"name": "free night", "kind": "in_kind", "amount_usd": 150,
                  "period": "annual", "usage_keys": ["brandair"],
                  "realistic_capture_rate_note": "estimate"}
        card = synth_card(credits=[credit])
        prof = make_profile({"other": 5000}, confirmed_usage=["brandair"])
        r = score([card], prof)
        self.assertAlmostEqual(r["credits"][0]["value"], 142.5)  # 150 × 0.95
        # Unconfirmed, cashback-only prefs: brandair is not assumed → $0.
        unconfirmed = score([card], make_profile(
            {"other": 5000}, reward_preferences=["cashback"]))
        self.assertEqual(unconfirmed["credits"][0]["value"], 0.0)

    def brandair_card(self, **overrides):
        return synth_card(currency={"type": "points", "program": "brandair_miles"},
                          **overrides)

    def test_lockin_currency_floored_without_loyalty(self):
        # brandair_miles: floor 0.8, optimistic 1.5 → avg 1.15; loyalty_keys
        # [brandair]. Without confirmation → floor cpp (keep-but-devalue).
        prof = make_profile({"other": 10000})
        r = score([self.brandair_card()], prof)
        self.assertAlmostEqual(r["earnings"], 80.0)  # 10000 × 1x × 0.8cpp
        loyal = make_profile({"other": 10000}, confirmed_usage=["brandair"])
        r = score([self.brandair_card()], loyal)
        self.assertAlmostEqual(r["earnings"], 115.0)  # 10000 × 1x × avg 1.15cpp

    def test_ungated_transferables_get_avg_cpp(self):
        # amex_mr has a cashback path and transfers natively (no gateway
        # required) → never devalued by the loyalty gate: avg (0.6+1.9)/2.
        prof = make_profile({"other": 10000})
        mr = synth_card(currency={"type": "points", "program": "amex_mr"})
        r = score([mr], prof)
        self.assertAlmostEqual(r["earnings"], 125.0)  # 10000 × 1x × avg 1.25cpp

    def test_lockin_devalues_bonus_and_points_credits(self):
        bonus = {"value": {"points": 10000}, "spend_requirement_usd": 100,
                 "window_months": 3}
        credit = {"name": "anniversary miles", "amount_points": 5000,
                  "period": "annual", "realistic_capture_rate_note": "automatic"}
        card = self.brandair_card(signup_bonus=bonus, credits=[credit])
        prof = make_profile({"other": 10000})
        r = score([card], prof)
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 80.0)   # 10000 × 0.8cpp
        self.assertAlmostEqual(r["credits"][0]["value"], 40.0)        # 5000 × 0.8cpp
        loyal = make_profile({"other": 10000}, confirmed_usage=["brandair"])
        r = score([card], loyal)
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 115.0)  # avg 1.15cpp
        self.assertAlmostEqual(r["credits"][0]["value"], 57.5)

    def test_valuation_note_surfaced_in_bundle_and_text(self):
        dataset = {**{k: DATASET[k] for k in
                      ("categories", "merchants", "programs", "usage_questions",
                       "usage_keys")},
                   "cards": [self.brandair_card(id="brand", name="Brand")]}
        # accepts_brand_lockin: the lock-in filter would otherwise exclude the
        # brandair card before scoring — this test targets the valuation note.
        prof = make_profile({"other": 10000}, accepts_brand_lockin=True)
        bundle = opt.run(dataset, prof, AS_OF, 1)
        note = bundle["portfolios"][0]["per_card"]["brand"]["valuation_note"]
        self.assertIn("no confirmed loyalty", note)
        self.assertIn("brandair", note)
        self.assertIn("no confirmed loyalty", opt.render_text(bundle))
        self.assertIn("confirmed_usage", bundle)
        # Loyal user: no note.
        loyal = make_profile({"other": 10000}, accepts_brand_lockin=True,
                             confirmed_usage=["brandair"])
        bundle = opt.run(dataset, loyal, AS_OF, 1)
        self.assertNotIn("valuation_note", bundle["portfolios"][0]["per_card"]["brand"])
        self.assertEqual(bundle["confirmed_usage"], ["brandair"])

    def test_confirmed_capture_in_policy_constants(self):
        self.assertIn("CONFIRMED_CREDIT_CAPTURE", opt.policy_constants())


class TestAssumedUsage(unittest.TestCase):
    """Brand-loyalty split: airline/hotel usage keys (groups carrying
    assumed_reward_kind in usage-questions.yaml) are assumed usable for credit
    gating when the matching reward kind — or total_value — is in
    reward_preferences. The user is assumed to book whichever brand gives the
    best value; explicit confirmation now means brand loyalty."""

    CREDIT = {"name": "flight credit", "amount_usd": 100, "period": "annual",
              "usage_keys": ["brandair"], "realistic_capture_rate_note": "x"}

    def test_assumed_key_unlocks_credit_at_conservative_capture(self):
        # Fixture airlines group: assumed_reward_kind: flights. Default prefs
        # (total_value) imply flights → brandair assumed: 100 × 0.9, not the
        # confirmed 0.95, and the note says so.
        r = score([synth_card(credits=[dict(self.CREDIT)])],
                  make_profile({"other": 5000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 90.0)
        self.assertIn("assumed usable: brandair", r["credits"][0]["note"])

    def test_concrete_flights_pref_also_unlocks(self):
        r = score([synth_card(credits=[dict(self.CREDIT)])],
                  make_profile({"other": 5000}, reward_preferences=["flights"]))
        self.assertAlmostEqual(r["credits"][0]["value"], 90.0)

    def test_no_flights_pref_keeps_strict_gate(self):
        r = score([synth_card(credits=[dict(self.CREDIT)])],
                  make_profile({"other": 5000}, reward_preferences=["cashback"]))
        self.assertEqual(r["credits"][0]["value"], 0.0)
        self.assertIn("requires confirmed use", r["credits"][0]["note"])

    def test_confirmation_beats_assumption(self):
        # Loyal user: CONFIRMED_CREDIT_CAPTURE (0.95) wins over assumed (0.9).
        r = score([synth_card(credits=[dict(self.CREDIT)])],
                  make_profile({"other": 5000}, confirmed_usage=["brandair"]))
        self.assertAlmostEqual(r["credits"][0]["value"], 95.0)
        self.assertIn("confirmed: brandair", r["credits"][0]["note"])

    def test_non_loyalty_groups_never_assumed(self):
        # uber is in a group without assumed_reward_kind — strict gate stands
        # even in a total_value run.
        credit = {"name": "ride credit", "amount_usd": 100, "period": "annual",
                  "usage_keys": ["uber"], "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertEqual(r["credits"][0]["value"], 0.0)

    def test_assumption_never_unlocks_loyalty_cpp(self):
        # Point valuation is a loyalty question, not a usage question: a
        # merely-assumed brandair still prices at floor 0.8cpp (the companion
        # golden test_lockin_currency_floored_without_loyalty pins the same).
        card = synth_card(currency={"type": "points", "program": "brandair_miles"})
        r = score([card], make_profile({"other": 10000}))  # total_value default
        self.assertAlmostEqual(r["earnings"], 80.0)  # floor, not avg 1.15

    def test_parse_profile_derives_assumed_usage(self):
        prof = make_profile({"other": 5000})
        self.assertEqual(prof["user"]["assumed_usage"], ["brandair"])
        prof = make_profile({"other": 5000}, reward_preferences=["cashback"])
        self.assertEqual(prof["user"]["assumed_usage"], [])

    def test_assumed_usage_is_not_a_profile_input(self):
        with self.assertRaises(opt.InputError):
            make_profile({"other": 5000}, assumed_usage=["brandair"])

    def test_bundle_and_text_surface_assumed_usage(self):
        prof = make_profile({"other": 5000})
        bundle = opt.run(DATASET, prof, AS_OF, 1)
        self.assertEqual(bundle["assumed_usage"], ["brandair"])
        self.assertIn("Assumed usage", opt.render_text(bundle))


class TestTransferGateway(unittest.TestCase):
    """Plan 07 addendum: transfer_gateway_required currencies get optimistic_cpp
    only when the scored portfolio holds a gateway card (unlocks_transfers)."""

    FLEX_PROF = {"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000}

    def test_standalone_flex_prices_at_floor(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["freedom-flex"], prof)
        for a in r["assignments"]:
            self.assertEqual(a["cpp"], 1.0)

    def test_pairing_with_sapphire_unlocks_optimistic(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["freedom-flex", "sapphire-preferred"], prof)
        for a in r["assignments"]:  # BOTH cards' UR now price at avg 1.5cpp
            self.assertEqual(a["cpp"], 1.5, a)

    def test_gateway_card_is_standalone_avg(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["sapphire-preferred"], prof)
        for a in r["assignments"]:
            self.assertEqual(a["cpp"], 1.5)

    def test_gateway_note_surfaced_in_bundle(self):
        dataset = {**{k: DATASET[k] for k in
                      ("categories", "merchants", "programs", "usage_questions",
                       "usage_keys")},
                   "cards": [seed_card("freedom-flex")]}
        prof = make_profile(self.FLEX_PROF)
        bundle = opt.run(dataset, prof, AS_OF, 1)
        note = bundle["portfolios"][0]["per_card"]["freedom-flex"]["valuation_note"]
        # No gateway card exists in this dataset → generic pairing hint.
        self.assertIn("pair with a gateway card", note)
        # With the Sapphire in the pool the top portfolio pairs them: the
        # warning is replaced by the positive pairing_note naming the gateway.
        dataset["cards"] = [seed_card("freedom-flex"), seed_card("sapphire-preferred")]
        prof = make_profile(self.FLEX_PROF, max_cards=2)
        bundle = opt.run(dataset, prof, AS_OF, 1)
        top = bundle["portfolios"][0]
        self.assertEqual(top["cards"], ["freedom-flex", "sapphire-preferred"])
        flex = top["per_card"]["freedom-flex"]
        self.assertNotIn("valuation_note", flex)
        self.assertIn("pooled with Chase Sapphire Preferred", flex["pairing_note"])
        self.assertIn("1.5cpp", flex["pairing_note"])
        self.assertEqual(flex["currency"], {"kind": "points", "program": "chase_ur",
                                            "label": "Chase Ultimate Rewards"})
        # The gateway card itself gets neither note (it unlocks its own program).
        csp = top["per_card"]["sapphire-preferred"]
        self.assertNotIn("valuation_note", csp)
        self.assertNotIn("pairing_note", csp)
        # A size-1 flex portfolio in the same bundle names the Sapphire in its
        # floored note (gateway map comes from the full dataset).
        flex_solo = next((p for p in bundle["best_by_size"]
                          if p["cards"] == ["freedom-flex"]), None)
        if flex_solo:
            self.assertIn("pair with Chase Sapphire Preferred",
                          flex_solo["per_card"]["freedom-flex"]["valuation_note"])

    def test_standalone_note_names_gateways(self):
        flex = seed_card("freedom-flex")
        gates = opt.gateway_names([flex, seed_card("sapphire-preferred")])
        self.assertEqual(gates, {"chase_ur": ["Chase Sapphire Preferred"]})
        cpp, note = opt.effective_cpp(flex, DATASET["programs"], set(),
                                      frozenset(), gates)
        self.assertEqual(cpp, 1.0)
        self.assertIn("pair with Chase Sapphire Preferred", note)
        self.assertIn("1.5cpp", note)

    def test_context_dependent_card_never_pruned(self):
        # A plain UR card is worth 1.0cpp standalone but avg 1.5cpp next to a
        # Sapphire — pruning must not judge it by its standalone floor.
        plain_ur = synth_card(id="plain-ur", base_rate=1.5,
                              currency={"type": "points", "program": "chase_ur"})
        better = synth_card(id="better", base_rate=2)
        prof = make_profile({"other": 10000})
        _, pruned = opt.prune_dominated_variants(
            [plain_ur, better], prof,
            DATASET["programs"], DATASET["merchants"], DATASET["categories"])
        self.assertEqual(pruned, [])


class TestRewardCapAndPeriods(unittest.TestCase):
    def test_max_annual_rewards_clamp(self):
        # 5% on $10,000 = $500 earned, clamped to a $300/yr reward cap.
        card = synth_card(base_rate=5, max_annual_rewards_usd=300)
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["earnings"], 300.0)
        self.assertEqual(r["reward_cap_clamps"], {"synth": 200.0})
        # Under the cap: untouched, no clamp recorded.
        r = score([card], make_profile({"other": 2000}))
        self.assertAlmostEqual(r["earnings"], 100.0)
        self.assertEqual(r["reward_cap_clamps"], {})

    def test_reward_cap_clamp_surfaced_in_bundle(self):
        # The output contract carries the clamp so a consumer can reconcile
        # per-line usd_value sums against the portfolio's clamped earnings.
        dataset = {"categories": DATASET["categories"],
                   "merchants": DATASET["merchants"],
                   "programs": DATASET["programs"],
                   "cards": [synth_card(id="capped", name="Capped", base_rate=5,
                                        max_annual_rewards_usd=300)]}
        prof = make_profile({"other": 10000})
        bundle = opt.run(dataset, prof, AS_OF, 1)
        per_card = bundle["portfolios"][0]["per_card"]["capped"]
        self.assertEqual(per_card["reward_cap_clamp"], 200.0)
        line_sum = sum(a["usd_value"] for a in per_card["assignments"])
        self.assertAlmostEqual(line_sum - per_card["reward_cap_clamp"],
                               bundle["portfolios"][0]["earnings"])
        self.assertIn("clamped by $200.00", opt.render_text(bundle))
        # Unclamped cards must not carry the key at all.
        dataset["cards"] = [synth_card(id="uncapped", name="Uncapped", base_rate=2)]
        bundle = opt.run(dataset, prof, AS_OF, 1)
        self.assertNotIn("reward_cap_clamp",
                         bundle["portfolios"][0]["per_card"]["uncapped"])

    def test_clamped_earnings_feed_first_year_match(self):
        card = synth_card(base_rate=5, max_annual_rewards_usd=300,
                          signup_bonus={"first_year_match": True})
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 300.0)

    def test_card_exclusive_membership_scored_as_fee(self):
        # $10,000 at 3% = $300; a card_exclusive membership (Robinhood Gold
        # pattern) costs $50/yr in BOTH metrics — a first-year fee waiver never
        # covers the separate membership.
        rm = {"name": "Gold", "annual_cost_usd": 50, "card_exclusive": True,
              "note": "x"}
        card = synth_card(base_rate=3, required_membership=rm,
                          fees={"annual_fee_usd": 0, "first_year_waived": True,
                                "foreign_transaction_pct": 0})
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["ongoing_net"], 250.0)
        self.assertAlmostEqual(r["year1_net"], 250.0)
        # Non-exclusive membership (Costco/Prime pattern) stays unscored.
        card = synth_card(base_rate=3,
                          required_membership={"name": "Prime",
                                               "annual_cost_usd": 139,
                                               "note": "x"})
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["ongoing_net"], 300.0)

    def test_membership_fee_surfaced_in_bundle(self):
        rm = {"name": "Gold", "annual_cost_usd": 50, "card_exclusive": True,
              "note": "x"}
        dataset = {"categories": DATASET["categories"],
                   "merchants": DATASET["merchants"],
                   "programs": DATASET["programs"],
                   "cards": [synth_card(id="gated", name="Gated", base_rate=3,
                                        required_membership=rm)]}
        bundle = opt.run(dataset, make_profile({"other": 10000}), AS_OF, 1)
        fees = bundle["portfolios"][0]["per_card"]["gated"]["fees"]
        self.assertEqual(fees["membership_fee_usd"], 50.0)
        self.assertEqual(fees["membership_name"], "Gold")
        self.assertIn("required membership (Gold): -$50.00/yr",
                      opt.render_text(bundle))

    def test_every_5_years_credit(self):
        # $120 every 5 years, uncategorized statement credit → face value
        # annualized: 120 * 0.2 = $24.
        credit = {"name": "global entry", "amount_usd": 120,
                  "period": "every_5_years", "realistic_capture_rate_note": "x"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 24.0)


class TestBonusVariants(unittest.TestCase):
    def test_mixed_points_plus_usd_bonus(self):
        bonus = {"value": {"points": 10000, "usd": 100},
                 "spend_requirement_usd": 500, "window_months": 3}
        card = synth_card(currency={"type": "points", "program": "chase_ur"},
                          signup_bonus=bonus)
        r = score([card], make_profile({"other": 12000}))
        # gated chase_ur, no gateway → floor 1.0cpp: 10000 × 1.0cpp + $100 = $200.
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 200.0)

    def test_tiered_bonus_counts_only_reachable_tiers(self):
        bonus = {"value": {"usd": 200}, "spend_requirement_usd": 500,
                 "window_months": 3,
                 "tiers": [{"value": {"usd": 100}, "spend_requirement_usd": 2000},
                           {"value": {"usd": 300}, "spend_requirement_usd": 10000}]}
        # 12000/yr × 3/12 = 3000 window spend → base + first tier only.
        r = score([synth_card(signup_bonus=bonus)], make_profile({"other": 12000}))
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 300.0)
        self.assertIn("1 tier(s) unreachable", r["bonuses"]["synth"]["note"])

    def test_first_year_match_equals_card_earnings(self):
        card = synth_card(base_rate=1.5, signup_bonus={"first_year_match": True})
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["earnings"], 150.0)
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 150.0)
        self.assertAlmostEqual(r["year1_net"], 300.0)
        self.assertIn("first-year match", r["bonuses"]["synth"]["note"])


class TestPortfolio(unittest.TestCase):
    def test_cap_competition(self):
        # BCP 6% wins groceries (Gold 4x * avg 1.25cpp = 5%): BCP takes 6000
        # (360), Gold takes overflow 4000@5% (200) + dining 4000@5% (200);
        # Gold base 1.25% beats BCP base 1% for other 6000 (75) → 835 earn.
        # Gold credits confirmed: dining tracker 4000 → 96+0+90+67.2 = 253.2.
        # Fees 95+325 → ongoing 835+253.2-420 = 668.2.
        # Bonuses: 250 + 60000*.0125=750; year-1 fee 325 (BCP waived)
        # → year1 835+253.2+250+750-325 = 1763.2.
        prof = make_profile({"groceries": 10000, "dining": 4000, "other": 6000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["blue-cash-preferred", "gold"], prof)
        self.assertAlmostEqual(r["earnings"], 835.0)
        self.assertAlmostEqual(r["ongoing_net"], 668.2)
        self.assertAlmostEqual(r["year1_net"], 1763.2)


class TestChooseYourOwnCategory(unittest.TestCase):
    """Choice cards expand into per-option variants; the search configures the
    card optimally per combination (docs/plans/02-optimizer.md §10)."""

    def test_expansion_only_for_options_with_spend(self):
        prof = make_profile(P30K)  # groceries, dining, other — 'other' not an option
        variants = opt.expand_choice_variants([seed_card("custom-cash")], prof)
        self.assertEqual([v["id"] for v in variants],
                         ["custom-cash[dining]", "custom-cash[groceries]"])
        self.assertTrue(all(v["base_id"] == "custom-cash" for v in variants))

    def test_expansion_no_matching_spend_drops_choice_line(self):
        prof = make_profile({"utilities": 5000})
        variants = opt.expand_choice_variants([seed_card("custom-cash")], prof)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["id"], "custom-cash")
        r = score(variants, prof)
        # Everything at base 1x (citi_typ floor 1.0cpp): 5000*1% = 50.
        self.assertAlmostEqual(r["earnings"], 50.0)

    def test_variant_golden_values(self):
        # groceries variant, floor: 6000@5% (monthly $500 cap → $6,000/yr room)
        # + 2000@1% fallback + dining 5000@1% + other 17000@1% = 540; no fee.
        # year1: +$200 bonus (30000*.5=15000 ≥ 1500) → 740.
        # dining variant: 5000@5% + groceries 8000@1% + other 170 = 500.
        prof = make_profile(P30K)
        variants = {v["id"]: v for v in
                    opt.expand_choice_variants([seed_card("custom-cash")], prof)}
        groceries = score([variants["custom-cash[groceries]"]], prof)
        self.assertAlmostEqual(groceries["ongoing_net"], 540.0)
        self.assertAlmostEqual(groceries["year1_net"], 740.0)
        dining = score([variants["custom-cash[dining]"]], prof)
        self.assertAlmostEqual(dining["ongoing_net"], 500.0)

    def test_best_configuration_flips_inside_a_combination(self):
        # Solo, groceries is custom-cash's best category; paired with Blue Cash
        # Preferred (6% groceries takes that bucket), the dining configuration
        # wins instead — the search re-configures the card per combination.
        prof = make_profile({"groceries": 6000, "dining": 5000, "other": 9000})
        variants = {v["id"]: v for v in
                    opt.expand_choice_variants([seed_card("custom-cash")], prof)}
        with_dining = score([seed_card("blue-cash-preferred"),
                             variants["custom-cash[dining]"]], prof)
        with_groceries = score([seed_card("blue-cash-preferred"),
                                variants["custom-cash[groceries]"]], prof)
        self.assertAlmostEqual(with_dining["earnings"], 700.0)
        self.assertAlmostEqual(with_groceries["earnings"], 500.0)
        self.assertGreater(with_dining["ongoing_net"], with_groceries["ongoing_net"])

    def test_search_never_pairs_two_variants_of_one_card(self):
        prof = make_profile(P30K, max_cards=2)
        variants = opt.expand_choice_variants([seed_card("custom-cash")], prof)
        results = opt.search(variants, prof, DATASET["programs"],
                             DATASET["merchants"], DATASET["categories"], AS_OF)
        # Only one physical card exists → only single-card portfolios.
        self.assertTrue(all(len(r["cards"]) == 1 for r in results))
        self.assertEqual(results[0]["cards"], ["custom-cash[groceries]"])

    def test_unexpanded_choice_reward_is_a_data_error(self):
        prof = make_profile(P30K)
        with self.assertRaises(opt.DataError):
            score([seed_card("custom-cash")], prof)


class TestFiltersAndSearch(unittest.TestCase):
    def test_tier_filter_excludes_venture_x(self):
        prof = make_profile(P30K, credit_tier="good")
        eligible, excluded = opt.filter_cards(DATASET["cards"], prof, DATASET["programs"])
        self.assertEqual([e["id"] for e in excluded], ["venture-x"])
        self.assertEqual(len(eligible), 7)

    def test_reward_preference_filter_flights(self):
        # Pure-cash cards can't serve a flights-only user; transferable
        # currencies (chase_ur, amex_mr, citi_typ, capital_one_miles) can.
        prof = make_profile(P30K, reward_preferences=["flights"])
        eligible, excluded = opt.filter_cards(DATASET["cards"], prof, DATASET["programs"])
        self.assertEqual(sorted(e["id"] for e in excluded),
                         ["active-cash", "blue-cash-preferred"])
        for e in excluded:
            self.assertIn("does not redeem for any of: flights", e["reason"])
        self.assertEqual(len(eligible), 6)

    def test_reward_preference_multi_select_unions(self):
        prof = make_profile(P30K, reward_preferences=["flights", "cashback"])
        _, excluded = opt.filter_cards(DATASET["cards"], prof, DATASET["programs"])
        self.assertEqual(excluded, [])

    def test_total_value_disables_reward_filter(self):
        prof = make_profile(P30K, reward_preferences=["flights", "total_value"])
        _, excluded = opt.filter_cards(DATASET["cards"], prof, DATASET["programs"])
        self.assertEqual(excluded, [])

    def test_merchant_restricted_currency_matches_nothing(self):
        # redeems_for: [] (store credit) survives only a total_value run —
        # accepts_brand_lockin=True keeps the lock-in filter out of the way so
        # this test isolates the reward-preference filter.
        programs = {**DATASET["programs"],
                    "store": {"label": "Store credit", "redeems_for": [],
                              "floor_cpp": 1.0, "optimistic_cpp": 1.0}}
        card = synth_card(currency={"type": "points", "program": "store"})
        for kind in ("cashback", "flights", "hotels"):
            prof = make_profile(P30K, reward_preferences=[kind],
                                accepts_brand_lockin=True)
            eligible, excluded = opt.filter_cards([card], prof, programs)
            self.assertEqual(eligible, [])
            self.assertEqual(len(excluded), 1)
        prof = make_profile(P30K, accepts_brand_lockin=True)  # default: total_value
        eligible, excluded = opt.filter_cards([card], prof, programs)
        self.assertEqual([c["id"] for c in eligible], ["synth"])
        self.assertEqual(excluded, [])

    def test_brand_lockin_filter(self):
        # Default (accepts_brand_lockin: false): a no-cashback-path currency is
        # excluded outright, whatever the reward preferences — willingness to
        # be brand-restricted is its own question.
        card = synth_card(currency={"type": "points", "program": "brandair_miles"})
        prof = make_profile(P30K)
        eligible, excluded = opt.filter_cards([card], prof, DATASET["programs"])
        self.assertEqual(eligible, [])
        self.assertIn("locks rewards to a single company", excluded[0]["reason"])
        # Opt-in: eligible again (valuation still floor unless loyalty confirmed).
        prof = make_profile(P30K, accepts_brand_lockin=True)
        eligible, excluded = opt.filter_cards([card], prof, DATASET["programs"])
        self.assertEqual([c["id"] for c in eligible], ["synth"])
        self.assertEqual(excluded, [])
        # Cashback-path currencies are never touched by this filter.
        cash = synth_card(id="plain-cash")
        eligible, excluded = opt.filter_cards([cash], make_profile(P30K),
                                              DATASET["programs"])
        self.assertEqual([c["id"] for c in eligible], ["plain-cash"])

    def test_accepts_brand_lockin_must_be_bool(self):
        with self.assertRaises(opt.InputError) as ctx:
            opt.parse_profile({"spend": {"groceries": 100},
                               "user": {"credit_tier": "good",
                                        "accepts_brand_lockin": "yes"}}, DATASET)
        self.assertIn("accepts_brand_lockin", str(ctx.exception))

    def test_search_is_exhaustive_and_ranked(self):
        # 7 eligible cards; custom-cash expands to 2 variants (dining, groceries)
        # → 8 variants, minus combos pairing both custom-cash variants:
        # C(8,1) + C(8,2)-1 + C(8,3)-6 = 8 + 27 + 50 = 85.
        prof = make_profile(P30K, credit_tier="good")
        eligible, _ = opt.filter_cards(DATASET["cards"], prof, DATASET["programs"])
        variants = opt.expand_choice_variants(eligible, prof)
        results = opt.search(variants, prof, DATASET["programs"],
                             DATASET["merchants"], DATASET["categories"], AS_OF)
        self.assertEqual(len(results), 85)
        nets = [r["ongoing_net"] for r in results]
        self.assertEqual(nets, sorted(nets, reverse=True))
        for r in results:  # never two configurations of the same physical card
            bases = [c.split("[")[0] for c in r["cards"]]
            self.assertEqual(len(bases), len(set(bases)), r["cards"])

    def test_low_confidence_warning_on_seed_cards(self):
        warnings = opt.card_warnings(seed_card("double-cash"), AS_OF)
        self.assertTrue(any("UNVERIFIED DATA" in w for w in warnings))


class TestProfileValidation(unittest.TestCase):
    def assert_rejected(self, raw, fragment):
        with self.assertRaises(opt.InputError) as ctx:
            opt.parse_profile(raw, DATASET)
        self.assertIn(fragment, str(ctx.exception))

    def test_rotating_pseudo_category_rejected(self):
        self.assert_rejected({"spend": {"rotating": 100},
                              "user": {"credit_tier": "good"}}, "pseudo-category")

    def test_unknown_category_rejected(self):
        self.assert_rejected({"spend": {"grocery": 100},
                              "user": {"credit_tier": "good"}}, "unknown category")

    def test_unknown_merchant_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "merchant_spend": {"kroger": 50},
                              "user": {"credit_tier": "good"}}, "unknown merchant")

    def test_carveout_exceeding_category_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "merchant_spend": {"costco": 200},
                              "user": {"credit_tier": "good"}}, "carve-outs")

    def test_unknown_user_key_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "user": {"credit_tier": "good", "maxcards": 2}},
                             "unknown key")

    def test_out_of_range_max_cards_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "user": {"credit_tier": "good", "max_cards": 7}},
                             "max_cards")

    def test_missing_credit_tier_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100}, "user": {}},
                             "credit_tier is required")

    def test_bad_reward_preferences_rejected(self):
        for bad in ([], ["cruises"], ["flights", "flights"], "flights"):
            self.assert_rejected({"spend": {"groceries": 100},
                                  "user": {"credit_tier": "good",
                                           "reward_preferences": bad}},
                                 "reward_preferences")

    def test_unknown_confirmed_usage_key_rejected(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "user": {"credit_tier": "good",
                                       "confirmed_usage": ["netflix"]}},
                             "unknown key(s) ['netflix']")

    def test_bad_confirmed_usage_shapes_rejected(self):
        for bad in ("uber", ["uber", "uber"], [7]):
            self.assert_rejected({"spend": {"groceries": 100},
                                  "user": {"credit_tier": "good",
                                           "confirmed_usage": bad}},
                                 "confirmed_usage")

    def test_confirmed_usage_stored_sorted(self):
        prof = make_profile({"groceries": 100}, confirmed_usage=["uber", "brandair"])
        self.assertEqual(prof["user"]["confirmed_usage"], ["brandair", "uber"])

    def test_uses_travel_portal_migration_error(self):
        self.assert_rejected({"spend": {"groceries": 100},
                              "user": {"credit_tier": "good",
                                       "uses_travel_portal": True}},
                             "uses_travel_portal was removed")

    def test_valuation_mode_migration_error(self):
        # Plan 08: floor|optimistic modes replaced by a single per-program
        # average; old profiles get a targeted message, not "unknown key".
        self.assert_rejected({"spend": {"groceries": 100},
                              "user": {"credit_tier": "good",
                                       "valuation_mode": "floor"}},
                             "valuation_mode was removed")


class TestSubsetBudget(unittest.TestCase):
    """Dynamic work-budget gate replacing the static 80-variant stop (plan 02.5 §1)."""

    def test_budget_formula(self):
        self.assertEqual(opt.subset_budget(129, 3), 357_889)
        self.assertEqual(opt.subset_budget(129, 5), 286_601_665)

    def test_over_budget_pool_raises_before_scoring(self):
        # Poison pill: an unexpanded 'choice' reward makes build_lines raise
        # with a different message, so getting the budget message proves the
        # gate fired before any subset was scored.
        poison = [{"category": "choice", "rate": 5,
                   "choice": {"options": ["gas"]}}]
        variants = [synth_card(id=f"card-{i:03d}", category_rewards=poison)
                    for i in range(300)]  # C(300,1..3) ≈ 4.5M > 2M budget
        prof = make_profile({"other": 10000})
        with self.assertRaises(opt.DataError) as ctx:
            opt.search(variants, prof, DATASET["programs"],
                       DATASET["merchants"], DATASET["categories"], AS_OF)
        msg = str(ctx.exception)
        self.assertIn("max_cards", msg)
        self.assertIn("MAX_SCORED_SUBSETS", msg)

    def test_small_pool_searches_fine(self):
        variants = [synth_card(id="one", base_rate=1), synth_card(id="two", base_rate=2)]
        results = opt.search(variants, make_profile({"other": 5000}),
                             DATASET["programs"], DATASET["merchants"],
                             DATASET["categories"], AS_OF)
        self.assertEqual(len(results), 3)  # {one}, {two}, {one, two}

    def test_policy_constants_echo(self):
        pc = opt.policy_constants()
        self.assertIn("MAX_SCORED_SUBSETS", pc)
        self.assertNotIn("MAX_ELIGIBLE_CARDS", pc)
        self.assertIn("EXPLICIT_ONLY_CATEGORIES", pc)


class TestExplicitOnlyHousing(unittest.TestCase):
    """Housing (explicit_only): rent/mortgage earns only through an explicit
    housing category reward — never the base rate — and never counts toward
    signup-bonus or credit-unlock spend feasibility."""

    def test_base_rate_never_earns_on_housing(self):
        # A plain 2% card has no housing line, so $24k of rent earns $0 and
        # stays unassigned; only the $6k of 'other' earns the base rate.
        plain = synth_card(base_rate=2)
        prof = make_profile({"housing": 24000, "other": 6000})
        r = score([plain], prof)
        self.assertAlmostEqual(r["earnings"], 120.0)  # 6000 * 2%, housing earns $0
        self.assertAlmostEqual(r["unassigned"]["housing"], 24000.0)

    def test_explicit_housing_reward_earns(self):
        # A card with an explicit housing reward (Bilt-style) earns on rent.
        bilt = synth_card(base_rate=1,
                          category_rewards=[{"category": "housing", "rate": 1}])
        prof = make_profile({"housing": 24000, "other": 6000})
        r = score([bilt], prof)
        self.assertAlmostEqual(r["earnings"], 300.0)  # (24000 + 6000) * 1%
        self.assertNotIn("housing", r["unassigned"])

    def test_housing_excluded_from_bonus_feasibility(self):
        # $40k spend requirement, but $36k of the $40k profile is housing —
        # only $4k is card-payable, so the requirement is unreachable and the
        # bonus is $0. Without the exclusion the $40k total would "reach" it.
        card = synth_card(base_rate=1, signup_bonus={
            "value": {"usd": 500}, "spend_requirement_usd": 40000,
            "window_months": 12})
        prof = make_profile({"housing": 36000, "other": 4000})
        r = score([card], prof)
        self.assertEqual(r["bonuses"]["synth"]["value"], 0.0)
        self.assertIn("unreachable", r["bonuses"]["synth"]["note"])

    def test_housing_excluded_from_credit_unlock_feasibility(self):
        # unlock_spend_usd is measured against card-payable (everyday) spend,
        # so a $10k/yr unlock is unreachable when only $2k is non-housing.
        credit = {"name": "spend-unlock perk", "amount_usd": 100,
                  "period": "annual", "unlock_spend_usd": 10000,
                  "realistic_capture_rate_note": "x"}
        card = synth_card(base_rate=1,
                          category_rewards=[{"category": "housing", "rate": 1}],
                          credits=[credit])
        prof = make_profile({"housing": 30000, "other": 2000})
        r = score([card], prof)
        self.assertEqual(r["credits"][0]["value"], 0.0)
        self.assertIn("unreachable", r["credits"][0]["note"])


class TestDominancePruning(unittest.TestCase):
    """Exact pre-search dominance pruning (plan 02.5 §2)."""

    def prune(self, variants, prof):
        return opt.prune_dominated_variants(variants, prof,
                                            DATASET["programs"], DATASET["merchants"],
                                            DATASET["categories"])

    def test_strictly_worse_clone_pruned(self):
        variants = [synth_card(id="worse", base_rate=1),
                    synth_card(id="better", base_rate=2)]
        kept, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual([v["id"] for v in kept], ["better"])
        self.assertEqual(pruned, [{"id": "worse", "reason": "dominated by better"}])

    def test_signup_bonus_blocks_pruning_even_expired(self):
        bonus = {"value": {"usd": 100}, "spend_requirement_usd": 500,
                 "window_months": 3, "expires": "2020-01-01"}
        variants = [synth_card(id="worse", base_rate=1, signup_bonus=bonus),
                    synth_card(id="better", base_rate=2)]
        _, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual(pruned, [])

    def test_credit_blocks_pruning(self):
        credit = {"name": "tiny credit", "amount_usd": 1, "period": "annual",
                  "realistic_capture_rate_note": "x"}
        variants = [synth_card(id="worse", base_rate=1, credits=[credit]),
                    synth_card(id="better", base_rate=2)]
        _, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual(pruned, [])

    def test_capped_cover_never_dominates(self):
        # B's 5% groceries line is capped; inside a subset its room may already
        # be consumed, so it cannot cover A's uncapped 1.5%.
        cap = {"period": "annual", "max_spend_usd": 6000, "fallback_rate": 1}
        variants = [synth_card(id="aflat", base_rate=1.5),
                    synth_card(id="bgroc", base_rate=1.5,
                               category_rewards=[{"category": "groceries",
                                                  "rate": 5, "cap": cap}])]
        _, pruned = self.prune(variants, make_profile({"groceries": 8000, "other": 4000}))
        self.assertEqual(pruned, [])

    def test_higher_fee_blocks_pruning(self):
        variants = [synth_card(id="worse", base_rate=1),
                    synth_card(id="better", base_rate=2,
                               fees={"annual_fee_usd": 95, "foreign_transaction_pct": 0})]
        _, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual(pruned, [])

    def test_first_year_waiver_blocks_pruning(self):
        # Equal ongoing fees, but A waives year 1 and B doesn't: year1_fee_B > year1_fee_A.
        variants = [synth_card(id="worse", base_rate=1,
                               fees={"annual_fee_usd": 95, "first_year_waived": True,
                                     "foreign_transaction_pct": 0}),
                    synth_card(id="better", base_rate=2,
                               fees={"annual_fee_usd": 95, "foreign_transaction_pct": 0})]
        _, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual(pruned, [])

    def test_reward_clamp_blocks_pruning(self):
        variants = [synth_card(id="worse", base_rate=1),
                    synth_card(id="better", base_rate=2, max_annual_rewards_usd=300)]
        _, pruned = self.prune(variants, make_profile({"other": 10000}))
        self.assertEqual(pruned, [])

    def test_capped_specialist_coexists_with_flat_card(self):
        # A's capped 5% groceries headline beats B's 2% uncapped cover, so A
        # survives even though B is better everywhere else.
        cap = {"period": "annual", "max_spend_usd": 6000, "fallback_rate": 1}
        variants = [synth_card(id="acap", base_rate=1,
                               category_rewards=[{"category": "groceries",
                                                  "rate": 5, "cap": cap}]),
                    synth_card(id="bflat", base_rate=2)]
        kept, pruned = self.prune(variants, make_profile({"groceries": 8000, "other": 4000}))
        self.assertEqual(pruned, [])
        self.assertEqual(sorted(v["id"] for v in kept), ["acap", "bflat"])

    def test_match_interception_guard(self):
        # M holds dining at 3% with a first-year match. B (4% dining) would
        # newly out-rate M where A's uncapped 1% did not → guard blocks the
        # prune. A control flat 2% card (no dining line above 3%) prunes A.
        matcher = synth_card(id="matcher", base_rate=1,
                             category_rewards=[{"category": "dining", "rate": 3}],
                             signup_bonus={"first_year_match": True},
                             fees={"annual_fee_usd": 5, "foreign_transaction_pct": 0})
        plain = synth_card(id="plainflat", base_rate=1)
        prof = make_profile({"dining": 3000, "other": 7000})
        interceptor = synth_card(id="bigdining", base_rate=2,
                                 category_rewards=[{"category": "dining", "rate": 4}])
        _, pruned = self.prune([plain, interceptor, matcher], prof)
        self.assertEqual(pruned, [])
        control = synth_card(id="modestflat", base_rate=2)
        _, pruned = self.prune([plain, control, matcher], prof)
        self.assertEqual(pruned, [{"id": "plainflat", "reason": "dominated by modestflat"}])

    def test_tie_pruning_is_deterministic(self):
        prof = make_profile({"other": 10000})
        first, second = synth_card(id="aaa"), synth_card(id="bbb")
        for order in ([first, second], [second, first]):
            kept, pruned = self.prune(order, prof)
            self.assertEqual([v["id"] for v in kept], ["aaa"])
            self.assertEqual(pruned, [{"id": "bbb", "reason": "dominated by aaa"}])

    def test_run_bundle_and_render_surface_pruned(self):
        dataset = {"categories": DATASET["categories"],
                   "merchants": DATASET["merchants"],
                   "programs": DATASET["programs"],
                   "cards": [synth_card(id="better", name="Better", base_rate=2),
                             synth_card(id="worse", name="Worse", base_rate=1)]}
        prof = make_profile({"other": 10000})
        bundle = opt.run(dataset, prof, AS_OF, 3)
        self.assertEqual(bundle["card_variants"], 2)
        self.assertEqual(bundle["card_variants_pruned"], 1)
        self.assertEqual(bundle["pruned"],
                         [{"id": "worse", "reason": "dominated by better"}])
        text = opt.render_text(bundle)
        self.assertIn("1 pruned as dominated", text)
        self.assertIn("Pruned: worse (dominated by better)", text)


class TestBestBySize(unittest.TestCase):
    """Plan 08: the bundle carries the best portfolio per exact size 1..max
    (the product UI shows size k only when it beats the previous size)."""

    def dataset_of(self, cards):
        return {**{k: DATASET[k] for k in
                   ("categories", "merchants", "programs", "usage_questions",
                    "usage_keys")},
                "cards": cards}

    def test_best_by_size_one_entry_per_size(self):
        # Three cards that each win somewhere (so none is dominance-pruned):
        # a 3% flat card, a groceries 5x specialist, a dining 4x specialist.
        # Profile 5000/5000/5000:
        #   best-1: flat  15000*3% = 450
        #   best-2: flat+groc  250 + 10000*3% = 550
        #   best-3: all three  250 + 200 + 5000*3% = 600
        cards = [
            synth_card(id="flat", name="Flat", base_rate=3),
            synth_card(id="groc", name="Groc",
                       category_rewards=[{"category": "groceries", "rate": 5}]),
            synth_card(id="dine", name="Dine",
                       category_rewards=[{"category": "dining", "rate": 4}]),
        ]
        prof = make_profile({"groceries": 5000, "dining": 5000, "other": 5000})
        bundle = opt.run(self.dataset_of(cards), prof, AS_OF, 1)
        best = bundle["best_by_size"]
        self.assertEqual([b["size"] for b in best], [1, 2, 3])
        self.assertEqual(best[0]["cards"], ["flat"])
        self.assertAlmostEqual(best[0]["ongoing_net"], 450.0)
        self.assertEqual(best[1]["cards"], ["flat", "groc"])
        self.assertAlmostEqual(best[1]["ongoing_net"], 550.0)
        self.assertAlmostEqual(best[2]["ongoing_net"], 600.0)
        # Each entry carries full per-card detail, same shape as portfolios.
        self.assertIn("per_card", best[0])
        self.assertIn("assignments", best[0]["per_card"]["flat"])

    def test_best_by_size_respects_max_cards(self):
        cards = [synth_card(id=f"flat-{r}", name=f"Flat {r}", base_rate=r)
                 for r in (1, 2, 3)]
        bundle = opt.run(self.dataset_of(cards),
                         make_profile({"other": 10000}, max_cards=1), AS_OF, 1)
        self.assertEqual([b["size"] for b in bundle["best_by_size"]], [1])

    def test_render_text_prints_best_by_size(self):
        cards = [synth_card(id="one", name="One", base_rate=2)]
        bundle = opt.run(self.dataset_of(cards), make_profile({"other": 10000}),
                         AS_OF, 1)
        self.assertIn("Best by size: 1 card: one", opt.render_text(bundle))

    def test_cpp_table_carries_avg(self):
        bundle = opt.run(self.dataset_of([synth_card()]),
                         make_profile({"other": 100}), AS_OF, 1)
        self.assertEqual(bundle["cpp_table"]["chase_ur"],
                         {"floor_cpp": 1.0, "optimistic_cpp": 2.0, "avg_cpp": 1.5})
        self.assertNotIn("valuation_mode", bundle)


class TestDeterminism(unittest.TestCase):
    def test_identical_inputs_identical_bytes(self):
        profile_yaml = ("spend:\n  groceries: 8000\n  dining: 5000\n  other: 17000\n"
                        "user:\n  credit_tier: excellent\n")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(profile_yaml)
            path = f.name
        outputs = []
        for _ in range(2):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = opt.main(["--profile", path, "--json", "--as-of", "2026-07-03"])
            self.assertEqual(code, 0)
            outputs.append(buf.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn('"policy_constants"', outputs[0])


if __name__ == "__main__":
    unittest.main()
