import type { Config } from '../types'
import type { Issue, SpendState } from '../lib/validation'
import { formatNumber, sumAmount, type Unit } from '../lib/money'
import { SectionIcon } from './SectionIcon'
import { CategoryRow } from './CategoryRow'
import { UnitToggle } from './UnitToggle'

interface Props {
  config: Config
  spend: SpendState
  unit: Unit
  warnings: Issue[]
  onUnitChange: (u: Unit) => void
  onCategoryChange: (key: string, cents: number | null) => void
  onCategoryExtrasChange: (key: string, extras: (number | null)[]) => void
  onMerchantChange: (key: string, cents: number | null) => void
  onMerchantExtrasChange: (key: string, extras: (number | null)[]) => void
}

/** Every real spend category always visible, registry order/labels — the fixed
 * list is a recall checklist (plan 03 §3.1). Housing (rent/mortgage) is the one
 * exception: it's an explicit_only category asked in its own RentMortgage block,
 * so it's filtered out here and out of these totals. Merchant carve-outs nest
 * under their parent category rows. The totals row lives in this panel's footer
 * (always annual regardless of the unit toggle; carve-outs excluded — they are
 * already inside their parents, plan 03 §3.5). */
export function SpendEntry({
  config, spend, unit, warnings, onUnitChange,
  onCategoryChange, onCategoryExtrasChange, onMerchantChange, onMerchantExtrasChange,
}: Props) {
  const categories = config.categories.filter((c) => c.key !== 'housing')
  const gridCents = categories.map((c) =>
    sumAmount(spend.categoryCents[c.key] ?? null, spend.categoryExtraCents[c.key] ?? []))
  const enteredCents = gridCents
    .reduce<number>((sum, c) => sum + (c !== null && !Number.isNaN(c) && c > 0 ? c : 0), 0)
  // Footer total is always annual regardless of the toggle; stored cents are in
  // the current unit, so monthly entries are annualized here for the /yr figure.
  const annualCents = unit === 'monthly' ? enteredCents * 12 : enteredCents
  const nonzero = gridCents
    .filter((c) => c !== null && !Number.isNaN(c) && c > 0).length
  return (
    <section className="block has-icon">
      <SectionIcon name="spend" />
      <div className="panel-head">
        <div>
          <h2>Your spending</h2>
          <p className="why">Estimates are fine. Anything you skip counts as $0.</p>
        </div>
        <span className="spacer" />
        <UnitToggle unit={unit} onChange={onUnitChange} />
      </div>
      <div className="spend-help">
        <strong>Where to find this:</strong> pull up your spending in your bank or
        credit-card website or app — most show yearly or monthly totals broken out by
        category. Enter each as accurately as you can. If a category here doesn't match
        the labels your bank uses, make your best guess as to which one the spending
        belongs in.
      </div>
      <div className="spend-rows">
        {categories.map((cat) => (
          <CategoryRow
            key={cat.key}
            category={cat}
            merchants={config.merchants.filter((m) => m.category === cat.key)}
            spend={spend}
            unit={unit}
            onCategoryChange={onCategoryChange}
            onCategoryExtrasChange={onCategoryExtrasChange}
            onMerchantChange={onMerchantChange}
            onMerchantExtrasChange={onMerchantExtrasChange}
          />
        ))}
      </div>
      <div className="spend-foot">
        <span className="big">
          ${formatNumber(annualCents / 100)}<span className="unit"> /yr</span>
        </span>
        <span className="muted">≈ ${formatNumber(Math.round(annualCents / 1200))} /mo</span>
        <span className="spacer" />
        <span className="muted">
          {nonzero} of {categories.length} categories · skipped categories count $0
        </span>
      </div>
      {warnings.map((w) => (
        <div key={w.code} className="issue warning">⚠ {w.message}</div>
      ))}
    </section>
  )
}
