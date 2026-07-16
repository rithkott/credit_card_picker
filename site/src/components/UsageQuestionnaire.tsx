import type { Config, UsageGroup } from '../types'
import { SectionIcon } from './SectionIcon'

/** One usage-question group as an inner glass panel — group name, a
 * selected-count badge in accent when >0, and the option chips (all of them;
 * they wrap — the design mock's "+ N more" condensation is mock-only).
 * Shared by the confirmed-usage questionnaire and the Brand loyalty block. */
export function UsageGroupPanel({ group, confirmed, onToggle }: {
  group: UsageGroup
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  const count = group.items.filter((it) => confirmed.has(it.key)).length
  return (
    <div className="ug-panel">
      <div className="ug-head">
        <span className="ug-title">{group.label}</span>
        {count > 0 && <span className="ug-count">{count} selected</span>}
      </div>
      <div className="chips">
        {group.items.map((it) => (
          <label key={it.key} className="chip">
            <input
              type="checkbox"
              checked={confirmed.has(it.key)}
              onChange={(e) => onToggle(it.key, e.target.checked)}
            />
            {it.label}
          </label>
        ))}
      </div>
    </div>
  )
}

/** Confirmed-usage questionnaire (plan 07): every option visible upfront.
 * Checked keys become user.confirmed_usage: they unlock merchant credits.
 * Airline and hotel groups (assumed_reward_kind) render in the Brand loyalty
 * block instead — brand usage there is assumed from reward preferences, so
 * this section only asks about habits the optimizer can't infer. (Issuer
 * travel portals are not asked about — the optimizer assumes you'd book
 * through the portal of whichever card you hold.) */
export function UsageQuestionnaire({ config, confirmed, onToggle }: {
  config: Config
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  return (
    <section className="block has-icon">
      <SectionIcon name="usage" />
      <h2>Things you already use (or would)</h2>
      <p className="why">
        Card credits only count if you'd <strong>actually use them</strong>. Anything
        unchecked is worth <strong className="why-emph">$0</strong>.
      </p>
      <div className="ug-grid">
        {config.usage_questions
          .filter((group) => !group.assumed_reward_kind)
          .map((group) => (
            <UsageGroupPanel
              key={group.key}
              group={group}
              confirmed={confirmed}
              onToggle={onToggle}
            />
          ))}
      </div>
    </section>
  )
}
