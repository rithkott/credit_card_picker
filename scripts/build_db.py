#!/usr/bin/env python3
"""Compile the hand-curated YAML dataset into a normalized SQLite artifact
(docs/plans/10-optimizer-overhaul.md §4).

YAML stays the only source of truth; `data/build/cards.sqlite` is a
gitignored, deterministic build product: third-normal-form tables with FK
integrity (a belt-and-suspenders check on validate_cards.py), a `manifest`
table recording each source file's sha256, and a `meta.dataset_hash` that is
the staleness/determinism contract. Rebuilding from unchanged sources yields
a byte-identical file: fixed PRAGMAs, one transaction, rows inserted in
sorted (file, position) order, explicit integer keys, no timestamps.

Every YAML mapping is decomposed with a closed key set — an unexpected key is
a hard build error, so schema drift breaks the build instead of silently
dropping data. Numeric columns are declared without a type name (BLOB
affinity) so SQLite stores ints as INTEGER and floats as REAL exactly as
curated; booleans are INTEGER 0/1 and restored to bool by the loader.

Usage:
  python3 scripts/build_db.py [--out data/build/cards.sqlite]
Exit codes: 0 ok, 2 dataset/build error.
"""

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "data" / "cards"
META_DIR = ROOT / "data" / "meta"
DEFAULT_OUT = ROOT / "data" / "build" / "cards.sqlite"

DB_SCHEMA_VERSION = 1
APPLICATION_ID = 0xCA4D5DB  # "card s db", stamped into the SQLite header

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE manifest (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE categories (
  key TEXT PRIMARY KEY, label TEXT NOT NULL, pseudo INTEGER) WITHOUT ROWID;
CREATE TABLE merchants (
  key TEXT PRIMARY KEY, label TEXT NOT NULL,
  category_key TEXT NOT NULL REFERENCES categories(key)) WITHOUT ROWID;
CREATE TABLE programs (
  key TEXT PRIMARY KEY, label TEXT NOT NULL,
  floor_cpp, optimistic_cpp,
  transfer_gateway_required INTEGER) WITHOUT ROWID;
CREATE TABLE program_redeems_for (
  program_key TEXT NOT NULL REFERENCES programs(key),
  position INTEGER NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY (program_key, position)) WITHOUT ROWID;
CREATE TABLE usage_groups (
  key TEXT PRIMARY KEY, position INTEGER NOT NULL,
  label TEXT NOT NULL, prompt TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE usage_items (
  key TEXT PRIMARY KEY,
  group_key TEXT NOT NULL REFERENCES usage_groups(key),
  position INTEGER NOT NULL, label TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE program_loyalty_keys (
  program_key TEXT NOT NULL REFERENCES programs(key),
  position INTEGER NOT NULL,
  usage_key TEXT NOT NULL REFERENCES usage_items(key),
  PRIMARY KEY (program_key, position)) WITHOUT ROWID;

CREATE TABLE statement_descriptors (
  key TEXT PRIMARY KEY, position INTEGER NOT NULL,
  label TEXT NOT NULL, benefit_context TEXT) WITHOUT ROWID;
CREATE TABLE descriptor_patterns (
  descriptor_key TEXT NOT NULL REFERENCES statement_descriptors(key),
  position INTEGER NOT NULL, pattern TEXT NOT NULL,
  PRIMARY KEY (descriptor_key, position)) WITHOUT ROWID;
CREATE TABLE rule_descriptor_categories (
  descriptor_key TEXT NOT NULL REFERENCES statement_descriptors(key),
  category_key TEXT NOT NULL REFERENCES categories(key),
  PRIMARY KEY (descriptor_key)) WITHOUT ROWID;
CREATE TABLE rule_aggregator_prefixes (
  descriptor_key TEXT NOT NULL REFERENCES statement_descriptors(key),
  fallback_category TEXT REFERENCES categories(key),
  PRIMARY KEY (descriptor_key)) WITHOUT ROWID;
CREATE TABLE rule_unmapped (
  descriptor_key TEXT NOT NULL REFERENCES statement_descriptors(key),
  position INTEGER NOT NULL,
  PRIMARY KEY (descriptor_key)) WITHOUT ROWID;
CREATE TABLE rule_keywords (
  category_key TEXT NOT NULL REFERENCES categories(key),
  position INTEGER NOT NULL, pattern TEXT NOT NULL,
  PRIMARY KEY (category_key, position)) WITHOUT ROWID;
CREATE TABLE rule_issuer_categories (
  issuer_label TEXT PRIMARY KEY,
  category_key TEXT NOT NULL REFERENCES categories(key)) WITHOUT ROWID;
CREATE TABLE rule_mcc_ranges (
  mcc_from INTEGER NOT NULL, mcc_to INTEGER NOT NULL,
  category_key TEXT NOT NULL REFERENCES categories(key),
  PRIMARY KEY (mcc_from)) WITHOUT ROWID;

CREATE TABLE issuers (slug TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE cards (
  id TEXT PRIMARY KEY,
  issuer_slug TEXT NOT NULL REFERENCES issuers(slug),
  name TEXT NOT NULL, network TEXT NOT NULL,
  currency_type TEXT NOT NULL,
  currency_program TEXT NOT NULL REFERENCES programs(key),
  base_rate,
  portal TEXT REFERENCES usage_items(key),
  unlocks_transfers INTEGER,
  max_annual_rewards_usd,
  annual_fee_usd, first_year_waived INTEGER, foreign_transaction_pct,
  approval_credit_tier TEXT NOT NULL, approval_estimated_min_score,
  approval_notes TEXT,
  last_verified_date TEXT NOT NULL, verified_by TEXT NOT NULL,
  confidence TEXT NOT NULL,
  notes TEXT) WITHOUT ROWID;
CREATE TABLE base_rate_conditionals (
  card_id TEXT PRIMARY KEY REFERENCES cards(id),
  rate, requires TEXT NOT NULL, note TEXT) WITHOUT ROWID;
CREATE TABLE category_rewards (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES cards(id),
  position INTEGER NOT NULL,
  category_key TEXT NOT NULL REFERENCES categories(key),
  rate, portal_only INTEGER, requires_enrollment INTEGER, notes TEXT);
CREATE TABLE merchant_rewards (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES cards(id),
  position INTEGER NOT NULL,
  merchant_key TEXT NOT NULL REFERENCES merchants(key),
  rate, notes TEXT);
CREATE TABLE caps (
  reward_kind TEXT NOT NULL CHECK (reward_kind IN ('category', 'merchant')),
  reward_id INTEGER NOT NULL,
  period TEXT NOT NULL, max_spend_usd, fallback_rate,
  shared_cap_id TEXT,
  PRIMARY KEY (reward_kind, reward_id)) WITHOUT ROWID;
CREATE TABLE rotations (
  reward_id INTEGER PRIMARY KEY REFERENCES category_rewards(id),
  frequency TEXT NOT NULL, requires_activation INTEGER NOT NULL,
  note TEXT NOT NULL);
CREATE TABLE choices (
  reward_id INTEGER PRIMARY KEY REFERENCES category_rewards(id),
  note TEXT NOT NULL);
CREATE TABLE choice_options (
  reward_id INTEGER NOT NULL REFERENCES choices(reward_id),
  position INTEGER NOT NULL,
  category_key TEXT NOT NULL REFERENCES categories(key),
  PRIMARY KEY (reward_id, position)) WITHOUT ROWID;
CREATE TABLE reward_conditional_rates (
  reward_kind TEXT NOT NULL CHECK (reward_kind IN ('category', 'merchant')),
  reward_id INTEGER NOT NULL,
  rate, requires TEXT NOT NULL, note TEXT,
  PRIMARY KEY (reward_kind, reward_id)) WITHOUT ROWID;
CREATE TABLE credits (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES cards(id),
  position INTEGER NOT NULL,
  name TEXT NOT NULL, kind TEXT,
  amount_usd, amount_points,
  period TEXT NOT NULL,
  category_key TEXT REFERENCES categories(key),
  automatic INTEGER, unlock_spend_usd, requires_enrollment INTEGER,
  expires TEXT, realistic_capture_rate_note TEXT NOT NULL, notes TEXT);
CREATE TABLE credit_usage_keys (
  credit_id INTEGER NOT NULL REFERENCES credits(id),
  position INTEGER NOT NULL,
  usage_key TEXT NOT NULL REFERENCES usage_items(key),
  PRIMARY KEY (credit_id, position)) WITHOUT ROWID;
CREATE TABLE signup_bonuses (
  card_id TEXT PRIMARY KEY REFERENCES cards(id),
  points, usd, spend_requirement_usd, window_months,
  first_year_match INTEGER, limited_time INTEGER,
  expires TEXT, notes TEXT) WITHOUT ROWID;
CREATE TABLE bonus_tiers (
  card_id TEXT NOT NULL REFERENCES signup_bonuses(card_id),
  position INTEGER NOT NULL,
  points, usd, spend_requirement_usd,
  PRIMARY KEY (card_id, position)) WITHOUT ROWID;
CREATE TABLE required_memberships (
  card_id TEXT PRIMARY KEY REFERENCES cards(id),
  name TEXT NOT NULL, annual_cost_usd, card_exclusive INTEGER,
  note TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE closed_loops (
  card_id TEXT PRIMARY KEY REFERENCES cards(id), note TEXT) WITHOUT ROWID;
CREATE TABLE closed_loop_merchants (
  card_id TEXT NOT NULL REFERENCES closed_loops(card_id),
  position INTEGER NOT NULL,
  merchant_key TEXT NOT NULL REFERENCES merchants(key),
  PRIMARY KEY (card_id, position)) WITHOUT ROWID;
CREATE TABLE relationship_boosts (
  card_id TEXT PRIMARY KEY REFERENCES cards(id),
  program TEXT NOT NULL, note TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE relationship_boost_tiers (
  card_id TEXT NOT NULL REFERENCES relationship_boosts(card_id),
  position INTEGER NOT NULL,
  tier_name TEXT, min_balance_usd, requirement TEXT, boost_pct,
  PRIMARY KEY (card_id, position)) WITHOUT ROWID;
CREATE TABLE benefit_flags (
  card_id TEXT NOT NULL REFERENCES cards(id),
  position INTEGER NOT NULL, flag TEXT NOT NULL,
  PRIMARY KEY (card_id, position)) WITHOUT ROWID;
CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  card_id TEXT NOT NULL REFERENCES cards(id),
  position INTEGER NOT NULL,
  url TEXT NOT NULL, accessed TEXT NOT NULL, added_by TEXT NOT NULL,
  note TEXT);
CREATE TABLE source_supports (
  source_id INTEGER NOT NULL REFERENCES sources(id),
  position INTEGER NOT NULL, block TEXT NOT NULL,
  PRIMARY KEY (source_id, position)) WITHOUT ROWID;
"""


class BuildError(Exception):
    pass


def load_yaml(path: Path):
    with open(path) as f:
        return yaml.safe_load(f)


def take(mapping: dict, context: str, *allowed) -> dict:
    """Closed-key-set guard: returns the mapping, erroring on any key not in
    `allowed` so schema drift breaks the build loudly."""
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise BuildError(f"{context}: unhandled key(s) {unknown} — extend "
                         f"scripts/build_db.py (and its loader) first")
    return mapping


def source_files() -> list:
    """[(logical path, file path)] — logical paths are location-independent
    (cards/<issuer>/<file>, meta/<file>) so the dataset hash depends on
    content only, not on where the tree happens to live."""
    files = ([(f"cards/{p.parent.name}/{p.name}", p)
              for p in sorted(CARDS_DIR.glob("*/*.yaml"))]
             + [(f"meta/{p.name}", p)
                for p in sorted(META_DIR.glob("*.yaml"))])
    if not files:
        raise BuildError(f"no source YAML found under {CARDS_DIR} / {META_DIR}")
    return files


def dataset_manifest() -> tuple:
    """[(logical path, sha256)] plus the combined dataset hash."""
    rows = []
    for logical, p in source_files():
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        rows.append((logical, digest))
    combined = hashlib.sha256(
        "\n".join(f"{path}:{digest}" for path, digest in rows).encode()
    ).hexdigest()
    return rows, combined


def build(out_path: Path) -> str:
    """Compile the dataset; returns the dataset_hash."""
    manifest, dataset_hash = dataset_manifest()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    con = sqlite3.connect(out_path)
    try:
        con.execute("PRAGMA page_size = 4096")
        con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        con.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(DDL)
        with con:
            _insert_meta(con, manifest, dataset_hash)
            _insert_registries(con)
            _insert_cards(con)
        violations = con.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise BuildError(f"foreign key violations: {violations[:5]}")
    finally:
        con.close()
    return dataset_hash


def _insert_meta(con, manifest, dataset_hash):
    con.execute("INSERT INTO meta VALUES ('schema_version', ?)",
                (str(DB_SCHEMA_VERSION),))
    con.execute("INSERT INTO meta VALUES ('dataset_hash', ?)", (dataset_hash,))
    con.executemany("INSERT INTO manifest VALUES (?, ?)", manifest)


def _insert_registries(con):
    categories = load_yaml(META_DIR / "categories.yaml")["categories"]
    for key in sorted(categories):
        entry = take(categories[key], f"categories.{key}", "label", "pseudo")
        con.execute("INSERT INTO categories VALUES (?, ?, ?)",
                    (key, entry["label"], entry.get("pseudo")))

    merchants = load_yaml(META_DIR / "merchants.yaml")["merchants"]
    for key in sorted(merchants):
        entry = take(merchants[key], f"merchants.{key}", "label", "category")
        con.execute("INSERT INTO merchants VALUES (?, ?, ?)",
                    (key, entry["label"], entry["category"]))

    groups = load_yaml(META_DIR / "usage-questions.yaml")["groups"]
    for g_pos, g_key in enumerate(groups):  # file order is display order
        group = take(groups[g_key], f"usage-questions.{g_key}",
                     "label", "prompt", "items")
        con.execute("INSERT INTO usage_groups VALUES (?, ?, ?, ?)",
                    (g_key, g_pos, group["label"], group["prompt"]))
        for i_pos, i_key in enumerate(group.get("items") or {}):
            item = take(group["items"][i_key],
                        f"usage-questions.{g_key}.items.{i_key}", "label")
            con.execute("INSERT INTO usage_items VALUES (?, ?, ?, ?)",
                        (i_key, g_key, i_pos, item["label"]))

    programs = load_yaml(META_DIR / "point-valuations.yaml")["programs"]
    for key in sorted(programs):
        entry = take(programs[key], f"point-valuations.{key}",
                     "label", "redeems_for", "floor_cpp", "optimistic_cpp",
                     "loyalty_keys", "transfer_gateway_required")
        con.execute("INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
                    (key, entry["label"], entry["floor_cpp"],
                     entry["optimistic_cpp"],
                     _b(entry.get("transfer_gateway_required"))))
        for pos, kind in enumerate(entry.get("redeems_for") or []):
            con.execute("INSERT INTO program_redeems_for VALUES (?, ?, ?)",
                        (key, pos, kind))
        for pos, uk in enumerate(entry.get("loyalty_keys") or []):
            con.execute("INSERT INTO program_loyalty_keys VALUES (?, ?, ?)",
                        (key, pos, uk))

    # The statement-import registries are optional (the optimizer never reads
    # them; the test fixture predates them).
    if not (META_DIR / "statement-descriptors.yaml").exists():
        return
    descriptors = load_yaml(META_DIR / "statement-descriptors.yaml")["descriptors"]
    for pos, key in enumerate(descriptors):  # file order preserved
        entry = take(descriptors[key], f"statement-descriptors.{key}",
                     "label", "benefit_context", "statement_patterns")
        con.execute("INSERT INTO statement_descriptors VALUES (?, ?, ?, ?)",
                    (key, pos, entry["label"], entry.get("benefit_context")))
        for p_pos, pattern in enumerate(entry.get("statement_patterns") or []):
            con.execute("INSERT INTO descriptor_patterns VALUES (?, ?, ?)",
                        (key, p_pos, pattern))

    if not (META_DIR / "category-rules.yaml").exists():
        return
    rules = take(load_yaml(META_DIR / "category-rules.yaml"), "category-rules",
                 "descriptor_categories", "aggregator_prefixes", "unmapped",
                 "keywords", "issuer_categories", "mcc")
    for key in sorted(rules["descriptor_categories"]):
        con.execute("INSERT INTO rule_descriptor_categories VALUES (?, ?)",
                    (key, rules["descriptor_categories"][key]))
    for key in sorted(rules["aggregator_prefixes"]):
        entry = take(rules["aggregator_prefixes"][key] or {},
                     f"category-rules.aggregator_prefixes.{key}",
                     "fallback_category")
        con.execute("INSERT INTO rule_aggregator_prefixes VALUES (?, ?)",
                    (key, entry.get("fallback_category")))
    for pos, key in enumerate(rules["unmapped"]):
        con.execute("INSERT INTO rule_unmapped VALUES (?, ?)", (key, pos))
    for cat in sorted(rules["keywords"]):
        for pos, pattern in enumerate(rules["keywords"][cat]):
            con.execute("INSERT INTO rule_keywords VALUES (?, ?, ?)",
                        (cat, pos, pattern))
    for label in sorted(rules["issuer_categories"]):
        con.execute("INSERT INTO rule_issuer_categories VALUES (?, ?)",
                    (label, rules["issuer_categories"][label]))
    for entry in rules["mcc"]:
        entry = take(entry, "category-rules.mcc[]", "from", "to", "category")
        con.execute("INSERT INTO rule_mcc_ranges VALUES (?, ?, ?)",
                    (entry["from"], entry["to"], entry["category"]))


def _b(value):
    """Booleans as INTEGER 0/1, absence as NULL."""
    return None if value is None else int(bool(value))


def _insert_cards(con):
    ids = {"category_reward": 0, "merchant_reward": 0, "credit": 0, "source": 0}

    def next_id(kind):
        ids[kind] += 1
        return ids[kind]

    seen_issuers = set()
    for path in sorted(CARDS_DIR.glob("*/*.yaml")):
        card = take(load_yaml(path), str(path),
                    "id", "name", "issuer", "network", "currency", "base_rate",
                    "base_rate_conditional", "portal", "unlocks_transfers",
                    "required_membership", "max_annual_rewards_usd",
                    "category_rewards", "merchant_rewards", "credits",
                    "signup_bonus", "fees", "approval", "closed_loop",
                    "relationship_boost", "benefit_flags", "sources",
                    "verification", "notes")
        cid = card["id"]
        if card["issuer"] not in seen_issuers:
            seen_issuers.add(card["issuer"])
            con.execute("INSERT INTO issuers VALUES (?)", (card["issuer"],))
        currency = take(card["currency"], f"{cid}.currency", "type", "program")
        fees = take(card["fees"], f"{cid}.fees", "annual_fee_usd",
                    "first_year_waived", "foreign_transaction_pct")
        approval = take(card["approval"], f"{cid}.approval", "credit_tier",
                        "estimated_min_score", "notes")
        verification = take(card["verification"], f"{cid}.verification",
                            "last_verified_date", "verified_by", "confidence")
        con.execute(
            "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, card["issuer"], card["name"], card["network"],
             currency["type"], currency["program"], card["base_rate"],
             card.get("portal"), _b(card.get("unlocks_transfers")),
             card.get("max_annual_rewards_usd"),
             fees["annual_fee_usd"], _b(fees.get("first_year_waived")),
             fees["foreign_transaction_pct"],
             approval["credit_tier"], approval.get("estimated_min_score"),
             approval.get("notes"),
             verification["last_verified_date"], verification["verified_by"],
             verification["confidence"], card.get("notes")))

        if "base_rate_conditional" in card:
            brc = take(card["base_rate_conditional"],
                       f"{cid}.base_rate_conditional", "rate", "requires", "note")
            con.execute("INSERT INTO base_rate_conditionals VALUES (?,?,?,?)",
                        (cid, brc["rate"], brc["requires"], brc.get("note")))

        def insert_cap(kind, reward_id, cap):
            cap = take(cap, f"{cid}.{kind}_rewards[].cap", "period",
                       "max_spend_usd", "fallback_rate", "shared_cap_id")
            con.execute("INSERT INTO caps VALUES (?,?,?,?,?,?)",
                        (kind, reward_id, cap["period"], cap["max_spend_usd"],
                         cap["fallback_rate"], cap.get("shared_cap_id")))

        def insert_conditional(kind, reward_id, cond):
            cond = take(cond, f"{cid}.{kind}_rewards[].conditional_rate",
                        "rate", "requires", "note")
            con.execute("INSERT INTO reward_conditional_rates VALUES (?,?,?,?,?)",
                        (kind, reward_id, cond["rate"], cond["requires"],
                         cond.get("note")))

        for pos, cr in enumerate(card["category_rewards"]):
            cr = take(cr, f"{cid}.category_rewards[{pos}]", "category", "rate",
                      "cap", "rotation", "choice", "portal_only",
                      "requires_enrollment", "conditional_rate", "notes")
            rid = next_id("category_reward")
            con.execute("INSERT INTO category_rewards VALUES (?,?,?,?,?,?,?,?)",
                        (rid, cid, pos, cr["category"], cr["rate"],
                         _b(cr.get("portal_only")),
                         _b(cr.get("requires_enrollment")), cr.get("notes")))
            if "cap" in cr:
                insert_cap("category", rid, cr["cap"])
            if "rotation" in cr:
                rot = take(cr["rotation"], f"{cid}.rotation", "frequency",
                           "requires_activation", "note")
                con.execute("INSERT INTO rotations VALUES (?,?,?,?)",
                            (rid, rot["frequency"],
                             _b(rot["requires_activation"]), rot["note"]))
            if "choice" in cr:
                choice = take(cr["choice"], f"{cid}.choice", "options", "note")
                con.execute("INSERT INTO choices VALUES (?,?)",
                            (rid, choice["note"]))
                for o_pos, option in enumerate(choice["options"]):
                    con.execute("INSERT INTO choice_options VALUES (?,?,?)",
                                (rid, o_pos, option))
            if "conditional_rate" in cr:
                insert_conditional("category", rid, cr["conditional_rate"])

        for pos, mr in enumerate(card["merchant_rewards"]):
            mr = take(mr, f"{cid}.merchant_rewards[{pos}]", "merchant", "rate",
                      "cap", "conditional_rate", "notes")
            rid = next_id("merchant_reward")
            con.execute("INSERT INTO merchant_rewards VALUES (?,?,?,?,?,?)",
                        (rid, cid, pos, mr["merchant"], mr["rate"],
                         mr.get("notes")))
            if "cap" in mr:
                insert_cap("merchant", rid, mr["cap"])
            if "conditional_rate" in mr:
                insert_conditional("merchant", rid, mr["conditional_rate"])

        for pos, credit in enumerate(card["credits"]):
            credit = take(credit, f"{cid}.credits[{pos}]", "name", "kind",
                          "amount_usd", "amount_points", "period", "category",
                          "usage_keys", "automatic", "unlock_spend_usd",
                          "requires_enrollment", "expires",
                          "realistic_capture_rate_note", "notes")
            crid = next_id("credit")
            con.execute("INSERT INTO credits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (crid, cid, pos, credit["name"], credit.get("kind"),
                         credit.get("amount_usd"), credit.get("amount_points"),
                         credit["period"], credit.get("category"),
                         _b(credit.get("automatic")),
                         credit.get("unlock_spend_usd"),
                         _b(credit.get("requires_enrollment")),
                         credit.get("expires"),
                         credit["realistic_capture_rate_note"],
                         credit.get("notes")))
            for k_pos, uk in enumerate(credit.get("usage_keys") or []):
                con.execute("INSERT INTO credit_usage_keys VALUES (?,?,?)",
                            (crid, k_pos, uk))

        bonus = card["signup_bonus"]
        if bonus is not None:
            bonus = take(bonus, f"{cid}.signup_bonus", "value",
                         "spend_requirement_usd", "window_months",
                         "first_year_match", "limited_time", "tiers",
                         "expires", "notes")
            value = take(bonus.get("value") or {}, f"{cid}.signup_bonus.value",
                         "points", "usd")
            con.execute("INSERT INTO signup_bonuses VALUES (?,?,?,?,?,?,?,?,?)",
                        (cid, value.get("points"), value.get("usd"),
                         bonus.get("spend_requirement_usd"),
                         bonus.get("window_months"),
                         _b(bonus.get("first_year_match")),
                         _b(bonus.get("limited_time")),
                         bonus.get("expires"), bonus.get("notes")))
            for pos, tier in enumerate(bonus.get("tiers") or []):
                tier = take(tier, f"{cid}.signup_bonus.tiers[{pos}]",
                            "value", "spend_requirement_usd")
                tv = take(tier["value"], f"{cid}.tiers[{pos}].value",
                          "points", "usd")
                con.execute("INSERT INTO bonus_tiers VALUES (?,?,?,?,?)",
                            (cid, pos, tv.get("points"), tv.get("usd"),
                             tier["spend_requirement_usd"]))

        if "required_membership" in card:
            rm = take(card["required_membership"], f"{cid}.required_membership",
                      "name", "annual_cost_usd", "card_exclusive", "note")
            con.execute("INSERT INTO required_memberships VALUES (?,?,?,?,?)",
                        (cid, rm["name"], rm.get("annual_cost_usd"),
                         _b(rm.get("card_exclusive")), rm["note"]))

        if "closed_loop" in card:
            cl = take(card["closed_loop"], f"{cid}.closed_loop",
                      "merchants", "note")
            con.execute("INSERT INTO closed_loops VALUES (?,?)",
                        (cid, cl.get("note")))
            for pos, m in enumerate(cl["merchants"]):
                con.execute("INSERT INTO closed_loop_merchants VALUES (?,?,?)",
                            (cid, pos, m))

        if "relationship_boost" in card:
            rb = take(card["relationship_boost"], f"{cid}.relationship_boost",
                      "program", "tiers", "note")
            con.execute("INSERT INTO relationship_boosts VALUES (?,?,?)",
                        (cid, rb["program"], rb["note"]))
            for pos, tier in enumerate(rb["tiers"]):
                tier = take(tier, f"{cid}.relationship_boost.tiers[{pos}]",
                            "tier_name", "min_balance_usd", "requirement",
                            "boost_pct")
                con.execute(
                    "INSERT INTO relationship_boost_tiers VALUES (?,?,?,?,?,?)",
                    (cid, pos, tier.get("tier_name"),
                     tier.get("min_balance_usd"), tier.get("requirement"),
                     tier["boost_pct"]))

        for pos, flag in enumerate(card["benefit_flags"]):
            con.execute("INSERT INTO benefit_flags VALUES (?,?,?)",
                        (cid, pos, flag))

        for pos, source in enumerate(card["sources"]):
            source = take(source, f"{cid}.sources[{pos}]", "url", "supports",
                          "accessed", "added_by", "note")
            sid = next_id("source")
            con.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)",
                        (sid, cid, pos, source["url"], source["accessed"],
                         source["added_by"], source.get("note")))
            for s_pos, block in enumerate(source["supports"]):
                con.execute("INSERT INTO source_supports VALUES (?,?,?)",
                            (sid, s_pos, block))


def stored_dataset_hash(db_path: Path) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT value FROM meta WHERE key = 'dataset_hash'").fetchone()
        return row[0] if row else ""
    finally:
        con.close()


def is_fresh(db_path: Path) -> bool:
    """True when the artifact at db_path was built from the current YAML
    sources (manifest hash comparison, ~ms)."""
    if not Path(db_path).exists():
        return False
    try:
        stored = stored_dataset_hash(db_path)
    except sqlite3.Error:
        return False
    return bool(stored) and stored == dataset_manifest()[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile data/ YAML into a normalized SQLite artifact "
                    "(plan 10 §4). YAML remains the source of truth.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"output path (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)
    try:
        dataset_hash = build(args.out)
    except (BuildError, OSError, yaml.YAMLError, sqlite3.Error, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"built {args.out} (dataset_hash {dataset_hash[:16]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
