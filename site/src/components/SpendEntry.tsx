import type { Config } from '../types'
import type { Issue, SpendState } from '../lib/validation'
import { formatNumber, type Unit } from '../lib/money'
import { CategoryRow } from './CategoryRow'
import { UnitToggle } from './UnitToggle'

interface Props {
  config: Config
  spend: SpendState
  unit: Unit
  warnings: Issue[]
  onUnitChange: (u: Unit) => void
  onCategoryChange: (key: string, cents: number | null) => void
  onMerchantChange: (key: string, cents: number | null) => void
}

/** All 13 categories always visible, registry order/labels — the fixed list
 * is a recall checklist (plan 03 §3.1). Merchant carve-outs nest under their
 * parent category rows. The totals row lives in this panel's footer (always
 * annual regardless of the unit toggle; carve-outs excluded — they are
 * already inside their parents, plan 03 §3.5). */
export function SpendEntry({ config, spend, unit, warnings, onUnitChange, onCategoryChange, onMerchantChange }: Props) {
  const totalCents = Object.values(spend.categoryCents)
    .reduce<number>((sum, c) => sum + (c !== null && !Number.isNaN(c) && c > 0 ? c : 0), 0)
  const nonzero = Object.values(spend.categoryCents)
    .filter((c) => c !== null && !Number.isNaN(c) && c > 0).length
  return (
    <section className="block">
      <div className="panel-head">
        <div>
          <h2>Your spending</h2>
          <p className="why">Estimates are fine. Anything you skip counts as $0.</p>
        </div>
        <span className="spacer" />
        <UnitToggle unit={unit} onChange={onUnitChange} />
      </div>
      <div className="spend-rows">
        {config.categories.map((cat) => (
          <CategoryRow
            key={cat.key}
            category={cat}
            merchants={config.merchants.filter((m) => m.category === cat.key)}
            spend={spend}
            unit={unit}
            onCategoryChange={onCategoryChange}
            onMerchantChange={onMerchantChange}
          />
        ))}
      </div>
      <div className="spend-foot">
        <span className="big">
          ${formatNumber(totalCents / 100)}<span className="unit"> /yr</span>
        </span>
        <span className="muted">≈ ${formatNumber(Math.round(totalCents / 1200))} /mo</span>
        <span className="spacer" />
        <span className="muted">
          {nonzero} of {config.categories.length} categories · skipped categories count $0
        </span>
      </div>
      {warnings.map((w) => (
        <div key={w.code} className="issue warning">⚠ {w.message}</div>
      ))}
    </section>
  )
}
