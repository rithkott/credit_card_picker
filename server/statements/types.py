"""Statement-parsing core types (plan 12 — server-side port of plan 09).

Everything here lives and dies in request memory: statement bytes and
transactions are parsed in-process and never written anywhere (no debug
dumps on this path, no storage). The parsers normalize every format into
Txn objects; detect_usage matches them against statement-descriptors.yaml
and only the usage-item hits are returned to the browser (plan 14) — full
transaction lists never leave the server.

Field names are the API contract (snake_case). The parsers were verified
against a real 42-file corpus (docs/local/09), so parsing semantics must
not drift.
"""

from dataclasses import dataclass, field
from typing import Optional

# purchase | refund | payment | fee | interest | transfer
TXN_KINDS = ("purchase", "refund", "payment", "fee", "interest", "transfer")


class StatementParseError(Exception):
    """User-renderable parse failure. `code` keys the API error taxonomy:
    scanned_pdf | unrecognized_format | no_transactions | too_many_txns |
    too_large (mapped to HTTP 413, the rest to 422)."""

    def __init__(self, message: str, code: str = "no_transactions"):
        super().__init__(message)
        self.code = code


class ScannedPdfError(StatementParseError):
    """PDF with no extractable text layer (scanned/image-only)."""

    def __init__(self, file: str):
        super().__init__(
            f"{file} has no extractable text (it looks scanned). "
            f"Download the CSV export from your issuer instead.",
            code="scanned_pdf",
        )


@dataclass
class Txn:
    """One normalized transaction. Positive amount = money spent, negative =
    money back (refund). Payments/fees/interest/transfers keep their sign but
    are excluded from spend by kind (browser-side aggregate)."""

    date: str  # YYYY-MM-DD
    amount_cents: int
    descriptor: str  # raw statement description, trimmed
    kind: str  # one of TXN_KINDS
    line: int  # 1-based row/line/block index in the source file
    issuer_category: Optional[str] = None  # issuer's own category column, lowercased
    mcc: Optional[int] = None  # CSV MCC column or OFX <SIC>

    def to_dict(self) -> dict:
        out = {
            "date": self.date,
            "amount_cents": self.amount_cents,
            "descriptor": self.descriptor,
            "kind": self.kind,
            "line": self.line,
        }
        if self.issuer_category is not None:
            out["issuer_category"] = self.issuer_category
        if self.mcc is not None:
            out["mcc"] = self.mcc
        return out


@dataclass
class Summary:
    """Per-file summary; `statement_totals` (positive cents) comes from a PDF
    summary box for reconciliation, `period_count` > 1 flags several
    statements combined into one PDF, `extraction` records which PDF path
    produced the transactions (regex | layout), `column_inference` records a
    semantic CSV column guess the review UI should surface."""

    name: str
    format: str  # csv | ofx | pdf
    txns: int
    rejected_rows: int
    range_start: str
    range_end: str
    statement_totals: Optional[dict] = None
    period_count: Optional[int] = None
    extraction: Optional[str] = None
    column_inference: Optional[dict] = None  # {"used": bool, "confidence": float}

    def to_dict(self) -> dict:
        out = {
            "name": self.name,
            "format": self.format,
            "txns": self.txns,
            "rejected_rows": self.rejected_rows,
            "range_start": self.range_start,
            "range_end": self.range_end,
        }
        for key in ("statement_totals", "period_count", "extraction", "column_inference"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass
class ParsedFile:
    summary: Summary
    txns: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary.to_dict(),
            "txns": [t.to_dict() for t in self.txns],
        }
