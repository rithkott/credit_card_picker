"""Benefit-usage detection (plan 14 — the gutted successor of categorize.py).

Statement transactions are matched against data/meta/statement-descriptors.yaml
`statement_patterns` ONLY. A hit counts when the descriptor key resolves to a
usage-questions item — a service some card in the dataset ties a credit or
benefit to. There is no category assignment, no keyword/MCC/fuzzy/semantic
matching, and no spend import: the user enters spending manually, and detected
usage travels back as pre-checked suggestions for user.confirmed_usage.

Matching rules:
  - Patterns are case-insensitive substrings of the whitespace-normalized
    descriptor; the LONGEST pattern is tried first, identical patterns break
    ties by ascending key, so matching is order-independent and deterministic.
  - Descriptor entries marked `aggregator_prefix: true` (PAYPAL *, SQ *, TST*,
    APLPAY) hide the real merchant: the matched prefix is stripped and the
    remainder re-matched once. An unrecognized remainder is no match.
  - A hit on a descriptor key that is NOT a usage item (e.g. issuer travel
    portals) is skipped — scanning continues so a usage merchant elsewhere in
    the descriptor can still be found.

Only purchases and refunds are examined (refunds subtract client-side);
payments/fees/interest/transfers are never usage evidence.
"""

import re
from typing import List, Optional


class Matcher:
    def __init__(self, descriptors: dict, usage_questions: dict):
        """descriptors: statement-descriptors.yaml as loaded by app.py's
        lifespan; usage_questions: the dataset's usage-questions registry
        (its item keys are the detectable vocabulary)."""
        def by_length_then_key(p):
            return (-len(p[0]), p[1])

        self.patterns = sorted(
            ((pattern.upper(), key)
             for key, entry in descriptors.items()
             for pattern in entry["statement_patterns"]),
            key=by_length_then_key)
        self.prefix_keys = {
            key for key, entry in descriptors.items()
            if entry.get("aggregator_prefix")}
        self.usage_labels = {
            item_key: item["label"]
            for group in usage_questions.values()
            for item_key, item in group["items"].items()}


def normalize_descriptor(descriptor: str) -> str:
    return re.sub(r"\s+", " ", descriptor.upper()).strip()


def _match(m: Matcher, upper: str, depth: int) -> Optional[dict]:
    for pattern, key in m.patterns:
        if pattern not in upper:
            continue
        if key in m.usage_labels:
            return {"usage_key": key, "usage_label": m.usage_labels[key]}
        if key in m.prefix_keys and depth == 0:
            at = upper.index(pattern)
            remainder = upper[at + len(pattern):].strip()
            if remainder != "":
                inner = _match(m, remainder, 1)
                if inner is not None:
                    return inner
        # Non-usage descriptor key (portal, detection helper): keep scanning.
    return None


def match_usage(m: Matcher, descriptor: str) -> Optional[dict]:
    """{usage_key, usage_label} when the descriptor evidences a usage item,
    else None."""
    return _match(m, normalize_descriptor(descriptor), 0)


def detect_usage(m: Matcher, txns: List) -> List[dict]:
    """The `matches` half of the POST /api/statements/parse response: one
    wire dict per purchase/refund whose descriptor hits a usage item."""
    out = []
    for t in txns:
        if t.kind not in ("purchase", "refund"):
            continue
        hit = match_usage(m, t.descriptor)
        if hit is None:
            continue
        out.append({
            "date": t.date,
            "amount_cents": t.amount_cents,
            "descriptor": t.descriptor,
            "kind": t.kind,
            "line": t.line,
            **hit,
        })
    return out
