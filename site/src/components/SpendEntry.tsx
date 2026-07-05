import type { Config } from '../types'
import type { SpendState } from '../lib/validation'
import type { Unit } from '../lib/money'
import { CategoryRow } from './CategoryRow'
import { UnitToggle } from './UnitToggle'

interface Props {
  config: Config
  spend: SpendState
  unit: Unit
  onUnitChange: (u: Unit) => void
  onCategoryChange: (key: string, cents: number | null) => void
  onMerchantChange: (key: string, cents: number | null) => void
}

/** All 13 categories always visible, registry order/labels — the fixed list
 * is a recall checklist (plan 03 §3.1). Merchant carve-outs nest under their
 * parent category rows. */
export function SpendEntry({ config, spend, unit, onUnitChange, onCategoryChange, onMerchantChange }: Props) {
  return (
    <section className="block">
      <h2>Your spending</h2>
      <p className="why">
        Estimate what you actually spend — every category you skip is counted as $0.
      </p>
      <UnitToggle unit={unit} onChange={onUnitChange} />
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
    </section>
  )
}
