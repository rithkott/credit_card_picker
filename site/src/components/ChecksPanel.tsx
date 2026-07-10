import type { Issue } from '../lib/validation'

/** Live E1–E5 errors; the run button is gated on errors being empty. Warnings
 * live in SpendEntry's totals footer (W1) — this panel is errors only. */
export function ChecksPanel({ errors }: { errors: Issue[] }) {
  if (errors.length === 0) return null
  return (
    <section className="block">
      {errors.map((e) => (
        <div key={e.code + e.message} className="issue error">✕ {e.message}</div>
      ))}
    </section>
  )
}
