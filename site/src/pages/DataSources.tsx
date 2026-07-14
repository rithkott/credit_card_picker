import { useEffect, useMemo, useState } from 'react'
import { getCards } from '../api'
import { issuerLabel } from '../lib/issuers'
import type { CardSummary } from '../types'

const REPO = 'https://github.com/rithkott/credit_card_picker'

type Phase =
  | { phase: 'loading' }
  | { phase: 'error' }
  | { phase: 'ready'; cards: CardSummary[]; total: number }

export function DataSources() {
  const [state, setState] = useState<Phase>({ phase: 'loading' })

  useEffect(() => {
    getCards()
      .then(({ cards, total }) => setState({ phase: 'ready', cards, total }))
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
    return [...groups.entries()].sort((a, b) =>
      issuerLabel(a[0]).localeCompare(issuerLabel(b[0])))
  }, [state])

  return (
    <div className="content-page">
      <div className="hero compact">
        <h1>
          Every card, <span className="shimmer-text">every source</span>
        </h1>
        <p className="sub">
          The complete dataset the optimizer scores — one hand-written file per card, each
          one traceable to issuer terms, with its verification status shown honestly.
        </p>
      </div>

      <section className="block prose">
        <h2>How this data is maintained</h2>
        <p>
          Each card below is a YAML file in the public repository, transcribed from the
          issuer's terms sheet. Files marked <span className="conf conf-low">needs review</span>{' '}
          were drafted from offer documents and not yet re-confirmed line-by-line against the
          issuer's current published terms — the file itself says exactly which numbers are
          uncertain. Verified files have been checked by a human against issuer sources.
          A scheduled job flags data as it goes stale.
        </p>
        <p className="src-link">
          Browse the raw files (every number carries a comment citing its source):{' '}
          <a href={`${REPO}/tree/main/data/cards`} target="_blank" rel="noreferrer">
            data/cards on GitHub
          </a>
          {' '}· spotted an error?{' '}
          <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">report it</a>
        </p>
      </section>

      {state.phase === 'loading' && <p style={{ textAlign: 'center' }}>Loading the card list…</p>}
      {state.phase === 'error' && (
        <p style={{ textAlign: 'center' }}>
          Couldn't reach the optimizer API — the card list lives there so it can never drift
          from what's actually scored.
        </p>
      )}

      {state.phase === 'ready' && (
        <>
          <p className="dataset-count">
            {state.total} cards across {byIssuer.length} issuers
          </p>
          {byIssuer.map(([issuer, cards]) => (
            <section className="block issuer-group" key={issuer}>
              <div className="panel-head">
                <h2>{issuerLabel(issuer)}</h2>
                <span className="optional">{cards.length} {cards.length === 1 ? 'card' : 'cards'}</span>
              </div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Card</th>
                      <th>Annual fee</th>
                      <th>Rewards currency</th>
                      <th>Status</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cards.map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}</td>
                        <td className="num">
                          {c.annual_fee_usd > 0
                            ? `$${c.annual_fee_usd}`
                            : c.required_membership
                              ? <>${c.required_membership.annual_cost_usd}<span className="dim"> {c.required_membership.name}</span></>
                              : '$0'}
                        </td>
                        <td>{c.currency.program_label}</td>
                        <td>
                          {c.verification.confidence === 'low'
                            ? <span className="conf conf-low">needs review</span>
                            : <span className="conf conf-ok">
                                verified{c.verification.last_verified_date
                                  ? ` ${c.verification.last_verified_date}` : ''}
                              </span>}
                        </td>
                        <td>
                          <a
                            href={`${REPO}/blob/main/data/cards/${c.issuer}/${c.id}.yaml`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            card file
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  )
}
