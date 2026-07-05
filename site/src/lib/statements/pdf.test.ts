/** PDF parser tests (plan 09, commit 3/5). The .pdf.b64 fixtures are
 * base64-encoded SYNTHETIC statements generated from hand-written text lines
 * (see __fixtures__/README.md) — statement.pdf has a real text layer,
 * scanned.pdf has none (image-only stand-in). */

import { describe, expect, it } from 'vitest'
import { extractFromLines, parsePdf, reconstructLines } from './pdf'
import { ScannedPdfError, StatementParseError } from './types'
import statementB64 from './__fixtures__/statement.pdf.b64?raw'
import scannedB64 from './__fixtures__/scanned.pdf.b64?raw'

const fromB64 = (b64: string): Uint8Array =>
  Uint8Array.from(atob(b64.trim()), (c) => c.charCodeAt(0))

// ── reconstructLines (pure) ──────────────────────────────────────────────────

describe('reconstructLines', () => {
  it('clusters items by y, orders by x, drops whitespace items', () => {
    expect(reconstructLines([
      { str: '$87.13', x: 450, y: 700 },
      { str: ' ', x: 200, y: 700 },
      { str: '12/18', x: 72, y: 700.5 },
      { str: 'WHOLEFDS #10236', x: 130, y: 699.8 },
      { str: 'PURCHASES', x: 72, y: 714 },
    ])).toEqual([
      'PURCHASES',
      '12/18 WHOLEFDS #10236 $87.13',
    ])
  })
  it('returns nothing for empty input', () => {
    expect(reconstructLines([])).toEqual([])
  })
})

// ── extractFromLines (pure) ──────────────────────────────────────────────────

describe('extractFromLines', () => {
  const LINES = [
    'Opening/Closing Date 12/06/25 - 01/05/26',
    'Payments and Other Credits -$1,012.50',
    'Purchases +$223.31',
    'Fees Charged $0.00',
    'Interest Charged $0.00',
    'PAYMENTS AND OTHER CREDITS',
    '12/15 Payment Thank You - Web -$1,000.00',
    '12/20 WHOLEFDS #10236 SEATTLE WA -$12.50',
    'PURCHASES',
    '12/12 UBER *TRIP HELP.UBER.COM $24.50',
    '01/02 SHELL OIL 5744221 PORTLAND OR $41.20',
    'Total fees charged in 2025 $0.00',
  ]

  it('extracts the period, summary totals, and dated transactions', () => {
    const out = extractFromLines(LINES, 'x.pdf')
    expect(out.rangeStart).toBe('2025-12-06')
    expect(out.rangeEnd).toBe('2026-01-05')
    expect(out.statementTotals).toEqual({
      purchasesCents: 22331,
      paymentsAndCreditsCents: 101250,
      feesCents: 0,
      interestCents: 0,
    })
  })

  it('infers years across the December-January boundary', () => {
    const out = extractFromLines(LINES, 'x.pdf')
    expect(out.txns.map((t) => [t.dateISO, t.amountCents, t.kind])).toEqual([
      ['2025-12-15', -100000, 'payment'],
      ['2025-12-20', -1250, 'refund'],
      ['2025-12-12', 2450, 'purchase'],
      ['2026-01-02', 4120, 'purchase'],
    ])
  })

  it('handles explicit years without a period line', () => {
    const out = extractFromLines(['03/05/2026 KROGER #442 $74.15'], 'x.pdf')
    expect(out.txns[0]).toMatchObject({ dateISO: '2026-03-05', amountCents: 7415 })
    expect(out.rangeStart).toBe('2026-03-05')
  })

  it('rejects a file with only undated MM/DD lines and no period', () => {
    expect(() => extractFromLines(['12/12 UBER TRIP $24.50'], 'x.pdf'))
      .toThrow(/no statement period/)
  })

  it('throws when no transaction lines are recognized', () => {
    expect(() => extractFromLines(['just prose', 'nothing here'], 'x.pdf'))
      .toThrow(StatementParseError)
  })
})

// ── parsePdf (integration, node legacy build) ────────────────────────────────

describe('parsePdf', () => {
  it('parses the synthetic statement PDF end to end', async () => {
    const { summary, txns } = await parsePdf(fromB64(statementB64), 'statement.pdf')
    expect(summary).toMatchObject({
      format: 'pdf',
      txns: 7,
      rangeStart: '2025-12-06',
      rangeEnd: '2026-01-05',
      statementTotals: {
        purchasesCents: 22331,
        paymentsAndCreditsCents: 101250,
        feesCents: 0,
        interestCents: 0,
      },
    })
    const purchases = txns.filter((t) => t.kind === 'purchase')
    expect(purchases.reduce((s, t) => s + t.amountCents, 0)).toBe(22331)
    const refunds = txns.filter((t) => t.kind === 'refund')
    expect(refunds.reduce((s, t) => s + t.amountCents, 0)).toBe(-1250)
    expect(txns.find((t) => t.kind === 'payment')?.amountCents).toBe(-100000)
    expect(txns.map((t) => t.dateISO).sort()[0]).toBe('2025-12-12')
  })

  it('rejects scanned (text-free) PDFs with the CSV pointer', async () => {
    await expect(parsePdf(fromB64(scannedB64), 'scanned.pdf'))
      .rejects.toThrow(ScannedPdfError)
    await expect(parsePdf(fromB64(scannedB64), 'scanned.pdf'))
      .rejects.toThrow(/CSV/)
  })

  it('turns corrupt PDFs into a user-renderable error', async () => {
    await expect(parsePdf(new TextEncoder().encode('%PDF-1.7 garbage'), 'bad.pdf'))
      .rejects.toThrow(/couldn't read this PDF/)
  })
})
