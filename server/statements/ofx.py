"""OFX / QFX statement parsing (port of site ofx.ts).

One tolerant scanner for both variants: OFX 1.x is SGML (leaf tags have no
closing tag), OFX 2.x is XML. Both write each value as <TAG>value, so a
per-tag scan up to the next '<' or newline reads either. Sign convention:
OFX credit-card charges are NEGATIVE TRNAMT, so amounts are flipped to the
importer's spend-positive convention.
"""

import math
import re
from typing import Optional

from .kind import classify_kind, refine_refund
from .types import ParsedFile, StatementParseError, Summary, Txn

ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def parse_ofx_date(text: str) -> Optional[str]:
    """<DTPOSTED>20260214093000[-5:EST] -> 2026-02-14 (None on garbage)."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})", text.strip())
    if not m:
        return None
    mo, d = int(m.group(2)), int(m.group(3))
    if mo < 1 or mo > 12 or d < 1 or d > 31:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _tag(block: str, name: str) -> Optional[str]:
    m = re.search(rf"<{name}>([^<\r\n]*)", block, re.IGNORECASE)
    if not m:
        return None
    value = re.sub(r"&(amp|lt|gt|quot|apos);", lambda e: ENTITIES[e.group(1)], m.group(1).strip())
    return value if value else None


def parse_ofx(text: str, file: str) -> ParsedFile:
    blocks = re.findall(r"<STMTTRN>[\s\S]*?(?=<STMTTRN>|</STMTTRN>|</BANKTRANLIST>|$)",
                        text, re.IGNORECASE)
    if not blocks:
        raise StatementParseError(f"{file}: no <STMTTRN> transactions found.",
                                  code="unrecognized_format")

    txns = []
    seen_fitids = set()
    rejected_rows = 0
    for block in blocks:
        fitid = _tag(block, "FITID")
        if fitid is not None:
            if fitid in seen_fitids:  # issuer-declared duplicate
                continue
            seen_fitids.add(fitid)
        date_iso = parse_ofx_date(_tag(block, "DTPOSTED") or "")
        try:
            amount_raw = float(_tag(block, "TRNAMT") or "")
        except ValueError:
            amount_raw = None
        name = _tag(block, "NAME") or ""
        memo = _tag(block, "MEMO") or ""
        descriptor = " ".join(p for p in (name, memo) if p).strip()
        if date_iso is None or amount_raw is None or descriptor == "":
            rejected_rows += 1
            continue
        # Flip: OFX charges are negative; the importer wants spend positive.
        # floor(x+0.5) mirrors JS Math.round half-up on the pre-flip value.
        amount_cents = -math.floor(amount_raw * 100 + 0.5)
        kind = refine_refund(
            classify_kind(descriptor, ofx_type=_tag(block, "TRNTYPE")), amount_cents)
        sic_text = (_tag(block, "SIC") or "").strip()
        sic = int(sic_text) if sic_text.isdigit() and int(sic_text) > 0 else None
        txns.append(Txn(
            date=date_iso,
            amount_cents=amount_cents,
            descriptor=descriptor,
            kind=kind,
            mcc=sic,
            # OFX has no meaningful line numbers; index the block instead.
            line=len(txns) + rejected_rows + 1,
        ))
    if not txns:
        raise StatementParseError(
            f"{file}: no parseable transactions ({rejected_rows} block(s) rejected).",
        )

    # Issuer-declared statement range when present, else observed txn range.
    dates = sorted(t.date for t in txns)
    range_start = parse_ofx_date(_tag(text, "DTSTART") or "") or dates[0]
    range_end = parse_ofx_date(_tag(text, "DTEND") or "") or dates[-1]
    return ParsedFile(
        summary=Summary(
            name=file,
            format="ofx",
            txns=len(txns),
            rejected_rows=rejected_rows,
            range_start=range_start,
            range_end=range_end,
        ),
        txns=txns,
    )
