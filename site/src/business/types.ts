/** TS mirrors of the BUSINESS server contract (server/business_api.py) —
 * plan 22D scaffold for the 22E business frontend.
 *
 * BusinessConfig mirrors GET /api/business/config; BusinessOptimizeBundle
 * mirrors the output of scripts/optimize_business.py run() returned verbatim
 * by POST /api/business/optimize (evaluate / suggest-addition return the same
 * shape, suggest-addition adding `added_card`).
 * Per CLAUDE.md's contract rule applied to the business pair: changes to the
 * business engine's bundle shape, /api/business/* response shapes, or its
 * TIER_ORDER / USER_DEFAULTS / COMPANY_DEFAULTS / PERSONAL_DEFAULTS /
 * PERSONAL_GATEWAYS / REWARD_KINDS constants must update this file and
 * tests/test_business_server_api.py in the same change.
 *
 * The consumer site/src/types.ts is untouched — the two apps share no code.
 */

export interface ConfigCategory { key: string; label: string }
export interface ConfigMerchant { key: string; label: string; category: string }
export interface UsageItem { key: string; label: string }
export interface UsageGroup {
  key: string
  label: string
  prompt: string
  /** Brand-loyalty groups (airlines → 'flights', hotels → 'hotels'): items
   * assumed usable when the kind is in reward_preferences. */
  assumed_reward_kind: string | null
  items: UsageItem[]
}

/** Issuer application rules (data/business/meta/issuer-rules.yaml) — the
 * personal↔business interaction model's inputs, surfaced for UI hints. */
export interface IssuerRules {
  gate_524: boolean
  adds_to_524: boolean
  adds_to_524_exceptions: string[]
  credit_card_limit: number | null
  charge_exempt: boolean
  once_per_lifetime_bonus: boolean
  velocity_note: string | null
}

export type EntityType = 'sole_prop' | 'llc' | 'corp'
export type FicoTier = 'good' | 'very_good' | 'excellent'
export type PaymentType = 'revolving' | 'charge'
export type OptimizeFor = 'ongoing' | 'year1'

export interface BusinessConfig {
  categories: ConfigCategory[]
  merchants: ConfigMerchant[]
  usage_questions: UsageGroup[]
  issuer_rules: Record<string, IssuerRules>
  tier_order: FicoTier[]
  entity_types: EntityType[]
  /** Personal premium cards the owner may hold → the program each gateways. */
  personal_gateways: Record<string, string>
  user_defaults: {
    max_cards: number
    optimize_for: OptimizeFor
    accepts_brand_lockin: boolean
    confirmed_usage: string[]
    reward_preferences: string[]
  }
  company_defaults: {
    owner_fico_tier: FicoTier | null
    cash_balance_usd: number
    annual_revenue_usd: number
    has_funding: boolean
    employee_card_seats: number
    large_txn_share: number
  }
  personal_defaults: {
    five24_count: number
    amex_credit_cards: number
    premium_cards_held: string[]
  }
  reward_kinds: string[]
  max_cards_range: [number, number]
  cards_total: number
  data_last_verified: string | null
}

/** GET /api/business/cards — one row per business card file. */
export interface BusinessCardSummary {
  id: string
  name: string
  issuer: string
  network: string | null
  availability: 'active' | 'discontinued'
  pricing: {
    model: 'annual_fee' | 'per_seat'
    annual_fee_usd: number | null
    first_year_waived: boolean
    fee_refund_spend_usd: number | null
    per_seat_monthly_usd: number | null
    free_tier: boolean | null
  }
  business_approval: {
    personal_guarantee: boolean
    min_personal_fico_tier: FicoTier | null
    entity_types: EntityType[]
    requires_ein: boolean
    min_cash_balance_usd: number | null
    min_annual_revenue_usd: number | null
    funding_qualifies: boolean
  }
  employee_cards: { fee_usd: number; controls: string[] }
  payment_type: PaymentType | null
  integrations: string[]
  virtual_cards: boolean
  currency: { type: 'cash' | 'points'; program: string; program_label: string }
  base_rate: number | null
  verification: {
    last_verified_date: string | null
    confidence: 'low' | 'medium' | 'high' | null
    verified_by: string | null
  }
}

export interface BusinessCards { cards: BusinessCardSummary[]; total: number }

/** GET /api/business/assumptions — the business valuation table. */
export interface AssumptionProgram {
  key: string
  label: string
  redeems_for: string[]
  floor_cpp: number
  optimistic_cpp: number
  transfer_gateway_required: boolean
  loyalty_keys: string[]
}
export interface BusinessAssumptions { programs: AssumptionProgram[] }

/** POST /api/business/optimize request body (profile contract of
 * parse_business_profile — the server is the single validator). */
export interface BusinessProfileRequest {
  spend: Record<string, number>
  merchant_spend?: Record<string, number>
  company: {
    entity_type: EntityType
    accepts_personal_guarantee: boolean
    owner_fico_tier?: FicoTier | null
    has_ein?: boolean
    cash_balance_usd?: number
    annual_revenue_usd?: number
    has_funding?: boolean
    employee_card_seats?: number
    /** 0..1 — fraction of spend in single transactions ≥ ~$5k (prices
     * min-transaction and large-purchase reward lines). */
    large_txn_share?: number
  }
  personal?: {
    five24_count?: number
    amex_credit_cards?: number
    premium_cards_held?: string[]
  }
  user?: {
    max_cards?: number
    optimize_for?: OptimizeFor
    reward_preferences?: string[]
    accepts_brand_lockin?: boolean
    confirmed_usage?: string[]
  }
  exclude_cards?: string[]
  as_of?: string
  top?: number
}

/** Evaluate / suggest-addition add the hand-picked (held) id list. */
export interface BusinessEvaluateRequest extends BusinessProfileRequest {
  cards: string[]
}

// ---------------------------------------------------------------------------
// Bundle (run/evaluate/augment output)
// ---------------------------------------------------------------------------

export interface Assignment {
  bucket: string
  usd_assigned: number
  rate: number
  cpp: number
  usd_value: number
  note: string
  /** Present on min-transaction / large-purchase lines: the large_txn_share
   * fraction that priced the line. */
  eligible_fraction?: number
}

export interface CreditLine {
  name: string
  value: number
  note: string
  potential_value?: number
  disclaimer?: string
}

export interface BonusResult { value: number; note: string; floor_value: number }

export interface CardFees {
  annual_fee_usd: number
  first_year_waived: boolean
  seat_fees_usd: number
  fee_refunded: boolean
  ongoing_usd: number
  year1_usd: number
  notes: string[]
}

export interface PortfolioCard {
  name: string
  currency: { kind: 'cash' | 'points'; program: string; label: string }
  assignments: Assignment[]
  credits: CreditLine[]
  bonus: BonusResult
  fees: CardFees
  payment_type: PaymentType | null
  integrations: string[]
  virtual_cards: boolean
  warnings: string[]
  valuation_note?: string
  pairing_note?: string
  reward_cap_clamp?: number
}

export interface FloatSummary {
  cards: { card_id: string; grace_days: number; note: string }[]
  spend_weighted_avg_days: number | null
}

export interface Portfolio {
  cards: string[]
  ongoing_net: number
  year1_net: number
  earnings: number
  /** Headline blended earn rate: spend earnings ÷ total profile spend, % —
   * the number a CFO compares to a flat 2% card. Null on zero spend. */
  blended_rate_pct: number | null
  /** The card carrying the most assigned spend — employee seats are assumed
   * equipped there (SEAT_PLACEMENT policy). */
  workhorse_card: string
  float_days: FloatSummary
  /** Informational velocity / 5-24 / once-per-lifetime sequencing hints —
   * never constraints. */
  application_notes: string[]
  unassigned_spend: Record<string, number>
  unassigned_notes?: Record<string, string>
  per_card: Record<string, PortfolioCard>
}

export interface SizedPortfolio extends Portfolio { size: number }

export interface CppTableEntry {
  floor_cpp: number
  optimistic_cpp: number
  avg_cpp: number
}

export interface ExcludedCard { id: string; reason: string }

export interface BusinessOptimizeBundle {
  as_of: string
  optimize_for: OptimizeFor
  max_cards: number
  reward_preferences: string[]
  confirmed_usage: string[]
  assumed_usage: string[]
  accepts_brand_lockin: boolean
  company: Record<string, unknown>
  personal: Record<string, unknown>
  cpp_table: Record<string, CppTableEntry>
  policy_constants: Record<string, unknown>
  cards_total: number
  cards_eligible: number
  excluded: ExcludedCard[]
  best_by_size: SizedPortfolio[]
  portfolios: Portfolio[]
  /** Only on suggest-addition responses. */
  added_card?: string
}
