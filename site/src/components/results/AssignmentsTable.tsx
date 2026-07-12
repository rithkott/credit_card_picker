import type { Assignment, PerCard } from '../../types'
import { formatNumber, formatUsd } from '../../lib/money'

export function AssignmentsTable({ assignments, currencyKind }: {
  assignments: Assignment[]
  currencyKind: PerCard['currency']['kind']
}) {
  if (assignments.length === 0) return null
  const points = currencyKind === 'points'
  return (
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
        {assignments.map((a, i) => (
          <tr key={`${a.bucket}-${i}`}>
            <td>
              {a.bucket}
              {a.note && <div className="note">{a.note}</div>}
            </td>
            <td>
              {points ? <>{a.rate}x @ {a.cpp}¢/pt</> : <>{a.rate}%</>}
            </td>
            <td>{formatUsd(a.usd_assigned)}</td>
            {points && <td>{formatNumber(Math.round(a.usd_assigned * a.rate))}</td>}
            <td>{formatUsd(a.usd_value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
