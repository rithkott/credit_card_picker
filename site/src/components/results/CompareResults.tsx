import type { OptimizeBundle } from '../../types'
import { formatNumber } from '../../lib/money'
import { RunHeader } from './RunHeader'
import { PortfolioCard } from './PortfolioCard'
import { ResultTiles } from './ResultTiles'
import { PolicyConstants } from './PolicyConstants'

/** One portfolio's evaluation in a compare run (plan 20). The label and card
 * list are snapshotted at run time so editing the pickers afterwards can't
 * desync what's rendered. */
export type CompareOutcome =
  | { ok: true; bundle: OptimizeBundle }
  | { ok: false; detail: string; unreachable: boolean }
export interface CompareEntry {
  label: string
  cards: string[]
  outcome: CompareOutcome
}

/** Compare-path results (plan 20): every hand-built portfolio's receipt
 * stacked vertically — winner ringed and tagged BEST — with each portfolio's
 * math tiles behind a collapsed disclosure so the stack stays scannable.
 * Each entry is an independent /api/evaluate bundle; a failed evaluation
 * renders as an inline error panel without hiding the others. No ladder, no
 * size slider — the user chose these exact sets. ExcludedPruned is skipped:
 * evaluate() bypasses the filters, so its lists are empty. */
export function CompareResults({ entries, excluded, onToggleExclude }: {
  entries: CompareEntry[]
  /** Cards the user vetoed (v2.5.0) — feeds each math tile's ⋯ menu; the veto
   * applies on the NEXT run, this bundle keeps rendering unchanged. */
  excluded?: Set<string>
  onToggleExclude?: (id: string) => void
}) {
  const firstOk = entries.find((e) => e.outcome.ok)?.outcome
  const firstBundle = firstOk?.ok ? firstOk.bundle : null

  // Winner: best net among successful evaluations, on the run's optimize_for
  // horizon (identical across entries — one profile, N card sets). First max
  // wins ties.
  const netOf = (bundle: OptimizeBundle): number => {
    const p = bundle.best_by_size[0]
    return bundle.optimize_for === 'ongoing' ? p.ongoing_net : p.year1_net
  }
  let winnerIdx = -1
  let winnerNet = -Infinity
  for (const [i, e] of entries.entries()) {
    if (!e.outcome.ok) continue
    const net = netOf(e.outcome.bundle)
    if (net > winnerNet) {
      winnerIdx = i
      winnerNet = net
    }
  }

  const perYear = firstBundle?.optimize_for === 'year1' ? ' yr 1' : '/yr'

  return (
    <div className="compare-results">
      {firstBundle && <RunHeader bundle={firstBundle} />}
      {entries.map((e, i) => {
        const isWinner = i === winnerIdx && entries.filter((x) => x.outcome.ok).length > 1
        if (!e.outcome.ok) {
          return (
            <section className="block compare-result" key={i}>
              <div className="compare-result-head">
                <span className="eyebrow">PORTFOLIO {i + 1}</span>
                <span className="cards">{e.cards.join(' + ')}</span>
              </div>
              <p className="compare-error">
                {e.outcome.unreachable
                  ? "Couldn't reach the server for this portfolio — try running again."
                  : e.outcome.detail}
              </p>
            </section>
          )
        }
        const bundle = e.outcome.bundle
        const portfolio = bundle.best_by_size[0]
        const names = portfolio.cards
          .map((id) => portfolio.per_card[id]?.name ?? id).join(' + ')
        return (
          <section className={`block compare-result${isWinner ? ' winner' : ''}`} key={i}>
            <div className="compare-result-head">
              <span className="eyebrow">{e.label.toUpperCase()}</span>
              <span className="cards">{names}</span>
              {isWinner && <span className="tag best">BEST</span>}
              <span className="spacer" />
              <span className="net">
                ${formatNumber(Math.round(netOf(bundle)))}{perYear}
              </span>
            </div>
            <PortfolioCard
              portfolio={portfolio}
              bundle={bundle}
              isBest={isWinner}
              worstCase={false}
            />
            <details className="disclosure">
              <summary>
                <span>Per-card math — how each card in {e.label} earns its keep</span>
                <span className="spacer" />
                <span className="show">show</span>
              </summary>
              <div className="body">
                <ResultTiles
                  cardIds={portfolio.cards}
                  perCard={portfolio.per_card}
                  cppTable={bundle.cpp_table}
                  worstCase={false}
                  excluded={excluded}
                  onToggleExclude={onToggleExclude}
                />
              </div>
            </details>
          </section>
        )
      })}
      {firstBundle && (
        <div className="disclosure-rows">
          <PolicyConstants bundle={firstBundle} />
        </div>
      )}
    </div>
  )
}
