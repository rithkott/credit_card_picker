import type { Config } from '../types'
import type { UserState } from '../lib/profile'

interface Props {
  config: Config
  user: UserState
  onChange: (patch: Partial<UserState>) => void
}

/** Maps to the profile's user block. Simplified per plan 08: credit tier
 * (defaulting to 'good'), what to optimize for, and the brand-restriction
 * question — portfolio size, point-valuation mode, and rotating activation
 * are no longer asked (fixed 1–3 escalation, average cpp, activation
 * assumed). The FICO bands in the hint are UI guidance only, not repo data. */
export function AboutYou({ config, user, onChange }: Props) {
  return (
    <section className="block">
      <h2>About you</h2>
      <div className="opts">
        <div className="field">
          <label htmlFor="tier">
            Credit tier
            <span className="hint">good ≈ FICO 670–739, very good ≈ 740–799 (guidance only)</span>
          </label>
          <select
            id="tier"
            value={user.credit_tier ?? 'good'}
            onChange={(e) => onChange({ credit_tier: e.target.value })}
          >
            {config.tier_order.map((t) => (
              <option key={t} value={t}>{t.replace('_', ' ')}</option>
            ))}
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
