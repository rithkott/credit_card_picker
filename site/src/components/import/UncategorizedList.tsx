import type { ConfigCategory } from '../../types'
import type { UncatGroup } from '../../lib/statements/types'
import { annualize } from '../../lib/statements/annualize'
import { formatUsd } from '../../lib/money'

/** Unrecognized merchants, grouped by descriptor stem, each with a category
 * picker. Labeled groups (explicitly-unmapped registry keys — Bilt rent,
 * Venmo) are never auto-folded into 'other'; everything else is, and the
 * copy says so. Negative groups are unmatched refunds — assigning them
 * subtracts from that category. */
export function UncategorizedList({ categories, groups, coverageDays, assignments, onAssign }: {
  categories: ConfigCategory[]
  groups: UncatGroup[]
  coverageDays: number
  assignments: Record<string, string>
  onAssign: (stem: string, category: string) => void
}) {
  if (groups.length === 0) return null
  return (
    <div className="uncat">
      <h3>Not recognized — your call</h3>
      <p className="why">
        Unassigned merchants below count into "Everything else" when you apply —
        except the flagged ones (like rent), which stay out unless you place them.
      </p>
      {groups.map((g) => (
        <div key={g.stem} className="uncat-row">
          <span className="uncat-name">
            {g.label !== undefined && <span className="uncat-flag">{g.label}</span>}
            {g.label === undefined && g.stem}
            <span className="line-note">
              {' '}×{g.count} · {formatUsd(annualize(g.rawCents, coverageDays) / 100)}/yr
              {g.rawCents < 0 && ' (refund)'}
            </span>
          </span>
          <select
            value={assignments[g.stem] ?? ''}
            aria-label={`Category for ${g.label ?? g.stem}`}
            onChange={(e) => onAssign(g.stem, e.target.value)}
          >
            <option value="">{g.label !== undefined ? 'leave out' : 'everything else'}</option>
            {categories.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}
