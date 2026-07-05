/** Integer-cents money math (plan 03 §3.2).
 *
 * Canonical state is INTEGER ANNUAL CENTS per category/merchant, regardless
 * of the display unit. Toggling monthly<->annual converts only what inputs
 * display and never mutates canonical state, so repeated toggling is a no-op,
 * and the carve-out inequality (validation E3) compares exact integers.
 */

export type Unit = 'monthly' | 'annual'

/** Parse a user-typed amount in the given display unit into annual cents.
 * Returns null for blank input, NaN for garbage (surfaced by validation E2). */
export function parseToAnnualCents(text: string, unit: Unit): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value < 0) return NaN
  const cents = Math.round(value * 100)
  return unit === 'monthly' ? cents * 12 : cents
}

/** Render annual cents in the given display unit for an input field. */
export function displayFromAnnualCents(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents)) return ''
  const divisor = unit === 'monthly' ? 1200 : 100
  const value = cents / divisor
  return formatNumber(value)
}

/** The grey other-unit annotation ("≈ $8,000/yr" under a monthly entry). */
export function otherUnitAnnotation(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents) || cents === 0) return ''
  return unit === 'monthly'
    ? `≈ $${formatNumber(cents / 100)}/yr`
    : `≈ $${formatNumber(cents / 1200)}/mo`
}

/** Annual cents -> the number sent in the profile: integer when whole,
 * two decimals otherwise (8000, not 8000.0; 641.67, never 641.6700000001). */
export function centsToDollars(cents: number): number {
  return cents % 100 === 0 ? cents / 100 : Math.round(cents) / 100
}

export function formatNumber(value: number): string {
  const rounded = Math.round(value * 100) / 100
  return Number.isInteger(rounded)
    ? rounded.toLocaleString('en-US')
    : rounded.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function formatUsd(value: number): string {
  const sign = value < 0 ? '-' : ''
  return `${sign}$${Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}
