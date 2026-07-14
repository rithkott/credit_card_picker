import type { Assignment, PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'
import { assignmentDrop } from '../../lib/worstCase'

export function AssignmentsTable({ assignments, currencyKind, worstCaseFloorCpp = null }: {
  assignments: Assignment[]
  currencyKind: PerCard['currency']['kind']
  /** When set, re-price points at this cash-out floor cpp (worst-case toggle). */
  worstCaseFloorCpp?: number | null
}) {
  if (assignments.length === 0) return null
  const points = currencyKind === 'points'
  const floor = worstCaseFloorCpp
  const cppOf = (a: Assignment): number => (floor !== null ? floor : a.cpp)
  const valueOf = (a: Assignment): number =>
    floor !== null ? a.usd_value - assignmentDrop(a, floor) : a.usd_value
  return (
    <div className="assign-scroll">
      <table className="assign">
      <thead>
        <tr>
          <th>spend bucket</th>
          <th>rate</th>
          <th>spend</th>
          {points && <th>points</th>}
          <th>value/yr</th>
        </tr>
      </thead>
      <tbody>
        {assignments.map((a, i) => {
          const frac = a.eligible_fraction ? `1⁄${Math.round(1 / a.eligible_fraction)}` : null
          const spend = a.eligible_fraction ? Math.round(a.usd_assigned / a.eligible_fraction) : a.usd_assigned
          return (
          <tr key={`${a.bucket}-${i}`}>
            <td>
              {a.bucket}
              {a.note && <div className="note">{a.note}</div>}
            </td>
            <td>
              {points ? <>{a.rate}x @ {cppOf(a)}¢/pt</> : <>{a.rate}%</>}
              {frac && <span className="frac"> × {frac}</span>}
            </td>
            <td>{formatUsd(spend)}</td>
            {points && <td>{formatNumber(Math.round(a.usd_assigned * a.rate))}</td>}
            <td>{formatUsd(valueOf(a))}</td>
          </tr>
        )})}
      </tbody>
      </table>
    </div>
  )
}
