# Step 1: Card & Rewards Dataset Schema

The card/rewards dataset is the foundation everything else depends on, so it's the first thing to build.

**Storage format:** one hand-curated YAML file per card, grouped by issuer, validated against a shared JSON Schema in CI — not a database. Rationale: the bottleneck here is human curation/review, not query performance (a few hundred cards, loaded into memory at runtime). One-file-per-card keeps PRs small and reviewable, gives meaningful git history per card, and lets YAML comments carry "why" notes (e.g. "capped at $6k, source: issuer footnote 3"). A compiled JSON/SQLite artifact can be generated from these YAML files at build time for fast runtime reads — the YAML stays the human-edited source of truth.

```
data/
  schema/card.schema.json         # JSON Schema, validated in CI on every PR
  cards/<issuer>/<card-id>.yaml   # one hand-curated file per card
  meta/point-valuations.yaml      # shared cents-per-point table (referenced, not duplicated per card)
  meta/categories.yaml            # canonical spend-category enum (shared by data + the manual-entry UI)
  meta/merchants.yaml             # canonical merchant enum
```

**Schema shape:** every card decomposes into six independent top-level blocks, because each requires fundamentally different math in the optimizer — mixing them into prose or a single flat rate table is exactly what makes this hard to calculate reliably:
1. `category_rewards` — proportional to spend; supports `cap` (period + max_spend + fallback_rate) and `rotation` (quarterly categories requiring manual activation, modeled explicitly so the optimizer can discount for non-activation)
2. `merchant_rewards` — same shape as category rewards, keyed to a canonical merchant list instead of a category
3. `credits` — fixed-value, use-it-or-lose-it, periodic (monthly/quarterly/annual/every-4-years), explicitly NOT scaled by spend — each carries a `realistic_capture_rate_note` since credits like Amex Platinum's are routinely partially wasted
4. `signup_bonus` — one-time, conditional on a spend threshold within a time window; excluded from multi-year projections
5. `fees` — annual fee (with optional first-year-waived), foreign transaction fee
6. `point_valuation` (via a shared `meta/point-valuations.yaml` cents-per-point table, so the same points can be valued conservatively "cash-out floor" or optimistically "transfer partner average" as a global, user-visible assumption) + `benefit_flags` (binary attributes like primary rental insurance — not scored in v1, available for future filtering)

Every card also carries a `verification` block (`last_verified_date`, `verified_by`, `source_urls`, `confidence`) so a CI/cron job can flag cards that haven't been re-checked against issuer terms in 6+ months — this is how "confirmed dataset" gets enforced structurally rather than just asserted.

**How the optimizer will consume it:** a `computeAnnualValue(card, spendProfile, valuationMode)` function per card — match spend to category/merchant rewards (merchant beats category beats catch-all), apply caps/fallback rates, convert points to USD via the valuation table, add credits the user profile indicates they'd actually use, add the signup bonus once (year 1 only), subtract fees. For a *combination* of cards, the optimizer assigns each spend-category dollar to whichever candidate card yields the best marginal rate given remaining room under its cap (a small per-category knapsack/assignment problem once multiple capped cards compete for the same category), then sums credits/bonuses and subtracts all fees across the set. The uniform six-block shape means this logic is identical for every card — no card-specific branches.

Representative example YAML entries were drafted for three archetypes (flat-rate Citi Double Cash, rotating-category Chase Freedom Flex, category+monthly-credits+signup-bonus Amex Blue Cash Preferred) to prove the shape works in practice, not just in the abstract — these will be written as the first real files in `data/cards/`.

**Concrete next actions for this step:**
1. Create `data/schema/card.schema.json` and the `data/meta/*.yaml` canonical registries (categories, merchants, point valuations).
2. Hand-curate an initial seed set of real cards (the three archetypes above plus a handful more spanning issuers) as `data/cards/<issuer>/<card-id>.yaml`.
3. Add a CI validation step that checks every card file against the schema and flags stale `verification.last_verified_date`.
