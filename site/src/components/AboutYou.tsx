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
 * assumed). The FICO bands shown are UI guidance only, not repo data. */
const FICO_BANDS: Record<string, string> = {
  building: 'FICO < 580 / limited history',
  fair: 'FICO 580–669',
  good: 'FICO 670–739',
  very_good: 'FICO 740–799',
  excellent: 'FICO 800+',
}

export function AboutYou({ config, user, onChange }: Props) {
  const tier = user.credit_tier ?? 'good'
  return (
    <section className="block">
      <h2>About you</h2>
      <div className="opts">
        <div className="field">
          <label htmlFor="tier">
            Credit tier{FICO_BANDS[tier] && <span className="hint">· {FICO_BANDS[tier]}</span>}
          </label>
          <div className="select-wrap">
            <select
              id="tier"
              value={tier}
              onChange={(e) => onChange({ credit_tier: e.target.value })}
            >
              {config.tier_order.map((t) => (
                <option key={t} value={t}>
                  {t.replace('_', ' ')}{FICO_BANDS[t] ? ` · ${FICO_BANDS[t]}` : ''}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="optfor">
            Optimize for <span className="hint">· year 1 includes bonuses</span>
          </label>
          <div className="select-wrap">
            <select
              id="optfor"
              value={user.optimize_for}
              onChange={(e) => onChange({ optimize_for: e.target.value as UserState['optimize_for'] })}
            >
              <option value="ongoing">ongoing value</option>
              <option value="year1">year 1</option>
            </select>
          </div>
        </div>
      </div>
      <p className="lockin-q">
        Some cards earn points locked to one airline or hotel chain — often worth more, but
        only there. Include them?
      </p>
      <div className="chips md lockin-chips" role="radiogroup" aria-label="Brand restriction">
        <label className="chip">
          <input
            type="radio"
            name="lockin"
            checked={!user.accepts_brand_lockin}
            onChange={() => onChange({ accepts_brand_lockin: false })}
          />
          No — cash-equivalent rewards only
        </label>
        <label className="chip">
          <input
            type="radio"
            name="lockin"
            checked={user.accepts_brand_lockin}
            onChange={() => onChange({ accepts_brand_lockin: true })}
          />
          Yes, include single-brand cards
        </label>
      </div>
    </section>
  )
}
