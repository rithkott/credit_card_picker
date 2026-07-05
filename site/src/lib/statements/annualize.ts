/** Date-coverage math and annualization (plan 09, commit 4/5).
 *
 * Statements cover partial periods; category totals scale by 365/coveredDays
 * where coverage is the UNION of per-file date intervals — two files over the
 * same month must not double the divisor, and a gap between statements must
 * not count as covered time. All date math is string/UTC-based (no local
 * timezones).
 */

export interface DateInterval { start: string; end: string }

const dayMs = 24 * 60 * 60 * 1000

function toUTC(iso: string): number {
  return Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
}

export function daysInclusive(startISO: string, endISO: string): number {
  return Math.round((toUTC(endISO) - toUTC(startISO)) / dayMs) + 1
}

/** Union length of the intervals in days, plus whether any two overlapped
 * (a review-screen warning: overlapping statements usually mean two exports
 * of the same account and possibly double-counted spend). */
export function mergeIntervals(intervals: DateInterval[]): { days: number; overlaps: boolean } {
  const valid = intervals
    .filter((i) => i.start !== '' && i.end !== '' && i.start <= i.end)
    .sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0))
  if (valid.length === 0) return { days: 0, overlaps: false }

  let days = 0
  let overlaps = false
  let curStart = valid[0].start
  let curEnd = valid[0].end
  for (const iv of valid.slice(1)) {
    if (iv.start <= curEnd) {
      overlaps = true
      if (iv.end > curEnd) curEnd = iv.end
    } else {
      days += daysInclusive(curStart, curEnd)
      curStart = iv.start
      curEnd = iv.end
    }
  }
  days += daysInclusive(curStart, curEnd)
  return { days, overlaps }
}

/** Scale raw covered-period cents to a year. Math.round is monotonic, so for
 * carve-out C <= parent P, round(C*f) <= round(P*f) — imported values can
 * never violate the form's E3 carve-out invariant. */
export function annualize(rawCents: number, coveredDays: number): number {
  return Math.round((rawCents * 365) / Math.max(1, coveredDays))
}

/** Below this coverage, annualizing is mostly extrapolation noise. */
export const MIN_COVERAGE_DAYS = 60
