# Card Data Curation Guide

How to write, verify, and review a card file in `data/cards/`. This is the human-facing companion to the machine-enforced schema at `data/schema/card.schema.json`.

**The one rule that matters most:** this dataset only works if every number in it is *confirmed against issuer terms*, not remembered, guessed, or copied from a blog's "best cards" list. If you can't cite where a number came from, mark the card `confidence: low` — the pipeline is built to surface unverified data, not hide it.

---

## Workflow for adding or updating a card

0. **If you're an AI converting a `data/offer_files/<issuer>/<slug>.txt` terms sheet into YAML**,
   stop and follow [`docs/ai-conversion-protocol.md`](ai-conversion-protocol.md) first — it's a
   stricter, mandatory checklist that gates entry into the workflow below, because transcribing
   a transcription is exactly where silent errors compound.
1. **Create the file** at `data/cards/<issuer>/<card-id>.yaml`. The `issuer` field must match the directory name and `id` must match the filename — the validator enforces both. Slugs are lowercase with hyphens (`blue-cash-preferred`, not `BlueCashPreferred`).
2. **Copy the template** at the bottom of this guide and fill it in, reading the field reference below for anything ambiguous.
3. **Verify every number** against the issuer's own page (rates, caps, fees, credits, bonus). Put the URLs in `verification.source_urls` and set `confidence` honestly (see [Verification standards](#verification-standards)).
4. **Run the validator:**
   ```sh
   pip install pyyaml jsonschema
   python3 scripts/validate_cards.py
   ```
   Fix every `ERROR`. Warnings about staleness/low confidence are informational.
5. **Use YAML comments liberally** for "why" notes that don't fit a field — e.g. `# capped at $6k, source: issuer footnote 3`. Comments are for reviewers; `notes` fields are data the app may display.

---

## How rates work (read this first)

A `rate` is **earn-units per dollar of spend**, and what a unit is worth depends on `currency`:

- **Cash card** (`currency.type: cash`, `program: cash`): `rate: 2` means 2% cash back. A unit is one cent.
- **Points card** (`currency.type: points`): `rate: 3` means 3 points per dollar. Points convert to dollars via the program's entry in `data/meta/point-valuations.yaml`, which has two modes — `floor_cpp` (guaranteed cash-out value) and `optimistic_cpp` (realistic transfer-partner value). Cards never embed their own point valuations; that's a single global assumption the user can see and change.

When spend matches multiple rewards, **merchant beats category beats `base_rate`**. So a card's rewards should be written as exceptions layered over `base_rate`, not as an exhaustive list.

---

## Field reference

### Identity

| Field | What to put there |
|---|---|
| `id` | Slug, must equal the filename without `.yaml` |
| `name` | Official product name as the issuer writes it (no "card" suffix needed) |
| `issuer` | Slug, must equal the parent directory (`amex`, `chase`, `capital-one`, …) |
| `network` | `visa`, `mastercard`, `amex`, or `discover` |
| `currency` | `type` (`cash`/`points`) + `program` (a key in `data/meta/point-valuations.yaml`; cash cards must use `cash`) |
| `base_rate` | The catch-all rate for spend no category/merchant reward matches |

### `category_rewards` — spend-proportional rewards

One entry per elevated rate. `category` must be a key in `data/meta/categories.yaml`.

- **`cap`** — use whenever the issuer limits the elevated rate: `period` (`monthly`/`quarterly`/`annual`), `max_spend_usd` (the *spend* ceiling, not the reward ceiling — if the issuer says "up to $300 cash back at 6%", that's `max_spend_usd: 5000`), and `fallback_rate` (what spend above the cap earns, usually the base rate).
- **`rotation`** — only for rotating-category cards (Freedom Flex, Discover it). Use the pseudo-category `rotating`, plus `frequency`, `requires_activation`, and a `note` describing typical categories. Never write this quarter's specific categories as if they were permanent — they'll be wrong in three months.
- **`choice`** — only for choose-your-own-category cards (Citi Custom Cash, BofA Customized Cash), including automatic top-category cards, which are equivalent for optimization. Use the pseudo-category `choice`, plus `options` (≥ 2 real category keys the cardholder can select) and a `note` on how selection works. If the issuer lists a selectable category we have no registry key for, omit it and say so in the note rather than inventing a key. The optimizer expands the card into one variant per option and picks the best per portfolio.
- **`portal_only: true`** — when the rate applies only to purchases made through the issuer's own travel portal (e.g. "5x on travel purchased through Chase Travel"). This matters: portal prices often exceed direct booking, so the optimizer treats these differently from unconditional rates.
- **Category fine print goes in `notes`**: "US supermarkets only", "excludes Walmart/Target", "online groceries only". If the issuer's definition of a category is narrower than ours, say so — the optimizer can't read the fine print, but the user can.

**Choosing a category:** map to the *issuer's* definition, closest canonical key wins. If no key fits, don't improvise — add a category (see [Extending the registries](#extending-the-registries)).

### `merchant_rewards` — merchant-keyed rewards

Same shape as category rewards, but keyed by a `merchant` from `data/meta/merchants.yaml`. Use only when the issuer names a specific merchant ("5% at Amazon"), not for category-wide rates. Merchant rewards beat category rewards when both match.

### `credits` — fixed-value periodic perks

Credits are **use-it-or-lose-it fixed amounts, not scaled by spend** — never model them as a reward rate.

- `amount_usd` is the face value *per period* ($10/month, not $120/year — the period field carries the frequency).
- **`realistic_capture_rate_note` is required and is the most important field in the block.** Issuers price annual fees against sticker credit value knowing most users capture a fraction. Say honestly who captures it and who doesn't: enrollment requirements, restricted partner lists, portal-only redemption, monthly-forfeit mechanics. "Easy for regular Uber users, worthless otherwise" is a good note; "credit for Uber" is not.
- Non-monetary automatic perks with clear cash value (e.g. anniversary bonus miles) may be modeled as an annual credit with a note explaining the valuation.

### `signup_bonus` — one-time, year-one only

`value` is exactly one of `points` or `usd`, plus `spend_requirement_usd` and `window_months`. Bonuses change constantly — record the current *public* offer only (no targeted/referral offers), and expect this field to go stale first. If there's no public bonus, use `signup_bonus: null`.

**Limited-time elevated offers** matter enormously for year-one value, so track them explicitly:

- `limited_time: true` — when the current offer is an elevated promotion above the card's standard bonus. Put the standard bonus in `notes` (e.g. "standard offer is 60k") so reviewers can see what it reverts to.
- `expires: "2026-09-30"` — the last day the offer is available, when the issuer announces one. Omit for evergreen offers with no stated end date. The validator warns once this date passes, so expired promos get re-checked instead of silently inflating recommendations.

When verifying a limited-time offer, the issuer's application page is the only source that counts — blog roundups of elevated offers are frequently out of date.

### `fees`

`annual_fee_usd`, optional `first_year_waived: true` (only when the issuer explicitly waives/intro-$0s the first year), and `foreign_transaction_pct` (`0` if none).

### `approval` — who can actually get this card

Required, because the optimizer must never recommend a card the user can't get approved for.

- `credit_tier` (required): `building` (secured/credit-builder cards that accept thin or damaged files) | `fair` (~580+) | `good` (~670+) | `very_good` (~740+) | `excellent` (~800+ or premium-card underwriting).
- `estimated_min_score` (optional): a finer FICO estimate when sources support one.
- `notes`: issuer-specific approval rules — Chase 5/24, Amex once-per-lifetime bonuses, security-deposit requirements, banking-relationship requirements.

Issuers don't publish score cutoffs, so **these are estimates by design** — use the issuer's own "recommended credit" marketing plus reputable approval-odds data, and explain your reasoning in `notes` when it isn't obvious. An estimate is fine; a guess presented as fact is not.

### `closed_loop` — store cards usable only at specific merchants

Omit this block entirely for normal (open-loop) cards. For store cards (Target Circle Card, Amazon Store Card):

- `merchants`: the canonical merchant key(s) where the card works at all. The optimizer will only ever assign those merchants' spend to this card — it can still be worth recommending when a big share of someone's spend is at that merchant.
- The card's earn rate at its merchant goes in `base_rate` (or `merchant_rewards` if rates differ across its merchants); `closed_loop` expresses the *restriction*, not the reward.

### `benefit_flags`

Snake-case binary attributes (`primary_rental_insurance`, `lounge_access`, `cell_phone_protection`). Not scored by the optimizer in v1 — list what's notable, don't exhaustively catalog. There is no registry for flags yet; reuse existing spellings (grep other cards) before inventing new ones.

### `sources` — where every fact came from

**Paste the exact link at the moment you put a fact into the file** — whether you're a human or an AI. Don't reconstruct sources afterward from memory; the whole point is that any number in the file can be traced to a URL someone actually read.

| Field | Meaning |
|---|---|
| `url` | The exact page (`https://` only) — deep-link to the pricing/terms page, not the issuer homepage. Issuer pages are primary; blog posts are secondary corroboration only. |
| `supports` | Which schema blocks this link backs: `identity`, `currency`, `base_rate`, `category_rewards`, `merchant_rewards`, `credits`, `signup_bonus`, `fees`, `approval`, `closed_loop`, `benefit_flags`. Be honest and specific — a source that only shows the annual fee supports `fees`, not everything. |
| `accessed` | The date the link was actually read. |
| `added_by` | Your name/handle, or the AI model that pasted it. AI-added sources whose URLs weren't actually fetched must say so in `note`. |
| `note` | Pinpoint within the source: "rates table, footnote 3", "terms PDF p.2". Saves the next verifier from re-reading the whole page. |

The validator warns (`UNSOURCED`) when a populated block has no source claiming to support it — every fact needs a paper trail.

### `verification` — how "confirmed dataset" is enforced

| Field | Meaning |
|---|---|
| `last_verified_date` | The date *you actually checked the sources* — never future-dated, never bumped without re-checking. CI warns when it's >6 months old. |
| `verified_by` | Who checked (name/handle). Drafts carry an explicit "NEEDS human verification" marker. |
| `confidence` | See below. |

`sources` records where facts came from; `verification` records the last time a human confirmed the file *as a whole* still matches them. Verifying a card means opening its `sources` URLs and re-checking — if a URL is dead or the page changed, fix the source entry too.

## Verification standards

- **`high`** — every number checked against the issuer's own pages/terms, on the date given. This is the target state for all cards.
- **`medium`** — checked against a reputable secondary source (issuer page unavailable/paywalled), or issuer-verified but more than a quarter ago for volatile fields like signup bonus.
- **`low`** — drafted from memory or unverified sources. Allowed to exist (CI warns but passes) so drafting isn't blocked, but a `low` card should never be treated as done.

When *reviewing* someone else's card: open the source URLs and spot-check the three highest-impact numbers (annual fee, top category rate + its cap, signup bonus). Fine print to check specifically: category exclusions (superstores/warehouse clubs are excluded from "supermarkets" on most cards), whether a rate is portal-only, and whether a cap is on spend or on reward.

## Extending the registries

- **New category** (`data/meta/categories.yaml`): add only when an issuer's bonus category genuinely doesn't map to an existing key. Remember every category (except pseudo-categories) becomes a line in the user's spend-entry form — keep the list short enough that filling it out stays pleasant. Never remove or rename a key without updating every card that uses it (the validator will catch stragglers).
- **New merchant** (`data/meta/merchants.yaml`): add only when a card in `data/cards/` actually references it, and set its `category` mapping so merchant spend routes out of the right bucket.
- **New points program** (`data/meta/point-valuations.yaml`): set `floor_cpp` to the guaranteed cash-out rate and `optimistic_cpp` to a defensible transfer-partner value, with a comment citing your reasoning. Valuations are judgment calls — the comment is the audit trail.

## Common validator errors

| Message | Fix |
|---|---|
| `id '…' does not match filename` | Rename the file or fix `id` |
| `unknown category '…'` | Typo, or the key needs adding to `categories.yaml` |
| `cash card must use program 'cash'` | `currency.type: cash` requires `program: cash` |
| `Additional properties are not allowed` | Field name typo — the schema rejects unknown keys on purpose |
| `last_verified_date … is in the future` | Use the date you actually verified |
| `STALE — last verified …` (warning) | Re-check the card against issuer terms and update the date |

---

## Template

```yaml
# <One-line comment: what archetype this card is / why it's in the dataset.>
id: card-slug                # = filename without .yaml
name: Official Card Name
issuer: issuer-slug          # = parent directory name
network: visa                # visa | mastercard | amex | discover
currency:
  type: points               # cash | points
  program: chase_ur          # key in data/meta/point-valuations.yaml ('cash' for cash cards)
base_rate: 1                 # catch-all rate

category_rewards:
  - category: dining          # key in data/meta/categories.yaml
    rate: 3
    # cap:                    # include when the issuer limits the elevated rate
    #   period: annual        # monthly | quarterly | annual
    #   max_spend_usd: 6000   # SPEND ceiling, not reward ceiling
    #   fallback_rate: 1
    # portal_only: true       # rate only via the issuer's travel portal
    # notes: issuer fine print worth surfacing to the user

merchant_rewards: []          # only for issuer-named merchants, key in data/meta/merchants.yaml

credits: []
# credits:
#   - name: Example credit
#     amount_usd: 10          # face value PER PERIOD
#     period: monthly         # monthly | quarterly | semiannual | annual | every_4_years
#     category: dining        # optional: which spend bucket it offsets
#     realistic_capture_rate_note: >-
#       Required. Who actually captures this and who doesn't (enrollment,
#       partner restrictions, monthly forfeit, portal-only redemption).

signup_bonus:                 # or `signup_bonus: null` if no public offer
  value:
    points: 60000             # exactly one of points / usd
  spend_requirement_usd: 4000
  window_months: 3
  # limited_time: true        # elevated promo above the standard bonus
  # expires: "2026-09-30"     # last day of the offer (omit if evergreen / no stated end)
  # notes: standard offer is 60k; elevated to 75k through the expiry above

fees:
  annual_fee_usd: 95
  # first_year_waived: true
  foreign_transaction_pct: 0

approval:
  credit_tier: good            # building | fair | good | very_good | excellent
  estimated_min_score: 670     # optional FICO estimate
  # notes: issuer-specific rules (Chase 5/24, Amex lifetime bonus, deposit required)

# closed_loop:                 # ONLY for store cards usable solely at specific merchants
#   merchants: [target]        # keys in data/meta/merchants.yaml
#   note: RedCard works only at Target / Target.com

benefit_flags: []             # snake_case, reuse existing spellings from other cards

sources:                      # paste the EXACT link when you add a fact, not after
  - url: https://issuer.com/the-cards-own-page
    supports: [identity, currency, base_rate, category_rewards, fees, approval]
    accessed: "2026-07-03"    # when you actually read it
    added_by: your-name       # or the AI model that pasted it
    # note: rates table, footnote 3
  - url: https://issuer.com/current-offer-page
    supports: [signup_bonus]
    accessed: "2026-07-03"
    added_by: your-name

verification:
  last_verified_date: "2026-07-03"   # the date YOU checked the sources
  verified_by: your-name
  confidence: low             # high | medium | low — see "Verification standards"
```
