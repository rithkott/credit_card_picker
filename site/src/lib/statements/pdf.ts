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
}

/** "Opening/Closing Date 12/06/25 - 01/05/26" / "Statement Period 1/1/2026 to 1/31/2026" */
const PERIOD = /(\d{1,2}\/\d{1,2}\/\d{2,4})\s*(?:-|–|to|through)\s*(\d{1,2}\/\d{1,2}\/\d{2,4})/i

/** "12/18 WHOLEFDS #10236 SEATTLE WA $87.13", optional post date, optional
 * year on the transaction date, trailing CR/minus/parenthesized negatives. */
const TXN_LINE = /^(\d{1,2}\/\d{1,2})(\/\d{2,4})?\s+(?:\d{1,2}\/\d{1,2}(?:\/\d{2,4})?\s+)?(.*?)\s+(-?\(?\$?[\d,]+\.\d{2}\)?(?:-|\s*CR)?)$/

const TOTALS_PATTERNS: [keyof StatementTotals, RegExp][] = [
  ['purchasesCents', /^[+\-]?\s*(?:total\s+)?purchases\b/i],
  ['paymentsAndCreditsCents', /^[+\-]?\s*payments?\b(?:\s*(?:and|&|\/)\s*(?:other\s+)?credits)?\b/i],
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
  let periodStart: string | null = null
  let periodEnd: string | null = null
  for (const line of lines) {
    const m = PERIOD.exec(line)
    if (m) {
      periodStart = parseDateToISO(m[1])
      periodEnd = parseDateToISO(m[2])
      if (periodStart && periodEnd) break
    }
  }

  const statementTotals: StatementTotals = {}
  const txns: Omit<NormalizedTxn, 'source'>[] = []
  let rejectedRows = 0

  for (const line of lines) {
    const txnMatch = TXN_LINE.exec(line)
    if (txnMatch) {
      const [, mmdd, yearPart, desc, amountRaw] = txnMatch
      const descriptor = desc.trim()
      const amountCents = parseAmountToCents(amountRaw)
      let dateISO: string | null = null
      if (yearPart) dateISO = parseDateToISO(mmdd + yearPart)
      else if (periodEnd) dateISO = mmddToISO(mmdd, periodEnd)
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
      },
      txns: extract.txns.map((t, i) => ({ ...t, source: { file, line: i + 1 } })),
    }
  } finally {
    await task.destroy()
  }
}
