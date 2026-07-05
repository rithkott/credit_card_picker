/** Client-side validation — an EXACT mirror of parse_profile/validate_user in
 * scripts/optimize.py, never a superset (plan 03 §4): the form must not block
 * any profile the optimizer would accept. Per CLAUDE.md, changes to
 * parse_profile's contract must update this file in the same change.
 *
 *   E1  at least one category > 0        (spend must be a non-empty mapping)
 *   E2  every amount finite and >= 0     (_require_number)
 *   E3  per category, carve-outs <= parent, compared in integer cents
 *   E4  credit_tier selected             (user.credit_tier is required)
 *   E5  at least one reward kind checked (reward_preferences non-empty)
 *   W1  'other' is 0 while other categories are nonzero — nudge, non-blocking
 */

import type { ConfigMerchant } from '../types'
import { formatNumber } from './money'

export interface SpendState {
  categoryCents: Record<string, number | null>
  merchantCents: Record<string, number | null>
}

export interface Issue { code: string; message: string }

export function validate(
  spend: SpendState,
  merchants: ConfigMerchant[],
  creditTier: string | null,
  rewardKinds: Record<string, boolean>,
  categoryLabels: Record<string, string>,
): { errors: Issue[]; warnings: Issue[] } {
  const errors: Issue[] = []
  const warnings: Issue[] = []

  const cents = Object.values(spend.categoryCents)
  if (!cents.some((c) => c !== null && !Number.isNaN(c) && c > 0)) {
    errors.push({ code: 'E1', message: 'Enter at least one category with spend > $0.' })
  }

  const bad = [...Object.values(spend.categoryCents), ...Object.values(spend.merchantCents)]
    .some((c) => c !== null && Number.isNaN(c))
  if (bad) {
    errors.push({ code: 'E2', message: 'Every amount must be a number ≥ 0.' })
  }

  // E3: per parent category, carve-out sum <= category amount (integer cents).
  const carved: Record<string, number> = {}
  for (const m of merchants) {
    const c = spend.merchantCents[m.key]
    if (c !== null && c !== undefined && !Number.isNaN(c) && c > 0) {
      carved[m.category] = (carved[m.category] ?? 0) + c
    }
  }
  for (const [cat, total] of Object.entries(carved)) {
    const parent = spend.categoryCents[cat]
    const parentCents = parent !== null && parent !== undefined && !Number.isNaN(parent) ? parent : 0
    if (total > parentCents) {
      const label = categoryLabels[cat] ?? cat
      errors.push({
        code: 'E3',
        message:
          `Merchant carve-outs total $${formatNumber(total / 100)} but ` +
          `${label} is $${formatNumber(parentCents / 100)} — enter the full ` +
          `${label} total first; carve-outs are counted inside it, not in addition.`,
      })
    }
  }

  if (!creditTier) {
    errors.push({ code: 'E4', message: 'Select your credit tier — it gates which cards you can be approved for.' })
  }

  if (!Object.values(rewardKinds).some(Boolean)) {
    errors.push({ code: 'E5', message: 'Check at least one reward kind (cash back, flights, hotels).' })
  }

  const other = spend.categoryCents['other']
  const anyNonzero = Object.entries(spend.categoryCents)
    .some(([k, c]) => k !== 'other' && c !== null && !Number.isNaN(c!) && c! > 0)
  if (anyNonzero && (other === null || other === 0)) {
    warnings.push({
      code: 'W1',
      message:
        '"Everything else" is $0 — that spend is where flat-rate cards earn, ' +
        'so leaving it empty usually understates the portfolio.',
    })
  }

  return { errors, warnings }
}
