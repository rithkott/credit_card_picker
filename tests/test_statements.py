"""Parser tests for server/statements/ (plan 12).

Parity assertions ported from the retired in-browser engine's vitest suites
(parsers.test.ts, pdf.test.ts) so the Python port provably matches the
corpus-verified TS behavior, plus new coverage for the server-only semantic
layer: CSV column inference, the PDF layout-band fallback, and the fuzzy
categorization layer. Fixtures are synthetic — see fixtures/statements/.

pdfplumber/rapidfuzz tests skip cleanly when those packages are absent so
`python3 -m unittest discover tests` still passes in the pyyaml-only CI
environment. Run: python3 -m unittest tests.test_statements
"""

import base64
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from statements import parse_statement  # noqa: E402
from statements.csv_parse import (parse_amount_to_cents, parse_csv,  # noqa: E402
                                  parse_date_to_iso)
from statements.detect import detect_format  # noqa: E402
from statements.ofx import parse_ofx, parse_ofx_date  # noqa: E402
from statements.types import StatementParseError  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "statements"
HAS_PDF = importlib.util.find_spec("pdfplumber") is not None
HAS_FUZZ = importlib.util.find_spec("rapidfuzz") is not None


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ── detect ───────────────────────────────────────────────────────────────────


class TestDetectFormat(unittest.TestCase):
    def test_pdf_magic_bytes(self):
        self.assertEqual(detect_format(b"%PDF-1.7 junk", "statement.pdf"), "pdf")
        self.assertEqual(detect_format(b"%PDF-1.4", "renamed.csv"), "pdf")

    def test_ofx_header_or_root_tag(self):
        self.assertEqual(detect_format(fixture_bytes("sgml.ofx"), "sgml.ofx"), "ofx")
        self.assertEqual(detect_format(fixture_bytes("xml.qfx"), "xml.qfx"), "ofx")

    def test_extension_tiebreak_for_ambiguous_ofx(self):
        self.assertEqual(detect_format(b"who knows", "export.qfx"), "ofx")

    def test_csv_by_delimited_header(self):
        self.assertEqual(detect_format(fixture_bytes("chase.csv"), "activity.csv"), "csv")
        self.assertEqual(detect_format(fixture_bytes("quirks.csv"), "quirks.txt"), "csv")

    def test_unknown_for_binary_junk(self):
        self.assertEqual(detect_format(bytes([0, 1, 2]), "blob.bin"), "unknown")


# ── field parsing ────────────────────────────────────────────────────────────


class TestFieldParsing(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date_to_iso("01/05/2026"), "2026-01-05")
        self.assertEqual(parse_date_to_iso("1/5/26"), "2026-01-05")
        self.assertEqual(parse_date_to_iso("2026-01-05"), "2026-01-05")
        self.assertIsNone(parse_date_to_iso("13/40/2026"))
        self.assertIsNone(parse_date_to_iso("yesterday"))

    def test_amounts(self):
        self.assertEqual(parse_amount_to_cents("1,234.56"), 123456)
        self.assertEqual(parse_amount_to_cents("$12.34"), 1234)
        self.assertEqual(parse_amount_to_cents("-12.34"), -1234)
        self.assertEqual(parse_amount_to_cents("(150.00)"), -15000)
        self.assertEqual(parse_amount_to_cents("12.34-"), -1234)
        self.assertEqual(parse_amount_to_cents("12.34CR"), -1234)
        self.assertIsNone(parse_amount_to_cents(""))
        self.assertIsNone(parse_amount_to_cents("12.345"))
        self.assertIsNone(parse_amount_to_cents("abc"))

    def test_ofx_dates(self):
        self.assertEqual(parse_ofx_date("20260302120000[-5:EST]"), "2026-03-02")
        self.assertEqual(parse_ofx_date("20260302"), "2026-03-02")
        self.assertIsNone(parse_ofx_date("2026030"))


# ── CSV issuer goldens ───────────────────────────────────────────────────────


class TestParseCsvIssuers(unittest.TestCase):
    def amounts_and_kinds(self, name):
        parsed = parse_csv(fixture(name), name)
        return [[t.amount_cents, t.kind] for t in parsed.txns]

    def test_chase_flips_negative_purchases(self):
        parsed = parse_csv(fixture("chase.csv"), "chase.csv")
        s = parsed.summary
        self.assertEqual((s.format, s.txns, s.rejected_rows, s.range_start, s.range_end),
                         ("csv", 7, 0, "2026-01-05", "2026-01-28"))
        t0 = parsed.txns[0]
        self.assertEqual((t0.date, t0.amount_cents, t0.kind, t0.descriptor,
                          t0.issuer_category, t0.line),
                         ("2026-01-05", 2450, "purchase",
                          "UBER *TRIP HELP.UBER.COM", "travel", 2))
        self.assertEqual([parsed.txns[3].amount_cents, parsed.txns[3].kind],
                         [-50000, "payment"])
        self.assertEqual([parsed.txns[5].amount_cents, parsed.txns[5].kind],
                         [-1250, "refund"])
        self.assertIsNone(s.column_inference)

    def test_amex_positive_purchases(self):
        self.assertEqual(self.amounts_and_kinds("amex.csv"), [
            [41260, "purchase"], [675, "purchase"], [-75000, "payment"],
            [28900, "purchase"], [550, "purchase"], [25000, "fee"]])

    def test_citi_debit_credit_pair(self):
        self.assertEqual(self.amounts_and_kinds("citi.csv"), [
            [16423, "purchase"], [1840, "purchase"], [-60000, "payment"],
            [5280, "purchase"], [-2000, "refund"]])

    def test_capital_one_autopay(self):
        parsed = parse_csv(fixture("capital-one.csv"), "capital-one.csv")
        self.assertEqual([[t.amount_cents, t.kind] for t in parsed.txns], [
            [32540, "purchase"], [4812, "purchase"], [-50000, "payment"],
            [1485, "purchase"]])
        self.assertEqual(parsed.txns[0].issuer_category, "airfare")

    def test_bofa_payee_profile(self):
        self.assertEqual(self.amounts_and_kinds("bofa.csv"), [
            [1199, "purchase"], [5642, "purchase"], [-85000, "payment"],
            [3875, "purchase"]])

    def test_discover_refunds(self):
        self.assertEqual(self.amounts_and_kinds("discover.csv"), [
            [7415, "purchase"], [1549, "purchase"], [-50000, "payment"],
            [4130, "purchase"], [-820, "refund"]])

    def test_generic_majority_sign_inference(self):
        self.assertEqual(self.amounts_and_kinds("generic.csv"), [
            [450, "purchase"], [3310, "purchase"], [-12000, "payment"],
            [1200, "purchase"]])

    def test_quirks_bom_crlf_quotes_parens(self):
        text = fixture_bytes("quirks.csv").decode("utf-8-sig")
        parsed = parse_csv(text, "quirks.csv")
        self.assertEqual(parsed.summary.txns, 3)
        self.assertEqual(parsed.txns[0].descriptor, 'JOE\'S "FAMOUS" PIZZA, INC')
        self.assertEqual(parsed.txns[0].amount_cents, 2340)
        self.assertEqual([parsed.txns[1].amount_cents, parsed.txns[1].kind],
                         [-15000, "refund"])

    def test_unmappable_headers_raise(self):
        with self.assertRaises(StatementParseError) as ctx:
            parse_csv("foo,bar\n1,2\n", "weird.csv")
        self.assertIn("date", str(ctx.exception))


# ── CSV column inference (plan 12, server-only) ─────────────────────────────


class TestColumnInference(unittest.TestCase):
    def test_headerless_csv(self):
        parsed = parse_csv(
            "01/05/2026,STARBUCKS #1234,4.50\n"
            "01/06/2026,WHOLE FOODS MKT,82.13\n"
            "01/07/2026,PAYMENT THANK YOU,-500.00\n"
            "01/09/2026,SHELL OIL 5551,41.00\n", "mystery.csv")
        self.assertEqual(parsed.summary.txns, 4)
        self.assertTrue(parsed.summary.column_inference["used"])
        self.assertEqual([t.amount_cents for t in parsed.txns],
                         [450, 8213, -50000, 4100])
        self.assertEqual(parsed.txns[2].kind, "payment")

    def test_unknown_header_names(self):
        parsed = parse_csv(
            "Fecha,Detalle,Importe\n"
            "02/01/2026,NETFLIX.COM,15.49\n"
            "02/03/2026,TRADER JOE S 987,54.20\n"
            "02/04/2026,DELTA AIR 0062341,321.00\n", "weird.csv")
        self.assertEqual(parsed.summary.txns, 3)
        self.assertTrue(parsed.summary.column_inference["used"])

    def test_inferred_debit_credit_pair(self):
        parsed = parse_csv(
            "Dia,Concepto,Cargo,Abono\n"
            "03/01/2026,COSTCO WHSE 112,120.55,\n"
            "03/02/2026,REFUND AMAZON,,30.00\n"
            "03/03/2026,CHEVRON 44,52.10,\n"
            "03/04/2026,KROGER 991,88.00,\n", "dc.csv")
        self.assertEqual([[t.amount_cents, t.kind] for t in parsed.txns], [
            [12055, "purchase"], [-3000, "refund"],
            [5210, "purchase"], [8800, "purchase"]])

    def test_no_date_column_still_raises(self):
        with self.assertRaises(StatementParseError):
            parse_csv("foo,bar\n1,2\n3,4\n", "nodates.csv")


# ── OFX ──────────────────────────────────────────────────────────────────────


class TestParseOfx(unittest.TestCase):
    def test_sgml(self):
        parsed = parse_ofx(fixture("sgml.ofx"), "sgml.ofx")
        s = parsed.summary
        self.assertEqual((s.format, s.txns, s.range_start, s.range_end),
                         ("ofx", 5, "2026-03-01", "2026-03-31"))
        t0 = parsed.txns[0]
        self.assertEqual((t0.date, t0.amount_cents, t0.kind, t0.mcc, t0.descriptor),
                         ("2026-03-02", 4567, "purchase", 5812,
                          "CHIPOTLE 2280 SEATTLE WA"))
        self.assertEqual(parsed.txns[1].descriptor,
                         "WHOLEFDS #10236 GROCERY PURCHASE")
        self.assertEqual([parsed.txns[2].amount_cents, parsed.txns[2].kind],
                         [-50000, "payment"])
        self.assertEqual([parsed.txns[3].amount_cents, parsed.txns[3].kind],
                         [-1230, "refund"])
        self.assertEqual([parsed.txns[4].amount_cents, parsed.txns[4].kind],
                         [2345, "interest"])
        self.assertFalse(any("DUPLICATE" in t.descriptor for t in parsed.txns))

    def test_xml_equals_sgml(self):
        def strip(t):
            return (t.date, t.amount_cents, t.descriptor, t.kind, t.mcc)
        sgml = [strip(t) for t in parse_ofx(fixture("sgml.ofx"), "a").txns]
        xml = [strip(t) for t in parse_ofx(fixture("xml.qfx"), "b").txns]
        self.assertEqual(xml, sgml)

    def test_empty_ofx_raises(self):
        with self.assertRaises(StatementParseError):
            parse_ofx("OFXHEADER:100\n<OFX></OFX>", "empty.ofx")


# ── PDF: pure line extraction ────────────────────────────────────────────────


class TestPdfLines(unittest.TestCase):
    def setUp(self):
        from statements.pdf import Word, extract_from_lines, reconstruct_lines
        self.Word = Word
        self.extract = extract_from_lines
        self.reconstruct = reconstruct_lines

    def test_reconstruct_clusters_and_orders(self):
        # pdfplumber tops grow DOWNWARD; the pdf.js test's y=714 header line
        # is above the y=700 txn line, so here it gets the smaller top.
        words = [
            self.Word("$87.13", 450, 700),
            self.Word(" ", 200, 700),
            self.Word("12/18", 72, 700.5),
            self.Word("WHOLEFDS #10236", 130, 699.8),
            self.Word("PURCHASES", 72, 686),
        ]
        self.assertEqual(self.reconstruct(words),
                         ["PURCHASES", "12/18 WHOLEFDS #10236 $87.13"])
        self.assertEqual(self.reconstruct([]), [])

    LINES = [
        "Opening/Closing Date 12/06/25 - 01/05/26",
        "Payments and Other Credits -$1,012.50",
        "Purchases +$223.31",
        "Fees Charged $0.00",
        "Interest Charged $0.00",
        "PAYMENTS AND OTHER CREDITS",
        "12/15 Payment Thank You - Web -$1,000.00",
        "12/20 WHOLEFDS #10236 SEATTLE WA -$12.50",
        "PURCHASES",
        "12/12 UBER *TRIP HELP.UBER.COM $24.50",
        "01/02 SHELL OIL 5744221 PORTLAND OR $41.20",
        "Total fees charged in 2025 $0.00",
    ]

    def test_period_totals_and_year_rollback(self):
        out = self.extract(self.LINES, "x.pdf")
        self.assertEqual(out["range_start"], "2025-12-06")
        self.assertEqual(out["range_end"], "2026-01-05")
        self.assertEqual(out["statement_totals"], {
            "purchases_cents": 22331, "payments_and_credits_cents": 101250,
            "fees_cents": 0, "interest_cents": 0})
        self.assertEqual([[t.date, t.amount_cents, t.kind] for t in out["txns"]], [
            ["2025-12-15", -100000, "payment"],
            ["2025-12-20", -1250, "refund"],
            ["2025-12-12", 2450, "purchase"],
            ["2026-01-02", 4120, "purchase"]])

    def test_long_form_dates_bilt(self):
        out = self.extract([
            "Apr 24 – May 23, 2026",
            "Payments and credits -$2,675.00",
            "Purchases (Including New Card Purchases) $2,680.43",
            "May 1, 2026 BILT RENT CHARGE ADJUSTMENT -$2,675.00",
            "May 1, 2026 BPS*BILT HOUSING 31 Bond St New York 10012 NY $2,675.00",
            "May 9, 2026 ROBLOX 1.888.858.2569 SAN MATEO $5.43",
            "Total new charges in this period $2,680.43",
        ], "bilt.pdf")
        self.assertEqual(out["range_start"], "2026-04-24")
        self.assertEqual(out["range_end"], "2026-05-23")
        self.assertEqual(out["period_count"], 1)
        self.assertEqual(out["statement_totals"], {
            "payments_and_credits_cents": 267500, "purchases_cents": 268043})
        self.assertEqual([[t.date, t.amount_cents, t.kind] for t in out["txns"]], [
            ["2026-05-01", -267500, "refund"],
            ["2026-05-01", 267500, "purchase"],
            ["2026-05-09", 543, "purchase"]])

    def test_multi_period_counted(self):
        out = self.extract([
            "February 23 - March 22, 2026", "02/25 KROGER #1 $10.00",
            "March 23 - April 22, 2026", "03/25 KROGER #1 $10.00",
        ], "combined.pdf")
        self.assertEqual(out["period_count"], 2)

    def test_explicit_years_without_period(self):
        out = self.extract(["03/05/2026 KROGER #442 $74.15"], "x.pdf")
        self.assertEqual([out["txns"][0].date, out["txns"][0].amount_cents],
                         ["2026-03-05", 7415])
        self.assertEqual(out["range_start"], "2026-03-05")

    def test_summary_box_furniture_skipped(self):
        """Bilt's account-summary box reconstructs as a dated line ("Apr 18,
        2026 Credit limit $10,000.00") — must never become a purchase (found
        in the plan-12 corpus rerun)."""
        out = self.extract([
            "Statement Period 1/1/2026 to 1/31/2026",
            "Apr 18, 2026 Credit limit $10,000.00",
            "Apr 18, 2026 Available credit $9,551.02",
            "01/12 KROGER #442 $74.15",
        ], "bilt.pdf")
        self.assertEqual([t.descriptor for t in out["txns"]], ["KROGER #442"])
        self.assertEqual(out["rejected_rows"], 0)  # furniture skips silently

    def test_undated_lines_without_period_raise(self):
        with self.assertRaises(StatementParseError) as ctx:
            self.extract(["12/12 UBER TRIP $24.50"], "x.pdf")
        self.assertIn("no statement period", str(ctx.exception))

    def test_prose_only_raises(self):
        with self.assertRaises(StatementParseError):
            self.extract(["just prose", "nothing here"], "x.pdf")


# ── PDF: layout-band fallback (plan 12, server-only) ─────────────────────────


class TestLayoutFallback(unittest.TestCase):
    def test_balance_column_layout(self):
        """Trailing running-balance column defeats the line regexes; the
        band vote picks the leftmost dense amount column instead."""
        import re

        from statements.pdf import Word, cluster_lines, layout_extract

        def line(top, date, desc, amount, balance):
            words = [Word(date, 50, top, 80)]
            x = 120
            for token in desc.split():
                words.append(Word(token, x, top, x + 40))
                x += 45
            words.append(Word(amount, 370, top, 400))
            words.append(Word(balance, 450, top, 480))
            return words

        words = [Word("Statement", 50, 10, 100), Word("Period", 105, 10, 140),
                 Word("1/1/2026", 145, 10, 190), Word("to", 195, 10, 205),
                 Word("1/31/2026", 210, 10, 260)]
        words += line(30, "01/03", "STARBUCKS #221", "6.40", "1,206.40")
        words += line(50, "01/05", "TRADER JOE S 987", "54.20", "1,260.60")
        words += line(70, "01/09", "PAYMENT THANK YOU", "-300.00", "960.60")
        words += line(90, "01/12", "SHELL OIL 4412", "38.75", "999.35")

        line_words = cluster_lines(words)
        lines = [re.sub(r"\s+", " ", " ".join(w.text for w in c)) for c in line_words]
        out = layout_extract(line_words, lines, "bal.pdf")
        self.assertEqual([[t.date, t.amount_cents, t.kind] for t in out["txns"]], [
            ["2026-01-03", 640, "purchase"],
            ["2026-01-05", 5420, "purchase"],
            ["2026-01-09", -30000, "payment"],
            ["2026-01-12", 3875, "purchase"]])
        self.assertEqual(out["range_start"], "2026-01-01")
        self.assertEqual(out["rejected_rows"], 0)


# ── PDF: end to end (needs pdfplumber) ───────────────────────────────────────


@unittest.skipUnless(HAS_PDF, "pdfplumber not installed")
class TestParsePdf(unittest.TestCase):
    def test_statement_pdf_end_to_end(self):
        data = base64.b64decode(fixture("statement.pdf.b64"))
        parsed = parse_statement(data, "statement.pdf")
        s = parsed.summary
        self.assertEqual((s.format, s.txns, s.range_start, s.range_end, s.extraction),
                         ("pdf", 7, "2025-12-06", "2026-01-05", "regex"))
        self.assertEqual(s.statement_totals, {
            "purchases_cents": 22331, "payments_and_credits_cents": 101250,
            "fees_cents": 0, "interest_cents": 0})
        purchases = [t for t in parsed.txns if t.kind == "purchase"]
        self.assertEqual(sum(t.amount_cents for t in purchases), 22331)
        refunds = [t for t in parsed.txns if t.kind == "refund"]
        self.assertEqual(sum(t.amount_cents for t in refunds), -1250)
        payment = next(t for t in parsed.txns if t.kind == "payment")
        self.assertEqual(payment.amount_cents, -100000)
        self.assertEqual(sorted(t.date for t in parsed.txns)[0], "2025-12-12")

    def test_scanned_pdf_rejected(self):
        data = base64.b64decode(fixture("scanned.pdf.b64"))
        with self.assertRaises(StatementParseError) as ctx:
            parse_statement(data, "scanned.pdf")
        self.assertEqual(ctx.exception.code, "scanned_pdf")
        self.assertIn("CSV", str(ctx.exception))

    def test_corrupt_pdf_user_error(self):
        with self.assertRaises(StatementParseError) as ctx:
            parse_statement(b"%PDF-1.7 garbage", "bad.pdf")
        self.assertIn("couldn't read this PDF", str(ctx.exception))


# ── entry point ──────────────────────────────────────────────────────────────


class TestParseStatementDispatch(unittest.TestCase):
    def test_unknown_format_code(self):
        with self.assertRaises(StatementParseError) as ctx:
            parse_statement(bytes([0, 1, 2]), "junk.bin")
        self.assertEqual(ctx.exception.code, "unrecognized_format")

    def test_oversize_code(self):
        from statements import MAX_FILE_BYTES
        with self.assertRaises(StatementParseError) as ctx:
            parse_statement(b"x" * (MAX_FILE_BYTES + 1), "big.csv")
        self.assertEqual(ctx.exception.code, "too_large")


# ── categorization (registries + fuzzy) ──────────────────────────────────────


class TestCategorize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml

        sys.path.insert(0, str(ROOT / "scripts"))
        import optimize as opt
        from statements.categorize import Matcher
        ds = opt.load_dataset()
        meta = ROOT / "data" / "meta"
        descriptors = yaml.safe_load(
            (meta / "statement-descriptors.yaml").read_text())["descriptors"]
        rules = yaml.safe_load((meta / "category-rules.yaml").read_text())
        cls.matcher = Matcher(descriptors, rules, ds["merchants"],
                              ds["usage_questions"])

    def match(self, descriptor, issuer_category=None, mcc=None):
        from statements.categorize import match_txn
        return match_txn(self.matcher, descriptor, issuer_category, mcc)

    def test_descriptor_layer(self):
        m = self.match("WHOLEFDS #10236 SEATTLE WA")
        self.assertEqual((m["category"], m["layer"], m["method"]),
                         ("groceries", 1, "exact"))
        self.assertEqual(m["merchant_key"], "whole_foods")

    def test_keyword_layer(self):
        m = self.match("SHELL OIL 5744221 PORTLAND OR")
        self.assertEqual((m["category"], m["layer"]), ("gas", 2))

    def test_issuer_category_layer(self):
        m = self.match("SOME UNKNOWN STORE", issuer_category="groceries")
        self.assertEqual((m["category"], m["layer"]), ("groceries", 3))

    def test_mcc_layer(self):
        m = self.match("SOME UNKNOWN STORE", mcc=5411)
        self.assertEqual((m["category"], m["layer"]), ("groceries", 4))

    def test_unmatched(self):
        m = self.match("TOTALLY UNKNOWN LLC")
        self.assertEqual((m["category"], m["layer"], m["method"]),
                         (None, None, None))

    @unittest.skipUnless(HAS_FUZZ, "rapidfuzz not installed")
    def test_fuzzy_layer_misspelling(self):
        m = self.match("STARBUKS #99881")
        self.assertEqual((m["category"], m["layer"], m["method"]),
                         ("dining", 5, "fuzzy"))
        self.assertGreaterEqual(m["confidence"], 0.9)

    @unittest.skipUnless(HAS_FUZZ, "rapidfuzz not installed")
    def test_fuzzy_never_overrides_exact(self):
        m = self.match("NETFLIX.COM 866-579-7172 CA")
        self.assertEqual((m["layer"], m["method"]), (1, "exact"))


class TestCategorizeGoldenTable(unittest.TestCase):
    """Matcher golden table ported from the retired engine.test.ts — inline
    registries shaped exactly like the YAML files, pinning prefix stripping,
    longest-pattern wins, tie-breaks, fallbacks, and labeled unmapped keys."""

    @classmethod
    def setUpClass(cls):
        from statements.categorize import Matcher
        descriptors = {
            "delta": {"label": "Delta Air Lines",
                      "statement_patterns": ["DELTA AIR LINES", "DELTA 006"]},
            "doordash": {"label": "DoorDash",
                         "statement_patterns": ["DD *DOORDASH", "DOORDASH"]},
            "uber": {"label": "Uber (rides)",
                     "statement_patterns": ["UBER *TRIP", "UBER TRIP"]},
            "uber_eats": {"label": "Uber Eats",
                          "statement_patterns": ["UBER *EATS", "UBER EATS"]},
            "costco": {"label": "Costco",
                       "statement_patterns": ["COSTCO WHSE", "COSTCO GAS"]},
            "whole_foods": {"label": "Whole Foods Market",
                            "statement_patterns": ["WHOLEFDS"]},
            "netflix": {"label": "Netflix", "statement_patterns": ["NETFLIX"]},
            "apple": {"label": "Apple",
                      "statement_patterns": ["APPLE.COM/BILL", "APPLE STORE"]},
            "apple_music": {"label": "Apple Music",
                            "statement_patterns": ["APPLE.COM/BILL"]},
            "paypal": {"label": "PayPal", "statement_patterns": ["PAYPAL *", "PP*"]},
            "toast_prefix": {"label": "Toast-acquired restaurants",
                             "statement_patterns": ["TST*"]},
            "square_prefix": {"label": "Square-acquired merchants",
                              "statement_patterns": ["SQ *"]},
            "bilt_rent": {"label": "Bilt rent/housing payments",
                          "statement_patterns": ["BILT"]},
        }
        rules = {
            "descriptor_categories": {
                "delta": "travel_flights", "doordash": "dining", "uber": "transit",
                "uber_eats": "dining", "costco": "groceries",
                "whole_foods": "groceries", "netflix": "streaming",
                "apple": "online_shopping", "apple_music": "streaming"},
            "aggregator_prefixes": {
                "paypal": {}, "square_prefix": {},
                "toast_prefix": {"fallback_category": "dining"}},
            "unmapped": ["bilt_rent"],
            "keywords": {"groceries": ["KROGER"], "gas": ["SHELL"],
                         "dining": ["CAFE "]},
            "issuer_categories": {"dining": "dining", "gasoline": "gas"},
            "mcc": [{"from": 5812, "to": 5814, "category": "dining"}],
        }
        merchants = {"costco": {}, "whole_foods": {}, "uber": {}}
        usage_questions = {"g": {"items": {
            "delta": {"label": "Delta"},
            "doordash": {"label": "DoorDash / DashPass"},
            "costco": {"label": "Costco"},
            "uber": {"label": "Uber rides / Uber One"}}}}
        cls.matcher = Matcher(descriptors, rules, merchants, usage_questions)

    CASES = [
        # (descriptor, issuer_category, mcc, expected subset of the match)
        ("DELTA AIR LINES ATLANTA", None, None,
         {"category": "travel_flights", "layer": 1, "usage_key": "delta",
          "descriptor_key": "delta"}),
        ("COSTCO WHSE #0021", None, None,
         {"category": "groceries", "layer": 1, "merchant_key": "costco",
          "usage_key": "costco", "descriptor_key": "costco"}),
        # Longest pattern: uber_eats, not uber.
        ("UBER *EATS PENDING", None, None,
         {"category": "dining", "layer": 1, "descriptor_key": "uber_eats"}),
        # Identical patterns tie-break by key asc -> apple.
        ("APPLE.COM/BILL 866-712-7753", None, None,
         {"category": "online_shopping", "layer": 1, "descriptor_key": "apple"}),
        # Prefix strip -> inner descriptor match.
        ("PAYPAL *DD *DOORDASH", None, None,
         {"category": "dining", "layer": 1, "usage_key": "doordash",
          "descriptor_key": "doordash"}),
        # Prefix strip -> inner keyword match.
        ("PAYPAL *KROGER 442", None, None, {"category": "groceries", "layer": 2}),
        # Prefix, unknown remainder -> fallback.
        ("TST* JOES CRAB SHACK", None, None,
         {"category": "dining", "layer": 1, "descriptor_key": "toast_prefix"}),
        # Prefix, unknown remainder, no fallback.
        ("SQ *UNKNOWN VENDOR", None, None, {"category": None, "layer": None}),
        # Explicitly unmapped -> labeled group.
        ("BILT REWARDS 000123", None, None,
         {"category": None, "layer": None, "descriptor_key": "bilt_rent",
          "descriptor_label": "Bilt rent/housing payments"}),
        ("KROGER #442 SPRINGFIELD", None, None,
         {"category": "groceries", "layer": 2}),
        ("MYSTERY MERCHANT", "dining", None, {"category": "dining", "layer": 3}),
        ("MYSTERY MERCHANT", None, 5813, {"category": "dining", "layer": 4}),
        ("MYSTERY MERCHANT", None, None, {"category": None, "layer": None}),
    ]

    def test_golden_table(self):
        from statements.categorize import match_txn
        for descriptor, issuer_category, mcc, expected in self.CASES:
            with self.subTest(descriptor=descriptor):
                match = match_txn(self.matcher, descriptor, issuer_category, mcc)
                for key, value in expected.items():
                    self.assertEqual(match.get(key), value,
                                     f"{descriptor}: {key}")

    def test_normalize_and_stem(self):
        from statements.categorize import descriptor_stem, match_txn, normalize_descriptor
        self.assertEqual(normalize_descriptor("  netflix.COM   ca "), "NETFLIX.COM CA")
        self.assertEqual(match_txn(self.matcher, "netflix.com", None, None)["category"],
                         "streaming")
        self.assertEqual(descriptor_stem("KWIK-E-MART #442 SPRINGFIELD"),
                         descriptor_stem("KWIK-E-MART #187 SPRINGFIELD"))
        self.assertEqual(descriptor_stem("KWIK-E-MART #442 SPRINGFIELD"),
                         "KWIK-E-MART SPRINGFIELD")
        self.assertEqual(descriptor_stem("12345"), "12345")  # all-numeric falls back


if __name__ == "__main__":
    unittest.main()
