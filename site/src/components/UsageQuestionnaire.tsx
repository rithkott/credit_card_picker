import type { Config } from '../types'

/** Confirmed-usage questionnaire (plan 07): every option visible upfront.
 * Each group renders as its own titled panel in a responsive grid — group
 * name, the "do you (or will you) use these" prompt as a subline, a
 * selected-count badge, and the option chips contained inside — so ~60
 * options scan as ten labeled boxes instead of one long column. Checked keys
 * become user.confirmed_usage: they unlock merchant credits, portal earn
 * rates, and airline/hotel point value. */
export function UsageQuestionnaire({ config, confirmed, onToggle }: {
  config: Config
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  return (
    <section className="block">
      <h2>Things you use or will use</h2>
      <p className="why">
        Unlocks card credits, portal earn rates, and airline/hotel point value — anything you
        don't check counts $0, so recommendations never assume habits you don't have.
      </p>
      <div className="ug-grid">
        {config.usage_questions.map((group) => {
          const count = group.items.filter((it) => confirmed.has(it.key)).length
          return (
            <div key={group.key} className="ug-panel">
              <div className="ug-head">
                <span className="ug-title">{group.label}</span>
                {count > 0 && <span className="ug-count">{count} selected</span>}
              </div>
              <div className="ug-q">{group.prompt}</div>
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
        })}
      </div>
    </section>
  )
}
