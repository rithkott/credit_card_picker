#!/usr/bin/env python3
"""One-time exporter for the semantic matcher's transformer (plan 13).

Downloads the int8-quantized ONNX export of sentence-transformers/
all-MiniLM-L6-v2 (Apache-2.0, via Xenova/all-MiniLM-L6-v2) and copies the two
artifacts the runtime needs into server/statements/model/:

  model_quantized.onnx   ~23 MB int8 MiniLM encoder
  tokenizer.json         the HuggingFace tokenizers file, verbatim
  meta.json              provenance + the exact pooling recipe

The runtime (server/statements/semantic.py) runs it with onnxruntime and
masked mean pooling + L2 norm — the standard sentence-transformers recipe.
huggingface_hub is DEV-ONLY; the deployed function never touches the network.

Rerun only to change models; the outputs are committed.
Usage: pip install huggingface_hub && python3 scripts/export_semantic_model.py
"""

import json
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

MODEL_ID = "Xenova/all-MiniLM-L6-v2"
OUT = Path(__file__).resolve().parent.parent / "server" / "statements" / "model"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for remote, local in [("onnx/model_quantized.onnx", "model_quantized.onnx"),
                          ("tokenizer.json", "tokenizer.json")]:
        shutil.copyfile(hf_hub_download(MODEL_ID, remote), OUT / local)
    (OUT / "meta.json").write_text(json.dumps({
        "model": MODEL_ID,
        "base": "sentence-transformers/all-MiniLM-L6-v2",
        "license": "Apache-2.0",
        "quantization": "int8 (dynamic)",
        "pooling": "attention-masked mean of last_hidden_state, L2-normalized",
        "max_tokens": 64,
    }, indent=2) + "\n")

    # Sanity: the runtime encoder must produce sane similarities.
    import sys
    sys.path.insert(0, str(OUT.parent.parent))
    from statements.semantic import SemanticEncoder
    enc = SemanticEncoder(OUT)
    vecs = enc.encode(["movie theater", "cinema tickets", "gas station"])
    close = float(vecs[0] @ vecs[1])
    far = float(vecs[0] @ vecs[2])
    assert close > 0.5 > far, (close, far)
    print(f"exported {MODEL_ID} to {OUT} (theater~cinema {close:.2f}, theater~gas {far:.2f})")


if __name__ == "__main__":
    main()
