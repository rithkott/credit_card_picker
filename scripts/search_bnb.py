#!/usr/bin/env python3
"""Exact branch-and-bound portfolio search (docs/plans/10-optimizer-overhaul.md §3).

Returns exactly what exhaustive enumeration would report — the global
top-`top` ranked entries and the best portfolio of every size 1..max_cards,
under the full exhaustive comparator (-primary, -year1_net, cards) — while
visiting a small fraction of the subsets. Soundness rests on an admissible
upper bound: every card is priced at cpp⁺ (its transfer-gateway gate assumed
satisfied; requires the validator's optimistic_cpp >= floor_cpp check), every
bucket dollar at the best headline rate of any subset card, credits at their
standalone value (the shared tracker only ever subtracts), bonuses at cpp⁺
with first_year_match bounded by headline earnings, fees exact. Pruning is
strictly-worse-only (threshold − ε), so primary-metric ties are always
explored and the year1/lexicographic tie-breaks resolve exactly as
exhaustive's sort would.

This module is imported lazily by optimize.search(); it imports optimize for
scoring and shares its RunTables cache.
"""

import bisect

import assign_exact
import optimize as opt

# Pruning slack: values are dollars (magnitude <= 1e5, double-precision noise
# <= 1e-9 here), so 1e-6 cleanly separates "provably worse" from "tie".
EPS_SAFETY = 1e-6

NEG_INF = float("-inf")


def bound_inputs(variants: list, profile: dict, buckets: dict, tables) -> tuple:
    """Per-variant admissible bound components, all at cpp⁺ (the ctx=True
    RunTables entries — identical to ctx=False for ungated cards). The
    spend-earnings bound is cap-aware (plan 10 §3.2):

      rbar[b]   best *uncapped* effective rate on live bucket b — every
                assigned dollar earns at least a bucket's best uncapped rate
                "for free" in the bound, so ρ/marginals run on these
      capbonus  Σ over the card's capped units of
                min(room, reachable spend) × max(0, unit rate − the card's
                own weakest uncapped alternative among the unit's buckets) —
                the most extra value the unit can add on top of rbar dollars
      x_on      capbonus + standalone credits − ongoing fee
      x_y1      capbonus + standalone credits + bonus bound − year-1 fee

    Admissible: a capped assignment x on bucket b earns x·rate =
    x·rbar_S(b) + x·(rate − rbar_S(b)) ≤ x·rbar_S(b) + x·(rate − rbar_c(b)),
    and summed over the unit x ≤ min(room, reachable). (A per-bucket
    "average of capped and uncapped rate" is NOT sound here — two subset
    cards with small caps on one bucket can jointly beat any single card's
    averaged rate — hence this additive decomposition.)

    Returns (live_bucket_keys, spend_amounts, {card_id: components})."""
    live = sorted(b for b, bk in buckets.items() if bk["amount"] > opt.EPS)
    pos = {b: i for i, b in enumerate(live)}
    live_set = set(live)
    s = [buckets[b]["amount"] for b in live]
    out = {}
    for v in variants:
        cid = v["id"]
        lines = tables.lines[cid][True]
        rbar = [0.0] * len(live)
        for ln in lines:
            if ln["room"] is not None:
                continue
            r = ln["effective_rate"]
            for b in ln["eligible"]:
                i = pos.get(b)
                if i is not None and r > rbar[i]:
                    rbar[i] = r
        capbonus = 0.0
        for u in assign_exact.capped_units(lines, live_set):
            if not u["eligible"]:
                continue
            reachable = sum(buckets[b]["amount"] for b in u["eligible"])
            room = min(u["room"], reachable)
            rate_u = max(lines[i]["effective_rate"] for i in u["lines"])
            own_alt = min(rbar[pos[b]] for b in u["eligible"])
            capbonus += room * max(0.0, rate_u - own_alt)
        # Standalone credit value (fresh tracker — an upper bound on the
        # card's in-portfolio credits, which share the tracker with others).
        tracker = dict(profile["spend"])
        credits = 0.0
        for part in tables.credit_parts[cid][True]:
            if part[0] == "final":
                credits += part[1]["value"]
            else:
                _, _name, haircut, cat, _note = part
                available = float(tracker.get(cat, 0.0))
                take = min(haircut, available) if available > opt.EPS else 0.0
                tracker[cat] = available - take
                credits += take
        static = tables.bonus_static[cid][True]
        if static[0] == "match":
            headline = sum(si * ri for si, ri in zip(s, rbar)) + capbonus
            clamp = v.get("max_annual_rewards_usd")
            bonus = min(headline, clamp) if clamp is not None else headline
        else:
            bonus = static[1]["value"]
        membership = opt.membership_fee(v)
        fee_on = v["fees"]["annual_fee_usd"] + membership
        fee_y1 = ((0 if v["fees"].get("first_year_waived")
                   else v["fees"]["annual_fee_usd"]) + membership)
        out[cid] = {"rbar": rbar,
                    "x_on": capbonus + credits - fee_on,
                    "x_y1": capbonus + credits + bonus - fee_y1}
    return live, s, out


def search_bnb(variants: list, profile: dict, programs: dict, buckets: dict,
               as_of, tables, top: int, node_budget: int) -> list:
    """The exact top-`top` entries plus the exact best entry per size, sorted
    by the exhaustive comparator — byte-compatible with feeding exhaustive's
    full ranked list through run()'s `ranked[:top]` + first-of-each-size
    logic. Raises opt.DataError past `node_budget` visited nodes (a safety
    valve orders of magnitude above real usage; the search is exact up to
    that point but refuses rather than silently degrading)."""
    primary = ("ongoing_net" if profile["user"]["optimize_for"] == "ongoing"
               else "year1_net")
    xkey = "x_on" if primary == "ongoing_net" else "x_y1"
    by_id = {v["id"]: v for v in variants}
    base_of = {cid: by_id[cid].get("base_id", cid) for cid in by_id}
    max_cards = min(profile["user"]["max_cards"], len(set(base_of.values())))
    if not variants:
        return []
    live, s, binfo = bound_inputs(variants, profile, buckets, tables)
    n_live = len(live)

    def entry_key(e):
        return (-e[primary], -e["year1_net"], tuple(e["cards"]))

    def exact(card_ids):
        # Canonical sorted-id order, exactly like exhaustive enumeration —
        # score_portfolio is card-order-sensitive when the flow assignment is
        # adopted (solve_assignment breaks rate ties by line-list position,
        # shifting residual attribution into first_year_match bonuses and
        # max_annual_rewards_usd clamps), so visitation order here would
        # diverge byte-wise from the oracle.
        cards = [by_id[c] for c in sorted(card_ids)]
        sc = opt.score_portfolio(cards, profile, programs, buckets, as_of,
                                 tables=tables)
        return {"cards": sc["cards"], "ongoing_net": sc["ongoing_net"],
                "year1_net": sc["year1_net"]}

    # Incumbents: the global top-`top` list and the best entry per size, both
    # under the full comparator. `seen` deduplicates seeding vs DFS visits.
    topn = []          # sorted [(entry_key, entry)]
    best_size = {}     # size -> entry
    seen = set()

    def consider(e):
        key = tuple(e["cards"])
        if key in seen:
            return
        seen.add(key)
        k = len(e["cards"])
        cur = best_size.get(k)
        if cur is None or entry_key(e) < entry_key(cur):
            best_size[k] = e
        bisect.insort(topn, (entry_key(e), e))
        if len(topn) > top:
            topn.pop()

    def theta_topn():
        return topn[-1][1][primary] if len(topn) == top else NEG_INF

    def theta_size(k):
        e = best_size.get(k)
        return e[primary] if e is not None else NEG_INF

    # Static order: descending standalone bound gain, id tie-break.
    m_hat = {cid: sum(si * ri for si, ri in zip(s, binfo[cid]["rbar"]))
                  + binfo[cid][xkey]
             for cid in by_id}
    order = sorted(by_id, key=lambda cid: (-m_hat[cid], cid))
    n = len(order)

    # suffix_topk[pos][k]: sum of the k largest positive m_hat among
    # order[pos:] — the free static screen (m_hat >= any m_P).
    suffix_topk = [[0.0] * (max_cards + 1) for _ in range(n + 1)]
    tail = []  # descending positive m_hat values, truncated to max_cards
    for pos in range(n - 1, -1, -1):
        v = m_hat[order[pos]]
        if v > 0.0:
            bisect.insort(tail, -v)
            if len(tail) > max_cards:
                tail.pop()
        row = suffix_topk[pos]
        acc = 0.0
        for k in range(1, max_cards + 1):
            if k <= len(tail):
                acc -= tail[k - 1]
            row[k] = acc

    # Seed incumbents constructively: score every size-1 subset (exact best
    # of size 1 for free), then grow the best prefix greedily one card at a
    # time — pruning bites from the first DFS node.
    prefix = []
    for _depth in range(max_cards):
        used = {base_of[c] for c in prefix}
        best = None
        for cid in order:
            if base_of[cid] in used:
                continue
            e = exact(prefix + [cid])
            consider(e)
            if best is None or entry_key(e) < entry_key(best[0]):
                best = (e, cid)
        if best is None:
            break
        prefix.append(best[1])

    # Bound arithmetic in matrix form, in static order. numpy (if available)
    # vectorizes the per-frame marginal pass — these floats feed pruning
    # decisions only and never reach output bytes; exact scores stay pure
    # Python, so cross-engine byte-equivalence is untouched.
    R_rows = [binfo[cid]["rbar"] for cid in order]
    x_vec = [binfo[cid][xkey] for cid in order]
    base_idx = {}
    base_vec = []
    for cid in order:
        base_vec.append(base_idx.setdefault(base_of[cid], len(base_idx)))
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        R_np = np.array(R_rows, dtype=float)
        s_np = np.array(s, dtype=float)
        x_np = np.array(x_vec, dtype=float)
        base_np = np.array(base_vec)

    nodes = [0]

    def marginals(pos, rho_vec, used_base_ids):
        """m_P(c) for every candidate in order[pos:], with same-base and
        used-base candidates masked to -inf. Returns a plain list."""
        if np is not None:
            gains = np.clip(R_np[pos:] - rho_vec, 0.0, None) @ s_np + x_np[pos:]
            if used_base_ids:
                mask = np.isin(base_np[pos:], list(used_base_ids))
                gains[mask] = NEG_INF
            return gains
        out = []
        for jdx in range(pos, n):
            if base_vec[jdx] in used_base_ids:
                out.append(NEG_INF)
                continue
            rb = R_rows[jdx]
            mg = 0.0
            for i in range(n_live):
                d = rb[i] - rho_vec[i]
                if d > 0.0:
                    mg += s[i] * d
            out.append(mg + x_vec[jdx])
        return out

    def top_k_sum(values, k):
        """Sum of the k largest positive entries."""
        if np is not None:
            pos_vals = values[values > 0.0]
            if pos_vals.size == 0:
                return 0.0
            if pos_vals.size <= k:
                return float(pos_vals.sum())
            part = np.partition(pos_vals, pos_vals.size - k)
            return float(part[-k:].sum())
        best = sorted((v for v in values if v > 0.0), reverse=True)
        return sum(best[:k])

    def dfs(pos, depth, used_bases, u_prefix, rho_vec):
        """Extend the current prefix (size `depth`, bound value `u_prefix`,
        per-bucket maxima `rho_vec`) with candidates from order[pos:]."""
        m_here = marginals(pos, rho_vec, used_bases)
        size = depth + 1
        th_exact = min(theta_topn(), theta_size(size)) - EPS_SAFETY
        for off in range(n - pos):
            mpc = m_here[off]
            if mpc == NEG_INF:
                continue  # base_id conflict with the prefix
            idx = pos + off
            cid = order[idx]
            nodes[0] += 1
            if nodes[0] > node_budget:
                raise opt.DataError(
                    f"branch-and-bound visited more than BNB_NODE_BUDGET = "
                    f"{node_budget:,} nodes — the search was exact up to the "
                    f"budget but refuses to continue; lower user.max_cards or "
                    f"raise the budget")
            u_child = u_prefix + mpc
            # Exact-score the child subset itself when its single-set bound
            # says it could enter the top-N or beat its size incumbent.
            if u_child >= th_exact:
                consider(exact(current_ids + [cid]))
                th_exact = min(theta_topn(), theta_size(size)) - EPS_SAFETY
            # Recurse when some completion could still matter.
            if size < max_cards and idx + 1 < n:
                k_left = max_cards - size
                th_cont = theta_topn()
                for k in range(size + 1, max_cards + 1):
                    tk = theta_size(k)
                    if tk < th_cont:
                        th_cont = tk
                if u_child + suffix_topk[idx + 1][k_left] < th_cont - EPS_SAFETY:
                    continue  # static screen pruned the whole subtree
                # Refined bound: k_left largest positive clipped marginals
                # against the child's per-bucket maxima.
                rbar = binfo[cid]["rbar"]
                if np is not None:
                    rho_child = np.maximum(rho_vec, R_np[idx])
                else:
                    rho_child = [max(rho_vec[i], rbar[i]) for i in range(n_live)]
                used_bases.add(base_vec[idx])
                m_next = marginals(idx + 1, rho_child, used_bases)
                ub_ref = u_child + top_k_sum(m_next, k_left)
                if ub_ref >= th_cont - EPS_SAFETY:
                    current_ids.append(cid)
                    dfs(idx + 1, size, used_bases, u_child, rho_child)
                    current_ids.pop()
                used_bases.discard(base_vec[idx])

    current_ids = []
    rho0 = np.zeros(n_live) if np is not None else [0.0] * n_live
    dfs(0, 0, set(), 0.0, rho0)

    ranked = sorted({tuple(e["cards"]): e
                     for _k, e in topn}.values(), key=entry_key)
    for e in best_size.values():
        if e not in ranked:
            ranked.append(e)
    ranked = sorted({tuple(e["cards"]): e for e in ranked}.values(),
                    key=entry_key)
    return [{"cards": list(e["cards"]), "ongoing_net": e["ongoing_net"],
             "year1_net": e["year1_net"]} for e in ranked]
