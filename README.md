# credit_card_picker

A deterministic credit-card portfolio optimizer: given your real spending profile, it computes the best card — or combination of cards — to hold, jointly weighing reward rates, category caps, annual fees, signup bonuses, and usable credits. No affiliate links, no sponsored rankings; see [docs/research.md](docs/research.md) for why.

## Layout

```
docs/research.md          competitive research + product decisions
docs/architecture.md      annotated diagram of the data infra & schema (kept current, built-only)
docs/curation-guide.md    how to write & verify card files (start here to contribute data)
docs/card-backlog.md      checklist of cards to curate, grouped by issuer
docs/plans/               step-by-step build plans (01 = dataset, 02 = optimizer, ...)
data/schema/              JSON Schema every card file must conform to
data/cards/<issuer>/      one hand-curated YAML file per card (source of truth)
data/meta/                canonical registries: categories, merchants, point valuations
scripts/validate_cards.py schema + registry + staleness validation (runs in CI)
tools/card-entry-form.html browser form that generates schema-valid card YAML (open directly, no build)
```

## Data philosophy

The dataset is hand-curated and verified — never scraped or AI-generated on the fly. Every card carries a `verification` block (date, sources, confidence); CI flags cards not re-checked in 6+ months, and `confidence: low` marks data still awaiting human verification against issuer terms. To add or verify a card, follow [docs/curation-guide.md](docs/curation-guide.md).

## Validating the data

```sh
pip install pyyaml jsonschema
python3 scripts/validate_cards.py
```

Runs automatically in CI on any change under `data/`, plus weekly to surface staleness.
