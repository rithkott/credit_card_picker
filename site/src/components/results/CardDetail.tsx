import type { PerCard } from '../../types'
import { formatDate, formatNumber, formatUsd } from '../../lib/money'
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
 * credits/bonus detail one disclosure away for power users. */
export function CardDetail({ id, card }: { id: string; card: PerCard }) {
  // Assignment usd_values are pre-clamp; a card-wide reward cap subtracts
  // from earnings (optimize.py reward_cap_clamps) and shows as its own line.
  const earn = card.assignments.reduce((s, a) => s + a.usd_value, 0)
    - (card.reward_cap_clamp ?? 0)
  const credits = card.credits.reduce((s, c) => s + c.value, 0)
  const fees = card.fees.annual_fee_usd + (card.fees.membership_fee_usd ?? 0)
  const adds = earn + credits - fees

  const isPoints = card.currency.kind === 'points'

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
  const maxValue = adds + card.bonus.value + unusedPerksValue
  const showMaxValue = card.bonus.value > 0 || unusedPerksValue > 0

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
      {card.points_gateway_caveat && (
        <div className="gateway-caveat">🔑 {card.points_gateway_caveat}</div>
      )}
      {shownAssignments.length > 0 && (
        <table className="earn-table">
          {isPoints && (
            <caption>
              points valued at {[...new Set(shownAssignments.map((a) => a.cpp))].join(' / ')}¢ each
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
                  {a.expires && (
                    <span className="note lt-inline">
                      ⏳ limited time · expires {formatDate(a.expires)}
                    </span>
                  )}
                </td>
                <td className="num">{formatUsd(fullSpend(a)).replace('.00', '')}</td>
                {isPoints && (
                  <td className="num">{formatNumber(Math.round(a.usd_assigned * a.rate))}</td>
                )}
                <td className="num val">{formatUsd(a.usd_value)}</td>
              </tr>
            )})}
          </tbody>
        </table>
      )}
      {shownCredits.length > 0 && (
        <div className="tile-lines tile-credits">
          <div className="sublabel">Credits</div>
          {shownCredits.map((c, i) => (
            <div className="line" key={`c-${c.name}-${i}`}>
              <span>
                {c.name} <span className="note">you use it</span>
                {c.expires && (
                  <span className="note lt-inline">
                    ⏳ limited time · expires {formatDate(c.expires)}
                  </span>
                )}
              </span>
              <i className="lead" aria-hidden="true" />
              <span>+ {formatUsd(c.value)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="tile-lines tile-costs">
        {card.fees.membership_fee_usd !== undefined && (
          <div className="line fee">
            <span>{card.fees.membership_name ?? 'Required'} membership</span>
            <i className="lead" aria-hidden="true" />
            <span>− {formatUsd(card.fees.membership_fee_usd)}</span>
          </div>
        )}
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
        {card.reward_cap_clamp !== undefined && (
          <div className="line fee">
            <span>Card-wide reward cap</span>
            <i className="lead" aria-hidden="true" />
            <span>− {formatUsd(card.reward_cap_clamp)}</span>
          </div>
        )}
        <div className={`line total adds-year${adds < 0 ? ' neg' : ''}`}>
          <span>Adds each year</span>
          <span>{formatUsd(adds)}</span>
        </div>
      </div>
      {card.pairing_note && <div className="tile-note">✓ {card.pairing_note}</div>}
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
      {(() => {
        // Dual signup bonus (plan 15): a permanent line and, beneath it, the
        // limited-time elevated offer with its expiry + revert note.
        const perm = card.bonus.permanent
        const lt = card.bonus.limited_time
        const hasPerm = (perm?.value ?? 0) > 0
        const hasLt = (lt?.value ?? 0) > 0
        if (!hasPerm && !hasLt) return null
        return (
          <div className="tile-lines tile-perks tile-bonus">
            <div className="sublabel">
              Signup bonus <span className="note">first year only, not in the yearly total</span>
            </div>
            {hasPerm && (
              <div className="line">
                <span>{hasLt ? 'Standard offer' : 'New-cardmember offer'}</span>
                <i className="lead" aria-hidden="true" />
                <span>{formatUsd(perm!.value)}</span>
              </div>
            )}
            {hasLt && (
              <div className={`lt-offer${hasPerm ? ' lt-divider' : ''}`}>
                <div className="line">
                  <span>
                    ⏳ Limited-time offer
                    {lt!.expires && (
                      <span className="conf conf-low lt-pill">
                        expires {formatDate(lt!.expires)}
                      </span>
                    )}
                  </span>
                  <i className="lead" aria-hidden="true" />
                  <span>{formatUsd(lt!.value)}</span>
                </div>
                {lt!.expires && (
                  <div className="tile-note lt-revert">
                    After {formatDate(lt!.expires)}, this reverts to{' '}
                    {hasPerm
                      ? `the ${formatUsd(perm!.value)} standard offer`
                      : 'no standard bonus (not yet published)'}.
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })()}
      {unusedPerks.length > 0 && (
        <div className="tile-lines tile-perks">
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
      )}
      {showMaxValue && (
        <div className="tile-lines tile-maxvalue">
          <div className={`line total max-value${maxValue < 0 ? ' neg' : ''}`}>
            <span>Max value</span>
            <span>{formatUsd(maxValue)}</span>
          </div>
        </div>
      )}
      <details className="full-detail">
        <summary>full detail</summary>
        <AssignmentsTable assignments={card.assignments} currencyKind={card.currency.kind} />
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
          {shownWarnings.map((w) => (
            <div key={`${id}-${w}`} className="warn-note">⚠ {w}</div>
          ))}
        </div>
      </details>
    </div>
  )
}
