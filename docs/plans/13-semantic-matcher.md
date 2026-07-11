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

## v1.2.1 second iteration (same branch) — user feedback round 2

Asks: place the still-obvious ones (Uniqlo, TJ Maxx, Häagen-Dazs, pita gyros,
concessions, cookies, convenience, deli, pasta); try a bigger/newer
transformer; never bother users with sub-1% charges; NO hand-added merchant
keywords (registry must work for average users, not be tuned to one person's
statements).

Measured constraints (pip wheels for manylinux/py312, unzipped): runtime deps
alone = 183 MB (numpy 57 + onnxruntime 53 + pdf stack 43 + rest), so model
budget ≈ 45 MB. Bake-offs run: bge-base-en-v1.5 int8 (110 MB — best quality,
DOESN'T FIT: 331 MB total), nli-deberta-v3-xsmall zero-shot (87 MB, fits
alone but 12/22 — flat probabilities), bge-small/gte-small/arctic-xs (fit,
worse separation than MiniLM), MiniLM⊕bge-small union (255 MB — over, and
adds garbage placements). **Verdict: keep MiniLM** — best
precision/separability within the physical budget.

What actually closed the gap, no merchant keywords added:
1. **Prefix-remainder fix**: semantic layer now judges the aggregator-prefix
   remainder ("SQ *PITA GYROS" → "PITA GYROS" → dining 0.79, was noise).
2. **Archetype descriptions** (category meanings, not merchant names): ice
   cream parlor, gyro and pita shop, cookie bakery, stadium concession stand,
   gourmet deli, pasta shop, juice bar, convenience store bodega, clothing
   brand store, discount department store.
3. **Registry correction**: 20 pre-existing retail-chain keywords (TJ MAXX,
   HOME DEPOT, MACY'S, IKEA, …) moved from 'other' to online_shopping — its
   label is literally "Shopping (online & in-store retail)". Only
   USPS/FedEx/UPS remain in 'other'.
4. **Materiality gate** (`MATERIALITY_PCT = 0.01`, site aggregate.ts): an
   unlabeled unknown worth <1% of total annualized spend is never asked — the
   review shows one summary line and it folds into 'Everything else' on Apply
   (existing mechanics). Labeled policy groups (rent, Venmo) always ask.

Corpus effect (real statements): semantic placements 91 → 112 txns; of 78
unknown merchant groups the user is asked about **7 — all rent variants**;
the other 71 (each < $1,260/yr on a $126k profile) fold silently. Brands the
model can't know without shipping a bigger encoder (Häagen-Dazs, Uniqlo
without its keyword) simply fold when small instead of interrupting.
