#!/usr/bin/env python3
"""One-time exporter for the semantic matcher's embedding model (plan 13).

Downloads minishlab/potion-base-8M (MIT license) via model2vec and writes the
two artifacts the runtime actually needs into server/statements/model/:

  embeddings.npy   token-embedding matrix, float16 (~15 MB; fp32 adds nothing
                   at cosine-similarity precision)
  tokenizer.json   the model's HuggingFace tokenizers file, verbatim
  meta.json        provenance + the exact encode recipe the runtime mirrors

The runtime (server/statements/semantic.py) reimplements model2vec's encode —
mean of token vectors, L2-normalized (verified identical: cosine 1.0) — so
model2vec/huggingface_hub are DEV-ONLY dependencies; the deployed function
needs just numpy + tokenizers, and never touches the network.

Rerun only to change models; the outputs are committed.
Usage: pip install model2vec && python3 scripts/export_semantic_model.py
"""

import json
from pathlib import Path

import numpy as np
from model2vec import StaticModel

MODEL_ID = "minishlab/potion-base-8M"
OUT = Path(__file__).resolve().parent.parent / "server" / "statements" / "model"


def main() -> None:
    model = StaticModel.from_pretrained(MODEL_ID)
    assert model.normalize, "runtime recipe assumes normalized embeddings"
    OUT.mkdir(parents=True, exist_ok=True)

    np.save(OUT / "embeddings.npy", model.embedding.astype(np.float16))
    (OUT / "tokenizer.json").write_text(model.tokenizer.to_str())
    (OUT / "meta.json").write_text(json.dumps({
        "model": MODEL_ID,
        "license": "MIT",
        "dim": int(model.embedding.shape[1]),
        "vocab": int(model.embedding.shape[0]),
        "dtype": "float16",
        "encode": "mean of token vectors (add_special_tokens=False), L2-normalized",
    }, indent=2) + "\n")

    # Sanity: reimplemented encode must match the library bit-for-bit in cosine.
    ids = model.tokenizer.encode("corner bar", add_special_tokens=False).ids
    manual = model.embedding[ids].mean(axis=0)
    manual = manual / np.linalg.norm(manual)
    lib = model.encode(["corner bar"])[0]
    cos = float(np.dot(manual, lib))
    assert cos > 0.9999, cos
    print(f"exported {MODEL_ID} to {OUT} (encode parity cosine {cos:.6f})")


if __name__ == "__main__":
    main()
