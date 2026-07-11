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
- Deployment is Vercel: the static `site/dist` build plus `server/app.py` running as one Python function via the `api/index.py` shim, configured entirely in `vercel.json` (root `requirements.txt` = the function's deps). Keep `api/index.py` a pure import shim — deployment must never fork the API's behavior from local mode.
- Statement parsing is server-side and **ephemeral by policy** (plan 12, `server/statements/`): one file per `POST /api/statements/parse` request, parsed deterministically (no LLM/AI services, ever) in request memory and discarded — no storage, no debug dumps on that route, no statement content in logs or error responses. Any change that would persist or transmit statement bytes/transactions beyond the request is a privacy regression; the guarantees are pinned by `tests/test_statements.py` + `tests/test_server_api.py`, and the review/aggregation layer stays in the browser (`site/src/lib/statements/`) — only user-approved totals reach `/api/optimize`.
