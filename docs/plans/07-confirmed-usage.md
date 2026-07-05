# Plan 07 — Confirmed usage: credits, portals, and program loyalty

## Why

The value model assumed everyone captures credits: every credit was worth
face × a period haircut, uncategorized statement credits were worth **full
face**, and `optimistic_cpp` applied to any points card regardless of whether
the user has any attachment to the program. Real behavior says otherwise — a
DoorDash credit is worthless to someone who never orders delivery, a Delta
Stays credit is worthless to someone who flies United, and 5x "through the
issuer portal" is worthless to someone who books direct. The result was
coupon-book premium cards and niche co-brand/portal cards ranking above what a
given user would actually realize.

The fix: **no credit counts unless the user confirmed they already use (or
will use) the underlying service**, and **optimistic point value requires
confirmed loyalty to the program's brand**. Confirmation is collected by a
grouped questionnaire: ~10 sections, each a "do you or will you use these"
prompt over its always-visible options — every option on screen (a prompt
like "are you a regular customer of these brands" only makes sense when the
brands are shown), kept scannable by compact per-section chip rows.

## What users can say

`user.confirmed_usage` in the spend profile (or `--confirm` on the CLI) is a
list (default `[]`) of item keys from `data/meta/usage-questions.yaml`:

```yaml
user:
  confirmed_usage: [chase_travel, doordash, delta, global_entry_tsa]
```

One flat list, three effects:

- **service keys** (doordash, resy, oura, …) unlock the credits carrying that
  key in `usage_keys`;
- **portal keys** (chase_travel, amex_travel, …) unlock `portal_only` earn
  rates on cards whose `portal` matches (still discounted by
  `PORTAL_RATE_MULT`);
- **brand keys** (delta, hilton, …) unlock `optimistic_cpp` for lock-in
  currencies via `loyalty_keys`, and unlock brand-locked credits (free-night
  certs, companion certificates, in-flight credits).

`user.uses_travel_portal` is removed (clean break, pre-release); profiles
still carrying it get a targeted migration error.

## Where the knowledge lives

- **`data/meta/usage-questions.yaml`** (new registry): the questionnaire —
  groups (label + "do you or will you use these" prompt) → always-visible
  items (key + label). Single source of truth
  for the UI, profile validation, and the vocabulary of the three fields
  below. Every item key must exist in `statement-descriptors.yaml` (the
  descriptor registry stays the statement-parsing ground truth), and every
  item must be referenced by at least one card credit, card portal, or program
  — both directions validator-enforced, so the question count stays minimal.
- **`credits[].usage_keys`** (card files): anyOf list of item keys gating the
  credit. `credits[].automatic: true` marks genuinely automatic credits
  (anniversary points/cash) that need no gate. New invariant: every credit
  carries at least one of `category` / `usage_keys` / `automatic`.
- **card-level `portal`**: which portal the card's `portal_only` lines book
  through. Card-level, not issuer-level — Citi AAdvantage cards use
  `aadvantage_hotels`, not `citi_travel`.
- **`loyalty_keys`** in `data/meta/point-valuations.yaml`: on every program
  with no cashback redemption path — whose confirmation unlocks
  `optimistic_cpp`. Cashback-path programs never carry it.

## Value model

- **Credit gate order**: `expires` → usage gate → `unlock_spend_usd` →
  valuation. Unconfirmed `usage_keys` → $0 with an explicit reason
  ("requires confirmed use of one of: …").
- **Two capture tables**: confirmed credits use the softer
  `CONFIRMED_CREDIT_CAPTURE` (monthly 0.8 … annual+ 0.95) — the "do they use
  it at all" risk is answered, the residual haircut covers breakage. Credits
  without `usage_keys` (generic category-gated) keep the conservative
  `CREDIT_CAPTURE` (monthly 0.5 … annual 0.9).
- **Full face value** is now reserved for `automatic` credits (no keys, no
  category). A confirmed uncategorized merchant coupon (Oura, StubHub,
  Walmart+) gets face × capture — it's a coupon, not cash.
- **Both gates stack**: a `usage_keys` credit with a `category` still draws
  from the shared remaining-spend tracker (confirmed Uber Cash with no
  transit spend is still $0).
- **Loyalty-aware cpp**: in optimistic mode a lock-in currency is valued at
  `floor_cpp` unless `loyalty_keys ∩ confirmed_usage` — keep-but-devalue, not
  exclude. `filter_cards` is untouched; the card can still win on raw earn.
  Surfaced as a per-card `valuation_note`. Floor mode and cashback-path
  currencies are unaffected.
- **Portal earn**: `portal_only` lines are dropped unless the card's `portal`
  key is confirmed; when confirmed, `PORTAL_RATE_MULT` still applies.

## Validator

- Registry integrity: labels/prompts/items present, item keys globally unique
  and ⊆ statement-descriptors.
- Per credit (error): at least one of `category`/`usage_keys`/`automatic`;
  `automatic` combined with either is an error; unknown keys are errors.
- Honesty nudge (warning): a monthly/quarterly USD statement credit that is
  category-only — short-cycle coupons are almost always merchant-specific.
- Portal (error): `portal_only` line without card `portal`; unknown portal
  key. Warning: `portal` with no `portal_only` line.
- Programs (error): non-cashback program without `loyalty_keys`; cashback
  program with them; unknown keys.
- Minimality (warning): registry item referenced by nothing.

## Output & UI

- Bundle gains `confirmed_usage` (echoed in the text header), per-card
  `valuation_note` for devalued currencies, and `CONFIRMED_CREDIT_CAPTURE`
  in `policy_constants`. Every $0 credit says exactly which confirmation
  would unlock it.
- The POC UI (`tools/test-ui.html`) renders the questionnaire from
  `GET /usage-questions` (served by `tools/test-server.py` straight from the
  registry): one section per group — the prompt above a wrapped row of
  checkbox chips, every option visible upfront; single-item groups render as
  one chip labeled by the prompt. Checked keys → `user.confirmed_usage`.

## Addendum: transfer-gateway gating (portfolio-aware cpp)

Found post-ship: Freedom Flex — marketed as cash back but curated as
`chase_ur` points — was valued at 2.0cpp in optimistic mode even standalone,
though its points only reach transfer partners when pooled into a Sapphire.
Same pattern: Citi TYP on non-premium cards (Double Cash, Strata,
AT&T Points Plus) and WF Rewards outside Autograph Journey.

Fix, following the same "no unconfirmed upside" philosophy but keyed to the
**portfolio** rather than the questionnaire (the gateway is a card you hold,
not a behavior to confirm):

- `transfer_gateway_required: true` on the affected programs in
  `point-valuations.yaml` (chase_ur, citi_typ, wells_fargo_rewards). Natively
  transferable currencies (amex_mr, capital_one_miles, bilt_points) are not
  flagged.
- `unlocks_transfers: true` on the gateway cards (Sapphire Preferred/Reserve,
  Strata Premier/Elite, Autograph Journey).
- `effective_cpp` grants `optimistic_cpp` to a gated currency only when the
  **scored portfolio** contains a gateway for it (a gateway qualifies by
  itself); otherwise floor, with a `valuation_note`. So standalone Freedom
  Flex prices as pure 1cpp cash back, while Freedom Flex + Sapphire Preferred
  — the canonical pairing this product exists to find — prices at 2.0cpp.
- Dominance pruning safety: a card whose cpp is portfolio-dependent is never
  pruned (its standalone floor understates its paired value); dominators keep
  their standalone (minimum) rates, which is conservative; pruning bails out
  entirely if a `first_year_match` card were ever context-dependent.
- Validator: `unlocks_transfers` only on gateway-gated programs (error); a
  gateway-gated program with cards but no gateway card in the dataset warns
  (optimistic_cpp unreachable).

## Addendum 2: brand-lock-in preference

Confirming you fly Delta (`confirmed_usage`) is a behavior; being *willing*
to hold a card whose rewards only redeem with Delta is a preference — some
frequent Delta flyers still want rewards they can always take as cash. New
`user.accepts_brand_lockin` (default **false**): unless opted in,
`filter_cards` excludes every card whose currency has no cashback redemption
path (the `loyalty_keys` programs — airline miles, hotel points, store
credit), with an explicit reason. Opting in restores keep-but-devalue: the
card competes, at floor cpp until brand loyalty is confirmed.

The POC UI asks this as a yes/no ("Are you OK being restricted to a single
company to maximize point output?", default no) and no longer offers a
"total value" reward-preference option — checking all three kinds (the UI
default) is the everything-run; `total_value` remains only as the engine's
profile-level default for CLI backward compatibility.

## Determinism

Confirmation is data: same profile + registries ⇒ same gates, byte-identical
output. `confirmed_usage` is stored sorted; notes are pure functions of
inputs. With `confirmed_usage: []` most merchant credits are $0 and lock-in
currencies floor — that is the intended honest default, and each affected
line carries its reason string.
