import { useState } from 'react'
import type { ConfigCategory, ConfigMerchant } from '../types'
import type { SpendState } from '../lib/validation'
import {
  displayCents, editDisplayCents, otherUnitAnnotation,
  parseCents, sumAmount, type Unit,
} from '../lib/money'
import { MerchantCarveouts } from './MerchantCarveouts'

/** Merchant name without its parenthetical/domain qualifier — the closed
 * disclosure lists every merchant it holds ("break out Costco, Whole Foods
 * Market"), so users know the options exist before clicking. */
function shortLabel(label: string): string {
  return label.replace(/\s*\(.*\)$/, '').replace(/\.com$/, '')
}

/** $-prefixed amount field. Canonical state is integer cents in the current
 * display unit (never rescaled by the toggle). Idle, the field shows the
 * grouped display ("8,000"); while focused it holds the raw text being typed,
 * so grouping never reformats mid-edit. */
export function MoneyInput({ id, cents, onChange }: {
  id: string
  cents: number | null
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
        value={draft ?? displayCents(cents)}
        onFocus={() => setDraft(editDisplayCents(cents))}
        onBlur={() => setDraft(null)}
        onChange={(e) => {
          setDraft(e.target.value)
          onChange(parseCents(e.target.value))
        }}
        placeholder="0"
      />
    </div>
  )
}

/** A MoneyInput plus a "+" that adds extra sub-amounts for the same topic
 * (e.g. the same category spent across two cards). The extras sum into the
 * topic total everywhere downstream; here they just render as stacked wells
 * with a running "= $X total" line. The main field's value stays the raw main
 * amount — folding happens in the parent's annot and in validation/profile. */
export function MoneyInputGroup({ id, cents, extras, onChange, onExtrasChange }: {
  id: string
  cents: number | null
  extras: (number | null)[]
  onChange: (cents: number | null) => void
  onExtrasChange: (extras: (number | null)[]) => void
}) {
  const total = sumAmount(cents, extras)
  return (
    <div className="money-group">
      <div className="money-row">
        <MoneyInput id={id} cents={cents} onChange={onChange} />
        <button
          type="button"
          className="add-sub"
          title="Add another amount (e.g. the same spend on a second card or account)"
          aria-label="Add another amount"
          onClick={() => onExtrasChange([...extras, null])}
        >
          +
        </button>
      </div>
      {extras.map((c, i) => (
        <div className="money-row sub" key={i}>
          <MoneyInput
            id={`${id}-x${i}`}
            cents={c}
            onChange={(v) => onExtrasChange(extras.map((e, idx) => (idx === i ? v : e)))}
          />
          <button
            type="button"
            className="rm-sub"
            title="Remove this amount"
            aria-label="Remove this amount"
            onClick={() => onExtrasChange(extras.filter((_, idx) => idx !== i))}
          >
            ×
          </button>
        </div>
      ))}
      {extras.length > 0 && (
        <div className="group-total">= ${displayCents(total)} total</div>
      )}
    </div>
  )
}

interface Props {
  category: ConfigCategory
  merchants: ConfigMerchant[]
  spend: SpendState
  unit: Unit
  onCategoryChange: (key: string, cents: number | null) => void
  onCategoryExtrasChange: (key: string, extras: (number | null)[]) => void
  onMerchantChange: (key: string, cents: number | null) => void
  onMerchantExtrasChange: (key: string, extras: (number | null)[]) => void
}

export function CategoryRow({
  category, merchants, spend, unit,
  onCategoryChange, onCategoryExtrasChange, onMerchantChange, onMerchantExtrasChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const cents = spend.categoryCents[category.key] ?? null
  const extras = spend.categoryExtraCents[category.key] ?? []
  const folded = sumAmount(cents, extras)
  const empty = folded === null || Number.isNaN(folded) || folded === 0
  return (
    <div className={`cat-row${empty ? ' empty' : ''}`}>
      <label htmlFor={`cat-${category.key}`}>{category.label}</label>
      <MoneyInputGroup
        id={`cat-${category.key}`}
        cents={cents}
        extras={extras}
        onChange={(c) => onCategoryChange(category.key, c)}
        onExtrasChange={(e) => onCategoryExtrasChange(category.key, e)}
      />
      <span className="annot">{otherUnitAnnotation(folded, unit)}</span>
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
          onMerchantExtrasChange={onMerchantExtrasChange}
        />
      )}
    </div>
  )
}
