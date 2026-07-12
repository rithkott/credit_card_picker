import type { Config } from '../types'
import type { UserState } from '../lib/profile'

interface Props {
  config: Config
  user: UserState
  onChange: (patch: Partial<UserState>) => void
}

/** Maps to the profile's user block. Simplified per plan 08, and further to a
 * single 720 threshold: most "excellent"-labeled cards actually approve around
 * 720, so gating them behind higher bands locked out cards that don't need it.
 * The two choices map to engine tiers — 720+ → 'excellent' (top rank, no tier
 * gating) and below 720 → 'good' (premium/very-good cards filtered out). */
const TIER_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: 'excellent', label: '720 or above', hint: 'unlocks every card here' },
  { value: 'good', label: 'Below 720', hint: 'a few premium cards may be out of reach' },
]

/** Collapse any stored engine tier into the two buckets. Anything at or above
 * "very good" reads as 720+; the rest (good / fair / building / unset→720+). */
function bucketOf(raw: string | null | undefined): string {
  return raw === 'good' || raw === 'fair' || raw === 'building' ? 'good' : 'excellent'
}

export function AboutYou({ config: _config, user, onChange }: Props) {
  const tier = bucketOf(user.credit_tier)
  const hint = TIER_OPTIONS.find((o) => o.value === tier)?.hint
  return (
    <section className="block">
      <h2>About you</h2>
      <div className="opts">
        <div className="field">
          <label htmlFor="tier">
            Credit score{hint && <span className="hint">· {hint}</span>}
          </label>
          <div className="select-wrap">
            <select
              id="tier"
              value={tier}
              onChange={(e) => onChange({ credit_tier: e.target.value })}
            >
              {TIER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
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
