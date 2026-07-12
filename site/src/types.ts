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
export interface UsageGroup {
  key: string
  label: string
  prompt: string
  /** Set on brand-loyalty groups (airlines → 'flights', hotels → 'hotels'):
   * the UI renders them in the Brand loyalty block, and the optimizer treats
   * their items as assumed-usable when the kind is in reward_preferences. */
  assumed_reward_kind: string | null
  items: UsageItem[]
}

export interface Config {
  categories: ConfigCategory[]
  merchants: ConfigMerchant[]
  usage_questions: UsageGroup[]
  tier_order: string[]
  user_defaults: {
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
  /** Most recent verification date across the dataset (YYYY-MM-DD), computed
   * server-side from the card files — quoted by the footer trust line instead
   * of a hardcoded date. Null only if no card carries a date. */
  data_last_verified: string | null
}

/** GET /api/cards — one row per card file, for the Data-sources page. */
export interface CardSummary {
  id: string
  name: string
  issuer: string
  network: string | null
  annual_fee_usd: number
  currency: { type: string; program: string; program_label: string }
  base_rate: number | null
  verification: {
    last_verified_date: string | null
    confidence: string | null
    verified_by: string | null
  }
}
export interface CardsResponse { cards: CardSummary[]; total: number }

/** GET /api/assumptions — the shared point-valuation table
 * (data/meta/point-valuations.yaml), exactly as the optimizer uses it. */
export interface AssumptionProgram {
  key: string
  label: string
  redeems_for: string[]
  floor_cpp: number
  optimistic_cpp: number
  transfer_gateway_required: boolean
  loyalty_keys: string[]
}
export interface AssumptionsResponse { programs: AssumptionProgram[] }

export interface ProfileUser {
  credit_tier: string
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
  /** The card's earning currency: cash back or a points program. Drives
   * points-chain rendering (spend → pts → $ at cpp) vs plain % lines. */
  currency: { kind: 'cash' | 'points'; program: string; label: string }
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
  /** Positive counterpart of valuation_note: this card's points reach the avg
   * valuation because a gateway card (e.g. a Sapphire) is in the portfolio. */
  pairing_note?: string
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

export interface BestBySize extends Portfolio {
  size: number
}

export interface OptimizeBundle {
  as_of: string
  optimize_for: 'ongoing' | 'year1'
  max_cards: number
  reward_preferences: string[]
  confirmed_usage: string[]
  /** Derived, not user input: airline/hotel usage keys treated as usable
   * because the matching reward kind is in reward_preferences. */
  assumed_usage: string[]
  accepts_brand_lockin: boolean
  cpp_table: Record<string, { floor_cpp: number; optimistic_cpp: number; avg_cpp: number }>
  policy_constants: Record<string, unknown>
  cards_total: number
  cards_eligible: number
  card_variants: number
  card_variants_pruned: number
  pruned: { id: string; reason: string }[]
  excluded: { id: string; reason: string }[]
  best_by_size: BestBySize[]
  portfolios: Portfolio[]
}
