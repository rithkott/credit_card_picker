/** Build the POST /api/optimize body from form state (plan 03 §2 emission
 * rules): zero/blank categories omitted (parse_profile reads absences as 0),
 * merchant_spend omitted entirely when no carve-out is nonzero, all user keys
 * always sent, reward_preferences = the checked kinds (the UI offers no
 * total_value — both kinds checked is the everything-run). */

import type { Profile } from '../types'
import { centsToDollars, foldCents, type Unit } from './money'
import type { SpendState } from './validation'

/** Housing (rent/mortgage) is always entered monthly in its own block,
 * regardless of the spending grid's toggle, so it is always annualized. */
const HOUSING_KEY = 'housing'

export interface UserState {
  credit_tier: string | null
  optimize_for: 'ongoing' | 'year1'
  accepts_brand_lockin: boolean
  rewardKinds: Record<string, boolean>
  confirmed_usage: Set<string>
}

/** Fixed for the product UI (plan 08): the engine searches sizes 1..3 and the
 * results view escalates best-1 → best-2 → best-3; rotating activation is
 * assumed (the engine already dilutes rotating lines to the ~1/N featured-
 * quarter share of each eligible bucket). */
export const MAX_CARDS = 3

const ACTIVATES_ROTATING = true

/** Emit nonzero keys as annual dollars. Stored cents are in the entered unit;
 * `monthlyKey(key)` decides which keys are monthly and get ×12 to annualize. */
function nonzeroDollars(
  cents: Record<string, number | null>,
  monthlyKey: (key: string) => boolean,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [key, c] of Object.entries(cents)) {
    if (c !== null && !Number.isNaN(c) && c > 0) {
      const annualCents = monthlyKey(key) ? c * 12 : c
      out[key] = centsToDollars(annualCents)
    }
  }
  return out
}

export function buildProfile(
  spend: SpendState,
  user: UserState,
  unit: Unit,
  excluded: Set<string> = new Set(),
): Profile {
  // Grid amounts are monthly when the toggle is monthly; housing is always
  // monthly (its block ignores the toggle). Merchants share the grid's unit.
  const gridMonthly = (key: string) => unit === 'monthly' || key === HOUSING_KEY
  const merchantMonthly = () => unit === 'monthly'
  const profile: Profile = {
    spend: nonzeroDollars(foldCents(spend.categoryCents, spend.categoryExtraCents), gridMonthly),
    user: {
      credit_tier: user.credit_tier ?? '',
      max_cards: MAX_CARDS,
      optimize_for: user.optimize_for,
      activates_rotating: ACTIVATES_ROTATING,
      accepts_brand_lockin: user.accepts_brand_lockin,
      confirmed_usage: [...user.confirmed_usage].sort(),
      reward_preferences: Object.entries(user.rewardKinds)
        .filter(([, on]) => on)
        .map(([kind]) => kind),
    },
  }
  const merchantSpend = nonzeroDollars(
    foldCents(spend.merchantCents, spend.merchantExtraCents), merchantMonthly)
  if (Object.keys(merchantSpend).length > 0) profile.merchant_spend = merchantSpend
  if (excluded.size > 0) profile.exclude_cards = [...excluded].sort()
  return profile
}
