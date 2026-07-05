import type { BestBySize, OptimizeBundle } from '../../types'
import { RunHeader } from './RunHeader'
import { PortfolioCard } from './PortfolioCard'
import { ExcludedPruned } from './ExcludedPruned'
import { PolicyConstants } from './PolicyConstants'

/** Escalating presentation (plan 08): always the best single card, then the
 * best 2-card and 3-card portfolios — each shown only when it beats the last
 * shown size on the optimize_for metric (adding a card for $0 gain is noise).
 * Everything shown comes verbatim from the engine's best_by_size. */
export function ResultsView({ bundle }: { bundle: OptimizeBundle }) {
  const metric = bundle.optimize_for === 'ongoing' ? 'ongoing_net' : 'year1_net'
  const shown: { entry: BestBySize; gain: number | null }[] = []
  for (const entry of bundle.best_by_size) {
    const prev = shown.length > 0 ? shown[shown.length - 1].entry[metric] : null
    if (prev === null) {
      shown.push({ entry, gain: null })
    } else if (entry[metric] > prev) {
      shown.push({ entry, gain: entry[metric] - prev })
    }
  }
  return (
    <div>
      <RunHeader bundle={bundle} />
      {shown.length === 0 && (
        <section className="block">
          No eligible portfolios — check the exclusions below for why each card was filtered out.
        </section>
      )}
      {shown.map(({ entry, gain }) => (
        <PortfolioCard
          key={entry.size}
          title={entry.size === 1 ? 'Best single card'
            : `Best ${entry.size}-card portfolio`}
          gain={gain}
          portfolio={entry}
          bundle={bundle}
        />
      ))}
      {shown.length < bundle.best_by_size.length && (
        <p className="reason-list">
          Larger portfolios didn't beat the ones shown — an extra card only appears
          when it genuinely adds value.
        </p>
      )}
      <ExcludedPruned bundle={bundle} />
      <PolicyConstants bundle={bundle} />
    </div>
  )
}
