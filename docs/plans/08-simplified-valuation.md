# Plan 08 — Single average valuation & best-by-size results

## Why

Two v1 knobs asked users questions they can't meaningfully answer:

- **floor vs optimistic point valuation** — a user doesn't know whether their
  future redemptions will hit the conservative cash floor or the
  transfer-partner ceiling; making them pick a mode just moved an engine
  judgment call onto them, and produced two different answers to "which cards
  should I hold".
- **max cards** — users don't know how many cards they want until they see
  what each additional card is worth.

Plus two form simplifications: rotating-category activation is assumed (the
engine already dilutes rotating lines to the ~1/N featured-quarter coverage), and credit tier
defaults to `good` instead of forcing a selection.

## Value model

`user.valuation_mode` is removed (targeted migration error, like
`uses_travel_portal`). Points are valued at a single **engaged average** per
program:

    avg_cpp = (floor_cpp + optimistic_cpp) / 2

computed by the engine from the unchanged registry (`avg_cpp()` /
`effective_cpp()` in `scripts/optimize.py`; echoed per program in the
bundle's `cpp_table` and as the `CPP_MODEL` policy constant). The plan-07
gates are unchanged and still floor mechanically — they are facts, not modes:

- loyalty-gated currencies (no cashback path) → `floor_cpp` until the brand is
  confirmed in `user.confirmed_usage`;
- `transfer_gateway_required` currencies → `floor_cpp` unless the scored
  portfolio holds an `unlocks_transfers` gateway card.

Cash and fixed-value currencies have floor == optimistic, so the average
changes nothing for them. Dominance pruning treats every gated non-gateway
card as context-dependent (never pruned) since its cpp still varies with
portfolio composition.

## Best-by-size results

The engine still accepts `max_cards` (CLI); the product UI fixes it at 3 and
no longer asks. `run()` adds `best_by_size` to the bundle: the best portfolio
of each exact size 1..max_cards (full per-card detail, same shape as
`portfolios`), derived from the already-ranked search results.
`render_text` prints a "Best by size" line; the ranked `--top` list is
unchanged for the CLI.

The site shows an escalation instead of a ranked list: **best single card
always**, then the best 2-card and 3-card portfolios **only when each beats
the last shown size** on the `optimize_for` metric (with the marginal gain
labeled) — adding a card for $0 gain is noise, and the engine guarantees the
comparison because every size's best is in the bundle.

## Form changes

- Credit tier: defaults to `good` (was a forced "— select —"); validation E4
  remains as a guard but can no longer fire in normal use.
- Removed from the form: point-valuation mode, max cards, "I activate rotating
  5% categories" (sent as `activates_rotating: true`; the engine option
  remains for CLI users).

## Contract changes

- Bundle: `valuation_mode` removed; `best_by_size` added; `cpp_table` entries
  gain `avg_cpp`; `CPP_MODEL` added to `policy_constants`.
- Profile: `user.valuation_mode` → migration error. `--mode` CLI flag removed.
- Sync surfaces updated per CLAUDE.md: `tests/test_server_api.py` (unchanged
  contract tests still pass — golden equivalence recomputes both sides),
  `site/src/types.ts`, `site/src/lib/validation.ts` (E5 unchanged),
  `examples/spend-profile.example.yaml`.
