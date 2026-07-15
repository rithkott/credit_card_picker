# Plan 19 — Neuter rotating so it never splits a category across cards

## Problem

Steering rule (product): **the same category must never be suggested on two
cards** — a user won't split a category perfectly in real life. Only whole
categories (or individually broken-out stores like Uber/Costco) get steered.
The one allowed exception is a hard earning/point cap (e.g. Amex 50k restaurant
spend), where spill onto a second card is unavoidable and real.

Audit result: across the live 115-card dataset, **the only** categories the
optimizer ever splits across two cards without a cap are the two rotating
Discover it cards (`discover/it-cash-back`, `discover/it-student-cash-back`).
Every non-rotating card already assigns each category wholly to one card
(greedy assignment, uncapped line → whole bucket to the single best rate).

Root cause: `build_lines` models a rotating reward as **two** lines —

1. a `rotating` line capped to `1/N` of each eligible bucket (the
   featured-quarter share, `eligible_fraction`), and
2. a `fallback` line at the base rate for the rest —

so the non-featured `(N-1)/N` of the bucket is free to land on a *different*
card whose category rate beats the rotating card's fallback. That is the split
(e.g. groceries `1/6` on `it-cash-back` + `5/6` on `strata-premier`).

## Decision

Keep the Discover cards. **Neuter rotating in the engine**: a rotating reward
competes for the **whole** category at a realistic blended annual rate, and the
whole category is assigned to one card.

Blended rate (per rotating-eligible bucket, in the card's own currency):

```
blended = fraction * bonus_rate + (1 - fraction) * fallback_rate
fraction = 1 / len(ROTATING_ELIGIBLE)   # ~1/6, featured-quarter coverage
```

- Activated: `(1/6)*5 + (5/6)*1 = 10/6 ≈ 1.667%` for a 5%/1% card.
- Not activated: `bonus_rate → fallback_rate`, so `blended = fallback_rate` (1%).

Emitted as a single **`category`-kind, uncapped** line over the rotating-eligible
buckets. In greedy assignment it competes whole-bucket against every other card's
category line; whichever wins takes the entire category. No `rotating`/`fallback`
line pair, no `eligible_fraction`, so nothing can spill to a second card.

### Known simplification (documented, accepted)

The quarterly spend cap (`$1,500/qtr = $6,000/yr` bonus spend) is **dropped** in
the blended line. Honoring the cap would require a `room` limit, which reintroduces
a split (remainder spills to another card) — directly violating the rule. The cap
only ever binds at absurd single-category spend (> ~$36k/yr in one rotating
category); below that the blend is exact. Overvalue is bounded and only affects
unrealistic profiles. Rotating is a deprecated archetype, so this tradeoff is
accepted rather than modeled.

## Changes

- `scripts/optimize.py` — `build_lines` rotating branch: emit one blended
  `category` line instead of the `rotating` + `fallback` pair. Update the
  `ROTATING_ELIGIBLE` / rotating-model comments. `eligible_fraction` handling in
  `assign_spend` becomes legacy/no-longer-emitted (left inert, harmless).
- `tests/test_optimizer.py` — rewrite `test_freedom_flex_rotating_activated`,
  `test_freedom_flex_rotating_not_activated` (unchanged result, new mechanism),
  `test_freedom_flex_rotating_cap_binds` (cap no longer binds → blended whole
  category). Add an assertion that no category is split across two cards in a
  multi-card portfolio that includes a rotating card.
- `docs/architecture.md` — value-model note: rotating is a single blended
  whole-category line (no featured-quarter split).

Frontend (`AssignmentsTable`, `CardDetail`) already guards on
`a.eligible_fraction ?` — with the field now always absent, the "1⁄6" label
simply stops rendering (correct: nothing is diluted anymore). No type/contract
change; `activates_rotating` stays (the blended rate still reads it).

## Verify

- `python3 scripts/validate_cards.py` clean.
- `python3 -m unittest discover tests` green.
- Re-run the example profile: no category appears on two cards (except a hard
  cap). Preview deploy, then ship as **v2.5.0** (optimizer value-model change).
