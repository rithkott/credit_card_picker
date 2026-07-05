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


def score(cards, profile, mode="floor"):
    cards = [seed_card(c) if isinstance(c, str) else c for c in cards]
    buckets = opt.build_buckets(profile, DATASET["merchants"])
    return opt.score_portfolio(cards, profile, mode, DATASET["programs"], buckets, AS_OF)


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
        # Spec §4.3: floor ongoing $600, year-1 $800. Optimistic (plan 07
        # addendum): citi_typ is transfer_gateway_required and no premium TY
        # card is in the portfolio, so standalone Double Cash stays at floor
        # 1.0cpp — its 1.7cpp upside needs a Strata Premier/Elite pairing.
        prof = make_profile(P30K)
        floor = score(["double-cash"], prof, "floor")
        self.assertAlmostEqual(floor["ongoing_net"], 600.0)
        self.assertAlmostEqual(floor["year1_net"], 800.0)
        optimistic = score(["double-cash"], prof, "optimistic")
        self.assertAlmostEqual(optimistic["ongoing_net"], 600.0)
        self.assertAlmostEqual(optimistic["year1_net"], 800.0)

    def test_active_cash(self):
        # Flat 2% cash: 30000*2% = 600; +$200 bonus year 1. Identical both modes.
        prof = make_profile(P30K)
        for mode in ("floor", "optimistic"):
            r = score(["active-cash"], prof, mode)
            self.assertAlmostEqual(r["ongoing_net"], 600.0)
            self.assertAlmostEqual(r["year1_net"], 800.0)

    def test_blue_cash_preferred(self):
        # groceries 6% on 6000 cap = 360, 1% fallback on 2000 = 20,
        # base 1% on dining+other 22000 = 220 → 600 earn; Disney credit $0
        # (no streaming spend); ongoing 600-95=505; year1 600+250-0(waived)=850.
        prof = make_profile(P30K)
        for mode in ("floor", "optimistic"):  # cash card: modes identical
            r = score(["blue-cash-preferred"], prof, mode)
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

    def test_amex_gold_floor(self):
        # cpp 0.6: dining 5000*4*.006=120, groceries 8000*4*.006=192,
        # other 17000*.006=102 → 414 earn.
        # All four credit services confirmed → CONFIRMED_CREDIT_CAPTURE.
        # Credits vs dining tracker 5000: dining 10*12*.8=96, Uber $0 (no transit
        # spend), Resy 50*2*.9=90, Dunkin 7*12*.8=67.2 → 253.2.
        # ongoing 414+253.2-325=342.2; bonus 60000*.006=360 → year1 702.2.
        prof = make_profile(P30K, confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 414.0)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 253.2)
        self.assertAlmostEqual(r["ongoing_net"], 342.2)
        self.assertAlmostEqual(r["year1_net"], 702.2)

    def test_amex_gold_floor_unconfirmed(self):
        # No confirmed usage: every merchant credit is $0 with an explicit
        # reason — the card is just its earn minus the fee.
        prof = make_profile(P30K)
        r = score(["gold"], prof, "floor")
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 0.0)
        for c in r["credits"]:
            self.assertIn("requires confirmed use", c["note"])
        self.assertAlmostEqual(r["ongoing_net"], 414.0 - 325.0)

    def test_amex_gold_optimistic(self):
        # cpp 1.9: 5000*4*.019=380 + 8000*4*.019=608 + 17000*.019=323 = 1311.
        # ongoing 1311+253.2-325=1239.2; bonus 1140 → year1 2379.2.
        prof = make_profile(P30K, confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof, "optimistic")
        self.assertAlmostEqual(r["ongoing_net"], 1239.2)
        self.assertAlmostEqual(r["year1_net"], 2379.2)

    def test_sapphire_preferred_portal_unconfirmed(self):
        # chase_travel not confirmed: the portal-only 5x travel_other line is
        # dropped (falls to base 1x) AND the portal-locked hotel credit is $0.
        # floor: dining 120 + groceries 180 + hotels 40 + base(1000+7000)*1% 80
        # = 420; ongoing 420+0-95=325; bonus 60000*1.0cpp=600 → year1 925.
        prof = make_profile({"dining": 4000, "groceries": 6000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 7000})
        r = score(["sapphire-preferred"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 420.0)
        self.assertAlmostEqual(r["ongoing_net"], 325.0)
        self.assertAlmostEqual(r["year1_net"], 925.0)
        self.assertIn("requires confirmed use", r["credits"][0]["note"])

    def test_sapphire_preferred_portal_confirmed(self):
        # chase_travel confirmed: travel_other kept at 5*0.75=3.75x →
        # 1000*.0375=37.5 replaces base $10 (earn 447.5); hotel credit
        # min(50*0.95, 2000)=47.5; ongoing 447.5+47.5-95=400.
        prof = make_profile({"dining": 4000, "groceries": 6000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 7000},
                            confirmed_usage=["chase_travel"])
        r = score(["sapphire-preferred"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 447.5)
        self.assertAlmostEqual(r["ongoing_net"], 400.0)

    def test_freedom_flex_rotating_activated(self):
        # Rotating room 1500*4*0.75=4500 @5x. Regret rule fills gas (alt 1%)
        # then groceries (alt 1%) before dining (alt 3%): gas 2000 + groceries
        # 2500. Then dining 4000@3%=120, groceries fallback 3500@1%=35,
        # base other 8000@1%=80 → 225+120+35+80=460. Bonus $200 → year1 660.
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000})
        r = score(["freedom-flex"], prof, "floor")
        rotating = [a for a in r["assignments"] if a["kind"] == "rotating"]
        self.assertEqual({(a["bucket"], a["usd_assigned"]) for a in rotating},
                         {("gas", 2000.0), ("groceries", 2500.0)})
        self.assertAlmostEqual(r["earnings"], 460.0)
        self.assertAlmostEqual(r["ongoing_net"], 460.0)
        self.assertAlmostEqual(r["year1_net"], 660.0)

    def test_freedom_flex_rotating_not_activated(self):
        # Rotating line drops to fallback 1x: groceries+gas 8000@1% + dining
        # 4000@3% + other 8000@1% = 80+120+80 = 280.
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000},
                            activates_rotating=False)
        r = score(["freedom-flex"], prof, "floor")
        self.assertAlmostEqual(r["ongoing_net"], 280.0)

    def test_freedom_flex_optimistic(self):
        # Plan 07 addendum: standalone Freedom Flex is pure cash back — its UR
        # points can't reach transfer partners without a Sapphire in the
        # portfolio, so optimistic == floor (1.0cpp): 460 ongoing, 660 year-1.
        # (Paired 2.0cpp behavior is pinned in TestTransferGateway.)
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000})
        r = score(["freedom-flex"], prof, "optimistic")
        self.assertAlmostEqual(r["ongoing_net"], 460.0)
        self.assertAlmostEqual(r["year1_net"], 660.0)

    def test_venture_x_portal_unconfirmed(self):
        # capital_one_travel not confirmed: both portal-only lines drop → all
        # 20000 at base 2x*0.5cpp=1% → 200; the portal-locked travel credit is
        # $0, only the automatic anniversary $100 survives. ongoing
        # 200+100-395=-95; bonus 75000*.005=375 → year1 280.
        prof = make_profile({"travel_flights": 3000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 14000})
        r = score(["venture-x"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 200.0)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 100.0)
        self.assertAlmostEqual(r["ongoing_net"], -95.0)
        self.assertAlmostEqual(r["year1_net"], 280.0)

    def test_venture_x_portal_confirmed(self):
        # hotels 2000@7.5x*.005=75, flights 3000@3.75x*.005=56.25,
        # base 15000@1%=150 → 281.25. Credits: travel credit
        # min(300*0.95, travel_other 1000)=285 + anniversary 100 = 385.
        # ongoing 281.25+385-395=271.25.
        prof = make_profile({"travel_flights": 3000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 14000},
                            confirmed_usage=["capital_one_travel"])
        r = score(["venture-x"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 281.25)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 385.0)
        self.assertAlmostEqual(r["ongoing_net"], 271.25)


class TestCreditsAndBonus(unittest.TestCase):
    def test_credit_gating_no_dining_spend(self):
        # Even with every service confirmed, the category gate still applies:
        # without dining/transit spend all four Gold credits are $0 with reasons.
        prof = make_profile({"groceries": 8000, "other": 22000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof, "floor")
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 0.0)
        for c in r["credits"]:
            self.assertIn("no remaining spend", c["note"])

    def test_stacked_credits_capped_by_real_spend(self):
        # Only $150 of dining spend, all services confirmed: file order draws
        # dining min(10*12*.8=96, 150)=96, then Resy min(50*2*.9=90,
        # remaining 54)=54, then Dunkin $0.
        prof = make_profile({"dining": 150, "other": 30000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["gold"], prof, "floor")
        by_name = {c["name"]: c["value"] for c in r["credits"]}
        self.assertAlmostEqual(by_name["Dining credit (Grubhub, Cheesecake Factory, etc.)"], 96.0)
        self.assertAlmostEqual(by_name["Resy dining credit"], 54.0)
        self.assertAlmostEqual(by_name["Dunkin' credit"], 0.0)

    def test_bonus_infeasible_at_low_volume(self):
        # Gold needs 6000 in 6 months; 1000/yr * 0.5 = 500 < 6000 → $0.
        prof = make_profile({"other": 1000})
        r = score(["gold"], prof, "floor")
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
        # unlocks_transfers: the card is its own UR gateway, so optimistic
        # 2.0cpp applies standalone (the gateway gate is tested separately).
        card = synth_card(currency={"type": "points", "program": "chase_ur"},
                          unlocks_transfers=True, credits=[credit])
        prof = make_profile({"other": 5000})
        self.assertAlmostEqual(score([card], prof, "floor")["credits"][0]["value"], 100.0)
        self.assertAlmostEqual(score([card], prof, "optimistic")["credits"][0]["value"], 200.0)

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
        buckets = opt.build_buckets(prof, DATASET["merchants"])
        expired = opt.score_portfolio([card], prof, "floor", DATASET["programs"],
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
        unconfirmed = score([card], make_profile({"other": 5000}))
        self.assertEqual(unconfirmed["credits"][0]["value"], 0.0)

    def brandair_card(self, **overrides):
        return synth_card(currency={"type": "points", "program": "brandair_miles"},
                          **overrides)

    def test_lockin_currency_floored_without_loyalty(self):
        # brandair_miles: floor 0.8, optimistic 1.5, loyalty_keys [brandair].
        # Optimistic without confirmation → floor cpp (keep-but-devalue).
        prof = make_profile({"other": 10000})
        r = score([self.brandair_card()], prof, "optimistic")
        self.assertAlmostEqual(r["earnings"], 80.0)  # 10000 × 1x × 0.8cpp
        loyal = make_profile({"other": 10000}, confirmed_usage=["brandair"])
        r = score([self.brandair_card()], loyal, "optimistic")
        self.assertAlmostEqual(r["earnings"], 150.0)  # 10000 × 1x × 1.5cpp

    def test_lockin_floor_mode_is_noop_and_transferables_unaffected(self):
        prof = make_profile({"other": 10000})
        r = score([self.brandair_card()], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 80.0)
        # amex_mr has a cashback path and transfers natively (no gateway
        # required) → never devalued by the loyalty gate.
        mr = synth_card(currency={"type": "points", "program": "amex_mr"})
        r = score([mr], prof, "optimistic")
        self.assertAlmostEqual(r["earnings"], 190.0)  # 1.9cpp intact

    def test_lockin_devalues_bonus_and_points_credits(self):
        bonus = {"value": {"points": 10000}, "spend_requirement_usd": 100,
                 "window_months": 3}
        credit = {"name": "anniversary miles", "amount_points": 5000,
                  "period": "annual", "realistic_capture_rate_note": "automatic"}
        card = self.brandair_card(signup_bonus=bonus, credits=[credit])
        prof = make_profile({"other": 10000})
        r = score([card], prof, "optimistic")
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 80.0)   # 10000 × 0.8cpp
        self.assertAlmostEqual(r["credits"][0]["value"], 40.0)        # 5000 × 0.8cpp
        loyal = make_profile({"other": 10000}, confirmed_usage=["brandair"])
        r = score([card], loyal, "optimistic")
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 150.0)
        self.assertAlmostEqual(r["credits"][0]["value"], 75.0)

    def test_valuation_note_surfaced_in_bundle_and_text(self):
        dataset = {**{k: DATASET[k] for k in
                      ("categories", "merchants", "programs", "usage_questions",
                       "usage_keys")},
                   "cards": [self.brandair_card(id="brand", name="Brand")]}
        # accepts_brand_lockin: the lock-in filter would otherwise exclude the
        # brandair card before scoring — this test targets the valuation note.
        prof = make_profile({"other": 10000}, valuation_mode="optimistic",
                            accepts_brand_lockin=True)
        bundle = opt.run(dataset, prof, AS_OF, 1)
        note = bundle["portfolios"][0]["per_card"]["brand"]["valuation_note"]
        self.assertIn("no confirmed loyalty", note)
        self.assertIn("brandair", note)
        self.assertIn("no confirmed loyalty", opt.render_text(bundle))
        self.assertIn("confirmed_usage", bundle)
        # Loyal user: no note.
        loyal = make_profile({"other": 10000}, valuation_mode="optimistic",
                             accepts_brand_lockin=True,
                             confirmed_usage=["brandair"])
        bundle = opt.run(dataset, loyal, AS_OF, 1)
        self.assertNotIn("valuation_note", bundle["portfolios"][0]["per_card"]["brand"])
        self.assertEqual(bundle["confirmed_usage"], ["brandair"])

    def test_confirmed_capture_in_policy_constants(self):
        self.assertIn("CONFIRMED_CREDIT_CAPTURE", opt.policy_constants())


class TestTransferGateway(unittest.TestCase):
    """Plan 07 addendum: transfer_gateway_required currencies get optimistic_cpp
    only when the scored portfolio holds a gateway card (unlocks_transfers)."""

    FLEX_PROF = {"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000}

    def test_standalone_flex_prices_at_floor(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["freedom-flex"], prof, "optimistic")
        for a in r["assignments"]:
            self.assertEqual(a["cpp"], 1.0)

    def test_pairing_with_sapphire_unlocks_optimistic(self):
        prof = make_profile(self.FLEX_PROF, confirmed_usage=["chase_travel"])
        r = score(["freedom-flex", "sapphire-preferred"], prof, "optimistic")
        for a in r["assignments"]:  # BOTH cards' UR now price at 2.0cpp
            self.assertEqual(a["cpp"], 2.0, a)

    def test_gateway_card_is_standalone_optimistic(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["sapphire-preferred"], prof, "optimistic")
        for a in r["assignments"]:
            self.assertEqual(a["cpp"], 2.0)

    def test_floor_mode_is_a_noop(self):
        prof = make_profile(self.FLEX_PROF)
        r = score(["freedom-flex"], prof, "floor")
        for a in r["assignments"]:
            self.assertEqual(a["cpp"], 1.0)

    def test_gateway_note_surfaced_in_bundle(self):
        dataset = {**{k: DATASET[k] for k in
                      ("categories", "merchants", "programs", "usage_questions",
                       "usage_keys")},
                   "cards": [seed_card("freedom-flex")]}
        prof = make_profile(self.FLEX_PROF, valuation_mode="optimistic")
        bundle = opt.run(dataset, prof, AS_OF, 1)
        note = bundle["portfolios"][0]["per_card"]["freedom-flex"]["valuation_note"]
        self.assertIn("gateway card", note)
        # With the Sapphire in the pool the top portfolio pairs them: no note.
        dataset["cards"] = [seed_card("freedom-flex"), seed_card("sapphire-preferred")]
        prof = make_profile(self.FLEX_PROF, valuation_mode="optimistic",
                            max_cards=2, confirmed_usage=["chase_travel"])
        bundle = opt.run(dataset, prof, AS_OF, 1)
        top = bundle["portfolios"][0]
        self.assertEqual(top["cards"], ["freedom-flex", "sapphire-preferred"])
        self.assertNotIn("valuation_note", top["per_card"]["freedom-flex"])

    def test_context_dependent_card_never_pruned_in_optimistic(self):
        # A plain UR card is worth 1.0cpp standalone but 2.0cpp next to a
        # Sapphire — pruning must not judge it by its standalone floor.
        plain_ur = synth_card(id="plain-ur", base_rate=1.5,
                              currency={"type": "points", "program": "chase_ur"})
        better = synth_card(id="better", base_rate=2)
        prof = make_profile({"other": 10000})
        _, pruned = opt.prune_dominated_variants(
            [plain_ur, better], prof, "optimistic",
            DATASET["programs"], DATASET["merchants"])
        self.assertEqual(pruned, [])
        # Floor mode: cpp is fixed at 1.0, 1.5% < 2% → prunable as before.
        _, pruned = opt.prune_dominated_variants(
            [plain_ur, better], prof, "floor",
            DATASET["programs"], DATASET["merchants"])
        self.assertEqual([p["id"] for p in pruned], ["plain-ur"])


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
        r = score([card], make_profile({"other": 12000}), "floor")
        # 10000 × 1.0cpp + $100 = $200.
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
    def test_cap_competition_floor(self):
        # BCP 6% wins groceries at floor (Gold 4x*0.6cpp=2.4%): BCP takes 6000
        # (360), Gold takes overflow 4000 (96) + dining 4000 (96); BCP base 1%
        # beats Gold base 0.6% for other 6000 (60) → 612 earn. Gold credits
        # confirmed: dining tracker 4000 → 96+0+90+67.2 = 253.2.
        # Fees 95+325 → ongoing 612+253.2-420 = 445.2.
        # Bonuses: 250 + 360; year-1 fee 325 (BCP waived) → year1 1150.2.
        prof = make_profile({"groceries": 10000, "dining": 4000, "other": 6000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["blue-cash-preferred", "gold"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 612.0)
        self.assertAlmostEqual(r["ongoing_net"], 445.2)
        self.assertAlmostEqual(r["year1_net"], 1150.2)

    def test_cap_competition_flips_optimistic(self):
        # At 1.9cpp Gold groceries is 7.6% > BCP 6%: Gold takes all 10000
        # groceries (760) + dining (304); Gold base 1.9% takes other (114)
        # → 1178 earn; ongoing 1178+253.2-420=1011.2; year1 +250+1140-325 → 2496.2.
        prof = make_profile({"groceries": 10000, "dining": 4000, "other": 6000},
                            confirmed_usage=GOLD_KEYS)
        r = score(["blue-cash-preferred", "gold"], prof, "optimistic")
        self.assertAlmostEqual(r["earnings"], 1178.0)
        self.assertAlmostEqual(r["ongoing_net"], 1011.2)
        self.assertAlmostEqual(r["year1_net"], 2496.2)
        gold_groceries = [a for a in r["assignments"]
                          if a["card_id"] == "gold" and a["bucket"] == "groceries"]
        self.assertAlmostEqual(gold_groceries[0]["usd_assigned"], 10000.0)


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
        r = score(variants, prof, "floor")
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
        groceries = score([variants["custom-cash[groceries]"]], prof, "floor")
        self.assertAlmostEqual(groceries["ongoing_net"], 540.0)
        self.assertAlmostEqual(groceries["year1_net"], 740.0)
        dining = score([variants["custom-cash[dining]"]], prof, "floor")
        self.assertAlmostEqual(dining["ongoing_net"], 500.0)

    def test_best_configuration_flips_inside_a_combination(self):
        # Solo, groceries is custom-cash's best category; paired with Blue Cash
        # Preferred (6% groceries takes that bucket), the dining configuration
        # wins instead — the search re-configures the card per combination.
        prof = make_profile({"groceries": 6000, "dining": 5000, "other": 9000})
        variants = {v["id"]: v for v in
                    opt.expand_choice_variants([seed_card("custom-cash")], prof)}
        with_dining = score([seed_card("blue-cash-preferred"),
                             variants["custom-cash[dining]"]], prof, "floor")
        with_groceries = score([seed_card("blue-cash-preferred"),
                                variants["custom-cash[groceries]"]], prof, "floor")
        self.assertAlmostEqual(with_dining["earnings"], 700.0)
        self.assertAlmostEqual(with_groceries["earnings"], 500.0)
        self.assertGreater(with_dining["ongoing_net"], with_groceries["ongoing_net"])

    def test_search_never_pairs_two_variants_of_one_card(self):
        prof = make_profile(P30K, max_cards=2)
        variants = opt.expand_choice_variants([seed_card("custom-cash")], prof)
        results = opt.search(variants, prof, "floor", DATASET["programs"],
                             DATASET["merchants"], AS_OF)
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
        results = opt.search(variants, prof, "floor", DATASET["programs"],
                             DATASET["merchants"], AS_OF)
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
            opt.search(variants, prof, "floor", DATASET["programs"],
                       DATASET["merchants"], AS_OF)
        msg = str(ctx.exception)
        self.assertIn("max_cards", msg)
        self.assertIn("MAX_SCORED_SUBSETS", msg)

    def test_small_pool_searches_fine(self):
        variants = [synth_card(id="one", base_rate=1), synth_card(id="two", base_rate=2)]
        results = opt.search(variants, make_profile({"other": 5000}), "floor",
                             DATASET["programs"], DATASET["merchants"], AS_OF)
        self.assertEqual(len(results), 3)  # {one}, {two}, {one, two}

    def test_policy_constants_echo(self):
        pc = opt.policy_constants()
        self.assertIn("MAX_SCORED_SUBSETS", pc)
        self.assertNotIn("MAX_ELIGIBLE_CARDS", pc)


class TestDominancePruning(unittest.TestCase):
    """Exact pre-search dominance pruning (plan 02.5 §2)."""

    def prune(self, variants, prof, mode="floor"):
        return opt.prune_dominated_variants(variants, prof, mode,
                                            DATASET["programs"], DATASET["merchants"])

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
