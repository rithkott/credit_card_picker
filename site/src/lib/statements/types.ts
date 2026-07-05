/** Statement-import core types (plan 09).
 *
 * Everything here lives and dies in browser memory: statement bytes and
 * transactions never leave the page (not even to the localhost API). The
 * parsers normalize every format into NormalizedTxn; categorize/aggregate
 * reduce those to an ImportResult the review screen edits and applies.
 */

export type TxnKind = 'purchase' | 'refund' | 'payment' | 'fee' | 'interest' | 'transfer'

export interface NormalizedTxn {
  /** YYYY-MM-DD */
  dateISO: string
  /** Positive = money spent, negative = money back (refund). Payments, fees,
   * interest, and transfers keep their sign but are excluded by kind. */
  amountCents: number
  /** Raw statement description, trimmed (rendered only as text nodes). */
  descriptor: string
  /** Issuer's own category column (CSV), lowercased + trimmed. */
  issuerCategory?: string
  /** Merchant category code (CSV MCC column or OFX <SIC>). */
  mcc?: number
  kind: TxnKind
  source: { file: string; line: number }
}

/** Statement-declared totals (PDF summary box), for reconciliation warnings.
 * All values are positive cents. */
export interface StatementTotals {
  purchasesCents?: number
  paymentsAndCreditsCents?: number
  feesCents?: number
  interestCents?: number
}

export interface FileSummary {
  name: string
  format: 'csv' | 'ofx' | 'pdf'
  txns: number
  /** Rows/lines that looked transactional but failed to parse. */
  rejectedRows: number
  /** Covered date range: OFX DTSTART/DTEND when present, else min..max
   * transaction date. Empty strings when the file had no dated rows. */
  rangeStart: string
  rangeEnd: string
  statementTotals?: StatementTotals
}

export interface ParsedFile {
  summary: FileSummary
  txns: NormalizedTxn[]
}

export interface FileError {
  name: string
  message: string
}

export interface ImportWarning {
  /** W-coverage | W-overlap | W-rows | W-reconcile | W-duplicate-file */
  code: string
  message: string
}

/** Uncategorized transactions grouped by descriptor stem for the review UI.
 * `label` is set (from statement-descriptors.yaml) when the group is an
 * explicitly-unmapped descriptor key (e.g. Bilt rent) needing a user call. */
export interface UncatGroup {
  stem: string
  label?: string
  count: number
  rawCents: number
}

/** "We detected $412/yr at Delta" — usage-questions items seen in the data. */
export interface UsageSuggestion {
  key: string
  label: string
  annualCents: number
}

export interface ImportResult {
  /** Annualized integer cents per real category key. */
  categoryCents: Record<string, number>
  /** Annualized integer cents per merchants.yaml key (⊆ parent category by
   * construction, so validation E3 can never fire from imported values). */
  merchantCents: Record<string, number>
  uncategorized: UncatGroup[]
  usageSuggestions: UsageSuggestion[]
  coverageDays: number
  files: FileSummary[]
  warnings: ImportWarning[]
  /** Money excluded from categorization, by kind (payments, fees, ...). */
  excludedCents: Partial<Record<TxnKind, number>>
}

/** User-renderable parse failure ("couldn't map the CSV headers"). */
export class StatementParseError extends Error {}

/** PDF with no extractable text layer (scanned/image-only). */
export class ScannedPdfError extends StatementParseError {
  constructor(file: string) {
    super(
      `${file} has no extractable text (it looks scanned). ` +
      `Download the CSV export from your issuer instead.`,
    )
  }
}
