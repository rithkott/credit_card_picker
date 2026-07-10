import type { PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'
import { AssignmentsTable } from './AssignmentsTable'
import { CreditsList } from './CreditsList'

function pretty(bucket: string): string {
  return bucket.replace(/_/g, ' ')
}

/** "groceries, streaming, gas & transit" — the tile's role subtitle, derived
 * from where the optimizer actually routed spend. */
function roleSubtitle(card: PerCard): string {
  const buckets = [...new Set(
    card.assignments.filter((a) => a.usd_assigned > 0).map((a) => pretty(a.bucket)),
  )]
  if (buckets.length === 0) return 'No spend routed here — credits and perks only'
  const shown = buckets.slice(0, 4)
  const text = buckets.length > 4
    ? `${shown.join(', ')} & more`
    : shown.length > 1
      ? `${shown.slice(0, -1).join(', ')} & ${shown[shown.length - 1]}`
      : shown[0]
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Per-card tile (design handoff v2): name, role, the money line items, and
 * an "Adds each year" total — with the existing full AssignmentsTable and
 * credits/bonus detail one disclosure away for power users. */
export function CardDetail({ id, card }: { id: string; card: PerCard }) {
  // Assignment usd_values are pre-clamp; a card-wide reward cap subtracts
  // from earnings (optimize.py reward_cap_clamps) and shows as its own line.
  const earn = card.assignments.reduce((s, a) => s + a.usd_value, 0)
    - (card.reward_cap_clamp ?? 0)
  const credits = card.credits.reduce((s, c) => s + c.value, 0)
  const fees = card.fees.annual_fee_usd + (card.fees.membership_fee_usd ?? 0)
  const adds = earn + credits - fees

  const warnText = [
    ...(card.valuation_note ? [card.valuation_note] : []),
    ...card.warnings,
  ].join(' · ')

  const coverage = card.fees.annual_fee_usd > 0 && earn + credits > card.fees.annual_fee_usd
    ? Math.round((earn + credits) / card.fees.annual_fee_usd)
    : null

  return (
    <div className="card-tile">
      <h3>{card.name}</h3>
      <div className="role">
        {card.choice_category
          ? `Choice category: ${pretty(card.choice_category)}`
          : roleSubtitle(card)}
      </div>
      <div className="tile-lines">
        {card.assignments.filter((a) => a.usd_assigned > 0).map((a, i) => (
          <div className="line" key={`a-${a.bucket}-${i}`}>
            <span>
              {a.cpp === 1 ? `${a.rate}%` : `${a.rate}x`} {pretty(a.bucket)}
              {a.note && <span className="note"> {a.note}</span>}
            </span>
            <span>{formatUsd(a.usd_value)}</span>
          </div>
        ))}
        {card.credits.filter((c) => c.value > 0).map((c, i) => (
          <div className="line" key={`c-${c.name}-${i}`}>
            <span>
              {c.name} <span className="note">you use it</span>
            </span>
            <span>+ {formatUsd(c.value)}</span>
          </div>
        ))}
        {card.fees.membership_fee_usd !== undefined && (
          <div className="line fee">
            <span>{card.fees.membership_name ?? 'Required'} membership</span>
            <span>− {formatUsd(card.fees.membership_fee_usd)}</span>
          </div>
        )}
        <div className="line fee">
          <span>
            Annual fee
            {card.fees.first_year_waived && <span className="note"> waived year 1</span>}
          </span>
          <span>
            {card.fees.annual_fee_usd > 0 ? `− ${formatUsd(card.fees.annual_fee_usd)}` : '$0'}
          </span>
        </div>
        {card.reward_cap_clamp !== undefined && (
          <div className="line fee">
            <span>Card-wide reward cap</span>
            <span>− {formatUsd(card.reward_cap_clamp)}</span>
          </div>
        )}
        <div className="line total">
          <span>Adds each year</span>
          <span>{formatUsd(adds)}</span>
        </div>
      </div>
      {warnText ? (
        <div className="tile-note warn">⚠ {warnText}</div>
      ) : coverage !== null && coverage >= 2 ? (
        <div className="tile-note">
          The {formatUsd(card.fees.annual_fee_usd).replace('.00', '')} fee is covered ~{coverage}×
          by what this card earns for you.
        </div>
      ) : credits > 0 ? (
        <div className="tile-note">
          Credit values are discounted to what you'll realistically capture, not face value.
        </div>
      ) : null}
      <details className="full-detail">
        <summary>full detail</summary>
        <AssignmentsTable assignments={card.assignments} />
        <div className="detail-lines">
          <CreditsList credits={card.credits} />
          <div>
            signup bonus (year 1 only): {formatUsd(card.bonus.value)}{' '}
            <span className="line-note">[{card.bonus.note}]</span>
          </div>
          {card.reward_cap_clamp !== undefined && (
            <div className="warn-note">
              ⚠ card-wide reward cap: earnings above clamped by {formatNumber(card.reward_cap_clamp)}
            </div>
          )}
          <div>
            annual fee: {formatUsd(card.fees.annual_fee_usd)}
            {card.fees.first_year_waived && ' (first year waived)'}
            {card.fees.membership_fee_usd !== undefined && (
              <> · required membership ({card.fees.membership_name}): −{formatUsd(card.fees.membership_fee_usd)}/yr</>
            )}
          </div>
          {card.warnings.map((w) => (
            <div key={`${id}-${w}`} className="warn-note">⚠ {w}</div>
          ))}
        </div>
      </details>
    </div>
  )
}
