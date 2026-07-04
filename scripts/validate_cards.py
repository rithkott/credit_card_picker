#!/usr/bin/env python3
"""Validate every card YAML in data/cards/ against the schema and meta registries.

Checks, per card file:
  1. Valid YAML and conforms to data/schema/card.schema.json.
  2. `id` matches the filename and `issuer` matches the parent directory.
  3. Every category / merchant / currency.program / credit category / choice-option
     key exists in the data/meta/ registries; pseudo-categories may not be used as
     credit categories or choice options; a `choice` block appears only on the
     'choice' pseudo-category, at most once per card.
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
    merchants = set(load_yaml(META_DIR / "merchants.yaml")["merchants"])
    programs = set(load_yaml(META_DIR / "point-valuations.yaml")["programs"])

    backlog = BACKLOG_PATH.read_text() if BACKLOG_PATH.exists() else ""

    card_files = sorted(CARDS_DIR.glob("*/*.yaml"))
    if not card_files:
        print(f"ERROR: no card files found under {CARDS_DIR}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: dict[str, Path] = {}

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

        choice_rewards = 0
        for i, cr in enumerate(card["category_rewards"]):
            if cr["category"] not in categories:
                errors.append(f"{rel}: category_rewards[{i}]: unknown category '{cr['category']}'")
            if cr["category"] == "choice":
                choice_rewards += 1
                for j, opt in enumerate(cr.get("choice", {}).get("options", [])):
                    if opt not in categories:
                        errors.append(f"{rel}: category_rewards[{i}]: choice.options[{j}]: unknown category '{opt}'")
                    elif opt in pseudo_categories:
                        errors.append(f"{rel}: category_rewards[{i}]: choice.options[{j}]: '{opt}' is a pseudo-category and may not be a choice option")
            elif "choice" in cr:
                errors.append(f"{rel}: category_rewards[{i}]: a choice block is only allowed on the 'choice' pseudo-category")
        if choice_rewards > 1:
            errors.append(f"{rel}: {choice_rewards} 'choice' category rewards — the optimizer supports at most one per card")
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

        if path.stem not in backlog:
            warnings.append(
                f"{rel}: not listed in docs/card-backlog.md — add it; the backlog tracks human verification"
            )

        supported = {block for src in card["sources"] for block in src["supports"]}
        populated = {"identity", "currency", "base_rate", "fees", "approval"}
        for block in ("category_rewards", "merchant_rewards", "credits", "benefit_flags"):
            if card[block]:
                populated.add(block)
        if card["signup_bonus"] is not None:
            populated.add("signup_bonus")
        if "closed_loop" in card:
            populated.add("closed_loop")
        for block in sorted(populated - supported):
            warnings.append(f"{rel}: UNSOURCED — no entry in `sources` supports the '{block}' block")

        bonus = card["signup_bonus"]
        if bonus is not None and "expires" in bonus:
            expires = date.fromisoformat(bonus["expires"])
            if expires < date.today():
                warnings.append(
                    f"{rel}: signup bonus offer EXPIRED {expires} — re-check the current offer and update"
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

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\n{len(card_files)} card file(s) checked: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
