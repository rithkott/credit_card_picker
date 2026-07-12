# Step 2: Optimization Engine — design

Complete design for the deterministic portfolio optimizer. This document is the
implementation spec for `scripts/optimize.py`: a later session builds exactly what is
written here. Nothing in this step ships code, so `docs/architecture.md` is untouched
(it documents only what is built); the implementation session must extend the diagram
and CI when the optimizer lands.

The design works entirely with the **existing** schema, registries, and validator —
no schema fields are added, so `tools/card-entry-form.html` needs no changes either.

## 1. Scope and non-goals

The optimizer is a pure function:

```
recommendations = f(dataset, spend_profile, policy_constants, as_of_date)
```

Identical inputs produce byte-identical output. `--as-of` (default: today) is the
*only* time input, used solely for signup-bonus expiry and staleness warnings.

**Non-goals for v1** (listed so nobody accidentally half-builds them):

- Multi-year value projections (we report `year1_net` and `ongoing_net`, nothing else).
- Scoring `benefit_flags` (lounge access, insurance, …) — displayed, not valued.
- Foreign-transaction-fee scoring — `foreign_transaction_pct` is display-only.
- Business or invite-only cards.
- "Value my existing cards" mode (v1 always builds the best portfolio from scratch).
- Issuer application-rule modeling (Chase 5/24, Amex once-per-lifetime, …) —
  `approval.notes` is echoed verbatim as a warning on recommended cards instead.
- Spend seasonality; all caps and spend are treated as evenly spread over the year.

## 2. Inputs

### 2.1 The spend profile (user-authored YAML)

```yaml
spend:                 # annual USD per category key from data/meta/categories.yaml
  groceries: 8000
  dining: 5000
  other: 12000
merchant_spend:        # optional carve-outs, keys from data/meta/merchants.yaml
  costco: 3000         # counted INSIDE spend[groceries], not in addition to it
user:
  credit_tier: very_good        # required; key from the schema's approval tiers
  valuation_mode: floor         # floor | optimistic (default floor)
  max_cards: 3                  # 1–5 (default 3)
  optimize_for: ongoing         # ongoing | year1 (default ongoing)
  activates_rotating: true      # default true
  uses_travel_portal: false     # default false
```

> **Superseded (plan 07):** `uses_travel_portal` was replaced by
> `user.confirmed_usage`, a list of usage-questions item keys; portal-only
> lines now gate on the card's `portal` key being confirmed. See
> `docs/plans/07-confirmed-usage.md`.
>
> **Superseded (plan 08):** `user.valuation_mode` (and `--mode`) were removed —
> points are valued at each program's engaged average, (floor_cpp +
> optimistic_cpp)/2, dropping to floor_cpp when a loyalty/transfer gate is
> unconfirmed; `run()` additionally emits `best_by_size`. See
> `docs/plans/08-simplified-valuation.md`.

Rules, enforced at load with hand-rolled checks in the style of
`validate_cards.py`'s registry checks (exit 1 with a clear message on violation):

- Every `spend:` key must be a non-pseudo key in `categories.yaml`. Using the
  `rotating` pseudo-category in a profile is an error.
- Every `merchant_spend:` key must exist in `merchants.yaml`. Each merchant's
  spend is a **sub-bucket of its parent category** (via `merchants.yaml[m].category`):
  for each category, the sum of its merchants' carve-outs must be ≤ the category's
  total, or the load fails. Carve-outs are never additive to category spend.
- Unknown `user:` keys or out-of-range values are errors.

### 2.2 The dataset

Loaded with the same conventions as `scripts/validate_cards.py`: `ROOT`-relative
paths, `load_yaml`, glob `data/cards/*/*.yaml`, registries from `data/meta/`. The
optimizer assumes the dataset already passes the validator; it re-checks nothing
structural.

## 3. Policy constants

Every judgment call lives in one module-level block and is **echoed into every
output**, so a user can always see the assumptions behind a recommendation:

```python
# Fraction of a credit's face value a typical user captures. Haircut scales with
# redemption friction: monthly use-it-or-lose-it coupons are easy to miss;
# annual credits are hard to miss.
CREDIT_CAPTURE = {"monthly": 0.5, "quarterly": 0.7, "semiannual": 0.8,
                  "annual": 0.9, "every_4_years": 0.9}

PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "semiannual": 2,
                    "annual": 1, "every_4_years": 0.25}

CAP_PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "annual": 1}

# Deterministic proxy for portal price premiums (portal fares often run above
# direct booking, eroding the headline multiplier).
PORTAL_RATE_MULT = 0.75

# Categories that historically appear in rotating quarters (Freedom Flex,
# Discover it). The rotating wildcard line may draw only from these.
ROTATING_ELIGIBLE = ["dining", "drugstores", "gas", "groceries",
                     "online_shopping", "streaming"]

TIER_ORDER = ["building", "fair", "good", "very_good", "excellent"]
```

## 4. Value model

### 4.1 Core conversion

Every reward line's effective USD-per-dollar rate is:

```
effective_rate = rate × cpp / 100
cpp = point_valuations["programs"][card.currency.program][mode + "_cpp"]
```

This one formula covers cash and points cards identically — the `cash` program is
1.0/1.0 cpp, so a cash rate of 2 is 2%. It also correctly handles points cards
modeled as cash-back-like: Citi Double Cash is `base_rate: 2` in `citi_typ`, so it
is 2% at floor (1.0 cpp) and 3.4% optimistic (1.7 cpp).

Signup-bonus and credit values use the same `cpp` when denominated in points.

### 4.2 `compute_annual_value(card, profile, mode, as_of)`

Single-card scoring (also the portfolio scorer's per-card core — see §6). Steps:

1. Build reward lines (§5.1) and assign spend (§5.5) with this card as the only
   candidate.
2. `earnings = Σ assigned_usd × effective_rate` over all lines.
3. Credits (below).
4. Signup bonus (below) — contributes to `year1_net` only.
5. Fees: `ongoing_fee = annual_fee_usd`; `year1_fee = 0 if first_year_waived else
   annual_fee_usd`.

Returns `{year1_net, ongoing_net, breakdown}` where
`ongoing_net = earnings + credits − ongoing_fee` and
`year1_net = earnings + credits + bonus − year1_fee`.

**Credits** (no schema change needed):

- A credit **without** a `category` key (exists in seed data: Venture X anniversary
  miles) is automatic: value = `amount_usd × PERIODS_PER_YEAR[period]`, full face.
- A credit **with** a `category` counts only if the profile has spend in that
  category. Value =
  `min(amount_usd × PERIODS_PER_YEAR[period] × CREDIT_CAPTURE[period],
       remaining_spend[category])`
  drawn from a **shared per-category remaining-spend tracker**, so stacked credits
  (e.g. Amex Gold's three dining credits) can never exceed the user's real spend in
  that category. Draw order is deterministic: file order within a card, card-id
  order across a portfolio. If the category has no (remaining) spend, the credit
  is $0 with a stated reason.
- A possible future numeric `capture_class` schema field could replace the
  period-based haircut; that is a non-blocking enhancement, not part of this design.

**Signup bonus** — counted once, year-1 only, iff ALL of:

- `signup_bonus` is non-null;
- `expires` is absent or `>= as_of` (expired → bonus $0 + warning, card kept);
- spend-feasible: `total_annual_spend × window_months / 12 >= spend_requirement_usd`
  (else $0 with reason "spend requirement unreachable at your volume").

Value = `usd`, or `points × cpp / 100` (mode-dependent, consistent with everything
else). Never appears in `ongoing_net`.

### 4.3 Worked example (embed as the first golden test)

Citi Double Cash on a $30,000/yr profile, no annual fee, $200 bonus with $1,500
requirement in 6 months:

- floor ongoing: `30000 × 2 × 1.0 / 100 = $600`
- year-1 floor: bonus feasible (`30000 × 6/12 = 15000 ≥ 1500`) → `600 + 200 = $800`
- optimistic ongoing: `30000 × 2 × 1.7 / 100 = $1,020`

## 5. Reward-line model and spend assignment

Shared by single-card scoring and portfolio search — one algorithm, one set of
tie-breaks, so results are consistent and explainable.

### 5.1 Buckets and lines

**Buckets** partition the user's spend: one bucket per merchant carve-out, plus one
residual bucket per category (category total minus its carve-outs).

**Lines** per card:

- **merchant line** per `merchant_rewards[]` entry — eligible only for that
  merchant's bucket.
- **category line** per `category_rewards[]` entry — eligible for that category's
  residual bucket AND the carve-out buckets of merchants mapped to that category,
  *except* merchants for which the same card has a merchant line. (Issuer
  precedence: on a given card, merchant beats category beats base — that is how the
  issuer pays, not a choice the optimizer makes.)
- **base line** — infinite room, eligible for every bucket not claimed by a higher
  line *of the same card*.
- **fallback line** — for each capped line, an uncapped sibling at
  `cap.fallback_rate` with identical eligibility. Above-cap spend earns the
  fallback rate, never `base_rate` (the schema requires `fallback_rate` inside
  every `cap`, so this is always explicit).
- **closed_loop** card: all of its lines are eligible only for the buckets of
  `closed_loop.merchants`. Spend at those merchants must be carved out in the
  profile to be assignable to the card at all.

### 5.2 Cap normalization

Annual room of a capped line = `cap.max_spend_usd × CAP_PERIODS_PER_YEAR[period]`.
Stated simplification: spend is even across periods (no seasonality).

### 5.3 `portal_only` lines

> **Superseded (plan 07):** the gate is now per-portal — a portal-only line is
> kept only when the card's `portal` key appears in `user.confirmed_usage`.

If `user.uses_travel_portal` is false, portal-only lines are dropped entirely —
their spend falls through to the next eligible line. If true, the line is kept with
`rate × PORTAL_RATE_MULT`. In seed data this governs Sapphire Preferred 5x
travel_other, Freedom Flex 5x travel_other, and Venture X 10x hotels / 5x flights.

### 5.4 The `rotating` pseudo-category

A `rotating` category line becomes a **capped wildcard line**:

- eligible for every bucket whose category ∈ `ROTATING_ELIGIBLE`;
- annual room = `cap.max_spend_usd × 4`; the line may additionally take at
  most `1/len(ROTATING_ELIGIBLE)` of each eligible bucket's spend — the
  featured-quarter coverage model (v1.3.2, replaced ROTATING_OVERLAP)
  (Freedom Flex: room `1500 × 4 = $6,000`, per-bucket share `1/6`);
- rate = `rate` if (`not rotation.requires_activation` or
  `user.activates_rotating`) else `cap.fallback_rate`.

This is reproducible, explainable, and — because the wildcard participates in the
same assignment as every other line — can never double-count a dollar of spend.

### 5.5 Assignment algorithm (exact spec)

Greedy over all lines of all candidate cards, in descending effective USD rate,
with deterministic tie-breaks:

```
sort key = (−effective_rate, card_id,
            kind_rank {merchant:0, category:1, rotating:2, fallback:3, base:4},
            category_or_merchant_key)
```

Each line absorbs `min(remaining_room, remaining_bucket_spend)` from its eligible
buckets. For **capped multi-bucket lines** (rotating is the only kind in the current
schema), buckets are chosen in ascending order of that bucket's best *alternative*
effective rate among remaining lines (the regret rule — steal spend where
displacement costs least), ties broken by bucket key.

Honesty note for the doc and code comments: this greedy is **exact for the current
structure** (at most one capped wildcard per card, uncapped base lines guarantee
coverage). Beyond that structure it is a documented heuristic; a tiny-LP (scipy)
solver is the named future upgrade, but **v1 stays stdlib + pyyaml only**.

Invariants: every dollar of profile spend is assigned exactly once; base lines
guarantee full coverage — except portfolios consisting only of closed-loop cards,
where unassignable spend earns $0 and is reported as such.

## 6. Portfolio search

Exhaustive over all subsets of eligible cards, sizes 1..`max_cards`. Each subset is
scored **jointly**: one shared assignment over all the subset's lines (§5.5), plus
Σ credits (with the shared per-category remaining-spend tracker), plus Σ eligible
signup bonuses (year-1 total only), minus Σ fees.

Ranking: by the `optimize_for` value (default `ongoing_net`), tie-break
`year1_net` descending, then lexicographic card-id tuple.

Complexity: C(n, k) subsets × a cheap assignment. Fine to n ≈ 80 eligible cards
(C(80,3) = 82,160). Above 80 the script hard-stops with a clear message; the
documented later path (needed near ~200 cards) is: pre-prune dominated cards (a
card that never wins any bucket at any mode and has no unique credit or bonus
edge), then beam search / branch-and-bound. **v1 ships exhaustive.**

> **Superseded:** the fixed n ≤ 80 hard stop is replaced by a dynamic
> subset-work budget (`MAX_SCORED_SUBSETS`) plus exact dominance pruning — see
> `docs/plans/02.5-optimizer_improvements.md`. The search itself remains
> exhaustive; beam search stays future work.

## 7. Filters and data-quality gating

Applied before search; every exclusion/warning is counted in the run header:

- **Approval:** include a card iff
  `TIER_ORDER.index(user.credit_tier) >= TIER_ORDER.index(card.approval.credit_tier)`.
  `estimated_min_score` is display-only in v1. `approval.notes` (5/24, once-per-
  lifetime, …) is echoed as a warning on any recommended card.
- **`confidence: low`** — INCLUDE, with a prominent per-card `UNVERIFIED DATA`
  warning in output. (Excluding would empty the product today: all 7 seed cards are
  low.) `high`/`medium` are silent.
- **Stale verification** (`last_verified_date` > 183 days before `as_of`, matching
  the validator's `STALE_DAYS`) — include + warning.
- **Expired bonus** — bonus zeroed + warning, card kept (§4.2).

## 8. Output contract

Default: human-readable text. `--json`: machine output with sorted keys. Both
contain:

- **Run header:** as-of date; valuation mode and the cpp table used; the full
  policy-constants block; eligible/filtered card counts.
- **Ranked portfolios** (top `--top N`, default 5), each with `year1_net`,
  `ongoing_net`, and per card:
  - assignment lines: `bucket, usd_assigned, rate, cpp, usd_value, note`
    (e.g. "capped at $6,000/yr", "portal ×0.75", "rotating: featured ~1/6 of the year; up to $6,000/yr ×activation");
  - credits: face value, multiplier applied, cap-by-spend note, or $0 + reason;
  - bonus: value, or $0 + reason;
  - fee(s);
  - warnings: low confidence, stale verification, approval notes.

Determinism restated: `--as-of YYYY-MM-DD` is the only time input; identical
inputs ⇒ identical bytes.

## 9. Implementation plan (for the build session)

- One plain script **`scripts/optimize.py`**, same style as `validate_cards.py`:
  stdlib + pyyaml, `ROOT`-relative paths, exit codes 0/1/2 for ok / input error /
  data error. Pure functions: `load_dataset`, `load_profile`, `build_lines`,
  `assign_spend`, `score_portfolio`, `search`, `render_text`, `render_json`.
- CLI:
  `python3 scripts/optimize.py --profile PATH  <!-- --mode removed by plan 08 -->
  [--max-cards N] [--top N] [--json] [--as-of YYYY-MM-DD]`
  — flags override the profile's `user:` fields.
- Tests: new `tests/test_optimizer.py` using stdlib `unittest` (no pytest
  dependency), run via `python3 -m unittest discover tests`. Golden tests with
  hand-computed expected values:
  - all 7 seed cards single-card, both modes (starting from §4.3's Double Cash);
  - capped category (Blue Cash Preferred groceries);
  - rotating wildcard (Freedom Flex);
  - portal on/off (Sapphire Preferred, Venture X);
  - credit gating (Amex Gold with and without dining spend);
  - bonus feasibility and expiry;
  - one 2–3 card portfolio with cap competition;
  - synthetic fixtures for `merchant_rewards` and `closed_loop` — no seed card
    uses them, so golden tests can't come from seed data.
- **Reminders for that session, not this one:** shipping the optimizer requires
  extending `docs/architecture.md` (the diagram documents only what is built) and
  CI (test run in `validate-data.yml` or a new workflow); any example-profile file
  added under `data/` also triggers the diagram rule per CLAUDE.md.

## 10. Addendum: choose-your-own-category cards (shipped after v1)

Cards whose 5% category is cardholder-selected — or automatic-top-category, which
is equivalent for optimization — (Citi Custom Cash, BofA Customized Cash) are
modeled with a second pseudo-category, `choice`, carrying a `choice` block:

```yaml
- category: choice
  rate: 5
  cap: {period: monthly, max_spend_usd: 500, fallback_rate: 1}
  choice:
    options: [dining, gas, groceries, ...]   # non-pseudo registry keys, >= 2
    note: How selection works (user-picked vs automatic, change cadence)
```

**Valuation by variant expansion.** Before search, `expand_choice_variants`
replaces each choice card with one virtual card per option **the profile actually
spends in** (id `custom-cash[groceries]`, carrying `base_id`), where the choice
line becomes an ordinary category line with the same rate/cap. If no option
matches any spend, a single variant keeps the card's id with the choice line
dropped. The subset search treats variants of the same `base_id` as **mutually
exclusive** (a physical card is configured exactly one way), and otherwise scores
them like any card — so the search picks the best configuration *per combination*:
solo, Custom Cash might be set to groceries; next to Blue Cash Preferred's 6%
groceries it flips to dining, with no special-casing beyond expansion.

Constraints: at most one `choice` reward per card (validator + optimizer both
enforce); the `MAX_ELIGIBLE_CARDS = 80` exhaustive-search cap now counts
*variants*; `choice` is banned from spend profiles and credit categories like any
pseudo-category.

> **Superseded:** `MAX_ELIGIBLE_CARDS` is gone — the scale gate is now the
> `MAX_SCORED_SUBSETS` work budget (still counted over variants); see
> `docs/plans/02.5-optimizer_improvements.md`.
