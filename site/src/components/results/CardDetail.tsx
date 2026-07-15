import type { OptimizeBundle, PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'
import { assignmentDrop, floorCppOf } from '../../lib/worstCase'
import { AssignmentsTable } from './AssignmentsTable'
import { CreditsList } from './CreditsList'

function pretty(bucket: string): string {
  return bucket.replace(/_/g, ' ')
}

/** Rotating featured-quarter lines carry eligible_fraction (~1/6): usd_assigned
 * is already diluted, so the table shows the FULL eligible spend (undo the
 * fraction) and surfaces the ×1/N against the points/value actually earned. */
function fullSpend(a: { usd_assigned: number; eligible_fraction?: number }): number {
  // Round the reconstructed full spend — the featured-quarter model is already
  // an approximation, and undoing a rounded 1/N share otherwise yields cents
  // like $4,000.02.
  return a.eligible_fraction ? Math.round(a.usd_assigned / a.eligible_fraction) : a.usd_assigned
}
function fractionLabel(a: { eligible_fraction?: number }): string | null {
  return a.eligible_fraction ? `1⁄${Math.round(1 / a.eligible_fraction)}` : null
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

/** Verification bookkeeping is curator-facing; users only see warnings that
 * change what the card does for them (expired bonus, …). Approval notes are
 * curator credit-tier inferences ("estimated from the card's positioning"),
 * not actionable approval odds — dropped alongside the other bookkeeping. */
function userFacing(warnings: string[]): string[] {
  return warnings
    .filter((w) => !w.startsWith('UNVERIFIED DATA') && !w.startsWith('stale verification')
      && !w.startsWith('approval:'))
    .map((w) => w.replace(/\s*NEEDS human verification\.?/g, '').trim())
    .filter((w) => w.length > 0)
}

/** Per-card tile (design handoff v2): name, role, the money line items, and
 * an "Adds each year" total — with the existing full AssignmentsTable and
 * credits/bonus detail one disclosure away for power users.
 *
 * Layout: every tile renders the SAME fixed sequence of section slots, empty
 * where a card has no such section. Combined with the CSS subgrid on
 * `.tile-grid`, that makes each band (earn table, credits, annual fee, adds,
 * bonus, max value…) line up horizontally across every card in the row —
 * shorter sections get whitespace so the next band still aligns. */
export function CardDetail({ id, card, cppTable, worstCase, suggested }: {
  id: string
  card: PerCard
  cppTable: OptimizeBundle['cpp_table']
  worstCase: boolean
  /** Improve path: this card is the server's suggested addition. */
  suggested?: boolean
}) {
  const isPoints = card.currency.kind === 'points'
  // Worst-case (cash-out): re-price this card's points at the program floor.
  // floorCpp drives the earn-table caption and the per-row value/total drop;
  // cash cards and missing programs resolve to no drop. See lib/worstCase.
  const floorCpp = isPoints ? floorCppOf(card, cppTable) : null
  const useWorst = worstCase && floorCpp !== null
  const rowValue = (a: PerCard['assignments'][number]): number =>
    useWorst ? a.usd_value - assignmentDrop(a, floorCpp as number) : a.usd_value

  // Assignment usd_values are pre-clamp; a card-wide reward cap subtracts
  // from earnings (optimize.py reward_cap_clamps) and shows as its own line.
  const earn = card.assignments.reduce((s, a) => s + rowValue(a), 0)
    - (card.reward_cap_clamp ?? 0)
  const credits = card.credits.reduce((s, c) => s + c.value, 0)
  const fees = card.fees.annual_fee_usd + (card.fees.membership_fee_usd ?? 0)
  const adds = earn + credits - fees
  const bonusValue = useWorst ? card.bonus.floor_value : card.bonus.value

  const shownWarnings = userFacing(card.warnings)
  const warnText = [
    ...(card.valuation_note ? [card.valuation_note] : []),
    ...shownWarnings,
  ].join(' · ')

  const shownAssignments = card.assignments
    .filter((a) => a.usd_assigned > 0)
    .sort((a, b) => b.usd_value - a.usd_value)
  const shownCredits = card.credits
    .filter((c) => c.value > 0)
    .sort((a, b) => b.value - a.value)
  // Perks the user didn't confirm using — $0 to the optimizer, but they'd get
  // them anyway with the card. Shown at full face value, never in any total.
  const unusedPerks = card.credits
    .filter((c) => c.value === 0 && (c.potential_value ?? 0) > 0)
    .sort((a, b) => (b.potential_value ?? 0) - (a.potential_value ?? 0))
  // "Max value" = the recurring yearly adds + the one-time signup bonus + every
  // perk they'd get anyway at full face value. The optimistic ceiling, shown
  // as its own highlighted total when there's anything beyond `adds` to add.
  const unusedPerksValue = unusedPerks.reduce((s, c) => s + (c.potential_value ?? 0), 0)
  const maxValue = adds + bonusValue + unusedPerksValue
  const showMaxValue = bonusValue > 0 || unusedPerksValue > 0

  const coverage = card.fees.annual_fee_usd > 0 && earn + credits > card.fees.annual_fee_usd
    ? Math.round((earn + credits) / card.fees.annual_fee_usd)
    : null

  const hasMembership = card.fees.membership_fee_usd !== undefined
  // Coverage/pairing/warning note — at most a pairing line plus one of
  // warn/coverage/credits, both living in the single note band.
  const feeNote = warnText
    ? <div className="tile-note warn">⚠ {warnText}</div>
    : coverage !== null && coverage >= 2
      ? (
        <div className="tile-note">
          The {formatUsd(card.fees.annual_fee_usd).replace('.00', '')} fee is covered ~{coverage}×
          by what this card earns for you.
        </div>
      )
      : credits > 0
        ? (
          <div className="tile-note">
            Credit values are discounted to what you'll realistically capture, not face value.
          </div>
        )
        : null
  const hasNote = Boolean(card.pairing_note) || Boolean(feeNote)

  return (
    <div className="card-tile">
      {/* 1 · header */}
      <div className="tile-slot slot-header">
        <h3>
          {card.name}
          {suggested && <span className="badge-suggested">Suggested addition</span>}
        </h3>
        <div className="role">
          {card.choice_category
            ? `Choice category: ${pretty(card.choice_category)}`
            : roleSubtitle(card)}
        </div>
        {card.points_gateway_caveat && (
          <div className="gateway-caveat">🔑 {card.points_gateway_caveat}</div>
        )}
      </div>

      {/* 2 · earn table */}
      {shownAssignments.length > 0 ? (
        <div className="tile-slot slot-earn">
          <table className="earn-table">
            {isPoints && (
              <caption>
                points valued at{' '}
                {useWorst
                  ? `${floorCpp}¢ each (cash-out floor)`
                  : `${[...new Set(shownAssignments.map((a) => a.cpp))].join(' / ')}¢ each`}
              </caption>
            )}
            <thead>
              <tr>
                <th>Earns</th>
                <th className="num">Spend</th>
                {isPoints && <th className="num">Points</th>}
                <th className="num">Value/yr</th>
              </tr>
            </thead>
            <tbody>
              {shownAssignments.map((a, i) => {
                const frac = fractionLabel(a)
                return (
                  <tr key={`a-${a.bucket}-${i}`}>
                    <td>
                      {isPoints ? `${a.rate}x` : `${a.rate}%`}
                      {frac && <span className="frac"> × {frac}</span>} {pretty(a.bucket)}
                      {a.note && <span className="note">{a.note}</span>}
                    </td>
                    <td className="num">{formatUsd(fullSpend(a)).replace('.00', '')}</td>
                    {isPoints && (
                      <td className="num">{formatNumber(Math.round(a.usd_assigned * a.rate))}</td>
                    )}
                    <td className="num val">{formatUsd(rowValue(a))}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : <div className="tile-slot" />}

      {/* 3 · credits */}
      {shownCredits.length > 0 ? (
        <div className="tile-slot tile-lines tile-credits">
          <div className="sublabel">Credits</div>
          {shownCredits.map((c, i) => (
            <div className="line" key={`c-${c.name}-${i}`}>
              <span>
                {c.name} <span className="note">you use it</span>
              </span>
              <i className="lead" aria-hidden="true" />
              <span>+ {formatUsd(c.value)}</span>
            </div>
          ))}
        </div>
      ) : <div className="tile-slot" />}

      {/* 4 · required membership (optional): card-exclusive is a deducted
          cost; assumed-held (Costco/Sam's/Prime) is disclosure only */}
      {hasMembership ? (
        <div className="tile-slot tile-lines slot-cost slot-cost-first">
          <div className="line fee">
            <span>{card.fees.membership_name ?? 'Required'} membership</span>
            <i className="lead" aria-hidden="true" />
            <span>− {formatUsd(card.fees.membership_fee_usd as number)}</span>
          </div>
        </div>
      ) : card.fees.assumed_membership_usd !== undefined ? (
        <div className="tile-slot tile-lines">
          <div className="line">
            <span>
              Assumes {card.fees.assumed_membership_name} membership{' '}
              <span className="note">
                ({formatUsd(card.fees.assumed_membership_usd)}/yr — assumed already held, not deducted)
              </span>
            </span>
          </div>
        </div>
      ) : <div className="tile-slot" />}

      {/* 5 · annual fee (always) */}
      <div className={`tile-slot tile-lines slot-cost${hasMembership ? '' : ' slot-cost-first'}`}>
        <div className={`line fee${card.fees.annual_fee_usd > 0 ? ' annual-fee' : ''}`}>
          <span>
            Annual fee
            {card.fees.first_year_waived && <span className="note"> waived year 1</span>}
          </span>
          <i className="lead" aria-hidden="true" />
          <span>
            {card.fees.annual_fee_usd > 0 ? `− ${formatUsd(card.fees.annual_fee_usd)}` : '$0'}
          </span>
        </div>
      </div>

      {/* 6 · card-wide reward cap (optional) */}
      {card.reward_cap_clamp !== undefined ? (
        <div className="tile-slot tile-lines slot-cost">
          <div className="line fee">
            <span>Card-wide reward cap</span>
            <i className="lead" aria-hidden="true" />
            <span>− {formatUsd(card.reward_cap_clamp)}</span>
          </div>
        </div>
      ) : <div className="tile-slot" />}

      {/* 7 · adds each year (always) */}
      <div className="tile-slot tile-lines slot-adds">
        <div className={`line total adds-year${adds < 0 ? ' neg' : ''}`}>
          <span>Adds each year</span>
          <span>{formatUsd(adds)}</span>
        </div>
      </div>

      {/* 8 · note (optional) */}
      {hasNote ? (
        <div className="tile-slot slot-note">
          {card.pairing_note && <div className="tile-note">✓ {card.pairing_note}</div>}
          {feeNote}
        </div>
      ) : <div className="tile-slot" />}

      {/* 9 · signup bonus (optional) */}
      {bonusValue > 0 ? (
        <div className="tile-slot tile-lines tile-perks tile-bonus">
          <div className="sublabel">
            Signup bonus <span className="note">first year only, not in the yearly total</span>
          </div>
          <div className="line">
            <span>New-cardmember offer</span>
            <i className="lead" aria-hidden="true" />
            <span>{formatUsd(bonusValue)}</span>
          </div>
        </div>
      ) : <div className="tile-slot" />}

      {/* 10 · perks you'd get anyway (optional) */}
      {unusedPerks.length > 0 ? (
        <div className="tile-slot tile-lines tile-perks">
          <div className="sublabel">
            Perks you'd get anyway <span className="note">not counted above</span>
          </div>
          {unusedPerks.map((c, i) => (
            <div className="line" key={`p-${c.name}-${i}`}>
              <span>{c.name}</span>
              <i className="lead" aria-hidden="true" />
              <span>{formatUsd(c.potential_value ?? 0)}/yr</span>
            </div>
          ))}
        </div>
      ) : <div className="tile-slot" />}

      {/* 11 · max value (optional) */}
      {showMaxValue ? (
        <div className="tile-slot tile-lines tile-maxvalue">
          <div className={`line total max-value${maxValue < 0 ? ' neg' : ''}`}>
            <span>Max value</span>
            <span>{formatUsd(maxValue)}</span>
          </div>
        </div>
      ) : <div className="tile-slot" />}

      {/* 12 · full detail (always) */}
      <details className="tile-slot full-detail">
        <summary>full detail</summary>
        <AssignmentsTable
          assignments={card.assignments}
          currencyKind={card.currency.kind}
          worstCaseFloorCpp={useWorst ? (floorCpp as number) : null}
        />
        <div className="detail-lines">
          <CreditsList credits={card.credits} />
          <div>
            signup bonus (year 1 only): {formatUsd(bonusValue)}{' '}
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
            {card.fees.assumed_membership_usd !== undefined && (
              <> · assumes {card.fees.assumed_membership_name} membership ({formatUsd(card.fees.assumed_membership_usd)}/yr — assumed already held, not deducted)</>
            )}
          </div>
          {shownWarnings.map((w) => (
            <div key={`${id}-${w}`} className="warn-note">⚠ {w}</div>
          ))}
        </div>
      </details>
    </div>
  )
}
