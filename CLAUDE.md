# credit_card_picker — instructions for Claude

Deterministic credit-card portfolio optimizer built on a hand-curated YAML dataset. Read `docs/research.md` for product direction and `docs/curation-guide.md` before touching card data.

## Workflow: branching, releases, deployment (required)

All work follows this process — no direct commits to `main`.

**Branching**
- Every change is developed on a git worktree (`git worktree add .claude/worktrees/<branch> -b <branch> main`), branched from up-to-date `main`.
- `main` is the only long-lived branch. It is the branch Vercel deploys to production (https://creditcardpicker.vercel.app). Never push work-in-progress directly to `main`.
- No dedicated dev/preview branch: Vercel's git integration builds a preview deployment for every pushed non-`main` branch — that preview URL is the staging environment.

**Preview → production**
1. Develop and commit on the worktree branch; push it to `origin`.
2. Vercel auto-builds a preview deployment for the branch. Test the change on that preview URL (not just locally).
3. Only after the user's **explicit approval** of the tested preview: merge the branch to `main` and push. The `main` push is the production deploy — verify it goes READY and the live site reflects the change.
4. Remove the worktree and delete the merged branch.

**Versioning** (semver, tracked as git tags `vX.Y.Z` on `main`)
- Small edits (bug fixes, copy, styling, minor tweaks): bump the **patch** number (v1.1.3 → v1.1.4).
- Large overhauls (new subsystems, reworked optimizer/UI, breaking data-model changes): bump the **minor** number (v1.1.3 → v1.2.0).
- Tag the merge commit on `main` after the production deploy is verified, and push the tag.

## Architecture diagram maintenance (required)

`docs/architecture.md` contains a Mermaid diagram of the whole system — data infrastructure, schema, optimizer, web UI, and Vercel deployment — annotated with why each piece exists. **Any change to the architecture must update this diagram in the same commit/PR.** That means edits to any of:

- `data/schema/card.schema.json` (fields added/removed/changed — the diagram explains every block)
- `data/meta/` registries (new registry files, or structural changes to existing ones)
- `scripts/validate_cards.py` (new checks, or changes to what's an error vs a warning)
- `scripts/optimize.py` (policy constants, value model, filters, or output-contract changes — golden tests in `tests/test_optimizer.py` must be updated in the same change)
- `.github/workflows/validate-data.yml` (triggers, cadence)
- the repo's data layout (`data/`, `scripts/` structure)

The diagram documents **only what is built** — never add planned/future components to it. When new architecture ships (optimizer, UI, build pipeline), extend the diagram then.

## Project conventions

- The dataset is hand-curated and verified — never scrape or generate card data on the fly, and never add affiliate/monetization features (see `docs/research.md` for why).
- New/edited card files must pass `python3 scripts/validate_cards.py` (needs `pyyaml` + `jsonschema`).
- Card data drafted without checking issuer sources must be marked `confidence: low` with a "NEEDS human verification" marker in `verified_by`.
- When converting a `data/offer_files/<issuer>/<slug>.txt` terms sheet into `data/cards/<issuer>/<card-id>.yaml`, follow `docs/ai-conversion-protocol.md` exactly — it is a mandatory, stricter checklist layered on top of `docs/curation-guide.md` for this specific AI task.
- Cross-card assumptions (categories, merchants, point valuations) live only in `data/meta/` registries, referenced by key — never inline them in card files.
- `tools/card-entry-form.html` embeds copies of the `data/meta/` registry keys and mirrors the schema and validator checks — when the schema, registries, or validator change, update the form's embedded lists and emitted YAML in the same change.
- `server/app.py` wraps `scripts/optimize.py` in-process — any change to `parse_profile`'s contract, `run()`'s output bundle shape, any `/api/*` response shape (`/api/config`, `/api/cards`, `/api/assumptions`), or the `TIER_ORDER` / `USER_DEFAULTS` / `REWARD_KINDS` constants must update `tests/test_server_api.py` + `site/src/types.ts` (+ `site/src/lib/validation.ts` when validation rules are affected) in the same change. The web frontend embeds no registry copies (the API is its source); the embedded-lists rule above stays scoped to `tools/card-entry-form.html`.
- Deployment is Vercel: the static `site/dist` build plus `server/app.py` running as one Python function via the `api/index.py` shim, configured entirely in `vercel.json` (root `requirements.txt` = the function's deps). Keep `api/index.py` a pure import shim — deployment must never fork the API's behavior from local mode. Statement parsing stays 100% in-browser; only aggregated category totals may ever travel to the API.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **credit_card_picker** (1203 symbols, 2457 relationships, 73 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/credit_card_picker/context` | Codebase overview, check index freshness |
| `gitnexus://repo/credit_card_picker/clusters` | All functional areas |
| `gitnexus://repo/credit_card_picker/processes` | All execution flows |
| `gitnexus://repo/credit_card_picker/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
