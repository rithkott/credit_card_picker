"""Tests for scripts/assign_exact.py (plan 10 §2): the greedy-exactness
detector and the deterministic flow solver, cross-checked against
scipy.optimize.linprog — scipy is a test-time oracle only; the runtime never
imports it.

Run: python3 -m unittest discover tests
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import assign_exact as ax
import optimize as opt


def bucket(amount):
    return {"amount": float(amount)}


def buckets_of(**amounts):
    return {k: bucket(v) for k, v in amounts.items()}


def line(card_id, key, rate, eligible, room=None, room_key=None, kind="category"):
    return {"card_id": card_id, "kind": kind, "key": key, "rate": rate,
            "cpp": 1.0, "effective_rate": rate,
            "room": room, "room_key": room_key,
            "eligible": sorted(eligible), "note": ""}


def base_line(card_id, rate, eligible):
    return line(card_id, "base", rate, eligible, kind="base")


def lp_oracle(lines, buckets):
    """Reference optimum via scipy linprog (HiGHS): variables are the eligible
    (line, bucket) pairs; constraints are bucket amounts and capped-unit rooms."""
    from scipy.optimize import linprog

    live = sorted(ax.live_bucket_keys(buckets))
    pairs = [(i, b) for i, ln in enumerate(lines)
             for b in ln["eligible"] if b in set(live)]
    if not pairs:
        return 0.0
    c = [-lines[i]["effective_rate"] for i, _ in pairs]
    a_ub, b_ub = [], []
    for lb in live:
        a_ub.append([1.0 if b == lb else 0.0 for _, b in pairs])
        b_ub.append(buckets[lb]["amount"])
    for unit in ax.capped_units(lines, set(live)):
        members = set(unit["lines"])
        a_ub.append([1.0 if i in members else 0.0 for i, _ in pairs])
        b_ub.append(unit["room"])
    res = linprog(c, A_ub=a_ub, b_ub=b_ub, bounds=(0, None), method="highs")
    assert res.status == 0, res.message
    return -res.fun


class TestDetector(unittest.TestCase):
    def test_no_caps_is_exact(self):
        lines = [base_line("a", 1.0, ["x", "y"]), line("b", "x", 2.0, ["x"])]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(x=100, y=100)))

    def test_single_capped_multibucket_is_exact(self):
        lines = [line("a", "rot", 5.0, ["x", "y"], room=1500),
                 base_line("a", 1.0, ["x", "y"])]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(x=100, y=100)))

    def test_disjoint_capped_units_are_exact(self):
        lines = [line("a", "gas", 4.0, ["gas"], room=1000),
                 line("b", "groceries", 3.0, ["groceries"], room=2000),
                 base_line("a", 1.0, ["gas", "groceries"])]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(gas=500, groceries=500)))

    def test_identical_singleton_units_are_exact(self):
        lines = [line("a", "gas", 4.0, ["gas"], room=1000),
                 line("b", "gas", 3.0, ["gas"], room=2000)]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(gas=5000)))

    def test_overlapping_multibucket_units_flagged(self):
        lines = [line("a", "rot", 5.0, ["gas", "groceries"], room=1500),
                 line("b", "groceries", 4.0, ["groceries"], room=2000)]
        self.assertFalse(ax.greedy_is_exact(lines, buckets_of(gas=2000, groceries=3000)))

    def test_nonbinding_caps_are_invisible(self):
        # Same shape as test_overlapping_multibucket_units_flagged, but the
        # spend is small enough that neither cap can bind — the constraint is
        # slack in every feasible solution, so greedy stays exact.
        lines = [line("a", "rot", 5.0, ["gas", "groceries"], room=1500),
                 line("b", "groceries", 4.0, ["groceries"], room=2000)]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(gas=500, groceries=500)))

    def test_multiline_pool_with_two_live_buckets_flagged(self):
        pool = "card|pool"
        lines = [line("a", "gas", 3.0, ["gas"], room=2500, room_key=pool),
                 line("a", "groceries", 2.0, ["groceries"], room=2500, room_key=pool)]
        self.assertFalse(ax.greedy_is_exact(lines, buckets_of(gas=2000, groceries=2000)))

    def test_multiline_pool_single_live_bucket_is_exact(self):
        pool = "card|pool"
        lines = [line("a", "gas", 3.0, ["gas"], room=2500, room_key=pool),
                 line("a", "groceries", 2.0, ["groceries"], room=2500, room_key=pool)]
        # No grocery spend: the pool has one live bucket, greedy drains it fine.
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(gas=500, groceries=0)))

    def test_dead_bucket_overlap_ignored(self):
        lines = [line("a", "rot", 5.0, ["gas", "groceries"], room=1500),
                 line("b", "groceries", 4.0, ["groceries"], room=2000)]
        self.assertTrue(ax.greedy_is_exact(lines, buckets_of(gas=500, groceries=0)))

    def test_masks_agree_with_reference(self):
        # The RunTables bitmask fast path (unit_masks + masks_compatible) must
        # return exactly the reference verdict for every detector scenario.
        rng = random.Random(20260708)
        cats = ["a", "b", "c", "d"]
        for trial in range(200):
            buckets = {c: bucket(rng.choice([0, 500, 2000, 6000])) for c in cats}
            lines = []
            pool_key = "x|pool" if rng.random() < 0.5 else None
            for li in range(rng.randint(0, 5)):
                elig = rng.sample(cats, rng.randint(1, 3))
                capped = rng.random() < 0.7
                lines.append(line(
                    "x", f"k{li}", rng.choice([2, 3, 4]), elig,
                    room=rng.choice([500, 1500, 4000, 20000]) if capped else None,
                    room_key=pool_key if capped and rng.random() < 0.5 else None))
            bucket_bit = {b: 1 << i for i, b in enumerate(sorted(
                b for b, bk in buckets.items() if bk["amount"] > ax.EPS))}
            masks = ax.unit_masks(lines, buckets, bucket_bit)
            fast = False if masks is False else ax.masks_compatible(masks)
            self.assertEqual(fast, ax.greedy_is_exact(lines, buckets),
                             msg=f"trial {trial}")


class TestSolver(unittest.TestCase):
    def solve_and_check(self, lines, buckets):
        total, flows = ax.solve_assignment(lines, buckets)
        # Feasibility: bucket amounts and unit rooms respected.
        by_bucket, by_unit = {}, {}
        unit_of = {}
        for u_idx, u in enumerate(ax.capped_units(lines, ax.live_bucket_keys(buckets))):
            for i in u["lines"]:
                unit_of[i] = (u_idx, u["room"])
        for (i, b), f in flows.items():
            self.assertGreater(f, 0)
            by_bucket[b] = by_bucket.get(b, 0.0) + f
            if i in unit_of:
                key = unit_of[i][0]
                by_unit[key] = by_unit.get(key, 0.0) + f
        for b, used in by_bucket.items():
            self.assertLessEqual(used, buckets[b]["amount"] + 1e-6)
        for u_idx, used in by_unit.items():
            room = next(r for i, (u, r) in unit_of.items() if u == u_idx)
            self.assertLessEqual(used, room + 1e-6)
        return total, flows

    def test_matches_oracle_on_overlapping_caps(self):
        # Capped wildcard (5x on gas+groceries, $1000 room) vs capped grocery
        # line (4x, $2000 room) vs weak base — the regret rule happens to tie
        # the optimum here; the solver must too.
        lines = [line("a", "rot", 5.0, ["gas", "groceries"], room=1000),
                 line("b", "groceries", 4.0, ["groceries"], room=2000),
                 base_line("a", 1.0, ["gas", "groceries"])]
        buckets = buckets_of(gas=1000, groceries=2000)
        total, _ = self.solve_and_check(lines, buckets)
        self.assertAlmostEqual(total, lp_oracle(lines, buckets), places=6)
        # wildcard->gas 5x*1000 + grocery cap 4x*2000
        self.assertAlmostEqual(total, 5.0 * 1000 + 4.0 * 2000, places=6)

    def test_multiline_pool_split(self):
        # One $2500 pool across two lines; optimum spends it where the
        # displaced alternative is weakest.
        pool = "card|pool"
        lines = [line("a", "online", 3.0, ["online"], room=2500, room_key=pool),
                 line("a", "groceries", 3.0, ["groceries"], room=2500, room_key=pool),
                 base_line("b", 2.5, ["online"]),   # strong alternative on online
                 base_line("a", 1.0, ["online", "groceries"])]
        buckets = buckets_of(online=2000, groceries=2000)
        total, _ = self.solve_and_check(lines, buckets)
        self.assertAlmostEqual(total, lp_oracle(lines, buckets), places=6)
        # Pool -> groceries 2000 (3.0 beats 1.0) + pool -> online 500,
        # rest of online at 2.5.
        expected = 3.0 * 2000 + 3.0 * 500 + 2.5 * 1500
        self.assertAlmostEqual(total, expected, places=6)

    def test_randomized_against_scipy(self):
        rng = random.Random(20260707)
        cats = ["a", "b", "c", "d", "e"]
        for trial in range(60):
            buckets = {c: bucket(rng.choice([0, 500, 1500, 4000])) for c in cats}
            lines = []
            n_cards = rng.randint(1, 4)
            for ci in range(n_cards):
                cid = f"card{ci}"
                pool_key = f"{cid}|pool" if rng.random() < 0.4 else None
                for li in range(rng.randint(0, 3)):
                    elig = rng.sample(cats, rng.randint(1, 3))
                    capped = rng.random() < 0.6
                    lines.append(line(
                        cid, f"k{li}", rng.choice([1.5, 2, 3, 4, 5, 6]), elig,
                        room=rng.choice([500, 1000, 2500]) if capped else None,
                        room_key=pool_key if capped and rng.random() < 0.5 else None))
                lines.append(base_line(cid, rng.choice([1, 1.5, 2]), cats))
            total, _ = self.solve_and_check(lines, buckets)
            self.assertAlmostEqual(total, lp_oracle(lines, buckets), places=5,
                                   msg=f"trial {trial}")

    def test_deterministic(self):
        lines = [line("a", "rot", 5.0, ["gas", "groceries"], room=1000),
                 line("b", "groceries", 4.0, ["groceries"], room=2000),
                 base_line("a", 1.0, ["gas", "groceries"])]
        buckets = buckets_of(gas=1000, groceries=2000)
        first = ax.solve_assignment(lines, buckets)
        for _ in range(5):
            self.assertEqual(repr(ax.solve_assignment(lines, buckets)), repr(first))


class TestDispatcher(unittest.TestCase):
    """assign_spend adopts the flow solution only when it strictly beats greedy."""

    def test_greedy_kept_when_tied(self):
        lines = [line("a", "gas", 4.0, ["gas"], room=1000),
                 base_line("a", 1.0, ["gas"])]
        buckets = buckets_of(gas=500)
        got, _ = opt.assign_spend(lines, buckets)
        want, _ = opt.assign_spend_greedy(lines, buckets)
        self.assertEqual(got, want)

    def test_flow_adopted_when_strictly_better(self):
        # The 02.5 §2.4 rerouting hole: the regret rule sees a 2.9x line on B
        # and treats B as safe to skip, but that line's room (1000) cannot
        # absorb all of B's spend (2000). Optimum: wildcard->B, uncapped
        # 2.8x line keeps A.
        lines = [line("w", "wild", 3.0, ["A", "B"], room=1000),
                 line("c", "B", 2.9, ["B"], room=1000),
                 line("d", "A", 2.8, ["A"]),
                 base_line("w", 1.0, ["A", "B"])]
        buckets = buckets_of(A=1000, B=2000)
        greedy, _ = opt.assign_spend_greedy(lines, buckets)
        greedy_total = sum(a["usd_value"] for a in greedy)
        self.assertAlmostEqual(greedy_total,
                               3.0 * 1000 + 2.9 * 1000 + 1.0 * 1000, places=6)
        got, unassigned = opt.assign_spend(lines, buckets)
        got_total = sum(a["usd_value"] for a in got)
        optimal = lp_oracle(lines, buckets)
        self.assertAlmostEqual(optimal,
                               3.0 * 1000 + 2.9 * 1000 + 2.8 * 1000, places=6)
        self.assertAlmostEqual(got_total, optimal, places=6)
        self.assertGreater(got_total, greedy_total)
        # Every dollar still assigned exactly once.
        self.assertEqual(unassigned, {})
        per_bucket = {}
        for a in got:
            per_bucket[a["bucket"]] = per_bucket.get(a["bucket"], 0.0) + a["usd_assigned"]
        for b, bk in buckets.items():
            self.assertAlmostEqual(per_bucket.get(b, 0.0), bk["amount"], places=6)


if __name__ == "__main__":
    unittest.main()
