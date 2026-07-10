# v1.2.0 — Backend statement parsing (deterministic, no API costs)

## Context

Statement import (plan 09) parses CSV/OFX/PDF entirely in-browser (`site/src/lib/statements/`). It works against the verified 42-file corpus but has hit its ceiling: generic PDF regexes are brittle, issuer CSV profiles are unverified drafts, and robust format handling needs a semantic layer the browser can't provide. v1.2.0 moves parsing to a proper backend.

**User decisions (fixed):**
- Formats: PDF, CSV, OFX/QFX/QBO, automatic content-based detection.
- Engine: **deterministic only — no LLM, no API costs.** Semantic layer must be free and run inside the Vercel Python function.
- Privacy: **ephemeral** — parse in function memory, return results, store nothing (no DB, no blob).
- Runtime: extend existing FastAPI function (`server/app.py`, deployed via `api/index.py` shim).

This inverts the documented invariant "statement bytes never leave the tab" — all privacy copy must be rewritten honestly (CLAUDE.md, README, architecture.md, code comments, UI pill).

## Architecture decisions

**D1 — Per-file endpoint.** `POST /api/statements/parse`, multipart, one file per request → normalized transactions + file summary. Maps 1:1 to the existing per-file progress bar, no cross-request server state, per-file failure isolation. **Client file cap drops 10 MB → 4 MB** (Vercel 4.5 MB body limit minus multipart headroom); oversize files get a local error chip ("larger than 4 MB — download the CSV export instead") and never upload. Batch upload rejected (would cap the *sum* of a year of PDFs at 4.5 MB).

**D2 — Categorization moves server-side; aggregation/review stays client-side.** Port `detect/csv/ofx/pdf/kind/categorize` to Python. Keep `annualize/aggregate/applyReview/toSpendState` in TS (run per review keystroke on returned txns). The server already loads both rule YAMLs in lifespan (`server/app.py:72-76`) — matcher compiles at startup. Per-txn provenance (`layer/method/confidence`) computed once, travels with each txn. Consequence: **`statement_import` block removed from `/api/config`** — update `tests/test_server_api.py` + `site/src/types.ts` in the same change (CLAUDE.md contract rule).

**D3 — Python stack.** stdlib `csv` (issuer profiles + synonyms ported verbatim from `csv.ts`); hand-rolled `re` port of `ofx.ts` scanner; **pdfplumber** (lazy import) for PDFs — `page.extract_words()` gives `{text, x0, top}`, the direct analogue of pdf.js text items, so `reconstructLines` ports 1:1 (sort `top` ascending — pdfplumber origin is top-left vs pdf.js bottom-left). All corpus-verified regexes (`TXN_LINE`, `TXN_LINE_LONG`, `PERIOD*`, `TOTALS_PATTERNS`), sign conventions, `classifyKind` lists, and matcher order (descriptors → keywords → issuer category → MCC, longest-pattern-then-key ties) are **direct ports** — the TS engine is corpus-verified; don't redesign it.

**D4 — Free semantic layer (replaces the LLM idea):**
- **CSV column inference (zero deps).** When header mapping fails or file is headerless: score columns by content shape over ≤200 sampled rows (date-parse fraction, amount-parse fraction, descriptor = alpha length × uniqueness, debit/credit pair detection). Accept at ≥0.8 per chosen column, else keep today's header error. Provenance `summary.column_inference {used, confidence}` → file-chip note. Fixes the "issuer CSV profiles unverified" pain point.
- **PDF layout-band fallback.** Only when the regex path yields 0 txns on a text-bearing PDF: cluster word x-positions into right-aligned amount band + left date band, descriptor between. Summary-box reconciliation still applies. `summary.extraction = "regex" | "layout"`. Not pdfplumber `extract_table` (bank statements are unruled; stream mode noisy).
- **Fuzzy descriptor matching (rapidfuzz) as matcher layer 5.** After layers 1–4 miss: `token_set_ratio` on stem vs descriptor patterns + keyword stems, `score_cutoff=90`, pattern length ≥5. Fuzzy never overrides exact; fuzzy hit on explicitly-unmapped keys (venmo/bilt_rent) stays a labeled uncategorized group. Provenance `match.method="fuzzy"`, `confidence=score/100`; aggregate emits `I-fuzzy` info line ("N transactions (~$X/yr) matched approximately"). rapidfuzz ≈ 7 MB, no transitive deps.
- **No ML model** (no shippable training data — only labels are 42 private statements; cold-start tax; unexplainable misses worse than honest uncategorized rows). **No OCR** (tesseract = native binary, infeasible on Vercel Python) — keep scanned-PDF rejection: 422 `code: "scanned_pdf"`, existing "download the CSV export" copy.

## New module layout

`server/statements/` package:
- `__init__.py` — dispatch (detect → parse → classify → categorize), caps (4 MB, 200 PDF pages, 50k txns), error taxonomy
- `types.py`, `detect.py`, `kind.py`, `csv_parse.py` (avoid stdlib shadow), `columns.py` (inference), `ofx.py`, `pdf.py`, `categorize.py`
- `cli.py` — corpus harness (server-side replacement for the docs/local/09 vite-node harness)

Matcher compiled in `app.py` lifespan from the already-loaded registries.

## API contract

`POST /api/statements/parse` (multipart, field `file`) →
```json
{
  "summary": {"name", "format", "txns", "rejected_rows", "range_start", "range_end",
               "statement_totals?", "period_count?", "extraction", "column_inference?"},
  "txns": [{"date", "amount_cents", "descriptor", "kind", "mcc?", "issuer_category?", "line",
             "match": {"category", "layer", "method", "confidence",
                        "merchant_key?", "usage_key?", "descriptor_key?", "descriptor_label?"}}]
}
```
Errors: 422 `{detail, code}` with `code ∈ scanned_pdf | unrecognized_format | no_transactions | too_many_txns`; 413 `too_large`; 500 `internal` (logged **without** statement content). `dump_debug_run` never called on this route — no statement bytes or txns ever written server-side.

## Frontend changes

- `site/src/api.ts`: add `parseStatement(file)` (FormData; don't set Content-Type manually).
- `site/src/lib/statements/index.ts`: becomes sequential upload loop — keeps client-side SHA-256 dedupe (duplicates never upload), `MAX_FILES` 50, `MAX_TXNS_TOTAL` 50k, per-file `onProgress`; one retry on network/5xx only.
- **Delete** `detect.ts`, `csv.ts`, `ofx.ts`, `pdf.ts`, `kind.ts`, `categorize.ts`, their tests (`parsers.test.ts`, `pdf.test.ts`), `pdfjs-dist` dep + its `vite.config.ts` handling. Old client parsers deleted outright (dead fallback path would contradict new privacy copy; git history preserves them).
- `aggregate.ts`: consume `txn.match` from server instead of calling `matchTxn`; add `I-fuzzy` info line.
- `StatementImport.tsx`: drop `compileRules`/`terminatePdfWorker`; rewrite privacy pill — "Parsed in memory, never stored — files are discarded the moment totals come back". `FileDrop.tsx` copy → "Uploading and parsing…".
- `site/src/types.ts` + `validation.ts`: new response types, remove `statement_import` config types.

## Tests

- New `tests/test_statements.py` (unittest, matches repo runner): fixtures copied from `site/src/lib/statements/__fixtures__/`; parity assertions ported from `parsers.test.ts`/`pdf.test.ts`; new cases for column inference, fuzzy layer, layout fallback, scanned-PDF rejection.
- `tests/test_server_api.py`: multipart happy path per format, error-code contract (413/422 codes), assertion that `statement_import` is absent from `/api/config`.
- Corpus rerun: `server/statements/cli.py` against `~/Desktop/Personal` (never commit); append findings to `docs/local/09-verification-findings.md`.

## Deployment

- Root `requirements.txt` += `python-multipart` (UploadFile requirement), `rapidfuzz`, `pdfplumber` (~35 MB installed delta total; well under 250 MB function cap).
- `vercel.json` functions block: add `"memory": 1024, "maxDuration": 60` to `api/index.py`. Measure largest corpus PDF duration on preview; lower `MAX_PDF_PAGES` if needed.
- pdfplumber lazy-imported → optimizer-only cold starts unaffected. No env vars needed.

## Docs (same PR — mandatory per CLAUDE.md)

- `CLAUDE.md` deployment bullet: rewrite "Statement parsing stays 100% in-browser" → server parses ephemerally, nothing stored, debug dumps never on statement route.
- `README` Privacy section, `docs/architecture.md` (SITE/SERVER/META-RULES nodes + invariants — diagram update is required in same commit), `site/src/lib/statements/types.ts:1-7` header comment.

## Rollout

1. Worktree branch `statement-backend-v1.2` from up-to-date `main`.
2. Ordered commits: core parsers (csv/ofx/detect/kind) → pdf → categorize + semantic layer → API route + server tests → frontend swap → deploy config + docs → corpus verification notes.
3. GitNexus: run `impact` on `config`/`app.py` symbols before edits; `detect_changes()` before each commit.
4. Push branch → Vercel preview. **Preview checklist:** upload each format; oversize/scanned/duplicate error chips; inferred-columns note; fuzzy `I-fuzzy` line; `W-reconcile` still fires; full import → review → apply → optimize e2e; function duration in Vercel logs; confirm no statement content in logs.
5. User explicit approval of preview → merge to `main`, push, verify prod READY + live behavior.
6. Tag `v1.2.0` on the merge commit (minor bump — new subsystem), push tag. Remove worktree, delete branch.

## Risks

- pdfminer speed vs 60 s budget — measure on preview; page cap is the lever.
- 4 MB cap is a UX regression from 10 MB — explicit per-file messaging.
- Fuzzy false positives — cutoff 90 + guards + review-screen transparency.
- Statement text is untrusted input — only regex/fuzzy-matched, rendered as text nodes; never evaluated, logged, or persisted.
