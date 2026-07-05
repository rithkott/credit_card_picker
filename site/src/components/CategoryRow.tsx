import { useState } from 'react'
import type { ConfigCategory, ConfigMerchant } from '../types'
import type { SpendState } from '../lib/validation'
import { displayFromAnnualCents, otherUnitAnnotation, parseToAnnualCents, type Unit } from '../lib/money'
import { MerchantCarveouts } from './MerchantCarveouts'

interface Props {
  category: ConfigCategory
  merchants: ConfigMerchant[]
  spend: SpendState
  unit: Unit
  onCategoryChange: (key: string, cents: number | null) => void
  onMerchantChange: (key: string, cents: number | null) => void
}

export function CategoryRow({ category, merchants, spend, unit, onCategoryChange, onMerchantChange }: Props) {
  const [open, setOpen] = useState(false)
  const cents = spend.categoryCents[category.key] ?? null
  return (
    <div className="cat-row">
      <label htmlFor={`cat-${category.key}`}>{category.label}</label>
      <input
        id={`cat-${category.key}`}
        type="number"
        min="0"
        step="any"
        inputMode="decimal"
        value={displayFromAnnualCents(cents, unit)}
        onChange={(e) => onCategoryChange(category.key, parseToAnnualCents(e.target.value, unit))}
        placeholder="0"
      />
      <span className="annot">{otherUnitAnnotation(cents, unit)}</span>
      {merchants.length > 0 ? (
        <button type="button" className="disclose" onClick={() => setOpen(!open)}>
          {open ? '▾ hide merchants' : '▸ break out specific merchants'}
        </button>
      ) : (
        <span />
      )}
      {open && merchants.length > 0 && (
        <MerchantCarveouts
          category={category}
          merchants={merchants}
          spend={spend}
          unit={unit}
          onMerchantChange={onMerchantChange}
        />
      )}
    </div>
  )
}
