#!/usr/bin/env python3
"""Exact spend assignment for subsets outside the greedy exactness envelope
(docs/plans/10-optimizer-overhaul.md §2).

The per-subset assignment problem is a transportation LP: maximize
Σ effective_rate(l)·x(l,b) over eligible (line, bucket) pairs, subject to
per-bucket spend limits and per-capped-unit room limits (a unit is a capped
line, or all lines sharing one shared_cap_id pool). `greedy_is_exact` is a
conservative detector for when the regret-rule greedy provably solves that LP;
`solve_assignment` is a deterministic successive most-profitable-augmenting-
path flow solver used when it might not. Pure stdlib — scipy.linprog is the
*test-time* oracle for this module (tests/test_assign_exact.py), never a
runtime import.
"""

import heapq

EPS = 1e-9

# A flow solution must beat greedy by more than accumulated float noise before
# the dispatcher adopts it (dollar values, double precision: 1e-6 is orders of
# magnitude above roundoff and orders of magnitude below any real rate gap).
VALUE_EPS = 1e-6

# Profits below this are treated as zero when hunting augmenting paths.
PROFIT_EPS = 1e-12


def live_bucket_keys(buckets: dict) -> set:
    return {b for b, bk in buckets.items() if bk["amount"] > EPS}


def capped_units(lines: list, live: set) -> list:
    """Group capped lines into units in first-appearance order. A unit is one
    capped line, or every line drawing one shared_cap_id pool (their `room` is
    the pool total, stated identically on each member — validator-guaranteed).
    Returns [{"room", "lines": [line indices], "eligible": live bucket set}]."""
    units, order = {}, []
    for i, ln in enumerate(lines):
        if ln["room"] is None:
            continue
        key = ln.get("room_key") or ("line", i)
        if key not in units:
            units[key] = {"room": ln["room"], "lines": [], "eligible": set()}
            order.append(key)
        units[key]["lines"].append(i)
        units[key]["eligible"].update(b for b in ln["eligible"] if b in live)
    return [units[k] for k in order]


def binding_units(lines: list, buckets: dict) -> list:
    """Capped units whose cap can actually bind: room < the total live spend
    the unit can reach. A unit with room >= reachable spend behaves exactly
    like uncapped lines (the constraint is slack in every feasible solution),
    so it is invisible to the exactness question and to the solver."""
    live = live_bucket_keys(buckets)
    units = []
    for u in capped_units(lines, live):
        if not u["eligible"]:
            continue
        reachable = sum(buckets[b]["amount"] for b in u["eligible"])
        if u["room"] < reachable - EPS:
            units.append(u)
    return units


def greedy_is_exact(lines: list, buckets: dict) -> bool:
    """Conservative sufficient condition for the regret-rule greedy to be an
    exact LP solution (plan 10 §2.2), over *binding* capped units only:

      - no binding unit spreads a shared pool across several lines AND several
        live buckets (the pool split between lines is not regret-managed), and
      - every pair of binding units has disjoint live eligible sets, or
        identical singletons (competition inside one bucket is a fractional
        knapsack the rate ordering solves exactly).

    Under those conditions each binding unit interacts only with uncapped (or
    never-binding) lines on its own buckets, which is exactly the regime plan
    02 §5.5 proves the regret rule exact for. Returns False on *maybe* inexact
    — never wrongly True."""
    units = binding_units(lines, buckets)
    for u in units:
        if len(u["lines"]) > 1 and len(u["eligible"]) > 1:
            return False
    for i, ui in enumerate(units):
        for uj in units[i + 1:]:
            inter = ui["eligible"] & uj["eligible"]
            if not inter:
                continue
            if ui["eligible"] == uj["eligible"] and len(ui["eligible"]) == 1:
                continue
            return False
    return True


def unit_masks(lines: list, buckets: dict, bucket_bit: dict):
    """Per-card precompute hook (RunTables): the detector's view of one card's
    lines as (is_multiline, live-eligible bitmask) pairs over binding units,
    or False when the card alone already breaks the exactness condition
    (a multi-line pool binding across several live buckets, or two of its own
    binding units competing). Bitmasks make the per-subset detector a handful
    of integer ANDs."""
    masks = []
    for u in binding_units(lines, buckets):
        mask = 0
        for b in u["eligible"]:
            mask |= bucket_bit[b]
        masks.append((len(u["lines"]) > 1, mask))
    if not masks_compatible(masks):
        return False
    return masks


def masks_compatible(masks) -> bool:
    """The pairwise + multiline exactness rules over (is_multiline, mask)
    pairs — shared by the per-card precompute and the per-subset check."""
    for multi, mask in masks:
        if multi and mask & (mask - 1):  # multiline pool, >1 live bucket
            return False
    for i in range(len(masks)):
        mi = masks[i][1]
        for j in range(i + 1, len(masks)):
            mj = masks[j][1]
            inter = mi & mj
            if not inter:
                continue
            if mi == mj and not mi & (mi - 1):  # identical singletons
                continue
            return False
    return True


def solve_value(lines: list, buckets: dict, cache: dict = None) -> float:
    """Exact optimum VALUE of the assignment LP, optionally memoized. The
    reduced problem (plan 10 §2.3) depends only on the binding units' rooms
    and profitable (rate, bucket) arcs plus the per-bucket alternative rates —
    a signature that repeats heavily across the subsets of one run, so a
    per-run cache (RunTables.assign_cache) turns most solves into a lookup.
    Flows are not produced here; assign_spend re-solves for them only when
    this value strictly beats greedy."""
    if cache is None:
        return solve_assignment(lines, buckets)[0]
    live = sorted(live_bucket_keys(buckets))
    if not live:
        return 0.0
    live_set = set(live)
    units = binding_units(lines, buckets)
    binding_lines = {i for u in units for i in u["lines"]}
    alt_rate = {b: 0.0 for b in live}
    for i, ln in enumerate(lines):
        if i in binding_lines:
            continue
        r = ln["effective_rate"]
        for b in ln["eligible"]:
            if b in live_set and r > alt_rate[b] + PROFIT_EPS:
                alt_rate[b] = r
    unit_sigs = []
    for u in units:
        arcs = []
        for i in u["lines"]:
            rate = lines[i]["effective_rate"]
            for b in lines[i]["eligible"]:
                if b in live_set:
                    p = rate - alt_rate[b]
                    if p > PROFIT_EPS:
                        arcs.append((rate, b))
        unit_sigs.append((u["room"], tuple(sorted(arcs))))
    base = sum(buckets[b]["amount"] * alt_rate[b] for b in live)
    if not any(sig[1] for sig in unit_sigs):
        return base
    key = (tuple(sorted(unit_sigs)),
           tuple(alt_rate[b] for b in live))
    profit = cache.get(key)
    if profit is None:
        total, _flows = solve_assignment(lines, buckets)
        profit = total - base
        cache[key] = profit
    return base + profit


def solve_assignment(lines: list, buckets: dict) -> tuple:
    """Exact optimum of the assignment LP. Returns (total_value, flows) where
    flows maps (line_index, bucket_key) -> usd assigned, covering every line
    that carries spend (binding-unit lines from the LP, everything else on the
    best non-binding line per bucket).

    The LP is solved on an opportunity-cost reduction: only *binding* capped
    units are modeled; every displaced dollar of bucket b falls back to the
    best non-binding rate alt(b) (non-binding rooms can absorb their whole
    reachable spend simultaneously, so alt is always available). Arcs price
    the marginal profit rate - alt(b); non-positive arcs are dropped because
    routing that spend to the alt line is feasible and never worse. The
    reduced network (source -> unit[room] -> line -> bucket[amount] -> sink)
    is solved by successive most-profitable augmenting paths — Dijkstra with
    Johnson potentials seeded by one DP pass over the initial DAG — the
    classic min-cost-flow optimality argument, real-valued capacities (an LP
    needs no integrality). Deterministic: fixed node order, index-order alt
    tie-breaks, heap ties resolved by node id."""
    live = sorted(live_bucket_keys(buckets))
    if not live:
        return 0.0, {}
    live_set = set(live)
    units = binding_units(lines, buckets)
    binding_lines = {i for u in units for i in u["lines"]}

    # Best non-binding alternative per bucket. First strictly-better line (in
    # list order) wins ties, so reconstruction is deterministic.
    alt_rate = {b: 0.0 for b in live}
    alt_line = {b: None for b in live}
    for i, ln in enumerate(lines):
        if i in binding_lines:
            continue
        r = ln["effective_rate"]
        for b in ln["eligible"]:
            if b in live_set and (alt_line[b] is None or r > alt_rate[b] + PROFIT_EPS):
                alt_rate[b] = r
                alt_line[b] = i

    # Only buckets a binding line can profitably reach appear in the network.
    arc_pairs = []  # (unit_idx, line_idx, bucket, marginal profit)
    used_buckets = []
    bucket_pos = {}
    for u_idx, u in enumerate(units):
        for i in u["lines"]:
            rate = lines[i]["effective_rate"]
            for b in lines[i]["eligible"]:
                if b not in live_set:
                    continue
                p = rate - alt_rate[b]
                if p > PROFIT_EPS:
                    if b not in bucket_pos:
                        bucket_pos[b] = len(used_buckets)
                        used_buckets.append(b)
                    arc_pairs.append((u_idx, i, b, p))

    total_spend = sum(buckets[b]["amount"] for b in live)
    INF = total_spend + 1.0

    flows = {}
    total = 0.0
    if arc_pairs and len(units) == 1:
        # Single binding unit: a one-supply transportation problem, solved
        # exactly by filling arcs in descending marginal profit (exchange
        # argument / polymatroid greedy). Deterministic tie-breaks.
        room = units[0]["room"]
        remaining = {b: buckets[b]["amount"] for b in used_buckets}
        for _u, i, b, p in sorted(arc_pairs, key=lambda t: (-t[3], t[1], t[2])):
            if room <= EPS:
                break
            take = min(room, remaining[b])
            if take <= EPS:
                continue
            room -= take
            remaining[b] -= take
            flows[(i, b)] = take
            total += take * lines[i]["effective_rate"]
    elif arc_pairs:
        # Node ids: 0 = source, units, binding lines, used buckets, sink —
        # a DAG in id order, which the potential-seeding DP relies on.
        line_ids = sorted(binding_lines)
        line_pos = {i: k for k, i in enumerate(line_ids)}
        n_units, n_lines = len(units), len(line_ids)
        unit_node = lambda u: 1 + u
        line_node = lambda i: 1 + n_units + line_pos[i]
        bucket_node = lambda b: 1 + n_units + n_lines + bucket_pos[b]
        sink = 1 + n_units + n_lines + len(used_buckets)
        n_nodes = sink + 1

        # Arc arrays (paired forward/reverse at 2k / 2k+1).
        to, cap, profit, head = [], [], [], [[] for _ in range(n_nodes)]

        def add_arc(u, v, c, p):
            head[u].append(len(to)); to.append(v); cap.append(c); profit.append(p)
            head[v].append(len(to)); to.append(u); cap.append(0.0); profit.append(-p)

        for u_idx, u in enumerate(units):
            add_arc(0, unit_node(u_idx), u["room"], 0.0)
            for i in u["lines"]:
                add_arc(unit_node(u_idx), line_node(i), INF, 0.0)
        line_bucket_arc = {}
        for u_idx, i, b, p in arc_pairs:
            line_bucket_arc[(i, b)] = len(to)
            add_arc(line_node(i), bucket_node(b), INF, p)
        for b in used_buckets:
            add_arc(bucket_node(b), sink, buckets[b]["amount"], 0.0)

        # Johnson potentials: cost = -profit; the initial graph is a DAG in
        # node-id order, so one DP pass gives exact starting potentials and
        # every residual arc keeps a non-negative reduced cost afterwards.
        POS = float("inf")
        pot = [POS] * n_nodes
        pot[0] = 0.0
        for u in range(n_nodes):
            if pot[u] == POS:
                continue
            for a in head[u]:
                if cap[a] > EPS and pot[u] - profit[a] < pot[to[a]]:
                    pot[to[a]] = pot[u] - profit[a]
        for v in range(n_nodes):
            if pot[v] == POS:
                pot[v] = 0.0  # unreachable: any finite value is safe

        max_rounds = 10 * len(to) + 100  # far above any real augmentation count
        for _ in range(max_rounds):
            dist = [POS] * n_nodes
            pred = [-1] * n_nodes
            dist[0] = 0.0
            heap = [(0.0, 0)]
            while heap:
                d, u = heapq.heappop(heap)
                if d > dist[u] + PROFIT_EPS:
                    continue
                for a in head[u]:
                    if cap[a] <= EPS:
                        continue
                    v = to[a]
                    nd = d + (-profit[a]) + pot[u] - pot[v]
                    if nd < dist[v] - PROFIT_EPS:
                        dist[v] = nd
                        pred[v] = a
                        heapq.heappush(heap, (nd, v))
            if dist[sink] == POS:
                break
            if dist[sink] + pot[sink] - pot[0] >= -PROFIT_EPS:
                break  # best remaining path profit <= 0
            for v in range(n_nodes):
                if dist[v] < POS:
                    pot[v] += dist[v]
            bottleneck = INF
            v = sink
            while v != 0:
                a = pred[v]
                bottleneck = min(bottleneck, cap[a])
                v = to[a ^ 1]
            v = sink
            while v != 0:
                a = pred[v]
                cap[a] -= bottleneck
                cap[a ^ 1] += bottleneck
                v = to[a ^ 1]
        else:
            raise RuntimeError("assign_exact.solve_assignment failed to "
                               "converge — this is a bug, not a data problem")

        for (i, b), a in sorted(line_bucket_arc.items(),
                                key=lambda kv: (kv[0][0], kv[0][1])):
            f = cap[a ^ 1]  # reverse-arc capacity == flow pushed forward
            if f > EPS:
                flows[(i, b)] = f
                total += f * lines[i]["effective_rate"]

    # Residual spend of every live bucket lands on its best non-binding line.
    residual = {b: buckets[b]["amount"] for b in live}
    for (i, b), f in flows.items():
        residual[b] -= f
    for b in live:
        r = residual[b]
        if r > EPS and alt_line[b] is not None:
            i = alt_line[b]
            flows[(i, b)] = flows.get((i, b), 0.0) + r
            total += r * lines[i]["effective_rate"]
    return total, flows
