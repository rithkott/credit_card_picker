import type { ConfigCategory, ConfigMerchant } from '../types'
import type { SpendState } from '../lib/validation'
import { formatNumber, otherUnitAnnotation, sumAmount, type Unit } from '../lib/money'
import { MoneyInputGroup } from './CategoryRow'

interface Props {
  category: ConfigCategory
  merchants: ConfigMerchant[]
  spend: SpendState
  unit: Unit
  onMerchantChange: (key: string, cents: number | null) => void
  onMerchantExtrasChange: (key: string, extras: (number | null)[]) => void
}

/** Carve-outs are sub-buckets of their parent category, never additive — the
 * live budget line makes that visually literal (plan 03 §3.3). Amounts fold in
 * their "+"-added sub-amounts, matching the parent category total. */
export function MerchantCarveouts({
  category, merchants, spend, unit, onMerchantChange, onMerchantExtrasChange,
}: Props) {
  const parentFolded = sumAmount(
    spend.categoryCents[category.key] ?? null,
    spend.categoryExtraCents[category.key] ?? [],
  )
  const parentCents = parentFolded !== null && !Number.isNaN(parentFolded) ? parentFolded : 0
  const carvedCents = merchants.reduce((sum, m) => {
    const c = sumAmount(spend.merchantCents[m.key] ?? null, spend.merchantExtraCents[m.key] ?? [])
    return sum + (c !== null && !Number.isNaN(c) && c > 0 ? c : 0)
  }, 0)
  return (
    <div className="carveouts">
      {merchants.map((m) => {
        const cents = spend.merchantCents[m.key] ?? null
        const extras = spend.merchantExtraCents[m.key] ?? []
        const folded = sumAmount(cents, extras)
        return (
          <div className="cat-row" key={m.key}>
            <label htmlFor={`mer-${m.key}`}>{m.label}</label>
            <MoneyInputGroup
              id={`mer-${m.key}`}
              cents={cents}
              extras={extras}
              onChange={(c) => onMerchantChange(m.key, c)}
              onExtrasChange={(e) => onMerchantExtrasChange(m.key, e)}
            />
            <span className="annot">{otherUnitAnnotation(folded, unit)}</span>
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
