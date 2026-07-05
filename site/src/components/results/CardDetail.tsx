import type { PerCard } from '../../types'
import { formatUsd } from '../../lib/money'
import { AssignmentsTable } from './AssignmentsTable'
import { CreditsList } from './CreditsList'

export function CardDetail({ id, card }: { id: string; card: PerCard }) {
  return (
    <div className="card-detail">
      <h4>
        {card.name}
        {card.choice_category && <> — choice category: {card.choice_category}</>}
      </h4>
      {card.valuation_note && <div className="warn-note">⚠ {card.valuation_note}</div>}
      <AssignmentsTable assignments={card.assignments} />
      {card.reward_cap_clamp !== undefined && (
        <div className="warn-note">
          ⚠ card-wide reward cap: earnings above clamped by {formatUsd(card.reward_cap_clamp)}
        </div>
      )}
      <CreditsList credits={card.credits} />
      <div>
        signup bonus (year 1 only): {formatUsd(card.bonus.value)}{' '}
        <span className="line-note">[{card.bonus.note}]</span>
      </div>
      <div>
        annual fee: {formatUsd(card.fees.annual_fee_usd)}
        {card.fees.first_year_waived && ' (first year waived)'}
        {card.fees.membership_fee_usd !== undefined && (
          <> · required membership ({card.fees.membership_name}): -{formatUsd(card.fees.membership_fee_usd)}/yr</>
        )}
      </div>
      {card.warnings.map((w) => (
        <div key={`${id}-${w}`} className="warn-note">⚠ {w}</div>
      ))}
    </div>
  )
}
