import type { Config } from '../types'

const KIND_LABELS: Record<string, string> = {
  cashback: 'Cash back',
  flights: 'Flights',
  hotels: 'Hotels',
}

/** All kinds checked (the default) = the everything-run; there is no
 * "total value" option (plan 07 addendum 2). */
export function RewardPreferences({ config, kinds, onChange }: {
  config: Config
  kinds: Record<string, boolean>
  onChange: (kind: string, on: boolean) => void
}) {
  return (
    <section className="block">
      <h2>Rewards to prioritize</h2>
      <p className="why">Check all that apply — all three means every kind of value counts.</p>
      <div className="chips">
        {config.reward_kinds.map((kind) => (
          <label key={kind} className="chip">
            <input
              type="checkbox"
              checked={kinds[kind] ?? false}
              onChange={(e) => onChange(kind, e.target.checked)}
            />
            {KIND_LABELS[kind] ?? kind}
          </label>
        ))}
      </div>
    </section>
  )
}
