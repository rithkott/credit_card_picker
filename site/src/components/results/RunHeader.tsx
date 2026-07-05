import type { OptimizeBundle } from '../../types'

export function RunHeader({ bundle }: { bundle: OptimizeBundle }) {
  return (
    <section className="block">
      <h2>Results</h2>
      <p className="why">
        as of {bundle.as_of} · {bundle.valuation_mode} point values · optimizing{' '}
        {bundle.optimize_for === 'ongoing' ? 'ongoing yearly value' : 'first-year value'} · up to{' '}
        {bundle.max_cards} card{bundle.max_cards > 1 ? 's' : ''} ·{' '}
        {bundle.cards_eligible} of {bundle.cards_total} cards eligible ({bundle.card_variants}{' '}
        variants, {bundle.card_variants_pruned} pruned) · rewards:{' '}
        {bundle.reward_preferences.join(', ')} · brand lock-in:{' '}
        {bundle.accepts_brand_lockin ? 'ok' : 'no'} · confirmed:{' '}
        {bundle.confirmed_usage.length > 0 ? bundle.confirmed_usage.join(', ') : 'none'}
      </p>
    </section>
  )
}
