import type { Config } from '../types'

/** Confirmed-usage questionnaire (plan 07): every option visible upfront as a
 * checkbox chip under its group's "do you (or will you) use these" prompt —
 * nothing hidden behind gate questions. Single-item groups render one chip
 * labeled by the prompt itself. Checked keys become user.confirmed_usage:
 * they unlock merchant credits, portal earn rates, and airline/hotel point
 * value. */
export function UsageQuestionnaire({ config, confirmed, onToggle }: {
  config: Config
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  const chip = (key: string, label: string) => (
    <label key={key} className="chip">
      <input
        type="checkbox"
        checked={confirmed.has(key)}
        onChange={(e) => onToggle(key, e.target.checked)}
      />
      {label}
    </label>
  )
  return (
    <section className="block">
      <h2>Things you use or will use</h2>
      <p className="why">
        Unlocks card credits, portal earn rates, and airline/hotel point value — anything you
        don't check counts $0, so recommendations never assume habits you don't have.
      </p>
      {config.usage_questions.map((group) => (
        <div key={group.key} className="ug">
          {group.items.length === 1 ? (
            <div className="chips">{chip(group.items[0].key, group.prompt)}</div>
          ) : (
            <>
              <div className="ug-prompt">
                <b>{group.label}</b> — {group.prompt}
              </div>
              <div className="chips">{group.items.map((it) => chip(it.key, it.label))}</div>
            </>
          )}
        </div>
      ))}
    </section>
  )
}
