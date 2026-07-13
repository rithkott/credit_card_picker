/** Build the POST /api/optimize body from form state (plan 03 §2 emission
 * rules): zero/blank categories omitted (parse_profile reads absences as 0),
 * merchant_spend omitted entirely when no carve-out is nonzero, all user keys
 * always sent, reward_preferences = the checked kinds (the UI offers no
 * total_value — both kinds checked is the everything-run). */

import type { Profile } from '../types'
import { centsToDollars } from './money'
import type { SpendState } from './validation'

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

function nonzeroDollars(cents: Record<string, number | null>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [key, c] of Object.entries(cents)) {
    if (c !== null && !Number.isNaN(c) && c > 0) out[key] = centsToDollars(c)
  }
  return out
}

export function buildProfile(spend: SpendState, user: UserState): Profile {
  const profile: Profile = {
    spend: nonzeroDollars(spend.categoryCents),
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
  const merchantSpend = nonzeroDollars(spend.merchantCents)
  if (Object.keys(merchantSpend).length > 0) profile.merchant_spend = merchantSpend
  return profile
}
