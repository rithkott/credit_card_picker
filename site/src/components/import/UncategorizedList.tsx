import type { ConfigCategory } from '../../types'
import type { UncatGroup } from '../../lib/statements/types'
import { annualize } from '../../lib/statements/annualize'
import { formatUsd } from '../../lib/money'

/** Unrecognized merchants, grouped by descriptor stem, each with a category
 * picker. Labeled groups (explicitly-unmapped registry keys — Bilt rent,
 * Venmo) are never auto-folded into 'other'; everything else is, and the
 * copy says so. Negative groups are unmatched refunds — assigning them
 * subtracts from that category.
 *
 * Suggestions (v1.3.0): unmatched groups usually carry the semantic model's
 * below-gate top-1 guess. Unassigned rows show it as a one-click "use" chip,
 * and "Accept all guesses" fills every unassigned suggestion at once — the
 * user confirms instead of hand-indexing. Guesses never apply themselves.
 *
 * Materiality (plan 13): minor unlabeled groups (under 0.1% of total spend
 * each) don't get their own ask — they're summarized in a collapsed section
 * and fold into 'Everything else'. The silent fold-in is bounded (aggregate
 * MISC_CAP_PCT): when the tail sums to real money, the largest tail groups
 * are promoted into the asked list above. */
export function UncategorizedList({ categories, groups, coverageDays, assignments, onAssign, onAssignMany }: {
  categories: ConfigCategory[]
  groups: UncatGroup[]
  coverageDays: number
  assignments: Record<string, string>
  onAssign: (stem: string, category: string) => void
  onAssignMany: (next: Record<string, string>) => void
}) {
  if (groups.length === 0) return null
  const asked = groups.filter((g) => !g.minor)
  const minor = groups.filter((g) => g.minor)
  const minorAnnual = minor.reduce((s, g) => s + annualize(g.rawCents, coverageDays), 0)
  const labelOf = new Map(categories.map((c) => [c.key, c.label]))

  const askedPending = Object.fromEntries(
    asked
      .filter((g) => g.suggestion !== undefined && assignments[g.stem] === undefined)
      .map((g) => [g.stem, g.suggestion!.category]))
  const askedPendingCount = Object.keys(askedPending).length

  const row = (g: UncatGroup) => (
    <div key={g.stem} className="uncat-row">
      <span className="uncat-name">
        {g.label !== undefined && <span className="uncat-flag">{g.label}</span>}
        {g.label === undefined && g.stem}
        <span className="line-note">
          {' '}×{g.count} · {formatUsd(annualize(g.rawCents, coverageDays) / 100)}/yr
          {g.rawCents < 0 && ' (refund)'}
        </span>
        {g.example !== undefined && g.example.toUpperCase().trim() !== g.stem && (
          <span className="line-note uncat-example"> e.g. “{g.example}”</span>
        )}
        {g.suggestion !== undefined && assignments[g.stem] === undefined && (
          <button
            type="button"
            className="uncat-guess"
            onClick={() => onAssign(g.stem, g.suggestion!.category)}
          >
            guess: {labelOf.get(g.suggestion.category) ?? g.suggestion.category}
            {' '}· {Math.round(g.suggestion.confidence * 100)}% — use
          </button>
        )}
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
  )

  return (
    <div className="uncat">
      {asked.length > 0 && (
        <>
          <div className="panel-head">
            <h3>Not recognized — your call</h3>
            <span className="spacer" />
            {askedPendingCount > 0 && (
              <button
                type="button"
                className="uncat-accept-all"
                onClick={() => onAssignMany(askedPending)}
              >
                Accept all {askedPendingCount} guesses
              </button>
            )}
          </div>
          <p className="why">
            Unassigned merchants below count into "Everything else" when you apply —
            except the flagged ones (like rent), which stay out unless you place them.
            Guesses are the model's best idea; nothing counts until you accept it.
          </p>
          {asked.map(row)}
        </>
      )}
      {minor.length > 0 && (
        <details className="uncat-minor">
          <summary className="line-note">
            {minor.length} small merchant{minor.length === 1 ? '' : 's'} (each under 0.1% of
            your spending, {formatUsd(minorAnnual / 100)}/yr together) will count as
            "Everything else" — open to review or place them.
          </summary>
          {minor.map(row)}
        </details>
      )}
    </div>
  )
}
