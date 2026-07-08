"""Engine-equivalence and bound-admissibility tests for the branch-and-bound
search (scripts/search_bnb.py, plan 10 §3).

The bnb engine's whole contract is: byte-identical bundles to the exhaustive
oracle, given the same pruning setting. These tests pin that over the frozen
fixture dataset (which contains a transfer gateway, a gateway-gated rotating
card, capped categories, shared caps via choice expansion, points credits, and
plain cash cards) across a matrix of profile toggles, plus seeded random
synthetic pools; and they verify the admissible bound U(S) >= net(S) directly
by brute force.

Run: python3 -m unittest discover tests
"""

import random
import sys
import unittest
from datetime import date
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import optimize as opt
import search_bnb

FIXTURE_DATA = Path(__file__).resolve().parent / "fixtures" / "data"
opt.CARDS_DIR = FIXTURE_DATA / "cards"
opt.META_DIR = FIXTURE_DATA / "meta"

AS_OF = date(2026, 7, 3)
DATASET = opt.load_dataset()

GOLD_KEYS = ["chase_travel", "uber"]  # portal + credit keys in the fixture


def profile_of(spend, **user):
    raw = {"spend": spend, "user": {"credit_tier": "excellent", **user}}
    return opt.parse_profile(raw, DATASET)


SPEND_FULL = {"dining": 6000, "groceries": 8000, "gas": 3000,
              "travel_flights": 4000, "travel_hotels": 2500,
              "online_shopping": 3000, "drugstores": 900, "other": 9000}


def run_both(profile, top=5, prune=False):
    a = opt.render_json(opt.run(DATASET, profile, AS_OF, top,
                                engine="bnb", prune=prune))
    b = opt.render_json(opt.run(DATASET, profile, AS_OF, top,
                                engine="exhaustive", prune=prune))
    return a, b


class TestEngineEquivalence(unittest.TestCase):
    def assert_equivalent(self, profile, top=5):
        for prune in (False, True):
            a, b = run_both(profile, top=top, prune=prune)
            self.assertEqual(a, b, msg=f"engines diverge (prune={prune})")

    def test_matrix_over_fixture(self):
        cases = []
        for optimize_for in ("ongoing", "year1"):
            for max_cards in (1, 2, 3, 4, 5):
                cases.append(dict(optimize_for=optimize_for,
                                  max_cards=max_cards))
        for user in cases:
            with self.subTest(**user):
                self.assert_equivalent(profile_of(SPEND_FULL, **user))

    def test_confirmed_usage_and_rotating_toggles(self):
        confirmed = sorted(set(
            key for group in DATASET["usage_questions"].values()
            for key in (group.get("items") or {})))
        for user in (dict(max_cards=3, confirmed_usage=confirmed),
                     dict(max_cards=3, activates_rotating=False),
                     dict(max_cards=4, confirmed_usage=confirmed,
                          optimize_for="year1")):
            with self.subTest(**user):
                self.assert_equivalent(profile_of(SPEND_FULL, **user))

    def test_sparse_and_lopsided_profiles(self):
        for spend in ({"groceries": 12000},
                      {"other": 40000},
                      {"dining": 100, "gas": 100, "other": 100},
                      {"travel_flights": 20000, "dining": 5000}):
            with self.subTest(spend=spend):
                self.assert_equivalent(profile_of(spend, max_cards=4))

    def test_top_values(self):
        prof = profile_of(SPEND_FULL, max_cards=3)
        for top in (1, 2, 10, 100):
            with self.subTest(top=top):
                for prune in (False, True):
                    a, b = run_both(prof, top=top, prune=prune)
                    self.assertEqual(a, b)

    def test_pure_python_fallback_matches_numpy(self):
        # search_bnb's bound arithmetic has a numpy fast path and a pure
        # stdlib fallback; both must produce the same bundle (bound floats
        # never reach output bytes, but pruning decisions must agree enough
        # to keep the exact result identical — which they do by admissibility
        # either way).
        prof = profile_of(SPEND_FULL, max_cards=3)
        with_np = opt.render_json(opt.run(DATASET, prof, AS_OF, 5))
        saved = sys.modules.get("numpy")
        sys.modules["numpy"] = None  # forces ImportError inside search_bnb
        try:
            without_np = opt.render_json(opt.run(DATASET, prof, AS_OF, 5))
        finally:
            if saved is None:
                del sys.modules["numpy"]
            else:
                sys.modules["numpy"] = saved
        self.assertEqual(with_np, without_np)

    def test_random_synthetic_pools(self):
        rng = random.Random(20260709)
        cats = ["dining", "groceries", "gas", "online_shopping", "other"]
        for trial in range(25):
            cards = []
            for ci in range(rng.randint(3, 10)):
                rewards = []
                for cat in rng.sample(cats, rng.randint(0, 3)):
                    reward = {"category": cat, "rate": rng.choice([2, 3, 4, 5])}
                    if rng.random() < 0.5:
                        reward["cap"] = {"period": "quarterly",
                                         "max_spend_usd": rng.choice([500, 1500]),
                                         "fallback_rate": 1}
                    rewards.append(reward)
                fee = rng.choice([0, 0, 95, 250])
                bonus = None
                if rng.random() < 0.4:
                    bonus = {"value": {"usd": rng.choice([200, 500])},
                             "spend_requirement_usd": 1000, "window_months": 3}
                cards.append({
                    "id": f"synth-{trial}-{ci:02d}", "name": f"Synth {ci}",
                    "issuer": "test", "network": "visa",
                    "currency": {"type": "cash", "program": "cash"},
                    "base_rate": rng.choice([1, 1.5, 2]),
                    "category_rewards": rewards, "merchant_rewards": [],
                    "credits": [], "signup_bonus": bonus,
                    "fees": {"annual_fee_usd": fee,
                             "foreign_transaction_pct": 0},
                    "approval": {"credit_tier": "good"}, "benefit_flags": [],
                    "verification": {"last_verified_date": "2026-07-03",
                                     "verified_by": "test",
                                     "confidence": "high"},
                })
            dataset = {**{k: DATASET[k] for k in
                          ("categories", "merchants", "programs",
                           "usage_questions", "usage_keys")},
                       "cards": cards}
            spend = {c: rng.choice([500, 3000, 8000]) for c in cats}
            prof = opt.parse_profile(
                {"spend": spend,
                 "user": {"credit_tier": "excellent",
                          "max_cards": rng.randint(1, 4),
                          "optimize_for": rng.choice(["ongoing", "year1"])}},
                dataset)
            with self.subTest(trial=trial):
                for prune in (False, True):
                    a = opt.render_json(opt.run(dataset, prof, AS_OF, 5,
                                                engine="bnb", prune=prune))
                    b = opt.render_json(opt.run(dataset, prof, AS_OF, 5,
                                                engine="exhaustive", prune=prune))
                    self.assertEqual(a, b, msg=f"trial {trial} prune={prune}")


class TestBoundAdmissible(unittest.TestCase):
    """U(S) >= net(S) for every subset, both metrics — brute force over the
    fixture pool (post choice-expansion), the direct proof obligation behind
    the pruning rule."""

    def test_bound_dominates_every_subset(self):
        prof = profile_of(SPEND_FULL, max_cards=3,
                          confirmed_usage=GOLD_KEYS)
        eligible, _ = opt.filter_cards(DATASET["cards"], prof,
                                       DATASET["programs"])
        variants = opt.expand_choice_variants(eligible, prof)
        buckets = opt.build_buckets(prof, DATASET["merchants"])
        tables = opt.RunTables(variants, prof, DATASET["programs"],
                               buckets, AS_OF)
        live, s, binfo = search_bnb.bound_inputs(variants, prof, buckets,
                                                 tables)
        by_id = {v["id"]: v for v in variants}
        base_of = {cid: by_id[cid].get("base_id", cid) for cid in by_id}
        ids = sorted(by_id)
        checked = 0
        for k in (1, 2, 3):
            for combo in combinations(ids, k):
                if len({base_of[c] for c in combo}) < k:
                    continue
                sc = opt.score_portfolio([by_id[c] for c in combo], prof,
                                         DATASET["programs"], buckets, AS_OF,
                                         tables=tables)
                for metric, xkey in (("ongoing_net", "x_on"),
                                     ("year1_net", "x_y1")):
                    ub = sum(si * max(binfo[c]["rbar"][i] for c in combo)
                             for i, si in enumerate(s))
                    ub += sum(binfo[c][xkey] for c in combo)
                    self.assertGreaterEqual(
                        ub + 1e-6, sc[metric],
                        msg=f"bound violated for {combo} on {metric}")
                checked += 1
        self.assertGreater(checked, 50)


if __name__ == "__main__":
    unittest.main()
