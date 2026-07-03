# credit_card_picker — instructions for Claude

Deterministic credit-card portfolio optimizer built on a hand-curated YAML dataset. Read `docs/research.md` for product direction and `docs/curation-guide.md` before touching card data.

## Architecture diagram maintenance (required)

`docs/architecture.md` contains a Mermaid diagram of the data infrastructure and schema, annotated with why each field exists. **Any change to the architecture must update this diagram in the same commit/PR.** That means edits to any of:

- `data/schema/card.schema.json` (fields added/removed/changed — the diagram explains every block)
- `data/meta/` registries (new registry files, or structural changes to existing ones)
- `scripts/validate_cards.py` (new checks, or changes to what's an error vs a warning)
- `.github/workflows/validate-data.yml` (triggers, cadence)
- the repo's data layout (`data/`, `scripts/` structure)

The diagram documents **only what is built** — never add planned/future components to it. When new architecture ships (optimizer, UI, build pipeline), extend the diagram then.

## Project conventions

- The dataset is hand-curated and verified — never scrape or generate card data on the fly, and never add affiliate/monetization features (see `docs/research.md` for why).
- New/edited card files must pass `python3 scripts/validate_cards.py` (needs `pyyaml` + `jsonschema`).
- Card data drafted without checking issuer sources must be marked `confidence: low` with a "NEEDS human verification" marker in `verified_by`.
- Cross-card assumptions (categories, merchants, point valuations) live only in `data/meta/` registries, referenced by key — never inline them in card files.
