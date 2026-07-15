# Credit Card Picker

**Find the credit card that actually pays you the most based on your real spending**

Most card recommendation sites rank whatever pays them the highest commission, this tool tells you exactly which card is the best for you

**Try it now: [creditcardpicker.vercel.app](https://creditcardpicker.vercel.app)** — no install, no clone, no account. Or run everything locally (see [Getting started](#getting-started)).

## What it does

- **Enter your spending** by category (groceries, dining, gas, travel, …) — or import it straight from your card statements (PDF/CSV) and let the tool categorize it.
- **Answer a few honesty questions** — would you really use an airline credit? keep a DoorDash habit? — so credits and perks are only counted when you'd actually redeem them.
- **Get a ranked list of card portfolios** (1 up to N cards), each with its net annual value: rewards earned minus fees, with every assumption shown. It tells you which card to swipe for which category.
- **Read the receipts**: the site's How-it-works, Data-sources, and Assumptions pages show the full methodology, every card file's verification status, and the exact point valuations used — served live from the same data the optimizer scores.

## Privacy

**Your statements are parsed in memory and never stored.**

- Statement imports (PDF/CSV/OFX) are parsed one file at a time by the API: each file is held in memory only for the duration of its request, parsed deterministically (no AI/LLM services, no third parties), and discarded the moment the transactions are returned to your browser. Nothing is written to disk, logged, or debug-dumped — the no-storage guard is enforced in code and pinned by tests, not just promised.
- Review and aggregation stay in your browser: which totals reach the optimizer is decided by you on the review screen, and only those per-category dollar totals are sent to be scored. Nothing is stored there either.
- No accounts, no cookies, no analytics, no tracking.
- Want nothing to leave your machine at all? Run the whole thing locally (below) — the same site and API work against `localhost`, and the command-line mode needs no server at all.

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
docs/architecture.md      annotated diagram of the whole system — data, optimizer, web, deploy (kept current, built-only)
docs/curation-guide.md    how to write & verify card files (start here to contribute data)
data/schema/              JSON Schema every card file must conform to
data/cards/<issuer>/      one hand-curated YAML file per card (source of truth)
data/meta/                canonical registries: categories, merchants, point valuations
scripts/validate_cards.py schema + registry + staleness validation (runs in CI)
scripts/optimize.py       deterministic portfolio optimizer
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

**Optimizer details:** ranks every 1–`max_cards` portfolio of approvable cards by net annual value (`--json` for machine output, `--as-of` for reproducible runs).

## Adding & verifying cards

Every card is one hand-curated YAML file in `data/cards/<issuer>/<card-id>.yaml`, checked against issuer terms. There are three ways in, all ending at the same validator gate. Read [docs/curation-guide.md](docs/curation-guide.md) first — it's the field-by-field reference these tools assume.

**1. Card-entry form (easiest — no build, no Python to write).** Open `tools/card-entry-form.html` directly in a browser. It embeds the current category / merchant / point-program registry keys and mirrors the schema, so it can only emit valid choices; fill in the fields and it generates schema-valid YAML for you to save under `data/cards/<issuer>/`.

```sh
open tools/card-entry-form.html      # macOS; or just double-click it
```

**2. By hand from the template.** Copy the template at the bottom of [docs/curation-guide.md](docs/curation-guide.md) into `data/cards/<issuer>/<card-id>.yaml` and fill it in. `issuer` must match the directory name, `id` must match the filename. Rates are earn-units per dollar; cross-card assumptions (categories, merchants, point values) are referenced by key from `data/meta/` — never inlined.

**3. Converting an offer file (AI task).** Terms sheets live in `data/offer_files/<issuer>/<slug>.txt`. Turning one into a card YAML is a stricter job because you're transcribing a transcription — follow [docs/ai-conversion-protocol.md](docs/ai-conversion-protocol.md) step by step (it gates entry into the curation guide, not replaces it). Any card drafted without confirming numbers against the issuer's own page **must** be marked `confidence: low` with a `NEEDS human verification` marker in `verification`.

**Verifying existing cards.** The dataset is only as good as its sources. To promote a `confidence: low` card to `high`, check every rate, cap, fee, credit, and bonus against the issuer's live terms and record the URLs in `verification.source_urls`. Cards flagged `NEEDS_VERIFICATION` already have their official page links collected in [docs/needs-verification-links.md](docs/needs-verification-links.md) — start there. CI re-flags any card not re-checked in 6 months.

**The gate (required for every path).** Nothing lands until it passes the validator — schema, registry-key, and staleness checks, the same run CI does on any `data/` change:

```sh
pip install pyyaml jsonschema
python3 scripts/validate_cards.py
```

Fix every `ERROR`; staleness / low-confidence `WARN`ings are informational. See the full flow in [docs/curation-guide.md](docs/curation-guide.md).

## Deployment

Live at **https://creditcardpicker.vercel.app**. The site deploys to Vercel as a static Vite build plus one Python serverless function running the exact same `server/app.py` (via the `api/index.py` shim — the API has one definition everywhere). `vercel.json` carries the whole config: build commands, SPA rewrites, and the function's `excludeFiles`; root `requirements.txt` lists the function's dependencies.

Deploys happen automatically via Vercel's git integration on push. For manual deploys:

```sh
npm i -g vercel
vercel          # preview deploy from the repo root
vercel --prod   # production
```

No environment variables are required — the production build talks to the API on the same origin. To point a static build at a different API host, set `VITE_API_URL` at build time.
