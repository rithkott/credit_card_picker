"""CSV statement parsing (port of site csv.ts + new column inference).

Hand-rolled RFC-4180 reader (quotes, escaped quotes, CRLF, embedded
newlines) + issuer header profiles for the major US issuers + a generic
header-synonym fallback. Sign conventions are normalized so SPEND IS
POSITIVE; issuers disagree (Chase/BofA export purchases negative, Amex and
Discover positive), so each profile declares its convention and the generic
fallback infers it from the majority sign of purchase rows.

New on the server (plan 12): when header mapping fails — unknown header
names, or no header row at all — semantic column inference (columns.py)
scores columns by content shape and, above a confidence floor, maps them
anyway. The guess is reported in summary.column_inference so the review UI
can disclose it.

The reader/parsers are named exports because tests and the PDF/OFX modules
reuse parse_date_to_iso / parse_amount_to_cents.
"""

import math
import re
from dataclasses import dataclass
from typing import Optional

from .columns import infer_columns
from .kind import classify_kind, refine_refund
from .types import ParsedFile, StatementParseError, Summary, Txn

# ── RFC-4180 reader ──────────────────────────────────────────────────────────


def parse_csv_rows(text: str) -> list:
    """Parse CSV text into [{"fields": [...], "line": n}] with each row's
    1-based line number in the original file (quoted fields may span lines)."""
    rows = []
    fields = []
    field_chars = []
    in_quotes = False
    line = 1
    row_line = 1
    saw_any = False

    def push_field():
        nonlocal saw_any
        fields.append("".join(field_chars))
        field_chars.clear()
        saw_any = True

    def push_row():
        nonlocal fields, saw_any, row_line
        push_field()
        if len(fields) > 1 or fields[0].strip() != "":
            rows.append({"fields": fields, "line": row_line})
        fields = []
        saw_any = False
        row_line = line

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field_chars.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                if ch == "\n":
                    line += 1
                field_chars.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch == ",":
            push_field()
        elif ch == "\n":
            line += 1
            push_row()
        elif ch != "\r":
            field_chars.append(ch)
        i += 1
    if saw_any or field_chars:
        push_row()
    return rows


# ── Header mapping ───────────────────────────────────────────────────────────


@dataclass
class ColumnMap:
    date: int
    description: int
    amount: Optional[int] = None
    debit: Optional[int] = None
    credit: Optional[int] = None
    category: Optional[int] = None
    type: Optional[int] = None
    mcc: Optional[int] = None


@dataclass
class IssuerProfile:
    issuer: str
    requires: list  # lowercased header names that identify this profile
    negative_purchases: bool  # export writes purchases as negative amounts


# Header fingerprints for the big issuers' transaction exports. Drafted from
# their documented CSV layouts, confidence: low until checked against real
# exports (same caveat as data/meta/statement-descriptors.yaml).
ISSUER_PROFILES = [
    IssuerProfile("chase", ["transaction date", "post date", "description", "type", "amount"], True),
    IssuerProfile("amex", ["date", "description", "amount"], False),
    IssuerProfile("citi", ["status", "date", "description", "debit", "credit"], False),
    IssuerProfile("capital-one", ["transaction date", "posted date", "description", "debit", "credit"], False),
    IssuerProfile("bofa", ["posted date", "payee", "amount"], True),
    IssuerProfile("discover", ["trans. date", "post date", "description", "amount"], False),
]

DATE_SYNONYMS = ["transaction date", "trans. date", "trans date", "date", "posted date", "post date"]
DESC_SYNONYMS = ["description", "payee", "merchant", "name", "details", "memo"]
AMOUNT_SYNONYMS = ["amount", "transaction amount", "amount (usd)"]
DEBIT_SYNONYMS = ["debit", "withdrawals", "charge"]
CREDIT_SYNONYMS = ["credit", "deposits"]
CATEGORY_SYNONYMS = ["category"]
TYPE_SYNONYMS = ["type", "transaction type"]
MCC_SYNONYMS = ["mcc", "merchant category code", "sic"]


def _find_column(headers: list, synonyms: list) -> Optional[int]:
    for syn in synonyms:
        if syn in headers:
            return headers.index(syn)
    return None


def map_headers(headers: list):
    lower = [h.strip().lower() for h in headers]
    profile = next((p for p in ISSUER_PROFILES if all(r in lower for r in p.requires)), None)

    date = _find_column(lower, DATE_SYNONYMS)
    description = _find_column(lower, DESC_SYNONYMS)
    amount = _find_column(lower, AMOUNT_SYNONYMS)
    debit = _find_column(lower, DEBIT_SYNONYMS)
    credit = _find_column(lower, CREDIT_SYNONYMS)
    if date is None or description is None or (amount is None and debit is None and credit is None):
        raise StatementParseError(
            f"Couldn't recognize the CSV columns (got: {', '.join(headers) or 'none'}). "
            f"The file needs a date, a description, and an amount (or debit/credit) column.",
            code="unrecognized_format",
        )
    return (
        ColumnMap(
            date=date, description=description, amount=amount, debit=debit, credit=credit,
            category=_find_column(lower, CATEGORY_SYNONYMS),
            type=_find_column(lower, TYPE_SYNONYMS),
            mcc=_find_column(lower, MCC_SYNONYMS),
        ),
        profile,
    )


# ── Field parsing ────────────────────────────────────────────────────────────


def parse_date_to_iso(text: str) -> Optional[str]:
    """MM/DD/YYYY, MM/DD/YY, or YYYY-MM-DD -> ISO YYYY-MM-DD (None on garbage)."""
    t = text.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _check_ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}(?:\d{2})?)", t)
    if m:
        year = int(m.group(3))
        if year < 100:
            year += 1900 if year >= 70 else 2000
        return _check_ymd(year, int(m.group(1)), int(m.group(2)))
    return None


def _check_ymd(y: int, mo: int, d: int) -> Optional[str]:
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return None
    return f"{y}-{mo:02d}-{d:02d}"


def parse_amount_to_cents(text: str) -> Optional[int]:
    """"$1,234.56", "(12.34)", "12.34-", "-12.34" -> signed cents (None on garbage)."""
    t = text.strip()
    if t == "":
        return None
    sign = 1
    if t.startswith("(") and t.endswith(")"):
        sign = -1
        t = t[1:-1]
    if t.endswith("-"):
        sign = -sign
        t = t[:-1]
    if t.endswith("CR"):
        sign = -sign
        t = t[:-2].strip()
    if t.startswith("-"):
        sign = -sign
        t = t[1:]
    elif t.startswith("+"):
        t = t[1:]
    t = re.sub(r"[$,\s]", "", t)
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    # floor(x+0.5) mirrors JS Math.round half-up (Python round() half-evens).
    return sign * math.floor(float(t) * 100 + 0.5)


# ── Parser ───────────────────────────────────────────────────────────────────


def parse_csv(text: str, file: str) -> ParsedFile:
    rows = parse_csv_rows(text)
    if not rows:
        raise StatementParseError(f"{file} is empty.", code="unrecognized_format")

    inference = None
    try:
        col_map, profile = map_headers(rows[0]["fields"])
        data_rows = rows[1:]
    except StatementParseError as header_error:
        # Semantic fallback: score columns by content shape. Headerless files
        # keep row 0 as data; files with an unrecognized header drop it.
        inferred = infer_columns(rows, parse_date_to_iso, parse_amount_to_cents)
        if inferred is None:
            raise header_error
        col_map, headerless, confidence = inferred
        profile = None
        data_rows = rows if headerless else rows[1:]
        inference = {"used": True, "confidence": round(confidence, 2)}

    txns = []
    rejected_rows = 0
    for row in data_rows:
        f = row["fields"]

        def cell(idx):
            return f[idx] if idx is not None and idx < len(f) else ""

        date_iso = parse_date_to_iso(cell(col_map.date))
        descriptor = cell(col_map.description).strip()
        cents = None
        if col_map.amount is not None:
            cents = parse_amount_to_cents(cell(col_map.amount))
        else:
            # Debit/credit pair: debit = money spent, credit = money back.
            debit = parse_amount_to_cents(cell(col_map.debit)) if col_map.debit is not None else None
            credit = parse_amount_to_cents(cell(col_map.credit)) if col_map.credit is not None else None
            if debit is not None and debit != 0:
                cents = abs(debit)
            elif credit is not None and credit != 0:
                cents = -abs(credit)
            elif debit is not None or credit is not None:
                cents = 0
        if date_iso is None or cents is None or descriptor == "":
            rejected_rows += 1
            continue
        kind = classify_kind(descriptor, csv_type=cell(col_map.type) if col_map.type is not None else None)
        issuer_category = cell(col_map.category).strip().lower() if col_map.category is not None else ""
        mcc_text = cell(col_map.mcc).strip() if col_map.mcc is not None else ""
        mcc = int(mcc_text) if mcc_text.isdigit() and int(mcc_text) > 0 else None
        txns.append(Txn(
            date=date_iso,
            amount_cents=cents,
            descriptor=descriptor,
            kind=kind,
            line=row["line"],
            issuer_category=issuer_category or None,
            mcc=mcc,
        ))
    if not txns:
        raise StatementParseError(
            f"{file}: no parseable transactions ({rejected_rows} row(s) rejected).",
        )

    # Sign normalization to spend-positive. Profiles declare their convention;
    # the generic fallback infers it: if most purchase-classified rows are
    # negative, the export writes purchases negative.
    if profile:
        flip = profile.negative_purchases and col_map.amount is not None
    elif col_map.amount is not None:
        purchases = [t for t in txns if t.kind == "purchase" and t.amount_cents != 0]
        negatives = sum(1 for t in purchases if t.amount_cents < 0)
        flip = bool(purchases) and negatives * 2 > len(purchases)
    else:
        flip = False  # debit/credit pairs are already normalized above
    for t in txns:
        if flip:
            t.amount_cents = -t.amount_cents
        t.kind = refine_refund(t.kind, t.amount_cents)

    dates = sorted(t.date for t in txns)
    return ParsedFile(
        summary=Summary(
            name=file,
            format="csv",
            txns=len(txns),
            rejected_rows=rejected_rows,
            range_start=dates[0] if dates else "",
            range_end=dates[-1] if dates else "",
            column_inference=inference,
        ),
        txns=txns,
    )
