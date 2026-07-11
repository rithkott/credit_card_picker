"""Server-side statement parsing (plan 12) — deterministic, ephemeral.

Entry point: parse_statement(data, name) — sniff the format, parse, classify
kinds. Categorization is a separate pass (categorize.annotate) because the
matcher is compiled once from the registries at app startup.

Everything is deterministic and free: no LLM, no network, no storage. One
request = one file; the FastAPI route holds the bytes in memory and drops
them when the response is built.
"""

from .detect import detect_format
from .types import ParsedFile, ScannedPdfError, StatementParseError

# Per-file caps. 4 MB tracks Vercel's 4.5 MB request-body limit (multipart
# overhead needs headroom); the browser enforces the same number before
# uploading so oversize files fail fast with a local message.
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TXNS_PER_FILE = 50_000


def parse_statement(data: bytes, name: str) -> ParsedFile:
    """Parse one statement file into normalized transactions.

    Raises StatementParseError (a user-renderable message + error code) on
    anything the user can act on; the route maps those to 4xx responses."""
    if len(data) > MAX_FILE_BYTES:
        raise StatementParseError(
            f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
            f"Download a smaller export (CSV) from your issuer instead.",
            code="too_large",
        )

    fmt = detect_format(data, name)
    if fmt == "pdf":
        from .pdf import parse_pdf  # lazy: pdfplumber import is the slow part
        parsed = parse_pdf(data, name)
    elif fmt == "ofx":
        from .ofx import parse_ofx
        parsed = parse_ofx(_decode(data), name)
    elif fmt == "csv":
        from .csv_parse import parse_csv
        parsed = parse_csv(_decode(data), name)
    else:
        raise StatementParseError(
            f"{name} doesn't look like a statement file (PDF, CSV, or OFX/QFX).",
            code="unrecognized_format",
        )

    if len(parsed.txns) > MAX_TXNS_PER_FILE:
        raise StatementParseError(
            f"{name} has more than {MAX_TXNS_PER_FILE:,} transactions.",
            code="too_many_txns",
        )
    return parsed


def _decode(data: bytes) -> str:
    """UTF-8 with BOM stripped, tolerant of stray bytes (matches the
    browser TextDecoder the TS engine used)."""
    return data.decode("utf-8-sig", errors="replace")
