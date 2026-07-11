"""Semantic CSV column inference (plan 12 — new, no TS ancestor).

Runs only when header-name mapping fails: unknown header vocabulary, or no
header row at all. Instead of giving up, score every column by the SHAPE of
its content over a sample of rows:

  date column        — fraction of cells parse_date_to_iso accepts
  amount column      — fraction of cells parse_amount_to_cents accepts
                       (dates fail the amount regex, so the sets are disjoint)
  descriptor column  — letters-heavy cells, many distinct values

A debit/credit pair is recognized as two amount-shaped columns that are never
both nonzero on the same row (the column with more nonzero cells is the
debit side — purchases outnumber credits on card statements).

Deterministic, zero dependencies, and honest: the mapping is accepted only
when every chosen column clears ACCEPT_THRESHOLD, and the caller reports
{"used": true, "confidence": ...} so the review UI can disclose the guess.
"""

from typing import Callable, Optional, Tuple

SAMPLE_ROWS = 200
ACCEPT_THRESHOLD = 0.8
# Descriptor gate: cells must be at least half letters on average, and the
# column must not be a constant (uniqueness floor keeps "USD"-style columns out).
DESC_MIN_ALPHA = 0.5
DESC_MIN_UNIQUE = 0.05


def infer_columns(rows: list, parse_date: Callable, parse_amount: Callable):
    """rows = [{"fields": [...], "line": n}] including a possible header row.

    Returns (ColumnMap, headerless, confidence) or None when no confident
    mapping exists. Imported lazily by csv_parse to avoid a circular import
    of ColumnMap — the dataclass is fetched inside the function."""
    from .csv_parse import ColumnMap

    if not rows:
        return None
    width = max(len(r["fields"]) for r in rows)
    if width < 2:
        return None

    # Headerless when the first row already looks like data (its cells parse
    # as a date somewhere). Otherwise treat row 0 as an unknown header.
    first = rows[0]["fields"]
    headerless = any(parse_date(c) is not None for c in first)
    data = rows if headerless else rows[1:]
    data = data[:SAMPLE_ROWS]
    if not data:
        return None

    def column(i):
        return [(r["fields"][i] if i < len(r["fields"]) else "") for r in data]

    date_frac = []
    amount_frac = []  # over NON-EMPTY cells: debit/credit pairs are half-empty by design
    fill_frac = []
    nonzero = []
    alpha_frac = []
    unique_frac = []
    for i in range(width):
        cells = column(i)
        non_empty = [c for c in cells if c.strip() != ""]
        total = len(cells)
        date_frac.append(sum(1 for c in cells if parse_date(c) is not None) / total)
        amounts = [parse_amount(c) for c in non_empty]
        amount_frac.append(sum(1 for a in amounts if a is not None) / len(non_empty)
                           if non_empty else 0.0)
        fill_frac.append(len(non_empty) / total)
        nonzero.append(sum(1 for a in amounts if a is not None and a != 0))
        letters = [sum(ch.isalpha() for ch in c) / len(c) for c in non_empty if len(c) > 0]
        alpha_frac.append(sum(letters) / len(letters) if letters else 0.0)
        unique_frac.append(len(set(non_empty)) / total if non_empty else 0.0)

    # Date: best date-shaped column.
    date_i = max(range(width), key=lambda i: date_frac[i])
    if date_frac[date_i] < ACCEPT_THRESHOLD:
        return None

    # Amount candidates: amount-shaped, not the date column, not letters-heavy
    # (an all-digits ID column parses as an amount but so be it — the
    # debit/credit pairing and value spread below can't distinguish it, and a
    # wrong pick still reconciles as garbage the user sees in review).
    candidates = [i for i in range(width)
                  if i != date_i and amount_frac[i] >= ACCEPT_THRESHOLD
                  and alpha_frac[i] < 0.1 and nonzero[i] > 0]
    if not candidates:
        return None

    amount_i = debit_i = credit_i = None
    pair = _debit_credit_pair(candidates, data, parse_amount)
    if pair is not None:
        debit_i, credit_i = pair
    else:
        # Single amount column: prefer well-filled columns (a lone stray
        # number shouldn't win), then the most nonzero cells (statement
        # amounts are rarely zero), leftmost wins ties deterministically.
        full = [i for i in candidates if fill_frac[i] >= ACCEPT_THRESHOLD]
        if not full:
            return None
        amount_i = max(full, key=lambda i: (nonzero[i], -i))

    # Descriptor: letters-heavy, distinct, not already claimed.
    claimed = {date_i, amount_i, debit_i, credit_i}
    desc_candidates = [i for i in range(width)
                       if i not in claimed
                       and alpha_frac[i] >= DESC_MIN_ALPHA
                       and unique_frac[i] >= DESC_MIN_UNIQUE]
    if not desc_candidates:
        return None
    desc_i = max(desc_candidates, key=lambda i: (alpha_frac[i] * unique_frac[i], -i))

    chosen_fracs = [date_frac[date_i]]
    if amount_i is not None:
        chosen_fracs.append(amount_frac[amount_i])
    else:
        chosen_fracs.extend([amount_frac[debit_i], amount_frac[credit_i]])
    confidence = min(chosen_fracs)

    return (
        ColumnMap(date=date_i, description=desc_i,
                  amount=amount_i, debit=debit_i, credit=credit_i),
        headerless,
        confidence,
    )


def _debit_credit_pair(candidates: list, data: list,
                       parse_amount: Callable) -> Optional[Tuple[int, int]]:
    """Two amount columns that are never both nonzero on one row form a
    debit/credit pair; the busier column is the debit (spend) side. Requires
    both sides to actually carry values — two sparse columns are noise."""
    best = None
    for a in range(len(candidates)):
        for b in range(a + 1, len(candidates)):
            ia, ib = candidates[a], candidates[b]
            counts = [0, 0]
            clash = False
            for r in data:
                fields = r["fields"]
                va = parse_amount(fields[ia]) if ia < len(fields) else None
                vb = parse_amount(fields[ib]) if ib < len(fields) else None
                za = va is not None and va != 0
                zb = vb is not None and vb != 0
                if za and zb:
                    clash = True
                    break
                counts[0] += za
                counts[1] += zb
            if clash or counts[0] == 0 or counts[1] == 0:
                continue
            filled = counts[0] + counts[1]
            if best is None or filled > best[0]:
                debit, credit = (ia, ib) if counts[0] >= counts[1] else (ib, ia)
                best = (filled, debit, credit)
    return (best[1], best[2]) if best else None
