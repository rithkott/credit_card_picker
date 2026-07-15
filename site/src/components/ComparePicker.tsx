import { useEffect, useState } from 'react'
import { getCardsCached } from '../api'
import { ManualGrid } from './ManualGrid'

/** Compare path (plan 20) picker: one shared card catalog with a tab strip
 * that routes picks into the active portfolio. All 2–4 portfolios stay
 * visible as chip rows while you edit one — that running comparison is the
 * point. Controlled — the portfolio lists live in Home (useFormState) so the
 * run action can read them. The active tab index is in-session only, like the
 * wizard step (accepted tradeoff, keeps this simple). */
export function ComparePicker({ portfolios, excluded, onToggleCard, onAdd, onRemove, onToggleExclude }: {
  portfolios: string[][]
  excluded: Set<string>
  onToggleCard: (pIdx: number, id: string) => void
  onAdd: () => void
  onRemove: (pIdx: number) => void
  onToggleExclude: (id: string) => void
}) {
  const [active, setActive] = useState(0)
  // Card id → display name for the chips. Shares ManualGrid's fetch via the
  // module-level cache; on failure the chips fall back to raw ids while the
  // grid shows its own error.
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

  // Clamp after a remove (or a shrunken restored blob) so the active tab
  // always exists.
  const activeIdx = Math.min(active, portfolios.length - 1)

  const removePortfolio = (idx: number) => {
    onRemove(idx)
    setActive((a) => Math.min(idx < a ? a - 1 : a, portfolios.length - 2))
  }

  return (
    // Not a raised .block: ManualGrid renders its own block per issuer group,
    // and nesting raised panels double-shadows. The tab strip + chip rows sit
    // on the page like the runbar does.
    <div className="compare-picker">
      <div className="compare-tabs" role="tablist" aria-label="Portfolios">
        {portfolios.map((cards, i) => (
          <div key={i} className={`compare-tab${i === activeIdx ? ' active' : ''}`}>
            <button
              type="button"
              role="tab"
              aria-selected={i === activeIdx}
              onClick={() => setActive(i)}
            >
              Portfolio {i + 1}
              <span className="compare-tab-count">
                {cards.length} card{cards.length === 1 ? '' : 's'}
              </span>
            </button>
            {portfolios.length > 2 && (
              <button
                type="button"
                className="compare-tab-x"
                aria-label={`Remove portfolio ${i + 1}`}
                title="Remove this portfolio"
                onClick={() => removePortfolio(i)}
              >
                ✕
              </button>
            )}
          </div>
        ))}
        {portfolios.length < 4 && (
          <button type="button" className="compare-add" onClick={onAdd}>
            + Add portfolio
          </button>
        )}
      </div>
      <div className="compare-chips-rows">
        {portfolios.map((cards, i) => (
          <div key={i} className={`compare-chips${i === activeIdx ? ' active' : ''}`}>
            <button
              type="button"
              className="compare-chips-label"
              onClick={() => setActive(i)}
            >
              Portfolio {i + 1}
            </button>
            {cards.length === 0
              ? <span className="empty">empty — pick cards below</span>
              : cards.map((id) => (
                <span key={id} className="compare-chip">
                  {names[id] ?? id}
                  <button
                    type="button"
                    aria-label={`Remove ${names[id] ?? id} from portfolio ${i + 1}`}
                    onClick={() => onToggleCard(i, id)}
                  >
                    ✕
                  </button>
                </span>
              ))}
          </div>
        ))}
      </div>
      <ManualGrid
        selected={new Set(portfolios[activeIdx])}
        excluded={excluded}
        onToggle={(id) => onToggleCard(activeIdx, id)}
        onToggleExclude={onToggleExclude}
      />
    </div>
  )
}
