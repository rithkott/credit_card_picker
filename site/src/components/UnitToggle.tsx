import type { Unit } from '../lib/money'

/** Global monthly|annual display toggle. Canonical state is integer annual
 * cents, so toggling only changes what inputs show (plan 03 §3.2). */
export function UnitToggle({ unit, onChange }: { unit: Unit; onChange: (u: Unit) => void }) {
  return (
    <div className="chips" role="radiogroup" aria-label="Amount unit" style={{ marginBottom: '0.6em' }}>
      {(['monthly', 'annual'] as const).map((u) => (
        <label key={u} className="chip">
          <input
            type="radio"
            name="unit"
            checked={unit === u}
            onChange={() => onChange(u)}
          />
          {u === 'monthly' ? 'per month' : 'per year'}
        </label>
      ))}
    </div>
  )
}
