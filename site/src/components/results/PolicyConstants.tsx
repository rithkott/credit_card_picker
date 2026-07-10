import type { OptimizeBundle } from '../../types'

/** Every judgment call behind a recommendation, verbatim from the engine —
 * the transparency disclosure (docs/architecture.md invariant 7). */
export function PolicyConstants({ bundle }: { bundle: OptimizeBundle }) {
  return (
    <details className="disclosure">
      <summary>
        <span>Assumptions used in this run — point valuations, capture rates, policy constants</span>
        <span className="spacer" />
        <span className="show">show</span>
      </summary>
      <div className="body">
        <pre>{JSON.stringify(
          { policy_constants: bundle.policy_constants, cpp_table: bundle.cpp_table },
          null,
          2,
        )}</pre>
      </div>
    </details>
  )
}
