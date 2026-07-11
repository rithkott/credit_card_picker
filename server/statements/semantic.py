"""Semantic descriptor matching — matcher layer 6 (plan 13, v1.2.1).

A LOCAL static embedding model (minishlab/potion-base-8M, exported to
server/statements/model/ by scripts/export_semantic_model.py) semantically
matches descriptor stems the exact and fuzzy layers missed: "JOES DELI",
"CORNER BAR", "AMC THEATRES" are obvious to an embedding space and shouldn't
land on the user's review pile. No network, no API, no cost — the model is a
14 MB numpy matrix; encode = mean of token vectors, L2-normalized (verified
identical to model2vec's output).

Each real category declares short prototype phrases in
data/meta/category-rules.yaml (semantic_prototypes); a stem matches the
category of its most-similar prototype, and is accepted only when BOTH
  cosine >= ACCEPT_SIM          (absolute floor: garbage stays unmatched)
  best - runner_up >= ACCEPT_MARGIN  (margin over the best OTHER category:
                                      genuinely ambiguous merchants — a wine
                                      shop vs a wine bar — go to the user;
                                      0.12 calibrated so "TOTAL WINE" stays
                                      ambiguous while "CORNER BAR" passes)
hold. Accepted matches carry method="semantic" + confidence so the review UI
discloses them; everything else stays uncategorized exactly as before — the
user is only asked about what the model can't confidently place.

Deterministic: fixed matrix, fixed prototypes, argmax with stable tie-break
by prototype order. Degrades to layers 1-5 when numpy/tokenizers or the
model files are absent (import guarded by categorize.py).
"""

import json
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from tokenizers import Tokenizer

MODEL_DIR = Path(__file__).resolve().parent / "model"

ACCEPT_SIM = 0.35
ACCEPT_MARGIN = 0.12
MIN_STEM_CHARS = 4  # "SQ" or "#42" can't carry meaning


class SemanticEncoder:
    """Loads the exported matrix + tokenizer once; encodes short strings."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.embedding = np.load(model_dir / "embeddings.npy").astype(np.float32)
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.meta = json.loads((model_dir / "meta.json").read_text())

    def encode(self, texts: List[str]) -> np.ndarray:
        """Mean of token vectors, L2-normalized — model2vec's exact recipe.
        Unknown/empty inputs yield a zero vector (cosine 0 with everything)."""
        out = np.zeros((len(texts), self.embedding.shape[1]), dtype=np.float32)
        for i, text in enumerate(texts):
            ids = self.tokenizer.encode(text, add_special_tokens=False).ids
            if not ids:
                continue
            v = self.embedding[ids].mean(axis=0)
            norm = float(np.linalg.norm(v))
            if norm > 0:
                out[i] = v / norm
        return out


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
        below the floor or inside the ambiguity margin."""
        if len(stem.strip()) < MIN_STEM_CHARS:
            return None
        vec = self.encoder.encode([stem.lower()])[0]
        sims = self.proto @ vec
        best = int(np.argmax(sims))  # ties: first prototype in registry order
        best_sim = float(sims[best])
        if best_sim < ACCEPT_SIM:
            return None
        category = self.owners[best]
        runner_up = max((float(s) for s, o in zip(sims, self.owners) if o != category),
                        default=0.0)
        if best_sim - runner_up < ACCEPT_MARGIN:
            return None  # genuinely ambiguous: the user decides
        return category, best_sim
