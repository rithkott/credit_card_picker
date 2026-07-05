/** Categorize/annualize/aggregate tests (plan 09, commit 4/5). The rules
 * fixture is an inline subset shaped exactly like /api/config's
 * statement_import payload. */

import { describe, expect, it } from 'vitest'
import { annualize, daysInclusive, mergeIntervals } from './annualize'
import { compileRules, descriptorStem, matchTxn, normalizeDescriptor } from './categorize'
import { aggregate, applyReview, toSpendState } from './aggregate'
import { validate } from '../validation'
import type { ConfigMerchant, StatementImportRules, UsageItem } from '../../types'
import type { NormalizedTxn, ParsedFile } from './types'

const RULES: StatementImportRules = {
  descriptors: [
    { key: 'delta', label: 'Delta Air Lines', patterns: ['DELTA AIR LINES', 'DELTA 006'] },
    { key: 'doordash', label: 'DoorDash', patterns: ['DD *DOORDASH', 'DOORDASH'] },
    { key: 'uber', label: 'Uber (rides)', patterns: ['UBER *TRIP', 'UBER TRIP'] },
    { key: 'uber_eats', label: 'Uber Eats', patterns: ['UBER *EATS', 'UBER EATS'] },
    { key: 'costco', label: 'Costco', patterns: ['COSTCO WHSE', 'COSTCO GAS'] },
    { key: 'whole_foods', label: 'Whole Foods Market', patterns: ['WHOLEFDS'] },
    { key: 'netflix', label: 'Netflix', patterns: ['NETFLIX'] },
    { key: 'apple', label: 'Apple', patterns: ['APPLE.COM/BILL', 'APPLE STORE'] },
    { key: 'apple_music', label: 'Apple Music', patterns: ['APPLE.COM/BILL'] },
    { key: 'paypal', label: 'PayPal', patterns: ['PAYPAL *', 'PP*'] },
    { key: 'toast_prefix', label: 'Toast-acquired restaurants', patterns: ['TST*'] },
    { key: 'square_prefix', label: 'Square-acquired merchants', patterns: ['SQ *'] },
    { key: 'bilt_rent', label: 'Bilt rent/housing payments', patterns: ['BILT'] },
  ],
  descriptor_categories: {
    delta: 'travel_flights',
    doordash: 'dining',
    uber: 'transit',
    uber_eats: 'dining',
    costco: 'groceries',
    whole_foods: 'groceries',
    netflix: 'streaming',
    apple: 'online_shopping',
    apple_music: 'streaming',
  },
  aggregator_prefixes: {
    paypal: {},
    square_prefix: {},
    toast_prefix: { fallback_category: 'dining' },
  },
  unmapped: ['bilt_rent'],
  keywords: {
    groceries: ['KROGER'],
    gas: ['SHELL'],
    dining: ['CAFE '],
  },
  issuer_categories: { 'dining': 'dining', 'gasoline': 'gas' },
  mcc: [{ from: 5812, to: 5814, category: 'dining' }],
}

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
const MATCHER = compileRules(RULES, MERCHANTS, USAGE_ITEMS)

const txn = (descriptor: string, over: Partial<NormalizedTxn> = {}): NormalizedTxn => ({
  dateISO: '2026-01-10', amountCents: 1000, descriptor, kind: 'purchase',
  source: { file: 'f', line: 1 }, ...over,
})

// ── matchTxn golden table ────────────────────────────────────────────────────

describe('matchTxn', () => {
  const cases: [string, Partial<NormalizedTxn>, ReturnType<typeof matchTxn>][] = [
    ['DELTA AIR LINES ATLANTA', {},
      { category: 'travel_flights', layer: 1, usageKey: 'delta', descriptorKey: 'delta', descriptorLabel: 'Delta Air Lines' }],
    ['COSTCO WHSE #0021', {},
      { category: 'groceries', layer: 1, merchantKey: 'costco', usageKey: 'costco', descriptorKey: 'costco', descriptorLabel: 'Costco' }],
    ['UBER *EATS PENDING', {},   // longest pattern: uber_eats, not uber
      { category: 'dining', layer: 1, descriptorKey: 'uber_eats', descriptorLabel: 'Uber Eats' }],
    ['APPLE.COM/BILL 866-712-7753', {},   // identical patterns tie-break by key asc -> apple
      { category: 'online_shopping', layer: 1, descriptorKey: 'apple', descriptorLabel: 'Apple' }],
    ['PAYPAL *DD *DOORDASH', {},   // prefix strip -> inner descriptor match
      { category: 'dining', layer: 1, usageKey: 'doordash', descriptorKey: 'doordash', descriptorLabel: 'DoorDash' }],
    ['PAYPAL *KROGER 442', {},     // prefix strip -> inner keyword match
      { category: 'groceries', layer: 2 }],
    ['TST* JOES CRAB SHACK', {},   // prefix, unknown remainder -> fallback
      { category: 'dining', layer: 1, descriptorKey: 'toast_prefix', descriptorLabel: 'Toast-acquired restaurants' }],
    ['SQ *UNKNOWN VENDOR', {},     // prefix, unknown remainder, no fallback
      { category: null, layer: null }],
    ['BILT REWARDS 000123', {},    // explicitly unmapped -> labeled group
      { category: null, layer: null, descriptorKey: 'bilt_rent', descriptorLabel: 'Bilt rent/housing payments' }],
    ['KROGER #442 SPRINGFIELD', {},
      { category: 'groceries', layer: 2 }],
    ['MYSTERY MERCHANT', { issuerCategory: 'dining' },
      { category: 'dining', layer: 3 }],
    ['MYSTERY MERCHANT', { mcc: 5813 },
      { category: 'dining', layer: 4 }],
    ['MYSTERY MERCHANT', {},
      { category: null, layer: null }],
  ]
  for (const [descriptor, over, expected] of cases) {
    it(`${descriptor} -> ${expected.category ?? 'uncategorized'} (layer ${expected.layer})`, () => {
      expect(matchTxn(MATCHER, txn(descriptor, over))).toEqual(expected)
    })
  }

  it('normalizes case and whitespace', () => {
    expect(normalizeDescriptor('  netflix.COM   ca ')).toBe('NETFLIX.COM CA')
    expect(matchTxn(MATCHER, txn('netflix.com')).category).toBe('streaming')
  })

  it('groups uncategorized stems without store numbers', () => {
    expect(descriptorStem('KWIK-E-MART #442 SPRINGFIELD'))
      .toBe(descriptorStem('KWIK-E-MART #187 SPRINGFIELD'))
    expect(descriptorStem('KWIK-E-MART #442 SPRINGFIELD')).toBe('KWIK-E-MART SPRINGFIELD')
    expect(descriptorStem('12345')).toBe('12345') // all-numeric falls back to itself
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
    ])], MATCHER)

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
      { key: 'whole_foods', label: 'Whole Foods Market', annualCents: 20000 },
    ].filter((s) => s.key !== 'whole_foods')) // whole_foods is not a usage item
  })

  it('clamps refund-heavy categories (and their carve-outs) at zero', () => {
    const result = aggregate([file('a.csv', RANGE, [
      txn('COSTCO WHSE #0021', { amountCents: 2000 }),
      txn('WHOLEFDS #10236', { amountCents: -5000, kind: 'refund' }),
      txn('SHELL OIL', { amountCents: 4000 }),
    ])], MATCHER)
    expect(result.categoryCents).toEqual({ gas: 20000 })
    expect(result.merchantCents).toEqual({}) // costco capped by clamped parent
  })

  it('warns on short coverage, overlaps, and rejected rows', () => {
    const result = aggregate([
      file('a.csv', ['2026-01-01', '2026-01-31'], [txn('KROGER')]),
      { ...file('b.csv', ['2026-01-15', '2026-02-10'], [txn('SHELL')]),
        summary: { ...file('b.csv', ['2026-01-15', '2026-02-10'], []).summary, rejectedRows: 3 } },
    ], MATCHER)
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
    })], MATCHER)
    expect(clean.warnings.filter((w) => w.code === 'W-reconcile')).toEqual([])

    const tampered = aggregate([file('s.pdf', RANGE, txns, {
      purchasesCents: 99999, paymentsAndCreditsCents: 100000,
    })], MATCHER)
    const reconcile = tampered.warnings.filter((w) => w.code === 'W-reconcile')
    expect(reconcile).toHaveLength(1)
    expect(reconcile[0].message).toMatch(/\$999\.99/)
    expect(reconcile[0].message).toMatch(/\$24\.50/)
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
  ])], MATCHER)

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
    ])], MATCHER)
    expect(withRefund.uncategorized).toEqual([
      { stem: 'SOME AIRLINE REFUND', count: 1, rawCents: -8000 },
    ])
    const out = applyReview(withRefund, { 'SOME AIRLINE REFUND': 'travel_flights' },
      new Set(), MERCHANTS)
    expect(out.categoryCents).toEqual({ travel_flights: (20000 - 8000) * 5 })
  })

  it('unassigned negative leftovers reduce other, clamped at zero', () => {
    const result = aggregate([file('a.csv', RANGE, [
      txn('MYSTERY MERCHANT', { amountCents: 1000 }),
      txn('MYSTERY REFUNDER', { amountCents: -9000, kind: 'refund' }),
    ])], MATCHER)
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
    const result = aggregate([file('a.csv', RANGE, txns)], MATCHER)
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
    ], { purchasesCents: 72484 })], MATCHER)
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
