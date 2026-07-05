import type { OptimizeBundle } from '../../types'

/** Every judgment call behind a recommendation, verbatim from the engine —
 * the transparency disclosure (docs/architecture.md invariant 7). */
export function PolicyConstants({ bundle }: { bundle: OptimizeBundle }) {
  return (
    <details className="disclosure">
      <summary>assumptions: policy constants & point valuations</summary>
      <pre>{JSON.stringify(
        { policy_constants: bundle.policy_constants, cpp_table: bundle.cpp_table },
        null,
        2,
      )}</pre>
    </details>
  )
}
