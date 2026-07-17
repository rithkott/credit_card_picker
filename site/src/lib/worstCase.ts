/** Worst-case (cash-out) points valuation — display-only (v1.11.14).
 *
 * The optimizer values points at the engaged average cpp
 * (avg = (floor_cpp + optimistic_cpp)/2). Some users will only ever cash out
 * points / take a statement credit, and want to see the floor of what their
 * points are worth. This module derives that worst case ENTIRELY in the UI, so
 * the recommended portfolio never changes — only the shown dollar figures drop.
 *
 * Every points value is `points × cpp/100`. Re-pricing at the program's
 * `floor_cpp` (already shipped in bundle.cpp_table) means subtracting a "drop":
 *   drop = points × (cpp − floor_cpp)/100 = usd_assigned × rate × (cpp − floor_cpp)/100
 * Cash rewards, and points already valued at their floor (cashback-only /
 * gated / fixed-value programs where cpp == floor_cpp), drop by 0.
 */
import type { Assignment, BestBySize, OptimizeBundle, PerCard } from '../types'

type CppTable = OptimizeBundle['cpp_table']

/** The cash-out floor cpp for a card's program; falls back to a no-op cpp when
 * the program is missing from the table (drop resolves to 0). */
export function floorCppOf(card: PerCard, cppTable: CppTable): number | null {
  return cppTable[card.currency.program]?.floor_cpp ?? null
}

/** Points actually earned on an assignment, derived from its value: rate ×
 * spend breaks on flat-floor lines (Bilt's 250 pts/cycle floor keeps rate at
 * the real 0× tier while the value comes from the floor points). */
export function assignmentPoints(a: { usd_value: number; cpp: number }): number {
  return a.cpp > 0 ? (a.usd_value * 100) / a.cpp : 0
}

/** Per-assignment value drop when switching to worst-case. Points lines only;
 * clamped >= 0 (a floor above the effective cpp never inflates the value). */
export function assignmentDrop(a: Assignment, floorCpp: number): number {
  const perPointDrop = (a.cpp - floorCpp) / 100
  if (perPointDrop <= 0) return 0
  return assignmentPoints(a) * perPointDrop
}

/** Sum of the worst-case drop across a card's spend-earned points. */
export function cardSpendDrop(card: PerCard, cppTable: CppTable): number {
  if (card.currency.kind !== 'points') return 0
  const floorCpp = floorCppOf(card, cppTable)
  if (floorCpp === null) return 0
  return card.assignments.reduce((s, a) => s + assignmentDrop(a, floorCpp), 0)
}

/** Worst-case drop on a card's signup bonus (points portion only). */
export function bonusDrop(card: PerCard): number {
  return Math.max(0, card.bonus.value - card.bonus.floor_value)
}

/** Total worst-case drop for a whole portfolio. Ongoing-net excludes the
 * signup bonus, so `includeBonus` is set only for the year-1 metric. */
export function entryDrop(
  entry: BestBySize,
  cppTable: CppTable,
  { includeBonus }: { includeBonus: boolean },
): number {
  return entry.cards.reduce((sum, id) => {
    const card = entry.per_card[id]
    if (!card) return sum
    return sum + cardSpendDrop(card, cppTable) + (includeBonus ? bonusDrop(card) : 0)
  }, 0)
}

/** Whether any shown card actually moves under worst-case — a points card whose
 * effective cpp sits above its floor (spend line or bonus). When false the
 * toggle is a pure no-op and is hidden. */
export function hasWorstCaseGap(entries: BestBySize[], cppTable: CppTable): boolean {
  return entries.some((e) =>
    entryDrop(e, cppTable, { includeBonus: true }) > 0.005)
}
