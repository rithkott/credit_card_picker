import type { CSSProperties } from 'react'
import type { BestBySize, OptimizeBundle, PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'

const SIZE_WORDS = ['', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE']

function totalFees(card: PerCard): number {
  return card.fees.annual_fee_usd + (card.fees.membership_fee_usd ?? 0)
}

/** Deterministic dark hue family per card id, for the CSS card render. */
function hueOf(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360
  return h
}

/** Deterministic per-id background: a corner glow over a two-hue diagonal, so
 * every card gets a distinct-but-cohesive dark face. Hue is stable per id. */
function faceStyle(id: string): CSSProperties {
  const h = hueOf(id)
  const h2 = (h + 28) % 360
  return {
    background:
      `radial-gradient(130% 150% at 16% -10%, hsl(${h} 34% 24% / 0.95), transparent 52%), ` +
      `linear-gradient(120deg, hsl(${h} 26% 17%), hsl(${h} 24% 9%) 62%, hsl(${h2} 24% 13%))`,
  }
}

/** The lead credit-card render: a deterministic gradient face in the id's hue
 * family, a chip, and the card name as the glowing, animated hero. No external
 * art; the face is drawn entirely from the id. */
function CardRender({ id, name }: { id: string; name: string }) {
  return (
    <div className="card-render" style={faceStyle(id)}>
      <span className="sheen" />
      <span className="cchip" />
      <span className="cname">{name}</span>
    </div>
  )
}

function CardBar({ id, name, kind }: { id: string; name: string; kind: 'mid' | 'bottom' }) {
  const h = hueOf(id)
  return (
    <div
      className={`card-bar ${kind}`}
      style={{ background: `linear-gradient(120deg, hsl(${h} 20% 16%), hsl(${h} 20% 8%))` }}
    >
      {name}
    </div>
  )
}

/** The receipt panel: eyebrow, big shimmer net, the four receipt rows, and
 * the stacked credit-card renders for the selected portfolio. Every number
 * derives from the bundle's per_card blocks — earnings are assignment
 * usd_values, credits are credit values, fees are annual + membership. */
export function PortfolioCard({ portfolio, bundle, isBest, stack }: {
  portfolio: BestBySize
  bundle: OptimizeBundle
  isBest: boolean
  stack: string[]
}) {
  const cards = portfolio.cards.map((id) => portfolio.per_card[id]).filter(Boolean)
  // Assignment usd_values are pre-clamp; card-wide reward caps subtract from
  // earnings (optimize.py reward_cap_clamps), so the receipt rows sum to net.
  const earnings = cards.reduce(
    (sum, c) => sum + c.assignments.reduce((s, a) => s + a.usd_value, 0)
      - (c.reward_cap_clamp ?? 0), 0)
  const credits = cards.reduce(
    (sum, c) => sum + c.credits.reduce((s, cr) => s + cr.value, 0), 0)
  const fees = cards.reduce((sum, c) => sum + totalFees(c), 0)
  const bonuses = cards.reduce((sum, c) => sum + c.bonus.value, 0)
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
  const netMain = year1 ? portfolio.year1_net : portfolio.ongoing_net
  // The other horizon gets its own big figure below the headline — a small
  // sentence buried the number people ask about most (year one with bonuses).
  const netSecond = year1 ? portfolio.ongoing_net : portfolio.year1_net
  const secondLabel = year1
    ? 'each year after the bonuses'
    : `in year one with the signup bonus${cards.filter((c) => c.bonus.value > 0).length > 1 ? 'es' : ''} included`
  const netSub = `left over ${year1 ? 'in year one' : 'each year'}, ${feePhrase}` +
    (bonuses > 0 ? '' : ' · no signup bonuses in this combination')

  const unassigned = Object.entries(portfolio.unassigned_spend)
  const stackCards = stack
    .map((id) => ({ id, card: portfolio.per_card[id] }))
    .filter((s) => s.card)

  return (
    <section className="block receipt">
      <div className="receipt-grid">
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
          {unassigned.length > 0 && (
            <div className="warn-note">
              ⚠ unassignable spend earning $0 (closed-loop-only portfolio):{' '}
              {unassigned.map(([bucket, v]) => `${bucket} ${formatUsd(v)}`).join(', ')}
            </div>
          )}
        </div>
        <div className="card-stack">
          {stackCards.map((s, i) =>
            i === 0
              ? <CardRender key={s.id} id={s.id} name={s.card.name} />
              : <CardBar key={s.id} id={s.id} name={s.card.name} kind={i === 1 ? 'mid' : 'bottom'} />,
          )}
        </div>
      </div>
    </section>
  )
}
