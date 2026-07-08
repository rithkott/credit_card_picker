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
scripts/optimize.py       deterministic portfolio optimizer (spec: docs/plans/02-optimizer.md)
server/                   FastAPI wrapper exposing the optimizer to the web UI (local-only v1)
site/                     the web UI (Vite + React + TS; deploys to GitHub Pages)
tests/                    optimizer golden + API tests (python3 -m unittest discover tests, runs in CI)
examples/                 example spend-profile YAML to copy for scripts/optimize.py
tools/card-entry-form.html browser form that generates schema-valid card YAML (open directly, no build)
```

## Web UI

The site computes nothing itself and your spending data never leaves your
machine — it talks to the optimizer running locally
([docs/plans/04-tech-stack.md](docs/plans/04-tech-stack.md)):

```sh
pip install -r server/requirements.txt
python3 server/app.py              # API on http://localhost:8000

cd site && npm ci && npm run dev   # dev UI on http://localhost:5173
# or: npm run build — the server then serves the built site at http://localhost:8000
```

## Data philosophy

The dataset is hand-curated and verified — never scraped or AI-generated on the fly. Every card carries a `verification` block (date, sources, confidence); CI flags cards not re-checked in 6+ months, and `confidence: low` marks data still awaiting human verification against issuer terms. To add or verify a card, follow [docs/curation-guide.md](docs/curation-guide.md).

## Validating the data

```sh
pip install pyyaml jsonschema
python3 scripts/validate_cards.py
```

Runs automatically in CI on any change under `data/`, plus weekly to surface staleness.

## Running the optimizer

```sh
pip install pyyaml
cp examples/spend-profile.example.yaml my-profile.yaml   # then edit in your numbers
python3 scripts/optimize.py --profile my-profile.yaml
```

Ranks every 1–`max_cards` portfolio of cards you can get approved for by net annual value (`--json` for machine output, `--as-of` for reproducible runs; points priced at each program's engaged-average cpp — see docs/plans/08-simplified-valuation.md). Deterministic by design: identical inputs produce byte-identical output, and every valuation assumption is echoed in the run header. The optimizer runtime stays pure stdlib + pyyaml; `scipy` is used only by the test suite as an LP oracle (`pip install scipy` to run `tests/test_assign_exact.py`). Design specs: [docs/plans/02-optimizer.md](docs/plans/02-optimizer.md), [docs/plans/10-optimizer-overhaul.md](docs/plans/10-optimizer-overhaul.md).
