/** OFX / QFX statement parsing (plan 09).
 *
 * One tolerant scanner for both variants: OFX 1.x is SGML (leaf tags have no
 * closing tag), OFX 2.x is XML. Both write each value as <TAG>value, so a
 * per-tag scan up to the next '<' or newline reads either. Sign convention:
 * OFX credit-card charges are NEGATIVE TRNAMT, so amounts are flipped to the
 * importer's spend-positive convention.
 */

import { classifyKind, refineRefund } from './kind'
import { StatementParseError } from './types'
import type { NormalizedTxn, ParsedFile } from './types'

/** <DTPOSTED>20260214093000[-5:EST] -> 2026-02-14 (null on garbage). */
export function parseOfxDate(text: string): string | null {
  const m = /^(\d{4})(\d{2})(\d{2})/.exec(text.trim())
  if (!m) return null
  const mo = Number(m[2]); const d = Number(m[3])
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return `${m[1]}-${m[2]}-${m[3]}`
}

const ENTITIES: Record<string, string> = {
  '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'",
}

function tag(block: string, name: string): string | undefined {
  const m = new RegExp(`<${name}>([^<\\r\\n]*)`, 'i').exec(block)
  const value = m?.[1].trim().replace(/&(amp|lt|gt|quot|apos);/g, (e) => ENTITIES[e])
  return value ? value : undefined
}

export function parseOfx(text: string, file: string): ParsedFile {
  const blocks = text.match(/<STMTTRN>[\s\S]*?(?=<STMTTRN>|<\/STMTTRN>|<\/BANKTRANLIST>|$)/gi)
  if (!blocks || blocks.length === 0) {
    throw new StatementParseError(`${file}: no <STMTTRN> transactions found.`)
  }

  const txns: NormalizedTxn[] = []
  const seenFitids = new Set<string>()
  let rejectedRows = 0
  for (const block of blocks) {
    const fitid = tag(block, 'FITID')
    if (fitid !== undefined) {
      if (seenFitids.has(fitid)) continue // issuer-declared duplicate
      seenFitids.add(fitid)
    }
    const dateISO = parseOfxDate(tag(block, 'DTPOSTED') ?? '')
    const amountRaw = Number(tag(block, 'TRNAMT') ?? NaN)
    const name = tag(block, 'NAME') ?? ''
    const memo = tag(block, 'MEMO') ?? ''
    const descriptor = [name, memo].filter(Boolean).join(' ').trim()
    if (dateISO === null || !Number.isFinite(amountRaw) || descriptor === '') {
      rejectedRows++
      continue
    }
    // Flip: OFX charges are negative; the importer wants spend positive.
    const amountCents = -Math.round(amountRaw * 100)
    const kind = refineRefund(
      classifyKind(descriptor, { ofxType: tag(block, 'TRNTYPE') }), amountCents)
    const sic = Number(tag(block, 'SIC') ?? NaN)
    txns.push({
      dateISO,
      amountCents,
      descriptor,
      ...(Number.isInteger(sic) && sic > 0 ? { mcc: sic } : {}),
      kind,
      // OFX has no meaningful line numbers; index the block instead.
      source: { file, line: txns.length + rejectedRows + 1 },
    })
  }
  if (txns.length === 0) {
    throw new StatementParseError(
      `${file}: no parseable transactions (${rejectedRows} block(s) rejected).`,
    )
  }

  // Issuer-declared statement range when present, else observed txn range.
  const dates = txns.map((t) => t.dateISO).sort()
  const rangeStart = parseOfxDate(tag(text, 'DTSTART') ?? '') ?? dates[0]
  const rangeEnd = parseOfxDate(tag(text, 'DTEND') ?? '') ?? dates[dates.length - 1]
  return {
    summary: {
      name: file,
      format: 'ofx',
      txns: txns.length,
      rejectedRows,
      rangeStart,
      rangeEnd,
    },
    txns,
  }
}
