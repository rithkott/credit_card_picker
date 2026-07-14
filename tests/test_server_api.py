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
            self.assertEqual(row["availability"], src.get("availability", "active"))
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
        """Since plan 12 the server parses statements itself (POST
        /api/statements/parse); the descriptor registry stays server-side
        and must not ship to the browser anymore."""
        cfg = self.client.get("/api/config").json()
        self.assertNotIn("statement_import", cfg)

    # -- statements/parse (plan 12; detection-only since plan 14) -------------

    FIXTURES = ROOT / "tests" / "fixtures" / "statements"

    def upload(self, name, data):
        return self.client.post("/api/statements/parse",
                                files={"file": (name, data, "application/octet-stream")})

    def test_parse_csv_upload(self):
        """{summary, matches}: only usage-item hits come back — the full
        transaction list never leaves the server (plan 14)."""
        r = self.upload("chase.csv", (self.FIXTURES / "chase.csv").read_bytes())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(set(body), {"summary", "matches"})
        self.assertEqual(body["summary"]["format"], "csv")
        self.assertEqual(body["summary"]["txns"], 7)
        self.assertLess(len(body["matches"]), 7)
        uber = next(m for m in body["matches"] if "UBER" in m["descriptor"])
        self.assertEqual(uber["usage_key"], "uber")
        self.assertEqual(uber["usage_label"], "Uber rides / Uber One")
        for m in body["matches"]:
            self.assertEqual(
                set(m), {"date", "amount_cents", "descriptor", "kind",
                         "line", "usage_key", "usage_label"})
            self.assertIn(m["kind"], ("purchase", "refund"))

    def test_parse_ofx_upload(self):
        r = self.upload("sgml.ofx", (self.FIXTURES / "sgml.ofx").read_bytes())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["summary"]["format"], "ofx")
        self.assertIn("matches", body)

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

    def test_parse_unmatched_txns_never_returned(self):
        """A statement with no benefit-relevant merchants returns an empty
        matches list — descriptors of unrecognized spend stay server-side."""
        csv = (b"Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
               b"01/05/2026,01/06/2026,SPIRIT AI EXECUTIVE,,Sale,-42.00,\n"
               b"01/06/2026,01/07/2026,JOES DELI 42 NYC,,Sale,-12.00,\n")
        r = self.upload("misc.csv", csv)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["matches"], [])
        self.assertEqual(body["summary"]["txns"], 2)
        self.assertNotIn("SPIRIT", r.text)

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
                # Contract: potential_value (full face of a usage-gated perk the
                # user hasn't confirmed) appears only on $0 credits and is
                # display-only — it never rides on an earning credit (v1.6.5).
                for c in d["credits"]:
                    if "potential_value" in c:
                        self.assertEqual(c["value"], 0.0)
                        self.assertGreater(c["potential_value"], 0)

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

    # -- evaluate (manual mode, v1.7): golden equivalence + errors ------------

    def test_evaluate_matches_engine_byte_for_byte(self):
        ids = [c["id"] for c in self.dataset["cards"]][:2]
        raw = {"spend": {"dining": 6000, "groceries": 4800, "other": 12000},
               "user": {"credit_tier": "good"}}
        r = self.client.post("/api/evaluate",
                             json={**raw, "cards": ids, "as_of": AS_OF})
        self.assertEqual(r.status_code, 200, r.text)
        profile = opt.parse_profile(raw, self.dataset)
        expected = opt.evaluate(self.dataset, profile, date.fromisoformat(AS_OF), ids)
        self.assertEqual(json.dumps(r.json(), sort_keys=True, indent=2) + "\n",
                         opt.render_json(expected))
        # Contract: same bundle shape as /api/optimize — a single best_by_size
        # entry carrying exactly the chosen cards.
        self.assertEqual(len(r.json()["best_by_size"]), 1)
        self.assertEqual(r.json()["best_by_size"][0]["cards"], ids)
        self.assertEqual(r.json()["portfolios"][0]["cards"], ids)

    def assert_evaluate_422(self, body, fragment):
        r = self.client.post("/api/evaluate", json=body)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn(fragment, r.json()["detail"])

    def test_evaluate_unknown_card_422(self):
        self.assert_evaluate_422(
            {"spend": {"other": 5000}, "user": {"credit_tier": "good"},
             "cards": ["no-such-card"]},
            "unknown card id")

    def test_evaluate_no_card_cap(self):
        # v1.10 removed the old 5-card manual limit: >5 hand-picked cards score fine.
        ids = [c["id"] for c in self.dataset["cards"]][:7]
        r = self.client.post("/api/evaluate",
                             json={"spend": {"other": 5000},
                                   "user": {"credit_tier": "good"},
                                   "cards": ids, "as_of": AS_OF})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["best_by_size"][0]["cards"], ids)

    def test_evaluate_duplicate_422(self):
        cid = self.dataset["cards"][0]["id"]
        self.assert_evaluate_422(
            {"spend": {"other": 5000}, "user": {"credit_tier": "good"},
             "cards": [cid, cid]},
            "duplicate ids")

    def test_evaluate_empty_422(self):
        self.assert_evaluate_422(
            {"spend": {"other": 5000}, "user": {"credit_tier": "good"},
             "cards": []},
            "non-empty list")

    # -- suggest-addition (best additional card, v1.10) -----------------------

    def test_suggest_addition_matches_engine_and_adds_a_card(self):
        held = [c["id"] for c in self.dataset["cards"]][:1]
        raw = {"spend": {"dining": 6000, "groceries": 4800, "other": 12000},
               "user": {"credit_tier": "good"}}
        r = self.client.post("/api/suggest-addition",
                             json={**raw, "cards": held, "as_of": AS_OF})
        self.assertEqual(r.status_code, 200, r.text)
        profile = opt.parse_profile(raw, self.dataset)
        expected = opt.augment(self.dataset, profile, date.fromisoformat(AS_OF), held)
        self.assertEqual(json.dumps(r.json(), sort_keys=True, indent=2) + "\n",
                         opt.render_json(expected))
        body = r.json()
        # Contract: added_card is a real card not already held, and the scored
        # portfolio is exactly held + added_card.
        self.assertNotIn(body["added_card"], held)
        self.assertIn(body["added_card"],
                      {c["id"] for c in self.dataset["cards"]})
        self.assertEqual(set(body["best_by_size"][0]["cards"]),
                         set(held) | {body["added_card"]})

    def test_suggest_addition_empty_422(self):
        r = self.client.post("/api/suggest-addition",
                             json={"spend": {"other": 5000},
                                   "user": {"credit_tier": "good"}, "cards": []})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("non-empty list", r.json()["detail"])

    def test_suggest_addition_unknown_card_422(self):
        r = self.client.post("/api/suggest-addition",
                             json={"spend": {"other": 5000},
                                   "user": {"credit_tier": "good"},
                                   "cards": ["no-such-card"]})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("unknown card id", r.json()["detail"])

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
