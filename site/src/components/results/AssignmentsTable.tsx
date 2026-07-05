import type { Assignment } from '../../types'
import { formatUsd } from '../../lib/money'

export function AssignmentsTable({ assignments }: { assignments: Assignment[] }) {
  if (assignments.length === 0) return null
  return (
    <table className="assign">
      <thead>
        <tr>
          <th>spend bucket</th>
          <th>rate</th>
          <th>assigned</th>
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
              {a.rate}x{a.cpp !== 1 && <> @ {a.cpp}cpp</>}
            </td>
            <td>{formatUsd(a.usd_assigned)}</td>
            <td>{formatUsd(a.usd_value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
