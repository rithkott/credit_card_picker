# Plan 06 — Reward-kind preferences (implemented)

## Why

The project's direction shifted away from squeezing maximum point value out of
every niche card for edge-case spenders. Users think in terms of *what they
want back* — flights, hotels, plain cash — not cents-per-point tables. The
optimizer should let them say so and stop recommending cards whose currency
can't serve that goal, while keeping the default behavior (pure total-value
maximization) untouched.

## What users can say

`user.reward_preferences` in the spend profile (or `--rewards` on the CLI) is a
non-empty list, any combination of:

- `flights`
- `hotels`
- `cashback`
- `total_value` — "just maximize net value"; disables the filter. Default.

Multiple concrete kinds are a union: `[flights, hotels]` keeps any card whose
currency serves *either*. Including `total_value` anywhere disables filtering.

## Where the knowledge lives

Per project convention, the cross-card assumption lives in a `data/meta/`
registry, not in card files: every program in `data/meta/point-valuations.yaml`
now carries `redeems_for`, a (possibly empty) subset of
`[cashback, flights, hotels]`.

Classification rule (documented in the registry header):

- `cashback` — the program has a cash / statement-credit / deposit path.
- `flights` / `hotels` — the currency is an airline/hotel currency, or has a
  flight/hotel redemption path (transfer partners, travel eraser, portal boost)
  whose cpp **beats its own cash-out cpp**. Fixed-value 1cpp-everywhere bank
  points are cashback only — redeeming them for travel adds nothing over cash.
- `[]` — merchant-restricted currencies (store credit, cruise/theme-park
  dollars); they match only a `total_value` run.

Consequences: transferable bank currencies (Chase UR, Amex MR, Citi TYP,
Capital One miles, Wells Fargo Rewards, Bilt) match all three kinds; airline
programs match `flights`; hotel programs match `hotels`; Luxury Card points
match `cashback, flights` (2cpp airfare portal).

## Mechanics

- `filter_cards()` applies the preference filter alongside the approval-tier
  filter, before choice expansion / pruning / search. Excluded cards surface in
  the output's `excluded` list with an explicit reason — never a silent drop.
- Valuation math is untouched: this is a candidate filter, not a re-weighting.
  Within the surviving set the optimizer still maximizes net value in the
  chosen `valuation_mode`. (A per-kind cpp re-valuation is the possible future
  upgrade if filtering proves too blunt.)
- `scripts/validate_cards.py` errors on any program missing a valid
  `redeems_for` list.
- Output bundle gains `reward_preferences`; the text header echoes it.
- The spend-entry form (plan 03) should expose this as a multi-select chip row
  when built; `tools/card-entry-form.html` is unaffected (program keys
  unchanged).

## Determinism

The classification is data, not runtime judgment: same registry + profile ⇒
same eligible set, byte-identical output. All existing golden tests are
unchanged (default `[total_value]` keeps the old behavior exactly).
