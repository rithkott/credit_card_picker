#!/usr/bin/env python3
"""Validate every BUSINESS card YAML in data/business/cards/ (plan 22).

Forked from scripts/validate_cards.py for the business dataset. Checks, per
card file:
  1. Valid YAML and conforms to data/business/schema/business-card.schema.json.
  2. `id` matches the filename; `issuer` matches the parent directory AND has
     an entry in data/business/meta/issuer-rules.yaml.
  3. Registry membership: every category (rewards, adaptive_top_n
     eligible_categories, credit category) exists in categories.yaml; every
     merchant in merchants.yaml; currency.program in point-valuations.yaml;
     credit usage_keys and program loyalty_keys in usage-questions.yaml.
  4. Business mechanics:
     - shared_cap_id groups have >= 2 members agreeing on period+max_spend_usd
     - adaptive_top_n: n < len(eligible_categories); eligible categories may
       not also appear in category_rewards (the top-n line replaces them)
     - pricing: model annual_fee requires annual_fee_usd; model per_seat
       requires free_tier: true (V1 scores per-seat cards at $0) and forbids
       annual_fee_usd / first_year_waived / fee_refund_spend_usd
     - business_approval: min_personal_fico_tier only with
       personal_guarantee: true; no-PG cards must state at least one business
       underwriting anchor (requires_ein / min_cash_balance_usd /
       min_annual_revenue_usd / funding_qualifies)
     - credits: at least one of usage_keys / category / automatic (automatic
       exclusive of the other two); amount_points only on points cards;
       portal_only credits and portal_only reward lines require the card-level
       portal key
     - unlocks_transfers only on transfer_gateway_required programs
     - signup-bonus tiers exceed the base requirement and strictly ascend
     - issuer-rules integrity: adds_to_524_exceptions entries must name card
       ids that exist (warning while the corpus is incomplete)
  5. Registry integrity: programs carry numeric floor/optimistic cpp and a
     valid redeems_for list; no-cashback programs require loyalty_keys (and
     cashback ones may not carry them); usage-question item keys are globally
     unique (NO statement-descriptors backing — the business product has no
     statement parsing); merchants map to real categories.
  6. Cross-dataset drift warning: a program key present in BOTH
     data/business/meta/point-valuations.yaml and the consumer
     data/meta/point-valuations.yaml must state identical floor/optimistic cpp
     (UR is UR) — mismatch warns, never blocks.
  7. verification.last_verified_date not in the future / stale warning;
     confidence: low warning; card listed in docs/business-card-backlog.md.

Exit code 0 on success (warnings allowed), 1 on any error.
Usage: python3 scripts/validate_business_cards.py
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "data" / "business" / "cards"
SCHEMA_PATH = ROOT / "data" / "business" / "schema" / "business-card.schema.json"
META_DIR = ROOT / "data" / "business" / "meta"
CONSUMER_VALUATIONS = ROOT / "data" / "meta" / "point-valuations.yaml"
BACKLOG_PATH = ROOT / "docs" / "business-card-backlog.md"
STALE_DAYS = 183  # ~6 months


def load_yaml(path: Path):
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema)

    categories = set(load_yaml(META_DIR / "categories.yaml")["categories"])
    merchants_registry = load_yaml(META_DIR / "merchants.yaml")["merchants"] or {}
    merchants = set(merchants_registry)
    programs_registry = load_yaml(META_DIR / "point-valuations.yaml")["programs"]
    programs = set(programs_registry)
    questions_registry = load_yaml(META_DIR / "usage-questions.yaml")["groups"]
    issuer_rules = load_yaml(META_DIR / "issuer-rules.yaml")["issuers"]

    backlog = BACKLOG_PATH.read_text() if BACKLOG_PATH.exists() else ""

    errors: list[str] = []
    warnings: list[str] = []

    # usage-questions integrity: item keys globally unique, labels present.
    # Unlike the consumer validator there is NO statement-descriptors parent
    # vocabulary — the business product has no statement parsing (plan 22).
    usage_keys_all: set[str] = set()
    for gname in sorted(questions_registry):
        group = questions_registry[gname] or {}
        items = group.get("items")
        if not group.get("label") or not group.get("prompt") or not items:
            errors.append(
                f"data/business/meta/usage-questions.yaml: group '{gname}' must have "
                f"a label, a prompt, and a non-empty items map")
            continue
        assumed = group.get("assumed_reward_kind")
        if assumed is not None and assumed not in ("flights", "hotels"):
            errors.append(
                f"data/business/meta/usage-questions.yaml: group '{gname}': "
                f"assumed_reward_kind must be 'flights' or 'hotels', got {assumed!r}")
        for key in items:
            if key in usage_keys_all:
                errors.append(
                    f"data/business/meta/usage-questions.yaml: item key '{key}' appears "
                    f"in more than one group — keys must be globally unique")
            usage_keys_all.add(key)
            if not (items[key] or {}).get("label"):
                errors.append(
                    f"data/business/meta/usage-questions.yaml: item '{key}' "
                    f"(group '{gname}') is missing a label")

    # Program integrity — same contract as the consumer table.
    reward_kinds = {"cashback", "flights", "hotels"}
    for name in sorted(programs):
        entry = programs_registry[name] or {}
        rf = entry.get("redeems_for")
        if (not isinstance(rf, list) or any(k not in reward_kinds for k in rf)
                or len(set(rf)) != len(rf)):
            errors.append(
                f"data/business/meta/point-valuations.yaml: program '{name}': "
                f"redeems_for must be a list of unique values from "
                f"{sorted(reward_kinds)}, got {rf!r}")
        for key in ("floor_cpp", "optimistic_cpp"):
            v = entry.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors.append(
                    f"data/business/meta/point-valuations.yaml: program '{name}': "
                    f"{key} must be a number, got {v!r}")
        lk = entry.get("loyalty_keys")
        if isinstance(rf, list) and "cashback" not in rf:
            if not isinstance(lk, list) or not lk:
                errors.append(
                    f"data/business/meta/point-valuations.yaml: program '{name}' has "
                    f"no cashback path and must carry non-empty loyalty_keys")
            else:
                for k in lk:
                    if k not in usage_keys_all:
                        errors.append(
                            f"data/business/meta/point-valuations.yaml: program "
                            f"'{name}': loyalty_keys entry '{k}' is not a "
                            f"usage-questions item")
        elif lk is not None:
            errors.append(
                f"data/business/meta/point-valuations.yaml: program '{name}' redeems "
                f"for cashback — loyalty_keys must be absent")

    # Cross-dataset drift check (plan 22): overlapping programs must agree with
    # the consumer table — UR is UR regardless of which card earned it. Warning,
    # not error: the datasets are deliberately decoupled.
    if CONSUMER_VALUATIONS.exists():
        consumer_programs = load_yaml(CONSUMER_VALUATIONS)["programs"]
        for name in sorted(programs & set(consumer_programs)):
            for key in ("floor_cpp", "optimistic_cpp"):
                b = (programs_registry[name] or {}).get(key)
                c = (consumer_programs[name] or {}).get(key)
                if b != c:
                    warnings.append(
                        f"data/business/meta/point-valuations.yaml: program '{name}': "
                        f"{key} {b!r} disagrees with the consumer table ({c!r}) — "
                        f"the same currency should be valued identically")

    for name in sorted(merchants):
        entry = merchants_registry[name] or {}
        cat = entry.get("category")
        if cat not in categories:
            errors.append(
                f"data/business/meta/merchants.yaml: merchant '{name}': category must "
                f"be a key in categories.yaml, got {cat!r}")

    # issuer-rules integrity: typed fields; exception ids checked against the
    # corpus after the card loop (warning while the corpus is incomplete).
    for iname in sorted(issuer_rules):
        rules = issuer_rules[iname] or {}
        for bool_key in ("gate_524", "adds_to_524", "charge_exempt",
                         "once_per_lifetime_bonus"):
            v = rules.get(bool_key)
            if v is not None and not isinstance(v, bool):
                errors.append(
                    f"data/business/meta/issuer-rules.yaml: issuer '{iname}': "
                    f"{bool_key} must be boolean, got {v!r}")
        limit = rules.get("credit_card_limit")
        if limit is not None and (isinstance(limit, bool)
                                  or not isinstance(limit, int) or limit < 1):
            errors.append(
                f"data/business/meta/issuer-rules.yaml: issuer '{iname}': "
                f"credit_card_limit must be a positive integer, got {limit!r}")
        exc = rules.get("adds_to_524_exceptions")
        if exc is not None and (not isinstance(exc, list)
                                or any(not isinstance(e, str) for e in exc)):
            errors.append(
                f"data/business/meta/issuer-rules.yaml: issuer '{iname}': "
                f"adds_to_524_exceptions must be a list of card-id strings")

    card_files = sorted(CARDS_DIR.glob("*/*.yaml"))
    if not card_files:
        print(f"ERROR: no business card files found under {CARDS_DIR}")
        return 1

    seen_ids: dict[str, Path] = {}
    referenced_usage_keys: set[str] = {
        k for entry in programs_registry.values()
        for k in ((entry or {}).get("loyalty_keys") or [])}
    gateway_programs = {name for name, entry in programs_registry.items()
                        if (entry or {}).get("transfer_gateway_required")}
    programs_in_use: set[str] = set()
    programs_with_gateway: set[str] = set()

    for path in card_files:
        rel = path.relative_to(ROOT)
        try:
            card = load_yaml(path)
        except yaml.YAMLError as e:
            errors.append(f"{rel}: invalid YAML: {e}")
            continue

        schema_errors = sorted(validator.iter_errors(card),
                               key=lambda e: list(e.absolute_path))
        for e in schema_errors:
            loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
            errors.append(f"{rel}: schema violation at {loc}: {e.message}")
        if schema_errors:
            continue

        if card["id"] != path.stem:
            errors.append(f"{rel}: id '{card['id']}' does not match filename '{path.stem}'")
        if card["issuer"] != path.parent.name:
            errors.append(f"{rel}: issuer '{card['issuer']}' does not match directory '{path.parent.name}'")
        if card["issuer"] not in issuer_rules:
            errors.append(
                f"{rel}: issuer '{card['issuer']}' has no entry in "
                f"data/business/meta/issuer-rules.yaml — every business issuer "
                f"must declare its application rules (empty {{}} is fine)")
        if card["id"] in seen_ids and seen_ids[card["id"]] != path:
            errors.append(f"{rel}: duplicate card id '{card['id']}' (also in {seen_ids[card['id']].relative_to(ROOT)})")
        seen_ids[card["id"]] = path

        if card["currency"]["program"] not in programs:
            errors.append(f"{rel}: unknown point-valuation program '{card['currency']['program']}'")
        if card["currency"]["type"] == "cash" and card["currency"]["program"] != "cash":
            errors.append(f"{rel}: cash card must use program 'cash', got '{card['currency']['program']}'")
        programs_in_use.add(card["currency"]["program"])
        if card.get("unlocks_transfers"):
            if card["currency"]["program"] not in gateway_programs:
                errors.append(
                    f"{rel}: unlocks_transfers on program '{card['currency']['program']}', "
                    f"which is not transfer_gateway_required")
            else:
                programs_with_gateway.add(card["currency"]["program"])

        has_portal_lines = any(cr.get("portal_only") for cr in card["category_rewards"])
        has_portal_credits = any(c.get("portal_only") for c in card["credits"])
        if (has_portal_lines or has_portal_credits) and "portal" not in card:
            errors.append(
                f"{rel}: portal_only reward lines/credits but no top-level portal key")
        elif "portal" in card and not (has_portal_lines or has_portal_credits):
            warnings.append(
                f"{rel}: portal '{card['portal']}' declared but nothing is portal_only")

        for i, cr in enumerate(card["category_rewards"]):
            if cr["category"] not in categories:
                errors.append(f"{rel}: category_rewards[{i}]: unknown category '{cr['category']}'")
        for i, mr in enumerate(card["merchant_rewards"]):
            if mr["merchant"] not in merchants:
                errors.append(f"{rel}: merchant_rewards[{i}]: unknown merchant '{mr['merchant']}'")

        atn = card.get("adaptive_top_n")
        if atn:
            elig = atn["eligible_categories"]
            for j, c in enumerate(elig):
                if c not in categories:
                    errors.append(f"{rel}: adaptive_top_n.eligible_categories[{j}]: unknown category '{c}'")
            if len(set(elig)) != len(elig):
                errors.append(f"{rel}: adaptive_top_n.eligible_categories has duplicates")
            if atn["n"] >= len(elig):
                errors.append(
                    f"{rel}: adaptive_top_n.n ({atn['n']}) must be smaller than the "
                    f"eligible_categories menu ({len(elig)}) — otherwise it's a plain "
                    f"multi-category reward, model it as category_rewards")
            overlap = set(elig) & {cr["category"] for cr in card["category_rewards"]}
            if overlap:
                errors.append(
                    f"{rel}: adaptive_top_n eligible categories also appear in "
                    f"category_rewards ({sorted(overlap)}) — the top-n line replaces "
                    f"them; a static reward on the same category is ambiguous")

        pricing = card["pricing"]
        if pricing["model"] == "annual_fee":
            if "annual_fee_usd" not in pricing:
                errors.append(f"{rel}: pricing.model annual_fee requires annual_fee_usd")
            for k in ("per_seat_monthly_usd", "free_tier", "platform_fee_note"):
                if k in pricing:
                    errors.append(f"{rel}: pricing.{k} is per_seat-only, but model is annual_fee")
        else:  # per_seat
            if pricing.get("free_tier") is not True:
                errors.append(
                    f"{rel}: pricing.model per_seat requires free_tier: true — the V1 "
                    f"optimizer scores per-seat cards at $0 and has no paid-tier "
                    f"scoring; a per-seat card with no free tier can't be scored yet")
            for k in ("annual_fee_usd", "first_year_waived", "fee_refund_spend_usd"):
                if k in pricing:
                    errors.append(f"{rel}: pricing.{k} is annual_fee-only, but model is per_seat")

        appr = card["business_approval"]
        if appr.get("min_personal_fico_tier") and not appr["personal_guarantee"]:
            errors.append(
                f"{rel}: business_approval.min_personal_fico_tier is set but "
                f"personal_guarantee is false — no-PG cards don't pull personal credit")
        if not appr["personal_guarantee"]:
            anchors = ("requires_ein", "min_cash_balance_usd",
                       "min_annual_revenue_usd", "funding_qualifies")
            if not any(appr.get(k) for k in anchors):
                errors.append(
                    f"{rel}: business_approval: personal_guarantee false but no "
                    f"business underwriting anchor ({', '.join(anchors)}) — a no-PG "
                    f"card must state what it underwrites on")

        for i, credit in enumerate(card["credits"]):
            cat = credit.get("category")
            if cat is not None and cat not in categories:
                errors.append(f"{rel}: credits[{i}]: unknown category '{cat}'")
            if "amount_points" in credit and card["currency"]["type"] != "points":
                errors.append(f"{rel}: credits[{i}]: amount_points on a cash card")
            referenced_usage_keys.update(credit.get("usage_keys", []))
            for k in credit.get("usage_keys", []):
                if k not in usage_keys_all:
                    errors.append(f"{rel}: credits[{i}]: usage_keys entry '{k}' is not a usage-questions item")
            if credit.get("automatic") and (credit.get("usage_keys") or cat is not None):
                errors.append(
                    f"{rel}: credits[{i}]: automatic: true may not be combined with "
                    f"usage_keys or category")
            if not credit.get("automatic") and not credit.get("usage_keys") and cat is None:
                errors.append(
                    f"{rel}: credits[{i}] '{credit['name']}': un-gated credit — needs "
                    f"usage_keys, a category, or automatic: true")
            if "expires" in credit:
                if date.fromisoformat(credit["expires"]) < date.today():
                    warnings.append(f"{rel}: credits[{i}] '{credit['name']}' EXPIRED {credit['expires']} — re-check")

        lpr = card.get("large_purchase_rate")
        if lpr and lpr["rate"] <= card["base_rate"]:
            errors.append(
                f"{rel}: large_purchase_rate {lpr['rate']} must exceed base_rate "
                f"{card['base_rate']} — otherwise it never wins a bucket")

        # shared_cap_id groups: >= 2 members, identical pool. The
        # large_purchase_rate cap may join a group (Amex $2M pool spans the
        # category lines and the $5k+ line).
        cap_groups: dict[str, list] = {}
        for kind_name, rewards in (("category_rewards", card["category_rewards"]),
                                   ("merchant_rewards", card["merchant_rewards"])):
            for i, rw in enumerate(rewards):
                cap = rw.get("cap")
                if cap and "shared_cap_id" in cap:
                    cap_groups.setdefault(cap["shared_cap_id"], []).append(
                        (f"{kind_name}[{i}]", cap))
        if lpr and lpr.get("cap", {}).get("shared_cap_id"):
            cap = lpr["cap"]
            cap_groups.setdefault(cap["shared_cap_id"], []).append(
                ("large_purchase_rate", cap))
        for gid, members in sorted(cap_groups.items()):
            if len(members) < 2:
                errors.append(f"{rel}: {members[0][0]}: shared_cap_id '{gid}' has only one member")
            pools = {(c["period"], c["max_spend_usd"]) for _, c in members}
            if len(pools) > 1:
                errors.append(f"{rel}: shared_cap_id '{gid}': members disagree on the pool ({sorted(pools)})")

        if path.stem not in backlog:
            warnings.append(
                f"{rel}: not listed in docs/business-card-backlog.md — add it; the "
                f"backlog tracks curation + human verification for the business corpus")

        supported = {block for src in card["sources"] for block in src["supports"]}
        populated = {"identity", "currency", "base_rate", "pricing",
                     "business_approval", "employee_cards", "payment_type"}
        for block in ("category_rewards", "merchant_rewards", "credits", "benefit_flags"):
            if card[block]:
                populated.add(block)
        for block in ("adaptive_top_n", "large_purchase_rate", "pooling",
                      "integrations", "float_days"):
            if block in card:
                populated.add(block)
        if card["signup_bonus"] is not None:
            populated.add("signup_bonus")
        for block in sorted(populated - supported):
            warnings.append(f"{rel}: UNSOURCED — no entry in `sources` supports the '{block}' block")

        bonus = card["signup_bonus"]
        if bonus is not None and "tiers" in bonus:
            reqs = [t["spend_requirement_usd"] for t in bonus["tiers"]]
            if reqs and reqs[0] <= bonus["spend_requirement_usd"]:
                errors.append(f"{rel}: signup_bonus.tiers[0] spend requirement {reqs[0]} must exceed the base requirement {bonus['spend_requirement_usd']}")
            if reqs != sorted(reqs) or len(set(reqs)) != len(reqs):
                errors.append(f"{rel}: signup_bonus.tiers spend requirements must strictly ascend, got {reqs}")
        if bonus is not None and "expires" in bonus:
            if date.fromisoformat(bonus["expires"]) < date.today():
                warnings.append(f"{rel}: signup bonus offer EXPIRED {bonus['expires']} — re-check")

        verified = date.fromisoformat(card["verification"]["last_verified_date"])
        if verified > date.today():
            errors.append(f"{rel}: last_verified_date {verified} is in the future")
        elif date.today() - verified > timedelta(days=STALE_DAYS):
            warnings.append(f"{rel}: STALE — last verified {verified} (> {STALE_DAYS} days ago)")
        if card["verification"]["confidence"] == "low":
            warnings.append(f"{rel}: confidence is 'low' — data needs human verification")

    # Post-loop cross-checks.
    for iname in sorted(issuer_rules):
        for cid in (issuer_rules[iname] or {}).get("adds_to_524_exceptions") or []:
            if cid not in seen_ids:
                warnings.append(
                    f"data/business/meta/issuer-rules.yaml: issuer '{iname}': "
                    f"adds_to_524_exceptions id '{cid}' is not (yet) a card in the "
                    f"corpus — fine while curation is incomplete, re-check at 22B end")

    for prog in sorted((gateway_programs & programs_in_use) - programs_with_gateway):
        warnings.append(
            f"data/business/meta/point-valuations.yaml: program '{prog}' is "
            f"transfer_gateway_required but no business card carries "
            f"unlocks_transfers for it — reachable only via a personal gateway "
            f"card in the profile")

    for key in sorted(usage_keys_all - referenced_usage_keys):
        warnings.append(
            f"data/business/meta/usage-questions.yaml: item '{key}' is referenced by "
            f"no card usage_keys and no program loyalty_keys — remove it")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\n{len(card_files)} business card file(s) checked: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
