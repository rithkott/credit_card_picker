# credit_card_picker — instructions for Claude

Deterministic credit-card portfolio optimizer built on a hand-curated YAML dataset. Read `docs/research.md` for product direction and `docs/curation-guide.md` before touching card data.

## Architecture diagram maintenance (required)

`docs/architecture.md` contains a Mermaid diagram of the data infrastructure and schema, annotated with why each field exists. **Any change to the architecture must update this diagram in the same commit/PR.** That means edits to any of:

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
