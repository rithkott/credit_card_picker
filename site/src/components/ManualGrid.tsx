import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { getCardsCached } from '../api'
import { issuerLabel, issuerMatchesAlias } from '../lib/issuers'
import { formatNumber } from '../lib/money'
import { PORT_COLORS } from '../lib/portfolios'
import type { CardSummary } from '../types'

type Phase =
  | { phase: 'loading' }
  | { phase: 'error' }
  | { phase: 'ready'; cards: CardSummary[] }

/** Manual mode (v1.7) card picker: every card as a translucent, selectable
 * tile, grouped by issuer like the Data sources tab. Controlled — selection
 * state lives in Home so the "Score selected" action can read it. Plain tiles,
 * no card art: name, annual fee, and rewards currency. No selection cap (v1.10).
 * A search field (v2.1) filters the list in place by card or company name
 * (common issuer nicknames like "amex" or "bofa" match too); the
 * whole list lives in a bounded, internally-scrolling well so it never runs off
 * the page. */
export function ManualGrid({ selected, excluded, onToggle, onToggleExclude, ownersOf }: {
  selected: Set<string>
  /** Cards vetoed from consideration (v2.5.0) — shown greyed with the ✕ lit;
   * the ✕ in each tile's corner toggles membership. */
  excluded: Set<string>
  onToggle: (id: string) => void
  onToggleExclude: (id: string) => void
  /** Compare mode (plan 20 workbench): card id → every owning portfolio index
   * ([] = unowned). When present, tiles swap the ✓ box for an ownership ring
   * + one corner P-tag per owner in that portfolio's identity color (a card
   * in several portfolios shows all of them; extra owners add concentric
   * rings), and issuer groups flatten to sticky letterheads (the compare well
   * provides the container). Manual mode (prop absent) is untouched. */
  ownersOf?: (id: string) => number[]
}) {
  const [state, setState] = useState<Phase>({ phase: 'loading' })
  const [query, setQuery] = useState('')

  useEffect(() => {
    getCardsCached()
      .then(({ cards }) => setState({ phase: 'ready', cards }))
      .catch(() => setState({ phase: 'error' }))
  }, [])

  const byIssuer = useMemo(() => {
    if (state.phase !== 'ready') return []
    const q = query.trim().toLowerCase()
    const match = (c: CardSummary) =>
      !q
      || c.name.toLowerCase().includes(q)
      || issuerLabel(c.issuer).toLowerCase().includes(q)
      || issuerMatchesAlias(c.issuer, q)
      || c.currency.program_label.toLowerCase().includes(q)
    const groups = new Map<string, CardSummary[]>()
    for (const c of state.cards) {
      if (!match(c)) continue
      const list = groups.get(c.issuer) ?? []
      list.push(c)
      groups.set(c.issuer, list)
    }
    for (const list of groups.values()) list.sort((a, b) => a.name.localeCompare(b.name))
    return [...groups.entries()].sort((a, b) =>
      issuerLabel(a[0]).localeCompare(issuerLabel(b[0])))
  }, [state, query])

  if (state.phase === 'loading') return <p style={{ opacity: 0.7 }}>Loading cards…</p>
  if (state.phase === 'error') return <p className="error">Couldn't load the card list.</p>

  const shown = byIssuer.reduce((n, [, cards]) => n + cards.length, 0)
  const total = state.cards.length

  return (
    <>
      <div className="manual-search">
        <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.2-3.2" />
        </svg>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search cards or companies…"
          aria-label="Search cards or companies"
        />
        {query && (
          <button type="button" className="search-clear" aria-label="Clear search"
            onClick={() => setQuery('')}>×</button>
        )}
        <div className="search-count">
          {query ? `${shown} of ${total} cards` : `${total} cards`}
        </div>
      </div>
      <div className="manual-grid">
        {byIssuer.length === 0 ? (
          <p className="manual-empty">No cards match “{query}”.</p>
        ) : byIssuer.map(([issuer, cards]) => (
        // Compare mode drops the raised .block per issuer — the darker well is
        // the container, and the letterhead h2 (with inline count) sticks to
        // the top of the scroll.
        <section className={ownersOf ? 'issuer-group' : 'block issuer-group'} key={issuer}>
          <h2>
            {issuerLabel(issuer)}
            {ownersOf && (
              <span className="count">{cards.length} card{cards.length === 1 ? '' : 's'}</span>
            )}
          </h2>
          <div className="tile-grid">
            {cards.map((c) => {
              const isSel = selected.has(c.id)
              const isExcl = excluded.has(c.id)
              const owners = ownersOf ? ownersOf(c.id) : []
              const owned = owners.length > 0
              return (
                // Wrapper div: the exclude ✕ can't nest inside the tile
                // <button>, so it sits as an absolutely-positioned sibling.
                <div
                  key={c.id}
                  className={`tile-wrap${isExcl ? ' excluded' : ''}${owned ? ' owned' : ''}`}
                  style={owned
                    ? { '--tags-w': `${owners.length * 28 + (owners.length - 1) * 4}px` } as CSSProperties
                    : undefined}
                >
                  <button
                    type="button"
                    className={`card-tile selectable${ownersOf
                      ? (owned ? ' owned' : '')
                      : (isSel ? ' selected' : '')}`}
                    style={owned
                      ? {
                        // Owners beyond the first ring inward, concentrically,
                        // via the ::after/::before inset borders (owners 2–3;
                        // a 4th owner still gets its P-tag).
                        '--owner-color': PORT_COLORS[owners[0]],
                        '--owner-color-2': owners.length > 1 ? PORT_COLORS[owners[1]] : undefined,
                        '--owner-color-3': owners.length > 2 ? PORT_COLORS[owners[2]] : undefined,
                      } as CSSProperties
                      : undefined}
                    aria-pressed={isSel}
                    disabled={isExcl}
                    onClick={() => onToggle(c.id)}
                  >
                    {!ownersOf && <span className="check" aria-hidden="true">{isSel ? '✓' : ''}</span>}
                    {owned && (
                      <span className="tile-owner-tags" aria-hidden="true">
                        {owners.map((o) => (
                          <span
                            key={o}
                            className="tile-owner-tag"
                            style={{ '--owner-color': PORT_COLORS[o] } as CSSProperties}
                          >
                            P{o + 1}
                          </span>
                        ))}
                      </span>
                    )}
                    <h3>
                      {c.name}
                      {c.availability === 'discontinued' && (
                        <span className="badge-discontinued" title="No longer open to new applicants — pick it here only if you already hold it.">Discontinued</span>
                      )}
                      {isExcl && <span className="badge-excluded">Excluded</span>}
                    </h3>
                    <div className="role">
                      {c.annual_fee_usd > 0
                        ? <><span className="fee-amount">${formatNumber(c.annual_fee_usd)}</span> annual fee</>
                        : c.required_membership
                          ? <><span className="fee-amount">${formatNumber(c.required_membership.annual_cost_usd)}</span>/yr {c.required_membership.name} membership{c.required_membership.assumed_held ? ' (assumed held)' : ''}</>
                          : 'No annual fee'}
                      {' · '}{c.currency.program_label}
                    </div>
                  </button>
                  <button
                    type="button"
                    className="tile-x"
                    aria-pressed={isExcl}
                    aria-label={isExcl
                      ? `Consider ${c.name} again`
                      : `Exclude ${c.name} from consideration`}
                    title={isExcl
                      ? 'Excluded — click to consider this card again'
                      : "Don't consider this card"}
                    onClick={() => onToggleExclude(c.id)}
                  >
                    ✕
                  </button>
                </div>
              )
            })}
          </div>
        </section>
        ))}
      </div>
    </>
  )
}
