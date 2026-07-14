import { useEffect, useMemo, useState } from 'react'
import { getCards } from '../api'
import { issuerLabel } from '../lib/issuers'
import { formatNumber } from '../lib/money'
import type { CardSummary } from '../types'

type Phase =
  | { phase: 'loading' }
  | { phase: 'error' }
  | { phase: 'ready'; cards: CardSummary[] }

/** Manual mode (v1.7) card picker: every card as a translucent, selectable
 * tile, grouped by issuer like the Data sources tab. Controlled — selection
 * state lives in Home so the "Score selected" action can read it. Plain tiles,
 * no card art: name, annual fee, and rewards currency. No selection cap (v1.10).
 * A search field (v2.1) filters the list in place by card or company name; the
 * whole list lives in a bounded, internally-scrolling well so it never runs off
 * the page. */
export function ManualGrid({ selected, onToggle }: {
  selected: Set<string>
  onToggle: (id: string) => void
}) {
  const [state, setState] = useState<Phase>({ phase: 'loading' })
  const [query, setQuery] = useState('')

  useEffect(() => {
    getCards()
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
        <section className="block issuer-group" key={issuer}>
          <h2>{issuerLabel(issuer)}</h2>
          <div className="tile-grid">
            {cards.map((c) => {
              const isSel = selected.has(c.id)
              return (
                <button
                  type="button"
                  key={c.id}
                  className={`card-tile selectable${isSel ? ' selected' : ''}`}
                  aria-pressed={isSel}
                  onClick={() => onToggle(c.id)}
                >
                  <span className="check" aria-hidden="true">{isSel ? '✓' : ''}</span>
                  <h3>
                    {c.name}
                    {c.availability === 'discontinued' && (
                      <span className="badge-discontinued" title="No longer open to new applicants — pick it here only if you already hold it.">Discontinued</span>
                    )}
                  </h3>
                  <div className="role">
                    {c.annual_fee_usd > 0
                      ? <><span className="fee-amount">${formatNumber(c.annual_fee_usd)}</span> annual fee</>
                      : c.required_membership
                        ? <><span className="fee-amount">${formatNumber(c.required_membership.annual_cost_usd)}</span>/yr {c.required_membership.name}</>
                        : 'No annual fee'}
                    {' · '}{c.currency.program_label}
                  </div>
                </button>
              )
            })}
          </div>
        </section>
        ))}
      </div>
    </>
  )
}
