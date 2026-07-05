import type { OptimizeBundle, Portfolio } from '../../types'
import { formatUsd } from '../../lib/money'
import { CardDetail } from './CardDetail'

export function PortfolioCard({ title, gain, portfolio, bundle }: {
  title: string
  gain: number | null
  portfolio: Portfolio
  bundle: OptimizeBundle
}) {
  const primary = bundle.optimize_for === 'ongoing' ? 'ongoing_net' : 'year1_net'
  const unassigned = Object.entries(portfolio.unassigned_spend)
  return (
    <div className="portfolio">
      <h3>
        {title} — {portfolio.cards.map((id) => portfolio.per_card[id]?.name ?? id).join(' + ')}
        {gain !== null && <span className="gain"> (+{formatUsd(gain)}/yr over the previous)</span>}
      </h3>
      <div className="nets">
        <span className={primary === 'ongoing_net' ? 'primary-metric' : ''}>
          ongoing net {formatUsd(portfolio.ongoing_net)}/yr
        </span>
        <span className={primary === 'year1_net' ? 'primary-metric' : ''}>
          year-1 net {formatUsd(portfolio.year1_net)}
        </span>
      </div>
      {portfolio.cards.map((id) => (
        <CardDetail key={id} id={id} card={portfolio.per_card[id]} />
      ))}
      {unassigned.length > 0 && (
        <div className="warn-note">
          ⚠ unassignable spend earning $0 (closed-loop-only portfolio):{' '}
          {unassigned.map(([bucket, v]) => `${bucket} ${formatUsd(v)}`).join(', ')}
        </div>
      )}
    </div>
  )
}
