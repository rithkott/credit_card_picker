# Plan 14 — Gut statement parsing to a benefit-usage detector (v1.4.0)

**Status: shipped (v1.4.0).**

## Why

The plan 12/13 statement importer tried to categorize *all* spending from
statement exports: a 6-layer matcher (descriptor patterns → keyword stems →
issuer category column → MCC ranges → rapidfuzz → a local MiniLM ONNX
transformer) feeding a review screen that filled the spend form. Verdict after
shipping it: without a paid LLM API the categorization is not good enough to
trust, and a paid API is off the table (cost + the no-external-AI privacy
stance). Users can state their own spending — their card portal already shows
it — so the machinery to guess it was carrying its weight in complexity and
183 MB of deploy budget without earning it.

What statements ARE uniquely good for is cheaper than categorization:
spotting the benefit-relevant services someone already pays for. "You spent
$412 at Delta last year" is a descriptor keyword hit, not an ML problem.

## Decision

- **Spending is always entered manually** (the existing `SpendEntry` form).
  Statement upload never touches spend state.
- **Statement upload survives only as a benefit-usage detector**: transactions
  are matched against `data/meta/statement-descriptors.yaml`
  `statement_patterns` (the old layer 1) and a hit counts only when the
  descriptor key is a usage-questions item. Detected services render as the
  existing pre-checked suggestion chips; confirming merges the keys into
  `user.confirmed_usage`.
- Keep all three formats (CSV / OFX-QFX / PDF) — the parsers are
  corpus-verified and unchanged. Keep the annualized amount on each chip
  ("Delta — $412/yr"), so `annualize.ts` and the coverage-union math stay.

## What was deleted

- `server/statements/semantic.py` + `server/statements/model/` (23 MB MiniLM
  int8 ONNX + tokenizer) and the deps `onnxruntime`, `numpy`, `tokenizers`,
  `rapidfuzz` (both requirements files — roughly 120 MB off the Vercel
  function).
- `server/statements/categorize.py` (6-layer matcher) → replaced by
  `server/statements/detect_usage.py` (descriptor-patterns-only; ~90 lines).
- `data/meta/category-rules.yaml` entirely — the descriptor→category bridge,
  keyword stems, issuer_categories, MCC ranges, and semantic_prototypes were
  all categorization-only. The one live concept, aggregator-prefix stripping,
  moved into `statement-descriptors.yaml` as `aggregator_prefix: true` on
  `paypal` / `square_prefix` / `toast_prefix` / `apple_pay_prefix`.
- The review screen: `ImportReview.tsx`, `UncategorizedList.tsx`, and the
  aggregate machinery behind them (materiality gate, misc cap, `applyReview`,
  `toSpendState`, reconcile warnings, excluded-kind tallies).
- `Txn.match` — transactions no longer carry per-txn categorization.

## New API contract

`POST /api/statements/parse` → 200:

```json
{
  "summary": {
    "name": "chase-2025-03.csv", "format": "csv", "txns": 214,
    "rejected_rows": 1, "range_start": "2025-01-01", "range_end": "2025-03-31",
    "statement_totals": {"purchases_cents": 123456},
    "period_count": 1, "extraction": "regex",
    "column_inference": {"used": true, "confidence": 0.8}
  },
  "matches": [
    {
      "date": "2025-01-14", "amount_cents": 41250,
      "descriptor": "DELTA AIR 0062341983477 ATLANTA",
      "kind": "purchase", "line": 12,
      "usage_key": "delta", "usage_label": "Delta"
    }
  ]
}
```

- `matches` holds ONLY purchase/refund transactions whose descriptor resolves
  to a usage-questions item — **unmatched transactions never leave the
  server** (a deliberate privacy improvement over returning the full list).
- Optional summary fields as before; error taxonomy (`{detail, code}`,
  413/422/500) and the ephemeral policy are unchanged.
- The client's 50k-transaction session cap now counts `summary.txns`.

## Matching rules (server/statements/detect_usage.py)

Case-insensitive substring over the whitespace-normalized descriptor; longest
pattern first, identical patterns tie-break by ascending key (deterministic).
`aggregator_prefix: true` entries strip the matched prefix and re-match the
remainder once; an unrecognized remainder is no match. A hit on a non-usage
descriptor key (issuer portals, detection helpers) is skipped and scanning
continues, so a usage merchant elsewhere in the descriptor still matches.
Only purchases and refunds are examined; refunds subtract client-side and
suggestions net ≤ 0 are dropped.

## Frontend

`StatementImport.tsx` phases: `idle | parsing | detected | applied`. The
detected screen = file/duplicate/error chips + coverage line + parse-path
warnings (coverage, overlap, rejected rows, multi-statement, inferred
columns, layout fallback) + the `UsageSuggestions` chips + a
"Confirm checked services" button whose `onApply(usageKeys)` merges into
`confirmed_usage` in `Home.tsx`. `aggregate.ts` shrank to: sum matches per
usage key, annualize over merged coverage, emit warnings.

## Pinned by

`tests/test_statements.py` (format suites unchanged; `TestDetectUsageReal` +
`TestDetectUsageGolden` replace the categorizer/semantic suites),
`tests/test_server_api.py` (the `{summary, matches}` contract, an
unmatched-transactions-never-returned test, the no-debug-dumps test), and
`site/src/lib/statements/engine.test.ts` / `session.test.ts`.
