# Plan 09 — Statement import: upload → parse → review → auto-fill (V2)

Users upload real statement exports (CSV, OFX/QFX, PDF); the site parses them
**entirely in the browser**, categorizes transactions into the 13 real spend
categories, annualizes by covered date range, and shows a review screen whose
Apply button fills the existing form state. `scripts/optimize.py` and
`parse_profile` are untouched — the importer's output is ordinary form state.

## Decisions

| Area | Decision |
|---|---|
| Privacy boundary | Statement bytes and transactions never leave the browser — not even to `localhost:8000`. Only the aggregated, user-approved profile reaches `/api/optimize` (so `server/debug-runs/` dumps never contain transactions, same as manual entry). |
| Rules source | New registry `data/meta/category-rules.yaml`: `descriptor_categories` (bridge from every `statement-descriptors.yaml` key), `aggregator_prefixes` (strip-and-rematch), `unmapped` (justified exceptions), `keywords`, `issuer_categories`, `mcc`. Served to the browser as `statement_import` on `GET /api/config`. |
| Categorization | Deterministic layered matcher, first hit wins, longest pattern wins within a layer, ties broken by descriptor key (ascending): (1) descriptor patterns → bridge (+ merchant carve-out + usage suggestion), (2) keywords, (3) issuer CSV category column, (4) MCC/OFX `<SIC>`, (5) uncategorized (grouped for review; leftovers go to `other` on Apply). No LLM, no network, no Plaid. |
| Formats | CSV (issuer header profiles: Chase, Amex, Citi, Capital One, BofA, Discover + generic header-synonym fallback), OFX/QFX (SGML + XML), PDF (pdf.js text layer + one generic date/description/amount line-reconstruction heuristic). |
| PDF engine | `pdfjs-dist` (site's third runtime dep), lazy `import()` so the main bundle is unchanged; Vite-bundled worker (no CDN); `isEvalSupported: false`; `ArrayBuffer` input only. Scanned/image-only PDFs (no text items) rejected with "download the CSV from your issuer instead". |
| Annualization | Coverage = union of per-file date intervals (OFX `DTSTART/DTEND` when present, else min..max txn date); `annualCents = round(rawCents × 365 / coveredDays)`; warn < 60 days. Payments/fees/interest/cash advances excluded by kind classification; refunds subtract in-category; per-category clamp ≥ 0 after scaling. |
| Reconciliation | Parsed totals are validated against the statement's own numbers wherever the format carries them: PDF summary lines ("Purchases", "Payments and Credits", "Fees Charged"...) are extracted and compared to the parsed purchase/credit sums; OFX ledger transaction sets are checked for `FITID` duplicates; per-file rejected-row counts always surface. Mismatches are review-screen warnings, never silent. |
| Dedup | SHA-256 of file bytes (same file twice → skipped with notice) + OFX `FITID` dedup within a file; overlapping date ranges across files → warning only. |
| Apply semantics | Overwrite: Apply replaces `categoryCents`/`merchantCents` with detected annualized values; detected usage keys are unioned into `confirmed_usage`. Confirm note shown when the form is non-empty; everything stays editable afterwards. |
| Review state | Entirely local to the new `<StatementImport>` component; `App.tsx` gains one `onApply` callback and nothing else. Nothing persists (no localStorage/IndexedDB). |

## Rejected alternatives

- **`category:` field on `statement-descriptors.yaml` entries** — that file's keys are the benefit vocabulary (usage-questions items must be a subset); aggregators like `paypal` have no single category. A separate bridge keeps "what unlocks a benefit" and "what fills a spend bucket" independent.
- **Separate `/api/import-rules` endpoint** — `/api/config` is already "everything the form needs in one call"; a second endpoint is a second contract to test.
- **Papa Parse / an OFX npm dep** — the formats are simple enough for small hand-rolled parsers; keeps runtime deps at react + react-dom + pdfjs-dist with every branch under our own tests.
- **Per-issuer PDF line profiles** — unverifiable maintenance burden; a generic date/description/amount reconstruction plus the reconciliation check covers it, and CSV/OFX are the recommended paths (the UI says so).
- **Backend parsing endpoint** — would add an upload path and file-parsing attack surface to the server for no capability gain; pdf.js makes text-layer PDFs feasible client-side.
- **Merging Apply into existing form values** — ambiguous (double-count vs keep-max); overwrite + editable fields is predictable.

## Pipeline

```
File[] ─detect→ per-format parse ─→ NormalizedTxn[]  (kind: purchase/refund/payment/fee/interest/transfer)
       └ sha-256 file dedupe, size/row limits
NormalizedTxn[] ─categorize→ category + merchantKey? + usageKey? per txn
                ─aggregate→ raw cents per category/merchant + uncategorized groups
                ─annualize→ ×(365 / covered days), clamp ≥ 0
                ─reconcile→ warnings (statement totals vs parsed sums)
                ─→ ImportResult ─ review screen ─ Apply → setSpend / setUser
```

Merchant carve-out transactions also count in their parent category, so
carve-out ≤ parent before scaling; `Math.round` is monotonic, so validation E3
(carve-outs ≤ parent) can never fire from imported values.

## Module layout — `site/src/lib/statements/`

| File | Responsibility |
|---|---|
| `types.ts` | `NormalizedTxn`, `TxnKind`, `ImportResult`, warning/error types |
| `detect.ts` | format sniffing: `%PDF-` magic / `OFXHEADER`·`<OFX>` / CSV header row |
| `csv.ts` | RFC-4180 state machine + issuer header profiles + generic fallback |
| `ofx.ts` | tolerant SGML/XML `<STMTTRN>` scanner, `FITID` dedupe, `DTSTART/DTEND` |
| `pdf.ts` | lazy pdf.js text extraction → line reconstruction → txn regexes + summary-total extraction; `ScannedPdfError` |
| `categorize.ts` | `compileRules()` once per config; `matchTxn()` pure layered matcher |
| `annualize.ts` | interval merge, scaling, `classifyKind()` |
| `aggregate.ts` | orchestration + `reassign()` + `toSpendState()` + reconciliation warnings |
| `index.ts` | `parseStatementFiles()` — limits, dedupe, dispatch, per-file errors |
| `__fixtures__/` | **synthetic fixtures only — never commit a real statement export, even redacted** |

## Review UI — `site/src/components/import/`

`<StatementImport>` above `<SpendEntry>` in App's ready block. Sub-components:
`FileDrop` (multi-file + drag-drop + privacy line), `ImportReview` (coverage
banner, category table with contributing descriptors and exclude toggles,
carve-outs nested under parents, excluded-money footnote, reconciliation
warnings), `UncategorizedList` (grouped stems, reassign via category select;
explicitly-unmapped descriptor groups like Bilt rent appear labeled),
`UsageSuggestions` (pre-checked "detected $N/yr at X" rows for usage-question
items). Privacy copy: *"Your statements are read entirely in your browser.
They are never uploaded — not to this site, not to the local optimizer. Only
the category totals you approve go into the form."*

## Security

- Limits: 10 MB/file, 20 files/batch, 50k transactions, 200 PDF pages; exceeding is a per-file error, batch continues.
- pdf.js: `isEvalSupported: false`, `ArrayBuffer` only, self-hosted bundled worker, worker terminated after each batch, per-file try/catch.
- No persistence: raw bytes and transactions are memory-only, dropped on Apply/cancel.
- CSP meta in `site/index.html`: `default-src 'self'; script-src 'self'; worker-src 'self' blob:; connect-src 'self' http://localhost:8000; img-src 'self' data:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'`.
- CSV formula injection is moot (nothing is exported; descriptors render as React text nodes) — documented, no sanitization theater.

## Testing

- Vitest on synthetic fixtures: format-detection matrix, per-issuer CSV goldens, OFX SGML/XML equivalence + FITID dedupe, PDF line-reconstruction goldens + summary reconciliation, layered-categorization goldens (incl. aggregator strip-and-rematch), annualization edges (single-day, overlap merge, refund>purchase clamp, sign-flip detection, <60-day warning), E3-invariant property, `toSpendState` output passes `validate()` clean.
- Python: validator checks exercised by `python3 scripts/validate_cards.py`; `tests/test_server_api.py` pins the `statement_import` config mirror.
- Real-statement verification (never committed): the local parsers are run against the maintainer's own statement exports via a scratch harness, results compared against an independent manual/AI parse of the same files, and divergences fixed before ship.

## Governance sync surfaces (per CLAUDE.md)

`docs/architecture.md` (new registry + validator checks + config payload) ·
`tests/test_server_api.py` · `site/src/types.ts` — all updated with commit 1.
`tools/card-entry-form.html` unaffected (embeds card-schema vocabulary only;
category-rules is not card-file vocabulary).

## Commit breakdown

1. Registry + contract: `category-rules.yaml`, validator checks, `/api/config` `statement_import`, `tests/test_server_api.py`, `types.ts`, `architecture.md`, this doc.
2. Text parsers: `detect/csv/ofx/types/index` + fixtures + tests.
3. PDF: `pdfjs-dist`, `pdf.ts`, fixtures + tests, bundle-size check.
4. Brain: `categorize/annualize/aggregate` + golden tests.
5. UI: import components, `App.tsx` wiring, CSP, privacy copy, architecture site-node update.

## Verification (manual end-to-end checklist)

1. `python3 server/app.py` + `npm run dev`; upload one statement of each format, then a mixed multi-month batch.
2. Scanned/image PDF → rejection message pointing at CSV export.
3. Reassign an uncategorized stem; totals update live. Exclude a category.
4. Apply → form filled, validation panel clean, usage chips checked, optimizer runs.
5. Network tab shows zero requests while parsing.
6. Reconciliation warning appears when a PDF's summary totals disagree with parsed sums (synthetic tamper test).
7. `npm run build -- --base=/credit_card_picker/` and verify the importer works under the Pages base path (worker loads, pdf.js lazy chunk loads).

## Deferred

Interactive CSV column-mapper for unknown headers · per-issuer PDF profiles ·
cross-file transaction dedup beyond FITID/file-hash · OCR for scanned PDFs ·
persisting import summaries · verifying descriptor patterns against real
exports at registry level (stays confidence: low) · MCC table expansion.
