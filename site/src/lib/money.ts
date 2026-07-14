/** Integer-cents money math (plan 03 §3.2).
 *
 * Canonical state is INTEGER ANNUAL CENTS per category/merchant, regardless
 * of the display unit. Toggling monthly<->annual converts only what inputs
 * display and never mutates canonical state, so repeated toggling is a no-op,
 * and the carve-out inequality (validation E3) compares exact integers.
 */

export type Unit = 'monthly' | 'annual'

/** Parse a user-typed amount in the given display unit into annual cents.
 * Thousands separators are accepted (inputs display "8,000" when idle).
 * Returns null for blank input, NaN for garbage (surfaced by validation E2). */
export function parseToAnnualCents(text: string, unit: Unit): number | null {
  const trimmed = text.trim().replace(/,/g, '')
  if (trimmed === '') return null
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value < 0) return NaN
  const cents = Math.round(value * 100)
  return unit === 'monthly' ? cents * 12 : cents
}

/** Render annual cents in the given display unit for an idle input field
 * (grouped: "8,000"). */
export function displayFromAnnualCents(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents)) return ''
  const divisor = unit === 'monthly' ? 1200 : 100
  const value = cents / divisor
  return formatNumber(value)
}

/** Render annual cents as a plain editable string ("8000", no grouping) —
 * what the input shows while focused, so typing isn't reformatted mid-edit. */
export function editDisplayFromAnnualCents(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents)) return ''
  const divisor = unit === 'monthly' ? 1200 : 100
  return String(Math.round((cents / divisor) * 100) / 100)
}

/** The grey other-unit annotation ("≈ $667 /mo" beside a yearly entry) —
 * rounded to whole dollars, it's an approximation by design. */
export function otherUnitAnnotation(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents) || cents === 0) return ''
  return unit === 'monthly'
    ? `≈ $${formatNumber(Math.round(cents / 100))} /yr`
    : `≈ $${formatNumber(Math.round(cents / 1200))} /mo`
}

/** main + each positive extra (a "+"-added sub-amount for the same topic). NaN
 * and null and 0 contribute nothing to the sum. Returns `main` untouched when
 * nothing positive is present, so null stays null and a garbage NaN main is
 * still surfaced by validation E2 / rendered as empty. */
export function sumAmount(main: number | null, extras: (number | null)[]): number | null {
  let sum = 0
  let any = false
  for (const c of [main, ...extras]) {
    if (c !== null && !Number.isNaN(c) && c > 0) {
      sum += c
      any = true
    }
  }
  return any ? sum : main
}

/** Fold each key's main amount together with its extra sub-amounts into one
 * per-key total, the value the optimizer actually sees. Keys present only in
 * `extras` are included. */
export function foldCents(
  main: Record<string, number | null>,
  extras: Record<string, (number | null)[]>,
): Record<string, number | null> {
  const out: Record<string, number | null> = {}
  for (const k of new Set([...Object.keys(main), ...Object.keys(extras)])) {
    out[k] = sumAmount(main[k] ?? null, extras[k] ?? [])
  }
  return out
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
