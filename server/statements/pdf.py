"""PDF statement parsing via pdfplumber (port of site pdf.ts + layout fallback).

Bank statement PDFs are digitally generated with a text layer; pdfplumber
extracts positioned words in-process. Scanned/image-only PDFs yield zero
words and are rejected with a pointer to the issuer's CSV export instead of
guessing via OCR (no OCR by design — tesseract can't ship in the function).

Primary extraction is the corpus-verified generic path ported from pdf.ts:
words -> top-clustered visual lines -> date/description/amount transaction
regexes, plus the statement's own summary box (Purchases / Payments and
Credits / Fees / Interest) so the browser aggregator can reconcile parsed
sums against the issuer's printed totals and warn on mismatch.

New on the server (plan 12): when the regex path finds ZERO transaction
lines on a text-bearing PDF, a layout-band fallback re-reads the word
geometry — lines that start with a date and carry amount-shaped words get
their amount picked by column band (the leftmost dense right-aligned amount
band, so a trailing running-balance column doesn't win). The summary
records which path produced the result (extraction: "regex" | "layout").

pdfplumber is imported lazily by the package entry point so optimizer-only
cold starts never pay for it.
"""

import io
import re
from collections import defaultdict
from typing import List, Optional

from .csv_parse import parse_amount_to_cents, parse_date_to_iso
from .kind import classify_kind, refine_refund
from .types import ParsedFile, ScannedPdfError, StatementParseError, Summary, Txn

MAX_PDF_PAGES = 200

# ── Pure text-layer reconstruction (unit-tested without pdfplumber) ──────────

Y_TOLERANCE = 2


class Word:
    """One positioned word. `top` grows downward (pdfplumber's coordinate
    system; pdf.js used bottom-left origin — the port flips the sort)."""

    __slots__ = ("text", "x0", "x1", "top")

    def __init__(self, text: str, x0: float, top: float, x1: Optional[float] = None):
        self.text = text
        self.x0 = x0
        self.x1 = x1 if x1 is not None else x0
        self.top = top


def cluster_lines(words: List[Word]) -> List[List[Word]]:
    """Positioned words -> visual lines: cluster by top (ascending = page
    order), order by x within a cluster."""
    real = [w for w in words if w.text.strip() != ""]
    ordered = sorted(real, key=lambda w: (w.top, w.x0))
    lines: List[List[Word]] = []
    current: List[Word] = []
    current_top = None
    for w in ordered:
        if current_top is None or abs(w.top - current_top) > Y_TOLERANCE:
            if current:
                # Re-sort by x: the global top sort scrambles x order inside
                # a near-top cluster.
                current.sort(key=lambda i: i.x0)
                lines.append(current)
            current = []
            current_top = w.top
        current.append(w)
    if current:
        current.sort(key=lambda i: i.x0)
        lines.append(current)
    return lines


def reconstruct_lines(words: List[Word]) -> List[str]:
    """Word clusters joined to text lines (whitespace collapsed) — the input
    shape the corpus-verified regexes were written against."""
    return [re.sub(r"\s+", " ", " ".join(w.text.strip() for w in cluster)).strip()
            for cluster in cluster_lines(words)]


# ── Pure line -> transaction extraction (direct port of pdf.ts) ──────────────

MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
             "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MONTH = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"


def parse_long_date(month: str, day: str, year: str) -> Optional[str]:
    """"May 1, 2026" -> 2026-05-01 (None on garbage)."""
    mo = MONTH_NUM.get(month[:3].lower())
    d = int(day)
    if mo is None or d < 1 or d > 31:
        return None
    return f"{year}-{mo:02d}-{d:02d}"


# "Opening/Closing Date 12/06/25 - 01/05/26" / "Statement Period 1/1/2026 to 1/31/2026"
PERIOD = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{2,4})\s*(?:-|–|—|to|through)\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
# "February 23 - March 22, 2026" / "Apr 24 – May 23, 2026" (start year
# optional: inherits the end year, rolling back one across Dec-Jan).
PERIOD_LONG = re.compile(
    rf"{MONTH}\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\s*(?:-|–|—|to|through)\s*{MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})",
    re.I)

# "12/18 WHOLEFDS #10236 SEATTLE WA $87.13", optional post date, optional
# year on the transaction date, trailing CR/minus/parenthesized negatives.
TXN_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2})(/\d{2,4})?\s+(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+)?(.*?)\s+(-?\(?\$?\s?[\d,]+\.\d{2}\)?(?:-|\s*CR)?)$")
# "May 1, 2026 BPS*BILT HOUSING 31 Bond St New York $2,675.00" (Bilt).
TXN_LINE_LONG = re.compile(
    rf"^{MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})\s+(.*?)\s+(-?\(?\$?\s?[\d,]+\.\d{{2}}\)?(?:-|\s*CR)?)$",
    re.I)

TOTALS_PATTERNS = [
    ("purchases_cents", re.compile(r"^[+\-]?\s*(?:total\s+)?(?:purchases\b|new\s+charges\b)", re.I)),
    ("payments_and_credits_cents",
     re.compile(r"^[+\-]?\s*(?:total\s+)?payments?\b(?:\s*(?:and|&|/)\s*(?:other\s+)?credits)?\b", re.I)),
    ("fees_cents", re.compile(r"^[+\-]?\s*(?:total\s+)?fees\s+charged\b", re.I)),
    ("interest_cents", re.compile(r"^[+\-]?\s*(?:total\s+)?interest\s+charged\b", re.I)),
]
TOTALS_AMOUNT = re.compile(r"(-?\(?\$?[\d,]+\.\d{2}\)?-?)\s*$")
NON_DESCRIPTOR = re.compile(r"^[\d\s$,.()-]*$")  # digits/punctuation only = not a merchant


def _mmdd_to_iso(mmdd: str, period_end_iso: str) -> Optional[str]:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", mmdd)
    if not m:
        return None
    end_year = int(period_end_iso[:4])
    iso = parse_date_to_iso(f"{m.group(1)}/{m.group(2)}/{end_year}")
    if iso is None:
        return None
    # A December transaction on a statement closing in January belongs to the
    # previous year: anything after the period end rolls back one year.
    if iso > period_end_iso:
        return parse_date_to_iso(f"{m.group(1)}/{m.group(2)}/{end_year - 1}")
    return iso


def scan_periods(lines: List[str]):
    """First period line dates the MM/DD transactions; every DISTINCT period
    seen is counted, because >1 means a multi-statement combined PDF whose
    transactions can't all be dated by one period (surfaced as a warning)."""
    period_start = period_end = None
    periods_seen = set()
    for line in lines:
        start = end = None
        m = PERIOD.search(line)
        if m:
            start = parse_date_to_iso(m.group(1))
            end = parse_date_to_iso(m.group(2))
        else:
            ml = PERIOD_LONG.search(line)
            if ml:
                start_month, start_day, start_year, end_month, end_day, end_year = ml.groups()
                end = parse_long_date(end_month, end_day, end_year)
                start = parse_long_date(start_month, start_day, start_year or end_year)
                # "Dec 24 – Jan 23, 2026" without a start year spans the year boundary.
                if start and end and start_year is None and start > end:
                    start = parse_long_date(start_month, start_day, str(int(end_year) - 1))
        if start and end:
            periods_seen.add(f"{start}..{end}")
            if period_start is None:
                period_start, period_end = start, end
    return period_start, period_end, len(periods_seen)


def scan_totals(lines: List[str]) -> dict:
    """Summary box ("Purchases +$223.31"). Year-to-date recap lines ("Total
    fees charged in 2025") are skipped: only cycle totals reconcile."""
    totals = {}
    for line in lines:
        if TXN_LINE.match(line) or TXN_LINE_LONG.match(line):
            continue  # never a txn line (those start with a date)
        if re.search(r"\bin\s+\d{4}\b", line, re.I):
            continue
        for key, pattern in TOTALS_PATTERNS:
            if key not in totals and pattern.match(line):
                amount = TOTALS_AMOUNT.search(line)
                cents = parse_amount_to_cents(amount.group(1)) if amount else None
                if cents is not None:
                    totals[key] = abs(cents)
                break
    return totals


def extract_from_lines(lines: List[str], file: str) -> dict:
    period_start, period_end, period_count = scan_periods(lines)
    statement_totals = {}
    txns = []
    rejected_rows = 0

    for line in lines:
        # Numeric (Chase/BofA "02/20 02/23 DESC ... 25.00") or long-form
        # (Bilt "May 1, 2026 DESC ... $2,675.00") transaction lines.
        date_iso = None
        desc = amount_raw = None
        txn_match = TXN_LINE.match(line)
        long_match = None if txn_match else TXN_LINE_LONG.match(line)
        if txn_match:
            mmdd, year_part = txn_match.group(1), txn_match.group(2)
            desc = txn_match.group(3)
            amount_raw = txn_match.group(4)
            if year_part:
                date_iso = parse_date_to_iso(mmdd + year_part)
            elif period_end:
                date_iso = _mmdd_to_iso(mmdd, period_end)
        elif long_match:
            month, day, year = long_match.group(1), long_match.group(2), long_match.group(3)
            desc = long_match.group(4)
            amount_raw = long_match.group(5)
            date_iso = parse_long_date(month, day, year)
        if txn_match or long_match:
            descriptor = (desc or "").strip()
            amount_cents = parse_amount_to_cents(amount_raw or "")
            if (date_iso is None or amount_cents is None or descriptor == ""
                    or NON_DESCRIPTOR.fullmatch(descriptor)):
                rejected_rows += 1
                continue
            # PDF statements print charges positive and payments/credits negative.
            txns.append(Txn(
                date=date_iso, amount_cents=amount_cents, descriptor=descriptor,
                kind=refine_refund(classify_kind(descriptor), amount_cents),
                line=len(txns) + 1,
            ))
            continue

        if re.search(r"\bin\s+\d{4}\b", line, re.I):
            continue
        for key, pattern in TOTALS_PATTERNS:
            if key not in statement_totals and pattern.match(line):
                amount = TOTALS_AMOUNT.search(line)
                cents = parse_amount_to_cents(amount.group(1)) if amount else None
                if cents is not None:
                    statement_totals[key] = abs(cents)
                break

    if not txns:
        raise StatementParseError(
            f"{file}: no transaction lines recognized"
            + (" (no statement period found to date them by)" if period_end is None else "")
            + " — download the CSV export from your issuer instead.")

    dates = sorted(t.date for t in txns)
    return {
        "txns": txns,
        "rejected_rows": rejected_rows,
        "range_start": period_start or dates[0],
        "range_end": period_end or dates[-1],
        "statement_totals": statement_totals,
        "period_count": period_count,
    }


# ── Layout-band fallback (plan 12 — new, no TS ancestor) ─────────────────────

AMOUNT_WORD = re.compile(r"^-?\(?\$?[\d,]+\.\d{2}\)?(?:-|CR)?$")
BAND_TOLERANCE = 6  # points; amount columns are right-aligned on x1


def _line_date(words: List[Word], period_end: Optional[str]):
    """Leading date on a line: MM/DD[/YY], or month-name + day [, year].
    Returns (iso_date_or_None, words_consumed)."""
    if not words:
        return None, 0
    first = words[0].text
    m = re.fullmatch(r"(\d{1,2}/\d{1,2})(/\d{2,4})?,?", first)
    if m:
        if m.group(2):
            return parse_date_to_iso(m.group(1) + m.group(2)), 1
        if period_end:
            return _mmdd_to_iso(m.group(1), period_end), 1
        return None, 1
    # "May 1, 2026" split across words.
    if re.fullmatch(MONTH, first, re.I) and len(words) >= 2:
        dm = re.fullmatch(r"(\d{1,2}),?", words[1].text)
        if dm:
            if len(words) >= 3 and re.fullmatch(r"\d{4},?", words[2].text):
                return parse_long_date(first, dm.group(1), words[2].text.rstrip(",")), 3
            if period_end:
                iso = parse_long_date(first, dm.group(1), period_end[:4])
                if iso and iso > period_end:
                    iso = parse_long_date(first, dm.group(1), str(int(period_end[:4]) - 1))
                return iso, 2
    return None, 0


def layout_extract(line_words: List[List[Word]], lines: List[str], file: str) -> dict:
    """Column-geometry fallback for layouts the line regexes can't see —
    e.g. a trailing running-balance column, so the amount isn't the last
    token. Dated lines vote for right-aligned amount-column bands (grouped
    by x1); the LEFTMOST band dense enough on those lines is the transaction
    amount (a balance column sits further right). Everything downstream —
    kind classification, reconciliation, review — treats the result exactly
    like the regex path; extraction="layout" is surfaced to the UI."""
    period_start, period_end, period_count = scan_periods(lines)

    dated = []  # (date_iso, consumed, words)
    for words in line_words:
        date_iso, consumed = _line_date(words, period_end)
        if date_iso:
            dated.append((date_iso, consumed, words))
    if not dated:
        raise StatementParseError(
            f"{file}: no transaction lines recognized — download the CSV "
            f"export from your issuer instead.")

    # Vote for amount bands by right edge across dated lines.
    votes = defaultdict(int)
    for _, consumed, words in dated:
        for w in words[consumed:]:
            if AMOUNT_WORD.fullmatch(w.text):
                votes[round(w.x1 / BAND_TOLERANCE)] += 1
    threshold = max(2, len(dated) // 2)
    bands = sorted(k for k, n in votes.items() if n >= threshold)
    if not bands:
        raise StatementParseError(
            f"{file}: no transaction lines recognized — download the CSV "
            f"export from your issuer instead.")
    amount_band = bands[0]  # leftmost dense band; balances sit further right

    txns = []
    rejected_rows = 0
    for date_iso, consumed, words in dated:
        rest = words[consumed:]
        amount_word = next(
            (w for w in rest
             if AMOUNT_WORD.fullmatch(w.text) and round(w.x1 / BAND_TOLERANCE) == amount_band),
            None)
        if amount_word is None:
            rejected_rows += 1
            continue
        amount_cents = parse_amount_to_cents(amount_word.text)
        descriptor = re.sub(r"\s+", " ", " ".join(
            w.text.strip() for w in rest if w.x1 < amount_word.x0)).strip()
        if amount_cents is None or descriptor == "" or NON_DESCRIPTOR.fullmatch(descriptor):
            rejected_rows += 1
            continue
        txns.append(Txn(
            date=date_iso, amount_cents=amount_cents, descriptor=descriptor,
            kind=refine_refund(classify_kind(descriptor), amount_cents),
            line=len(txns) + 1,
        ))
    if not txns:
        raise StatementParseError(
            f"{file}: no transaction lines recognized — download the CSV "
            f"export from your issuer instead.")

    dates = sorted(t.date for t in txns)
    return {
        "txns": txns,
        "rejected_rows": rejected_rows,
        "range_start": period_start or dates[0],
        "range_end": period_end or dates[-1],
        "statement_totals": scan_totals(lines),
        "period_count": period_count,
    }


# ── Entry point ──────────────────────────────────────────────────────────────


def parse_pdf(data: bytes, file: str) -> ParsedFile:
    import pdfplumber  # lazy: keep optimizer-only cold starts fast
    from pdfminer.pdfexceptions import PDFException
    from pdfminer.psexceptions import PSException
    from pdfplumber.utils.exceptions import PdfminerException

    unreadable = (PdfminerException, PDFException, PSException,
                  ValueError, KeyError, TypeError)
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except unreadable:
        # Corrupt/encrypted/unreadable PDF — a per-file, user-renderable error.
        raise StatementParseError(
            f"{file}: couldn't read this PDF — download the CSV export from "
            f"your issuer instead.")
    with pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise StatementParseError(f"{file}: more than {MAX_PDF_PAGES} pages.")
        words: List[Word] = []
        for page in pdf.pages:
            try:
                extracted = page.extract_words()
            except unreadable:
                continue  # one broken page shouldn't kill the statement
            base = page.page_number * 100_000  # keep pages in order, tops page-local
            words.extend(
                Word(w["text"], w["x0"], base + w["top"], w["x1"]) for w in extracted)
    if not any(w.text.strip() for w in words):
        raise ScannedPdfError(file)

    line_words = cluster_lines(words)
    lines = [re.sub(r"\s+", " ", " ".join(w.text.strip() for w in cluster)).strip()
             for cluster in line_words]

    try:
        extract = extract_from_lines(lines, file)
        extraction = "regex"
    except StatementParseError:
        extract = layout_extract(line_words, lines, file)
        extraction = "layout"

    return ParsedFile(
        summary=Summary(
            name=file,
            format="pdf",
            txns=len(extract["txns"]),
            rejected_rows=extract["rejected_rows"],
            range_start=extract["range_start"],
            range_end=extract["range_end"],
            statement_totals=extract["statement_totals"] or None,
            period_count=extract["period_count"],
            extraction=extraction,
        ),
        txns=extract["txns"],
    )
