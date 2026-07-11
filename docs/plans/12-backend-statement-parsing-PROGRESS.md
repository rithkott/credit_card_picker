# v1.2.0 backend statement parsing — execution progress

Tracks step-by-step progress so a partial session can resume. Full design: `12-backend-statement-parsing.md`.
Branch: `statement-backend-v1.2` (worktree `.claude/worktrees/statement-backend-v1.2`). Push after every commit.

## Steps

- [x] 1. Core parsers ported to `server/statements/`: types.py, detect.py, kind.py, csv_parse.py, ofx.py (+ columns.py inference) — direct ports of site/src/lib/statements TS. Smoke-tested against all 10 text fixtures + 3 synthetic inference cases (headerless, unknown headers, debit/credit pair).
- [x] 2. pdf.py (pdfplumber, regex path + layout-band fallback). Verified: statement.pdf fixture (7 txns, year rollback, summary-box totals), scanned.pdf rejection, synthetic balance-column layout fallback.
- [x] 3. categorize.py (4 registry layers + rapidfuzz layer 5) compiled from lifespan registries
- [x] 4. API route POST /api/statements/parse (sync, ephemeral, no debug dumps, {detail,code} errors, 413 too_large) + matcher compiled in lifespan + statement_import REMOVED from /api/config + deps added to both requirements files + tests/test_statements.py (44 tests, fixtures copied to tests/fixtures/statements/) + test_server_api.py upload/error/no-dump tests. Full suite: 162 tests OK.
- [x] 5. Frontend swap: upload loop in index.ts (4MB pre-check, dedupe before upload, one retry on 5xx/network, fromWire converter), deleted detect/csv/ofx/pdf/kind/categorize.ts + their tests + __fixtures__ + pdfjs-dist + vite test alias, aggregate consumes txn.match + I-fuzzy/I-inferred-columns/I-layout disclosures, types.ts wire shapes, api.ts parseStatement + ApiError.code, StatementImport/FileDrop privacy+progress copy, site/src/types.ts statement_import removed, engine.test.ts rewritten (matches inline), matcher golden table ported to Python (46 py tests). Verified: 164 unittest OK, 35 vitest OK, build OK, live curl upload OK.
- [x] 6. Deploy config (vercel.json memory:1024/maxDuration:60; requirements done in step 4) + docs (CLAUDE.md ephemeral-parsing rule replaces in-browser rule, README Privacy rewritten, architecture.md intro/DESC/RULES/SITE/SERVER/VERCEL nodes + invariant 12)
- [x] 7. Corpus rerun via server/statements/cli.py: 43 files parse, 29/29 printed totals reconcile, 0 mismatch. Found+fixed bug #7 (Bilt summary-box 'Credit limit $10,000.00' phantom purchase -> FURNITURE_DESCRIPTORS filter + regression test). Findings appended to docs/local/09 (main checkout, gitignored). Branch pushed; Vercel preview builds per push. REMAINING: test preview URL checklist (upload each format, error chips, I-* lines, e2e optimize).
- [ ] 8. After user preview approval: merge to main, verify prod, tag v1.2.0. Also: rerun GitNexus analyze after merge.

## Resume notes

- 2026-07-10: Steps 1-7 complete, all pushed. Preview verified via Vercel share link
  (branch alias creditcardpicker-git-statement-backend-v12-rithkotts-projects.vercel.app):
  /api/health OK (114 cards), statement_import absent from /api/config, CSV/OFX/PDF
  uploads parse + categorize correctly, scanned-PDF and junk uploads return coded 422s,
  PDF round trip < 0.5 s, POST /api/optimize e2e OK. Local: 165 unittest + 35 vitest
  green, site builds, real corpus 43 files / 29 totals reconcile / 0 mismatch.
- AWAITING: user approval of preview -> then merge to main, verify prod READY,
  tag v1.2.0, remove worktree, rerun `node .gitnexus/run.cjs analyze` (index stale
  since 969b451).
