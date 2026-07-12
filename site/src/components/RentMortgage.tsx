import { useState } from 'react'
import { MoneyInput } from './CategoryRow'
import { otherUnitAnnotation } from '../lib/money'
import { SectionIcon } from './SectionIcon'

/** Rent / mortgage lives in its own block, not the general spending grid,
 * because housing is a special category: normal cards can't earn on it
 * without a ~3% processor fee, so the optimizer only lets a card with an
 * explicit housing reward (Bilt, fee-free through its app) score it. Asking
 * separately keeps the "what a card actually earns you" story honest — a
 * high-rent household is exactly who a Bilt card can win as a standalone
 * pick. The amount still lands in spend.categoryCents.housing, so the rest of
 * the profile machinery is unchanged. */
export function RentMortgage({ cents, onChange }: {
  cents: number | null
  onChange: (cents: number | null) => void
}) {
  const hasHousing = cents !== null && !Number.isNaN(cents) && cents > 0
  const [pays, setPays] = useState(hasHousing)
  // Rent is always entered monthly — the single most natural unit for housing.
  // No unit toggle here (unlike the general spending grid).
  const unit = 'monthly' as const

  return (
    <section className="block has-icon block-accent">
      <SectionIcon name="home" />
      <div className="panel-head">
        <div>
          <h2>Rent or mortgage</h2>
          <p className="why">
            Most cards earn nothing on housing — it can't be charged without a
            fee. A few (like Bilt) pay you fee-free, so if you rent or carry a
            mortgage, that changes which single card is worth the most.
          </p>
        </div>
      </div>
      <div className="chips lg" style={{ marginTop: 6 }}>
        <label className="chip">
          <input
            type="checkbox"
            checked={pays}
            onChange={(e) => {
              setPays(e.target.checked)
              if (!e.target.checked) onChange(null)
            }}
          />
          I pay rent or a mortgage
        </label>
      </div>
      {pays && (
        <div className="cat-row" style={{ marginTop: 14 }}>
          <label htmlFor="cat-housing">How much per month?</label>
          <MoneyInput id="cat-housing" cents={cents} unit={unit} onChange={onChange} />
          <span className="annot">{otherUnitAnnotation(cents, unit)}</span>
          <span className="spacer" />
        </div>
      )}
    </section>
  )
}
