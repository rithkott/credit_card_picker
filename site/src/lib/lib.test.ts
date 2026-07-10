/** Tests for the parse_profile mirrors — the drift-prone layer (plan 04).
 * Run: npm test (vitest). Components are covered by the manual checklist in
 * docs/plans/04-tech-stack.md instead. */
import { describe, expect, it } from 'vitest'
import {
  centsToDollars, displayFromAnnualCents, otherUnitAnnotation, parseToAnnualCents,
} from './money'
import { buildProfile, type UserState } from './profile'
import { validate, type SpendState } from './validation'
import type { ConfigMerchant } from '../types'

const MERCHANTS: ConfigMerchant[] = [
  { key: 'costco', label: 'Costco', category: 'groceries' },
  { key: 'uber', label: 'Uber', category: 'transit' },
]
const LABELS = { groceries: 'Groceries / supermarkets', transit: 'Transit & rideshare' }

const baseUser = (): UserState => ({
  credit_tier: 'very_good',
  optimize_for: 'ongoing',
  accepts_brand_lockin: false,
  rewardKinds: { cashback: true, flights: true, hotels: true },
  confirmed_usage: new Set(['doordash', 'chase_travel']),
})

const spendOf = (cats: Record<string, number | null>, mers: Record<string, number | null> = {}): SpendState => ({
  categoryCents: cats,
  merchantCents: mers,
})

describe('money: integer-cents canonical state (plan 03 §3.2)', () => {
  it('parses monthly input as x12 annual cents', () => {
    expect(parseToAnnualCents('666.67', 'monthly')).toBe(66667 * 12)
    expect(parseToAnnualCents('8000', 'annual')).toBe(800000)
  })
  it('blank is null, garbage is NaN, negatives are NaN', () => {
    expect(parseToAnnualCents('', 'annual')).toBeNull()
    expect(parseToAnnualCents('  ', 'monthly')).toBeNull()
    expect(Number.isNaN(parseToAnnualCents('12e', 'annual') as number)).toBe(true)
    expect(Number.isNaN(parseToAnnualCents('-5', 'annual') as number)).toBe(true)
  })
  it('accepts the grouped display format back ("8,000" round-trips)', () => {
    expect(parseToAnnualCents('8,000', 'annual')).toBe(800000)
    expect(parseToAnnualCents(displayFromAnnualCents(800000, 'annual'), 'annual')).toBe(800000)
  })
  it('display round-trips are lossless: toggle never mutates state', () => {
    const cents = parseToAnnualCents('641.67', 'annual') as number
    // Simulate toggling display units repeatedly: state is untouched by display.
    const shownMonthly = displayFromAnnualCents(cents, 'monthly')
    const shownAnnual = displayFromAnnualCents(cents, 'annual')
    expect(shownAnnual).toBe('641.67')
    expect(shownMonthly).toBe('53.47')
    expect(displayFromAnnualCents(cents, 'annual')).toBe('641.67') // unchanged after "toggling"
  })
  it('other-unit annotation (whole dollars — it is an approximation)', () => {
    expect(otherUnitAnnotation(800000, 'monthly')).toBe('≈ $8,000 /yr')
    expect(otherUnitAnnotation(800000, 'annual')).toBe('≈ $667 /mo')
    expect(otherUnitAnnotation(0, 'annual')).toBe('')
    expect(otherUnitAnnotation(null, 'annual')).toBe('')
  })
  it('centsToDollars emits integers when whole, 2-decimals otherwise', () => {
    expect(centsToDollars(800000)).toBe(8000)
    expect(centsToDollars(64167)).toBe(641.67)
  })
})

describe('validation: exact parse_profile mirror (plan 03 §4)', () => {
  it('E1 requires at least one nonzero category', () => {
    const { errors } = validate(spendOf({ groceries: 0, other: null }), MERCHANTS, 'good',
      { cashback: true }, LABELS)
    expect(errors.map((e) => e.code)).toContain('E1')
  })
  it('E2 flags NaN amounts', () => {
    const { errors } = validate(spendOf({ groceries: NaN, other: 100 }), MERCHANTS, 'good',
      { cashback: true }, LABELS)
    expect(errors.map((e) => e.code)).toContain('E2')
  })
  it('E3 caps carve-outs at the parent, in integer cents, incl. blank parent', () => {
    const over = validate(spendOf({ groceries: 100000 }, { costco: 100001 }), MERCHANTS, 'good',
      { cashback: true }, LABELS)
    expect(over.errors.map((e) => e.code)).toContain('E3')
    const blankParent = validate(spendOf({ other: 5000 }, { costco: 300000 }), MERCHANTS, 'good',
      { cashback: true }, LABELS)
    const e3 = blankParent.errors.find((e) => e.code === 'E3')
    expect(e3?.message).toContain('$0')
    const exact = validate(spendOf({ groceries: 100000, other: 1 }, { costco: 100000 }),
      MERCHANTS, 'good', { cashback: true }, LABELS)
    expect(exact.errors.map((e) => e.code)).not.toContain('E3') // equal is legal
  })
  it('E4 requires a credit tier', () => {
    const { errors } = validate(spendOf({ other: 100 }), MERCHANTS, null, { cashback: true }, LABELS)
    expect(errors.map((e) => e.code)).toContain('E4')
  })
  it('E5 requires at least one reward kind', () => {
    const { errors } = validate(spendOf({ other: 100 }), MERCHANTS, 'good',
      { cashback: false, flights: false, hotels: false }, LABELS)
    expect(errors.map((e) => e.code)).toContain('E5')
  })
  it('W1 nudges when other is 0 but never blocks', () => {
    const { errors, warnings } = validate(spendOf({ groceries: 100, other: 0 }), MERCHANTS,
      'good', { cashback: true }, LABELS)
    expect(errors).toHaveLength(0)
    expect(warnings.map((w) => w.code)).toContain('W1')
  })
})

describe('profile emission (plan 03 §2 rules)', () => {
  it('omits zero/blank categories and empty merchant_spend', () => {
    const p = buildProfile(spendOf({ groceries: 800000, dining: 0, other: null }), baseUser())
    expect(p.spend).toEqual({ groceries: 8000 })
    expect(p.merchant_spend).toBeUndefined()
  })
  it('includes nonzero carve-outs and all user keys', () => {
    const p = buildProfile(spendOf({ groceries: 800000 }, { costco: 300000, uber: 0 }), baseUser())
    expect(p.merchant_spend).toEqual({ costco: 3000 })
    expect(p.user).toEqual({
      credit_tier: 'very_good',
      max_cards: 3, // fixed (plan 08): the results view escalates sizes 1-3
      optimize_for: 'ongoing',
      activates_rotating: true, // assumed on; no longer asked in the UI
      accepts_brand_lockin: false,
      confirmed_usage: ['chase_travel', 'doordash'], // sorted
      reward_preferences: ['cashback', 'flights', 'hotels'],
    })
  })
  it('reward_preferences carries only the checked kinds — never total_value', () => {
    const user = baseUser()
    user.rewardKinds = { cashback: false, flights: true, hotels: false }
    const p = buildProfile(spendOf({ other: 100 }), user)
    expect(p.user.reward_preferences).toEqual(['flights'])
  })
})
