# Step 10: Optimizer overhaul — exact search at max_cards 4–5, exact assignment, compiled data artifact

Complete design for the optimizer overhaul, spec'd here first per the
02/02.5 precedent and implemented in the same change set as this doc:

1. **Per-run precompute** (§1) — byte-identical refactor: per-card reward
   lines, credit parts, and bonus parts are built once per run instead of
   once per scored subset.
2. **Exact spend assignment** (§2) — the greedy regret rule stays the fast
   path; a conservative detector flags subsets where its exactness argument
   does not apply, and a tiny deterministic min-cost-flow solver rescues
   those exactly. scipy is the test-time oracle that proves the solver
   correct.
3. **Branch-and-bound search engine** (§3) — a second engine
   (`--engine bnb`, the new default) that returns *provably identical
   results* to exhaustive enumeration while visiting a small fraction of the
   subsets. `max_cards: 4` and `5` — which exit 2 today on the full pool
   (129 variants ⇒ 7.2M subsets at k=4) — become interactive. The
   exhaustive engine is kept verbatim as the verification oracle.
4. **Compiled SQLite artifact** (§4) — `scripts/build_db.py` compiles the
   hand-curated YAML into a normalized (3NF) `data/build/cards.sqlite`,
   deterministically. YAML remains the only source of truth; the DB is a
   gitignored build product with FK integrity as a belt-and-suspenders
   check on `validate_cards.py`.
5. **Server cache + hot reload** (§5) — determinism makes result caching
   trivially safe; a dataset-manifest hash makes staleness detection cheap.

Dependency-policy change (user-approved): the optimizer layer may now use
**numpy/scipy** in addition to stdlib + pyyaml. In this design scipy is
required only by the test suite (LP oracle); the runtime hot paths stay
pure Python for per-subset speed and trivial byte-determinism. This
supersedes the "stdlib + pyyaml only" language in `02-optimizer.md` §5.5/§6
and `CLAUDE.md`-adjacent docs; those carry pointers here.

Measured baseline (Apple Silicon, worst-case profile: every category,
excellent tier, `accepts_brand_lockin: true`, all merchants):

- pool: 114 eligible cards → 129 variants → 115 after dominance pruning
- `max_cards=3`: 258,646 subsets, **14.4 s**
- `max_cards=4`: 7,166,915 subsets — **exit 2** (over `MAX_SCORED_SUBSETS`)
- example profile (47 kept variants): k=3 ≈ 1.0 s, k=4 ≈ 9.5 s

## 0. Invariants that the overhaul must preserve

- **Output contract unchanged**: the bundle keys, per-card blocks,
  presence-sensitive optional keys, and rounding (`_round2` at the edge)
  are exactly plan 02 §8 / plan 08. The UI reconciliation identity
  (earnings = Σ assignment `usd_value` − `reward_cap_clamp`; receipt rows
  sum to the net) holds line-for-line.
- **Determinism**: identical inputs → byte-identical JSON, on every engine.
- **`best_by_size`**: still the exact best portfolio per size 1..max_cards
  under the full comparator `(-primary, -year1_net, cards)`.
- **Purity**: `recommendations = f(dataset, profile, policy constants,
  as_of)`. New policy constants are echoed in `policy_constants()` like the
  old ones.

## 1. Per-run precompute (`RunTables`)

`score_portfolio` today rebuilds, per scored subset: every card's reward
lines (`build_lines`), every credit's gates/arithmetic (`score_credits`),
every bonus's parts (`score_bonus`), and each card's cpp. All of that is
portfolio-independent except two effects:

- **transfer-gateway cpp** (`effective_cpp`): a card's points price at
  `avg_cpp` instead of `floor_cpp` iff the subset holds a gateway card for
  its program. Binary context ⇒ at most **two** variants per card:
  `locked` and `unlocked`. Only `transfer_gateway_required` programs ever
  differ; every other card gets one shared entry.
- **the shared credit tracker** (`score_credits`): categorized credits draw
  a per-category remaining-spend pool across the portfolio. The draw
  (`min(haircut, available)`) must stay per-subset; everything before it —
  expiry gate, usage gate, unlock-spend gate, capture table, face value,
  note strings — is per-card and precomputable.

`RunTables` is built once per `run()` (and once inside
`prune_dominated_variants`, replacing its private `build_lines` calls):

```
tables.lines[variant_id][ctx]      # build_lines output, ctx ∈ {locked, unlocked}
tables.credit_parts[variant_id][ctx]  # per credit: either a final (value, note)
                                      # or a pending (haircut, category, note_fmt)
tables.bonus_parts[variant_id][ctx]   # everything except first_year_match's earnings
tables.cpp[variant_id][ctx]           # (cpp, valuation_note)
tables.fees / membership / warnings   # per card, as_of fixed per run
```

The precomputed paths must execute the *same arithmetic in the same order*
as today's inline code (same float products, same f-strings) so output
bytes cannot move. `score_portfolio()` keeps its signature and gains an
optional `tables=` parameter; callers without tables get the old behavior
(the fixture goldens exercise both).

**Gate**: the entire golden suite passes unchanged, and `--json` output on
the live dataset is byte-identical before/after. Measured win: the
per-subset cost drops to the greedy assignment + credit draws only
(~3-5×).

## 2. Exact spend assignment

### 2.1 The problem

Per subset, spend assignment is a transportation LP: variables x(l,b) ≥ 0
over (line, bucket) eligible pairs; maximize Σ effective_rate(l)·x(l,b)
subject to Σ_l x(l,b) ≤ amount(b) and, for each capped *unit* U (a capped
line, or the union of lines sharing a `shared_cap_id` pool),
Σ_{l∈U,b} x(l,b) ≤ room(U). Sizes: ≤ ~20 live buckets, ≤ ~40 lines,
≤ ~10 capped units per subset.

The greedy regret rule (plan 02 §5.5) is exact when capped units do not
compete: its displacement argument assumes the "best alternative rate" of
a bucket is not itself another capped unit whose room the reassignment
would consume (the 02.5 §2.4 "third-order rerouting" honesty note).

### 2.2 Detector: `greedy_is_exact(lines, buckets)`

Only **binding** capped units matter: a unit whose room ≥ the total live
spend it can reach has a slack constraint in every feasible solution and
behaves exactly like uncapped lines, so it is filtered out first
(`binding_units`). Conservative sufficient condition over the binding
units:

> No binding unit spreads a shared pool across several lines AND several
> live buckets, and every pair of binding units has live eligible sets
> that either do not intersect or are equal singletons.

If it holds, binding units interact only with never-binding lines, and the
regret rule's swap argument applies unit-by-unit → greedy is exact.
Returns False ⇒ *maybe* inexact — never wrongly True. (Proof sketch:
disjoint binding units decompose the LP into independent single-capped-unit
subproblems over a field of effectively-uncapped lines; each is a
fractional knapsack the regret ordering solves exactly. Equal-singleton
units are a rate-sorted drain of one bucket. A multi-line pool split
across several buckets is *not* regret-managed — the rule orders buckets
within one line only — hence the multiline condition.)

Because live buckets are run-static, RunTables precomputes each card's
binding units as bitmasks (`assign_exact.unit_masks`), and the per-subset
check (`RunTables.greedy_exact_hint` → `masks_compatible`) is a handful of
integer ANDs. A randomized test pins the bitmask path to the reference
set-based detector.

### 2.3 Exact solver: pure-Python min-cost flow, scipy as oracle

When the detector fires, the subset is re-solved exactly on an
**opportunity-cost reduction**: every displaced dollar of bucket b falls
back to the best non-binding rate alt(b) (non-binding rooms can absorb
their whole reachable spend simultaneously), so only binding units enter
the network and arcs price the marginal profit rate − alt(b), dropping
non-positive arcs. The reduced network (source → unit[room] → line →
bucket[amount] → sink, typically ≤ ~15 nodes) is solved by successive
most-profitable augmenting paths — Dijkstra with Johnson potentials seeded
by one DP pass over the initial DAG; float capacities are fine (LP
optimality needs no integrality). Measured ≈ 50 µs/flagged subset — cheap
enough to run inline in the search loop, unlike `scipy.linprog` whose
per-call wrapper overhead (~1 ms) would dominate (measured: ~608 µs/subset
even for a hand-rolled full-graph Bellman-Ford variant; the reduction is
what makes exactness affordable).

Measured on the live worst-case pool (max_cards=3, 247k scored subsets):
22% of subsets flagged, and greedy was *genuinely* suboptimal on ~1.8% —
the flow solution was adopted there (none changed the reported top-5 or
best-by-size on current data, but the exactness guarantee now holds
subset-by-subset). Full-pool k=3 runtime: 6.7 s (greedy only) → 9.4 s
(exact everywhere).

Output policy, for byte stability and minimal golden churn:

- If the greedy total already equals the flow optimum (within EPS) — the
  overwhelmingly common case — **keep the greedy assignment verbatim**.
- Otherwise adopt the flow solution, canonicalized: merged per (line,
  bucket), EPS-cleaned, emitted in the greedy sort order
  `(-effective_rate, card_id, KIND_RANK, key)` then bucket. Deterministic
  because the solver is.

`scripts/assign_exact.py` holds the detector + solver.
`assign_spend()` in `optimize.py` becomes the dispatcher (greedy →
detector → flow). Both engines (§3) score through the same dispatcher, so
engine equivalence is unaffected by where greedy is inexact.

**scipy's role**: `tests/test_assign_exact.py` cross-checks the flow
solver against `scipy.optimize.linprog(method="highs")` on randomized
instances and hand-built adversarial cases (two overlapping multi-bucket
capped units where greedy provably loses value). scipy is a test
dependency; the runtime never imports it.

With exact assignment everywhere, the 02.5 §2.4 caveat (pruning's swap
argument vs a heuristic scorer) is closed: the swap argument now holds
against the true optimum.

## 3. Branch-and-bound search engine

### 3.1 Engines

`search(variants, profile, programs, merchants, as_of, engine=...)`:

- `exhaustive` — today's code verbatim, including `subset_budget()` and
  the `MAX_SCORED_SUBSETS` exit-2 semantics. The oracle.
- `bnb` (default) — returns *exactly* the same top-`top` ranked entries
  and per-size bests as exhaustive would, proven by the admissible bound
  below plus tie-safe pruning. CLI: `--engine {bnb,exhaustive}`; the
  server always uses the default.

### 3.2 Admissible upper bound

Prerequisite (added to `validate_cards.py` as an **error**): every program
has `optimistic_cpp >= floor_cpp`, so `avg_cpp >= floor_cpp` and unlocking
a gateway can only raise a card's cpp.

Per variant c, once per run (from `RunTables`, ctx=True entries):

- `cpp⁺(c)`: `effective_cpp` with the gateway gate assumed satisfied. The
  loyalty gate is portfolio-independent and still applies. For every
  portfolio S: `cpp_S(c) ≤ cpp⁺(c)`.
- `r̄_c(b) = max{ rate(l) · cpp⁺(c)/100 : l ∈ **uncapped** lines(c),
  b ∈ eligible(l) }` — best uncapped effective rate per live bucket
  (portal multiplier and rotating fallback are already inside the line
  rates; closed-loop and rotating eligibility restrictions are already
  inside the eligible sets; every capped line emits an uncapped fallback,
  so r̄ is well-defined wherever the card earns at all).
- `capbonus(c) = Σ over c's capped units u of min(room_u, reachable live
  spend of u) × max(0, rate_u − min_{b ∈ eligible(u)} r̄_c(b))` — the most
  extra value u can add on top of r̄-priced dollars. **Cap-awareness must
  be additive like this**: pricing a capped rate into a per-bucket average
  is NOT admissible (two subset cards with small caps on one bucket can
  jointly beat any single card's averaged rate); the additive form is
  sound because a capped assignment x on b earns
  x·r̄_S(b) + x·(rate_u − r̄_S(b)) ≤ x·r̄_S(b) + x·(rate_u − r̄_c(b)), and
  Σx over the unit is ≤ min(room, reachable). This tightening is what
  makes k=5 tractable: it cut the full-pool k=5 wall clock ~10×.
- `K(c)`: c's credits scored standalone at `cpp⁺` with a full tracker.
  Admissible: the shared tracker is only ever decremented, so in-portfolio
  availability ≤ standalone availability, and points-credits scale with
  cpp ≤ cpp⁺.
- `B(c)`: signup bonus at `cpp⁺`, with `first_year_match` bounded by
  `min(Σ_b s_b·r̄_c(b) + capbonus(c), max_annual_rewards_usd or ∞)` ≥ the
  card's actual post-clamp earnings. Expiry and spend-feasibility gates
  are portfolio-independent.
- `x_on(c) = capbonus(c) + K(c) − fee_on(c)`,
  `x_y1(c) = capbonus(c) + K(c) + B(c) − fee_y1(c)` with fees exact
  (incl. card-exclusive membership).

**Lemma (single set).** For any portfolio S and either metric,
`net(S) ≤ U(S) = Σ_b s_b · max_{c∈S} r̄_c(b) + Σ_{c∈S} x(c)`:
every assigned dollar of bucket b earns at most the subset's best uncapped
rate on b plus its unit's capbonus allowance; reward-cap clamps only
subtract; credits and bonus per the itemized bounds; fees are exact.
Property-tested by brute force over every fixture subset
(tests/test_search_bnb.py::TestBoundAdmissible).

**Prefix bound.** DFS over variants in a fixed static order (descending
`m̂(c) = Σ_b s_b·r̄_c(b) + x(c)`, id tie-break), maintaining
`ρ_P(b) = max_{c∈P} r̄_c(b)` incrementally (restore on backtrack). For a
prefix P, remaining candidates R (static-order suffix, minus same-`base_id`
conflicts), and k_left more picks:

```
m_P(c)  = Σ_b s_b · max(0, r̄_c(b) − ρ_P(b)) + x(c)        # marginal bound
UB(P,R,k_left) = U(P) + sum of the k_left largest positive m_P(c), c ∈ R
```

Admissible because per-bucket maxima telescope into clipped marginals
(`max_{c∈P∪T} r̄ − ρ_P ≤ Σ_{c∈T} max(0, r̄_c − ρ_P)`), and dropping
negative-marginal cards never lowers a max. A cheaper static screen
`U(P) + suffix_topk[pos][k_left]` (precomputed from `m̂`, which dominates
`m_P`) runs first; the refined pass only when the static screen fails to
prune. numpy vectorizes the marginal passes (a clipped `R @ s` per DFS
frame) with a pure-stdlib fallback kept and pinned equivalent by test —
bound floats feed pruning decisions only and never reach output bytes, so
cross-engine byte-equivalence is untouched either way. The §2 solver adds a
per-run reduced-problem value memo (`RunTables.assign_cache`): the flow
optimum depends only on (binding units' rooms and profitable arcs, per-
bucket alternative rates), a signature that repeats heavily across
subsets.

### 3.3 Exactness of the full output contract

The bnb engine maintains:

- a top-`top` candidate list ordered by the exhaustive comparator
  `(-primary, -year1_net, cards)`, and
- per-size incumbents `best[k]`, k = 1..max_cards, same comparator.

Pruning threshold: `θ(P) = min( worst primary in the top-`top` list,
min over sizes reachable from P of best[k].primary )`. A node is pruned
only when `UB < θ − ε_safety`, ε_safety = 1e-6 — strictly-worse only, so
every subset that could tie the incumbent on the primary metric is still
visited and exact-scored, letting the year1/lexicographic tie-breaks
resolve exactly as exhaustive's sort would. (Dollar magnitudes ≤ 1e5 and
double-precision relative error ≤ 1e-11 keep 1e-6 a safe margin; the
cross-engine equivalence suite is the empirical proof.)

Every DFS prefix *is* a candidate subset of its size. It is exact-scored
(through §2's dispatcher) only when `U(P) ≥ θ − ε_safety` — sound because
`net(P) ≤ U(P)`. Incumbents are seeded before the DFS by a greedy
constructive build (grow the best size-(k−1) incumbent by each candidate,
exact-score, keep the best per size: ~max_cards·n exact scores ≈ tens of
ms) so pruning bites from the first node.

`base_id` mutual exclusion is enforced in candidate iteration, as in
`search()` today.

### 3.4 Budget and pruning defaults

- `BNB_NODE_BUDGET = 25_000_000` visited nodes (a policy constant, echoed
  in `policy_constants()`): safety valve with the same `DataError`/exit-2
  semantics as `MAX_SCORED_SUBSETS`, expected to be orders of magnitude
  above real usage (n≈129, K≤5 ⇒ 10⁴–10⁶ nodes). The message states the
  search was exact up to the budget.
- `MAX_SCORED_SUBSETS` stays, scoped to the exhaustive engine.
- **Dominance pruning defaults OFF under bnb** and stays ON under
  exhaustive (compat). Pruning only ever guaranteed that *one* optimal
  portfolio survives (02.5 §2.3); with it off, ranked rows and
  `best_by_size` regain full fidelity — the 02.5 documented caveat is
  eliminated rather than re-documented. `--prune/--no-prune` overrides per
  engine. The bundle keys `pruned` / `card_variants_pruned` remain
  (empty/0 under bnb defaults) — contract shape unchanged.
- **Benchmark-gate outcome (measured, Apple Silicon, live worst-case
  pool of 129 variants, exact assignment on):** bnb-without-pruning runs
  `max_cards=3` in **0.85 s** (exhaustive: 9 s), `max_cards=4` in
  **1.8 s** (exhaustive: exit 2), `max_cards=5` in **~28 s** (exhaustive:
  exit 2). Pruning ON only shaves ~30% at k=5, so the gate's premise
  (pruning rescues the 5 s target) fails and the default stays OFF —
  fidelity wins; k=5 is a wait-once operation and the server result cache
  (§5) makes repeats instant. The k=5 cost is dominated by exact-scoring
  ~240k near-optimal candidates, ~80% of which need the flow solver.

## 4. Compiled SQLite artifact

`scripts/build_db.py` compiles `data/cards/**` + `data/meta/**` into
`data/build/cards.sqlite` (directory gitignored). Deterministic: one
transaction, rows inserted in sorted (card id, file order) order, no
timestamps, fixed PRAGMAs, `PRAGMA user_version` = DB schema version,
`foreign_keys=ON` during build. A `meta` table stores the **dataset
manifest**: per-file sha256 of every source YAML plus the combined
`dataset_hash` (sha256 of the sorted per-file digests) — the staleness and
determinism contract. Byte-identical rebuilds are expected and tested; the
manifest hash is authoritative.

3NF tables (PKs bold; all cross-references FK-enforced):

- registries: `programs`, `program_redeems_for`, `program_loyalty_keys`,
  `categories`, `merchants`, `usage_groups`, `usage_items`,
  `statement_descriptors`, `descriptor_patterns`, and the category-rules
  blocks (`descriptor_categories`, `aggregator_prefixes`,
  `unmapped_descriptors`, `rule_keywords`, `issuer_categories`,
  `mcc_ranges`)
- cards: `issuers`, `cards` (scalar fields + fees/approval/verification
  columns), `category_rewards`, `merchant_rewards`, `caps` (one row per
  capped reward; `shared_cap_id` kept as a column — the pool is a
  *derived* grouping), `rotations`, `choices`, `choice_options`,
  `conditional_rates`, `credits`, `credit_usage_keys`, `signup_bonuses`,
  `bonus_tiers`, `required_memberships`, `closed_loops`,
  `closed_loop_merchants`, `benefit_flags`, `sources`, `source_supports`
- `meta` (key/value: schema_version, dataset_hash, file manifest)

Nullable columns encode YAML key *absence*; the loader restores absence
(never null/False placeholders) so presence-sensitive behavior is
untouched.

`load_dataset_db(path)` in `optimize.py` reconstructs the **identical**
in-memory dict shape as `load_dataset()` — the oracle test is
`load_dataset() == load_dataset_db(build(...))` deep-equality on the live
dataset and the test fixture. Selection: `--db [PATH]` explicit; the
server's lifespan hook rebuilds automatically when the stored manifest
disagrees with the current files, then loads from the DB.
`validate_cards.py` remains the validation surface, unchanged (except the
§3.2 cpp-ordering check).

## 5. Server result cache + hot reload

`server/app.py`:

- **Result cache**: LRU (~128 entries) keyed
  `sha256(canonical_json(parsed_profile) | as_of | top | dataset_hash)`.
  Purity makes stale-value bugs impossible; the dataset hash in the key
  makes reloads self-invalidating. Cache hits skip the per-run debug dump
  (one log line instead).
- **Hot reload**: per-request manifest check (ms-cheap hash of file
  stats/digests) or explicit `POST /api/reload`; on change, rebuild DB,
  swap `STATE["dataset"]`, new `dataset_hash`.

## 6. Test & golden strategy

1. §1 is gated on the goldens passing *unchanged* (they are the tripwire)
   plus a live-dataset byte-diff.
2. §2: `tests/test_assign_exact.py` — flow solver vs scipy linprog
   (random + adversarial instances), detector unit tests, determinism
   (repeat-solve byte equality). Fixture goldens are expected unchanged
   (greedy keeps its assignment when it ties the optimum); any golden that
   moves must be traced to a detector-flagged, provably-inexact greedy
   case and recomputed with the flow value as truth.
3. §3: dollar goldens unchanged by construction. Structural pins move:
   `test_search_is_exhaustive_and_ranked` pins `engine="exhaustive"`;
   budget tests split per engine. New `TestEngineEquivalence`:
   `render_json(run(...))` byte-equal across engines **with pruning pinned
   to the same setting on both sides**, over the fixture × a profile
   matrix (portal/loyalty/gateway/rotating toggles, both `optimize_for`,
   max_cards 1–5) and seeded random small pools. Bound property test: on
   random ≤12-variant pools, brute-force every completion of every prefix
   and assert `UB ≥ net`.
4. §4: `tests/test_build_db.py` — loader deep-equality oracle, rebuild
   idempotence (same bytes, same hash), FK-violation fails loudly.
5. §5: cache-hit byte-equality; reload-after-edit picks up a changed card.

## 7. Rollout order

§1 precompute → §2 exact assignment → §3 bnb engine → §4 SQLite artifact →
§5 server. Each lands independently green; the in-flight `site/` work is
untouched (bundle shape and reconciliation identities preserved
throughout).
