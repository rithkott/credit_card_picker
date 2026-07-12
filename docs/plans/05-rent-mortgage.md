# Plan 05 — rent/mortgage (housing) and Bilt's Everyday Spend Ratio

Status: **shipped**. This doc records the model as built (v1.5.0 introduced the
`housing` category; v1.6.0 added the `earn_ratio` multiplier + steering pass).
The original plan-05 draft was lost in the v1/v2 `main` rewind; this is the
authoritative record.

## Problem

Rent/mortgage is most households' largest outflow, but it can't be charged to a
normal credit card without a ~3% processor fee — so a normal card earns **nothing**
on it. A few cards (Bilt) let you pay housing fee-free through their app and earn
points on it. That makes "do you pay rent/mortgage, and how much?" a first-class
input: for a high-rent household a Bilt card can be the best *standalone* pick,
where it would look mediocre on everyday spend alone.

Bilt's housing earn is **not** a flat rate. It's a step function of the
**Everyday Spend Ratio (ESR)** = (everyday spend charged to the Bilt card) ÷
(housing payment), per billing cycle:

| ESR | points per $ on housing |
|-----|--------------------------|
| < 25% | 0 (250 pt/cycle floor) |
| 25–49% | 0.5 |
| 50–74% | 0.75 |
| 75–99% | 1.0 |
| ≥ 100% | 1.25 |

The optimizer already decides how much everyday spend to put on each card, so the
ratio — and thus the multiplier — is computable, not a guess.

## Model

### `housing` category — `explicit_only`
`data/meta/categories.yaml` marks `housing` with `explicit_only: true`. In the
optimizer (`scripts/optimize.py`):
- `build_buckets` tags explicit_only buckets; the base-rate line **skips** them, so
  housing earns only via an explicit `category: housing` reward, never the base rate.
- housing spend is **excluded** from signup-bonus and credit-unlock spend-feasibility
  windows (`everyday_spend` in `score_portfolio` → `score_credits`/`score_bonus`) —
  those measure card-payable volume, and Bilt's own bonuses require "Everyday Spend."
- The web UI asks for it in a dedicated rent/mortgage block, not the general grid.

### `earn_ratio` reward block — the ESR multiplier
A `category: housing` reward may carry an `earn_ratio` block (schema
`data/schema/card.schema.json`, `$defs.earnRatio`; validated in
`scripts/validate_cards.py`):
```yaml
- category: housing
  rate: 1.25                      # max tier rate (ordering / pruning only)
  earn_ratio:
    denominator_category: housing # ratio = everyday-on-card / housing-on-card
    floor_points_per_cycle: 250
    cycles_per_year: 12
    tiers: [{min_ratio: 0, rate: 0}, {min_ratio: 0.25, rate: 0.5},
            {min_ratio: 0.5, rate: 0.75}, {min_ratio: 0.75, rate: 1},
            {min_ratio: 1.0, rate: 1.25}]
```

### Steering pass (`steer_earn_ratio`, active steering)
Because `housing` is explicit_only, its bucket is only ever eligible on the card's
housing line and everyday buckets are never eligible there — so the multiplier can
be resolved **after** the greedy assignment without perturbing it. For a portfolio
containing an earn_ratio card:

```
V(x) = baseline_everyday_value − Sacrifice(x) + Housing(mult((E0 + x)/housing))
```

- `E0` = everyday already assigned to the card by the greedy baseline.
- `Sacrifice(x)`: move the **cheapest** everyday dollars first (each dollar's cost =
  what it earns now − what it earns on this card). Built from the baseline assignment
  (other cards' everyday assignments + unassigned everyday spend), sorted ascending.
- `Housing(mult)` = `max(mult·housing, floor_pts/yr) · cpp/100`.
- `mult` is a step function, so `V` jumps at each tier threshold then decays as
  Sacrifice grows ⇒ the optimum is `x=0` or exactly one tier threshold
  `S_T = T·housing − E0` (reachable ones only). Evaluate those few points, pick the
  best, move the chosen dollars onto the card, and re-price the housing line at the
  resolved multiplier (expressed as an effective points-per-$ when the floor binds,
  so the displayed `rate × spend × cpp` reconciles). The housing note shows the ESR:
  `everyday $X ÷ rent $Y = Z% → M× housing points`.

Standalone Bilt: all everyday is already on the card ⇒ ESR maxes naturally, nothing
to steer. Steering only matters in 2–3 card portfolios, where everyday spend would
otherwise flow to stronger cards and collapse the housing multiplier.

Guards / approximations:
- earn_ratio cards are marked **context-dependent** in `prune_dominated_variants`
  (like transfer-gateway cards): never pruned, never a dominator on their max rate.
- With >1 earn_ratio card in a portfolio, only the one that actually holds the
  housing spend is steered (the other has no denominator). A user won't hold two.
- Second-order cap-refill effects of moved dollars are treated as negligible — the
  same documented-heuristic footing as the greedy assignment itself.

## Data
The three Bilt Card 2.0 tiers (`data/cards/cardless/bilt-{blue,obsidian,palladium}.yaml`)
carry the housing `earn_ratio` block above. Confidence stays `low` (AI drafts, need
human verification). The "Flexible Bilt Cash" 4% option is still unmodeled (flagged
in the card notes).

## Tests
`tests/test_optimizer.py::TestEarnRatioHousing` (standalone top tier, sub-25% floor,
multi-card steering to the best tier, unreachable-tier-stays-floored) plus the v1.5
`TestExplicitOnlyHousing` cases. Fixture registry carries `housing`; tests synth an
earn_ratio card on the ungated `amex_mr` program (cpp 1.25) — no new fixture files.

## Not built
The "Flexible Bilt Cash" 4%-everyday alternative option; per-cycle (vs annual)
ratio timing; steering across two simultaneous earn_ratio cards.
