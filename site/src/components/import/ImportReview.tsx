import type { Config } from '../../types'
import type { ParseBatchResult } from '../../lib/statements'
import type { ReviewOutcome } from '../../lib/statements/aggregate'
import type { ImportResult } from '../../lib/statements/types'
import { formatUsd } from '../../lib/money'
import { UncategorizedList } from './UncategorizedList'
import { UsageSuggestions } from './UsageSuggestions'

const usd = (cents: number) => formatUsd(cents / 100)

const KIND_LABELS: Record<string, string> = {
  payment: 'card payments',
  fee: 'fees',
  interest: 'interest',
  transfer: 'balance transfers / cash advances',
}

/** The review screen: what was parsed, how it categorized, and every lever
 * (exclude a category, reassign an unknown merchant, confirm usage) before
 * anything touches the form. */
export function ImportReview({
  config, batch, result, totals, assignments, excluded, usageChecks,
  onAssign, onAssignMany, onExclude, onUsageCheck,
}: {
  config: Config
  batch: ParseBatchResult
  result: ImportResult
  totals: ReviewOutcome
  assignments: Record<string, string>
  excluded: ReadonlySet<string>
  usageChecks: Record<string, boolean>
  onAssign: (stem: string, category: string) => void
  onAssignMany: (next: Record<string, string>) => void
  onExclude: (category: string, off: boolean) => void
  onUsageCheck: (key: string, on: boolean) => void
}) {
  const factor = result.coverageDays > 0 ? 365 / result.coverageDays : 0
  const excludedTotal = Object.values(result.excludedCents).reduce((s, c) => s + (c ?? 0), 0)
  // Rows: every category that has detected money (even if currently excluded),
  // ordered by the registry so the table matches the form below.
  const rows = config.categories.filter(
    (c) => totals.categoryCents[c.key] !== undefined || excluded.has(c.key))
  const merchantsByParent = new Map<string, [string, number][]>()
  for (const m of config.merchants) {
    const cents = totals.merchantCents[m.key]
    if (cents === undefined) continue
    merchantsByParent.set(m.category,
      [...(merchantsByParent.get(m.category) ?? []), [m.label, cents]])
  }

  return (
    <div className="import-review">
      <div className="file-chips">
        {batch.files.map((f) => (
          <span key={f.summary.name} className="file-chip">
            {f.summary.name} · {f.summary.txns} txns · {f.summary.rangeStart} → {f.summary.rangeEnd}
          </span>
        ))}
        {batch.duplicates.map((name) => (
          <span key={name} className="file-chip muted">{name} · duplicate, skipped</span>
        ))}
        {batch.errors.map((e) => (
          <span key={e.name} className="file-chip error" title={e.message}>
            {e.name} · {e.message}
          </span>
        ))}
      </div>

      <p className="coverage">
        {batch.files.length} file(s) · {result.coverageDays} days of activity — every
        total below is scaled to a 12-month year (×{factor.toFixed(1)})
      </p>
      {Object.entries(
        result.warnings.reduce<Record<string, typeof result.warnings>>((acc, w) => {
          (acc[w.code] ??= []).push(w)
          return acc
        }, {}),
      ).map(([code, ws]) => ws.length <= 3 ? (
        ws.map((w) => <p key={code + w.message} className="issue warning">{w.message}</p>)
      ) : (
        // Twelve near-identical reconcile warnings teach the user to ignore
        // warnings — collapse repeats of one code behind a single line.
        <details key={code} className="issue warning warning-group">
          <summary>{ws.length} files: {ws[0].message.replace(/^[^:]*: /, '')} (and similar) — details</summary>
          {ws.map((w) => <p key={w.message} className="issue warning">{w.message}</p>)}
        </details>
      ))}

      <table className="assign import-table">
        <thead>
          <tr><th>Include</th><th>Category</th><th>Detected annual spend</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const off = excluded.has(c.key)
            const cents = totals.categoryCents[c.key] ?? 0
            return (
              <tr key={c.key} className={off ? 'excluded' : undefined}>
                <td>
                  <input
                    type="checkbox"
                    checked={!off}
                    aria-label={`Include ${c.label}`}
                    onChange={(e) => onExclude(c.key, !e.target.checked)}
                  />
                </td>
                <td>
                  {c.label}
                  {(merchantsByParent.get(c.key) ?? []).map(([label, mCents]) => (
                    <div key={label} className="line-note">
                      ↳ {label}: {usd(mCents)} of it
                    </div>
                  ))}
                </td>
                <td>{off ? '—' : usd(cents)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <UncategorizedList
        categories={config.categories}
        groups={result.uncategorized}
        coverageDays={result.coverageDays}
        assignments={assignments}
        onAssign={onAssign}
        onAssignMany={onAssignMany}
      />

      <UsageSuggestions
        suggestions={result.usageSuggestions}
        checks={usageChecks}
        onCheck={onUsageCheck}
      />

      {excludedTotal > 0 && (
        <p className="line-note">
          Ignored (not spend):{' '}
          {Object.entries(result.excludedCents)
            .filter(([, c]) => (c ?? 0) > 0)
            .map(([kind, c]) => `${KIND_LABELS[kind] ?? kind} ${usd(c ?? 0)}`)
            .join(' · ')}
        </p>
      )}
    </div>
  )
}
