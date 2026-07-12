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
      <path d="M17.8 19.2 16 11l3.5-3.5a2.12 2.12 0 0 0-3-3L13 8 4.8 6.2a1 1 0 0 0-.9 1.7l4.1 3.1-2.3 2.3-2-.5a1 1 0 0 0-.9 1.6L5 18l1.6 2.4a1 1 0 0 0 1.6-.1l2.3-2 3.1 4.1a1 1 0 0 0 1.7-.9z" />
    </svg>
  ),
  hotels: (
    <svg {...svg}>
      <path d="M6 22V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v17" />
      <path d="M17 10h2a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4" />
      <path d="M10 8h1M13 8h0M10 12h1M13 12h0M10 16h1M13 16h0" />
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
        perks count without you naming a brand.
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
