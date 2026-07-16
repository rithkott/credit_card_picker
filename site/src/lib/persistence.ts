/** Local persistence for the input form (v1.9.0). The whole form lives in the
 * browser only — saved to localStorage so a refresh never loses entered values,
 * never uploaded (the footer's "no cookies/accounts/analytics" stays true; only
 * the built Profile is POSTed at run time). Run results are NOT persisted.
 *
 * Sets (user.confirmed_usage, selected) round-trip through arrays. Any parse or
 * shape failure — absent key, malformed JSON, wrong version, wrong field types —
 * discards the whole blob (returns null) so callers fall back to defaults and
 * the first-run wizard shows. Storage access is wrapped for private-mode/quota. */

import type { Unit } from './money'
import type { SpendState } from './validation'
import type { UserState } from './profile'

const KEY = 'ccp:form:v1'
/** v2: stored cents are in the unit the user entered them (money.ts). v1 blobs
 * are read as entered-unit too — see the note above loadForm. */
const VERSION = 2

export interface PersistedForm {
  unit: Unit
  mode: 'generate' | 'analyze' | 'improve' | 'compare'
  spend: SpendState
  user: UserState
  selected: Set<string>
  /** Cards the user excluded from consideration (v2.5.0) — sent as the
   * profile's exclude_cards so generate/improve never pick them. */
  excluded: Set<string>
  /** Compare path (plan 20): 2–4 hand-built card sets, in pick order. */
  comparePortfolios: string[][]
  completed: boolean
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Record<string, number|null>, dropping any non-number/non-null entries. */
function coerceCents(v: unknown): Record<string, number | null> {
  if (!isObject(v)) return {}
  const out: Record<string, number | null> = {}
  for (const [k, val] of Object.entries(v)) {
    if (val === null || typeof val === 'number') out[k] = val
  }
  return out
}

/** Record<string, (number|null)[]> — the "+"-added sub-amounts. Drops any
 * non-array entry and any non-number/non-null element; older blobs (pre this
 * feature) simply lack these keys and coerce to {}, so no version bump / reset. */
function coerceExtras(v: unknown): Record<string, (number | null)[]> {
  if (!isObject(v)) return {}
  const out: Record<string, (number | null)[]> = {}
  for (const [k, val] of Object.entries(v)) {
    if (Array.isArray(val)) {
      out[k] = val.filter((x): x is number | null => x === null || typeof x === 'number')
    }
  }
  return out
}

function coerceSpend(v: unknown): SpendState {
  const o = isObject(v) ? v : {}
  return {
    categoryCents: coerceCents(o.categoryCents),
    merchantCents: coerceCents(o.merchantCents),
    categoryExtraCents: coerceExtras(o.categoryExtraCents),
    merchantExtraCents: coerceExtras(o.merchantExtraCents),
  }
}

/** v2.2 renamed the modes without a version bump — blobs written before the
 * three-path journey carry 'auto'/'manual' and must migrate, not discard
 * (users keep their entered values across the deploy). 'manual' users had
 * hand-picked cards, so they land in 'analyze' with their picks intact. */
function coerceMode(v: unknown): PersistedForm['mode'] {
  if (v === 'analyze' || v === 'improve' || v === 'generate' || v === 'compare') return v
  if (v === 'manual') return 'analyze'
  return 'generate'
}

function coerceStringSet(v: unknown): Set<string> {
  if (!Array.isArray(v)) return new Set()
  return new Set(v.filter((x): x is string => typeof x === 'string'))
}

/** Compare path's 2–4 card sets. Pre-plan-20 blobs simply lack the key and
 * coerce to the default two empty portfolios — no version bump / reset (same
 * precedent as coerceExtras). Each entry keeps string ids only, deduped in
 * pick order; the list is clamped to 4 and padded to the 2-portfolio floor. */
function coercePortfolios(v: unknown): string[][] {
  const entries = Array.isArray(v)
    ? v.filter((p): p is unknown[] => Array.isArray(p)).slice(0, 4).map((p) =>
        [...new Set(p.filter((x): x is string => typeof x === 'string'))])
    : []
  while (entries.length < 2) entries.push([])
  return entries
}

function coerceUser(v: unknown): UserState {
  const o = isObject(v) ? v : {}
  const rewardKinds: Record<string, boolean> = {}
  if (isObject(o.rewardKinds)) {
    for (const [k, val] of Object.entries(o.rewardKinds)) {
      if (typeof val === 'boolean') rewardKinds[k] = val
    }
  }
  return {
    credit_tier: typeof o.credit_tier === 'string' ? o.credit_tier : null,
    optimize_for: o.optimize_for === 'year1' ? 'year1' : 'ongoing',
    accepts_brand_lockin: o.accepts_brand_lockin === true,
    rewardKinds,
    confirmed_usage: coerceStringSet(o.confirmed_usage),
  }
}

/** v1 blobs are read AS-IS (entered-unit cents), same as v2.
 *
 * History: v1 originally stored annual cents, and the unit-semantics change
 * (e133101) switched canonical storage to as-entered cents WITHOUT bumping the
 * version — so "v: 1" tags two incompatible populations. A first migration
 * attempt assumed v1 = annual and divided housing (and, under a monthly
 * toggle, every amount) by 12, which silently corrupted the entered-unit
 * v1 blobs live users actually hold: a $2,465/mo rent reloaded as $205/mo,
 * and the wrong value became permanent v2 state on their next edit. The
 * annual-cents v1 population only ever existed for the ~1 day between the
 * wizard-persistence launch and e133101; misreading one shows obviously
 * inflated (×12) numbers the user can see and retype, whereas the division
 * was subtle and destructive. So: no rescale, ever — v1 loads verbatim and
 * becomes v2 on the next save. */
export function loadForm(): PersistedForm | null {
  let raw: string | null
  try {
    raw = localStorage.getItem(KEY)
  } catch {
    return null
  }
  if (!raw) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isObject(parsed) || (parsed.v !== VERSION && parsed.v !== 1)) return null
  const unit: Unit = parsed.unit === 'annual' ? 'annual' : 'monthly'
  return {
    unit,
    spend: coerceSpend(parsed.spend),
    mode: coerceMode(parsed.mode),
    user: coerceUser(parsed.user),
    selected: coerceStringSet(parsed.selected),
    excluded: coerceStringSet(parsed.excluded),
    comparePortfolios: coercePortfolios(parsed.comparePortfolios),
    completed: parsed.completed === true,
  }
}

export function saveForm(state: PersistedForm): void {
  const payload = {
    v: VERSION,
    unit: state.unit,
    mode: state.mode,
    spend: state.spend,
    user: { ...state.user, confirmed_usage: [...state.user.confirmed_usage] },
    selected: [...state.selected],
    excluded: [...state.excluded],
    comparePortfolios: state.comparePortfolios,
    completed: state.completed,
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(payload))
  } catch {
    // Private mode / quota — persistence is best-effort, never block the UI.
  }
}

export function clearForm(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ignore
  }
}
