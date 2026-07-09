"""Tests for the compiled SQLite artifact (scripts/build_db.py +
optimize.load_dataset_db, plan 10 §4).

The one test that matters is the deep-equality oracle: the loader must
reconstruct byte-for-byte the same in-memory dataset as load_dataset() reads
from YAML — every absent key absent, every int an int, every list in file
order. Everything else (determinism, FK integrity, staleness detection)
guards the artifact's build contract.

Run: python3 -m unittest discover tests
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_db
import optimize as opt

REPO_DATA = Path(__file__).resolve().parent.parent / "data"
FIXTURE_DATA = Path(__file__).resolve().parent / "fixtures" / "data"


def assert_key_order(tc, from_yaml, from_db):
    """dict == is insertion-order-blind, but registry key iteration order is
    part of what load_dataset() reads (curated file order, served verbatim by
    /api/config as UI display order — plan 11 R2), so pin it explicitly for
    every dict-valued registry, including usage-question item order. Field
    order WITHIN an entry is not checked — the loader constructs entries in a
    fixed field order and nothing observes it."""
    for key, val in from_yaml.items():
        if not isinstance(val, dict):
            continue
        tc.assertEqual(list(val), list(from_db[key]),
                       msg=f"dataset[{key!r}] key order differs")
    for gkey, group in from_yaml["usage_questions"].items():
        tc.assertEqual(list(group["items"]),
                       list(from_db["usage_questions"][gkey]["items"]),
                       msg=f"usage_questions[{gkey!r}] item order differs")


class BuildDbBase(unittest.TestCase):
    cards_dir = REPO_DATA / "cards"
    meta_dir = REPO_DATA / "meta"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "cards.sqlite"
        self.saved = (build_db.CARDS_DIR, build_db.META_DIR,
                      opt.CARDS_DIR, opt.META_DIR)
        build_db.CARDS_DIR = opt.CARDS_DIR = self.cards_dir
        build_db.META_DIR = opt.META_DIR = self.meta_dir
        self.addCleanup(self._restore)

    def _restore(self):
        (build_db.CARDS_DIR, build_db.META_DIR,
         opt.CARDS_DIR, opt.META_DIR) = self.saved


class TestRoundTripLive(BuildDbBase):
    """Against the full live dataset — the strongest oracle available."""

    def test_loader_deep_equals_yaml(self):
        build_db.build(self.db_path)
        from_yaml = opt.load_dataset()
        from_db = opt.load_dataset_db(self.db_path)
        self.assertEqual(sorted(from_yaml), sorted(from_db))
        for key in from_yaml:
            self.assertEqual(from_yaml[key], from_db[key],
                             msg=f"dataset[{key!r}] differs")
        assert_key_order(self, from_yaml, from_db)
        # Type fidelity spot-checks == cannot see: bool vs int, int vs float.
        for a, b in zip(from_yaml["cards"], from_db["cards"]):
            self.assertEqual(type(a["base_rate"]), type(b["base_rate"]),
                             msg=a["id"])
            self.assertEqual(sorted(a), sorted(b), msg=f"{a['id']} key sets")

    def test_rebuild_is_byte_identical(self):
        h1 = build_db.build(self.db_path)
        bytes1 = self.db_path.read_bytes()
        h2 = build_db.build(self.db_path)
        self.assertEqual(h1, h2)
        self.assertEqual(bytes1, self.db_path.read_bytes())

    def test_failed_build_preserves_existing_artifact(self):
        # Plan 11 R3: build() writes to a temp path and os.replace()s into
        # place — a failed rebuild must leave the existing artifact byte-intact
        # and no temp file behind (the old in-place write unlinked first, so
        # readers could observe a half-built DB).
        build_db.build(self.db_path)
        bytes_before = self.db_path.read_bytes()
        saved = build_db._insert_cards

        def boom(con):
            raise build_db.BuildError("injected mid-build failure")

        build_db._insert_cards = boom
        self.addCleanup(setattr, build_db, "_insert_cards", saved)
        with self.assertRaises(build_db.BuildError):
            build_db.build(self.db_path)
        self.assertEqual(self.db_path.read_bytes(), bytes_before)
        leftovers = [p for p in self.db_path.parent.iterdir()
                     if p.name != self.db_path.name]
        self.assertEqual(leftovers, [])

    def test_freshness_tracks_sources(self):
        build_db.build(self.db_path)
        self.assertTrue(build_db.is_fresh(self.db_path))
        # A different sources tree (the fixture) must read as stale.
        build_db.CARDS_DIR = FIXTURE_DATA / "cards"
        build_db.META_DIR = FIXTURE_DATA / "meta"
        self.assertFalse(build_db.is_fresh(self.db_path))

    def test_schema_version_bump_reads_as_stale(self):
        # Plan 11 R2 shipped a schema change (registry position columns): an
        # artifact built by an older schema must rebuild, not fail the loader.
        build_db.build(self.db_path)
        self.assertTrue(build_db.is_fresh(self.db_path))
        con = sqlite3.connect(self.db_path)
        with con:
            con.execute("UPDATE meta SET value = '0' "
                        "WHERE key = 'schema_version'")
        con.close()
        self.assertFalse(build_db.is_fresh(self.db_path))

    def test_fk_integrity_enforced(self):
        build_db.build(self.db_path)
        con = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(
                con.execute("PRAGMA foreign_key_check").fetchall(), [])
            con.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO merchants VALUES "
                            "('bogus', 999, 'Bogus', 'no-such-category')")
        finally:
            con.close()

    def test_optimizer_runs_identically_from_db(self):
        build_db.build(self.db_path)
        from datetime import date
        profile_raw = {"spend": {"dining": 4000, "groceries": 6000,
                                 "other": 8000},
                       "user": {"credit_tier": "excellent"}}
        d_yaml = opt.load_dataset()
        d_db = opt.load_dataset_db(self.db_path)
        p_yaml = opt.parse_profile(profile_raw, d_yaml)
        p_db = opt.parse_profile(profile_raw, d_db)
        as_of = date(2026, 7, 7)
        self.assertEqual(opt.render_json(opt.run(d_yaml, p_yaml, as_of, 3)),
                         opt.render_json(opt.run(d_db, p_db, as_of, 3)))


class TestRoundTripFixture(BuildDbBase):
    """Same oracle over the frozen 8-card fixture (choice/rotating/gateway)."""
    cards_dir = FIXTURE_DATA / "cards"
    meta_dir = FIXTURE_DATA / "meta"

    def test_loader_deep_equals_yaml(self):
        build_db.build(self.db_path)
        from_yaml = opt.load_dataset()
        from_db = opt.load_dataset_db(self.db_path)
        self.assertEqual(from_yaml, from_db)
        assert_key_order(self, from_yaml, from_db)


if __name__ == "__main__":
    unittest.main()
