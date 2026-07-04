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


class TestSingleCardGolden(unittest.TestCase):
    """All 7 seed cards single-card, both modes (spec §9)."""

    def test_double_cash_worked_example(self):
        # Spec §4.3: floor ongoing $600, year-1 $800, optimistic ongoing $1,020.
        prof = make_profile(P30K)
        floor = score(["double-cash"], prof, "floor")
        self.assertAlmostEqual(floor["ongoing_net"], 600.0)
        self.assertAlmostEqual(floor["year1_net"], 800.0)
        optimistic = score(["double-cash"], prof, "optimistic")
        self.assertAlmostEqual(optimistic["ongoing_net"], 1020.0)
        self.assertAlmostEqual(optimistic["year1_net"], 1220.0)

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
        # Credits vs dining tracker 5000: dining 10*12*.5=60, Uber $0 (no transit
        # spend), Resy 50*2*.8=80, Dunkin 7*12*.5=42 → 182.
        # ongoing 414+182-325=271; bonus 60000*.006=360 → year1 631.
        prof = make_profile(P30K)
        r = score(["gold"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 414.0)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 182.0)
        self.assertAlmostEqual(r["ongoing_net"], 271.0)
        self.assertAlmostEqual(r["year1_net"], 631.0)

    def test_amex_gold_optimistic(self):
        # cpp 1.9: 5000*4*.019=380 + 8000*4*.019=608 + 17000*.019=323 = 1311.
        # ongoing 1311+182-325=1168; bonus 1140 → year1 2308.
        prof = make_profile(P30K)
        r = score(["gold"], prof, "optimistic")
        self.assertAlmostEqual(r["ongoing_net"], 1168.0)
        self.assertAlmostEqual(r["year1_net"], 2308.0)

    def test_sapphire_preferred_portal_off(self):
        # Portal-only 5x travel_other dropped → falls to base 1x.
        # floor: dining 120 + groceries 180 + hotels 40 + base(1000+7000)*1% 80
        # = 420; hotel credit min(50*0.9, 2000)=45; ongoing 420+45-95=370;
        # bonus 60000*1.0cpp=600 → year1 970.
        prof = make_profile({"dining": 4000, "groceries": 6000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 7000})
        r = score(["sapphire-preferred"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 420.0)
        self.assertAlmostEqual(r["ongoing_net"], 370.0)
        self.assertAlmostEqual(r["year1_net"], 970.0)

    def test_sapphire_preferred_portal_on(self):
        # travel_other kept at 5*0.75=3.75x → 1000*.0375=37.5 replaces base $10.
        prof = make_profile({"dining": 4000, "groceries": 6000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 7000},
                            uses_travel_portal=True)
        r = score(["sapphire-preferred"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 447.5)
        self.assertAlmostEqual(r["ongoing_net"], 397.5)

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
        # cpp 2.0 doubles everything: 460*2 = 920 ongoing; +$200 bonus → 1120.
        prof = make_profile({"dining": 4000, "groceries": 6000, "gas": 2000, "other": 8000})
        r = score(["freedom-flex"], prof, "optimistic")
        self.assertAlmostEqual(r["ongoing_net"], 920.0)
        self.assertAlmostEqual(r["year1_net"], 1120.0)

    def test_venture_x_portal_off(self):
        # Both elevated lines are portal-only → all 20000 at base 2x*0.5cpp=1%
        # → 200. Credits: travel credit min(300*0.9, 1000)=270 + anniversary 100
        # (automatic). ongoing 200+370-395=175; bonus 75000*.005=375 → year1 550.
        prof = make_profile({"travel_flights": 3000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 14000})
        r = score(["venture-x"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 200.0)
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 370.0)
        self.assertAlmostEqual(r["ongoing_net"], 175.0)
        self.assertAlmostEqual(r["year1_net"], 550.0)

    def test_venture_x_portal_on(self):
        # hotels 2000@7.5x*.005=75, flights 3000@3.75x*.005=56.25,
        # base 15000@1%=150 → 281.25; ongoing 281.25+370-395=256.25.
        prof = make_profile({"travel_flights": 3000, "travel_hotels": 2000,
                             "travel_other": 1000, "other": 14000},
                            uses_travel_portal=True)
        r = score(["venture-x"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 281.25)
        self.assertAlmostEqual(r["ongoing_net"], 256.25)


class TestCreditsAndBonus(unittest.TestCase):
    def test_credit_gating_no_dining_spend(self):
        # Without dining spend all three Gold dining credits are $0 with reasons.
        prof = make_profile({"groceries": 8000, "other": 22000})
        r = score(["gold"], prof, "floor")
        self.assertAlmostEqual(sum(c["value"] for c in r["credits"]), 0.0)
        for c in r["credits"]:
            self.assertIn("no remaining spend", c["note"])

    def test_stacked_credits_capped_by_real_spend(self):
        # Only $80 of dining spend: file order draws dining $60, then Resy
        # min(80, remaining 20)=20, then Dunkin $0.
        prof = make_profile({"dining": 80, "other": 30000})
        r = score(["gold"], prof, "floor")
        by_name = {c["name"]: c["value"] for c in r["credits"]}
        self.assertAlmostEqual(by_name["Dining credit (Grubhub, Cheesecake Factory, etc.)"], 60.0)
        self.assertAlmostEqual(by_name["Resy dining credit"], 20.0)
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
        card = synth_card(currency={"type": "points", "program": "chase_ur"},
                          credits=[credit])
        prof = make_profile({"other": 5000})
        self.assertAlmostEqual(score([card], prof, "floor")["credits"][0]["value"], 100.0)
        self.assertAlmostEqual(score([card], prof, "optimistic")["credits"][0]["value"], 200.0)

    def test_in_kind_credit_always_haircut(self):
        # Uncategorized statement credits pay full face; in_kind gets the
        # period capture haircut even without a category (annual = 0.9).
        credit = {"name": "free night", "kind": "in_kind", "amount_usd": 150,
                  "period": "annual", "realistic_capture_rate_note": "estimate"}
        r = score([synth_card(credits=[credit])], make_profile({"other": 5000}))
        self.assertAlmostEqual(r["credits"][0]["value"], 135.0)


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

    def test_clamped_earnings_feed_first_year_match(self):
        card = synth_card(base_rate=5, max_annual_rewards_usd=300,
                          signup_bonus={"first_year_match": True})
        r = score([card], make_profile({"other": 10000}))
        self.assertAlmostEqual(r["bonuses"]["synth"]["value"], 300.0)

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
        # 182 (dining tracker 4000). Fees 95+325 → ongoing 374.
        # Bonuses: 250 + 360; year-1 fee 325 (BCP waived) → year1 1079.
        prof = make_profile({"groceries": 10000, "dining": 4000, "other": 6000})
        r = score(["blue-cash-preferred", "gold"], prof, "floor")
        self.assertAlmostEqual(r["earnings"], 612.0)
        self.assertAlmostEqual(r["ongoing_net"], 374.0)
        self.assertAlmostEqual(r["year1_net"], 1079.0)

    def test_cap_competition_flips_optimistic(self):
        # At 1.9cpp Gold groceries is 7.6% > BCP 6%: Gold takes all 10000
        # groceries (760) + dining (304); Gold base 1.9% takes other (114)
        # → 1178 earn; ongoing 1178+182-420=940; year1 +250+1140-325 → 2425.
        prof = make_profile({"groceries": 10000, "dining": 4000, "other": 6000})
        r = score(["blue-cash-preferred", "gold"], prof, "optimistic")
        self.assertAlmostEqual(r["earnings"], 1178.0)
        self.assertAlmostEqual(r["ongoing_net"], 940.0)
        self.assertAlmostEqual(r["year1_net"], 2425.0)
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
        eligible, excluded = opt.filter_cards(DATASET["cards"], prof)
        self.assertEqual([e["id"] for e in excluded], ["venture-x"])
        self.assertEqual(len(eligible), 7)

    def test_search_is_exhaustive_and_ranked(self):
        # 7 eligible cards; custom-cash expands to 2 variants (dining, groceries)
        # → 8 variants, minus combos pairing both custom-cash variants:
        # C(8,1) + C(8,2)-1 + C(8,3)-6 = 8 + 27 + 50 = 85.
        prof = make_profile(P30K, credit_tier="good")
        eligible, _ = opt.filter_cards(DATASET["cards"], prof)
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
