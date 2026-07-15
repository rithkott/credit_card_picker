import type { CSSProperties } from 'react'
import type { OptimizeBundle, PerCard } from '../../types'
import { CardDetail } from './CardDetail'

/** per_card keys are engine variant ids — a choose-your-own card renders as
 * "base-id[option]". Exclusion works on the physical card, so strip the
 * variant suffix before touching the excluded set. */
export function baseId(id: string): string {
  return id.replace(/\[[^\]]*\]$/, '')
}

/** One portfolio's math tiles. Max 3 tiles per row: chunk the ids into rows
 * of ≤3, each its own subgrid. One flat grid can't wrap — every tile's
 * `grid-row: 1 / -1` pins it to the same 12 bands, forcing a single row that
 * overflows. `--cols` = the full-row column count (min(total, 3)); every row
 * sizes its tracks to that so tiles are the SAME width across rows, and a
 * short trailing row centres its tiles at that width. `--tiles` = tiles in
 * this row (the repeat count). Shared by ResultsView and CompareResults. */
export function ResultTiles({ cardIds, perCard, cppTable, worstCase, addedCard, excluded, onToggleExclude }: {
  cardIds: string[]
  perCard: Record<string, PerCard>
  cppTable: OptimizeBundle['cpp_table']
  worstCase: boolean
  /** Improve path: the server-suggested addition — its tile gets a badge. */
  addedCard?: string
  excluded?: Set<string>
  onToggleExclude?: (id: string) => void
}) {
  const cols = Math.min(cardIds.length, 3)
  const rows: string[][] = []
  for (let i = 0; i < cardIds.length; i += 3) rows.push(cardIds.slice(i, i + 3))
  return (
    <>
      {rows.map((row, ri) => (
        <div
          className="tile-grid results-tiles"
          key={ri}
          style={{ '--cols': cols, '--tiles': row.length } as CSSProperties}
        >
          {row.map((id) => (
            <CardDetail
              key={id}
              id={id}
              card={perCard[id]}
              cppTable={cppTable}
              worstCase={worstCase}
              suggested={id === addedCard}
              isExcluded={excluded?.has(baseId(id)) ?? false}
              onToggleExclude={onToggleExclude ? () => onToggleExclude(baseId(id)) : undefined}
            />
          ))}
        </div>
      ))}
    </>
  )
}
