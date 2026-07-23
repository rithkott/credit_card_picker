"""Deterministic in-process token-bucket rate limiter for the API.

Design (backend-hardening): pure stdlib, no external store. On Vercel, Fluid
Compute reuses function instances across concurrent requests, so a
per-instance bucket gives real (approximate) flood protection from a single
source; horizontal scale multiplies the budgets and cold starts reset them —
this is flood protection, not quota enforcement. Vercel's edge DDoS
mitigation / WAF rate rules are the platform-side complement.

The clock is injected so tests are exact: no sleeps, no wall-clock reads.
"""

import math
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    capacity: float        # max burst (tokens in a full bucket)
    refill_per_sec: float  # sustained rate


# Route classes: cheap immutable GETs, expensive optimizer POSTs, and the
# statement-upload POST (frontend uploads sequentially, batch cap 120 files).
ROUTE_BUDGETS = {
    "read": Budget(60, 1.0),
    "compute": Budget(10, 0.25),
    "upload": Budget(40, 1.0),
}

_READ_PATHS = {"/api/health", "/api/cards", "/api/assumptions", "/api/config"}
_COMPUTE_PATHS = {"/api/optimize", "/api/evaluate", "/api/suggest-addition"}


def classify(method: str, path: str) -> str | None:
    """Route class for a request, or None for unlimited (SPA catch-all,
    unknown paths, and OPTIONS — CORS preflight must never be throttled)."""
    if method == "GET" and path in _READ_PATHS:
        return "read"
    if method == "POST" and path in _COMPUTE_PATHS:
        return "compute"
    if method == "POST" and path == "/api/statements/parse":
        return "upload"
    return None


class TokenBucketLimiter:
    """Lazy-refill token buckets keyed by "<route_class>:<client-ip>".

    check() consumes a token and returns None when allowed, otherwise the
    whole number of seconds until one token is available (for Retry-After).
    Sync routes run in Starlette's threadpool, so check() takes a lock.
    """

    def __init__(self, budgets=ROUTE_BUDGETS, clock=time.monotonic,
                 max_keys=10_000, idle_evict_secs=600.0):
        self.budgets = budgets
        self.clock = clock
        self.max_keys = max_keys
        self.idle_evict_secs = idle_evict_secs
        self.enabled = True  # tests flip this off; middleware honors it
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last)

    def check(self, key: str, route_class: str) -> int | None:
        budget = self.budgets[route_class]
        bucket_key = f"{route_class}:{key}"
        with self._lock:
            now = self.clock()
            tokens, last = self._buckets.get(bucket_key,
                                             (budget.capacity, now))
            tokens = min(budget.capacity,
                         tokens + (now - last) * budget.refill_per_sec)
            if tokens >= 1.0:
                self._buckets[bucket_key] = (tokens - 1.0, now)
                self._maybe_evict(now)
                return None
            self._buckets[bucket_key] = (tokens, now)
            self._maybe_evict(now)
            return max(1, math.ceil((1.0 - tokens) / budget.refill_per_sec))

    def _maybe_evict(self, now: float) -> None:
        # Bounds memory on long-lived instances; called under self._lock.
        if len(self._buckets) <= self.max_keys:
            return
        stale = [k for k, (_, last) in self._buckets.items()
                 if now - last > self.idle_evict_secs]
        for k in stale:
            del self._buckets[k]
