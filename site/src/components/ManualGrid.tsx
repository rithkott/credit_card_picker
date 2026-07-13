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
 * no card art: name, annual fee, and rewards currency. */
export function ManualGrid({ selected, max, onToggle }: {
  selected: Set<string>
  max: number
  onToggle: (id: string) => void
}) {
  const [state, setState] = useState<Phase>({ phase: 'loading' })

  useEffect(() => {
    getCards()
      .then(({ cards }) => setState({ phase: 'ready', cards }))
      .catch(() => setState({ phase: 'error' }))
  }, [])

  const byIssuer = useMemo(() => {
    if (state.phase !== 'ready') return []
    const groups = new Map<string, CardSummary[]>()
    for (const c of state.cards) {
      const list = groups.get(c.issuer) ?? []
      list.push(c)
      groups.set(c.issuer, list)
    }
    for (const list of groups.values()) list.sort((a, b) => a.name.localeCompare(b.name))
    return [...groups.entries()].sort((a, b) =>
      issuerLabel(a[0]).localeCompare(issuerLabel(b[0])))
  }, [state])

  if (state.phase === 'loading') return <p style={{ opacity: 0.7 }}>Loading cards…</p>
  if (state.phase === 'error') return <p className="error">Couldn't load the card list.</p>

  const atMax = selected.size >= max

  return (
    <div className="manual-grid">
      {byIssuer.map(([issuer, cards]) => (
        <section className="block issuer-group" key={issuer}>
          <h2>{issuerLabel(issuer)}</h2>
          <div className="tile-grid">
            {cards.map((c) => {
              const isSel = selected.has(c.id)
              // Block selecting past the cap, but always allow deselecting.
              const disabled = !isSel && atMax
              return (
                <button
                  type="button"
                  key={c.id}
                  className={`card-tile selectable${isSel ? ' selected' : ''}`}
                  aria-pressed={isSel}
                  disabled={disabled}
                  onClick={() => onToggle(c.id)}
                >
                  <span className="check" aria-hidden="true">{isSel ? '✓' : ''}</span>
                  <h3>{c.name}</h3>
                  <div className="role">
                    {c.annual_fee_usd > 0
                      ? <><span className="fee-amount">${formatNumber(c.annual_fee_usd)}</span> annual fee</>
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
  )
}
