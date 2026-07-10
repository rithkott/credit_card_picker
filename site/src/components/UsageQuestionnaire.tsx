import type { Config } from '../types'

/** Confirmed-usage questionnaire (plan 07): every option visible upfront.
 * Each group renders as its own inner glass panel in a 2-col grid — group
 * name, a selected-count badge in accent when >0, and the option chips
 * (all of them; they wrap — the design mock's "+ N more" condensation is
 * mock-only). Checked keys become user.confirmed_usage: they unlock merchant
 * credits and airline/hotel point value. */
export function UsageQuestionnaire({ config, confirmed, onToggle }: {
  config: Config
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  return (
    <section className="block">
      <h2>Things you already use (or would)</h2>
      <p className="why">
        Card credits and airline or hotel points only count if you'd actually
        use them. Anything unchecked is valued at $0 — so the results never assume habits you
        don't have.
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
