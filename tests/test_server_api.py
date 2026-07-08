"""API tests for server/app.py (docs/plans/04-tech-stack.md).

The server wraps scripts/optimize.py in-process; these tests pin the HTTP
contract to the engine: /api/config mirrors the registries and optimize.py
constants exactly, and /api/optimize is byte-equivalent to calling
parse_profile + run + render_json directly (golden equivalence).

Skips cleanly when fastapi/httpx are absent so `python3 -m unittest discover
tests` still passes in the pyyaml-only CI environment.
Run: python3 -m unittest tests.test_server_api
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import optimize as opt  # noqa: E402

HAS_FASTAPI = (importlib.util.find_spec("fastapi") is not None
               and importlib.util.find_spec("httpx") is not None)

AS_OF = "2026-07-05"


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx not installed (pip install -r server/requirements.txt)")
class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(ROOT / "server"))
        import app as server_app
        # tests/test_optimizer.py repoints the shared optimize module at its
        # frozen fixture dataset at import time; under `unittest discover` that
        # module imports first, so pin the REAL data paths back before the
        # lifespan loads the dataset — the API must be tested against the
        # production dataset, deterministically regardless of import order.
        cls._saved_paths = (opt.CARDS_DIR, opt.META_DIR)
        opt.CARDS_DIR = ROOT / "data" / "cards"
        opt.META_DIR = ROOT / "data" / "meta"
        # Debug dumps go to a tempdir, not the repo.
        cls._tmp = tempfile.TemporaryDirectory()
        server_app.DEBUG_DIR = Path(cls._tmp.name)
        cls.server_app = server_app
        cls.client = TestClient(server_app.app)
        cls.client.__enter__()  # run lifespan (loads the dataset once)
        cls.dataset = server_app.STATE["dataset"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()
        opt.CARDS_DIR, opt.META_DIR = cls._saved_paths

    # -- health / config ----------------------------------------------------

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(),
                         {"ok": True, "cards_total": len(self.dataset["cards"])})

    def test_config_mirrors_registries_and_constants(self):
        cfg = self.client.get("/api/config").json()
        real_cats = [k for k, v in self.dataset["categories"].items()
                     if not (v or {}).get("pseudo")]
        self.assertEqual([c["key"] for c in cfg["categories"]], real_cats)
        self.assertNotIn("rotating", [c["key"] for c in cfg["categories"]])
        self.assertNotIn("choice", [c["key"] for c in cfg["categories"]])
        self.assertTrue(all(c["label"] for c in cfg["categories"]))
        self.assertEqual([m["key"] for m in cfg["merchants"]],
                         list(self.dataset["merchants"]))
        for m in cfg["merchants"]:
            self.assertEqual(m["category"],
                             self.dataset["merchants"][m["key"]]["category"])
        self.assertEqual([g["key"] for g in cfg["usage_questions"]],
                         list(self.dataset["usage_questions"]))
        for g in cfg["usage_questions"]:
            reg = self.dataset["usage_questions"][g["key"]]
            self.assertEqual(g["prompt"], reg["prompt"])
            self.assertEqual([i["key"] for i in g["items"]], list(reg["items"]))
        self.assertEqual(cfg["tier_order"], opt.TIER_ORDER)
        self.assertEqual(cfg["user_defaults"], opt.USER_DEFAULTS)
        self.assertEqual(cfg["reward_kinds"], opt.REWARD_KINDS)
        self.assertEqual(cfg["max_cards_range"], [1, 5])
        self.assertEqual(
            cfg["data_last_verified"],
            max(c["verification"]["last_verified_date"]
                for c in self.dataset["cards"]))

    def test_config_statement_import_mirrors_registries(self):
        cfg = self.client.get("/api/config").json()
        si = cfg["statement_import"]
        descriptors = yaml.safe_load(
            (ROOT / "data" / "meta" / "statement-descriptors.yaml").read_text()
        )["descriptors"]
        rules = yaml.safe_load(
            (ROOT / "data" / "meta" / "category-rules.yaml").read_text())
        # Descriptors mirror the registry exactly, key order preserved.
        self.assertEqual([d["key"] for d in si["descriptors"]], list(descriptors))
        for d in si["descriptors"]:
            self.assertEqual(d["patterns"],
                             descriptors[d["key"]]["statement_patterns"])
            self.assertEqual(d["label"], descriptors[d["key"]]["label"])
        # Rule blocks are passed through verbatim.
        for block in ("descriptor_categories", "aggregator_prefixes", "unmapped",
                      "keywords", "issuer_categories", "mcc"):
            self.assertEqual(si[block], rules[block], block)
        # Bridge integrity as served: every bridge key resolves to a descriptor
        # and every descriptor key is accounted for in exactly one block.
        served_keys = {d["key"] for d in si["descriptors"]}
        assigned = (list(si["descriptor_categories"])
                    + list(si["aggregator_prefixes"]) + list(si["unmapped"]))
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertTrue(set(assigned) <= served_keys)

    # -- optimize: golden equivalence ----------------------------------------

    def test_optimize_matches_engine_byte_for_byte(self):
        raw = yaml.safe_load((ROOT / "examples" / "spend-profile.example.yaml").read_text())
        r = self.client.post("/api/optimize", json={**raw, "as_of": AS_OF, "top": 5})
        self.assertEqual(r.status_code, 200)
        profile = opt.parse_profile(raw, self.dataset)
        expected = opt.run(self.dataset, profile, date.fromisoformat(AS_OF), 5)
        self.assertEqual(json.dumps(r.json(), sort_keys=True, indent=2) + "\n",
                         opt.render_json(expected))

    def test_optimize_defaults_top_and_as_of(self):
        body = {"spend": {"other": 5000}, "user": {"credit_tier": "good",
                                                   "max_cards": 1},
                "as_of": AS_OF}
        r = self.client.post("/api/optimize", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["portfolios"]), 5)
        self.assertEqual(r.json()["as_of"], AS_OF)

    # -- error contract -------------------------------------------------------

    def assert_422(self, body, fragment):
        r = self.client.post("/api/optimize", json=body)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn(fragment, r.json()["detail"])

    def test_missing_tier_422(self):
        self.assert_422({"spend": {"other": 100}, "user": {}},
                        "credit_tier is required")

    def test_unknown_category_422(self):
        self.assert_422({"spend": {"grocery": 100}, "user": {"credit_tier": "good"}},
                        "unknown category")

    def test_carveout_overflow_422(self):
        self.assert_422({"spend": {"groceries": 100},
                         "merchant_spend": {"costco": 200},
                         "user": {"credit_tier": "good"}},
                        "carve-outs")

    def test_bad_as_of_422(self):
        self.assert_422({"spend": {"other": 100},
                         "user": {"credit_tier": "good"}, "as_of": "tomorrow"},
                        "as_of must be YYYY-MM-DD")

    def test_bad_top_422(self):
        self.assert_422({"spend": {"other": 100},
                         "user": {"credit_tier": "good"}, "top": 0},
                        "top must be an integer")

    # -- debug dumps ----------------------------------------------------------

    def test_debug_dump_written_per_call(self):
        before = set(Path(self._tmp.name).iterdir())
        body = {"spend": {"other": 1000}, "user": {"credit_tier": "good",
                                                   "max_cards": 1},
                "as_of": AS_OF}
        self.client.post("/api/optimize", json=body)
        new = set(Path(self._tmp.name).iterdir()) - before
        self.assertEqual(len(new), 1)
        record = yaml.safe_load(new.pop().read_text())
        self.assertEqual(record["request"], body)
        self.assertEqual(record["status"], 200)
        self.assertIn("portfolios", record["result"])

    # -- result cache + hot reload (plan 10 §5) -------------------------------

    def test_cache_hit_is_byte_identical_and_skips_dump(self):
        body = {"spend": {"other": 2000}, "user": {"credit_tier": "good",
                                                   "max_cards": 2},
                "as_of": AS_OF}
        first = self.client.post("/api/optimize", json=body)
        self.assertEqual(first.status_code, 200)
        before = set(Path(self._tmp.name).iterdir())
        second = self.client.post("/api/optimize", json=body)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.content, second.content)
        # The replay was served from the cache: no new debug dump.
        self.assertEqual(set(Path(self._tmp.name).iterdir()), before)

    def test_reload_endpoint(self):
        r = self.client.post("/api/reload")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["cards_total"],
                         len(self.server_app.STATE["dataset"]["cards"]))
        self.assertEqual(r.json()["dataset_hash"],
                         self.server_app.STATE["dataset_hash"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx not installed (pip install -r server/requirements.txt)")
class TestHotReload(unittest.TestCase):
    """Editing a card YAML is picked up on the next request — no restart
    (plan 10 §5). Runs against a temporary copy of the live dataset so the
    repo stays untouched."""

    def setUp(self):
        import shutil
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(ROOT / "server"))
        import app as server_app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name) / "data"
        shutil.copytree(ROOT / "data" / "cards", data / "cards")
        shutil.copytree(ROOT / "data" / "meta", data / "meta")
        self.saved = (opt.CARDS_DIR, opt.META_DIR,
                      server_app.DB_PATH, server_app.DEBUG_DIR)
        opt.CARDS_DIR = data / "cards"
        opt.META_DIR = data / "meta"
        server_app.DB_PATH = data / "build" / "cards.sqlite"
        server_app.DEBUG_DIR = Path(self.tmp.name) / "debug"
        self.server_app = server_app
        self.client = TestClient(server_app.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self._restore)

    def _restore(self):
        (opt.CARDS_DIR, opt.META_DIR, self.server_app.DB_PATH,
         self.server_app.DEBUG_DIR) = self.saved

    def test_card_edit_is_picked_up_without_restart(self):
        before = self.client.get("/api/config").json()["data_last_verified"]
        hash_before = self.server_app.STATE["dataset_hash"]
        card_path = Path(opt.CARDS_DIR) / "wells-fargo" / "active-cash.yaml"
        card = yaml.safe_load(card_path.read_text())
        card["verification"]["last_verified_date"] = "2099-01-01"
        card_path.write_text(yaml.safe_dump(card, sort_keys=False,
                                            allow_unicode=True))
        after = self.client.get("/api/config").json()["data_last_verified"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, "2099-01-01")
        # The reload minted a new dataset_hash and reset the result cache.
        self.assertNotEqual(hash_before, self.server_app.STATE["dataset_hash"])
        self.assertEqual(len(self.server_app.STATE["result_cache"]), 0)


if __name__ == "__main__":
    unittest.main()
