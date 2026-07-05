import type { OptimizeBundle } from '../../types'
import { RunHeader } from './RunHeader'
import { PortfolioCard } from './PortfolioCard'
import { ExcludedPruned } from './ExcludedPruned'
import { PolicyConstants } from './PolicyConstants'

/** Renders the optimizer bundle 1:1 — every number and note the engine emits
 * is shown or one disclosure away; nothing is invented client-side. */
export function ResultsView({ bundle }: { bundle: OptimizeBundle }) {
  return (
    <div>
      <RunHeader bundle={bundle} />
      {bundle.portfolios.length === 0 && (
        <section className="block">
          No eligible portfolios — check the exclusions below for why each card was filtered out.
        </section>
      )}
      {bundle.portfolios.map((p, i) => (
        <PortfolioCard key={p.cards.join('+')} rank={i + 1} portfolio={p} bundle={bundle} />
      ))}
      <ExcludedPruned bundle={bundle} />
      <PolicyConstants bundle={bundle} />
    </div>
  )
}
