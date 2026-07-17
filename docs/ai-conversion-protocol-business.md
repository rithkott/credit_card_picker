# AI Conversion Protocol — Business Addendum (plan 22B)

Mandatory addendum to `docs/ai-conversion-protocol.md` for drafting
`data/business/cards/<issuer>/<card-id>.yaml`. The base protocol assumed a
`data/offer_files/` terms sheet; the business corpus mostly has none, so the
source hierarchy changes — everything else (never invent, transcribed vs
inferred, cap math double-checks, category-mapping honesty, confidence
ceilings) applies unchanged.

## Source hierarchy (replaces base Step 0/5)

1. **Issuer page fetched live this session** → facts it states may reach
   `confidence: medium` for the file when ALL core blocks were checked there.
2. **Reputable secondary fetched live this session** (NerdWallet/TPG/Bankrate
   review pages) → `low` ceiling; note "verified against <site> <date>" on the
   specific figures checked.
3. **Plan 21 research claims** (`~/.claude/plans/business-research-claims.jsonl`
   — verbatim quotes captured 2026-07-16 with source URLs) → treat like an
   offer file WITH a NEEDS_VERIFICATION marker: `confidence: low`, every
   sources note repeats that figures are unconfirmed.
4. **Memory** → allowed only for well-known structure (a card is $0-fee flat
   1.5%), always labeled "drafted from memory — NEEDS human verification".

Every `sources[].url` must be a page someone (AI counts) actually read —
research-claim URLs qualify (they were fetched in the plan 21 pass); say which
pass read them in the note.

## Business-specific rules

- **Combined caps**: when the issuer says "combined" across categories, the
  entries MUST share a `shared_cap_id` pool — modeling combined caps as
  independent per-category caps overstates the card (the #1 business-card
  drafting error). Each entry states the full pool.
- **Flat-rate-capped cards** (Blue Business Plus/Cash "2x/2% on the first
  $50k, then 1x"): use `base_rate` = the elevated rate + `base_rate_cap`
  (period/max_spend_usd/fallback_rate) — never 16 identical category lines.
- **`business_approval` is always inferred** unless the issuer states
  thresholds (Brex/Ramp publish theirs; banks don't). PG cards: entity_types
  almost always `[sole_prop, llc, corp]`. No-PG cards must carry the
  underwriting anchor the issuer publishes (cash balance / revenue / funding).
- **`pricing.model` classification**: an issuer card with a $/yr fee is
  `annual_fee` even when $0. `per_seat` is ONLY for SaaS-priced fintech
  programs, requires `free_tier: true` in V1, and the paid tier goes in
  `per_seat_monthly_usd` + `platform_fee_note` (disclosure, unscored).
- **Employee-card fee** (`employee_cards.fee_usd`) is a required judgment:
  $0 unless the issuer charges per employee card (Amex Gold $95 / Platinum
  $400). When a $0 expense-card variant exists alongside a paid one, set
  `free_expense_card_variant: true` and note the tradeoff.
- **Payment-frequency-conditional rates** (BILL Divvy's 7x-at-weekly): the
  schema has no conditional-rate block — record the rate tier the issuer
  headlines, and state the condition + the lower tiers in the reward `notes`
  and card `notes`. Never silently record "up to" marketing rates
  (base-protocol bundled-earn rule applies).
- **`payment_type`**: `charge` for pay-in-full products even when an optional
  financing bolt-on exists (Pay Over Time, Flex for Business) — note the
  bolt-on. `revolving` only when carrying a balance is the product's normal
  operation.
- **Pooling breaks**: any UR/MR-denominated card whose points can't combine
  with the program's other cards MUST carry `pooling.program_combinable: false`
  (Ink Premier) — otherwise the optimizer grants it gateway upside it can't
  reach.
- **Category mapping quirks** (record imperfect fits in reward `notes`):
  Amex "electronic goods retailers + software & cloud" → `software_saas`;
  "wireless phone service" and "internet/cable/phone" → `telecom`; gas/EV →
  `fuel_fleet`; "construction material & hardware suppliers" →
  `contractors_materials`; transaction-size limits on a category ("gas, on
  transactions of $200 or less") are a note, not a schema field.
- **Issuer rules**: a new issuer directory requires an `issuer-rules.yaml`
  entry in the same change (empty `{}` is valid); 5/24 / Amex-limit /
  velocity facts belong in the registry, not per-card notes (per-card
  `business_approval.notes` may summarize).
- **Backlog**: flip the card's row in `docs/business-card-backlog.md` to
  `drafted` in the same change.
