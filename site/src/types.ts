/** TS mirrors of the server contract (server/app.py).
 *
 * Config mirrors GET /api/config; OptimizeBundle mirrors the output of
 * scripts/optimize.py run() returned verbatim by POST /api/optimize.
 * Per CLAUDE.md: changes to run()'s bundle shape or the optimizer's
 * TIER_ORDER / USER_DEFAULTS / REWARD_KINDS must update this file in the
 * same change.
 */

export interface ConfigCategory { key: string; label: string }
export interface ConfigMerchant { key: string; label: string; category: string }
export interface UsageItem { key: string; label: string }
export interface UsageGroup { key: string; label: string; prompt: string; items: UsageItem[] }

export interface Config {
  categories: ConfigCategory[]
  merchants: ConfigMerchant[]
  usage_questions: UsageGroup[]
  tier_order: string[]
  user_defaults: {
    valuation_mode: 'floor' | 'optimistic'
    max_cards: number
    optimize_for: 'ongoing' | 'year1'
    activates_rotating: boolean
    accepts_brand_lockin: boolean
    confirmed_usage: string[]
    reward_preferences: string[]
  }
  reward_kinds: string[]
  max_cards_range: [number, number]
  cards_total: number
}

export interface ProfileUser {
  credit_tier: string
  valuation_mode: 'floor' | 'optimistic'
  max_cards: number
  optimize_for: 'ongoing' | 'year1'
  activates_rotating: boolean
  accepts_brand_lockin: boolean
  confirmed_usage: string[]
  reward_preferences: string[]
}

export interface Profile {
  spend: Record<string, number>
  merchant_spend?: Record<string, number>
  user: ProfileUser
}

export interface Assignment {
  bucket: string
  usd_assigned: number
  rate: number
  cpp: number
  usd_value: number
  note: string
}

export interface CreditLine { name: string; value: number; note: string }

export interface PerCard {
  name: string
  assignments: Assignment[]
  credits: CreditLine[]
  bonus: { value: number; note: string }
  fees: {
    annual_fee_usd: number
    first_year_waived: boolean
    membership_fee_usd?: number
    membership_name?: string
  }
  warnings: string[]
  valuation_note?: string
  reward_cap_clamp?: number
  choice_category?: string
}

export interface Portfolio {
  cards: string[]
  ongoing_net: number
  year1_net: number
  earnings: number
  unassigned_spend: Record<string, number>
  per_card: Record<string, PerCard>
}

export interface OptimizeBundle {
  as_of: string
  valuation_mode: 'floor' | 'optimistic'
  optimize_for: 'ongoing' | 'year1'
  max_cards: number
  reward_preferences: string[]
  confirmed_usage: string[]
  accepts_brand_lockin: boolean
  cpp_table: Record<string, { floor_cpp: number; optimistic_cpp: number }>
  policy_constants: Record<string, unknown>
  cards_total: number
  cards_eligible: number
  card_variants: number
  card_variants_pruned: number
  pruned: { id: string; reason: string }[]
  excluded: { id: string; reason: string }[]
  portfolios: Portfolio[]
}
