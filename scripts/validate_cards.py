#!/usr/bin/env python3
"""Validate every card YAML in data/cards/ against the schema and meta registries.

Checks, per card file:
  1. Valid YAML and conforms to data/schema/card.schema.json.
  2. `id` matches the filename and `issuer` matches the parent directory.
  3. Every category / merchant / currency.program / credit category / choice-option
     key exists in the data/meta/ registries; pseudo-categories may not be used as
     credit categories or choice options; a `choice` block appears only on the
     'choice' pseudo-category, at most once per card; shared_cap_id groups have
     >= 2 members with identical period and max_spend_usd; point-denominated
     credits (amount_points) only on points cards; signup-bonus tier spend
     requirements exceed the base requirement and strictly ascend;
     conditional_rate / base_rate_conditional strictly exceed their baseline rate;
     rotating rewards carry a quarterly cap (uncapped rotating is a hard error
     in the optimizer). Registry integrity: every merchants.yaml entry maps to
     a real (non-pseudo) category, and every point-valuations.yaml program has
     numeric floor_cpp / optimistic_cpp and a valid redeems_for list.
     Confirmed-usage gating (plan 07): every credit carries at least one of
     usage_keys / category / automatic (else it would be free money for every
     user); automatic is exclusive of the other two; usage_keys / loyalty_keys
     must be usage-questions.yaml items (which must themselves be
     statement-descriptors.yaml keys); the card-level portal must be a
     statement-descriptors.yaml key (portal use is assumed by the optimizer,
     so portals are not questionnaire items); non-cashback programs require
     loyalty_keys and cashback programs may not carry them; cards with
     portal_only reward lines must declare their portal; unlocks_transfers is
     allowed only on transfer_gateway_required programs. Warnings: a monthly/
     quarterly USD statement credit that is category-only (probably needs
     usage_keys), a portal with no portal_only lines, any questionnaire
     item nothing references, and a transfer_gateway_required program
     whose cards include no gateway card (optimistic_cpp unreachable).
  4. `verification.last_verified_date` is not in the future and not stale
     (> STALE_DAYS old → warning; CI stays green so staleness nags, not blocks).
  5. The card is listed in docs/card-backlog.md — the backlog is the tracking
     source of truth for human verification, so no card file may exist off-list.

Exit code 0 on success (warnings allowed), 1 on any error.
Usage: python3 scripts/validate_cards.py
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "data" / "cards"
SCHEMA_PATH = ROOT / "data" / "schema" / "card.schema.json"
META_DIR = ROOT / "data" / "meta"
BACKLOG_PATH = ROOT / "docs" / "card-backlog.md"
STALE_DAYS = 183  # ~6 months


def load_yaml(path: Path):
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema)

    categories_registry = load_yaml(META_DIR / "categories.yaml")["categories"]
    categories = set(categories_registry)
    pseudo_categories = {k for k, v in categories_registry.items() if (v or {}).get("pseudo")}
    merchants_registry = load_yaml(META_DIR / "merchants.yaml")["merchants"]
    merchants = set(merchants_registry)
    programs_registry = load_yaml(META_DIR / "point-valuations.yaml")["programs"]
    programs = set(programs_registry)
    descriptors_registry = load_yaml(META_DIR / "statement-descriptors.yaml")["descriptors"]
    descriptors = set(descriptors_registry)
    questions_registry = load_yaml(META_DIR / "usage-questions.yaml")["groups"]

    backlog = BACKLOG_PATH.read_text() if BACKLOG_PATH.exists() else ""

    errors: list[str] = []
    warnings: list[str] = []

    # usage-questions.yaml is the confirmation vocabulary for credits[].usage_keys,
    # program loyalty_keys, and user.confirmed_usage — the optimizer and UI both
    # trust it, so its integrity is checked before any card is.
    usage_keys_all: set[str] = set()
    for gname in sorted(questions_registry):
        group = questions_registry[gname] or {}
        items = group.get("items")
        if not group.get("label") or not group.get("prompt") or not items:
            errors.append(
                f"data/meta/usage-questions.yaml: group '{gname}' must have a label, "
                f"a prompt, and a non-empty items map")
            continue
        # Brand-loyalty groups: assumed_reward_kind marks the group's items as
        # assumed-usable for credit gating when the matching reward kind is in
        # user.reward_preferences (the optimizer's assumed_usage()); only
        # flights/hotels make sense — "would book whichever brand is best".
        assumed = group.get("assumed_reward_kind")
        if assumed is not None and assumed not in ("flights", "hotels"):
            errors.append(
                f"data/meta/usage-questions.yaml: group '{gname}': "
                f"assumed_reward_kind must be 'flights' or 'hotels', got {assumed!r}")
        for key in items:
            if key in usage_keys_all:
                errors.append(
                    f"data/meta/usage-questions.yaml: item key '{key}' appears in more "
                    f"than one group — keys must be globally unique")
            usage_keys_all.add(key)
            if key not in descriptors:
                errors.append(
                    f"data/meta/usage-questions.yaml: item '{key}' (group '{gname}') is "
                    f"not a key in statement-descriptors.yaml")
            if not (items[key] or {}).get("label"):
                errors.append(
                    f"data/meta/usage-questions.yaml: item '{key}' (group '{gname}') "
                    f"is missing a label")

    # Every program must classify what its currency redeems for — the optimizer's
    # reward-preference filter (user.reward_preferences) depends on it — and carry
    # both cpp figures, which the optimizer reads unconditionally for every card.
    reward_kinds = {"cashback", "flights", "hotels"}
    for name in sorted(programs):
        entry = programs_registry[name] or {}
        rf = entry.get("redeems_for")
        if (not isinstance(rf, list) or any(k not in reward_kinds for k in rf)
                or len(set(rf)) != len(rf)):
            errors.append(
                f"data/meta/point-valuations.yaml: program '{name}': redeems_for must be "
                f"a list of unique values from {sorted(reward_kinds)} (empty allowed for "
                f"merchant-restricted currencies), got {rf!r}")
        for key in ("floor_cpp", "optimistic_cpp"):
            v = entry.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errors.append(
                    f"data/meta/point-valuations.yaml: program '{name}': {key} must be "
                    f"a number, got {v!r}")
        # Lock-in currencies (no cash-out path) must say whose loyalty unlocks
        # optimistic_cpp; cashback currencies must not — their floor is cash.
        lk = entry.get("loyalty_keys")
        if isinstance(rf, list) and "cashback" not in rf:
            if not isinstance(lk, list) or not lk:
                errors.append(
                    f"data/meta/point-valuations.yaml: program '{name}' has no cashback "
                    f"path and must carry non-empty loyalty_keys (usage-questions items)")
            else:
                for k in lk:
                    if k not in usage_keys_all:
                        errors.append(
                            f"data/meta/point-valuations.yaml: program '{name}': "
                            f"loyalty_keys entry '{k}' is not a usage-questions item")
        elif lk is not None:
            errors.append(
                f"data/meta/point-valuations.yaml: program '{name}' redeems for cashback "
                f"— loyalty_keys must be absent (no loyalty needed to realize cash)")

    # Every merchant must route to a real category — the optimizer moves
    # merchant-level spend out of that category bucket and crashes on a bad key.
    for name in sorted(merchants):
        cat = (merchants_registry[name] or {}).get("category")
        if cat not in categories or cat in pseudo_categories:
            errors.append(
                f"data/meta/merchants.yaml: merchant '{name}': category must be a real "
                f"(non-pseudo) category from categories.yaml, got {cat!r}")

    # statement-descriptors.yaml drives the benefit-usage detector (plan 14):
    # aggregator_prefix, when present, must be boolean true — the detector
    # strips those prefixes and re-matches the remainder.
    DESC = "data/meta/statement-descriptors.yaml"
    for key, entry in sorted(descriptors_registry.items()):
        flag = (entry or {}).get("aggregator_prefix")
        if flag is not None and flag is not True:
            errors.append(f"{DESC}: descriptor '{key}': aggregator_prefix must be "
                          f"boolean true when present, got {flag!r}")

    card_files = sorted(CARDS_DIR.glob("*/*.yaml"))
    if not card_files:
        print(f"ERROR: no card files found under {CARDS_DIR}")
        return 1

    seen_ids: dict[str, Path] = {}
    # Keys actually used anywhere — seeded with program loyalty_keys; card
    # usage_keys are added in the loop. Unreferenced registry items are
    # warned at the end: every questionnaire item must earn its question.
    referenced_usage_keys: set[str] = {
        k for entry in programs_registry.values()
        for k in ((entry or {}).get("loyalty_keys") or [])}
    # transfer_gateway_required programs (plan 07 addendum): track which get a
    # gateway card, so an unreachable optimistic_cpp is flagged after the loop.
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

        schema_errors = sorted(validator.iter_errors(card), key=lambda e: list(e.absolute_path))
        for e in schema_errors:
            loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
            errors.append(f"{rel}: schema violation at {loc}: {e.message}")
        if schema_errors:
            continue  # structural checks below assume a schema-valid card

        if card["id"] != path.stem:
            errors.append(f"{rel}: id '{card['id']}' does not match filename '{path.stem}'")
        if card["issuer"] != path.parent.name:
            errors.append(f"{rel}: issuer '{card['issuer']}' does not match directory '{path.parent.name}'")
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
                    f"which is not transfer_gateway_required — either the currency "
                    f"transfers natively (drop the flag) or the program entry in "
                    f"point-valuations.yaml needs the gate")
            else:
                programs_with_gateway.add(card["currency"]["program"])
        # Portal use is assumed by the optimizer (no questionnaire gate), but the
        # key must still name a real descriptor so statement import categorizes
        # portal purchases and typos don't slip through.
        if "portal" in card and card["portal"] not in descriptors:
            errors.append(
                f"{rel}: portal '{card['portal']}' is not a key in "
                f"statement-descriptors.yaml")
        has_portal_lines = any(cr.get("portal_only") for cr in card["category_rewards"])
        if has_portal_lines and "portal" not in card:
            errors.append(
                f"{rel}: card has portal_only reward lines but no top-level portal key — "
                f"the optimizer names it in the portal-rate note")
        elif "portal" in card and not has_portal_lines:
            warnings.append(
                f"{rel}: portal '{card['portal']}' declared but no reward line is "
                f"portal_only — drop it or mark the portal lines")

        choice_rewards = 0
        earn_ratio_rewards = 0
        for i, cr in enumerate(card["category_rewards"]):
            if cr["category"] not in categories:
                errors.append(f"{rel}: category_rewards[{i}]: unknown category '{cr['category']}'")
            er = cr.get("earn_ratio")
            if er is not None:
                earn_ratio_rewards += 1
                if cr["category"] in pseudo_categories:
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio is not allowed on a pseudo-category")
                if card["currency"]["type"] != "points":
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio needs a points currency to value its multiplier, got '{card['currency']['type']}'")
                den = er.get("denominator_category")
                if den not in categories or den in pseudo_categories:
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio.denominator_category must be a non-pseudo category, got {den!r}")
                tiers = er.get("tiers") or []
                mins = [t.get("min_ratio") for t in tiers]
                if not tiers or mins[0] != 0:
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio.tiers must start with a min_ratio 0 tier")
                if mins != sorted(mins):
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio.tiers must be sorted ascending by min_ratio")
                if any(t.get("rate", 0) > cr["rate"] + 1e-9 for t in tiers):
                    errors.append(f"{rel}: category_rewards[{i}]: earn_ratio tier rate exceeds the reward's top-level rate {cr['rate']} (rate must be the max tier rate)")
            if cr["category"] == "choice":
                choice_rewards += 1
                for j, opt in enumerate(cr.get("choice", {}).get("options", [])):
                    if opt not in categories:
                        errors.append(f"{rel}: category_rewards[{i}]: choice.options[{j}]: unknown category '{opt}'")
                    elif opt in pseudo_categories:
                        errors.append(f"{rel}: category_rewards[{i}]: choice.options[{j}]: '{opt}' is a pseudo-category and may not be a choice option")
            elif "choice" in cr:
                errors.append(f"{rel}: category_rewards[{i}]: a choice block is only allowed on the 'choice' pseudo-category")
            if cr["category"] == "rotating":
                cap = cr.get("cap")
                if not cap:
                    errors.append(f"{rel}: category_rewards[{i}]: rotating reward has no cap — an uncapped rotating reward is a hard error that kills every optimizer run")
                elif cap.get("period") != "quarterly":
                    errors.append(f"{rel}: category_rewards[{i}]: rotating cap period must be 'quarterly' (the optimizer models rotating room as four quarterly windows), got {cap.get('period')!r}")
        if choice_rewards > 1:
            errors.append(f"{rel}: {choice_rewards} 'choice' category rewards — the optimizer supports at most one per card")
        if earn_ratio_rewards > 1:
            errors.append(f"{rel}: {earn_ratio_rewards} earn_ratio category rewards — the optimizer supports at most one per card")
        for i, mr in enumerate(card["merchant_rewards"]):
            if mr["merchant"] not in merchants:
                errors.append(f"{rel}: merchant_rewards[{i}]: unknown merchant '{mr['merchant']}'")
        for i, m in enumerate(card.get("closed_loop", {}).get("merchants", [])):
            if m not in merchants:
                errors.append(f"{rel}: closed_loop.merchants[{i}]: unknown merchant '{m}'")
        for i, credit in enumerate(card["credits"]):
            cat = credit.get("category")
            if cat is not None and cat not in categories:
                errors.append(f"{rel}: credits[{i}]: unknown category '{cat}'")
            elif cat in pseudo_categories:
                errors.append(f"{rel}: credits[{i}]: '{cat}' is a pseudo-category and may not be a credit category")
            if "amount_points" in credit and card["currency"]["type"] != "points":
                errors.append(f"{rel}: credits[{i}]: amount_points on a cash card — point-denominated credits need a points program to value them")
            referenced_usage_keys.update(credit.get("usage_keys", []))
            for k in credit.get("usage_keys", []):
                if k not in usage_keys_all:
                    errors.append(f"{rel}: credits[{i}]: usage_keys entry '{k}' is not a usage-questions item")
            if credit.get("automatic") and (credit.get("usage_keys") or cat is not None):
                errors.append(
                    f"{rel}: credits[{i}]: automatic: true may not be combined with "
                    f"usage_keys or category — an automatic credit needs no gate")
            if not credit.get("automatic") and not credit.get("usage_keys") and cat is None:
                errors.append(
                    f"{rel}: credits[{i}] '{credit['name']}': un-gated credit — every credit "
                    f"needs usage_keys (merchant/service/brand), a category (generic "
                    f"spend-offset), or automatic: true (anniversary-style); otherwise the "
                    f"optimizer would count it as free money for every user")
            if (credit.get("period") in ("monthly", "quarterly")
                    and credit.get("kind", "statement_credit") == "statement_credit"
                    and "amount_usd" in credit
                    and cat is not None and not credit.get("usage_keys")):
                warnings.append(
                    f"{rel}: credits[{i}] '{credit['name']}': {credit['period']} statement "
                    f"credit with category but no usage_keys — short-cycle coupons are almost "
                    f"always merchant-specific; verify it is genuinely merchant-agnostic")
            if "expires" in credit:
                expires = date.fromisoformat(credit["expires"])
                if expires < date.today():
                    warnings.append(f"{rel}: credits[{i}] '{credit['name']}' EXPIRED {expires} — re-check whether the promo was renewed and update")
            if credit.get("auto_expire") and "expires" not in credit:
                errors.append(f"{rel}: credits[{i}] '{credit['name']}': auto_expire requires expires — the daily expirer deletes the credit by its end date")

        # conditional_rate must genuinely be a boost over the stated baseline,
        # otherwise the baseline was recorded wrong (or the two are swapped).
        for kind_name, rewards in (("category_rewards", card["category_rewards"]),
                                   ("merchant_rewards", card["merchant_rewards"])):
            for i, rw in enumerate(rewards):
                cond = rw.get("conditional_rate")
                if cond and cond["rate"] <= rw["rate"]:
                    errors.append(f"{rel}: {kind_name}[{i}]: conditional_rate {cond['rate']} must exceed the baseline rate {rw['rate']} — the plain rate must be the unconditional baseline")
                # Limited-time earn rows: flag lapsed rates, and require an
                # end date behind any auto_expire marker (the expirer keys off it).
                if "expires" in rw:
                    exp = date.fromisoformat(rw["expires"])
                    if exp < date.today():
                        warnings.append(f"{rel}: {kind_name}[{i}] EXPIRED earn rate {exp} — re-check whether the promo was renewed and update or remove the row")
                if rw.get("auto_expire") and "expires" not in rw:
                    errors.append(f"{rel}: {kind_name}[{i}]: auto_expire requires expires — the daily expirer deletes the row by its end date")
        cond = card.get("base_rate_conditional")
        if cond and cond["rate"] <= card["base_rate"]:
            errors.append(f"{rel}: base_rate_conditional {cond['rate']} must exceed base_rate {card['base_rate']} — base_rate must be the unconditional baseline")

        # shared_cap_id: every group needs >= 2 members (else it's a typo or
        # pointless) all stating the same pool (period + max_spend_usd).
        cap_groups: dict[str, list] = {}
        for kind_name, rewards in (("category_rewards", card["category_rewards"]),
                                   ("merchant_rewards", card["merchant_rewards"])):
            for i, rw in enumerate(rewards):
                cap = rw.get("cap")
                if cap and "shared_cap_id" in cap:
                    cap_groups.setdefault(cap["shared_cap_id"], []).append(
                        (f"{kind_name}[{i}]", cap))
        for gid, members in sorted(cap_groups.items()):
            if len(members) < 2:
                errors.append(f"{rel}: {members[0][0]}: shared_cap_id '{gid}' has only one member — drop it or add the other entries sharing the pool")
            pools = {(c["period"], c["max_spend_usd"]) for _, c in members}
            if len(pools) > 1:
                errors.append(f"{rel}: shared_cap_id '{gid}': members disagree on the pool ({sorted(pools)}) — each entry must state the identical period and max_spend_usd")

        if path.stem not in backlog:
            warnings.append(
                f"{rel}: not listed in docs/card-backlog.md — add it; the backlog tracks human verification"
            )

        supported = {block for src in card["sources"] for block in src["supports"]}
        populated = {"identity", "currency", "base_rate", "fees", "approval"}
        for block in ("category_rewards", "merchant_rewards", "credits", "benefit_flags"):
            if card[block]:
                populated.add(block)
        if (card["signup_bonus"] is not None
                or card.get("signup_bonus_limited_time") is not None):
            populated.add("signup_bonus")
        if "closed_loop" in card:
            populated.add("closed_loop")
        if "relationship_boost" in card:
            populated.add("relationship_boost")
        if "required_membership" in card:
            populated.add("required_membership")
            rm = card["required_membership"]
            if rm.get("card_exclusive") and "annual_cost_usd" not in rm:
                errors.append(
                    f"{rel}: required_membership.card_exclusive is true but annual_cost_usd is "
                    "missing — the optimizer scores that cost, so it must be recorded"
                )
        for block in sorted(populated - supported):
            warnings.append(f"{rel}: UNSOURCED — no entry in `sources` supports the '{block}' block")

        def check_offer_tiers(offer, label):
            if "tiers" not in offer:
                return
            reqs = [t["spend_requirement_usd"] for t in offer["tiers"]]
            if reqs and reqs[0] <= offer["spend_requirement_usd"]:
                errors.append(f"{rel}: {label}.tiers[0] spend requirement {reqs[0]} must exceed the base requirement {offer['spend_requirement_usd']} (tiers are cumulative)")
            if reqs != sorted(reqs) or len(set(reqs)) != len(reqs):
                errors.append(f"{rel}: {label}.tiers spend requirements must strictly ascend, got {reqs}")

        bonus = card["signup_bonus"]
        lt_bonus = card.get("signup_bonus_limited_time")
        if bonus is not None:
            check_offer_tiers(bonus, "signup_bonus")
            # Belt-and-suspenders: the schema already rejects the removed
            # limited_time flag (additionalProperties:false), but re-flag it as a
            # clear migration error in case the schema regresses.
            if "limited_time" in bonus:
                errors.append(f"{rel}: signup_bonus.limited_time was removed — move a limited-time elevated offer into the sibling signup_bonus_limited_time (dual-bonus model)")
            if "expires" in bonus:
                expires = date.fromisoformat(bonus["expires"])
                if expires < date.today():
                    warnings.append(
                        f"{rel}: signup bonus offer EXPIRED {expires} — re-check the current offer and update"
                    )
        if lt_bonus is not None:
            check_offer_tiers(lt_bonus, "signup_bonus_limited_time")
            if "expires" not in lt_bonus:  # belt-and-suspenders (schema-required)
                errors.append(f"{rel}: signup_bonus_limited_time requires expires — a limited-time offer must state its end date")
            else:
                expires = date.fromisoformat(lt_bonus["expires"])
                if expires < date.today():
                    warnings.append(
                        f"{rel}: limited-time signup offer EXPIRED {expires} — re-check the current offer (the optimizer has already auto-reverted to the standard bonus; remove the lapsed offer or renew it)"
                    )
            if bonus is None:
                warnings.append(
                    f"{rel}: signup_bonus is null while a limited-time elevated offer exists — the card shows no bonus once it expires; SOURCE the standard bonus into signup_bonus"
                )

        verified = date.fromisoformat(card["verification"]["last_verified_date"])
        if verified > date.today():
            errors.append(f"{rel}: last_verified_date {verified} is in the future")
        elif date.today() - verified > timedelta(days=STALE_DAYS):
            warnings.append(
                f"{rel}: STALE — last verified {verified} (> {STALE_DAYS} days ago); re-check against issuer terms"
            )
        if card["verification"]["confidence"] == "low":
            warnings.append(f"{rel}: confidence is 'low' — data needs human verification")

    for prog in sorted((gateway_programs & programs_in_use) - programs_with_gateway):
        warnings.append(
            f"data/meta/point-valuations.yaml: program '{prog}' is "
            f"transfer_gateway_required but no card in the dataset carries "
            f"unlocks_transfers for it — its optimistic_cpp is unreachable")

    for key in sorted(usage_keys_all - referenced_usage_keys):
        warnings.append(
            f"data/meta/usage-questions.yaml: item '{key}' is referenced by no card "
            f"usage_keys and no program loyalty_keys — remove it so "
            f"users aren't asked a question that can't change any recommendation")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\n{len(card_files)} card file(s) checked: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
