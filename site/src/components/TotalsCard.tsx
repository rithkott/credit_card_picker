import type { SpendState, Issue } from '../lib/validation'
import { formatNumber } from '../lib/money'

/** Always annual regardless of the unit toggle; carve-outs excluded (they are
 * already inside their parents) — plan 03 §3.5. */
export function TotalsCard({ spend, warnings, categoryCount }: {
  spend: SpendState
  warnings: Issue[]
  categoryCount: number
}) {
  const totalCents = Object.values(spend.categoryCents)
    .reduce<number>((sum, c) => sum + (c !== null && !Number.isNaN(c) && c > 0 ? c : 0), 0)
  const nonzero = Object.values(spend.categoryCents)
    .filter((c) => c !== null && !Number.isNaN(c) && c > 0).length
  return (
    <section className="block">
      <div className="totals">
        <span className="big">${formatNumber(totalCents / 100)}/yr</span>
        <span className="muted">≈ ${formatNumber(totalCents / 1200)}/mo</span>
        <span className="muted">{nonzero} of {categoryCount} categories</span>
      </div>
      {warnings.map((w) => (
        <div key={w.code} className="issue warning">⚠ {w.message}</div>
      ))}
    </section>
  )
}
