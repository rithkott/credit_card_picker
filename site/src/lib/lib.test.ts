/** Tests for the parse_profile mirrors — the drift-prone layer (plan 04).
 * Run: npm test (vitest). Components are covered by the manual checklist in
 * docs/plans/04-tech-stack.md instead. */
import { describe, expect, it, vi } from 'vitest'
import {
  centsToDollars, displayCents, editDisplayCents, foldCents, otherUnitAnnotation,
  parseCents, sumAmount,
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
  rewardKinds: { cashback: true, points: true },
  confirmed_usage: new Set(['doordash', 'delta']),
})

const spendOf = (
  cats: Record<string, number | null>,
  mers: Record<string, number | null> = {},
  catExtras: Record<string, (number | null)[]> = {},
  merExtras: Record<string, (number | null)[]> = {},
): SpendState => ({
  categoryCents: cats,
  merchantCents: mers,
  categoryExtraCents: catExtras,
  merchantExtraCents: merExtras,
})

describe('money: integer-cents canonical state (plan 03 §3.2)', () => {
  it('parses a typed amount into cents, unit-agnostically (no x12 rescale)', () => {
    expect(parseCents('666.67')).toBe(66667)
    expect(parseCents('8000')).toBe(800000)
  })
  it('blank is null, garbage is NaN, negatives are NaN', () => {
    expect(parseCents('')).toBeNull()
    expect(parseCents('  ')).toBeNull()
    expect(Number.isNaN(parseCents('12e') as number)).toBe(true)
    expect(Number.isNaN(parseCents('-5') as number)).toBe(true)
  })
  it('accepts the grouped display format back ("8,000" round-trips)', () => {
    expect(parseCents('8,000')).toBe(800000)
    expect(parseCents(displayCents(800000))).toBe(800000)
  })
  it('display is unit-independent: toggling never rescales the stored cents', () => {
    const cents = parseCents('641.67') as number
    // The stored cents are the digits the user typed; the toggle only relabels
    // them, so the displayed number is the same in either unit.
    expect(displayCents(cents)).toBe('641.67')
    expect(editDisplayCents(cents)).toBe('641.67')
  })
  it('other-unit annotation (whole dollars — it is an approximation)', () => {
    // cents are in the current unit; the annotation shows the *other* unit.
    expect(otherUnitAnnotation(800000, 'monthly')).toBe('≈ $96,000 /yr')
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
      { cashback: false, points: false }, LABELS)
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
    const p = buildProfile(spendOf({ groceries: 800000, dining: 0, other: null }), baseUser(), 'annual')
    expect(p.spend).toEqual({ groceries: 8000 })
    expect(p.merchant_spend).toBeUndefined()
  })
  it('annualizes monthly entries at the profile boundary (grid + merchants x12)', () => {
    const p = buildProfile(
      spendOf({ groceries: 50000 }, { costco: 20000 }), baseUser(), 'monthly')
    expect(p.spend).toEqual({ groceries: 6000 }) // $500/mo -> $6,000/yr
    expect(p.merchant_spend).toEqual({ costco: 2400 }) // $200/mo -> $2,400/yr
  })
  it('housing is always annualized (its block is monthly regardless of toggle)', () => {
    // Grid unit annual, but housing cents are monthly -> still x12.
    const p = buildProfile(spendOf({ housing: 200000, other: 800000 }), baseUser(), 'annual')
    expect(p.spend).toEqual({ housing: 24000, other: 8000 })
  })
  it('includes nonzero carve-outs and all user keys', () => {
    const p = buildProfile(spendOf({ groceries: 800000 }, { costco: 300000, uber: 0 }), baseUser(), 'annual')
    expect(p.merchant_spend).toEqual({ costco: 3000 })
    expect(p.user).toEqual({
      credit_tier: 'very_good',
      max_cards: 3, // fixed (plan 08): the results view escalates sizes 1-3
      optimize_for: 'ongoing',
      activates_rotating: true, // assumed on; no longer asked in the UI
      accepts_brand_lockin: false,
      confirmed_usage: ['delta', 'doordash'], // sorted
      reward_preferences: ['cashback', 'points'],
    })
  })
  it('reward_preferences carries only the checked kinds — never total_value', () => {
    const user = baseUser()
    user.rewardKinds = { cashback: false, points: true }
    const p = buildProfile(spendOf({ other: 100 }), user, 'annual')
    expect(p.user.reward_preferences).toEqual(['points'])
  })
  it('exclude_cards emits the vetoed ids sorted, and is omitted when empty', () => {
    const p = buildProfile(
      spendOf({ other: 100 }), baseUser(), 'annual', new Set(['venture-x', 'active-cash']))
    expect(p.exclude_cards).toEqual(['active-cash', 'venture-x'])
    expect(buildProfile(spendOf({ other: 100 }), baseUser(), 'annual').exclude_cards).toBeUndefined()
  })
})

describe('"+"-added sub-amounts fold into the topic total', () => {
  it('sumAmount adds positive extras, ignoring null/0/NaN, and preserves an empty main', () => {
    expect(sumAmount(5000, [3000, null, 0, NaN])).toBe(8000)
    expect(sumAmount(null, [])).toBeNull()
    expect(sumAmount(null, [2000])).toBe(2000)
    expect(Number.isNaN(sumAmount(NaN, []) as number)).toBe(true)
  })
  it('foldCents merges keys from both main and extras records', () => {
    expect(foldCents({ groceries: 5000 }, { groceries: [3000], dining: [1000] }))
      .toEqual({ groceries: 8000, dining: 1000 })
  })
  it('buildProfile emits the folded per-category dollar total', () => {
    const p = buildProfile(
      spendOf({ groceries: 500000 }, {}, { groceries: [300000, 200000] }), baseUser(), 'annual')
    expect(p.spend).toEqual({ groceries: 10000 }) // 5000 + 3000 + 2000
  })
  it('buildProfile folds merchant carve-out sub-amounts too', () => {
    const p = buildProfile(
      spendOf({ groceries: 800000 }, { costco: 200000 }, {}, { costco: [100000] }), baseUser(), 'annual')
    expect(p.merchant_spend).toEqual({ costco: 3000 })
  })
  it('E1 is satisfied by a category whose total comes only from extras', () => {
    const { errors } = validate(spendOf({ groceries: null }, {}, { groceries: [50000] }),
      MERCHANTS, 'good', { cashback: true }, LABELS)
    expect(errors.map((e) => e.code)).not.toContain('E1')
  })
  it('E2 flags a NaN inside an extras array', () => {
    const { errors } = validate(spendOf({ other: 100 }, {}, { other: [NaN] }),
      MERCHANTS, 'good', { cashback: true }, LABELS)
    expect(errors.map((e) => e.code)).toContain('E2')
  })
  it('E3 compares folded carve-out totals against the folded parent', () => {
    // Parent groceries folds to 100000; costco folds to 100001 → over by 1 cent.
    const over = validate(spendOf({ groceries: 60000 }, { costco: 60000 },
      { groceries: [40000] }, { costco: [40001] }), MERCHANTS, 'good', { cashback: true }, LABELS)
    expect(over.errors.map((e) => e.code)).toContain('E3')
  })
})

describe('persistence: v2.2 mode migration (auto/manual → generate/analyze)', () => {
  const store = new Map<string, string>()
  const fakeStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  }
  const blobWithMode = (mode: unknown) => JSON.stringify({
    v: 2, unit: 'monthly', mode,
    spend: { categoryCents: { groceries: 50000 }, merchantCents: {}, categoryExtraCents: {}, merchantExtraCents: {} },
    user: {
      credit_tier: 'good', optimize_for: 'ongoing', accepts_brand_lockin: false,
      rewardKinds: { cashback: true }, confirmed_usage: [],
    },
    selected: ['chase-freedom-flex'], completed: true,
  })
  const loadWithMode = async (mode: unknown) => {
    vi.stubGlobal('localStorage', fakeStorage)
    store.set('ccp:form:v1', blobWithMode(mode))
    try {
      const { loadForm } = await import('./persistence')
      return loadForm()
    } finally {
      vi.unstubAllGlobals()
      store.clear()
    }
  }

  it("migrates 'manual' to 'analyze' keeping selected cards", async () => {
    const form = await loadWithMode('manual')
    expect(form?.mode).toBe('analyze')
    expect(form?.selected).toEqual(new Set(['chase-freedom-flex']))
    expect(form?.spend.categoryCents).toEqual({ groceries: 50000 })
  })
  it("migrates 'auto' to 'generate'", async () => {
    expect((await loadWithMode('auto'))?.mode).toBe('generate')
  })
  it('passes new values through and defaults junk to generate', async () => {
    expect((await loadWithMode('improve'))?.mode).toBe('improve')
    expect((await loadWithMode('compare'))?.mode).toBe('compare')
    expect((await loadWithMode('bogus'))?.mode).toBe('generate')
  })
})

describe('persistence: v1 → v2 spend migration (annual cents → entered-unit cents)', () => {
  // v1 stored ANNUAL cents for everything; v2 stores the raw typed number in
  // its entered unit. Un-migrated, a monthly-toggle grid inflates ×12 and
  // housing (always monthly) inflates ×12 even under an annual toggle — the
  // Bilt double-annualization bug (rent ×144 → ratio floor tier).
  const store = new Map<string, string>()
  const fakeStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  }
  const v1Blob = (unit: 'monthly' | 'annual') => JSON.stringify({
    v: 1, unit, mode: 'generate',
    spend: {
      // annual cents: $29,580/yr rent ($2,465/mo), $12,000/yr groceries
      categoryCents: { housing: 2958000, groceries: 1200000, dining: null },
      merchantCents: { costco: 600000 },
      categoryExtraCents: { housing: [120000, null] },
      merchantExtraCents: {},
    },
    user: {
      credit_tier: 'good', optimize_for: 'ongoing', accepts_brand_lockin: false,
      rewardKinds: { cashback: true }, confirmed_usage: [],
    },
    selected: [], excluded: [], completed: true,
  })
  const loadV1 = async (unit: 'monthly' | 'annual') => {
    vi.stubGlobal('localStorage', fakeStorage)
    store.set('ccp:form:v1', v1Blob(unit))
    try {
      const { loadForm } = await import('./persistence')
      return loadForm()
    } finally {
      vi.unstubAllGlobals()
      store.clear()
    }
  }

  it('annual toggle: grid unchanged, housing ÷12 back to monthly', async () => {
    const form = await loadV1('annual')
    expect(form?.spend.categoryCents).toEqual({ housing: 246500, groceries: 1200000, dining: null })
    expect(form?.spend.merchantCents).toEqual({ costco: 600000 })
    expect(form?.spend.categoryExtraCents).toEqual({ housing: [10000, null] })
  })
  it('monthly toggle: everything ÷12 (grid, merchants, extras, housing)', async () => {
    const form = await loadV1('monthly')
    expect(form?.spend.categoryCents).toEqual({ housing: 246500, groceries: 100000, dining: null })
    expect(form?.spend.merchantCents).toEqual({ costco: 50000 })
    expect(form?.spend.categoryExtraCents).toEqual({ housing: [10000, null] })
  })
  it('v2 blobs load untouched; unknown versions discard', async () => {
    vi.stubGlobal('localStorage', fakeStorage)
    try {
      const v2 = JSON.parse(v1Blob('monthly'))
      v2.v = 2
      store.set('ccp:form:v1', JSON.stringify(v2))
      const { loadForm } = await import('./persistence')
      expect(loadForm()?.spend.categoryCents).toEqual({ housing: 2958000, groceries: 1200000, dining: null })
      v2.v = 3
      store.set('ccp:form:v1', JSON.stringify(v2))
      expect(loadForm()).toBeNull()
    } finally {
      vi.unstubAllGlobals()
      store.clear()
    }
  })
})

describe('persistence: compare portfolios (plan 20)', () => {
  const store = new Map<string, string>()
  const fakeStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  }
  const blob = (extra: Record<string, unknown>) => JSON.stringify({
    v: 2, unit: 'monthly', mode: 'compare',
    spend: { categoryCents: {}, merchantCents: {}, categoryExtraCents: {}, merchantExtraCents: {} },
    user: {
      credit_tier: 'good', optimize_for: 'ongoing', accepts_brand_lockin: false,
      rewardKinds: { cashback: true }, confirmed_usage: [],
    },
    selected: [], excluded: [], completed: true,
    ...extra,
  })
  const loadBlob = async (extra: Record<string, unknown>) => {
    vi.stubGlobal('localStorage', fakeStorage)
    store.set('ccp:form:v1', blob(extra))
    try {
      const { loadForm } = await import('./persistence')
      return loadForm()
    } finally {
      vi.unstubAllGlobals()
      store.clear()
    }
  }

  it('pre-plan-20 blob (key absent) still loads, defaulting to two empty portfolios', async () => {
    const form = await loadBlob({})
    expect(form).not.toBeNull()
    expect(form?.comparePortfolios).toEqual([[], []])
  })
  it('round-trips 2–4 portfolios in pick order', async () => {
    const portfolios = [['amex-gold', 'chase-freedom-flex'], ['csp'], ['bilt']]
    expect((await loadBlob({ comparePortfolios: portfolios }))?.comparePortfolios)
      .toEqual(portfolios)
  })
  it('coerces malformed shapes: non-array, junk members, dupes, over-cap', async () => {
    expect((await loadBlob({ comparePortfolios: 'junk' }))?.comparePortfolios).toEqual([[], []])
    expect((await loadBlob({ comparePortfolios: [['a', 5, 'a', null, 'b'], 'junk'] }))?.comparePortfolios)
      .toEqual([['a', 'b'], []])
    expect((await loadBlob({ comparePortfolios: [['a'], ['b'], ['c'], ['d'], ['e']] }))?.comparePortfolios)
      .toEqual([['a'], ['b'], ['c'], ['d']])
    expect((await loadBlob({ comparePortfolios: [['solo']] }))?.comparePortfolios)
      .toEqual([['solo'], []])
  })
  it('saveForm writes portfolios back verbatim', async () => {
    vi.stubGlobal('localStorage', fakeStorage)
    try {
      const { loadForm, saveForm } = await import('./persistence')
      store.set('ccp:form:v1', blob({ comparePortfolios: [['x'], ['y', 'z']] }))
      const form = loadForm()
      expect(form).not.toBeNull()
      saveForm(form!)
      const written = JSON.parse(store.get('ccp:form:v1')!) as { comparePortfolios: string[][] }
      expect(written.comparePortfolios).toEqual([['x'], ['y', 'z']])
    } finally {
      vi.unstubAllGlobals()
      store.clear()
    }
  })
})
