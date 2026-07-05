/** CSV statement parsing (plan 09).
 *
 * Hand-rolled RFC-4180 reader (quotes, escaped quotes, CRLF, embedded
 * newlines) + issuer header profiles for the major US issuers + a generic
 * header-synonym fallback. Sign conventions are normalized so SPEND IS
 * POSITIVE; issuers disagree (Chase/BofA export purchases negative, Amex and
 * Discover positive), so each profile declares its convention and the generic
 * fallback infers it from the majority sign of purchase rows.
 */

import { classifyKind, refineRefund } from './kind'
import { StatementParseError } from './types'
import type { NormalizedTxn, ParsedFile } from './types'

// ── RFC-4180 reader ──────────────────────────────────────────────────────────

/** Parse CSV text into rows of fields. Also returns each row's 1-based line
 * number in the original file (quoted fields may span lines). */
export function parseCsvRows(text: string): { fields: string[]; line: number }[] {
  const rows: { fields: string[]; line: number }[] = []
  let fields: string[] = []
  let field = ''
  let inQuotes = false
  let line = 1
  let rowLine = 1
  let sawAny = false

  const pushField = () => { fields.push(field); field = ''; sawAny = true }
  const pushRow = () => {
    pushField()
    if (fields.length > 1 || fields[0].trim() !== '') rows.push({ fields, line: rowLine })
    fields = []
    sawAny = false
    rowLine = line
  }

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } else inQuotes = false
      } else {
        if (ch === '\n') line++
        field += ch
      }
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      pushField()
    } else if (ch === '\n') {
      line++
      pushRow()
    } else if (ch !== '\r') {
      field += ch
    }
  }
  if (sawAny || field !== '') pushRow()
  return rows
}

// ── Header mapping ───────────────────────────────────────────────────────────

interface ColumnMap {
  date: number
  description: number
  amount?: number
  debit?: number
  credit?: number
  category?: number
  type?: number
  mcc?: number
}

interface IssuerProfile {
  issuer: string
  /** Lowercased header names that identify this profile (all must be present). */
  requires: string[]
  /** true when the export writes purchases as negative amounts. */
  negativePurchases: boolean
}

/** Header fingerprints for the big issuers' transaction exports. Drafted from
 * their documented CSV layouts, confidence: low until checked against real
 * exports (same caveat as data/meta/category-rules.yaml). */
const ISSUER_PROFILES: IssuerProfile[] = [
  { issuer: 'chase', requires: ['transaction date', 'post date', 'description', 'type', 'amount'], negativePurchases: true },
  { issuer: 'amex', requires: ['date', 'description', 'amount'], negativePurchases: false },
  { issuer: 'citi', requires: ['status', 'date', 'description', 'debit', 'credit'], negativePurchases: false },
  { issuer: 'capital-one', requires: ['transaction date', 'posted date', 'description', 'debit', 'credit'], negativePurchases: false },
  { issuer: 'bofa', requires: ['posted date', 'payee', 'amount'], negativePurchases: true },
  { issuer: 'discover', requires: ['trans. date', 'post date', 'description', 'amount'], negativePurchases: false },
]

const DATE_SYNONYMS = ['transaction date', 'trans. date', 'trans date', 'date', 'posted date', 'post date']
const DESC_SYNONYMS = ['description', 'payee', 'merchant', 'name', 'details', 'memo']
const AMOUNT_SYNONYMS = ['amount', 'transaction amount']
const DEBIT_SYNONYMS = ['debit', 'withdrawals', 'charge']
const CREDIT_SYNONYMS = ['credit', 'deposits']
const CATEGORY_SYNONYMS = ['category']
const TYPE_SYNONYMS = ['type', 'transaction type']
const MCC_SYNONYMS = ['mcc', 'merchant category code', 'sic']

function findColumn(headers: string[], synonyms: string[]): number | undefined {
  for (const syn of synonyms) {
    const i = headers.indexOf(syn)
    if (i !== -1) return i
  }
  return undefined
}

function mapHeaders(headers: string[]): { map: ColumnMap; profile?: IssuerProfile } {
  const lower = headers.map((h) => h.trim().toLowerCase())
  const profile = ISSUER_PROFILES.find((p) => p.requires.every((r) => lower.includes(r)))

  const date = findColumn(lower, DATE_SYNONYMS)
  const description = findColumn(lower, DESC_SYNONYMS)
  const amount = findColumn(lower, AMOUNT_SYNONYMS)
  const debit = findColumn(lower, DEBIT_SYNONYMS)
  const credit = findColumn(lower, CREDIT_SYNONYMS)
  if (date === undefined || description === undefined
      || (amount === undefined && debit === undefined && credit === undefined)) {
    throw new StatementParseError(
      `Couldn't recognize the CSV columns (got: ${headers.join(', ') || 'none'}). ` +
      `The file needs a date, a description, and an amount (or debit/credit) column.`,
    )
  }
  return {
    map: {
      date, description, amount, debit, credit,
      category: findColumn(lower, CATEGORY_SYNONYMS),
      type: findColumn(lower, TYPE_SYNONYMS),
      mcc: findColumn(lower, MCC_SYNONYMS),
    },
    profile,
  }
}

// ── Field parsing ────────────────────────────────────────────────────────────

/** MM/DD/YYYY, MM/DD/YY, or YYYY-MM-DD -> ISO YYYY-MM-DD (null on garbage). */
export function parseDateToISO(text: string): string | null {
  const t = text.trim()
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t)
  if (m) return checkYmd(Number(m[1]), Number(m[2]), Number(m[3]))
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{2}(?:\d{2})?)$/.exec(t)
  if (m) {
    let year = Number(m[3])
    if (year < 100) year += year >= 70 ? 1900 : 2000
    return checkYmd(year, Number(m[1]), Number(m[2]))
  }
  return null
}

function checkYmd(y: number, mo: number, d: number): string | null {
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** "$1,234.56", "(12.34)", "12.34-", "-12.34" -> signed cents (null on garbage). */
export function parseAmountToCents(text: string): number | null {
  let t = text.trim()
  if (t === '') return null
  let sign = 1
  if (t.startsWith('(') && t.endsWith(')')) { sign = -1; t = t.slice(1, -1) }
  if (t.endsWith('-')) { sign = -sign; t = t.slice(0, -1) }
  if (t.endsWith('CR')) { sign = -sign; t = t.slice(0, -2).trim() }
  if (t.startsWith('-')) { sign = -sign; t = t.slice(1) }
  else if (t.startsWith('+')) t = t.slice(1)
  t = t.replace(/[$,\s]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null
  return sign * Math.round(Number(t) * 100)
}

// ── Parser ───────────────────────────────────────────────────────────────────

export function parseCsv(text: string, file: string): ParsedFile {
  const rows = parseCsvRows(text)
  if (rows.length === 0) throw new StatementParseError(`${file} is empty.`)
  const { map, profile } = mapHeaders(rows[0].fields)

  const txns: NormalizedTxn[] = []
  let rejectedRows = 0
  for (const row of rows.slice(1)) {
    const f = row.fields
    const dateISO = parseDateToISO(f[map.date] ?? '')
    const descriptor = (f[map.description] ?? '').trim()
    let cents: number | null = null
    if (map.amount !== undefined) {
      cents = parseAmountToCents(f[map.amount] ?? '')
    } else {
      // Debit/credit pair: debit = money spent, credit = money back.
      const debit = map.debit !== undefined ? parseAmountToCents(f[map.debit] ?? '') : null
      const credit = map.credit !== undefined ? parseAmountToCents(f[map.credit] ?? '') : null
      if (debit !== null && debit !== 0) cents = Math.abs(debit)
      else if (credit !== null && credit !== 0) cents = -Math.abs(credit)
      else if (debit !== null || credit !== null) cents = 0
    }
    if (dateISO === null || cents === null || descriptor === '') {
      rejectedRows++
      continue
    }
    const kind = classifyKind(descriptor, { csvType: map.type !== undefined ? f[map.type] : undefined })
    const issuerCategory = map.category !== undefined ? (f[map.category] ?? '').trim().toLowerCase() : ''
    const mccRaw = map.mcc !== undefined ? Number((f[map.mcc] ?? '').trim()) : NaN
    txns.push({
      dateISO,
      amountCents: cents,
      descriptor,
      ...(issuerCategory !== '' ? { issuerCategory } : {}),
      ...(Number.isInteger(mccRaw) && mccRaw > 0 ? { mcc: mccRaw } : {}),
      kind,
      source: { file, line: row.line },
    })
  }
  if (txns.length === 0) {
    throw new StatementParseError(
      `${file}: no parseable transactions (${rejectedRows} row(s) rejected).`,
    )
  }

  // Sign normalization to spend-positive. Profiles declare their convention;
  // the generic fallback infers it: if most purchase-classified rows are
  // negative, the export writes purchases negative.
  let flip: boolean
  if (profile) {
    flip = profile.negativePurchases && map.amount !== undefined
  } else if (map.amount !== undefined) {
    const purchases = txns.filter((t) => t.kind === 'purchase' && t.amountCents !== 0)
    const negatives = purchases.filter((t) => t.amountCents < 0).length
    flip = purchases.length > 0 && negatives * 2 > purchases.length
  } else {
    flip = false // debit/credit pairs are already normalized above
  }
  const normalized = txns.map((t) => {
    const amountCents = flip ? -t.amountCents : t.amountCents
    return { ...t, amountCents, kind: refineRefund(t.kind, amountCents) }
  })

  const dates = normalized.map((t) => t.dateISO).sort()
  return {
    summary: {
      name: file,
      format: 'csv',
      txns: normalized.length,
      rejectedRows,
      rangeStart: dates[0] ?? '',
      rangeEnd: dates[dates.length - 1] ?? '',
    },
    txns: normalized,
  }
}
