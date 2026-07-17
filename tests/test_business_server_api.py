"""API tests for server/business_api.py (plan 22D).

Pins the /api/business/* HTTP contract to scripts/optimize_business.py:
/api/business/config mirrors the business registries and engine constants
exactly, and /api/business/optimize is byte-equivalent to calling
parse_business_profile + run + render_json directly (golden equivalence).
The consumer API's own contract stays pinned by tests/test_server_api.py —
these tests only add the business routes.

Skips cleanly when fastapi/httpx are absent so `python3 -m unittest discover
tests` still passes in the pyyaml-only CI environment.
Run: python3 -m unittest tests.test_business_server_api
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import optimize as copt  # noqa: E402  (consumer engine — path pinning only)
import optimize_business as bopt  # noqa: E402

HAS_FASTAPI = (importlib.util.find_spec("fastapi") is not None
               and importlib.util.find_spec("httpx") is not None)

AS_OF = "2026-07-17"

PROFILE = {
    "spend": {"advertising": 240000, "shipping": 120000,
              "software_saas": 60000, "travel_flights": 30000,
              "travel_hotels": 24000, "dining": 18000,
              "office_supplies": 12000, "telecom": 9000, "other": 87000},
    "company": {"entity_type": "llc", "accepts_personal_guarantee": True,
                "owner_fico_tier": "excellent", "employee_card_seats": 4,
                "large_txn_share": 0.2},
    "personal": {"five24_count": 2, "amex_credit_cards": 1,
                 "premium_cards_held": ["sapphire_preferred"]},
    "user": {"max_cards": 3},
}


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx not installed (pip install -r server/requirements.txt)")
class TestBusinessServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        sys.path.insert(0, str(ROOT / "server"))
        import app as server_app
        import business_api
        # Pin BOTH engines at the real data paths regardless of import order
        # (tests/test_optimizer.py repoints the consumer module at fixtures).
        cls._saved = (copt.CARDS_DIR, copt.META_DIR,
                      bopt.CARDS_DIR, bopt.META_DIR)
        copt.CARDS_DIR = ROOT / "data" / "cards"
        copt.META_DIR = ROOT / "data" / "meta"
        bopt.CARDS_DIR = ROOT / "data" / "business" / "cards"
        bopt.META_DIR = ROOT / "data" / "business" / "meta"
        cls._tmp = tempfile.TemporaryDirectory()
        server_app.DEBUG_DIR = Path(cls._tmp.name)
        cls.business_api = business_api
        cls.client = TestClient(server_app.app)
        cls.client.__enter__()  # lifespan loads consumer + business datasets
        cls.dataset = business_api.BIZ_STATE["dataset"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()
        (copt.CARDS_DIR, copt.META_DIR,
         bopt.CARDS_DIR, bopt.META_DIR) = cls._saved

    # -- read-only endpoints -------------------------------------------------

    def test_health(self):
        r = self.client.get("/api/business/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["cards_total"], len(self.dataset["cards"]))

    def test_cards_shape_matches_dataset(self):
        r = self.client.get("/api/business/cards")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], len(self.dataset["cards"]))
        by_id = {c["id"]: c for c in body["cards"]}
        for card in self.dataset["cards"]:
            row = by_id[card["id"]]
            self.assertEqual(row["issuer"], card["issuer"])
            self.assertEqual(row["pricing"]["model"], card["pricing"]["model"])
            self.assertEqual(row["business_approval"]["personal_guarantee"],
                             card["business_approval"]["personal_guarantee"])
            self.assertEqual(row["currency"]["program"],
                             card["currency"]["program"])
            self.assertEqual(row["verification"]["confidence"],
                             card["verification"]["confidence"])
        # Every row carries the business-only fields the consumer list lacks.
        sample = body["cards"][0]
        for key in ("business_approval", "employee_cards", "payment_type",
                    "integrations", "virtual_cards"):
            self.assertIn(key, sample)

    def test_assumptions_mirror_registry(self):
        r = self.client.get("/api/business/assumptions")
        self.assertEqual(r.status_code, 200)
        progs = {p["key"]: p for p in r.json()["programs"]}
        self.assertEqual(set(progs), set(self.dataset["programs"]))
        for key, entry in self.dataset["programs"].items():
            self.assertEqual(progs[key]["floor_cpp"], entry["floor_cpp"])
            self.assertEqual(progs[key]["optimistic_cpp"],
                             entry["optimistic_cpp"])

    def test_config_mirrors_registries_and_constants(self):
        r = self.client.get("/api/business/config")
        self.assertEqual(r.status_code, 200)
        cfg = r.json()
        self.assertEqual({c["key"] for c in cfg["categories"]},
                         set(self.dataset["categories"]))
        self.assertEqual({m["key"] for m in cfg["merchants"]},
                         set(self.dataset["merchants"]))
        self.assertEqual({g["key"] for g in cfg["usage_questions"]},
                         set(self.dataset["usage_questions"]))
        self.assertEqual(set(cfg["issuer_rules"]),
                         set(self.dataset["issuer_rules"]))
        self.assertEqual(cfg["tier_order"], bopt.TIER_ORDER)
        self.assertEqual(cfg["entity_types"], bopt.ENTITY_TYPES)
        self.assertEqual(cfg["personal_gateways"], bopt.PERSONAL_GATEWAYS)
        self.assertEqual(cfg["user_defaults"], bopt.USER_DEFAULTS)
        self.assertEqual(cfg["company_defaults"], bopt.COMPANY_DEFAULTS)
        self.assertEqual(cfg["personal_defaults"], bopt.PERSONAL_DEFAULTS)
        self.assertEqual(cfg["reward_kinds"], bopt.REWARD_KINDS)
        self.assertEqual(cfg["max_cards_range"], [1, 5])
        self.assertEqual(cfg["cards_total"], len(self.dataset["cards"]))
        # Chase carries the 5/24 gate; amex the card limit — the interaction
        # model's inputs must survive the wire format.
        self.assertTrue(cfg["issuer_rules"]["chase"]["gate_524"])
        self.assertEqual(cfg["issuer_rules"]["amex"]["credit_card_limit"], 5)

    # -- optimize ------------------------------------------------------------

    def test_optimize_golden_equivalence(self):
        """The HTTP result is byte-identical to calling the engine directly."""
        r = self.client.post("/api/business/optimize",
                             json={**PROFILE, "as_of": AS_OF, "top": 2})
        self.assertEqual(r.status_code, 200)
        profile = bopt.parse_business_profile(
            {k: PROFILE[k] for k in PROFILE}, self.dataset)
        from datetime import date
        expected = bopt.run(self.dataset, profile,
                            date.fromisoformat(AS_OF), 2)
        self.assertEqual(json.dumps(r.json(), sort_keys=True),
                         json.dumps(json.loads(bopt.render_json(expected)),
                                    sort_keys=True))

    def test_optimize_bundle_has_business_report_keys(self):
        r = self.client.post("/api/business/optimize",
                             json={**PROFILE, "as_of": AS_OF, "top": 1})
        self.assertEqual(r.status_code, 200)
        bundle = r.json()
        for key in ("company", "personal", "best_by_size", "portfolios",
                    "cpp_table", "policy_constants", "excluded"):
            self.assertIn(key, bundle)
        p = bundle["portfolios"][0]
        for key in ("blended_rate_pct", "workhorse_card", "float_days",
                    "application_notes", "per_card"):
            self.assertIn(key, p)
        card = next(iter(p["per_card"].values()))
        for key in ("fees", "payment_type", "integrations", "virtual_cards"):
            self.assertIn(key, card)
        for key in ("seat_fees_usd", "fee_refunded", "ongoing_usd",
                    "year1_usd", "notes"):
            self.assertIn(key, card["fees"])

    def test_optimize_input_errors_are_422(self):
        r = self.client.post("/api/business/optimize",
                             json={"spend": {}, "company": PROFILE["company"]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("spend", r.json()["detail"])
        r = self.client.post("/api/business/optimize",
                             json={**PROFILE, "top": 0})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/business/optimize",
                             json={**PROFILE, "as_of": "not-a-date"})
        self.assertEqual(r.status_code, 422)
        # Missing company block is the business contract's own required field.
        r = self.client.post("/api/business/optimize",
                             json={"spend": {"shipping": 1000}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("company", r.json()["detail"])

    def test_optimize_defaults_top_and_as_of(self):
        r = self.client.post("/api/business/optimize", json=dict(PROFILE))
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["portfolios"]), 5)  # default top=5

    # -- evaluate / suggest-addition ----------------------------------------

    def test_evaluate_manual_set(self):
        r = self.client.post("/api/business/evaluate",
                             json={**PROFILE, "as_of": AS_OF,
                                   "cards": ["ink-business-cash",
                                             "ink-business-unlimited"]})
        self.assertEqual(r.status_code, 200)
        bundle = r.json()
        self.assertEqual(bundle["portfolios"][0]["cards"],
                         ["ink-business-cash", "ink-business-unlimited"])
        self.assertEqual(bundle["best_by_size"][0]["size"], 2)

    def test_evaluate_bad_cards_422(self):
        r = self.client.post("/api/business/evaluate",
                             json={**PROFILE, "as_of": AS_OF, "cards": []})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/business/evaluate",
                             json={**PROFILE, "as_of": AS_OF,
                                   "cards": ["nope"]})
        self.assertEqual(r.status_code, 422)

    def test_suggest_addition_names_added_card(self):
        r = self.client.post("/api/business/suggest-addition",
                             json={**PROFILE, "as_of": AS_OF,
                                   "cards": ["ink-business-unlimited"]})
        self.assertEqual(r.status_code, 200)
        bundle = r.json()
        self.assertIn("added_card", bundle)
        self.assertNotEqual(bundle["added_card"], "ink-business-unlimited")
        self.assertEqual(len(bundle["portfolios"][0]["cards"]), 2)

    # -- consumer API untouched ----------------------------------------------

    def test_consumer_endpoints_still_serve(self):
        """The business router must not disturb the consumer surface — its
        own tests pin exact shapes; this is the coexistence smoke check."""
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        self.assertIn("categories", r.json())
        # Consumer config knows nothing of the business plane.
        self.assertNotIn("issuer_rules", r.json())


if __name__ == "__main__":
    unittest.main()
