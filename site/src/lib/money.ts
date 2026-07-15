/** Integer-cents money math (plan 03 §3.2).
 *
 * Canonical state is INTEGER CENTS in whatever unit the toggle is currently
 * showing (monthly or annual) — the raw number the user typed, never rescaled.
 * Toggling monthly<->annual re-labels the amounts but does NOT touch state, so
 * the digits on screen never jump. Conversion to annual happens once, at the
 * profile boundary (see lib/profile.ts). The carve-out inequality (validation
 * E3) compares merchant vs. category in the same unit, so it stays exact.
 */

export type Unit = 'monthly' | 'annual'

/** Parse a user-typed amount into integer cents (in the current display unit).
 * Thousands separators are accepted (inputs display "8,000" when idle).
 * Returns null for blank input, NaN for garbage (surfaced by validation E2). */
export function parseCents(text: string): number | null {
  const trimmed = text.trim().replace(/,/g, '')
  if (trimmed === '') return null
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value < 0) return NaN
  return Math.round(value * 100)
}

/** Render cents for an idle input field (grouped: "8,000"). The stored cents
 * are already in the display unit, so no unit conversion happens here. */
export function displayCents(cents: number | null): string {
  if (cents === null || Number.isNaN(cents)) return ''
  return formatNumber(cents / 100)
}

/** Render cents as a plain editable string ("8000", no grouping) — what the
 * input shows while focused, so typing isn't reformatted mid-edit. */
export function editDisplayCents(cents: number | null): string {
  if (cents === null || Number.isNaN(cents)) return ''
  return String(Math.round(cents) / 100)
}

/** The grey other-unit annotation ("≈ $667 /mo" beside a yearly entry) —
 * rounded to whole dollars, it's an approximation by design. `cents` are in
 * the current display `unit`; the annotation shows the *other* unit. */
export function otherUnitAnnotation(cents: number | null, unit: Unit): string {
  if (cents === null || Number.isNaN(cents) || cents === 0) return ''
  return unit === 'monthly'
    ? `≈ $${formatNumber(Math.round((cents * 12) / 100))} /yr`
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
