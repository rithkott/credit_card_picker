"""Deterministic transaction categorization (port of site categorize.ts
+ new fuzzy layer 5).

Rules come from the registries the server already loads at startup
(data/meta/category-rules.yaml + statement-descriptors.yaml); nothing is
embedded here. Layered matching per transaction, first hit wins:

  1. descriptor patterns -> descriptor_categories bridge; the same hit also
     tallies a merchant carve-out (merchants.yaml keys) and a confirmed-
     usage suggestion (usage-questions items). Aggregator-prefix keys strip
     the matched prefix and re-run layers 1-2 on the remainder; explicitly
     unmapped keys (venmo, bilt_rent) surface as labeled review groups.
  2. generic keyword stems
  3. the issuer's own CSV category column
  4. MCC / OFX SIC ranges
  5. NEW (plan 12): fuzzy match (rapidfuzz token_set_ratio >= 90) of the
     descriptor stem against layer-1/2 patterns — catches misspellings and
     truncations exact substring matching can't. Fuzzy NEVER overrides an
     exact hit (it only runs after 1-4 miss), never resolves into aggregator
     prefixes or explicitly-unmapped keys (those need exact evidence), and
     is marked method="fuzzy" with its score so the review UI can disclose
     approximate matches.
  6. NEW (plan 13): semantic match — a LOCAL transformer (semantic.py,
     MiniLM int8 ONNX) scores the stem against per-category archetype
     phrases from category-rules.yaml (semantic_prototypes). "JOES DELI" /
     "AMC THEATRES" resolve without a hand-written pattern; one confidence
     gate, the model's call is trusted and every placement stays editable
     on the review screen. method="semantic" + confidence. When even layer 6
     misses (top-1 below the gate), the top-1 candidate is still attached as
     match["suggestion"] = {"category", "confidence"} — a pre-filled guess
     for the review UI that only user confirmation turns into spend.

Within a layer the LONGEST pattern wins; identical patterns shared by two
descriptor keys (APPLE.COM/BILL) break ties by ascending key so matching is
order-independent and deterministic.
"""

import re
import sys
from typing import List, Optional

try:
    from rapidfuzz import fuzz, process
    HAVE_FUZZ = True
except ImportError:  # local dev without rapidfuzz: layers 1-4 still work
    HAVE_FUZZ = False

try:  # numpy/tokenizers or the exported model may be absent locally
    from .semantic import ACCEPT_SIM, MODEL_DIR, SemanticMatcher
    HAVE_SEMANTIC = (MODEL_DIR / "model_quantized.onnx").exists()
except ImportError:
    HAVE_SEMANTIC = False
    ACCEPT_SIM = 0.40  # unreachable without the model; keeps the gate referable

FUZZY_CUTOFF = 90.0
FUZZY_MIN_PATTERN = 5  # short stems ("CVS") false-positive too easily


class Matcher:
    def __init__(self, descriptors: dict, category_rules: dict,
                 merchants: dict, usage_questions: dict):
        """descriptors/category_rules: the two registries as loaded by
        app.py's lifespan; merchants/usage_questions: dataset registries
        (merchant keys and usage-question item labels)."""
        def by_length_then_key(p):
            return (-len(p[0]), p[1])

        self.descriptor_patterns = sorted(
            ((pattern.upper(), key)
             for key, entry in descriptors.items()
             for pattern in entry["statement_patterns"]),
            key=by_length_then_key)
        self.keyword_patterns = sorted(
            ((pattern.upper(), category)
             for category, patterns in category_rules["keywords"].items()
             for pattern in patterns),
            key=by_length_then_key)
        self.bridge = category_rules["descriptor_categories"]
        self.prefixes = category_rules["aggregator_prefixes"]
        self.issuer_categories = category_rules["issuer_categories"]
        self.mcc = category_rules["mcc"]
        self.merchant_keys = set(merchants)
        self.usage_labels = {
            item_key: item["label"]
            for group in usage_questions.values()
            for item_key, item in group["items"].items()}
        self.descriptor_labels = {
            key: entry.get("label", key) for key, entry in descriptors.items()}

        # Fuzzy candidates: (pattern, kind, key). Aggregator prefixes and
        # explicitly-unmapped keys are excluded — resolving those needs the
        # exact evidence of a literal substring hit.
        self.fuzzy_choices = []
        if HAVE_FUZZ:
            for pattern, key in self.descriptor_patterns:
                if len(pattern) >= FUZZY_MIN_PATTERN and key in self.bridge:
                    self.fuzzy_choices.append((pattern, "descriptor", key))
            for pattern, category in self.keyword_patterns:
                if len(pattern) >= FUZZY_MIN_PATTERN:
                    self.fuzzy_choices.append((pattern, "keyword", category))

        # Layer 6 (plan 13): built lazily on first use — loading the ONNX
        # session shouldn't tax startups that never parse statements.
        self.semantic_prototypes = category_rules.get("semantic_prototypes") or {}
        self._semantic = None
        self._semantic_cache: dict = {}  # stem -> Optional[(category, cosine)] top-1

    def semantic(self):
        if self._semantic is None and HAVE_SEMANTIC and self.semantic_prototypes:
            try:
                self._semantic = SemanticMatcher(self.semantic_prototypes)
            except Exception as e:  # model files unreadable: degrade, don't 500
                sys.stderr.write(f"semantic matcher disabled: {type(e).__name__}\n")
                self._semantic = False
        return self._semantic or None

    def semantic_best(self, stem: str):
        """Cached top-1 (category, cosine) for a stem, accept gate NOT
        applied — one ONNX pass serves both the layer-6 accept decision and
        the below-gate suggestion."""
        if stem not in self._semantic_cache:
            matcher = self.semantic()
            self._semantic_cache[stem] = matcher.best(stem) if matcher else None
        return self._semantic_cache[stem]


def normalize_descriptor(descriptor: str) -> str:
    return re.sub(r"\s+", " ", descriptor.upper()).strip()


def descriptor_stem(descriptor: str) -> str:
    """Group key for uncategorized transactions and the input to the fuzzy and
    semantic layers. Reference-code tokens — store numbers, auth codes, masked
    account fragments: any token whose alphanumerics are at least half digits —
    are dropped WHOLE, not digit-stripped, so codes never shed letter shrapnel
    into the stem ("15270219Q019KM5A5" must vanish, not become "Q KM A"). The
    first three real words remain: "210001500 15270219Q019KM5A5 SUITSUPPLY
    WILMINGTON DE" stems to "SUITSUPPLY WILMINGTON DE", and
    "KWIK-E-MART #442 SPRINGFIELD" / "#187" still group together."""
    words = []
    for token in normalize_descriptor(descriptor).split(" "):
        alnum = sum(c.isalnum() for c in token)
        digits = sum(c.isdigit() for c in token)
        if alnum == 0 or digits * 2 >= alnum:
            continue
        words.append(token)
        if len(words) == 3:
            break
    stem = " ".join(words)
    return stem if stem != "" else normalize_descriptor(descriptor)


def _find_pattern(patterns: list, upper: str):
    for pattern, key in patterns:
        if pattern in upper:
            return pattern, key
    return None


def _attach(m: Matcher, key: str) -> dict:
    out = {"descriptor_key": key, "descriptor_label": m.descriptor_labels.get(key)}
    if key in m.merchant_keys:
        out["merchant_key"] = key
    if key in m.usage_labels:
        out["usage_key"] = key
    return out


def _match_descriptor(m: Matcher, upper: str, depth: int) -> dict:
    """Layers 1-2 on a descriptor string; depth guards prefix recursion."""
    hit = _find_pattern(m.descriptor_patterns, upper)
    if hit:
        pattern, key = hit
        attach = _attach(m, key)
        bridged = m.bridge.get(key)
        if bridged is not None:
            return {"category": bridged, "layer": 1, **attach}

        prefix = m.prefixes.get(key)
        if prefix is not None and depth == 0:
            # Strip the matched prefix; the real merchant follows it.
            at = upper.index(pattern)
            remainder = upper[at + len(pattern):].strip()
            if remainder != "":
                inner = _match_descriptor(m, remainder, 1)
                if inner["category"] is not None:
                    return inner
            if prefix and prefix.get("fallback_category") is not None:
                return {"category": prefix["fallback_category"], "layer": 1, **attach}
            # Unknown merchant behind the prefix: hand the STRIPPED remainder
            # to the semantic layer — "SQ *PITA GYROS" should be judged as
            # "PITA GYROS", not with the processor noise in front.
            return {"category": None, "layer": None, "_remainder": remainder}
        # Explicitly unmapped (or prefix at depth): labeled group, user's call.
        return {"category": None, "layer": None, **attach}

    kw = _find_pattern(m.keyword_patterns, upper)
    if kw:
        return {"category": kw[1], "layer": 2}
    return {"category": None, "layer": None}


def _match_fuzzy(m: Matcher, upper: str) -> Optional[dict]:
    """Layer 5: approximate match on the noise-stripped stem. Only runs when
    every exact layer missed; returns None when nothing clears the cutoff."""
    if not HAVE_FUZZ or not m.fuzzy_choices:
        return None
    stem = descriptor_stem(upper)
    if len(stem) < FUZZY_MIN_PATTERN:
        return None
    found = process.extractOne(
        stem, [c[0] for c in m.fuzzy_choices],
        scorer=fuzz.token_set_ratio, score_cutoff=FUZZY_CUTOFF)
    if found is None:
        return None
    _, score, index = found
    pattern, kind, key = m.fuzzy_choices[index]
    confidence = round(score / 100, 2)
    if kind == "descriptor":
        return {"category": m.bridge[key], "layer": 5,
                "method": "fuzzy", "confidence": confidence, **_attach(m, key)}
    return {"category": key, "layer": 5, "method": "fuzzy", "confidence": confidence}


def match_txn(m: Matcher, descriptor: str, issuer_category: Optional[str],
              mcc: Optional[int], semantic_ok: bool = True) -> dict:
    """semantic_ok=False skips layer 6 — payments/fees/transfers are excluded
    from spend by kind anyway, and embedding "ONLINE PAYMENT FROM CHK" into a
    spend category would just be noise in the per-txn data."""
    upper = normalize_descriptor(descriptor)
    direct = _match_descriptor(m, upper, 0)
    semantic_text = direct.pop("_remainder", upper)
    if direct["category"] is not None or "descriptor_key" in direct:
        direct.setdefault("method", "exact")
        return direct

    if issuer_category is not None:
        cat = m.issuer_categories.get(issuer_category)
        if cat is not None:
            return {"category": cat, "layer": 3, "method": "exact"}
    if mcc is not None:
        for r in m.mcc:
            if r["from"] <= mcc <= r["to"]:
                return {"category": r["category"], "layer": 4, "method": "exact"}

    fuzzy = _match_fuzzy(m, upper)
    if fuzzy is not None:
        return fuzzy

    # Layer 6: semantic — confident transformer matches only. The below-gate
    # top-1 still travels as a SUGGESTION (category/layer/method stay None):
    # the review UI pre-fills the group's picker with it, and it becomes real
    # spend only when the user confirms — the gate stays the sole unattended
    # categorization path.
    semantic = m.semantic_best(descriptor_stem(semantic_text)) if semantic_ok else None
    if semantic is not None:
        category, sim = semantic
        if sim >= ACCEPT_SIM:
            return {"category": category, "layer": 6,
                    "method": "semantic", "confidence": round(sim, 2)}
        return {"category": None, "layer": None, "method": None,
                "suggestion": {"category": category, "confidence": round(sim, 2)}}
    return {"category": None, "layer": None, "method": None}


def annotate(m: Matcher, txns: List) -> None:
    """Set txn.match on every transaction (single pass, categorization is
    the only per-txn state the server adds)."""
    for t in txns:
        match = match_txn(m, t.descriptor, t.issuer_category, t.mcc,
                          semantic_ok=t.kind in ("purchase", "refund"))
        # The stem travels with the match so the browser can group
        # uncategorized rows without reimplementing the stemmer.
        match["stem"] = descriptor_stem(t.descriptor)
        t.match = match
