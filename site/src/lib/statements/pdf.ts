/** PDF statement parsing via pdf.js (plan 09, commit 3/5).
 *
 * Bank statement PDFs are digitally generated with a text layer; pdf.js
 * extracts positioned text items entirely in the browser (self-hosted worker,
 * no CDN, `isEvalSupported: false`, bytes only — never URLs). Scanned/
 * image-only PDFs yield zero text items and are rejected with a pointer to
 * the issuer's CSV export instead of guessing via OCR.
 *
 * Extraction is deliberately generic (no per-issuer layout profiles): text
 * items -> y-clustered lines -> date/description/amount transaction regexes,
 * plus the statement's own summary box (Purchases / Payments and Credits /
 * Fees / Interest) so the aggregator can reconcile parsed sums against the
 * issuer's printed totals and warn on mismatch.
 *
 * pdf.js is loaded lazily (dynamic import) so the main bundle never carries
 * it; vitest (node) gets the legacy build, browsers get the worker build.
 */

import { classifyKind, refineRefund } from './kind'
import { parseAmountToCents, parseDateToISO } from './csv'
import { ScannedPdfError, StatementParseError } from './types'
import type { NormalizedTxn, ParsedFile, StatementTotals } from './types'

export const MAX_PDF_PAGES = 200

// ── pdf.js loading ───────────────────────────────────────────────────────────

type Pdfjs = typeof import('pdfjs-dist')

let browserWorker: Worker | null = null

async function loadPdfjs(): Promise<Pdfjs> {
  if (typeof Worker === 'undefined') {
    // Node (vitest): the legacy build self-hosts a fake worker and needs no
    // DOM globals for text extraction.
    return (await import('pdfjs-dist/legacy/build/pdf.mjs')) as unknown as Pdfjs
  }
  const pdfjs = await import('pdfjs-dist')
  if (!pdfjs.GlobalWorkerOptions.workerPort) {
    const { default: PdfWorker } = await import('pdfjs-dist/build/pdf.worker.min.mjs?worker')
    browserWorker = new PdfWorker()
    pdfjs.GlobalWorkerOptions.workerPort = browserWorker
  }
  return pdfjs
}

/** Tear down the pdf.js worker after a batch — statement bytes should not
 * outlive the parse, and neither should the thread that saw them. */
export async function terminatePdfWorker(): Promise<void> {
  if (browserWorker === null) return
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerPort = null
  browserWorker.terminate()
  browserWorker = null
}

// ── Pure text-layer reconstruction (unit-tested without pdf.js) ─────────────

export interface TextItemLite { str: string; x: number; y: number }

const Y_TOLERANCE = 2

/** Positioned text items -> visual lines: cluster by y (PDF origin is
 * bottom-left, so top of page = descending y), order by x, join with spaces. */
export function reconstructLines(items: TextItemLite[]): string[] {
  const real = items.filter((i) => i.str.trim() !== '')
  const sorted = [...real].sort((a, b) => b.y - a.y || a.x - b.x)
  const lines: string[] = []
  let currentY = Infinity
  let current: TextItemLite[] = []
  const flush = () => {
    if (current.length === 0) return
    // Re-sort by x: the global y-descending sort scrambles x order inside a
    // near-y cluster (700.5 sorts before 700 regardless of column).
    current.sort((a, b) => a.x - b.x)
    lines.push(current.map((i) => i.str.trim()).join(' ').replace(/\s+/g, ' '))
    current = []
  }
  for (const item of sorted) {
    if (Math.abs(item.y - currentY) > Y_TOLERANCE) {
      flush()
      currentY = item.y
    }
    current.push(item)
  }
  flush()
  return lines
}

// ── Pure line -> transaction extraction ──────────────────────────────────────

export interface PdfExtract {
  txns: Omit<NormalizedTxn, 'source'>[]
  rejectedRows: number
  rangeStart: string
  rangeEnd: string
  statementTotals: StatementTotals
  /** Distinct statement-period lines seen — >1 means a combined multi-
   * statement PDF that one period can't date correctly. */
  periodCount: number
}

/** Month-name date support ("May 1, 2026", "February 23 - March 22, 2026" —
 * Bilt and BofA layouts; matched by 3-letter prefix, so Sep/Sept/September
 * all resolve). */
const MONTH_NUM: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
}
const MONTH = '(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?'

/** "May 1, 2026" -> 2026-05-01 (null on garbage). */
export function parseLongDate(month: string, day: string, year: string): string | null {
  const mo = MONTH_NUM[month.slice(0, 3).toLowerCase()]
  const d = Number(day)
  if (mo === undefined || d < 1 || d > 31) return null
  return `${year}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** "Opening/Closing Date 12/06/25 - 01/05/26" / "Statement Period 1/1/2026 to 1/31/2026" */
const PERIOD = /(\d{1,2}\/\d{1,2}\/\d{2,4})\s*(?:-|–|—|to|through)\s*(\d{1,2}\/\d{1,2}\/\d{2,4})/i
/** "February 23 - March 22, 2026" / "Apr 24 – May 23, 2026" (start year
 * optional: inherits the end year, rolling back one across Dec-Jan). */
const PERIOD_LONG = new RegExp(
  `${MONTH}\\s+(\\d{1,2})(?:,\\s*(\\d{4}))?\\s*(?:-|–|—|to|through)\\s*${MONTH}\\s+(\\d{1,2}),\\s*(\\d{4})`, 'i')

/** "12/18 WHOLEFDS #10236 SEATTLE WA $87.13", optional post date, optional
 * year on the transaction date, trailing CR/minus/parenthesized negatives. */
const TXN_LINE = /^(\d{1,2}\/\d{1,2})(\/\d{2,4})?\s+(?:\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\s+)?(.*?)\s+(-?\(?\$?\s?[\d,]+\.\d{2}\)?(?:-|\s*CR)?)$/
/** "May 1, 2026 BPS*BILT HOUSING 31 Bond St New York $2,675.00" (Bilt). */
const TXN_LINE_LONG = new RegExp(
  `^${MONTH}\\s+(\\d{1,2}),\\s*(\\d{4})\\s+(.*?)\\s+(-?\\(?\\$?\\s?[\\d,]+\\.\\d{2}\\)?(?:-|\\s*CR)?)$`, 'i')

const TOTALS_PATTERNS: [keyof StatementTotals, RegExp][] = [
  ['purchasesCents', /^[+\-]?\s*(?:total\s+)?(?:purchases\b|new\s+charges\b)/i],
  ['paymentsAndCreditsCents', /^[+\-]?\s*(?:total\s+)?payments?\b(?:\s*(?:and|&|\/)\s*(?:other\s+)?credits)?\b/i],
  ['feesCents', /^[+\-]?\s*(?:total\s+)?fees\s+charged\b/i],
  ['interestCents', /^[+\-]?\s*(?:total\s+)?interest\s+charged\b/i],
]

function mmddToISO(mmdd: string, periodEndISO: string): string | null {
  const m = /^(\d{1,2})\/(\d{1,2})$/.exec(mmdd)
  if (!m) return null
  const endYear = Number(periodEndISO.slice(0, 4))
  const iso = parseDateToISO(`${m[1]}/${m[2]}/${endYear}`)
  if (iso === null) return null
  // A December transaction on a statement closing in January belongs to the
  // previous year: anything after the period end rolls back one year.
  return iso > periodEndISO ? parseDateToISO(`${m[1]}/${m[2]}/${endYear - 1}`) : iso
}

export function extractFromLines(lines: string[], file: string): PdfExtract {
  // First period line dates the MM/DD transactions; every DISTINCT period
  // seen is counted, because >1 means a multi-statement combined PDF whose
  // transactions can't all be dated by one period (surfaced as a warning).
  let periodStart: string | null = null
  let periodEnd: string | null = null
  const periodsSeen = new Set<string>()
  for (const line of lines) {
    let start: string | null = null
    let end: string | null = null
    const m = PERIOD.exec(line)
    if (m) {
      start = parseDateToISO(m[1])
      end = parseDateToISO(m[2])
    } else {
      const ml = PERIOD_LONG.exec(line)
      if (ml) {
        const [, startMonth, startDay, startYear, endMonth, endDay, endYear] = ml
        end = parseLongDate(endMonth, endDay, endYear)
        start = parseLongDate(startMonth, startDay, startYear ?? endYear)
        // "Dec 24 – Jan 23, 2026" without a start year spans the year boundary.
        if (start && end && startYear === undefined && start > end) {
          start = parseLongDate(startMonth, startDay, String(Number(endYear) - 1))
        }
      }
    }
    if (start && end) {
      periodsSeen.add(`${start}..${end}`)
      if (periodStart === null) {
        periodStart = start
        periodEnd = end
      }
    }
  }

  const statementTotals: StatementTotals = {}
  const txns: Omit<NormalizedTxn, 'source'>[] = []
  let rejectedRows = 0

  for (const line of lines) {
    // Numeric (Chase/BofA "02/20 02/23 DESC ... 25.00") or long-form
    // (Bilt "May 1, 2026 DESC ... $2,675.00") transaction lines.
    let dateISO: string | null = null
    let desc: string | undefined
    let amountRaw: string | undefined
    const txnMatch = TXN_LINE.exec(line)
    const longMatch = txnMatch ? null : TXN_LINE_LONG.exec(line)
    if (txnMatch) {
      const [, mmdd, yearPart] = txnMatch
      desc = txnMatch[3]
      amountRaw = txnMatch[4]
      if (yearPart) dateISO = parseDateToISO(mmdd + yearPart)
      else if (periodEnd) dateISO = mmddToISO(mmdd, periodEnd)
    } else if (longMatch) {
      const [, month, day, year] = longMatch
      desc = longMatch[4]
      amountRaw = longMatch[5]
      dateISO = parseLongDate(month, day, year)
    }
    if (txnMatch || longMatch) {
      const descriptor = (desc ?? '').trim()
      const amountCents = parseAmountToCents(amountRaw ?? '')
      if (dateISO === null || amountCents === null || descriptor === ''
          || /^[\d\s$,.()-]*$/.test(descriptor)) {
        rejectedRows++
        continue
      }
      // PDF statements print charges positive and payments/credits negative.
      txns.push({
        dateISO, amountCents, descriptor,
        kind: refineRefund(classifyKind(descriptor), amountCents),
      })
      continue
    }

    // Summary box ("Purchases +$223.31") — never a txn line (those start with
    // a date). Year-to-date recap lines ("Total fees charged in 2025") are
    // skipped: only the cycle totals reconcile against this statement.
    if (/\bin\s+\d{4}\b/i.test(line)) continue
    for (const [key, pattern] of TOTALS_PATTERNS) {
      if (statementTotals[key] === undefined && pattern.test(line)) {
        const amount = /(-?\(?\$?[\d,]+\.\d{2}\)?-?)\s*$/.exec(line)
        const cents = amount ? parseAmountToCents(amount[1]) : null
        if (cents !== null) statementTotals[key] = Math.abs(cents)
        break
      }
    }
  }

  if (txns.length === 0) {
    throw new StatementParseError(
      `${file}: no transaction lines recognized` +
      (periodEnd === null ? ' (no statement period found to date them by)' : '') +
      ` — download the CSV export from your issuer instead.`)
  }

  const dates = txns.map((t) => t.dateISO).sort()
  return {
    txns,
    rejectedRows,
    rangeStart: periodStart ?? dates[0],
    rangeEnd: periodEnd ?? dates[dates.length - 1],
    statementTotals,
    periodCount: periodsSeen.size,
  }
}

// ── Entry point ──────────────────────────────────────────────────────────────

export async function parsePdf(bytes: Uint8Array, file: string): Promise<ParsedFile> {
  const pdfjs = await loadPdfjs()
  // pdf.js transfers the buffer to its worker (detaching it) — hand it a copy.
  const task = pdfjs.getDocument({
    data: bytes.slice(),
    isEvalSupported: false,
    disableFontFace: true,
  })
  try {
    let doc
    try {
      doc = await task.promise
    } catch {
      // Corrupt/encrypted/unreadable PDF — keep it a per-file, user-renderable error.
      throw new StatementParseError(
        `${file}: couldn't read this PDF — download the CSV export from your issuer instead.`)
    }
    if (doc.numPages > MAX_PDF_PAGES) {
      throw new StatementParseError(`${file}: more than ${MAX_PDF_PAGES} pages.`)
    }
    const lines: string[] = []
    let itemCount = 0
    for (let p = 1; p <= doc.numPages; p++) {
      const content = await (await doc.getPage(p)).getTextContent()
      const items = content.items
        .filter((i) => 'str' in i)
        .map((i) => ({ str: i.str, x: i.transform[4], y: i.transform[5] }))
      itemCount += items.filter((i) => i.str.trim() !== '').length
      lines.push(...reconstructLines(items))
    }
    if (itemCount === 0) throw new ScannedPdfError(file)

    const extract = extractFromLines(lines, file)
    return {
      summary: {
        name: file,
        format: 'pdf',
        txns: extract.txns.length,
        rejectedRows: extract.rejectedRows,
        rangeStart: extract.rangeStart,
        rangeEnd: extract.rangeEnd,
        statementTotals: extract.statementTotals,
        periodCount: extract.periodCount,
      },
      txns: extract.txns.map((t, i) => ({ ...t, source: { file, line: i + 1 } })),
    }
  } finally {
    await task.destroy()
  }
}
