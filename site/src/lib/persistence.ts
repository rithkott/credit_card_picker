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
const VERSION = 1

export interface PersistedForm {
  unit: Unit
  mode: 'generate' | 'analyze' | 'improve'
  spend: SpendState
  user: UserState
  selected: Set<string>
  /** Cards the user excluded from consideration (v2.5.0) — sent as the
   * profile's exclude_cards so generate/improve never pick them. */
  excluded: Set<string>
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
  if (v === 'analyze' || v === 'improve' || v === 'generate') return v
  if (v === 'manual') return 'analyze'
  return 'generate'
}

function coerceStringSet(v: unknown): Set<string> {
  if (!Array.isArray(v)) return new Set()
  return new Set(v.filter((x): x is string => typeof x === 'string'))
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
  if (!isObject(parsed) || parsed.v !== VERSION) return null
  return {
    unit: parsed.unit === 'annual' ? 'annual' : 'monthly',
    mode: coerceMode(parsed.mode),
    spend: coerceSpend(parsed.spend),
    user: coerceUser(parsed.user),
    selected: coerceStringSet(parsed.selected),
    excluded: coerceStringSet(parsed.excluded),
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
