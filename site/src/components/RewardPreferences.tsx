import type { ReactNode } from 'react'
import type { Config } from '../types'
import { SectionIcon } from './SectionIcon'

const KIND_LABELS: Record<string, string> = {
  cashback: 'Cash back',
  flights: 'Flights',
  hotels: 'Hotels',
}

const svg = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/** Large square-tile icons for each reward kind (v1.9.0). */
const KIND_ICONS: Record<string, ReactNode> = {
  cashback: (
    <svg {...svg}>
      <line x1="12" y1="2.5" x2="12" y2="21.5" />
      <path d="M17 5.5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  ),
  flights: (
    <svg {...svg}>
      <path d="M2 22h20" />
      <path d="M6.36 17.4 4 17l-2-4 1.1-.55a2 2 0 0 1 1.8 0l.17.1a2 2 0 0 0 1.8 0L8 12 5 6l.9-.45a2 2 0 0 1 2.09.2l4.02 3a2 2 0 0 0 .9.42l4.9.98a2.06 2.06 0 0 1 1.66 1.51 1.91 1.91 0 0 1-1.55 2.3l-11.24 2a2 2 0 0 1-1.02-.06z" />
    </svg>
  ),
  hotels: (
    <svg {...svg}>
      <path d="M2 4v16" />
      <path d="M2 8h18a2 2 0 0 1 2 2v10" />
      <path d="M2 17h20" />
      <path d="M6 8v9" />
    </svg>
  ),
}

/** All kinds checked (the default) = the everything-run; there is no
 * "total value" option (plan 07 addendum 2). */
export function RewardPreferences({ config, kinds, onChange }: {
  config: Config
  kinds: Record<string, boolean>
  onChange: (kind: string, on: boolean) => void
}) {
  return (
    <section className="block has-icon">
      <SectionIcon name="rewards" />
      <h2>What rewards do you want to prioritize?</h2>
      <p className="why">
        Check all that apply — all three means every kind of value counts. Checking
        flights or hotels also tells us you fly or stay in hotels, so airline and hotel
        perks count without you naming a brand. Points are usually worth more than cash
        back when redeemed directly for flights and hotel stays.
      </p>
      <div
        className="reward-tiles"
        style={{ gridTemplateColumns: `repeat(${config.reward_kinds.length}, 1fr)` }}
      >
        {config.reward_kinds.map((kind) => {
          const on = kinds[kind] ?? false
          return (
            <button
              key={kind}
              type="button"
              role="checkbox"
              aria-checked={on}
              className={`reward-tile${on ? ' active' : ''}`}
              onClick={() => onChange(kind, !on)}
            >
              <span className="reward-tile-icon" aria-hidden="true">
                {KIND_ICONS[kind] ?? KIND_ICONS.cashback}
              </span>
              <span className="reward-tile-label">{KIND_LABELS[kind] ?? kind}</span>
              <span className="reward-tile-check" aria-hidden="true">
                {on ? '✓' : ''}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
