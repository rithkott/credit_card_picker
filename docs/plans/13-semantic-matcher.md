# Plan 13 — Semantic matcher layer 6 (v1.2.1)

## Context

After v1.2.0, too many transactions land in "Not recognized": obvious merchants
("JOES DELI", "CORNER BAR", "AMC THEATRES", anything with wines/sports in the
name) that no hand-written pattern covers. User decisions: add a **local
transformer** to semantically place them, asking the user only about
low-confidence ones; **don't overengineer** — prefer a bigger model with one
trusted confidence gate over threshold/margin tuning against a small,
unrepresentative sample. Plan-12 constraints carry over: no API costs, no
network, deterministic, ephemeral.

## Design

- **Model**: sentence-transformers/all-MiniLM-L6-v2, int8 ONNX export
  (Apache-2.0, via Xenova) — a real 6-layer transformer encoder, 23 MB,
  committed at `server/statements/model/` by `scripts/export_semantic_model.py`.
  Run by onnxruntime (single-threaded for reproducibility), lazy-loaded so
  optimizer-only cold starts pay nothing. Deployed deps: numpy + tokenizers +
  onnxruntime (~130 MB total function, limit 250 MB). huggingface_hub is
  dev-only; the function never touches the network.
  (A static-embedding candidate, potion-base-8M, was tried first: smaller but
  needed margin heuristics to stay accurate — rejected as overengineering.)
- **Targets**: `semantic_prototypes` block in `data/meta/category-rules.yaml` —
  short GENERIC merchant archetypes per category ("deli sandwiches",
  "movie theater", "liquor store"), max cosine over phrases per category.
  Explicitly never tuned to any particular user's statements. Raw category
  labels alone were tested and are too abstract (8/15 vs 16/20 top-1).
  Validator enforces: real non-pseudo categories, never `other`, non-blank.
- **One gate** (`server/statements/semantic.py`): cosine ≥ 0.40. The model's
  call is trusted — no margin logic, no second-guessing. Below the gate the
  stem stays in the uncategorized review list where the user is asked; above
  it the placement is still fully visible and editable on the review screen,
  disclosed by the `I-semantic` info line and per-txn `method="semantic"` +
  `confidence`.
- **Wiring**: layer 6 in `categorize.match_txn`, strictly after layers 1–5;
  never overrides exact/fuzzy; **purchases/refunds only** (payments/fees/
  transfers are excluded by kind classification, not semantics); per-stem
  result cache per matcher.

## Corpus results (real statements, 2026-07-10)

91 txns across 35 stems placed at the 0.40 gate (climbing gym, delis, markets,
transit fare, Japanese railway, airline, liquor, pizzerias, AMC). 183 txns
stay for the user — rent variants, laundry-machine kiosks, and genuinely
opaque names. Full pipeline (30 files) stays fast; the encoder only runs on
stems every other layer missed.

## Function size

Model 23 MB + onnxruntime 53 MB + numpy/tokenizers ≈ 130 MB installed —
comfortably under the 250 MB function limit alongside plan-12 deps.
