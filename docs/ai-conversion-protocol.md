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

## Step 3 — No forced-fit registry keys

If a category, merchant, or program the offer file describes has no reasonable match in
`data/meta/categories.yaml`, `merchants.yaml`, or `point-valuations.yaml`, do not pick the
closest-sounding key just to make the validator pass. Stop and either:
- propose the registry addition per curation-guide's [Extending the registries](curation-guide.md#extending-the-registries) section, or
- omit the reward and note the omission in the card's `notes` field, explaining what was dropped and why.

Forcing a fit here is worse than an omission — it silently corrupts a shared assumption every
other card also relies on.

## Step 4 — Rotating and choice cards get read twice

For any card with rotating categories or choose-your-own-category rewards:
- Confirm you used the `rotating` / `choice` pseudo-categories, not a snapshot of this quarter's
  or this user's actual categories (the curation guide explicitly bans hardcoding "this
  quarter's categories as if permanent").
- Re-read the offer file's selection mechanism once more after drafting — automatic top-category
  cards and user-selectable cards are schema-equivalent (`choice`) but the `note` field must say
  which one it is.

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
