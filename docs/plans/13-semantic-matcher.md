# Plan 13 — Semantic matcher layer 6 (v1.2.1)

## Context

After v1.2.0, too many transactions land in "Not recognized": obvious merchants
("JOES DELI", "CORNER BAR", "AMC THEATRES", anything with wines/sports in the
name) that no hand-written pattern covers. User decision: add a **local**
transformer-style model to semantically place them, asking the user only about
low-confidence ones. Constraints carry over from plan 12: no API costs, no
network, deterministic, ephemeral.

## Design

- **Model**: minishlab/potion-base-8M (MIT) — a static model2vec embedding
  model. Exported once by `scripts/export_semantic_model.py` to
  `server/statements/model/` (14 MB float16 matrix + tokenizer.json, committed).
  Runtime reimplements the encode (mean of token vectors, L2-normalized —
  parity cosine 1.0), so deployed deps are just **numpy + tokenizers**; model2vec
  and huggingface are dev-only. No onnxruntime, no cold-start tax (lazy load).
- **Prototypes**: `semantic_prototypes` block in `data/meta/category-rules.yaml` —
  short per-category merchant archetypes ("deli sandwiches", "movie theater",
  "liquor store"). Matcher takes the max cosine over phrases per category.
  Validator enforces: real non-pseudo categories, never `other`, non-blank.
- **Acceptance gates** (`server/statements/semantic.py`): similarity ≥ 0.35
  AND margin ≥ 0.12 over the best *other* category. Calibrated so
  "TOTAL WINE" (wine shop vs wine bar) and "BODEGA WINES" stay with the user
  while "CORNER BAR" (0.52) and "KATZS DELICATESSEN" (0.76) resolve.
- **Wiring**: layer 6 in `categorize.match_txn`, strictly after layers 1–5;
  never overrides exact/fuzzy; **purchases/refunds only** (a "$2,000 ONLINE
  PAYMENT" must never be semantically binned); per-stem result cache.
  `method="semantic"`, `confidence=cosine` in the txn match.
- **Disclosure**: review UI shows an `I-semantic` info line (count + $ placed
  by meaning); low-confidence stems stay in the existing uncategorized list —
  the user is only asked about what the model can't confidently place.

## Corpus results (real statements, 2026-07-10)

Uncategorized purchase/refund txns 416 → 311 (−25%); 99 txns across 27 stems
placed semantically, eyeballed correct (delis, markets, transit fare, climbing
gym, Japanese railway, airline, liquor, pizzerias). Fixes from calibration:
payment rows gated out; "ev charging" prototype reworded to stop
"PICKLE * EVT" → gas.

## Function size

Model +14 MB, numpy+tokenizers ≈ +55 MB installed — comfortably under the
250 MB function limit alongside plan-12 deps.
