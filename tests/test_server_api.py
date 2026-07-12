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
            self.assertEqual(g["assumed_reward_kind"], reg.get("assumed_reward_kind"))
            self.assertEqual([i["key"] for i in g["items"]], list(reg["items"]))
        # Brand-loyalty groups (assumed_reward_kind) exist in the real registry
        # — the UI's Brand loyalty block depends on them.
        self.assertEqual(
            {g["key"]: g["assumed_reward_kind"] for g in cfg["usage_questions"]
             if g["assumed_reward_kind"]},
            {"airlines": "flights", "hotels": "hotels"})
        self.assertEqual(cfg["tier_order"], opt.TIER_ORDER)
        self.assertEqual(cfg["user_defaults"], opt.USER_DEFAULTS)
        self.assertEqual(cfg["reward_kinds"], opt.REWARD_KINDS)
        self.assertEqual(cfg["max_cards_range"], [1, 5])
        # data_last_verified = the newest verification date across all cards.
        real_dates = [(c.get("verification") or {}).get("last_verified_date")
                      for c in self.dataset["cards"]]
        self.assertEqual(cfg["data_last_verified"],
                         max(d for d in real_dates if d))

    def test_cards_mirrors_card_files(self):
        body = self.client.get("/api/cards").json()
        self.assertEqual(body["total"], len(self.dataset["cards"]))
        self.assertEqual([c["id"] for c in body["cards"]],
                         [c["id"] for c in self.dataset["cards"]])
        by_id = {c["id"]: c for c in self.dataset["cards"]}
        for row in body["cards"]:
            src = by_id[row["id"]]
            self.assertEqual(row["name"], src["name"])
            self.assertEqual(row["issuer"], src["issuer"])
            self.assertEqual(row["annual_fee_usd"], src["fees"]["annual_fee_usd"])
            self.assertEqual(row["currency"]["program"], src["currency"]["program"])
            self.assertEqual(
                row["currency"]["program_label"],
                self.dataset["programs"][src["currency"]["program"]].get(
                    "label", src["currency"]["program"]))
            ver = src.get("verification", {})
            self.assertEqual(row["verification"]["confidence"],
                             ver.get("confidence"))
            self.assertEqual(row["verification"]["last_verified_date"],
                             ver.get("last_verified_date"))

    def test_assumptions_mirrors_point_valuations(self):
        body = self.client.get("/api/assumptions").json()
        programs = self.dataset["programs"]
        self.assertEqual([p["key"] for p in body["programs"]], list(programs))
        for p in body["programs"]:
            src = programs[p["key"]]
            self.assertEqual(p["floor_cpp"], src["floor_cpp"])
            self.assertEqual(p["optimistic_cpp"], src["optimistic_cpp"])
            self.assertEqual(p["redeems_for"], src.get("redeems_for", []))
            self.assertEqual(p["transfer_gateway_required"],
                             src.get("transfer_gateway_required", False))
            self.assertEqual(p["loyalty_keys"], src.get("loyalty_keys", []))

    def test_config_has_no_statement_import_block(self):
        """Since plan 12 the server parses AND categorizes statements itself
        (POST /api/statements/parse); the rule registries stay server-side
        and must not ship to the browser anymore."""
        cfg = self.client.get("/api/config").json()
        self.assertNotIn("statement_import", cfg)

    # -- statements/parse (plan 12) -------------------------------------------

    FIXTURES = ROOT / "tests" / "fixtures" / "statements"

    def upload(self, name, data):
        return self.client.post("/api/statements/parse",
                                files={"file": (name, data, "application/octet-stream")})

    def test_parse_csv_upload(self):
        r = self.upload("chase.csv", (self.FIXTURES / "chase.csv").read_bytes())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["summary"]["format"], "csv")
        self.assertEqual(body["summary"]["txns"], 7)
        self.assertEqual(len(body["txns"]), 7)
        # Every txn is categorized (match present, exact or a miss).
        for t in body["txns"]:
            self.assertIn("match", t)
            self.assertIn("stem", t["match"])
        uber = next(t for t in body["txns"] if "UBER" in t["descriptor"])
        self.assertEqual(uber["match"]["category"], "transit")
        self.assertEqual(uber["match"]["method"], "exact")

    def test_parse_ofx_upload(self):
        r = self.upload("sgml.ofx", (self.FIXTURES / "sgml.ofx").read_bytes())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["summary"]["format"], "ofx")

    def test_parse_pdf_upload(self):
        import importlib.util
        if importlib.util.find_spec("pdfplumber") is None:
            self.skipTest("pdfplumber not installed")
        import base64
        data = base64.b64decode((self.FIXTURES / "statement.pdf.b64").read_text())
        r = self.upload("statement.pdf", data)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["summary"]["format"], "pdf")
        self.assertEqual(body["summary"]["extraction"], "regex")
        self.assertEqual(body["summary"]["statement_totals"]["purchases_cents"], 22331)

    def test_parse_unknown_format_422_with_code(self):
        r = self.upload("junk.bin", bytes([0, 1, 2]))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "unrecognized_format")
        self.assertIn("detail", r.json())

    def test_parse_oversize_413(self):
        import statements as stmts
        r = self.upload("big.csv", b"a,b\n" * (stmts.MAX_FILE_BYTES // 4 + 1))
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["code"], "too_large")

    def test_parse_unmatched_txn_carries_suggestion(self):
        """v1.3.0 contract: an all-layers miss ships the semantic top-1 as
        match.suggestion {category, confidence<0.4} — category/layer/method
        stay null, so a suggestion is never a placement."""
        import importlib.util
        ready = all(importlib.util.find_spec(mod) is not None
                    for mod in ("numpy", "tokenizers", "onnxruntime")) and (
            ROOT / "server" / "statements" / "model" / "model_quantized.onnx").exists()
        if not ready:
            self.skipTest("onnxruntime/numpy/tokenizers or model files absent")
        csv = (b"Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
               b"01/05/2026,01/06/2026,SPIRIT AI EXECUTIVE,,Sale,-42.00,\n")
        r = self.upload("misc.csv", csv)
        self.assertEqual(r.status_code, 200, r.text)
        match = r.json()["txns"][0]["match"]
        self.assertIsNone(match["category"])
        self.assertIsNone(match["layer"])
        self.assertIsNone(match["method"])
        suggestion = match["suggestion"]
        real_categories = {c["key"] for c in
                           self.client.get("/api/config").json()["categories"]}
        self.assertIn(suggestion["category"], real_categories)
        self.assertGreaterEqual(suggestion["confidence"], 0.0)
        self.assertLess(suggestion["confidence"], 0.4)

    def test_parse_never_writes_debug_dumps(self):
        """EPHEMERAL BY POLICY: statement uploads must never produce a debug
        dump (unlike /api/optimize locally) — not on success, not on error."""
        before = set(Path(self._tmp.name).iterdir())
        self.upload("chase.csv", (self.FIXTURES / "chase.csv").read_bytes())
        self.upload("junk.bin", bytes([0, 1, 2]))
        self.assertEqual(set(Path(self._tmp.name).iterdir()), before)

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
        # Contract: every per_card block names its earning currency (drives
        # the frontend's points-chain rendering, v1.3.2).
        for p in r.json()["portfolios"]:
            for d in p["per_card"].values():
                self.assertIn(d["currency"]["kind"], ("cash", "points"))
                self.assertIn("program", d["currency"])
                self.assertIn("label", d["currency"])

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

    def test_debug_dump_disabled_on_vercel(self):
        """The hosted deployment must never write user spend anywhere —
        the privacy claim depends on this, not on the FS being read-only."""
        import os
        before = set(Path(self._tmp.name).iterdir())
        body = {"spend": {"other": 1000}, "user": {"credit_tier": "good",
                                                   "max_cards": 1},
                "as_of": AS_OF}
        os.environ["VERCEL"] = "1"
        try:
            r = self.client.post("/api/optimize", json=body)
        finally:
            del os.environ["VERCEL"]
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(Path(self._tmp.name).iterdir()), before)


if __name__ == "__main__":
    unittest.main()
