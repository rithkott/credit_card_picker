# Data Infrastructure & Schema Architecture

Current state of what's actually built (dataset layer + validation pipeline + optimization engine — the spend-entry UI and site are planned but not built, so they don't appear here).

> **Maintenance rule:** this diagram must be updated in the same change as any edit to `data/schema/card.schema.json`, the `data/meta/` registries, `scripts/validate_cards.py`, `scripts/optimize.py`, `.github/workflows/validate-data.yml`, or the repo's data layout. See `CLAUDE.md`.

```mermaid
flowchart TB

subgraph SOURCE["📁 Source of truth — hand-curated YAML, one file per card"]
    FORM["<b>tools/card-entry-form.html</b><br/><i>browser form (no build/server) that emits schema-valid YAML —<br/>mirrors the validator's checks live, embeds registry keys<br/>(must be kept in sync when registries change)</i>"]
    CARD["data/cards/&lt;issuer&gt;/&lt;card-id&gt;.yaml<br/><i>one file per card: small reviewable PRs,<br/>per-card git history, YAML comments carry 'why' notes</i>"]
    FORM -->|"copy/download YAML into"| CARD
end

subgraph SCHEMA["📐 data/schema/card.schema.json — every card decomposes into blocks needing different math"]
    IDENTITY["<b>id / name / issuer / network</b><br/><i>id = filename, issuer = directory —<br/>enforced so files can't drift from their paths</i>"]
    CURRENCY["<b>currency: type + program</b><br/><i>declares what a card earns (cash vs points)<br/>and which program prices those points —<br/>cards never embed their own point values</i>"]
    BASE["<b>base_rate (+ base_rate_conditional)</b><br/><i>catch-all earn rate; rewards are written as<br/>exceptions layered over it, never exhaustive lists.<br/>base_rate_conditional stores a gated boost (Apple Card 2%<br/>via Apple Pay vs 1% physical) — stored, unscored</i>"]
    CATREW["<b>category_rewards[]</b><br/><i>spend-proportional elevated rates.<br/>cap = spend ceiling + fallback_rate (issuers limit 5-6% rates);<br/>shared_cap_id = several entries drawing ONE combined pool<br/>('2x gas + groceries on the first $5k/yr combined');<br/>rotation = quarterly categories + activation (so non-activation<br/>can be discounted); choice = options list the cardholder picks<br/>from (optimizer expands into per-option variants);<br/>portal_only (portal prices run high); requires_enrollment<br/>(rates that pay 1% unless actively enrolled);<br/>conditional_rate = membership/payment-method-gated boost<br/>('5% with Walmart+, else 3%') — baseline scored, boost stored</i>"]
    MERREW["<b>merchant_rewards[]</b><br/><i>same shape, keyed to a named merchant<br/>('5% at Amazon') — beats category when both match;<br/>also carries conditional_rate</i>"]
    CREDITS["<b>credits[]</b><br/><i>fixed-value, use-it-or-lose-it, periodic — NOT scaled by spend.<br/>amount_usd or amount_points (anniversary point drops, valued via<br/>the card's program); kind: in_kind marks estimated-value non-cash<br/>benefits (free nights, companion certificates) that always take a<br/>capture haircut; unlock_spend_usd gates spend-triggered credits;<br/>requires_enrollment + expires record capture drag and promo ends.<br/>realistic_capture_rate_note is required because issuers price<br/>annual fees against sticker credit value most users never capture</i>"]
    SUB["<b>signup_bonus</b><br/><i>one-time, year-one only; value mixes points and/or usd;<br/>tiers[] add tranches at higher cumulative spend ('70k after $3k,<br/>+20k after $5k total'); first_year_match models Discover's<br/>Cashback Match (valued as the card's own year-1 earnings).<br/>limited_time + expires track elevated promos so an expired<br/>offer can't silently inflate recommendations</i>"]
    FEES["<b>fees</b><br/><i>annual_fee_usd + first_year_waived + foreign_transaction_pct —<br/>the costs every reward must be netted against</i>"]
    APPROVAL["<b>approval</b><br/><i>credit_tier (building→excellent) + estimated_min_score + notes.<br/>exists so no card is ever recommended that the user<br/>can't actually get approved for; 'building' makes<br/>secured/credit-builder cards first-class</i>"]
    CLOSED["<b>closed_loop (optional)</b><br/><i>marks store cards usable ONLY at listed merchants —<br/>expresses the restriction, not the reward, so store cards<br/>can still be recommended when spend concentrates there</i>"]
    RELBOOST["<b>relationship_boost (optional)</b><br/><i>banking-relationship earn boosts (BofA Preferred<br/>Rewards): program + tiers keyed by<br/>min_balance_usd and/or a free-text requirement (SoFi direct<br/>deposit, Truist account types) + boost_pct — recorded but<br/>unscored in v1; the optimizer models the no-relationship baseline</i>"]
    REQMEM["<b>required_membership (optional) · max_annual_rewards_usd</b><br/><i>paid membership prerequisite (Sam's Club, Prime,<br/>Robinhood Gold) — unscored by default (the optimizer assumes the<br/>user already holds it) unless card_exclusive: then annual_cost_usd<br/>is scored as an ongoing + year-1 cost (never fee-waived).<br/>max_annual_rewards_usd = card-wide<br/>reward-dollar cap (Sam's Cash $5k/yr), clamped at scoring</i>"]
    FLAGS["<b>benefit_flags[]</b><br/><i>binary perks (lounge_access, primary_rental_insurance) —<br/>recorded but unscored in v1; future filtering</i>"]
    SOURCES["<b>sources[]</b><br/><i>exact URL pasted at the moment a fact enters the file<br/>(by human or AI), with supports[] naming which blocks it backs,<br/>accessed date, added_by — every number traceable to a link<br/>someone actually read</i>"]
    VERIF["<b>verification</b><br/><i>last_verified_date + verified_by + confidence.<br/>sources say where facts came from; verification says when a<br/>human last confirmed the whole file still matches them —<br/>low confidence = drafted, not done</i>"]
end

subgraph META["📚 data/meta/ — shared registries: single source for every cross-card assumption"]
    CATS["<b>categories.yaml</b><br/><i>canonical spend-category enum; will also drive the<br/>spend-entry form, so data and UI can never drift.<br/>'rotating' (quarterly cards) and 'choice' (choose-your-own<br/>cards) are pseudo-categories, banned from spend profiles</i>"]
    MERCH["<b>merchants.yaml</b><br/><i>canonical merchant enum; each merchant maps to a<br/>category so merchant spend routes out of the right bucket</i>"]
    VALS["<b>point-valuations.yaml</b><br/><i>cents-per-point per program, two modes:<br/>floor_cpp (guaranteed cash-out) vs optimistic_cpp (transfer partners) —<br/>one global, user-visible assumption instead of per-card guesses.<br/>redeems_for classifies each currency (flights / hotels / cashback;<br/>empty = merchant-restricted) — a kind counts only when that<br/>redemption path beats the program's own cash-out cpp — so<br/>users can ask the optimizer for specific reward kinds</i>"]
    DESC["<b>statement-descriptors.yaml</b><br/><i>reward-relevant merchant keywords (extracted from offer_files)<br/>→ common statement-descriptor variants ('DD *DOORDASH',<br/>'AMZN MKTP') — groundwork for statement-import spend detection;<br/>heuristic draft, not yet read by validator or optimizer</i>"]
end

subgraph PIPE["✅ Validation pipeline — errors block, warnings nag"]
    VALIDATE["<b>scripts/validate_cards.py</b><br/><i>schema conformance · id=filename · issuer=directory ·<br/>duplicate ids · registry membership · cash⇒program:cash ·<br/>every valuation program has a valid redeems_for list ·<br/>no future verification dates · choice block ⇔ 'choice' category,<br/>≤1 per card, options are real (non-pseudo) categories ·<br/>credits can't use pseudo-categories · amount_points only on<br/>points cards · shared_cap_id groups have ≥2 members agreeing<br/>on period + max_spend_usd · bonus tier spend requirements<br/>exceed the base and strictly ascend · conditional_rate /<br/>base_rate_conditional strictly exceed their baseline rate ·<br/>rotating rewards carry a quarterly cap (uncapped rotating<br/>hard-errors the optimizer) · every merchants.yaml entry routes<br/>to a real (non-pseudo) category · every valuation program has<br/>numeric floor_cpp/optimistic_cpp</i>"]
    WARNINGS["<b>Warnings (exit 0)</b><br/><i>stale: last_verified_date &gt; 6 months ·<br/>confidence: low · signup bonus past expires ·<br/>promotional credit past expires ·<br/>UNSOURCED: populated block no source supports ·<br/>card file missing from docs/card-backlog.md —<br/>data-freshness nags that shouldn't block unrelated PRs</i>"]
    CI["<b>.github/workflows/validate-data.yml</b><br/><i>runs on PRs/pushes touching data, AND weekly on cron —<br/>so staleness and expired promos surface<br/>even when nobody is editing</i>"]
end

subgraph OPT["🧮 Optimization engine — deterministic portfolio recommendation (docs/plans/02-optimizer.md)"]
    PROFILE["<b>spend profile YAML (user-authored)</b><br/><i>annual spend per category + optional merchant carve-outs<br/>(sub-buckets of their category, never additive) + user block<br/>(credit_tier, valuation_mode, max_cards, optimize_for,<br/>activates_rotating, uses_travel_portal, reward_preferences —<br/>any mix of flights / hotels / cashback / total_value) — keys<br/>validated against the registries at load; see examples/</i>"]
    OPTIMIZE["<b>scripts/optimize.py</b><br/><i>pure function f(dataset, profile, policy constants, --as-of):<br/>identical inputs ⇒ byte-identical output. Buckets partition spend;<br/>reward lines (merchant &gt; category &gt; base per card, caps via<br/>fallback lines, shared_cap_id lines drain one combined pool,<br/>rotating as capped wildcard, portal ×0.75) are greedily<br/>assigned by effective rate with deterministic tie-breaks;<br/>credits get period-based capture haircuts against a shared<br/>remaining-spend tracker (points credits valued at program cpp;<br/>in_kind always haircut; unlock_spend_usd gated by the same<br/>feasibility rule as bonuses; promo credits past their expires<br/>date valued $0 at --as-of); signup bonuses are year-1 only<br/>(mixed points+usd summed, reachable tiers added,<br/>first_year_match = the card's own computed year-1 earnings).<br/>Choose-your-own ('choice') cards expand into one variant per<br/>option the profile spends in; variants of the same card are<br/>mutually exclusive, so the search configures each card optimally<br/>per combination. Exact dominance pruning (plan 02.5) then drops<br/>variants provably unable to appear in an optimal portfolio: a plain<br/>card (no credits/bonus) whose live-bucket rates are pointwise<br/>covered by a rival's uncapped lines at ≤ fees, no reward clamp,<br/>with match-interception + sibling guards; ties prune the larger id.<br/>Exhaustive subset search sizes 1..max_cards, gated on actual work:<br/>Σ C(n,k) ≤ MAX_SCORED_SUBSETS = 2M scored subsets (replaces the<br/>old 80-variant hard stop); approval-tier filter + reward-preference<br/>filter (concrete reward_preferences keep only cards whose<br/>currency's redeems_for intersects them; total_value = no filter);<br/>low-confidence / stale / expired-bonus warnings and pruned<br/>variants (with reasons) surface in output, never silently drop. relationship_boost, conditional_rate and<br/>base_rate_conditional are stored but<br/>unscored (unconditional baseline); required_membership is unscored<br/>unless card_exclusive, whose annual_cost_usd joins both fee totals<br/>(and the pruning fee comparison), surfaced per card as<br/>fees.membership_fee_usd; max_annual_rewards_usd clamps<br/>a card's spend earnings (clamp surfaced per card as<br/>reward_cap_clamp in the output so line sums reconcile).<br/>All judgment calls live in one policy-constants block echoed<br/>into every output. stdlib + pyyaml only</i>"]
    TESTS["<b>tests/test_optimizer.py</b><br/><i>golden tests with hand-computed expected values: every seed<br/>card both modes, caps, rotating, choice-variant expansion and<br/>per-combination flips, portal on/off, credit gating, bonus<br/>feasibility/expiry, portfolio cap competition, synthetic<br/>merchant_rewards/closed_loop fixtures, shared-cap pools,<br/>credit variants (points / in_kind / unlock / every_5_years /<br/>expired-promo $0), bonus variants (mixed value / tiers /<br/>first-year match), reward-cap clamping (incl. per-card<br/>surfacing in the run() bundle), reward-preference filtering (per-kind,<br/>multi-select union, total_value bypass, empty redeems_for),<br/>byte-determinism, subset-budget gate<br/>(formula + over-budget DataError before scoring), dominance<br/>pruning (worse-clone, extras/cap/fee/clamp blockers, match-<br/>interception guard, tie determinism, run()-level surfacing).<br/>Runs against a frozen fixture copy of the 8 seed cards<br/>(tests/fixtures/data/) so dataset growth never invalidates<br/>the hand-computed goldens</i>"]
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
CI -->|"runs unittest suite"| TESTS
TESTS -->|"golden-tests"| OPTIMIZE

PROFILE -->|"category/merchant keys validated against"| META
PROFILE --> OPTIMIZE
CARD -->|"scored by (assumes validator already passed)"| OPTIMIZE
VALS -->|"cpp (floor vs optimistic) prices every point line;<br/>redeems_for drives the reward-preference filter"| OPTIMIZE
MERCH -->|"routes carve-outs to their parent category"| OPTIMIZE
```

## Reading the diagram

**Data flow in one sentence:** humans hand-write one YAML file per card conforming to the schema's blocks, every cross-card assumption (categories, merchants, point values) lives once in the `meta/` registries and is referenced by key, a validator — run by CI on every data change plus weekly — enforces structure as errors and freshness as warnings, and a deterministic optimizer scores every subset of eligible cards against a user's registry-keyed spend profile to rank portfolios.

**Why the optimizer is a pure function:** `scripts/optimize.py` takes only the dataset, a spend profile, its module-level policy-constants block, and an `--as-of` date — no network, no randomness, no hidden time inputs — so identical inputs produce byte-identical output, every recommendation is reproducible, and every judgment call (credit-capture haircuts, portal discount, rotating overlap) is echoed into the output where the user can see it. Data-quality problems (`confidence: low`, stale verification, expired bonuses) become per-card warnings in the results rather than silent exclusions, because excluding unverified cards would empty the product today.

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
7. Optimizer runs are byte-reproducible: same dataset + profile + `--as-of` ⇒ identical output, with every policy assumption echoed in the run header.
8. In every scored portfolio each dollar of profile spend is assigned to exactly one reward line (closed-loop-only portfolios report unassignable spend as $0, never silently); credits can never exceed the user's real spend in their category; no card is recommended above the user's stated credit tier, and when the user asks for concrete reward kinds (flights / hotels / cashback), no card is recommended whose currency can't redeem for at least one of them.
