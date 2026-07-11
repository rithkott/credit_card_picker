import { useState } from 'react'
import type { BestBySize, OptimizeBundle } from '../../types'
import { formatNumber } from '../../lib/money'
import { RunHeader } from './RunHeader'
import { PortfolioCard } from './PortfolioCard'
import { CardDetail } from './CardDetail'
import { ExcludedPruned } from './ExcludedPruned'
import { PolicyConstants } from './PolicyConstants'

interface ShownEntry {
  entry: BestBySize
  gain: number | null
  /** Card ids in this entry that were not in the previous shown entry. */
  added: string[]
}

/** Escalating presentation (plan 08): always the best single card, then the
 * best 2-card and 3-card portfolios — each shown only when it beats the last
 * shown size on the optimize_for metric (adding a card for $0 gain is noise).
 * Everything shown comes verbatim from the engine's best_by_size.
 *
 * v2 (design handoff): the sizes render as a clickable ladder; the selected
 * row drives the receipt panel, card stack, and per-card tiles below. */
export function ResultsView({ bundle }: { bundle: OptimizeBundle }) {
  const metric = bundle.optimize_for === 'ongoing' ? 'ongoing_net' : 'year1_net'
  const shown: ShownEntry[] = []
  for (const entry of bundle.best_by_size) {
    const prev = shown.length > 0 ? shown[shown.length - 1].entry : null
    if (prev === null) {
      shown.push({ entry, gain: null, added: entry.cards })
    } else if (entry[metric] > prev[metric]) {
      shown.push({
        entry,
        gain: entry[metric] - prev[metric],
        added: entry.cards.filter((id) => !prev.cards.includes(id)),
      })
    }
  }

  // Default view = the best (last shown) size; clamp if a new bundle arrives
  // with fewer sizes than the previous selection.
  const [selectedSize, setSelectedSize] = useState<number | null>(null)
  const best = shown[shown.length - 1]
  const selected = shown.find((s) => s.entry.size === selectedSize) ?? best

  if (shown.length === 0) {
    return (
      <div>
        <RunHeader bundle={bundle} />
        <section className="block">
          No eligible portfolios — check the exclusions below for why each card was filtered out.
        </section>
        <div className="disclosure-rows">
          <ExcludedPruned bundle={bundle} />
          <PolicyConstants bundle={bundle} />
        </div>
      </div>
    )
  }

  // Card-stack order for the receipt panel: most important card first (the
  // big render at the back of the picture), latest addition last (the small
  // bottom-front bar), walking the shown ladder up to the selected entry.
  const additionOrder: string[] = []
  for (const s of shown) {
    for (const id of s.entry.cards) {
      if (!additionOrder.includes(id)) additionOrder.push(id)
    }
    if (s === selected) break
  }
  const stack = additionOrder.filter((id) => selected.entry.cards.includes(id))

  const bestNet = Math.max(best.entry[metric], 1)
  const perYear = bundle.optimize_for === 'ongoing' ? '/yr' : ' yr 1'

  return (
    <div>
      <RunHeader bundle={bundle} />
      <div className="ladder">
        {shown.map((s) => {
          const isBest = s === best
          const isSelected = s === selected
          const label = s.gain === null
            ? s.entry.cards.map((id) => s.entry.per_card[id]?.name ?? id).join(' + ')
            : s.added.length > 0
              ? `+ ${s.added.map((id) => s.entry.per_card[id]?.name ?? id).join(' + ')}`
              : s.entry.cards.map((id) => s.entry.per_card[id]?.name ?? id).join(' + ')
          const width = Math.max(0, Math.min(1, s.entry[metric] / bestNet)) * 100
          return (
            <button
              type="button"
              key={s.entry.size}
              className={`ladder-row${isBest ? ' best' : ''}`}
              onClick={() => setSelectedSize(s.entry.size)}
              aria-pressed={isSelected}
            >
              <span className="fill" style={{ width: `${width}%` }} />
              {isSelected && <span className="ring" />}
              <span className="content">
                <span className="size">{s.entry.size} card{s.entry.size > 1 ? 's' : ''}</span>
                <span className="name">{label}</span>
                {s.gain !== null && (
                  <span className="gain">+${formatNumber(Math.round(s.gain))}/yr</span>
                )}
                {isBest && <span className="tag best">BEST</span>}
                {isSelected && <span className="tag">viewing</span>}
                <span className="spacer" />
                <span className="net">
                  ${formatNumber(Math.round(s.entry[metric]))}{perYear}
                </span>
              </span>
            </button>
          )
        })}
        <span className="ladder-caption">
          {shown.length > 1 && 'Click a row to see its math below. '}
          {shown.length < bundle.best_by_size.length && (
            `A ${shown.length + 1}${['st', 'nd', 'rd'][shown.length] ?? 'th'} card didn't add ` +
            'anything — extra cards only appear here when they genuinely improve the total.'
          )}
        </span>
      </div>

      <PortfolioCard
        portfolio={selected.entry}
        bundle={bundle}
        isBest={selected === best}
        stack={stack}
      />

      <div className="tile-grid">
        {stack.map((id) => (
          <CardDetail key={id} id={id} card={selected.entry.per_card[id]} />
        ))}
      </div>

      <div className="disclosure-rows">
        <ExcludedPruned bundle={bundle} />
        <PolicyConstants bundle={bundle} />
      </div>
    </div>
  )
}
