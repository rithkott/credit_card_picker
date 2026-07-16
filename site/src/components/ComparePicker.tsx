import { useEffect, useState, type CSSProperties } from 'react'
import { getCardsCached } from '../api'
import { PORT_COLORS } from '../lib/portfolios'
import { ManualGrid } from './ManualGrid'

/** Compare path (plan 20) picker — "workbench split" (design handoff 1b).
 * Portfolios are pinned left as trays (the old tab strip + chip rows merged):
 * the active tray is raised with its identity-color ring and an EDITING flag,
 * inactive trays are inset. The shared card catalog sits right, recessed into
 * a darker well (raised = yours, sunken = the shop) with a destination pill
 * that always names where picks land. Controlled — the portfolio lists live
 * in Home (useFormState) so the run action can read them. The active tray
 * index is in-session only, like the wizard step (accepted tradeoff, keeps
 * this simple). */
export function ComparePicker({ portfolios, excluded, onToggleCard, onAdd, onRemove, onToggleExclude }: {
  portfolios: string[][]
  excluded: Set<string>
  onToggleCard: (pIdx: number, id: string) => void
  onAdd: () => void
  onRemove: (pIdx: number) => void
  onToggleExclude: (id: string) => void
}) {
  const [active, setActive] = useState(0)
  // Card id → display name for the tray rows. Shares ManualGrid's fetch via
  // the module-level cache; on failure the rows fall back to raw ids while
  // the grid shows its own error.
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    let alive = true
    getCardsCached()
      .then(({ cards }) => {
        if (alive) setNames(Object.fromEntries(cards.map((c) => [c.id, c.name])))
      })
      .catch(() => { /* ManualGrid renders the error state */ })
    return () => { alive = false }
  }, [])

  // Clamp after a remove (or a shrunken restored blob) so the active tray
  // always exists.
  const activeIdx = Math.min(active, portfolios.length - 1)

  const removePortfolio = (idx: number) => {
    onRemove(idx)
    setActive((a) => Math.min(idx < a ? a - 1 : a, portfolios.length - 2))
  }

  return (
    <div className="compare-picker">
      <div className="compare-side">
        <div className="compare-side-label">Your portfolios</div>
        <div className="tray-list" role="tablist" aria-label="Portfolios">
          {portfolios.map((cards, i) => (
            // A div with tab semantics, not a <button>: the row-remove and
            // tray-remove ✕ must stay real buttons, and interactive content
            // can't nest inside a button element.
            <div
              key={i}
              role="tab"
              tabIndex={0}
              aria-selected={i === activeIdx}
              className={`tray${i === activeIdx ? ' active' : ''}`}
              style={{ '--tray-color': PORT_COLORS[i] } as CSSProperties}
              onClick={() => setActive(i)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActive(i) }
              }}
            >
              <div className="tray-head">
                <span className="tray-dot" aria-hidden="true" />
                <span className="tray-name">Portfolio {i + 1}</span>
                <span className="tray-count">
                  {cards.length} card{cards.length === 1 ? '' : 's'}
                </span>
                {portfolios.length > 2 && (
                  <button
                    type="button"
                    className="tray-x"
                    aria-label={`Remove portfolio ${i + 1}`}
                    title="Remove this portfolio"
                    onClick={(e) => { e.stopPropagation(); removePortfolio(i) }}
                  >
                    ✕
                  </button>
                )}
              </div>
              <div className="tray-rows">
                {cards.length === 0
                  ? <span className="empty">empty — pick from the catalog →</span>
                  : cards.map((id) => (
                    <span key={id} className="tray-row">
                      <span className="tray-dot" aria-hidden="true" />
                      <span>{names[id] ?? id}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${names[id] ?? id} from portfolio ${i + 1}`}
                        onClick={(e) => { e.stopPropagation(); onToggleCard(i, id) }}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
              </div>
              {i === activeIdx && <span className="tray-flag">Editing</span>}
            </div>
          ))}
        </div>
        {portfolios.length < 4 && (
          <button type="button" className="compare-add" onClick={onAdd}>
            + Add portfolio
          </button>
        )}
      </div>
      <div className="compare-catalog">
        <div className="catalog-head">
          <span className="catalog-label">Card catalog</span>
          <span className="rule" />
          <span className="lands">Picks land in</span>
          <span className="lands-arrow" aria-hidden="true">→</span>
          <span
            className="dest-pill"
            style={{ '--tray-color': PORT_COLORS[activeIdx] } as CSSProperties}
          >
            Portfolio {activeIdx + 1}
          </span>
        </div>
        <ManualGrid
          selected={new Set(portfolios[activeIdx])}
          ownerOf={(id) => portfolios.findIndex((p) => p.includes(id))}
          excluded={excluded}
          onToggle={(id) => onToggleCard(activeIdx, id)}
          onToggleExclude={onToggleExclude}
        />
      </div>
    </div>
  )
}
