import type { Config } from '../types'
import { UsageGroupPanel } from './UsageQuestionnaire'

/** Brand-loyalty block: the airline and hotel groups from usage-questions.yaml
 * (the ones carrying assumed_reward_kind), split out of the usage
 * questionnaire. Whether you fly or stay in hotels at all is already answered
 * by the reward-priority checkboxes — the optimizer assumes you'd book
 * whichever brand gives the best value, so brand credits count without any
 * boxes checked here. Checking a brand declares loyalty: it unlocks that
 * program's higher point valuation and full credit capture. */
export function BrandLoyalty({ config, confirmed, onToggle }: {
  config: Config
  confirmed: Set<string>
  onToggle: (key: string, on: boolean) => void
}) {
  const groups = config.usage_questions.filter((g) => g.assumed_reward_kind)
  if (groups.length === 0) return null
  return (
    <section className="block">
      <h2>Any loyalty to airlines or hotels?</h2>
      <p className="why">
        Since you'd book whichever airline or hotel gives the best value, their perks
        already count when flights or hotels are among your priorities above. Loyalty to
        a specific brand does more: its points are valued at their higher loyalty rate,
        and its credits count at full capture. Skip this if you just chase the best deal.
      </p>
      <div className="ug-grid">
        {groups.map((group) => (
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
