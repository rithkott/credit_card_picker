"""Statement file-format sniffing (port of site detect.ts).

Content-based, extension as tiebreak only: banks are sloppy with download
names (.qfx files that are XML, .csv attachments served as .txt).
"""

import re


def detect_format(data: bytes, name: str) -> str:
    """Return 'pdf' | 'ofx' | 'csv' | 'unknown'."""
    head = data[:2048].decode("utf-8", errors="replace")
    # TextDecoder consumes a leading UTF-8 BOM by default; mirror that.
    if head.startswith("\ufeff"):
        head = head[1:]

    if head.startswith("%PDF-"):
        return "pdf"

    upper = head.upper()
    if "OFXHEADER" in upper or "<OFX>" in upper:
        return "ofx"

    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("ofx", "qfx"):
        return "ofx"

    # CSV: a plausible delimited header line (no NUL bytes, has a comma or
    # tab in the first non-empty line).
    if "\0" not in head:
        first_line = next((l for l in re.split(r"\r?\n", head) if l.strip() != ""), None)
        if first_line and ("," in first_line or "\t" in first_line):
            return "csv"
        if ext == "csv":
            return "csv"
    return "unknown"
