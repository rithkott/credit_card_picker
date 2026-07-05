import type { Config } from '../types'
import type { UserState } from '../lib/profile'

interface Props {
  config: Config
  user: UserState
  onChange: (patch: Partial<UserState>) => void
}

/** Maps 1:1 to the profile's user block. credit_tier deliberately has no
 * default — it is the one field the form cannot guess (plan 03 §3.4). The
 * FICO bands in the hint are UI guidance only, not repo data. */
export function AboutYou({ config, user, onChange }: Props) {
  return (
    <section className="block">
      <h2>About you</h2>
      <div className="opts">
        <div className="field">
          <label htmlFor="tier">
            Credit tier *
            <span className="hint">very good ≈ FICO 740–799 (guidance only)</span>
          </label>
          <select
            id="tier"
            value={user.credit_tier ?? ''}
            onChange={(e) => onChange({ credit_tier: e.target.value || null })}
          >
            <option value="">— select —</option>
            {config.tier_order.map((t) => (
              <option key={t} value={t}>{t.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mode">
            Point valuation
            <span className="hint">floor = guaranteed cash value; optimistic = transfer-partner value</span>
          </label>
          <select
            id="mode"
            value={user.valuation_mode}
            onChange={(e) => onChange({ valuation_mode: e.target.value as UserState['valuation_mode'] })}
          >
            <option value="floor">floor</option>
            <option value="optimistic">optimistic</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="maxcards">
            Max cards
            <span className="hint">portfolio size to search up to</span>
          </label>
          <select
            id="maxcards"
            value={user.max_cards}
            onChange={(e) => onChange({ max_cards: Number(e.target.value) })}
          >
            {Array.from(
              { length: config.max_cards_range[1] - config.max_cards_range[0] + 1 },
              (_, i) => config.max_cards_range[0] + i,
            ).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="optfor">
            Optimize for
            <span className="hint">ongoing = steady-state yearly value; year 1 includes signup bonuses</span>
          </label>
          <select
            id="optfor"
            value={user.optimize_for}
            onChange={(e) => onChange({ optimize_for: e.target.value as UserState['optimize_for'] })}
          >
            <option value="ongoing">ongoing</option>
            <option value="year1">year 1</option>
          </select>
        </div>
      </div>
      <div style={{ marginTop: '0.8em' }}>
        <label className="chip">
          <input
            type="checkbox"
            checked={user.activates_rotating}
            onChange={(e) => onChange({ activates_rotating: e.target.checked })}
          />
          I activate rotating 5% categories each quarter
        </label>
      </div>
      <div style={{ marginTop: '0.8em' }}>
        <p className="why" style={{ marginBottom: '0.3em' }}>
          Some cards earn points that only redeem with one company (an airline's miles, a hotel
          chain's points) — often worth more per point, but you're locked to that brand.
          Are you OK being restricted to a single company to maximize point output?
        </p>
        <div className="chips" role="radiogroup" aria-label="Brand restriction">
          <label className="chip">
            <input
              type="radio"
              name="lockin"
              checked={!user.accepts_brand_lockin}
              onChange={() => onChange({ accepts_brand_lockin: false })}
            />
            No — only cards whose rewards can always be taken as cash
          </label>
          <label className="chip">
            <input
              type="radio"
              name="lockin"
              checked={user.accepts_brand_lockin}
              onChange={() => onChange({ accepts_brand_lockin: true })}
            />
            Yes — include single-brand cards too
          </label>
        </div>
      </div>
    </section>
  )
}
