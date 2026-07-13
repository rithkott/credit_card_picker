import type { OptimizeBundle } from '../../types'

const cpp = (n: number) => `${n.toFixed(2)}¢`

/** snake_case / SCREAMING_CASE → Title Case, for program ids, constant keys,
 * and category/tier list members. */
function humanize(key: string): string {
  return key
    .toLowerCase()
    .split('_')
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ')
}

/** Render one policy-constant value by its shape: prose strings are documented
 * formulas, arrays are humanized lists, objects are key/value pairs, everything
 * else prints verbatim. */
function ConstantValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return <span className="pc-list-inline">{value.map((v) => humanize(String(v))).join(', ')}</span>
  }
  if (value !== null && typeof value === 'object') {
    return (
      <span className="pc-pairs">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <span key={k} className="pc-pair">
            <span className="pc-pair-key">{k}</span>
            <span className="pc-pair-val">{String(v)}</span>
          </span>
        ))}
      </span>
    )
  }
  if (typeof value === 'string') {
    return <span className="pc-prose">{value}</span>
  }
  return <span className="pc-num">{String(value)}</span>
}

/** Every judgment call behind a recommendation, verbatim from the engine —
 * the transparency disclosure (docs/architecture.md invariant 7). */
export function PolicyConstants({ bundle }: { bundle: OptimizeBundle }) {
  const programs = Object.entries(bundle.cpp_table)
  const constants = Object.entries(bundle.policy_constants)
  return (
    <details className="disclosure">
      <summary>
        <span>Assumptions used in this run — point valuations, capture rates, policy constants</span>
        <span className="spacer" />
        <span className="show">show</span>
      </summary>
      <div className="body policy-body">
        <section className="pc-section">
          <h4 className="pc-head">
            Point valuations <span className="pc-unit">cents per point</span>
          </h4>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Program</th>
                  <th>Conservative</th>
                  <th>Assumed</th>
                  <th>Optimistic</th>
                </tr>
              </thead>
              <tbody>
                {programs.map(([key, v]) => (
                  <tr key={key}>
                    <td>{humanize(key)}</td>
                    <td className="num">{cpp(v.floor_cpp)}</td>
                    <td className="num">{cpp(v.avg_cpp)}</td>
                    <td className="num">{cpp(v.optimistic_cpp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="pc-section">
          <h4 className="pc-head">Policy constants</h4>
          <dl className="pc-list">
            {constants.map(([key, value]) => (
              <div key={key} className="pc-row">
                <dt>{humanize(key)}</dt>
                <dd>
                  <ConstantValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </details>
  )
}
