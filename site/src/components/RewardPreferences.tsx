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
      <h2>What rewards do you want to prioritize?</h2>
      <p className="why">
        Check all that apply — all three means every kind of value counts. Checking
        flights or hotels also tells us you fly or stay in hotels, so airline and hotel
        perks count without you naming a brand.
      </p>
      <div className="chips lg" style={{ marginTop: 14 }}>
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
