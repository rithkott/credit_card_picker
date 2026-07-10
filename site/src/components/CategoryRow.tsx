import { useState } from 'react'
import type { ConfigCategory, ConfigMerchant } from '../types'
import type { SpendState } from '../lib/validation'
import {
  displayFromAnnualCents, editDisplayFromAnnualCents, otherUnitAnnotation,
  parseToAnnualCents, type Unit,
} from '../lib/money'
import { MerchantCarveouts } from './MerchantCarveouts'

/** Merchant name without its parenthetical/domain qualifier — the closed
 * disclosure lists every merchant it holds ("break out Costco, Whole Foods
 * Market"), so users know the options exist before clicking. */
function shortLabel(label: string): string {
  return label.replace(/\s*\(.*\)$/, '').replace(/\.com$/, '')
}

/** $-prefixed amount field. Canonical state stays integer annual cents. Idle,
 * the field shows the grouped display ("8,000"); while focused it holds the
 * raw text being typed, so grouping never reformats mid-edit. */
export function MoneyInput({ id, cents, unit, onChange }: {
  id: string
  cents: number | null
  unit: Unit
  onChange: (cents: number | null) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const empty = cents === null || Number.isNaN(cents) || cents === 0
  return (
    <div className={`money-input${empty ? ' empty' : ''}`}>
      <span className="prefix">$</span>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={draft ?? displayFromAnnualCents(cents, unit)}
        onFocus={() => setDraft(editDisplayFromAnnualCents(cents, unit))}
        onBlur={() => setDraft(null)}
        onChange={(e) => {
          setDraft(e.target.value)
          onChange(parseToAnnualCents(e.target.value, unit))
        }}
        placeholder="0"
      />
    </div>
  )
}

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
  const empty = cents === null || Number.isNaN(cents) || cents === 0
  return (
    <div className={`cat-row${empty ? ' empty' : ''}`}>
      <label htmlFor={`cat-${category.key}`}>{category.label}</label>
      <MoneyInput
        id={`cat-${category.key}`}
        cents={cents}
        unit={unit}
        onChange={(c) => onCategoryChange(category.key, c)}
      />
      <span className="annot">{otherUnitAnnotation(cents, unit)}</span>
      {merchants.length > 0 ? (
        <button type="button" className="linklike disclose" onClick={() => setOpen(!open)}>
          {open
            ? '▾ hide merchants'
            : `▸ break out ${merchants.map((m) => shortLabel(m.label)).join(', ')}`}
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
