# Plan 22 — Business Cards (3.0): Build Design

Successor to `21-business-cards-research.md` (research + scope decisions). This doc fixes the architecture and phases the build. User-confirmed decisions incorporated:

- **Corpus**: SMB issuer cards + fintech corporate charge (Brex/Ramp/BILL Divvy). ~**70 cards, exhaustive** — all Ink/Spark/Amex Business/US Bank/BofA/Citi/Wells core cards, airline/hotel business co-brands, fleet cards, fintech tier. Traditional negotiated corporate programs documented only.
- **Interactions**: FULL personal↔business model (5/24, Amex 5-card limit, velocity rules, cross-product point pooling). Personal holdings are business-profile inputs.
- **Mounting**: **separate subdomain `business.cardsharp.dev`** — a visually and conceptually distinct site ("almost no shared assets"), same repo + same Vercel deployment.

## Architecture decision: one deployment, two apps

One repo, one release train, one Python API function (unchanged deployment contract in `vercel.json` + `api/index.py`). The business product is a parallel data + engine + frontend stack inside it:

```
data/business/
  schema/business-card.schema.json     # forked schema, business approval/pricing/caps
  meta/  categories.yaml  point-valuations.yaml  usage-questions.yaml  issuer-rules.yaml
  cards/<issuer>/<card-id>.yaml        # ~70 curated cards
  offer_files/<issuer>/<slug>.txt      # terms sheets, same conversion protocol
scripts/
  optimize_business.py                 # new optimizer (own value model; may import
                                       #   pure helpers from optimize.py, never the reverse)
  validate_business_cards.py           # business validator (reuses generic check helpers)
server/
  business_api.py                      # APIRouter mounted by app.py under /api/business/*
site/
  business.html                        # second Vite entry (multi-page build)
  src/business/                        # own App/router/components/styles — no imports from
                                       #   consumer components; own design language
tests/
  test_business_optimizer.py           # golden tests
  test_business_server_api.py
```

**Subdomain serving.** The business SPA is path-addressable at `/business/` in every deployment (previews included), and the subdomain is a host-based rewrite on production:

- Vite `build.rollupOptions.input`: `index.html` + `business.html`; business app uses `base`-aware router with basename `/business`.
- `vercel.json` rewrites (order matters):
  1. `{source: "/(.*)", has: [{type: "host", value: "business.cardsharp.dev"}], destination: "/business/$1"}` — host → path mapping.
  2. existing `/api/(.*)` → `/api/index`.
  3. `/business(/.*)?` → `/business.html` (SPA fallback for the business app).
  4. everything else → `/index.html`.
- `business.cardsharp.dev` added as a domain on the existing Vercel project (CNAME to Vercel; one-time `vercel domains`/dashboard step at launch, Phase F).
- Branch previews test via the `/business/` path (host rewrites don't apply to `*.vercel.app` preview hosts) — fits the existing preview-QA recipe.

**Why not a second Vercel project:** doubles deploy/release surface, violates the "one API function, one release per main push" contract in CLAUDE.md, and the API must stay unified anyway (one FastAPI app serves both products).

**API namespace:** `/api/business/config|cards|assumptions|optimize|evaluate|suggest-addition`. Same bundle-shape family as consumer so the business frontend copies the consumer types pattern (`site/src/business/types.ts` mirrors the business contract; consumer `types.ts` untouched). Consumer endpoints byte-identical before/after (pinned by existing `tests/test_server_api.py`).

**No statement parsing for business V1.** CFOs enter GL-style annual spend manually (research §7). The `/api/statements/parse` route stays consumer-only; business spend entry is category-first with archetype presets later.

## Business schema (delta vs consumer `card.schema.json`)

Forked file; shares structural conventions (rates as earn-units/$, registries by key, sources+verification required, `additionalProperties:false`). Changes:

**Replaced**
- `approval` → `business_approval`:
  `{personal_guarantee: bool, min_personal_fico_tier: (good|very_good|excellent|null), entity_types: [sole_prop|llc|corp], requires_ein: bool, min_cash_balance_usd: int|null, min_annual_revenue_usd: int|null, funding_accepted: bool, notes}`
  (Ramp: PG false, cash 25000; Brex: PG false, cash 50000 or revenue 500000 or funding; Ink: PG true, fico very_good.)
- `fees` → `pricing`:
  `{model: annual_fee|per_seat, annual_fee_usd, first_year_waived, per_seat_monthly_usd, platform_fee_note, fee_refund_spend_usd (Spark Cash Plus $150k refund), foreign_transaction_pct}`

**Added**
- `cap_groups`: `{<group_key>: {amount_usd, period: year}}` at card level; a `category_rewards[]` entry may set `cap_group: <key>` instead of its own `cap` (Ink Cash: two groups of $25k; Ink Preferred/Biz Gold: one $150k group).
- `category_rewards[].min_transaction_usd` (Amex Biz Platinum 2x ≥$5k; Ink Premier 2.5% ≥$5k).
- `adaptive_top_n`: `{n: 2, rate, eligible_categories: [...], cap_group}` (Amex Biz Gold; deterministic: engine picks user's top-n eligible categories by spend).
- `employee_cards`: `{fee_usd, free_expense_card_variant: bool, max_cards, spend_counts_toward_bonus: bool (US Bank false), controls: [limits|mcc_restrictions|realtime_alerts|preswipe_policy]}`
- `payment_type`: `revolving|charge`.
- `pooling`: `{program_combinable: bool}` (Ink Premier false).
- `integrations`: `[quickbooks|netsuite|xero|sage_intacct|expensify]` (unscored, surfaced in UI).
- `virtual_cards`: bool flag (unscored).
- `float_days`: `{grace_days: int|null, note}` — reported per portfolio, not scored (V1).
- `issuer_rules_ref`: key into `issuer-rules.yaml`.

**Kept as-is**: `id/name/issuer/network`, `currency{type,program}`, `availability`, `base_rate`, `category_rewards` core, `merchant_rewards` (rare in business; kept for completeness), `credits[]` + `usage_keys` (Amex credit ecosystem maps directly), `signup_bonus` (business SUBs are large; same shape), `unlocks_transfers`, `max_annual_rewards_usd`, `benefit_flags`, `sources`, `verification`, `notes`.

**Dropped**: `earn_ratio` (Bilt housing), `closed_loop`, `relationship_boost`, `required_membership`, `base_rate_conditional`, `rotation`/`choice` (no business rotating/choice cards in scope; re-add if curation finds any).

## Registries (`data/business/meta/`)

- `categories.yaml` (~16): `advertising, shipping, software_saas, telecom, office_supplies, travel_flights, travel_hotels, travel_other, fuel_fleet, dining, transit, utilities, contractors_materials, wholesale, insurance_professional_services, other`. No pseudo-categories, no `explicit_only` (no housing analog).
- `point-valuations.yaml`: UR/MR/Capital One/co-brand programs copied from consumer values (same programs, same cpp — single source of truth question: **copy, not share**, per "no shared assets"; values must match consumer file at curation time and drift is caught by a validator warning that compares overlapping programs). Add `brex_points` (variable, floor/optimistic), `divvy_points`, `ramp_cashback` (cash).
- `usage-questions.yaml`: business usage groups — airlines flown for business, hotel programs, Dell/tech purchasing, wireless provider, shipping carrier usage, rideshare/travel platforms, ERP in use (drives integration surfacing, `assumed_reward_kind` n/a).
- `issuer-rules.yaml` (new registry, the FULL-interaction backbone):
  ```yaml
  chase:    {gate_524: true,  adds_to_524: false, velocity_note: "~2 accounts/30d"}
  amex:     {credit_card_limit: 5, charge_exempt: true, once_per_lifetime_bonus: true}
  capital_one: {adds_to_524: true, exceptions: [venture-x-business, spark-cash-plus], velocity: 1 per 6mo}
  citi:     {business_velocity_days: 95}
  discover: {adds_to_524: true}
  td:       {adds_to_524: true}
  ```
  Cards reference issuer rules implicitly via `issuer`; per-card overrides via `issuer_rules_ref` exceptions list.

## Business profile & optimizer (`scripts/optimize_business.py`)

**Profile contract** (`parse_business_profile`):
```
spend:            {<business_category>: annual_usd}   # required non-empty
company:          {entity_type, accepts_personal_guarantee, owner_fico_tier|null,
                   cash_balance_usd|band, annual_revenue_usd|band, has_funding,
                   employee_card_seats: int, large_txn_share: 0..1}
personal:         {five24_count: int, amex_credit_cards: int,
                   premium_cards_held: [sapphire_preferred|sapphire_reserve|ink_preferred|
                                        amex_platinum|amex_gold]}
user:             {max_cards, optimize_for: ongoing|year1, reward_preferences,
                   confirmed_usage[]}
exclude_cards:    [...]
```
`large_txn_share` = fraction of spend in ≥$5k transactions (single global knob V1; per-category later if needed).

**Value-model deltas vs consumer engine:**
1. **Cap groups**: reward lines referencing a `cap_group` draw from one shared annual pool; assignment order = highest-rate-first within group (deterministic).
2. **Min-transaction gating**: a `min_transaction_usd` line only earns on `spend × large_txn_share` of eligible buckets; remainder falls to base rate.
3. **Adaptive top-n**: expand at scoring time — pick user's top-n eligible categories by spend, materialize as category lines into the card's cap group.
4. **Fees**: `annual_fee` model → fee + `employee_card_seats × employee_cards.fee_usd` (0 when free / when free_expense_card_variant chosen — V1 uses the free variant when fee_usd > 0 unless the paid employee card carries scored benefits; simplest deterministic rule: always charge fee_usd, notes explain variants; final call at implementation). `per_seat` model → `seats × per_seat_monthly_usd × 12` with the **free tier priced at $0** and paid tier listed as a note (research: paid tiers buy software, not card economics). `fee_refund_spend_usd` refunds fee when total assigned card spend ≥ threshold.
5. **Approval filter**: card eligible iff company satisfies `business_approval` (PG acceptance, fico tier when PG, cash/revenue/funding thresholds, entity type).
6. **Portfolio constraints in `search`**:
   - Chase cards excluded when `five24_count ≥ 5` (gate_524).
   - Amex credit cards in portfolio + `personal.amex_credit_cards` ≤ 5 (charge-lineage cards exempt via `payment_type: charge`... exemption keys off issuer-rules `charge_exempt` + card `payment_type`).
   - Pooling/transfer gateways: `unlocks_transfers` unlocked by portfolio cards **or** `personal.premium_cards_held` (maps to program gateways registry-side).
   - `pooling.program_combinable: false` cards never contribute to nor benefit from program pooling.
7. **Reporting additions to bundle**: per-portfolio `blended_rate` (total rewards ÷ total spend), `float_days` summary, `application_notes[]` (velocity/5/24 sequencing hints — informational strings, not constraints), `fee_model_notes[]`.
8. Signup-bonus feasibility: per-card `employee_cards.spend_counts_toward_bonus` excludes seat spend — V1 simplification: feasibility uses total spend unless flag false, then uses total (owner) spend × heuristic? **No heuristics** — profile lacks owner/employee split; V1 rule: flag recorded, feasibility uses total spend, note emitted when flag false. (Deterministic, transparent.)

Engine skeleton (buckets → lines → greedy assignment → credits → bonus → subset search with `MAX_SCORED_SUBSETS` budget) is copied from `optimize.py` and adapted — not imported wholesale; shared pure helpers (money/cap arithmetic) may be lifted into a small `scripts/optimizer_common.py` only if extraction is clean, else duplicated (business file is authoritative for business math).

**Golden tests**: `tests/test_business_optimizer.py` mirrors consumer golden-test style — fixed profiles (DTC-heavy, SaaS startup no-PG, trades, restaurant flat-rate case, 5/24-blocked case, Amex-limit case, cap-overflow case) with exact expected bundles.

## Server (`server/business_api.py`)

`APIRouter(prefix="/api/business")` included from `app.py` lifespan-loaded with its own dataset (business cards + registries). Endpoints mirror consumer: `config` (business categories, company-field enums, defaults, usage questions, issuer rules summary), `cards`, `assumptions`, `optimize`, `evaluate`, `suggest-addition`. Same error mapping (InputError→422). `tests/test_business_server_api.py` pins shapes. Consumer API untouched (existing tests prove it).

## Frontend (`site/src/business/`)

Own tree, no imports from `site/src/components|pages` (enforced by review; a lint rule if cheap). Own design language: departs from consumer greige neomorphic — direction decided at Phase E with `frontend-design` skill (CFO-serious: ledger/annual-report aesthetic, denser numerics, restrained palette; distinct from consumer look on purpose).

- `business.html` entry → `src/business/main.tsx` → `BusinessApp` with basename-aware router (`/business`).
- Journeys V1: **generate** + **analyze** + **compare** (improve deferred — "best card to add" matters less when starting a program; revisit Phase E).
- Input flow: company profile step (entity/PG/revenue/cash/seats/large-txn share) → spend entry (business categories, annual units, GL framing) → personal-cards step (5/24 count, premium cards held, Amex count) → usage questions → results.
- Results: portfolio receipts w/ blended rate headline, cap-exhaustion visualization (how much spend earns bonus vs overflow), fee breakdown incl. seat fees, application notes, float days, integrations badges.
- Own `types.ts`, `api.ts` (business endpoints), `lib/` (money/persistence can be copied; localStorage keys namespaced `ccp:business:*`).
- Static pages: how-it-works (business framing), data-sources, assumptions.

## Phases (each = worktree branch → preview → merge → release, per CLAUDE.md)

- **22A — Foundations** `[minor]`: `data/business/{schema,meta}` complete, `scripts/validate_business_cards.py`, 3–5 seed cards (Ink Cash, Ink Preferred, Amex Biz Gold, Spark Cash Plus, Ramp) exercising every new schema mechanic, CI `validate-data.yml` extended to business dataset, `docs/architecture.md` diagram extended (new data plane + planned-nothing rule: only shipped pieces drawn per phase).
- **22B — Corpus** (multiple branches/releases): ~70 cards via offer-file conversion protocol (`docs/ai-conversion-protocol.md` applies; business addendum written first: cap groups, employee-card fields, business approval sourcing). All drafts `confidence: low` + "NEEDS human verification" unless issuer-verified. Order: Chase Ink line → Amex Business → Capital One Spark → US Bank/BofA/Citi/Wells → fintech (Brex/Ramp/Divvy) → co-brands (United/SW/Hyatt/IHG/Delta/Hilton/Marriott/Bonvoy Business, AA/Alaska) → fleet (WEX/Fuelman/Shell).
- **22C — Optimizer** `[minor]`: `optimize_business.py` + golden tests; CLI parity (`render_json/render_text`).
- **22D — API**: `server/business_api.py` + tests; `site/src/business/types.ts` scaffold in same change (contract rule from CLAUDE.md applies to the business pair: business API changes update business types/tests together).
- **22E — Frontend** `[minor]`: business SPA (Vite multi-entry, `/business/` path), full journey, preview QA via path URL with Playwright recipe.
- **22F — Launch** `[minor]`: host rewrite in `vercel.json`, add `business.cardsharp.dev` domain, cross-links (consumer footer ↔ business site), prod QA on subdomain, release notes announce 3.0.

CLAUDE.md conventions section gains a business paragraph at 22A (data/meta separation, no monetization, curation rules apply to `data/business/` identically; `tools/card-entry-form.html` embedded-lists rule stays consumer-scoped until a business form exists).

## Verification (per phase)

- 22A: `python3 scripts/validate_business_cards.py` green on seeds; consumer validator + tests untouched-green.
- 22C: golden tests + hand-checked math on 2 profiles (DTC $600k spend cap-overflow; SaaS no-PG fintech-only).
- 22D: pytest server suites (both products); `/api/*` consumer responses byte-diffed pre/post.
- 22E/F: preview Playwright pass on `/business/` (wizard → results, all journeys), consumer smoke on `/`, then subdomain smoke post-domain-attach.

## Open items (deferred, tracked here)

- Archetype spend presets — needs the follow-up research pass (plan 21 §7 weak spot) before shipping presets.
- Business statement import — explicitly out of V1.
- Improve journey for business — revisit at 22E.
- Employee paid-card benefits (Amex $400 employee Platinum lounge access) — recorded in notes, unscored V1.
