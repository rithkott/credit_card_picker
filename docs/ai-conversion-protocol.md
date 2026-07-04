# AI Offer-File → YAML Conversion Protocol

Mandatory checklist for an AI converting a `data/offer_files/<issuer>/<slug>.txt` terms sheet
into `data/cards/<issuer>/<slug>.yaml`. This is stricter than the general
[curation guide](curation-guide.md) because the AI here is not looking at the issuer's page
directly — it's transcribing a transcription, one extra step removed from the source of truth,
which is exactly where errors compound silently.

**This protocol does not replace the curation guide — it gates entry into it.** Read
`curation-guide.md`'s field reference and template first; this document only adds the checks
specific to converting from an offer file instead of drafting from scratch.

Follow every numbered step, in order, for every card. Do not skip a step because the card
"looks simple." Skipping steps is exactly how a plausible-looking wrong number gets in.

---

## Step 0 — Read the whole offer file before writing anything

Read the entire `.txt` file first, not just the sections you expect to map to fields. Offer
files carry footnotes, caveats, and "issued by" lines at the bottom that change how a number
should be recorded (e.g., a cap stated as a footnote, a category exclusion mentioned once).

**STOP condition:** if the file contains a `NEEDS_VERIFICATION` marker (check — 30 of the 93
offer files currently have one; see `docs/needs-verification-links.md`), you may still draft the
YAML, but:
- `verification.confidence` **must** be `low` — never `medium` or `high` — regardless of how
  clean the rest of the file looks.
- Every `sources` entry's `note` must repeat that the figures are third-party/unconfirmed.
- Check `docs/needs-verification-links.md` for the official page link and attempt Step 5 (live
  fetch) before drafting, since resolving the marker is more valuable than transcribing around it.

## Step 1 — Never invent a fact the offer file doesn't contain

Every field you fill must trace to a specific line in the `.txt` file, a value you fetched live
in Step 5, or an explicit, honestly-labeled inference (Step 2). If a required schema field
(`network`, `approval.credit_tier`, `fees.foreign_transaction_pct`, etc.) has no source in the
offer file:

- Do not guess a plausible-sounding value silently.
- Either fetch it live (Step 5), or record your best estimate **and say so** in the relevant
  `notes` field (e.g., `approval.notes: "credit_tier estimated from issuer's public positioning
  of this card; not stated in the offer file — NEEDS human verification"`).
- `foreign_transaction_pct` with no explicit "no foreign transaction fee" language anywhere in
  the source is an inference, not a read fact — label it as such if you can't confirm it live.

## Step 2 — Distinguish "transcribed" from "inferred"

Keep a running mental (or scratch-file) distinction as you fill each block:

| | Transcribed | Inferred |
|---|---|---|
| Definition | The offer file states this number/fact directly | You derived or estimated it |
| Confidence ceiling | `low` (offer file), `medium` (if live-fetched in Step 5) | `low`, always |
| Required note | none beyond normal sourcing | must say what was inferred and why, in the field's `notes` |

Common inference traps specific to this dataset:
- **Cap math**: an offer file saying "up to $300 cash back at 6%" requires you to compute
  `max_spend_usd: 5000` (300 / 0.06) yourself — this is arithmetic on a transcribed fact, not
  invention, but double-check the division before writing it (see Step 6).
- **Category mapping**: mapping the offer file's prose ("dining, including takeout and
  delivery") onto a `categories.yaml` key is an interpretation, not a pure transcription — if the
  fit is imperfect, say so in `category_rewards[].notes` per the curation guide, don't silently
  narrow or widen the issuer's definition.
- **`approval.credit_tier`**: offer files almost never state this. It is *always* an inference
  unless you fetch a page that states it — treat it as inferred by default.
- **`kind: in_kind` credit valuations**: the USD value you assign to a free night, companion
  certificate, or lounge-pass allotment is *always* an inference — the issuer never states one.
  Record your valuation reasoning in the credit's `notes` (e.g. "Category 1-4 Hyatt night ≈ $150
  based on the redemption ceiling"), never just the number. An offer file's own marketing
  valuation ("worth $469 a year") is a claim to note, not a fact to transcribe as the value.
- **`relationship_boost.boost_pct`**: offer files state boosts in different shapes — BofA says
  "25%-75% more rewards" (transcribe directly), but tiered total rates like Smartly's
  "2% base → 3% total at $50k" require you to compute the boost (3/2 − 1 = `boost_pct: 50`).
  That conversion is arithmetic on a transcribed fact — show it in the `note`.
- **Bundled program earn**: headline rates that fold non-card loyalty earn into the number —
  Frontier's "up to 15x" is 10x for program membership + 5x for the card; GM's "up to 10x" is
  7x card + up-to-3x member — must be split, and only the *card-attributable* portion becomes
  the `rate` (5x, 7x). If the offer file doesn't state the split, the whole rate is suspect:
  flag it in `notes` rather than transcribing the marketing number.
- **Which rate is the baseline**: for membership/payment-method-tiered rates ("5% with
  Walmart+, 3% without"; "2% via Apple Pay, 1% physical card"), deciding which figure goes in
  `rate` vs `conditional_rate`/`base_rate_conditional` is an interpretation — the plain rate
  must be the rate with NO memberships, no linked accounts, worst payment method. Getting this
  backwards inflates every recommendation; the validator only catches it when the conditional
  rate isn't strictly higher.

## Step 3 — No forced-fit registry keys

If a category, merchant, or program the offer file describes has no reasonable match in
`data/meta/categories.yaml`, `merchants.yaml`, or `point-valuations.yaml`, do not pick the
closest-sounding key just to make the validator pass. Stop and either:
- propose the registry addition per curation-guide's [Extending the registries](curation-guide.md#extending-the-registries) section, or
- omit the reward and note the omission in the card's `notes` field, explaining what was dropped and why.

Forcing a fit here is worse than an omission — it silently corrupts a shared assumption every
other card also relies on.

## Step 4 — Rotating, choice, combined-cap, and multi-part-bonus cards get read twice

For any card with rotating categories or choose-your-own-category rewards:
- Confirm you used the `rotating` / `choice` pseudo-categories, not a snapshot of this quarter's
  or this user's actual categories (the curation guide explicitly bans hardcoding "this
  quarter's categories as if permanent").
- Re-read the offer file's selection mechanism once more after drafting — automatic top-category
  cards and user-selectable cards are schema-equivalent (`choice`) but the `note` field must say
  which one it is.

For any card whose cap or bonus prose contains the word "combined", "total", or "additional":
- **Combined caps**: "3 points/$1 on gas + grocery + dining, *combined*, on the first $6,000"
  means one shared pool — use `cap.shared_cap_id` on every member entry, each stating the FULL
  pool (`max_spend_usd: 6000` on all three, not a split). Modeling a combined cap as independent
  per-category caps silently double- or triple-counts headroom; the validator can't detect it
  because each cap looks plausible alone. Re-read the cap sentence after drafting specifically
  to answer: per-category, or combined?
- **Tiered bonuses**: "70,000 miles after $3,000, plus an *additional* 20,000 (90,000 total)
  after $5,000 total" → base `value` 70k / `spend_requirement_usd` 3000, plus one `tiers` entry
  of 20k at 5000. Tier values are the *increment*, tier spend requirements are *cumulative* —
  offer files mix both framings in one sentence, so recompute which is which (see Step 6).
- **Mixed bonuses**: "100,000 points + $100 statement credit" is one `value` with both `points`
  and `usd`, not a bonus plus a credit. Approval-time gift cards with no spend requirement are a
  bonus with `spend_requirement_usd: 0`.
- **First-year match** (Discover): use `first_year_match: true` with no value/spend/window —
  never invent a dollar figure for it.
- **What tiers can't hold**: second tranches in a *different window* or gated on
  *merchant-specific* spend ("plus 30,000 after $750 at Hotels by Wyndham in 180 days") do NOT
  go in `tiers` — the validator's cumulative-ascending check will reject them or, worse, accept
  a distorted version. Structure only the primary spend-gated tranche; describe the rest in
  `signup_bonus.notes`.

For store cards, co-brands, and fintech cards tied to a membership or account (read the
"Modeling conventions" section of the curation guide before drafting these):
- **Conditional rates**: membership-gated ("5% at Walmart with linked Walmart+"), payment-method-gated
  (Apple Pay), and status-gated rates use `conditional_rate` (or `base_rate_conditional`),
  with the unconditional baseline in `rate`/`base_rate` — see the Step 2 trap.
- **`required_membership`** for *paid* prerequisites (Sam's Club, Prime, REI Co-op, Robinhood
  Gold — the membership fee is a real cost the note must surface). Free credit-union
  eligibility (Navy Federal, PenFed, Alliant) goes in `approval.notes`, not here.
- **Reward-dollar caps vs spend caps**: "maximum $5,000 in Sam's Cash per calendar year" caps
  *reward dollars* → `max_annual_rewards_usd: 5000`. "Up to $300 cash back at 6%" caps *spend*
  → `cap.max_spend_usd: 5000`. Confusing the two is off by the rate multiple.
- **Instant discounts** (Target 5% off, Lowe's 5% off) are modeled as the earn rate with the
  discount mechanics in `notes`. **Repayment-contingent earn** (Upgrade) is a normal rate + note.
- **One file per variant**: Luxury Card tiers, store-vs-Visa pairs (Kohl's, Best Buy,
  Nordstrom), apply-time scheme elections (Truist), credit-limit-determined variants (Navy
  Federal cashRewards) each get their own YAML with the siblings cross-referenced in `notes`.
- **Scoped credit triggers**: `unlock_spend_usd` is TOTAL card spend per period only — a credit
  triggered by spend at a specific merchant/category ("$100 after $100+ at Hotels by Wyndham")
  or by non-spend activity ("after 5 nights stayed") keeps `unlock_spend_usd` unset and carries
  the trigger in `realistic_capture_rate_note`.
- **Not structured, ever**: elite-status grants and spend-based retention (`benefit_flags` +
  `notes`), deferred-interest financing (`special_financing` flag + `notes`), redemption-side
  rebates ("10% points back on award flights" → `notes`), spend-progressive loyalty ladders
  (model the lowest tier, ladder in `notes`).

## Step 5 — Attempt a live cross-check before finalizing confidence

`confidence: low` is always allowed and never blocks CI, but don't default to it out of
laziness. Before finalizing:
- If you have live web access this session, fetch the issuer's own product/rates-and-fees page
  (use the link in `docs/needs-verification-links.md` if listed, otherwise search for the
  official page — never a blog/aggregator as primary).
- Cross-check the three highest-impact numbers first, same as the curation guide's human-review
  advice: **annual fee, top category rate + its cap, signup bonus** (amount, spend requirement,
  window, expiry).
- If the live page matches the offer file on all three, you may set `confidence: medium` and add
  a `sources` entry for the live URL with today's real `accessed` date — but this is still not
  `high`. `high` requires a human to have independently checked the file; do not set it yourself
  under any circumstance.
- If the live page **disagrees** with the offer file (rate changed, bonus expired, fee changed),
  the live page wins — use it, and note the discrepancy in the card's `notes` so a human reviewer
  knows the offer file is stale, not just the card.
- If you have no live web access this session, skip straight to Step 6 with `confidence: low`.
  Do not fabricate an `accessed` date for a page you did not actually fetch.

## Step 6 — Arithmetic self-check

Before writing the file, recompute by hand (or note in your reasoning) every number that
required a conversion:
- Spend-cap math (`max_spend_usd` from a stated reward-dollar cap and rate).
- Any percentage-to-points or points-to-percentage conversion.
- Signup bonus `expires` date arithmetic (e.g., "offer ends 90 days after account opening" is
  *not* a fixed `expires` date — don't invent one; omit `expires` and say so in `notes` if the
  offer file gives a relative window instead of a calendar date).
- **Tier math**: confirm each `tiers[].value` is the increment (not the "90,000 total" figure)
  and each `tiers[].spend_requirement_usd` is cumulative (not the "$2,000 more" figure), and
  that tier spend requirements strictly ascend past the base — the validator errors otherwise.
- **Credit period vs face**: `amount_usd`/`amount_points` is per *period* — "$120 rideshare
  credit, up to $10/month" is `amount_usd: 10, period: monthly`, never 120. Same for
  `unlock_spend_usd`: it's per period ("$200 credit after $10,000 in a calendar year" →
  `unlock_spend_usd: 10000` on an `annual` credit).
- **Percentage-rebate perks** ("10% back on concessions up to $250/yr", "25% back on in-flight
  purchases"): modeled as a credit whose `amount_usd` is the annual cap or a realistic fraction
  of it — write down which you chose and why in the capture note; the cap alone overstates what
  anyone captures.
- **`relationship_boost.boost_pct`** derived from tiered total rates (see the Step 2 trap).
- **Reward-dollar cap vs spend cap**: re-read every "maximum"/"up to" sentence and confirm
  whether it caps reward dollars (`max_annual_rewards_usd`, no division) or spend at a rate
  (`cap.max_spend_usd` = reward cap ÷ rate). One divides, the other doesn't.
- **Card-attributable rate**: when a headline bundles program earn ("up to 15x" = 10x program
  + 5x card), confirm the subtraction and that only the card's portion was written as `rate`.
- **Conditional-rate direction**: confirm `rate` < `conditional_rate` and that `rate` is the
  no-membership / worst-payment-method figure (the validator checks the inequality, not the
  reading).

## Step 7 — Sources block honesty

- If you only read the local `.txt` file and did not fetch anything live, `sources[].url` should
  point at the *original* URL the offer file itself was sourced from, if the offer file or
  `docs/needs-verification-links.md` records one. If no URL is known at all, do not invent one —
  flag this in the card's top-level `notes` ("no source URL on file for this offer sheet; the
  original page needs to be located and cited") rather than leaving `sources` looking more solid
  than it is.
- `added_by` must name the actual AI model doing the conversion (e.g., `claude-sonnet-5`), and
  any source whose URL wasn't fetched this session must say so explicitly in that source's
  `note` (e.g., `note: "URL carried over from offer file header; not re-fetched this session"`).
  This is required by the curation guide's `sources.added_by` field definition — don't let it
  slide just because the conversion is mechanical.

## Step 8 — Run the validator, then produce a traceability table

1. Run `python3 scripts/validate_cards.py`. Fix every `ERROR` before proceeding — do not hand a
   file to a human reviewer with schema errors.
2. For each `WARNING` on your new file, either fix it (e.g., add a missing source) or, if it's
   expected (e.g., `confidence: low`, `not listed in docs/card-backlog.md` before you update it),
   leave it — but don't ignore an `UNSOURCED` warning silently; it means Step 7 wasn't finished.
3. Before declaring the card done, write a short traceability table (in your response to the
   user, not committed to the repo) mapping each populated YAML block to the offer-file line or
   live-fetch source it came from:

   ```
   base_rate: 1        ← offer file, "2 points/$1: everything else" line → wait, that's 2, not 1. Re-check.
   category_rewards[0] (dining, rate 3, cap $6000/mo) ← offer file line 12; cap computed from "$180/mo max" ÷ 3%
   signup_bonus (60k pts / $4k / 3mo) ← offer file "Signup Bonus" section, live-fetched issuer page (accessed 2026-07-04)
   ```

   This table is what lets a human reviewer spot-check in seconds instead of re-reading the whole
   offer file — it is the single most valuable output of this protocol, more so than the YAML
   itself. If you can't fill in a row's source, that field isn't done yet.

## Step 9 — Update the backlog

Change the card's line in `docs/card-backlog.md` from `[/]` (terms sheet present) to `[~]`
(AI-drafted) once the file passes the validator. Never mark `[x]` yourself — that marker is
reserved for a human who has independently verified the card, per the curation guide.

---

## Hard rules (never violate these regardless of time pressure)

1. Never set `verification.confidence: high`. Only a human sets that.
2. Never set `verification.last_verified_date` to a date you didn't actually do the verifying
   work on — "today" is fine only if you actually performed the steps above today.
3. Never fabricate a `sources[].url` or `accessed` date for a page you didn't read.
4. Never force a category/merchant/program key that doesn't genuinely fit just to satisfy the
   validator — omit and flag instead.
5. Never copy this quarter's rotating categories or a targeted/referral bonus as if it were the
   evergreen public offer.
6. Never skip the traceability table (Step 8.3) — a YAML file without one is not considered
   converted, only drafted-and-hidden.
