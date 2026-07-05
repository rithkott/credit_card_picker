import type { CreditLine } from '../../types'
import { formatUsd } from '../../lib/money'

/** Every credit is listed, including $0 lines — their notes say exactly which
 * confirmation (or spend) would unlock them, the plan-07 self-explaining
 * output contract. */
export function CreditsList({ credits }: { credits: CreditLine[] }) {
  if (credits.length === 0) return null
  return (
    <div>
      {credits.map((c, i) => (
        <div key={`${c.name}-${i}`} className={c.value === 0 ? 'credit-zero' : ''}>
          credit: {c.name} = {formatUsd(c.value)}{' '}
          <span className="line-note">[{c.note}]</span>
        </div>
      ))}
    </div>
  )
}
