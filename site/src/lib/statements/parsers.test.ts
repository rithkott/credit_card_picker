/** Parser tests (plan 09, commit 2/5): format detection, per-issuer CSV
 * goldens, OFX SGML/XML equivalence, batch dispatch. Fixtures are synthetic —
 * see __fixtures__/README.md. */

import { describe, expect, it } from 'vitest'
import { detectFormat } from './detect'
import { parseAmountToCents, parseCsv, parseDateToISO } from './csv'
import { parseOfx, parseOfxDate } from './ofx'
import { parseFiles, MAX_FILES } from './index'
import { StatementParseError } from './types'
import type { NormalizedTxn } from './types'
import chaseCsv from './__fixtures__/chase.csv?raw'
import amexCsv from './__fixtures__/amex.csv?raw'
import citiCsv from './__fixtures__/citi.csv?raw'
import capitalOneCsv from './__fixtures__/capital-one.csv?raw'
import bofaCsv from './__fixtures__/bofa.csv?raw'
import discoverCsv from './__fixtures__/discover.csv?raw'
import genericCsv from './__fixtures__/generic.csv?raw'
import quirksCsv from './__fixtures__/quirks.csv?raw'
import sgmlOfx from './__fixtures__/sgml.ofx?raw'
import xmlQfx from './__fixtures__/xml.qfx?raw'

const FIXTURES: Record<string, string> = {
  'chase.csv': chaseCsv, 'amex.csv': amexCsv, 'citi.csv': citiCsv,
  'capital-one.csv': capitalOneCsv, 'bofa.csv': bofaCsv,
  'discover.csv': discoverCsv, 'generic.csv': genericCsv,
  'quirks.csv': quirksCsv, 'sgml.ofx': sgmlOfx, 'xml.qfx': xmlQfx,
}
const fixture = (name: string): string => FIXTURES[name]
const fixtureBytes = (name: string): Uint8Array =>
  new TextEncoder().encode(FIXTURES[name])

// ── detect ───────────────────────────────────────────────────────────────────

describe('detectFormat', () => {
  const enc = (s: string) => new TextEncoder().encode(s)

  it('detects PDF by magic bytes', () => {
    expect(detectFormat(enc('%PDF-1.7 junk'), 'statement.pdf')).toBe('pdf')
    expect(detectFormat(enc('%PDF-1.4'), 'renamed.csv')).toBe('pdf')
  })
  it('detects OFX by header or root tag', () => {
    expect(detectFormat(fixtureBytes('sgml.ofx'), 'sgml.ofx')).toBe('ofx')
    expect(detectFormat(fixtureBytes('xml.qfx'), 'xml.qfx')).toBe('ofx')
  })
  it('falls back to the extension for content-ambiguous OFX', () => {
    expect(detectFormat(enc('who knows'), 'export.qfx')).toBe('ofx')
  })
  it('detects CSV by a delimited header line', () => {
    expect(detectFormat(fixtureBytes('chase.csv'), 'activity.csv')).toBe('csv')
    expect(detectFormat(fixtureBytes('quirks.csv'), 'quirks.txt')).toBe('csv')
  })
  it('returns unknown for binary junk', () => {
    expect(detectFormat(new Uint8Array([0x00, 0x01, 0x02]), 'blob.bin')).toBe('unknown')
  })
})

// ── field parsing ────────────────────────────────────────────────────────────

describe('parseDateToISO / parseAmountToCents / parseOfxDate', () => {
  it('parses US and ISO dates', () => {
    expect(parseDateToISO('01/05/2026')).toBe('2026-01-05')
    expect(parseDateToISO('1/5/26')).toBe('2026-01-05')
    expect(parseDateToISO('2026-01-05')).toBe('2026-01-05')
    expect(parseDateToISO('13/40/2026')).toBeNull()
    expect(parseDateToISO('yesterday')).toBeNull()
  })
  it('parses amount notations into signed cents', () => {
    expect(parseAmountToCents('1,234.56')).toBe(123456)
    expect(parseAmountToCents('$12.34')).toBe(1234)
    expect(parseAmountToCents('-12.34')).toBe(-1234)
    expect(parseAmountToCents('(150.00)')).toBe(-15000)
    expect(parseAmountToCents('12.34-')).toBe(-1234)
    expect(parseAmountToCents('12.34CR')).toBe(-1234)
    expect(parseAmountToCents('')).toBeNull()
    expect(parseAmountToCents('12.345')).toBeNull()
    expect(parseAmountToCents('abc')).toBeNull()
  })
  it('parses OFX timestamps', () => {
    expect(parseOfxDate('20260302120000[-5:EST]')).toBe('2026-03-02')
    expect(parseOfxDate('20260302')).toBe('2026-03-02')
    expect(parseOfxDate('2026030')).toBeNull()
  })
})

// ── CSV issuer goldens ───────────────────────────────────────────────────────

describe('parseCsv issuer profiles', () => {
  it('Chase: flips negative purchases, keeps Type-column kinds', () => {
    const { summary, txns } = parseCsv(fixture('chase.csv'), 'chase.csv')
    expect(summary).toMatchObject({
      format: 'csv', txns: 7, rejectedRows: 0,
      rangeStart: '2026-01-05', rangeEnd: '2026-01-28',
    })
    expect(txns[0]).toMatchObject({
      dateISO: '2026-01-05', amountCents: 2450, kind: 'purchase',
      descriptor: 'UBER *TRIP HELP.UBER.COM', issuerCategory: 'travel',
      source: { file: 'chase.csv', line: 2 },
    })
    expect(txns[3]).toMatchObject({ amountCents: -50000, kind: 'payment' })
    expect(txns[5]).toMatchObject({ amountCents: -1250, kind: 'refund' })
  })

  it('Amex: positive purchases kept, payments and fees classified', () => {
    const { txns } = parseCsv(fixture('amex.csv'), 'amex.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [41260, 'purchase'],
      [675, 'purchase'],
      [-75000, 'payment'],
      [28900, 'purchase'],
      [550, 'purchase'],
      [25000, 'fee'],
    ])
  })

  it('Citi: debit/credit pair normalizes to spend-positive', () => {
    const { txns } = parseCsv(fixture('citi.csv'), 'citi.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [16423, 'purchase'],
      [1840, 'purchase'],
      [-60000, 'payment'],
      [5280, 'purchase'],
      [-2000, 'refund'],
    ])
  })

  it('Capital One: debit/credit with autopay classified as payment', () => {
    const { txns } = parseCsv(fixture('capital-one.csv'), 'capital-one.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [32540, 'purchase'],
      [4812, 'purchase'],
      [-50000, 'payment'],
      [1485, 'purchase'],
    ])
    expect(txns[0].issuerCategory).toBe('airfare')
  })

  it('BofA: flips negative purchases via the payee profile', () => {
    const { txns } = parseCsv(fixture('bofa.csv'), 'bofa.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [1199, 'purchase'],
      [5642, 'purchase'],
      [-85000, 'payment'],
      [3875, 'purchase'],
    ])
  })

  it('Discover: positive purchases, negative rows become refunds', () => {
    const { txns } = parseCsv(fixture('discover.csv'), 'discover.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [7415, 'purchase'],
      [1549, 'purchase'],
      [-50000, 'payment'],
      [4130, 'purchase'],
      [-820, 'refund'],
    ])
  })

  it('generic fallback: header synonyms + majority-sign inference', () => {
    const { txns } = parseCsv(fixture('generic.csv'), 'generic.csv')
    expect(txns.map((t) => [t.amountCents, t.kind])).toEqual([
      [450, 'purchase'],
      [3310, 'purchase'],
      [-12000, 'payment'],
      [1200, 'purchase'],
    ])
  })

  it('quirks: BOM, CRLF, quoted commas/quotes, parenthesized negatives', () => {
    const text = new TextDecoder().decode(fixtureBytes('quirks.csv'))
    const { summary, txns } = parseCsv(text, 'quirks.csv')
    expect(summary.txns).toBe(3)
    expect(txns[0].descriptor).toBe('JOE\'S "FAMOUS" PIZZA, INC')
    expect(txns[0].amountCents).toBe(2340)
    expect(txns[1]).toMatchObject({ amountCents: -15000, kind: 'refund' })
  })

  it('throws a user-renderable error on unmappable headers', () => {
    expect(() => parseCsv('foo,bar\n1,2\n', 'weird.csv')).toThrow(StatementParseError)
    expect(() => parseCsv('foo,bar\n1,2\n', 'weird.csv')).toThrow(/date/)
  })
})

// ── OFX ──────────────────────────────────────────────────────────────────────

describe('parseOfx', () => {
  it('parses SGML: sign flip, FITID dedupe, MEMO concat, SIC, kinds, range', () => {
    const { summary, txns } = parseOfx(fixture('sgml.ofx'), 'sgml.ofx')
    expect(summary).toMatchObject({
      format: 'ofx', txns: 5,
      rangeStart: '2026-03-01', rangeEnd: '2026-03-31',
    })
    expect(txns[0]).toMatchObject({
      dateISO: '2026-03-02', amountCents: 4567, kind: 'purchase', mcc: 5812,
      descriptor: 'CHIPOTLE 2280 SEATTLE WA',
    })
    expect(txns[1].descriptor).toBe('WHOLEFDS #10236 GROCERY PURCHASE')
    expect(txns[2]).toMatchObject({ amountCents: -50000, kind: 'payment' })
    expect(txns[3]).toMatchObject({ amountCents: -1230, kind: 'refund' })
    expect(txns[4]).toMatchObject({ amountCents: 2345, kind: 'interest' })
    expect(txns.some((t) => t.descriptor.includes('DUPLICATE'))).toBe(false)
  })

  it('parses XML QFX identically to the SGML equivalent', () => {
    const strip = ({ source: _source, ...rest }: NormalizedTxn) => rest
    const sgml = parseOfx(fixture('sgml.ofx'), 'a').txns.map(strip)
    const xml = parseOfx(fixture('xml.qfx'), 'b').txns.map(strip)
    expect(xml).toEqual(sgml)
  })

  it('throws on OFX with no transactions', () => {
    expect(() => parseOfx('OFXHEADER:100\n<OFX></OFX>', 'empty.ofx')).toThrow(StatementParseError)
  })
})

// ── batch entry point ────────────────────────────────────────────────────────

describe('parseFiles', () => {
  it('parses a mixed batch and skips byte-identical duplicates', async () => {
    const chase = fixtureBytes('chase.csv')
    const result = await parseFiles([
      { name: 'chase.csv', bytes: chase },
      { name: 'chase-again.csv', bytes: chase },
      { name: 'sgml.ofx', bytes: fixtureBytes('sgml.ofx') },
    ])
    expect(result.files.map((f) => f.summary.name)).toEqual(['chase.csv', 'sgml.ofx'])
    expect(result.duplicates).toEqual(['chase-again.csv'])
    expect(result.errors).toEqual([])
  })

  it('turns bad files into per-file errors without killing the batch', async () => {
    const result = await parseFiles([
      { name: 'junk.bin', bytes: new Uint8Array([0, 1, 2]) },
      { name: 'amex.csv', bytes: fixtureBytes('amex.csv') },
    ])
    expect(result.files).toHaveLength(1)
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0].message).toMatch(/unrecognized format/)
  })

  it('rejects PDFs with the not-yet-supported stub error', async () => {
    const result = await parseFiles([
      { name: 's.pdf', bytes: new TextEncoder().encode('%PDF-1.7') },
    ])
    expect(result.errors[0].message).toMatch(/PDF/)
  })

  it('enforces the batch file limit', async () => {
    const inputs = Array.from({ length: MAX_FILES + 1 }, (_, i) => ({
      name: `f${i}.csv`, bytes: fixtureBytes('generic.csv').slice(),
    }))
    // Identical bytes: first parses, rest dedupe — but the 21st errors before reading.
    const result = await parseFiles(inputs)
    expect(result.errors.some((e) => e.message.includes('Batch limit'))).toBe(true)
  })
})
