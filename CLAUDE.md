# credit_card_picker — instructions for Claude

Deterministic credit-card portfolio optimizer built on a hand-curated YAML dataset. Read `docs/research.md` for product direction and `docs/curation-guide.md` before touching card data.

## Workflow: branching, releases, deployment (required)

All work follows this process — no direct commits to `main`.

Multiple Claude Code sessions work this repo in parallel. The process below is concurrency-safe: versions/tags/releases are handled by CI, never by sessions.

**Branching**
- Every change is developed on a git worktree branched from **remote** main: `git fetch origin main && git worktree add .claude/worktrees/<branch> -b <branch> origin/main`.
- `main` is the only long-lived branch. It is the branch Vercel deploys to production (https://creditcardpicker.vercel.app). Never push work-in-progress directly to `main`.
- No dedicated dev/preview branch: Vercel's git integration builds a preview deployment for every pushed non-`main` branch — that preview URL is the staging environment.

**Preview → production**
1. Develop and commit on the worktree branch; push it to `origin`.
2. Vercel auto-builds a preview deployment for the branch. Test the change on that preview URL (not just locally).
3. **Pre-merge sync (required):** `git fetch origin main`; if `origin/main` moved past your branch point, rebase the branch onto `origin/main`, re-push, and re-verify the preview if the rebase touched overlapping areas. Never merge a branch that isn't rebased onto current `origin/main`.
4. Merge after self-verifying the preview (QA pass), no waiting for user approval: `git checkout main && git pull --ff-only origin main && git merge --no-ff <branch> -m "Merge <branch>: <summary>[ [minor]]" -m "<release-note bullets>" && git push origin main`. If the push is rejected (another session merged first), pull `--ff-only` again, confirm the merge is still clean, and re-push.
5. **Post-merge verification (read-only):**
   - Production deploy: Vercel deployment goes READY and the live site reflects the change. If the git trigger doesn't fire (known flaky), fall back to `vercel deploy --prod`.
   - Release: `gh run list --workflow=release.yml --limit 1` is green and `gh release list --limit 1` shows the new tag. **Sessions never create tags or releases themselves** — CI does it; a red Release run is what you fix (re-run it), not a reason to tag by hand.
6. Clean up: `scripts/finish-branch.sh <branch>` (removes the worktree, deletes local + remote branch; refuses if the branch isn't fully merged into `origin/main`).

**Versioning** (semver git tags `vX.Y.Z`, automated by `.github/workflows/release.yml`)
- Every push to `main` gets exactly one tag + one GitHub Release, created by CI. The version is computed from the remote tag list at run time; a tag-push race with a parallel merge is resolved automatically (loser retries with the next number). Sessions never pick version numbers.
- Bump size is signaled in the merge-commit **subject**: append ` [minor]` for large overhauls (new subsystems, reworked optimizer/UI, breaking data-model changes) or ` [major]`; default is patch. Do **not** put a version number in the commit message.
- The merge-commit **body** becomes the release notes verbatim — write user-facing bullets there.
- `[skip release]` in the merge subject skips tagging (true emergencies only).

## Architecture diagram maintenance (required)

`docs/architecture.md` contains a Mermaid diagram of the whole system — data infrastructure, schema, optimizer, web UI, and Vercel deployment — annotated with why each piece exists. **Any change to the architecture must update this diagram in the same commit/PR.** That means edits to any of:

- `data/schema/card.schema.json` (fields added/removed/changed — the diagram explains every block)
- `data/meta/` registries (new registry files, or structural changes to existing ones)
- `scripts/validate_cards.py` (new checks, or changes to what's an error vs a warning)
- `scripts/optimize.py` (policy constants, value model, filters, or output-contract changes — golden tests in `tests/test_optimizer.py` must be updated in the same change)
- `.github/workflows/validate-data.yml` and `.github/workflows/release.yml` (triggers, cadence, release logic)
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
- Statement parsing is server-side, **ephemeral by policy**, and **detection-only** (plans 12+14, `server/statements/`): one file per `POST /api/statements/parse` request, parsed deterministically (no external LLM/AI APIs, no ML models, ever) in request memory and discarded — no storage, no debug dumps on that route, no statement content in logs or error responses, and the response carries only the transactions whose descriptor matches a `data/meta/statement-descriptors.yaml` usage item (`{summary, matches}` — the full transaction list never leaves the server). Statements never populate spend: the user enters spending manually; detected services only pre-check `confirmed_usage` suggestions. Any change that would persist or transmit statement bytes/transactions beyond the request — or return unmatched transactions — is a privacy regression; the guarantees are pinned by `tests/test_statements.py` + `tests/test_server_api.py`, and the aggregation/annualization layer stays in the browser (`site/src/lib/statements/`).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **credit_card_picker** (1533 symbols, 3201 relationships, 101 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
