import type { OptimizeBundle } from '../../types'

/** Never a silent drop: every excluded/pruned card and its reason, one
 * disclosure away. */
export function ExcludedPruned({ bundle }: { bundle: OptimizeBundle }) {
  if (bundle.excluded.length === 0 && bundle.pruned.length === 0) return null
  return (
    <details className="disclosure">
      <summary>
        <span>
          {bundle.excluded.length} cards were excluded and {bundle.pruned.length} pruned
          — every single reason is listed
        </span>
        <span className="spacer" />
        <span className="show">show</span>
      </summary>
      <div className="body reason-list">
        {bundle.excluded.map((e) => (
          <div key={`x-${e.id}`}>{e.id}: {e.reason}</div>
        ))}
        {bundle.pruned.map((p) => (
          <div key={`p-${p.id}`}>{p.id}: {p.reason}</div>
        ))}
      </div>
    </details>
  )
}
