# Plan 20 — Compare portfolios (fourth journey path)

## Context

The site offers three journey paths (generate / analyze / improve, chosen on the start
page since v2.3.0). This plan adds a fourth: **Compare portfolios** — the user
hand-builds 2–4 sets of cards and sees them scored against their entered spending,
stacked vertically, with the best set highlighted.

User-confirmed UX decisions:
- Each portfolio shows its receipt (net ongoing/year1, rewards/credits/fees/bonuses)
  stacked vertically; per-card math tiles sit behind a collapsed disclosure.
- Starts at 2 portfolios; "+ Add portfolio" up to 4; removable back down to 2.

## Approach

Frontend-only. The backend already scores a fixed card set: `POST /api/evaluate` →
`opt.evaluate` (scripts/optimize.py) returns a full `OptimizeBundle` whose
`best_by_size` has exactly one entry. Compare = N parallel `/api/evaluate` calls
(one per portfolio), stitched client-side.

No `/api/*` contract change ⇒ `tests/test_server_api.py`, API response types, and
`docs/architecture.md` are untouched (the diagram's trigger list does not include
frontend views).

## 1. State & persistence

`site/src/hooks/useFormState.ts`
- `Mode` union gains `'compare'`.
- New state `comparePortfolios: string[][]` (arrays, not Sets: JSON round-trip,
  stable pick order), default `[[], []]`. Restored from the persisted blob; included
  in the save effect and `reset()`.
- Portfolio names are auto-derived ("Portfolio 1..4") from index — never stored.

`site/src/lib/persistence.ts`
- `PersistedForm.mode` union + `coerceMode` whitelist gain `'compare'`.
- New field `comparePortfolios: string[][]` with `coercePortfolios(v)`:
  non-array → `[[], []]`; per entry keep string ids, dedupe, cap at 4 entries,
  pad to ≥2. A pre-feature blob missing the key coerces to the default —
  no version bump (same precedent as `coerceExtras`).

## 2. Entry points

- `StartPage.tsx`: 4th `OPTIONS` keycap — title "Compare card portfolios",
  subtitle "Build two to four sets of cards and see which one wins for your spending."
- `global.css`: `.start-options` grid 3 → 2 columns (2×2 XL keycaps; 4-across is
  too skinny and 3+1 orphans). The mobile 1-column rule is unchanged.
- `Home.tsx` `modeToggle`: 4th tab `['compare', 'Compare card portfolios',
  'Hand-pick a few sets and see them scored side by side.']`; `.mode-toggle`
  grid 3 → 4 columns (fallback 2×2 if cramped on preview).

## 3. Picker — new `site/src/components/ComparePicker.tsx`

One shared card catalog with an active-portfolio tab strip (NOT 2–4 stacked
ManualGrids — each is a 100+ tile catalog):
- `.compare-tabs` tablist: `.compare-tab` per portfolio (label + card-count badge +
  remove ✕ shown only when length > 2), trailing "+ Add portfolio" (hidden at 4).
  Active tab index is local component state (in-session only, like the wizard step).
- `.compare-chips`: every portfolio's picks always visible as pills (card name + ✕),
  or an empty hint — all portfolios stay visible while editing one.
- Catalog reuses `ManualGrid` unchanged (fully controlled):
  `selected={new Set(portfolios[active])}`, `onToggle` routed to the active
  portfolio, existing `excluded`/`onToggleExclude` passed through.
- Card-name lookup for chips: `getCardsCached()` module-level promise cache added to
  `site/src/api.ts`; ManualGrid switches to it (avoids a duplicate /api/cards fetch).

Home handlers: `toggleCompareCard(pIdx, id)`, `addComparePortfolio` (<4),
`removeComparePortfolio` (>2). `toggleExclude` also purges the id from every compare
portfolio (mirrors the existing purge from `selected`). Duplicate/overlapping
portfolios are allowed — independent evaluations are legitimately useful
(e.g. same set with/without a premium card).

## 4. Run wiring — `Home.tsx`

New `RunPhase` variant (keeps the existing `done` narrowing untouched):

```ts
type CompareOutcome =
  | { ok: true; bundle: OptimizeBundle }
  | { ok: false; detail: string; unreachable: boolean }
type CompareEntry = { label: string; cards: string[]; outcome: CompareOutcome }
// added to RunPhase:
| { phase: 'done-compare'; entries: CompareEntry[] }
```

`entries` snapshot labels + card lists at run time so later picker edits cannot
desync rendered results.

`onRunCompare`: one `buildProfile(spend, user, unit, excluded)` — `exclude_cards`
is still sent, exactly like analyze (the server's `evaluate()` never applies the
veto; the UI prevents conflicts via the exclude purge). `Promise.all` over
`comparePortfolios.map(cards => evaluateManual(profile, cards))` with a
per-portfolio catch: one failed evaluation renders as an inline error panel while
the others show normally. All-failed-and-unreachable collapses to the existing
`error` phase (ServerBanner).

Mode wiring: `needsCards = analyze | improve`; `compareReady = every portfolio
non-empty`; run label `Compare portfolios (N)`; running status
`scoring N portfolios — Xs`; runbar disabled + idle hint
("Every portfolio needs at least one card."); `canFinish` gains the compare branch;
the autoscroll effect also fires on `done-compare`. Review step renders
`ComparePicker` when mode is compare and `CompareResults` when `done-compare`.

## 5. Results — new `site/src/components/results/CompareResults.tsx`

- Winner: among ok entries, max of `bundle.best_by_size[0]` net on
  `optimize_for === 'ongoing' ? ongoing_net : year1_net`; first max wins ties.
- `RunHeader` once at top (from the first ok bundle); `PolicyConstants` disclosure
  once at bottom. `ExcludedPruned` skipped — evaluate returns empty lists.
- Per entry, stacked `section.block.compare-result` (`.winner` on best):
  header row (eyebrow "PORTFOLIO N", card names joined " + ", mono net, BEST tag),
  the reused `PortfolioCard` receipt, then a native `<details class="disclosure">`
  "Per-card math" (same pattern as PolicyConstants) containing the tile grid.
- Error entry: `.compare-error` panel with the label, its cards, and the server
  detail verbatim.
- Extract `ResultTiles.tsx`: the rows-of-≤3 subgrid tile renderer lifted from
  `ResultsView.tsx` (the `--cols`/`--tiles` inline vars + `CardDetail` mapping)
  into a shared component; ResultsView switches to it (behavior-identical) and
  CompareResults reuses it inside each disclosure.
- Worst-case toggle: skipped in v1 (needs per-entry state) — noted follow-up.

## 6. CSS — `global.css`

Paired-shadow conventions throughout: `.compare-tabs` inset track with raised
active tab (mirrors `.mode-toggle`); `.compare-add` ghost button; `.compare-chip`
raised pill with ✕; `.compare-result.winner` accent ring
(`box-shadow: var(--raised), 0 0 0 2px var(--accent)`); `.compare-result-head`
flex + eyebrow; `.compare-error` in `--neg`; nested receipt flattened
(`.compare-result .receipt { box-shadow: none }`). Plus the two grid-column
changes from §2.

## 7. Tests

`site/src/lib/lib.test.ts` (vitest): `coerceMode('compare')`; a v1 blob without
`comparePortfolios` still loads with `[[], []]`; malformed portfolios (non-array,
>4 entries, non-string members, dupes) coerce to a valid 2–4 shape; save→load
round-trip preserves portfolios. Server tests untouched.

## 8. Verification

Local click-through (server + vite dev), then Vercel preview QA including mobile
widths; `npm run test`, `npm run lint`, `npm run build`. Ship per the standard
workflow with a `[minor]` merge (new user-facing journey path).
