import type { OptimizeBundle } from '../../types'

const KIND_LABELS: Record<string, string> = {
  cashback: 'cash back',
  flights: 'flights',
  hotels: 'hotels',
}

/** "2026-07-05" -> "Jul 5, 2026". */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return names[m - 1] ? `${names[m - 1]} ${d}, ${y}` : iso
}

export function RunHeader({ bundle }: { bundle: OptimizeBundle }) {
  return (
    <div className="results-head">
      <h2>Results</h2>
      <span className="meta">
        as of {shortDate(bundle.as_of)} · {bundle.cards_eligible} of {bundle.cards_total}{' '}
        cards were eligible for you · rewards:{' '}
        {bundle.reward_preferences.map((k) => KIND_LABELS[k] ?? k).join(', ')} ·{' '}
        {bundle.accepts_brand_lockin ? 'brand lock-in included' : 'no brand lock-in'}
      </span>
    </div>
  )
}
