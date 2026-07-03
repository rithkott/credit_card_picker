# Data Infrastructure & Schema Architecture

Current state of what's actually built (dataset layer + validation pipeline only — the optimizer, spend-entry UI, and site are planned but not built, so they don't appear here).

> **Maintenance rule:** this diagram must be updated in the same change as any edit to `data/schema/card.schema.json`, the `data/meta/` registries, `scripts/validate_cards.py`, `.github/workflows/validate-data.yml`, or the repo's data layout. See `CLAUDE.md`.

```mermaid
flowchart TB

subgraph SOURCE["📁 Source of truth — hand-curated YAML, one file per card"]
    CARD["data/cards/&lt;issuer&gt;/&lt;card-id&gt;.yaml<br/><i>one file per card: small reviewable PRs,<br/>per-card git history, YAML comments carry 'why' notes</i>"]
end

subgraph SCHEMA["📐 data/schema/card.schema.json — every card decomposes into blocks needing different math"]
    IDENTITY["<b>id / name / issuer / network</b><br/><i>id = filename, issuer = directory —<br/>enforced so files can't drift from their paths</i>"]
    CURRENCY["<b>currency: type + program</b><br/><i>declares what a card earns (cash vs points)<br/>and which program prices those points —<br/>cards never embed their own point values</i>"]
    BASE["<b>base_rate</b><br/><i>catch-all earn rate; rewards are written as<br/>exceptions layered over it, never exhaustive lists</i>"]
    CATREW["<b>category_rewards[]</b><br/><i>spend-proportional elevated rates.<br/>cap = spend ceiling + fallback_rate (issuers limit 5-6% rates);<br/>rotation = quarterly categories + activation (so non-activation<br/>can be discounted); portal_only (portal prices run high)</i>"]
    MERREW["<b>merchant_rewards[]</b><br/><i>same shape, keyed to a named merchant<br/>('5% at Amazon') — beats category when both match</i>"]
    CREDITS["<b>credits[]</b><br/><i>fixed-value, use-it-or-lose-it, periodic — NOT scaled by spend.<br/>realistic_capture_rate_note is required because issuers price<br/>annual fees against sticker credit value most users never capture</i>"]
    SUB["<b>signup_bonus</b><br/><i>one-time, year-one only; value is exactly one of points/usd.<br/>limited_time + expires track elevated promos so an expired<br/>offer can't silently inflate recommendations</i>"]
    FEES["<b>fees</b><br/><i>annual_fee_usd + first_year_waived + foreign_transaction_pct —<br/>the costs every reward must be netted against</i>"]
    APPROVAL["<b>approval</b><br/><i>credit_tier (building→excellent) + estimated_min_score + notes.<br/>exists so no card is ever recommended that the user<br/>can't actually get approved for; 'building' makes<br/>secured/credit-builder cards first-class</i>"]
    CLOSED["<b>closed_loop (optional)</b><br/><i>marks store cards usable ONLY at listed merchants —<br/>expresses the restriction, not the reward, so store cards<br/>can still be recommended when spend concentrates there</i>"]
    FLAGS["<b>benefit_flags[]</b><br/><i>binary perks (lounge_access, primary_rental_insurance) —<br/>recorded but unscored in v1; future filtering</i>"]
    SOURCES["<b>sources[]</b><br/><i>exact URL pasted at the moment a fact enters the file<br/>(by human or AI), with supports[] naming which blocks it backs,<br/>accessed date, added_by — every number traceable to a link<br/>someone actually read</i>"]
    VERIF["<b>verification</b><br/><i>last_verified_date + verified_by + confidence.<br/>sources say where facts came from; verification says when a<br/>human last confirmed the whole file still matches them —<br/>low confidence = drafted, not done</i>"]
end

subgraph META["📚 data/meta/ — shared registries: single source for every cross-card assumption"]
    CATS["<b>categories.yaml</b><br/><i>canonical spend-category enum; will also drive the<br/>spend-entry form, so data and UI can never drift.<br/>'rotating' is a pseudo-category for quarterly cards</i>"]
    MERCH["<b>merchants.yaml</b><br/><i>canonical merchant enum; each merchant maps to a<br/>category so merchant spend routes out of the right bucket</i>"]
    VALS["<b>point-valuations.yaml</b><br/><i>cents-per-point per program, two modes:<br/>floor_cpp (guaranteed cash-out) vs optimistic_cpp (transfer partners) —<br/>one global, user-visible assumption instead of per-card guesses</i>"]
end

subgraph PIPE["✅ Validation pipeline — errors block, warnings nag"]
    VALIDATE["<b>scripts/validate_cards.py</b><br/><i>schema conformance · id=filename · issuer=directory ·<br/>duplicate ids · registry membership · cash⇒program:cash ·<br/>no future verification dates</i>"]
    WARNINGS["<b>Warnings (exit 0)</b><br/><i>stale: last_verified_date &gt; 6 months ·<br/>confidence: low · signup bonus past expires ·<br/>UNSOURCED: populated block no source supports —<br/>data-freshness nags that shouldn't block unrelated PRs</i>"]
    CI["<b>.github/workflows/validate-data.yml</b><br/><i>runs on PRs/pushes touching data, AND weekly on cron —<br/>so staleness and expired promos surface<br/>even when nobody is editing</i>"]
end

CARD -->|"must conform to"| SCHEMA
IDENTITY ~~~ CURRENCY

CURRENCY -->|"program must be a key in"| VALS
CATREW -->|"category must be a key in"| CATS
MERREW -->|"merchant must be a key in"| MERCH
CREDITS -->|"optional category key in"| CATS
CLOSED -->|"merchants must be keys in"| MERCH
MERCH -->|"each merchant maps to a category in"| CATS

MERREW -->|"beats when both match"| CATREW
CATREW -->|"beats"| BASE

SOURCES -->|"supports[] must cover every populated block"| WARNINGS

VALIDATE -->|"validates every card against schema + registries"| CARD
VALIDATE -->|"reads"| META
VERIF -->|"staleness &amp; confidence checks"| WARNINGS
SUB -->|"expiry check"| WARNINGS
VALIDATE --> WARNINGS
CI -->|"runs (PR / push / weekly cron)"| VALIDATE
```

## Reading the diagram

**Data flow in one sentence:** humans hand-write one YAML file per card conforming to the schema's blocks, every cross-card assumption (categories, merchants, point values) lives once in the `meta/` registries and is referenced by key, and a validator — run by CI on every data change plus weekly — enforces structure as errors and freshness as warnings.

**Why the blocks are separate:** each block is a different *kind of value* requiring different math — spend-proportional rates (with caps), fixed periodic credits, a one-time bonus, recurring fees. Flattening them into one rate table or prose is exactly what makes card comparisons unreliable everywhere else. The uniform shape means no card ever needs special-case handling.

**Why registries are separate files:** if every card embedded its own category names or point valuations, two cards could silently disagree ("grocery" vs "groceries"; 1.8cpp vs 2.1cpp for the same points). Keys are validated against the registries, so disagreement is a CI failure, and a valuation change is one edit that repriced every card at once.

**Why errors vs warnings:** structural problems (wrong field, unknown key, id/filename mismatch) mean the data can't be trusted at all — they fail CI. Freshness problems (6-month staleness, `confidence: low`, expired signup promo) mean the data needs a human re-check — they warn without blocking, and the weekly cron guarantees they keep surfacing until fixed.

## Resulting invariants

1. Every card file parses, conforms to the schema, and rejects unknown fields (typos can't hide).
2. `id` matches the filename, `issuer` matches the directory, ids are globally unique.
3. Every category / merchant / points-program key used anywhere resolves to a registry entry.
4. Cash cards always use `program: cash`; points values come only from the shared valuation table.
5. Every card carries a `sources` list pasting the exact URLs its facts came from, each declaring which blocks it supports — populated blocks with no supporting source are flagged.
6. Every card states who verified it, when, at what confidence — and CI re-surfaces anything stale, unverified, unsourced, or past its offer expiry, weekly, forever.
