import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { BestBySize, OptimizeBundle } from '../../types'
import { formatNumber } from '../../lib/money'
import { entryDrop, hasWorstCaseGap } from '../../lib/worstCase'
import { RunHeader } from './RunHeader'
import { PortfolioCard } from './PortfolioCard'
import { CardDetail } from './CardDetail'
import { ExcludedPruned } from './ExcludedPruned'
import { PolicyConstants } from './PolicyConstants'

interface ShownEntry {
  entry: BestBySize
  gain: number | null
}

/** Escalating presentation (plan 08): always the best single card, then the
 * best 2-card and 3-card portfolios — each shown only when it beats the last
 * shown size on the optimize_for metric (adding a card for $0 gain is noise).
 * Everything shown comes verbatim from the engine's best_by_size. Each size
 * is optimized independently — the best k-card set need not contain the best
 * (k-1)-card set — so every row lists its complete portfolio. */
export function ResultsView({ bundle, addedCard }: {
  bundle: OptimizeBundle
  /** Improve path (suggest-addition): the card the server chose to add — its
   * tile gets a "Suggested addition" badge. */
  addedCard?: string
}) {
  const metric = bundle.optimize_for === 'ongoing' ? 'ongoing_net' : 'year1_net'
  const shown: ShownEntry[] = []
  for (const entry of bundle.best_by_size) {
    const prev = shown.length > 0 ? shown[shown.length - 1].entry : null
    if (prev === null) {
      shown.push({ entry, gain: null })
    } else if (entry[metric] > prev[metric]) {
      shown.push({ entry, gain: entry[metric] - prev[metric] })
    }
  }

  // Default view = the best (last shown) size; clamp if a new bundle arrives
  // with fewer sizes than the previous selection.
  const [selectedSize, setSelectedSize] = useState<number | null>(null)
  const best = shown[shown.length - 1]
  const selected = shown.find((s) => s.entry.size === selectedSize) ?? best

  // Worst-case (cash-out) points valuation toggle: display-only, never re-ranks
  // — the shown sizes and their order are chosen on the true (avg) metric; only
  // the displayed dollars drop. Offered only when a points card actually moves.
  const [worstCase, setWorstCase] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)
  const canWorstCase = hasWorstCaseGap(shown.map((s) => s.entry), bundle.cpp_table)
  const worst = worstCase && canWorstCase
  const netOf = (entry: BestBySize): number =>
    entry[metric] - (worst
      ? entryDrop(entry, bundle.cpp_table, { includeBonus: metric === 'year1_net' })
      : 0)

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

  const bestNet = Math.max(netOf(best.entry), 1)
  const perYear = bundle.optimize_for === 'ongoing' ? '/yr' : ' yr 1'

  // Portfolio-size control panel: an inset slider (and a decorative rotary knob
  // that mirrors it) that sets `selectedSize` — the same selection the ladder
  // rows drive. Shown only when more than one size made the cut.
  const selIdx = shown.findIndex((s) => s === selected)
  const lastIdx = shown.length - 1
  const selPct = lastIdx > 0 ? (selIdx / lastIdx) * 100 : 0
  const knobAngle = -50 + selPct
  const pickFromClientX = (clientX: number) => {
    const el = trackRef.current
    if (!el || lastIdx < 1) return
    const r = el.getBoundingClientRect()
    const t = Math.max(0, Math.min(1, (clientX - r.left) / r.width))
    setSelectedSize(shown[Math.round(t * lastIdx)].entry.size)
  }
  const onSliderDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    pickFromClientX(e.clientX)
  }
  const onSliderMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.buttons !== 1) return
    pickFromClientX(e.clientX)
  }
  const onSliderKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    let next = selIdx
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = Math.min(lastIdx, selIdx + 1)
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = Math.max(0, selIdx - 1)
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = lastIdx
    else return
    e.preventDefault()
    setSelectedSize(shown[next].entry.size)
  }

  return (
    <div>
      <RunHeader bundle={bundle} />
      {canWorstCase && (
        <label className="worst-case-toggle">
          <input
            type="checkbox"
            checked={worstCase}
            onChange={(e) => setWorstCase(e.target.checked)}
          />
          <span>
            Value points at cash-out floor
            <span className="note">
              {' '}worst case — what your points are worth as cash or gift cards,
              not optimal transfers. The recommended cards don't change.
            </span>
          </span>
        </label>
      )}
      {shown.length > 1 && (
        <div className="control-panel">
          <span className="screw tl" aria-hidden="true" />
          <span className="screw tr" aria-hidden="true" />
          <span className="screw bl" aria-hidden="true" />
          <span className="screw br" aria-hidden="true" />
          <div className="cp-slider-wrap">
            <div className="cp-eyebrow">
              PORTFOLIO SIZE · {selected.entry.size} CARD{selected.entry.size > 1 ? 'S' : ''}
            </div>
            <div
              ref={trackRef}
              className="cp-slider"
              role="slider"
              tabIndex={0}
              aria-label="Portfolio size"
              aria-valuemin={shown[0].entry.size}
              aria-valuemax={shown[lastIdx].entry.size}
              aria-valuenow={selected.entry.size}
              aria-valuetext={`${selected.entry.size} card${selected.entry.size > 1 ? 's' : ''}`}
              onPointerDown={onSliderDown}
              onPointerMove={onSliderMove}
              onKeyDown={onSliderKey}
            >
              <div className="cp-fill" style={{ width: `${selPct}%` }} />
              <div className="cp-handle" style={{ left: `${selPct}%` }} />
            </div>
            <div className="cp-ticks">
              {shown.map((s) => (
                <span key={s.entry.size}>
                  {s.entry.size} card{s.entry.size > 1 ? 's' : ''}
                </span>
              ))}
            </div>
          </div>
          <div className="cp-knob-wrap" aria-hidden="true">
            <div className="cp-knob" title="Follows the portfolio-size slider">
              <div className="cp-knob-face" style={{ transform: `rotate(${knobAngle}deg)` }} />
            </div>
          </div>
        </div>
      )}

      <div className="ladder">
        {shown.map((s, i) => {
          const isBest = s === best
          const isSelected = s === selected
          const label = s.entry.cards
            .map((id) => s.entry.per_card[id]?.name ?? id).join(' + ')
          const net = netOf(s.entry)
          const gain = i > 0 ? net - netOf(shown[i - 1].entry) : null
          const width = Math.max(0, Math.min(1, net / bestNet)) * 100
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
                {gain !== null && (
                  <span className="gain">+${formatNumber(Math.round(gain))}/yr</span>
                )}
                {isBest && <span className="tag best">BEST</span>}
                {isSelected && <span className="tag">viewing</span>}
                <span className="spacer" />
                <span className="net">
                  ${formatNumber(Math.round(net))}{perYear}
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
        worstCase={worst}
      />

      <div className="tile-grid">
        {stack.map((id) => (
          <CardDetail
            key={id}
            id={id}
            card={selected.entry.per_card[id]}
            cppTable={bundle.cpp_table}
            worstCase={worst}
            suggested={id === addedCard}
          />
        ))}
      </div>

      <div className="disclosure-rows">
        <ExcludedPruned bundle={bundle} />
        <PolicyConstants bundle={bundle} />
      </div>
    </div>
  )
}
