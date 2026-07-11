/** Aggregate/annualize/review tests (plan 09; server-side matches since
 * plan 12). Categorization now happens on the server, so transactions here
 * carry their `match` inline — exactly the shape POST /api/statements/parse
 * returns after fromWire. Matcher behavior itself is pinned by the Python
 * suite (tests/test_statements.py). */

import { describe, expect, it } from 'vitest'
import { annualize, daysInclusive, mergeIntervals } from './annualize'
import { aggregate, applyReview, toSpendState } from './aggregate'
import { fromWire } from './index'
import { validate } from '../validation'
import type { ConfigMerchant, UsageItem } from '../../types'
import type { NormalizedTxn, ParsedFile, TxnMatch, WireParsedFile } from './types'

const MERCHANTS: ConfigMerchant[] = [
  { key: 'costco', label: 'Costco', category: 'groceries' },
  { key: 'whole_foods', label: 'Whole Foods Market', category: 'groceries' },
  { key: 'uber', label: 'Uber (rides)', category: 'transit' },
]
const USAGE_ITEMS: UsageItem[] = [
  { key: 'delta', label: 'Delta' },
  { key: 'doordash', label: 'DoorDash / DashPass' },
  { key: 'costco', label: 'Costco' },
  { key: 'uber', label: 'Uber rides / Uber One' },
]

/** Server-shaped matches for the merchants the tests use. */
const MATCHES: Record<string, TxnMatch> = {
  'COSTCO WHSE #0021': {
    category: 'groceries', layer: 1, method: 'exact',
    merchantKey: 'costco', usageKey: 'costco',
    descriptorKey: 'costco', descriptorLabel: 'Costco', stem: 'COSTCO WHSE',
  },
  'WHOLEFDS #10236': {
    category: 'groceries', layer: 1, method: 'exact',
    merchantKey: 'whole_foods',
    descriptorKey: 'whole_foods', descriptorLabel: 'Whole Foods Market', stem: 'WHOLEFDS',
  },
  'KROGER #442': { category: 'groceries', layer: 2, method: 'exact', stem: 'KROGER SPRINGFIELD' },
  'KROGER': { category: 'groceries', layer: 2, method: 'exact', stem: 'KROGER' },
  'KROGER #1': { category: 'groceries', layer: 2, method: 'exact', stem: 'KROGER' },
  'SHELL': { category: 'gas', layer: 2, method: 'exact', stem: 'SHELL' },
  'SHELL OIL': { category: 'gas', layer: 2, method: 'exact', stem: 'SHELL OIL' },
  'DELTA AIR LINES': {
    category: 'travel_flights', layer: 1, method: 'exact',
    usageKey: 'delta', descriptorKey: 'delta', descriptorLabel: 'Delta Air Lines',
    stem: 'DELTA AIR LINES',
  },
  'BILT REWARDS': {
    category: null, layer: null, method: 'exact',
    descriptorKey: 'bilt_rent', descriptorLabel: 'Bilt rent/housing payments',
    stem: 'BILT REWARDS',
  },
}

const unmatched = (descriptor: string): TxnMatch => ({
  category: null, layer: null, method: null,
  stem: descriptor.replace(/[#*]?\d[\d\-/.]*/g, ' ').replace(/\s+/g, ' ').trim(),
})

const txn = (descriptor: string, over: Partial<NormalizedTxn> = {}): NormalizedTxn => ({
  dateISO: '2026-01-10', amountCents: 1000, descriptor, kind: 'purchase',
  match: MATCHES[descriptor] ?? unmatched(descriptor),
  source: { file: 'f', line: 1 }, ...over,
})

const file = (
  name: string, range: [string, string], txns: NormalizedTxn[],
  totals?: ParsedFile['summary']['statementTotals'],
): ParsedFile => ({
  summary: {
    name, format: 'csv', txns: txns.length, rejectedRows: 0,
    rangeStart: range[0], rangeEnd: range[1],
    ...(totals !== undefined ? { statementTotals: totals } : {}),
  },
  txns,
})

// ── fromWire ─────────────────────────────────────────────────────────────────

describe('fromWire', () => {
  it('converts the server wire shape to browser camelCase', () => {
    const wire: WireParsedFile = {
      summary: {
        name: 's.pdf', format: 'pdf', txns: 1, rejected_rows: 2,
        range_start: '2026-01-01', range_end: '2026-01-31',
        statement_totals: { purchases_cents: 2450, fees_cents: 0 },
        period_count: 1, extraction: 'layout',
      },
      txns: [{
        date: '2026-01-03', amount_cents: 2450, descriptor: 'KROGER #1',
        kind: 'purchase', line: 7,
        match: { category: 'groceries', layer: 5, method: 'fuzzy',
                 confidence: 0.93, stem: 'KROGER' },
      }],
    }
    expect(fromWire(wire)).toEqual({
      summary: {
        name: 's.pdf', format: 'pdf', txns: 1, rejectedRows: 2,
        rangeStart: '2026-01-01', rangeEnd: '2026-01-31',
        statementTotals: { purchasesCents: 2450, feesCents: 0 },
        periodCount: 1, extraction: 'layout',
      },
      txns: [{
        dateISO: '2026-01-03', amountCents: 2450, descriptor: 'KROGER #1',
        kind: 'purchase',
        match: { category: 'groceries', layer: 5, method: 'fuzzy',
                 confidence: 0.93, stem: 'KROGER' },
        source: { file: 's.pdf', line: 7 },
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
  it('E3 invariant: round is monotonic, carve-out never exceeds parent', () => {
    // Deterministic LCG so the property sweep is reproducible.
    let seed = 42
    const next = () => (seed = (seed * 1664525 + 1013904223) % 2 ** 32)
    for (let i = 0; i < 500; i++) {
      const parent = next() % 1_000_000
      const carve = next() % (parent + 1)
      const days = 1 + (next() % 400)
      expect(annualize(carve, days)).toBeLessThanOrEqual(annualize(parent, days))
    }
  })
})

// ── aggregate ────────────────────────────────────────────────────────────────

describe('aggregate', () => {
  // One 73-day window -> factor exactly 5 keeps expectations hand-computable.
  const RANGE: [string, string] = ['2026-01-01', '2026-03-14']

  it('buckets, excludes non-spend kinds, and annualizes ×5', () => {
    const result = aggregate([file('a.csv', RANGE, [
      txn('COSTCO WHSE #0021', { amountCents: 10000 }),
      txn('WHOLEFDS #10236', { amountCents: 5000 }),
      txn('KROGER #442', { amountCents: 3000 }),
      txn('DELTA AIR LINES', { amountCents: 20000 }),
      txn('PAYMENT THANK YOU', { amountCents: -30000, kind: 'payment' }),
      txn('ANNUAL FEE', { amountCents: 9500, kind: 'fee' }),
      txn('WHOLEFDS #10236', { amountCents: -1000, kind: 'refund' }),
      txn('MYSTERY MERCHANT 71', { amountCents: 4200 }),
      txn('BILT REWARDS', { amountCents: 150000 }),
    ])], MERCHANTS, USAGE_ITEMS)

    expect(result.coverageDays).toBe(73)
    expect(result.categoryCents).toEqual({
      groceries: (10000 + 5000 + 3000 - 1000) * 5,
      travel_flights: 20000 * 5,
    })
    expect(result.merchantCents).toEqual({
      costco: 50000,
      whole_foods: (5000 - 1000) * 5,
    })
    expect(result.excludedCents).toEqual({ payment: 30000, fee: 9500 })
    expect(result.uncategorized).toEqual([
      { stem: 'bilt_rent', label: 'Bilt rent/housing payments', count: 1, rawCents: 150000 },
      { stem: 'MYSTERY MERCHANT', count: 1, rawCents: 4200 },
    ])
    expect(result.usageSuggestions).toEqual([
      { key: 'delta', label: 'Delta', annualCents: 100000 },
      { key: 'costco', label: 'Costco', annualCents: 50000 },
    ])
  })

  it('clamps refund-heavy categories (and their carve-outs) at zero', () => {
    const result = aggregate([file('a.csv', RANGE, [
      txn('COSTCO WHSE #0021', { amountCents: 2000 }),
      txn('WHOLEFDS #10236', { amountCents: -5000, kind: 'refund' }),
      txn('SHELL OIL', { amountCents: 4000 }),
    ])], MERCHANTS, USAGE_ITEMS)
    expect(result.categoryCents).toEqual({ gas: 20000 })
    expect(result.merchantCents).toEqual({}) // costco capped by clamped parent
  })

  it('warns on short coverage, overlaps, and rejected rows', () => {
    const result = aggregate([
      file('a.csv', ['2026-01-01', '2026-01-31'], [txn('KROGER')]),
      { ...file('b.csv', ['2026-01-15', '2026-02-10'], [txn('SHELL')]),
        summary: { ...file('b.csv', ['2026-01-15', '2026-02-10'], []).summary, rejectedRows: 3 } },
    ], MERCHANTS, USAGE_ITEMS)
    const codes = result.warnings.map((w) => w.code).sort()
    expect(codes).toEqual(['W-coverage', 'W-overlap', 'W-rows'])
  })

  it('reconciles parsed sums against the statement summary box', () => {
    const txns = [
      txn('KROGER #1', { amountCents: 2450 }),
      txn('PAYMENT THANK YOU', { amountCents: -100000, kind: 'payment' }),
    ]
    const clean = aggregate([file('s.pdf', RANGE, txns, {
      purchasesCents: 2450, paymentsAndCreditsCents: 100000, feesCents: 0, interestCents: 0,
    })], MERCHANTS, USAGE_ITEMS)
    expect(clean.warnings.filter((w) => w.code === 'W-reconcile')).toEqual([])

    const tampered = aggregate([file('s.pdf', RANGE, txns, {
      purchasesCents: 99999, paymentsAndCreditsCents: 100000,
    })], MERCHANTS, USAGE_ITEMS)
    const reconcile = tampered.warnings.filter((w) => w.code === 'W-reconcile')
    expect(reconcile).toHaveLength(1)
    expect(reconcile[0].message).toMatch(/\$999\.99/)
    expect(reconcile[0].message).toMatch(/\$24\.50/)
  })

  it('discloses semantic-layer paths: fuzzy, semantic, inferred columns, layout', () => {
    const fuzzyTxn = txn('STARBUKS #99881', { amountCents: 640 })
    fuzzyTxn.match = { category: 'dining', layer: 5, method: 'fuzzy',
                       confidence: 0.94, stem: 'STARBUKS' }
    const semanticTxn = txn('JOES DELI 42', { amountCents: 1200 })
    semanticTxn.match = { category: 'dining', layer: 6, method: 'semantic',
                          confidence: 0.59, stem: 'JOES DELI' }
    const inferred = file('a.csv', RANGE, [fuzzyTxn, semanticTxn])
    inferred.summary.columnInference = { used: true, confidence: 0.95 }
    const layout = file('b.pdf', RANGE, [txn('KROGER #1')])
    layout.summary.extraction = 'layout'

    const result = aggregate([inferred, layout], MERCHANTS, USAGE_ITEMS)
    const codes = result.warnings.map((w) => w.code)
    expect(codes).toContain('I-fuzzy')
    expect(codes).toContain('I-semantic')
    expect(codes).toContain('I-inferred-columns')
    expect(codes).toContain('I-layout')
    // Approximate-match money still lands in its category.
    expect(result.categoryCents.dining).toBe((640 + 1200) * 5)
  })
})

// ── review edits + Apply payload ─────────────────────────────────────────────

describe('applyReview / toSpendState', () => {
  const RANGE: [string, string] = ['2026-01-01', '2026-03-14'] // ×5
  const base = aggregate([file('a.csv', RANGE, [
    txn('COSTCO WHSE #0021', { amountCents: 10000 }),
    txn('DELTA AIR LINES', { amountCents: 20000 }),
    txn('MYSTERY MERCHANT 71', { amountCents: 4200 }),
    txn('BILT REWARDS', { amountCents: 150000 }),
  ])], MERCHANTS, USAGE_ITEMS)

  it('moves reassigned groups and drops excluded categories', () => {
    const out = applyReview(base, { 'MYSTERY MERCHANT': 'dining' },
      new Set(['travel_flights']), MERCHANTS)
    expect(out.categoryCents).toEqual({ groceries: 50000, dining: 21000 })
    expect(out.merchantCents).toEqual({ costco: 50000 })
    expect(out.leftoverGroups.map((g) => g.stem)).toEqual(['bilt_rent'])
  })

  it('excluding a parent category drops its carve-outs', () => {
    const out = applyReview(base, {}, new Set(['groceries']), MERCHANTS)
    expect(out.merchantCents).toEqual({})
  })

  it('folds unlabeled leftovers into other; labeled groups never auto-fill', () => {
    const spend = toSpendState(base, {}, new Set(), MERCHANTS)
    expect(spend.categoryCents['other']).toBe(21000)   // mystery merchant only
    expect(Object.values(spend.categoryCents).reduce((s, c) => s! + (c ?? 0), 0))
      .toBe(50000 + 100000 + 21000)                    // bilt rent stayed out
  })

  it('assigned bilt rent lands where the user pointed it', () => {
    const spend = toSpendState(base, { bilt_rent: 'other' }, new Set(), MERCHANTS)
    expect(spend.categoryCents['other']).toBe(150000 * 5 + 21000)
  })

  it('keeps net-negative groups visible; unmatched refunds subtract on assign', () => {
    const withRefund = aggregate([file('a.csv', RANGE, [
      txn('DELTA AIR LINES', { amountCents: 20000 }),
      txn('SOME AIRLINE REFUND CO', { amountCents: -8000, kind: 'refund' }),
    ])], MERCHANTS, USAGE_ITEMS)
    expect(withRefund.uncategorized).toEqual([
      { stem: 'SOME AIRLINE REFUND CO', count: 1, rawCents: -8000 },
    ])
    const out = applyReview(withRefund, { 'SOME AIRLINE REFUND CO': 'travel_flights' },
      new Set(), MERCHANTS)
    expect(out.categoryCents).toEqual({ travel_flights: (20000 - 8000) * 5 })
  })

  it('unassigned negative leftovers reduce other, clamped at zero', () => {
    const result = aggregate([file('a.csv', RANGE, [
      txn('MYSTERY MERCHANT', { amountCents: 1000 }),
      txn('MYSTERY REFUNDER', { amountCents: -9000, kind: 'refund' }),
    ])], MERCHANTS, USAGE_ITEMS)
    const spend = toSpendState(result, {}, new Set(), MERCHANTS)
    expect(spend.categoryCents['other']).toBeUndefined()
  })

  it('money conservation: fully-assigned review equals annualized net spend', () => {
    const txns = [
      txn('COSTCO WHSE #0021', { amountCents: 10000 }),
      txn('DELTA AIR LINES', { amountCents: 20000 }),
      txn('MYSTERY MERCHANT 71', { amountCents: 4200 }),
      txn('BILT REWARDS', { amountCents: 150000 }),
      txn('MYSTERY REFUNDER', { amountCents: -3000, kind: 'refund' }),
      txn('PAYMENT THANK YOU', { amountCents: -50000, kind: 'payment' }),
    ]
    const result = aggregate([file('a.csv', RANGE, txns)], MERCHANTS, USAGE_ITEMS)
    const spend = toSpendState(result,
      { bilt_rent: 'other', 'MYSTERY MERCHANT': 'dining', 'MYSTERY REFUNDER': 'dining' },
      new Set(), MERCHANTS)
    const total = Object.values(spend.categoryCents).reduce((s, c) => s! + (c ?? 0), 0)
    const netSpendRaw = txns
      .filter((t) => t.kind === 'purchase' || t.kind === 'refund')
      .reduce((s, t) => s + t.amountCents, 0)
    expect(total).toBe(netSpendRaw * 5) // every parsed cent lands in exactly one bucket
  })

  it('reconciles issuer purchases totals that fold in balance transfers', () => {
    const result = aggregate([file('s.pdf', RANGE, [
      txn('KROGER #1', { amountCents: 16771 }),
      txn('CARD BALANCE TRANSFER', { amountCents: 55713, kind: 'transfer' }),
    ], { purchasesCents: 72484 })], MERCHANTS, USAGE_ITEMS)
    expect(result.warnings.filter((w) => w.code === 'W-reconcile')).toEqual([])
  })

  it('Apply output passes the form validation mirror unmodified', () => {
    const spend = toSpendState(base, { 'MYSTERY MERCHANT': 'dining' }, new Set(), MERCHANTS)
    const { errors } = validate(
      { categoryCents: spend.categoryCents, merchantCents: spend.merchantCents },
      MERCHANTS, 'good', { cashback: true }, {},
    )
    expect(errors).toEqual([])
  })
})
