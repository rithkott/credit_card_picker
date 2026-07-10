import type { Unit } from '../lib/money'

/** Global monthly|yearly display toggle, rendered as a segmented pill.
 * Canonical state is integer annual cents, so toggling only changes what
 * inputs show (plan 03 §3.2). */
export function UnitToggle({ unit, onChange }: { unit: Unit; onChange: (u: Unit) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label="Amount unit">
      {(['monthly', 'annual'] as const).map((u) => (
        <label key={u}>
          <input
            type="radio"
            name="unit"
            checked={unit === u}
            onChange={() => onChange(u)}
          />
          {u === 'monthly' ? 'monthly' : 'yearly'}
        </label>
      ))}
    </div>
  )
}
