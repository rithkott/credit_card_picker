# Credit Card Picker

**Find the credit cards that actually pay you the most — based on your real spending, with zero sales pitch.**

Most card-recommendation sites rank whatever pays them the highest affiliate commission. This tool does the opposite: you tell it how you actually spend, and it computes — deterministically, from a hand-curated dataset — the single best card *or combination of cards* for you, netting out reward rates, category caps, annual fees, signup bonuses, and the credits you'd realistically use.

**Try it:** deployed on Vercel (see [Deployment](#deployment)) — no install, no clone. Or run everything locally (see [Getting started](#getting-started)).

## What it does

- **Enter your spending** by category (groceries, dining, gas, travel, …) — or import it straight from your card statements (PDF/CSV) and let the tool categorize it.
- **Answer a few honesty questions** — would you really use an airline credit? carry a portal habit? — so credits and perks are only counted when you'd actually redeem them.
- **Get a ranked list of card portfolios** (1 up to N cards), each with its net annual value: rewards earned minus fees, with every assumption shown. It tells you which card to swipe for which category.
- **Read the receipts**: the site's How-it-works, Data-sources, and Assumptions pages show the full methodology, every card file's verification status, and the exact point valuations used — served live from the same data the optimizer scores.

## Privacy

**Your statements never leave your browser.**

- Statement imports (PDF/CSV/OFX) are parsed entirely in your browser — the files are never uploaded anywhere. Only the resulting per-category dollar totals are sent to the optimizer API to be scored, and nothing is stored.
- No accounts, no cookies, no analytics, no tracking.
- Want even the category totals to stay on your machine? Run the optimizer locally (below) — the same site works against `localhost`, and the command-line mode needs no server at all.

## No conflicts of interest

There are no affiliate links, sponsored placements, or monetization of any kind — by design, permanently. Rankings are pure arithmetic over your numbers. See [docs/research.md](docs/research.md) for why this matters in this industry.

## Getting started

Fully local mode — everything on your own machine:

```sh
# 1. Start the optimizer
pip install -r server/requirements.txt
python3 server/app.py              # API on http://localhost:8000

# 2. Build the web UI (the server then serves it at http://localhost:8000)
cd site && npm ci && npm run build
```

Prefer the command line? Same engine, no browser:

```sh
pip install pyyaml
cp examples/spend-profile.example.yaml my-profile.yaml   # then edit in your numbers
python3 scripts/optimize.py --profile my-profile.yaml
```

## Why trust the numbers

- **Hand-curated data.** Every card is a human-maintained YAML file with sources, verification date, and a confidence grade — never scraped or AI-generated on the fly. CI re-flags any card not re-checked in 6 months. `confidence: low` marks data still awaiting human verification against issuer terms.
- **Deterministic.** Identical inputs produce byte-identical output. Every valuation assumption (point values, credit usage, caps) is echoed in the run header so you can audit the math.
- **Honest valuation.** Points are priced at each program's engaged-average cents-per-point, and statement credits only count if you said you'd use them.

---

## Architecture & development

An annotated diagram of the whole system — data schema, validation pipeline, optimizer, and web stack — lives in [docs/architecture.md](docs/architecture.md).

```
docs/research.md          competitive research + product decisions
docs/architecture.md      annotated diagram of the data infra & schema (kept current, built-only)
docs/curation-guide.md    how to write & verify card files (start here to contribute data)
docs/plans/               design specs (02 = optimizer, 04 = tech stack, ...)
data/schema/              JSON Schema every card file must conform to
data/cards/<issuer>/      one hand-curated YAML file per card (source of truth)
data/meta/                canonical registries: categories, merchants, point valuations
scripts/validate_cards.py schema + registry + staleness validation (runs in CI)
scripts/optimize.py       deterministic portfolio optimizer (spec: docs/plans/02-optimizer.md)
server/                   FastAPI wrapper exposing the optimizer to the web UI
site/                     the web UI (Vite + React + TS; static build served by Vercel or the local server)
api/index.py              Vercel entrypoint — import shim re-exporting server/app.py's FastAPI app
vercel.json               Vercel build/rewrite/function config (see Deployment)
tests/                    optimizer golden + API tests (python3 -m unittest discover tests, runs in CI)
examples/                 example spend-profile YAML to copy for scripts/optimize.py
tools/card-entry-form.html browser form that generates schema-valid card YAML (open directly, no build)
```

**Validating the data** (runs in CI on any `data/` change, plus weekly for staleness):

```sh
pip install pyyaml jsonschema
python3 scripts/validate_cards.py
```

**Optimizer details:** ranks every 1–`max_cards` portfolio of approvable cards by net annual value (`--json` for machine output, `--as-of` for reproducible runs; point pricing per [docs/plans/08-simplified-valuation.md](docs/plans/08-simplified-valuation.md)). Design spec: [docs/plans/02-optimizer.md](docs/plans/02-optimizer.md).

**Contributing card data:** follow [docs/curation-guide.md](docs/curation-guide.md); every file must pass `scripts/validate_cards.py`.

## Deployment

The site deploys to Vercel as a static Vite build plus one Python serverless function running the exact same `server/app.py` (via the `api/index.py` shim — the API has one definition everywhere). `vercel.json` carries the whole config: build commands, SPA rewrites, and the function's `excludeFiles`; root `requirements.txt` lists the function's dependencies.

```sh
npm i -g vercel
vercel          # preview deploy from the repo root
vercel --prod   # production
```

No environment variables are required — the production build talks to the API on the same origin. To point a static build at a different API host, set `VITE_API_URL` at build time.
