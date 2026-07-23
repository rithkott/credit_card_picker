"""Unit tests for server/ratelimit.py — pure stdlib, no FastAPI needed, so
they run in the pyyaml-only CI environment. The clock is injected: every
assertion is exact, no sleeps.

Run: python3 -m unittest tests.test_ratelimit
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from ratelimit import Budget, TokenBucketLimiter, classify  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, secs):
        self.now += secs


def make(budgets=None, **kw):
    clock = FakeClock()
    limiter = TokenBucketLimiter(
        budgets=budgets or {"compute": Budget(3, 0.5)}, clock=clock, **kw)
    return limiter, clock


class TestClassify(unittest.TestCase):
    def test_route_classes(self):
        self.assertEqual(classify("GET", "/api/health"), "read")
        self.assertEqual(classify("GET", "/api/cards"), "read")
        self.assertEqual(classify("GET", "/api/config"), "read")
        self.assertEqual(classify("GET", "/api/assumptions"), "read")
        self.assertEqual(classify("POST", "/api/optimize"), "compute")
        self.assertEqual(classify("POST", "/api/evaluate"), "compute")
        self.assertEqual(classify("POST", "/api/suggest-addition"), "compute")
        self.assertEqual(classify("POST", "/api/statements/parse"), "upload")

    def test_unlimited_routes(self):
        # CORS preflight and the SPA catch-all must never be throttled.
        self.assertIsNone(classify("OPTIONS", "/api/optimize"))
        self.assertIsNone(classify("GET", "/"))
        self.assertIsNone(classify("GET", "/how-it-works"))
        self.assertIsNone(classify("GET", "/api/unknown"))


class TestTokenBucket(unittest.TestCase):
    def test_burst_up_to_capacity_then_reject(self):
        limiter, _ = make()
        for _ in range(3):
            self.assertIsNone(limiter.check("ip1", "compute"))
        retry = limiter.check("ip1", "compute")
        self.assertIsInstance(retry, int)
        self.assertGreater(retry, 0)

    def test_retry_after_is_exact_ceil(self):
        limiter, _ = make()  # refill 0.5/s: 1 token takes 2 s
        for _ in range(3):
            limiter.check("ip1", "compute")
        self.assertEqual(limiter.check("ip1", "compute"), 2)

    def test_refill_restores_exactly_one_token(self):
        limiter, clock = make()
        for _ in range(3):
            limiter.check("ip1", "compute")
        self.assertIsNotNone(limiter.check("ip1", "compute"))
        clock.advance(2.0)  # exactly one token at 0.5/s
        self.assertIsNone(limiter.check("ip1", "compute"))
        self.assertIsNotNone(limiter.check("ip1", "compute"))

    def test_tokens_cap_at_capacity(self):
        limiter, clock = make()
        clock.advance(1000.0)  # long idle must not build an unbounded burst
        for _ in range(3):
            self.assertIsNone(limiter.check("ip1", "compute"))
        self.assertIsNotNone(limiter.check("ip1", "compute"))

    def test_keys_are_independent(self):
        budgets = {"compute": Budget(1, 0.5), "read": Budget(1, 0.5)}
        limiter, _ = make(budgets=budgets)
        self.assertIsNone(limiter.check("ip1", "compute"))
        self.assertIsNotNone(limiter.check("ip1", "compute"))
        # Different IP and different route class each get their own bucket.
        self.assertIsNone(limiter.check("ip2", "compute"))
        self.assertIsNone(limiter.check("ip1", "read"))

    def test_eviction_prunes_idle_keeps_active(self):
        limiter, clock = make(max_keys=5, idle_evict_secs=600.0)
        for i in range(5):
            limiter.check(f"idle{i}", "compute")
        clock.advance(601.0)
        limiter.check("active", "compute")  # 6th key triggers the prune
        limiter.check("trigger", "compute")
        keys = set(limiter._buckets)
        self.assertIn("compute:active", keys)
        self.assertNotIn("compute:idle0", keys)

    def test_enabled_flag_defaults_true(self):
        limiter, _ = make()
        self.assertTrue(limiter.enabled)


if __name__ == "__main__":
    unittest.main()
