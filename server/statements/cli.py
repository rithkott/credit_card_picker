#!/usr/bin/env python3
"""Local corpus harness (plan 12; detection-only since plan 14).

Runs the parse + benefit-usage-detection pipeline over a directory of REAL
statement files (e.g. ~/Desktop/Personal — never committed) and prints one
line per file plus reconciliation checks (still a parser health check even
though the product dropped the reconcile warning) and per-key usage totals.
Local verification only; nothing here is imported by the server.

Usage: python3 server/statements/cli.py <dir> [--verbose]
"""

import os
import sys

# Running this file directly puts server/statements/ first on sys.path, where
# our types.py shadows the STDLIB types module and breaks every import after
# it. Point path[0] at server/ instead, before anything else is imported.
sys.path[0] = os.path.dirname(sys.path[0])

from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import yaml  # noqa: E402

import optimize as opt  # noqa: E402
from statements import parse_statement  # noqa: E402
from statements.detect_usage import Matcher, detect_usage  # noqa: E402
from statements.types import StatementParseError  # noqa: E402

EXTS = {".csv", ".ofx", ".qfx", ".pdf", ".txt"}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).expanduser()
    verbose = "--verbose" in sys.argv

    ds = opt.load_dataset()
    meta = Path(opt.META_DIR)
    with open(meta / "statement-descriptors.yaml") as f:
        descriptors = yaml.safe_load(f)["descriptors"]
    matcher = Matcher(descriptors, ds["usage_questions"])

    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in EXTS)
    ok = errors = reconciled = mismatched = 0
    usage_totals: dict = {}
    for path in files:
        try:
            parsed = parse_statement(path.read_bytes(), path.name)
        except StatementParseError as e:
            errors += 1
            print(f"ERROR  {path.name}: [{e.code}] {e}")
            continue
        matches = detect_usage(matcher, parsed.txns)
        ok += 1
        s = parsed.summary
        for hit in matches:
            usage_totals[hit["usage_key"]] = (
                usage_totals.get(hit["usage_key"], 0) + hit["amount_cents"])

        recon = ""
        if s.statement_totals:
            purchases = sum(t.amount_cents for t in parsed.txns if t.kind == "purchase")
            transfers = sum(abs(t.amount_cents) for t in parsed.txns if t.kind == "transfer")
            stated = s.statement_totals.get("purchases_cents")
            if stated is not None:
                if stated in (purchases, purchases + transfers):
                    recon = " reconciles"
                    reconciled += 1
                else:
                    recon = f" MISMATCH stated={stated} parsed={purchases}"
                    mismatched += 1
        extra = f" [{s.extraction}]" if s.extraction else ""
        extra += " [inferred-columns]" if s.column_inference else ""
        print(f"OK     {path.name}: {s.format} {s.txns} txns, rejected {s.rejected_rows}, "
              f"{s.range_start}..{s.range_end}{extra}{recon}, "
              f"{len(matches)} usage hits")
        if verbose:
            for hit in matches:
                print(f"         {hit['date']} {hit['amount_cents']:>9} {hit['kind']:9} "
                      f"{hit['usage_key']}: {hit['descriptor'][:60]}")

    print(f"\n{ok} parsed, {errors} errors; totals: {reconciled} reconcile, "
          f"{mismatched} mismatch; usage cents by key: "
          f"{dict(sorted(usage_totals.items()))}")
    return 0 if errors == 0 and mismatched == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
