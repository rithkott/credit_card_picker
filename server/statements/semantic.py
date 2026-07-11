"""Semantic descriptor matching — matcher layer 6 (plan 13, v1.2.1).

A LOCAL transformer (all-MiniLM-L6-v2, int8 ONNX, committed at
server/statements/model/) semantically matches descriptor stems the exact and
fuzzy layers missed: "JOES DELI", "CORNER BAR", "AMC THEATRES" are obvious to
a sentence encoder and shouldn't land on the user's review pile. No network,
no API, no cost — onnxruntime runs the 23 MB model in-process, lazy-loaded.

Each real category declares short archetype phrases in
data/meta/category-rules.yaml (semantic_prototypes — generic merchant
archetypes like "deli sandwiches" or "movie theater", NOT tuned to any
particular user's statements); a stem matches the category of its
most-similar phrase and is accepted at a single confidence gate:

  cosine >= ACCEPT_SIM

That's it — we trust the model's confidence and leave corrections to the
consumer: accepted matches carry method="semantic" + the score so the review
UI disclosed them (I-semantic line), every placement is visible and editable
there, and everything below the gate stays in the uncategorized list where
the user is asked. Only purchases/refunds are eligible (a "$2,000 ONLINE
PAYMENT" must never be semantically binned — that is kind classification's
job, not a tuning choice).

Deterministic: fixed int8 weights, single-threaded onnxruntime session,
argmax with stable tie-break by prototype order. Degrades to layers 1-5 when
onnxruntime/numpy/tokenizers or the model files are absent (import guarded
by categorize.py).
"""

import json
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = Path(__file__).resolve().parent / "model"

ACCEPT_SIM = 0.40
MIN_STEM_CHARS = 4  # "SQ" or "#42" can't carry meaning
MAX_TOKENS = 64


class SemanticEncoder:
    """Lazy MiniLM ONNX session; masked-mean-pooled, L2-normalized vectors."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        options = ort.SessionOptions()
        # Single-threaded on purpose: reproducible sums, and the inputs are
        # a handful of short strings — parallelism buys nothing here.
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_dir / "model_quantized.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.meta = json.loads((model_dir / "meta.json").read_text())

    def encode(self, texts: List[str]) -> np.ndarray:
        encs = [self.tokenizer.encode(t) for t in texts]
        maxlen = max(len(e.ids) for e in encs)
        ids = np.array([e.ids + [0] * (maxlen - len(e.ids)) for e in encs],
                       dtype=np.int64)
        mask = np.array([e.attention_mask + [0] * (maxlen - len(e.attention_mask))
                         for e in encs], dtype=np.int64)
        hidden = self.session.run(None, {
            "input_ids": ids, "attention_mask": mask,
            "token_type_ids": np.zeros_like(ids)})[0]
        m = mask[:, :, None].astype(np.float32)
        emb = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1e-9)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        return emb / np.maximum(norms, 1e-9)


class SemanticMatcher:
    """Prototype-phrase index over the real spend categories."""

    def __init__(self, prototypes: dict, encoder: Optional[SemanticEncoder] = None):
        """prototypes: {category: [short phrase, ...]} — the
        semantic_prototypes block of category-rules.yaml, verbatim."""
        self.encoder = encoder or SemanticEncoder()
        self.owners: List[str] = []
        texts: List[str] = []
        for category, phrases in prototypes.items():
            for phrase in phrases:
                self.owners.append(category)
                texts.append(phrase)
        self.proto = self.encoder.encode(texts)

    def match(self, stem: str) -> Optional[Tuple[str, float]]:
        """Best (category, confidence) for a descriptor stem, or None when
        the model isn't confident enough — those go to the user."""
        if len(stem.strip()) < MIN_STEM_CHARS:
            return None
        vec = self.encoder.encode([stem.lower()])[0]
        sims = self.proto @ vec
        best = int(np.argmax(sims))  # ties: first prototype in registry order
        best_sim = float(sims[best])
        if best_sim < ACCEPT_SIM:
            return None
        return self.owners[best], best_sim
