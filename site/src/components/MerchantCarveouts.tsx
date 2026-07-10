import type { ConfigCategory, ConfigMerchant } from '../types'
import type { SpendState } from '../lib/validation'
import { formatNumber, otherUnitAnnotation, type Unit } from '../lib/money'
import { MoneyInput } from './CategoryRow'

interface Props {
  category: ConfigCategory
  merchants: ConfigMerchant[]
  spend: SpendState
  unit: Unit
  onMerchantChange: (key: string, cents: number | null) => void
}

/** Carve-outs are sub-buckets of their parent category, never additive — the
 * live budget line makes that visually literal (plan 03 §3.3). */
export function MerchantCarveouts({ category, merchants, spend, unit, onMerchantChange }: Props) {
  const parent = spend.categoryCents[category.key]
  const parentCents = parent !== null && parent !== undefined && !Number.isNaN(parent) ? parent : 0
  const carvedCents = merchants.reduce((sum, m) => {
    const c = spend.merchantCents[m.key]
    return sum + (c !== null && c !== undefined && !Number.isNaN(c) && c > 0 ? c : 0)
  }, 0)
  return (
    <div className="carveouts">
      {merchants.map((m) => {
        const cents = spend.merchantCents[m.key] ?? null
        return (
          <div className="cat-row" key={m.key}>
            <label htmlFor={`mer-${m.key}`}>{m.label}</label>
            <MoneyInput
              id={`mer-${m.key}`}
              cents={cents}
              unit={unit}
              onChange={(c) => onMerchantChange(m.key, c)}
            />
            <span className="annot">{otherUnitAnnotation(cents, unit)}</span>
          </div>
        )
      })}
      <div className="budget">
        carve-outs ${formatNumber(carvedCents / 100)} of ${formatNumber(parentCents / 100)}{' '}
        {category.label.replace(/\s*\(.*\)$/, '').split(' / ')[0].toLowerCase()}
        {' '}— part of the total, not added to it
      </div>
    </div>
  )
}
