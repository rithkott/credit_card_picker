/** Statement-import core types (plan 09; server-side parsing since plan 12).
 *
 * Since v1.2.0 the parsing engine lives in server/statements/ — each file is
 * uploaded to POST /api/statements/parse, parsed and categorized IN MEMORY on
 * the server, and only the normalized transactions come back; the server
 * stores nothing. The browser keeps everything after that: review,
 * aggregation, annualization, and the Apply payload all stay in this tab and
 * die with it.
 *
 * The camelCase shapes here are the browser-side working types; the wire
 * shapes (snake_case, defined by server/statements/types.py) are converted in
 * index.ts as they arrive.
 */

export type TxnKind = 'purchase' | 'refund' | 'payment' | 'fee' | 'interest' | 'transfer'

/** Server-computed categorization, attached to every transaction.
 * layer: 1 descriptor · 2 keyword · 3 issuer category · 4 MCC · 5 fuzzy ·
 * 6 semantic (local embedding model). methods 'fuzzy' and 'semantic' are
 * approximate matches the review UI should disclose; `confidence` is their
 * 0-1 score. `stem` is the noise-stripped
 * grouping key for uncategorized rows (computed server-side so the browser
 * doesn't reimplement the stemmer). */
export interface TxnMatch {
  category: string | null
  layer: 1 | 2 | 3 | 4 | 5 | 6 | null
  method: 'exact' | 'fuzzy' | 'semantic' | null
  confidence?: number
  merchantKey?: string
  usageKey?: string
  descriptorKey?: string
  descriptorLabel?: string
  stem: string
}

export interface NormalizedTxn {
  /** YYYY-MM-DD */
  dateISO: string
  /** Positive = money spent, negative = money back (refund). Payments, fees,
   * interest, and transfers keep their sign but are excluded by kind. */
  amountCents: number
  /** Raw statement description, trimmed (rendered only as text nodes). */
  descriptor: string
  kind: TxnKind
  match: TxnMatch
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
  /** PDFs: distinct statement-period lines found. >1 = several statements
   * combined into one PDF, which a single period can't date correctly. */
  periodCount?: number
  /** PDFs: which server path produced the transactions — 'regex' (the
   * corpus-verified line patterns) or 'layout' (geometry fallback). */
  extraction?: 'regex' | 'layout'
  /** CSVs: set when the server inferred the columns from content shape
   * because the header names weren't recognized (or there was no header). */
  columnInference?: { used: boolean; confidence: number }
}

export interface ParsedFile {
  summary: FileSummary
  txns: NormalizedTxn[]
}

export interface FileError {
  name: string
  message: string
  /** Server error taxonomy (scanned_pdf, unrecognized_format, ...) when the
   * failure came from the API; absent for client-side failures. */
  code?: string
}

export interface ImportWarning {
  /** W-coverage | W-overlap | W-rows | W-reconcile | W-multi-statement |
   * I-fuzzy | I-semantic | I-inferred-columns | I-layout (I-* are
   * informational). */
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

/** User-renderable parse failure (client-side pre-checks: oversize file,
 * unreadable file). Server-side failures arrive as ApiError instead. */
export class StatementParseError extends Error {}

// ── Wire shapes (server/statements/types.py, snake_case) ────────────────────

export interface WireMatch {
  category: string | null
  layer: 1 | 2 | 3 | 4 | 5 | 6 | null
  method: 'exact' | 'fuzzy' | 'semantic' | null
  confidence?: number
  merchant_key?: string
  usage_key?: string
  descriptor_key?: string
  descriptor_label?: string
  stem: string
}

export interface WireTxn {
  date: string
  amount_cents: number
  descriptor: string
  kind: TxnKind
  line: number
  issuer_category?: string
  mcc?: number
  match: WireMatch
}

export interface WireSummary {
  name: string
  format: 'csv' | 'ofx' | 'pdf'
  txns: number
  rejected_rows: number
  range_start: string
  range_end: string
  statement_totals?: {
    purchases_cents?: number
    payments_and_credits_cents?: number
    fees_cents?: number
    interest_cents?: number
  }
  period_count?: number
  extraction?: 'regex' | 'layout'
  column_inference?: { used: boolean; confidence: number }
}

export interface WireParsedFile {
  summary: WireSummary
  txns: WireTxn[]
}
