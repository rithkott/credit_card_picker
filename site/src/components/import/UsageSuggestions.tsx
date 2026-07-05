import type { UsageSuggestion } from '../../lib/statements/types'
import { formatUsd } from '../../lib/money'

/** Pre-checked confirmed-usage suggestions from detected spend ("we saw
 * $412/yr at Delta"). Checked keys are unioned into the questionnaire on
 * Apply — the optimizer only counts brand-locked value for services the
 * user actually confirms. */
export function UsageSuggestions({ suggestions, checks, onCheck }: {
  suggestions: UsageSuggestion[]
  checks: Record<string, boolean>
  onCheck: (key: string, on: boolean) => void
}) {
  if (suggestions.length === 0) return null
  return (
    <div className="usage-suggest">
      <h3>Services we spotted</h3>
      <p className="why">
        These unlock card credits and point value in the questionnaire below —
        uncheck anything you don't actually use.
      </p>
      <div className="chips">
        {suggestions.map((s) => (
          <label key={s.key} className="chip">
            <input
              type="checkbox"
              checked={checks[s.key] ?? false}
              onChange={(e) => onCheck(s.key, e.target.checked)}
            />
            {s.label} — {formatUsd(s.annualCents / 100)}/yr
          </label>
        ))}
      </div>
    </div>
  )
}
