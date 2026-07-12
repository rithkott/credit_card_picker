/** Detection/annualize tests (plan 09 lineage; detection-only since plan 14).
 * Matching happens on the server, so files here carry only the usage-item
 * matches — exactly the shape POST /api/statements/parse returns after
 * fromWire. Matcher behavior itself is pinned by the Python suite
 * (tests/test_statements.py). */

import { describe, expect, it } from 'vitest'
import { annualize, daysInclusive, mergeIntervals } from './annualize'
import { aggregate } from './aggregate'
import { fromWire } from './index'
import type { UsageItem } from '../../types'
import type { DetectedTxn, ParsedFile, WireParsedFile } from './types'

const USAGE_ITEMS: UsageItem[] = [
  { key: 'delta', label: 'Delta' },
  { key: 'doordash', label: 'DoorDash / DashPass' },
  { key: 'costco', label: 'Costco' },
  { key: 'uber', label: 'Uber rides / Uber One' },
]

const hit = (
  usageKey: string, amountCents: number, over: Partial<DetectedTxn> = {},
): DetectedTxn => ({
  dateISO: '2026-01-10', amountCents, descriptor: usageKey.toUpperCase(),
  kind: 'purchase', usageKey, usageLabel: `${usageKey} (wire)`,
  source: { file: 'f', line: 1 }, ...over,
})

const file = (
  name: string, range: [string, string], matches: DetectedTxn[],
): ParsedFile => ({
  summary: {
    name, format: 'csv', txns: matches.length + 10, rejectedRows: 0,
    rangeStart: range[0], rangeEnd: range[1],
  },
  matches,
})

// ── fromWire ─────────────────────────────────────────────────────────────────

describe('fromWire', () => {
  it('converts the server wire shape to browser camelCase', () => {
    const wire: WireParsedFile = {
      summary: {
        name: 's.pdf', format: 'pdf', txns: 214, rejected_rows: 2,
        range_start: '2026-01-01', range_end: '2026-01-31',
        statement_totals: { purchases_cents: 123456 },
        period_count: 1, extraction: 'layout',
      },
      matches: [{
        date: '2026-01-14', amount_cents: 41250,
        descriptor: 'DELTA AIR 0062341983477 ATLANTA', kind: 'purchase',
        line: 12, usage_key: 'delta', usage_label: 'Delta',
      }],
    }
    expect(fromWire(wire)).toEqual({
      summary: {
        // statement_totals is dropped on purpose: the client no longer
        // reconciles (it never sees the full transaction list to sum).
        name: 's.pdf', format: 'pdf', txns: 214, rejectedRows: 2,
        rangeStart: '2026-01-01', rangeEnd: '2026-01-31',
        periodCount: 1, extraction: 'layout',
      },
      matches: [{
        dateISO: '2026-01-14', amountCents: 41250,
        descriptor: 'DELTA AIR 0062341983477 ATLANTA', kind: 'purchase',
        usageKey: 'delta', usageLabel: 'Delta',
        source: { file: 's.pdf', line: 12 },
      }],
    })
  })
})

// ── annualize ────────────────────────────────────────────────────────────────

describe('annualize / coverage', () => {
  it('computes inclusive day spans', () => {
    expect(daysInclusive('2026-01-01', '2026-01-31')).toBe(31)
    expect(daysInclusive('2026-01-01', '2026-01-01')).toBe(1)
    expect(daysInclusive('2025-12-06', '2026-01-05')).toBe(31)
  })
  it('merges overlapping intervals without double-counting days', () => {
    expect(mergeIntervals([
      { start: '2026-01-01', end: '2026-01-31' },
      { start: '2026-01-15', end: '2026-02-14' },
    ])).toEqual({ days: 45, overlaps: true })
  })
  it('sums disjoint intervals and ignores gaps', () => {
    expect(mergeIntervals([
      { start: '2026-03-01', end: '2026-03-31' },
      { start: '2026-01-01', end: '2026-01-31' },
    ])).toEqual({ days: 62, overlaps: false })
    expect(mergeIntervals([])).toEqual({ days: 0, overlaps: false })
  })
  it('scales to 365 days', () => {
    expect(annualize(10000, 31)).toBe(Math.round((10000 * 365) / 31))
    expect(annualize(10000, 365)).toBe(10000)
    expect(annualize(10000, 0)).toBe(10000 * 365) // guarded divisor
  })
})

// ── aggregate (detection) ────────────────────────────────────────────────────

describe('aggregate', () => {
  // One 73-day window -> factor exactly 5 keeps expectations hand-computable.
  const RANGE: [string, string] = ['2026-01-01', '2026-03-14']

  it('sums per usage key, subtracts refunds, annualizes ×5, sorts by value', () => {
    const result = aggregate([file('a.csv', RANGE, [
      hit('delta', 20000),
      hit('costco', 10000),
      hit('costco', 5000),
      hit('costco', -1000, { kind: 'refund' }),
    ])], USAGE_ITEMS)
    expect(result.coverageDays).toBe(73)
    expect(result.usageSuggestions).toEqual([
      { key: 'delta', label: 'Delta', annualCents: 100000 },
      { key: 'costco', label: 'Costco', annualCents: (10000 + 5000 - 1000) * 5 },
    ])
  })

  it('prefers config labels, falls back to wire labels', () => {
    const result = aggregate(
      [file('a.csv', RANGE, [hit('delta', 1000), hit('mystery_key', 1000)])],
      USAGE_ITEMS)
    const labels = Object.fromEntries(result.usageSuggestions.map((s) => [s.key, s.label]))
    expect(labels['delta']).toBe('Delta')
    expect(labels['mystery_key']).toBe('mystery_key (wire)')
  })

  it('drops keys whose refunds net them to zero or below', () => {
    const result = aggregate([file('a.csv', RANGE, [
      hit('uber', 4000),
      hit('uber', -6000, { kind: 'refund' }),
      hit('delta', 1000),
    ])], USAGE_ITEMS)
    expect(result.usageSuggestions.map((s) => s.key)).toEqual(['delta'])
  })

  it('warns on short coverage, overlaps, and rejected rows', () => {
    const b = file('b.csv', ['2026-01-15', '2026-02-10'], [hit('delta', 100)])
    b.summary.rejectedRows = 3
    const result = aggregate([
      file('a.csv', ['2026-01-01', '2026-01-31'], [hit('costco', 100)]),
      b,
    ], USAGE_ITEMS)
    const codes = result.warnings.map((w) => w.code).sort()
    expect(codes).toEqual(['W-coverage', 'W-overlap', 'W-rows'])
  })

  it('discloses guessing parse paths: inferred columns, layout, multi-statement', () => {
    const inferred = file('a.csv', RANGE, [hit('delta', 100)])
    inferred.summary.columnInference = { used: true, confidence: 0.95 }
    const layout = file('b.pdf', RANGE, [])
    layout.summary.extraction = 'layout'
    layout.summary.periodCount = 3

    const codes = aggregate([inferred, layout], USAGE_ITEMS).warnings.map((w) => w.code)
    expect(codes).toContain('I-inferred-columns')
    expect(codes).toContain('I-layout')
    expect(codes).toContain('W-multi-statement')
  })

  it('empty matches still produce coverage and file summaries', () => {
    const result = aggregate([file('a.csv', RANGE, [])], USAGE_ITEMS)
    expect(result.usageSuggestions).toEqual([])
    expect(result.coverageDays).toBe(73)
    expect(result.files).toHaveLength(1)
  })
})
