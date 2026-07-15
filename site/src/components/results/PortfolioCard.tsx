import type { BestBySize, OptimizeBundle, PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'
import { cardSpendDrop, entryDrop } from '../../lib/worstCase'

const SIZE_WORDS = ['', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE']

function totalFees(card: PerCard): number {
  return card.fees.annual_fee_usd + (card.fees.membership_fee_usd ?? 0)
}

/** The receipt panel: eyebrow, the big dot-matrix net figure, the two horizon
 * lines, and the itemised receipt rows for the selected portfolio. Every number
 * derives from the bundle's per_card blocks — earnings are assignment
 * usd_values, credits are credit values, fees are annual + membership. (Card
 * art is retired in v2 — the neomorphic surface has no dark card renders.) */
export function PortfolioCard({ portfolio, bundle, isBest, worstCase }: {
  portfolio: BestBySize
  bundle: OptimizeBundle
  isBest: boolean
  worstCase: boolean
}) {
  const cards = portfolio.cards.map((id) => portfolio.per_card[id]).filter(Boolean)
  const cppTable = bundle.cpp_table
  // Worst-case (cash-out) re-prices points at the program floor: earnings and
  // the net figures each drop by the per-portfolio points-value drop; nothing
  // else in the receipt moves. See lib/worstCase.
  // Assignment usd_values are pre-clamp; card-wide reward caps subtract from
  // earnings (optimize.py reward_cap_clamps), so the receipt rows sum to net.
  const earnings = cards.reduce(
    (sum, c) => sum + c.assignments.reduce((s, a) => s + a.usd_value, 0)
      - (c.reward_cap_clamp ?? 0)
      - (worstCase ? cardSpendDrop(c, cppTable) : 0), 0)
  const credits = cards.reduce(
    (sum, c) => sum + c.credits.reduce((s, cr) => s + cr.value, 0), 0)
  const fees = cards.reduce((sum, c) => sum + totalFees(c), 0)
  const bonuses = cards.reduce(
    (sum, c) => sum + (worstCase ? c.bonus.floor_value : c.bonus.value), 0)
  const spendTotal =
    cards.reduce((sum, c) => sum + c.assignments.reduce((s, a) => s + a.usd_assigned, 0), 0) +
    Object.values(portfolio.unassigned_spend).reduce((s, v) => s + v, 0)

  const size = portfolio.size
  const word = SIZE_WORDS[size] ?? String(size)
  const eyebrow = size === 1
    ? 'WITH JUST ONE CARD'
    : `WITH ${isBest && size > 2 ? 'ALL ' : ''}${word} CARDS`

  // "after the Gold membership" when the only cost is a single membership;
  // the generic phrase otherwise.
  const memberships = cards.filter((c) => c.fees.membership_fee_usd !== undefined)
  const annualFees = cards.reduce((sum, c) => sum + c.fees.annual_fee_usd, 0)
  const feePhrase = fees === 0
    ? 'with no fees to cover'
    : annualFees === 0 && memberships.length === 1
      ? `after the ${memberships[0].fees.membership_name ?? 'required'} membership`
      : 'after fees and memberships'

  const year1 = bundle.optimize_for === 'year1'
  // Year-1 net carries the signup bonus (its points drop too); ongoing net does
  // not, so each horizon's drop includes the bonus only when it's a year-1 net.
  const mainDrop = worstCase ? entryDrop(portfolio, cppTable, { includeBonus: year1 }) : 0
  const secondDrop = worstCase ? entryDrop(portfolio, cppTable, { includeBonus: !year1 }) : 0
  const netMain = (year1 ? portfolio.year1_net : portfolio.ongoing_net) - mainDrop
  // The other horizon gets its own big figure below the headline — a small
  // sentence buried the number people ask about most (year one with bonuses).
  const netSecond = (year1 ? portfolio.ongoing_net : portfolio.year1_net) - secondDrop
  const secondLabel = year1
    ? 'each year after the bonuses'
    : `in year one with the signup bonus${cards.filter((c) => c.bonus.value > 0).length > 1 ? 'es' : ''} included`
  const netSub = `left over ${year1 ? 'in year one' : 'each year'}, ${feePhrase}` +
    (bonuses > 0 ? '' : ' · no signup bonuses in this combination')

  return (
    <section className="block receipt">
      <div className="receipt-main">
          <div className="eyebrow">{eyebrow}</div>
          <div className="net-big shimmer-text">
            ${formatNumber(Math.round(netMain))}
            <span className="per">{year1 ? ' yr 1' : '/yr'}</span>
          </div>
          {bonuses > 0 && (
            <div className="net-second">
              ${formatNumber(Math.round(netSecond))}
              <span className="per"> {secondLabel}</span>
            </div>
          )}
          <div className="net-sub">{netSub}</div>
          <div className="receipt-rows">
            <div className="row">
              <span>Rewards on ${formatNumber(Math.round(spendTotal))} of spending</span>
              <i className="lead" aria-hidden="true" />
              <span>{formatUsd(earnings)}</span>
            </div>
            <div className="row">
              <span>Credits you said you'd use</span>
              <i className="lead" aria-hidden="true" />
              <span>+ {formatUsd(credits)}</span>
            </div>
            <div className="row">
              <span>Annual fees &amp; memberships</span>
              <i className="lead" aria-hidden="true" />
              <span>− {formatUsd(fees)}</span>
            </div>
            {year1 && (
              <div className="row">
                <span>Signup bonuses (year 1 only)</span>
                <i className="lead" aria-hidden="true" />
                <span>+ {formatUsd(bonuses)}</span>
              </div>
            )}
            <div className="row total">
              <span>{year1 ? 'Net, year one' : 'Net, each year'}</span>
              <span>{formatUsd(netMain)}</span>
            </div>
          </div>
      </div>
    </section>
  )
}
