/** Statement-import core types (plan 09; server-side parsing since plan 12;
 * detection-only since plan 14).
 *
 * Each file is uploaded to POST /api/statements/parse, parsed IN MEMORY on
 * the server, and only the summary plus the transactions that evidence a
 * usage-questions item (matched via statement-descriptors.yaml) come back —
 * the full transaction list never leaves the server, and the server stores
 * nothing. The browser annualizes the detected amounts and renders them as
 * pre-checked confirmed-usage suggestions; spending is entered manually.
 *
 * The camelCase shapes here are the browser-side working types; the wire
 * shapes (snake_case, defined by server/statements/) are converted in
 * index.ts as they arrive.
 */

export type TxnKind = 'purchase' | 'refund' | 'payment' | 'fee' | 'interest' | 'transfer'

/** One detected benefit-usage transaction. Only purchases and refunds are
 * returned (refunds subtract in the annualized total). */
export interface DetectedTxn {
  /** YYYY-MM-DD */
  dateISO: string
  /** Positive = money spent, negative = money back (refund). */
  amountCents: number
  /** Raw statement description, trimmed (rendered only as text nodes). */
  descriptor: string
  kind: 'purchase' | 'refund'
  usageKey: string
  usageLabel: string
  source: { file: string; line: number }
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
  matches: DetectedTxn[]
}

export interface FileError {
  name: string
  message: string
  /** Server error taxonomy (scanned_pdf, unrecognized_format, ...) when the
   * failure came from the API; absent for client-side failures. */
  code?: string
}

export interface ImportWarning {
  /** W-coverage | W-overlap | W-rows | W-multi-statement |
   * I-inferred-columns | I-layout (I-* are informational). */
  code: string
  message: string
}

/** "We detected $412/yr at Delta" — usage-questions items seen in the data. */
export interface UsageSuggestion {
  key: string
  label: string
  annualCents: number
}

export interface DetectionResult {
  usageSuggestions: UsageSuggestion[]
  coverageDays: number
  files: FileSummary[]
  warnings: ImportWarning[]
}

/** User-renderable parse failure (client-side pre-checks: oversize file,
 * unreadable file). Server-side failures arrive as ApiError instead. */
export class StatementParseError extends Error {}

// ── Wire shapes (server/statements/ + detect_usage.py, snake_case) ──────────

export interface WireUsageMatch {
  date: string
  amount_cents: number
  descriptor: string
  kind: 'purchase' | 'refund'
  line: number
  usage_key: string
  usage_label: string
}

export interface WireSummary {
  name: string
  format: 'csv' | 'ofx' | 'pdf'
  txns: number
  rejected_rows: number
  range_start: string
  range_end: string
  statement_totals?: Record<string, number>
  period_count?: number
  extraction?: 'regex' | 'layout'
  column_inference?: { used: boolean; confidence: number }
}

export interface WireParsedFile {
  summary: WireSummary
  matches: WireUsageMatch[]
}
