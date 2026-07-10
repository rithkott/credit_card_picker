import { useEffect, useState } from 'react'
import { getAssumptions } from '../api'
import type { AssumptionProgram } from '../types'

const REPO = 'https://github.com/rithkott/credit_card_picker'

const KIND_LABELS: Record<string, string> = {
  cashback: 'cash back',
  flights: 'flights',
  hotels: 'hotels',
}

type Phase =
  | { phase: 'loading' }
  | { phase: 'error' }
  | { phase: 'ready'; programs: AssumptionProgram[] }

function cpp(n: number): string {
  return `${n}¢`
}

export function Assumptions() {
  const [state, setState] = useState<Phase>({ phase: 'loading' })

  useEffect(() => {
    getAssumptions()
      .then(({ programs }) => setState({ phase: 'ready', programs }))
      .catch(() => setState({ phase: 'error' }))
  }, [])

  return (
    <div className="content-page">
      <div className="hero compact">
        <h1>
          What a point is <span className="shimmer-text">assumed to be worth</span>
        </h1>
        <p className="sub">
          Every points card references this one shared table — there is no per-card tuning.
          These are the exact numbers the optimizer uses, served from the same file it reads.
        </p>
      </div>

      <section className="block prose">
        <h2>How to read the numbers</h2>
        <p>
          Each rewards program gets two anchors, in cents per point. The <strong>floor</strong>{' '}
          is conservative: what you can always get, typically cash-out or statement credit
          (for currencies with no cash path, the most conservative realistic redemption
          instead). The <strong>optimistic</strong> value is the realistic upside through
          transfer partners or portal boosts — not aspirational first-class-suite math.
        </p>
        <p>
          The optimizer values points at the <strong>average of the two</strong>, with two
          honesty rules. If the upside requires a specific gateway card (Chase Freedom points
          only reach transfer partners through a Sapphire), the average applies only when the
          scored portfolio contains such a card. And if a currency has no cash path at all —
          airline miles, hotel points — the optimizer uses the floor unless you confirmed the
          matching loyalty habit, because a Delta mile is only worth 1.3¢ to someone who
          actually flies Delta.
        </p>
        <p className="src-link">
          The source file, with a cited rationale on every line:{' '}
          <a href={`${REPO}/blob/main/data/meta/point-valuations.yaml`} target="_blank" rel="noreferrer">
            data/meta/point-valuations.yaml on GitHub
          </a>
        </p>
      </section>

      {state.phase === 'loading' && <p style={{ textAlign: 'center' }}>Loading the valuation table…</p>}
      {state.phase === 'error' && (
        <p style={{ textAlign: 'center' }}>
          Couldn't reach the optimizer API — valuations are served from it so this page can
          never drift from what's actually used.
        </p>
      )}

      {state.phase === 'ready' && (
        <section className="block">
          <div className="panel-head">
            <h2>Point valuations</h2>
            <span className="optional">{state.programs.length} programs · US cents per point</span>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Program</th>
                  <th>Floor</th>
                  <th>Optimistic</th>
                  <th>Good for</th>
                  <th>Conditions</th>
                </tr>
              </thead>
              <tbody>
                {state.programs.map((p) => (
                  <tr key={p.key}>
                    <td>{p.label}</td>
                    <td className="num">{cpp(p.floor_cpp)}</td>
                    <td className="num">{cpp(p.optimistic_cpp)}</td>
                    <td>
                      {p.redeems_for.length === 0
                        ? <span className="dim">merchant-restricted</span>
                        : p.redeems_for.map((k) => KIND_LABELS[k] ?? k).join(', ')}
                    </td>
                    <td className="dim">
                      {[
                        p.transfer_gateway_required ? 'upside needs a gateway card' : null,
                        p.loyalty_keys.length > 0 ? 'upside needs confirmed loyalty' : null,
                      ].filter(Boolean).join(' · ') || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
