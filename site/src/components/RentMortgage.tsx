import { MoneyInputGroup } from './CategoryRow'
import { otherUnitAnnotation, sumAmount } from '../lib/money'
import { SectionIcon } from './SectionIcon'

/** Rent / mortgage lives in its own block, not the general spending grid,
 * because housing is a special category: normal cards can't earn on it
 * without a ~3% processor fee, so the optimizer only lets a card with an
 * explicit housing reward (Bilt, fee-free through its app) score it. Asking
 * separately keeps the "what a card actually earns you" story honest — a
 * high-rent household is exactly who a Bilt card can win as a standalone
 * pick. The amount still lands in spend.categoryCents.housing, so the rest of
 * the profile machinery is unchanged. */
export function RentMortgage({ cents, extras, onChange, onExtrasChange }: {
  cents: number | null
  extras: (number | null)[]
  onChange: (cents: number | null) => void
  onExtrasChange: (extras: (number | null)[]) => void
}) {
  // Rent is always entered monthly — the single most natural unit for housing.
  // No unit toggle here (unlike the general spending grid).
  const unit = 'monthly' as const
  const folded = sumAmount(cents, extras)

  return (
    <section className="block has-icon block-accent">
      <SectionIcon name="home" />
      <div className="panel-head">
        <div>
          <h2>Rent or mortgage</h2>
          <p className="why">
            Most cards earn <strong>nothing</strong> on housing. A few (like Bilt)
            pay you <strong className="why-emph">fee-free</strong> — that can change
            which card wins.
          </p>
        </div>
      </div>
      <div className="cat-row" style={{ marginTop: 14 }}>
        <label htmlFor="cat-housing">How much per month?</label>
        <MoneyInputGroup
          id="cat-housing"
          cents={cents}
          extras={extras}
          onChange={onChange}
          onExtrasChange={onExtrasChange}
        />
        <span className="annot">{otherUnitAnnotation(folded, unit)}</span>
        <span className="spacer" />
      </div>
    </section>
  )
}
