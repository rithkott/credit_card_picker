/** Aggregation: parsed files -> ImportResult for the review screen
 * (plan 09, commit 4/5; server-side matches since plan 12).
 *
 * Categorization happens on the server — every transaction arrives with its
 * `match` already attached; this module only reduces. Only purchases and
 * refunds reach spend buckets (refunds subtract); payments/fees/interest/
 * transfers accumulate in excludedCents so the review screen can show what
 * was ignored. Where a statement printed its own summary box (PDFs), parsed
 * sums are reconciled against it and a mismatch warns — a silent partial
 * parse must never masquerade as a complete one.
 */

import { annualize, mergeIntervals, MIN_COVERAGE_DAYS } from './annualize'

/** A merchant group below this share of total annualized spend is folded
 * into 'Everything else' without asking (plan 13 — don't interrupt the user
 * for charges that can't change the recommendation). */
export const MATERIALITY_PCT = 0.001

/** Hard bound on the SILENT fold-in: when minor groups together exceed this
 * share of total annualized spend, the largest are promoted back to asked
 * rows until the remainder fits. Keeps "Everything else" from quietly
 * swallowing a long tail that sums to real money. */
export const MISC_CAP_PCT = 0.02
import { formatUsd } from '../money'
import type { SpendState } from '../validation'
import type { ConfigMerchant, UsageItem } from '../../types'
import type { ImportResult, ImportWarning, ParsedFile, TxnKind, UncatGroup } from './types'

export function aggregate(
  files: ParsedFile[], merchants: ConfigMerchant[], usageItems: UsageItem[],
): ImportResult {
  const merchantByKey = new Map(merchants.map((m) => [m.key, m]))
  const usageLabels = new Map(usageItems.map((i) => [i.key, i.label]))
  const rawCategory: Record<string, number> = {}
  const rawMerchant: Record<string, number> = {}
  const rawUsage: Record<string, number> = {}
  const groups = new Map<string, UncatGroup>()
  const excludedCents: Partial<Record<TxnKind, number>> = {}
  const warnings: ImportWarning[] = []
  let fuzzyCount = 0
  let fuzzyCents = 0
  let semanticCount = 0
  let semanticCents = 0

  for (const file of files) {
    const fileSums: Record<'purchases' | 'paymentsAndCredits' | 'fees' | 'interest' | 'transfers', number> =
      { purchases: 0, paymentsAndCredits: 0, fees: 0, interest: 0, transfers: 0 }

    for (const txn of file.txns) {
      if (txn.kind === 'payment' || txn.kind === 'refund') {
        fileSums.paymentsAndCredits += Math.abs(txn.amountCents)
      } else if (txn.kind === 'fee') fileSums.fees += Math.abs(txn.amountCents)
      else if (txn.kind === 'interest') fileSums.interest += Math.abs(txn.amountCents)
      else if (txn.kind === 'transfer') fileSums.transfers += Math.abs(txn.amountCents)
      else if (txn.kind === 'purchase') fileSums.purchases += txn.amountCents

      if (txn.kind !== 'purchase' && txn.kind !== 'refund') {
        excludedCents[txn.kind] = (excludedCents[txn.kind] ?? 0) + Math.abs(txn.amountCents)
        continue
      }

      const match = txn.match
      if (match.category !== null) {
        rawCategory[match.category] = (rawCategory[match.category] ?? 0) + txn.amountCents
        if (match.method === 'fuzzy') {
          fuzzyCount++
          fuzzyCents += txn.amountCents
        } else if (match.method === 'semantic') {
          semanticCount++
          semanticCents += txn.amountCents
        }
        if (match.merchantKey !== undefined) {
          // Defensive: tally the carve-out only when the bridge category is
          // the merchant's declared parent, else E3 (carve-out <= parent)
          // could break if the two registries ever drift.
          const merchant = merchantByKey.get(match.merchantKey)
          if (merchant !== undefined && merchant.category === match.category) {
            rawMerchant[match.merchantKey] = (rawMerchant[match.merchantKey] ?? 0) + txn.amountCents
          }
        }
        if (match.usageKey !== undefined) {
          rawUsage[match.usageKey] = (rawUsage[match.usageKey] ?? 0) + txn.amountCents
        }
      } else {
        const key = match.descriptorKey ?? match.stem
        const group = groups.get(key) ?? {
          stem: key,
          ...(match.descriptorLabel !== undefined ? { label: match.descriptorLabel } : {}),
          count: 0,
          rawCents: 0,
          example: txn.descriptor,
        }
        group.count++
        group.rawCents += txn.amountCents
        // Below-gate semantic top-1 pre-fills the group's picker. Same stem ⇒
        // same model output, so first-non-null is stable; labeled policy
        // groups (rent, Venmo) never get one — those are the user's call.
        if (group.suggestion === undefined && group.label === undefined
            && match.suggestion !== undefined) {
          group.suggestion = match.suggestion
        }
        groups.set(key, group)
      }
    }

    if ((file.summary.periodCount ?? 0) > 1) {
      warnings.push({
        code: 'W-multi-statement',
        message:
          `${file.summary.name} looks like several statements combined into one ` +
          `PDF — transaction dates and totals can't be trusted; upload the ` +
          `individual monthly statements instead.`,
      })
    }

    // Semantic-layer disclosures (plan 12): the parse worked, but through a
    // guessing path the user should know about when checking the review.
    if (file.summary.columnInference?.used) {
      warnings.push({
        code: 'I-inferred-columns',
        message:
          `${file.summary.name}: the column layout wasn't recognized, so the ` +
          `columns were inferred from their content — double-check the totals.`,
      })
    }
    if (file.summary.extraction === 'layout') {
      warnings.push({
        code: 'I-layout',
        message:
          `${file.summary.name}: transactions were read from the PDF's column ` +
          `geometry (the usual line patterns didn't match) — double-check the totals.`,
      })
    }

    // Reconcile against the statement's own printed totals (PDF summary box).
    const declared = file.summary.statementTotals
    if (declared !== undefined) {
      const checks: [string, number | undefined, number][] = [
        ['purchases', declared.purchasesCents, fileSums.purchases],
        ['payments and credits', declared.paymentsAndCreditsCents, fileSums.paymentsAndCredits],
        ['fees', declared.feesCents, fileSums.fees],
        ['interest', declared.interestCents, fileSums.interest],
      ]
      for (const [what, stated, parsed] of checks) {
        // Some issuers fold balance transfers into their printed "purchases"
        // total (Bilt's "Including New Card Purchases"); we exclude transfers
        // from spend, so either reading reconciles.
        if (what === 'purchases' && stated !== undefined
            && stated === parsed + fileSums.transfers) continue
        if (stated !== undefined && stated !== parsed) {
          warnings.push({
            code: 'W-reconcile',
            message:
              `${file.summary.name}: parsed ${what} total ${formatUsd(parsed / 100)} ` +
              `but the statement says ${formatUsd(stated / 100)} — some transactions ` +
              `were likely missed; double-check against the CSV export.`,
          })
        }
      }
    }
  }

  const { days, overlaps } = mergeIntervals(
    files.map((f) => ({ start: f.summary.rangeStart, end: f.summary.rangeEnd })))
  if (days < MIN_COVERAGE_DAYS) {
    warnings.push({
      code: 'W-coverage',
      message:
        `Only ${days} day(s) of statements — annualized totals extrapolate a lot ` +
        `from that; import ~2+ months for steadier numbers.`,
    })
  }
  if (overlaps) {
    warnings.push({
      code: 'W-overlap',
      message:
        'Statement date ranges overlap — if two files cover the same account ' +
        'and period, that spend is counted twice.',
    })
  }
  const rejected = files.reduce((s, f) => s + f.summary.rejectedRows, 0)
  if (rejected > 0) {
    warnings.push({
      code: 'W-rows',
      message: `${rejected} row(s) couldn't be parsed and were skipped.`,
    })
  }
  if (fuzzyCount > 0) {
    warnings.push({
      code: 'I-fuzzy',
      message:
        `${fuzzyCount} transaction(s) (${formatUsd(Math.abs(fuzzyCents) / 100)} over the ` +
        `covered period) were categorized by approximate name match — worth a ` +
        `glance in the totals below.`,
    })
  }
  if (semanticCount > 0) {
    warnings.push({
      code: 'I-semantic',
      message:
        `${semanticCount} transaction(s) (${formatUsd(Math.abs(semanticCents) / 100)} over the ` +
        `covered period) were categorized by meaning ("JOE'S DELI" → dining) — ` +
        `only confident matches are placed; the rest are listed below for you.`,
    })
  }

  const categoryCents: Record<string, number> = {}
  for (const [cat, raw] of Object.entries(rawCategory)) {
    const cents = Math.max(0, annualize(raw, days))
    if (cents > 0) categoryCents[cat] = cents
  }
  const merchantCents: Record<string, number> = {}
  for (const [key, raw] of Object.entries(rawMerchant)) {
    const parent = merchantByKey.get(key)!.category
    // Parent may have been clamped to 0 by refunds elsewhere in its category;
    // cap the carve-out so E3 holds unconditionally.
    const cents = Math.min(Math.max(0, annualize(raw, days)), categoryCents[parent] ?? 0)
    if (cents > 0) merchantCents[key] = cents
  }

  // Materiality (plan 13): total annualized spend = categorized + every
  // uncategorized group; a group under 0.1% of it isn't worth interrupting the
  // user for — it folds into 'Everything else' via the existing Apply path.
  const uncategorized = [...groups.values()]
    .filter((g) => g.rawCents !== 0)
    .sort((a, b) => b.rawCents - a.rawCents || (a.stem < b.stem ? -1 : 1))
  const totalAnnualCents = Object.values(categoryCents).reduce((s, c) => s + c, 0)
    + uncategorized.reduce((s, g) => s + Math.abs(annualize(g.rawCents, days)), 0)
  for (const g of uncategorized) {
    if (g.label === undefined
        && Math.abs(annualize(g.rawCents, days)) < MATERIALITY_PCT * totalAnnualCents) {
      g.minor = true
    }
  }

  // The per-group gate alone is unbounded: a year of statements can hold
  // hundreds of sub-0.1% merchants that together dump thousands into
  // 'Everything else' unseen. Cap the SILENT fold-in at MISC_CAP_PCT of
  // total spend by promoting the largest minor groups back to asked rows
  // (they arrive pre-filled with suggestions, so promotion costs the user
  // ~one click). Deterministic: uncategorized is already sorted by spend
  // desc with a stem tie-break.
  let minorTotal = uncategorized.reduce(
    (s, g) => s + (g.minor ? Math.abs(annualize(g.rawCents, days)) : 0), 0)
  for (const g of uncategorized) {
    if (minorTotal <= MISC_CAP_PCT * totalAnnualCents) break
    if (g.minor !== true) continue
    g.minor = false
    minorTotal -= Math.abs(annualize(g.rawCents, days))
  }

  return {
    categoryCents,
    merchantCents,
    // Net-negative groups stay visible: an unmatched refund (a returned
    // flight whose refund descriptor matches nothing) must reduce SOME
    // bucket, or every total quietly overstates. The user can assign it;
    // unassigned ones subtract from 'other' on Apply.
    uncategorized,
    usageSuggestions: Object.entries(rawUsage)
      .map(([key, raw]) => ({
        key,
        label: usageLabels.get(key) ?? key,
        annualCents: Math.max(0, annualize(raw, days)),
      }))
      .filter((s) => s.annualCents > 0)
      .sort((a, b) => b.annualCents - a.annualCents || (a.key < b.key ? -1 : 1)),
    coverageDays: days,
    files: files.map((f) => f.summary),
    warnings,
    excludedCents,
  }
}

export interface ReviewOutcome {
  categoryCents: Record<string, number>
  merchantCents: Record<string, number>
  leftoverGroups: UncatGroup[]
}

/** Review-screen edits, pure: reassigned uncategorized groups move their
 * annualized value into a category; excluded categories drop entirely (with
 * their carve-outs). Always derived fresh from the base result so edits are
 * order-independent. */
export function applyReview(
  base: ImportResult,
  assignments: Record<string, string>,
  excludedCategories: ReadonlySet<string>,
  merchants: ConfigMerchant[],
): ReviewOutcome {
  const categoryCents = { ...base.categoryCents }
  const leftoverGroups: UncatGroup[] = []
  for (const group of base.uncategorized) {
    const target = assignments[group.stem]
    if (target !== undefined && !excludedCategories.has(target)) {
      // Negative groups (unmatched refunds) legitimately subtract.
      categoryCents[target] = (categoryCents[target] ?? 0)
        + annualize(group.rawCents, base.coverageDays)
    } else if (target === undefined) {
      leftoverGroups.push(group)
    }
  }
  for (const [cat, cents] of Object.entries(categoryCents)) {
    if (cents <= 0) delete categoryCents[cat]
  }
  for (const cat of excludedCategories) delete categoryCents[cat]

  const parentOf = new Map(merchants.map((m) => [m.key, m.category]))
  const merchantCents: Record<string, number> = {}
  for (const [key, cents] of Object.entries(base.merchantCents)) {
    const parent = parentOf.get(key)
    if (parent === undefined || excludedCategories.has(parent)) continue
    const capped = Math.min(cents, categoryCents[parent] ?? 0)
    if (capped > 0) merchantCents[key] = capped
  }
  return { categoryCents, merchantCents, leftoverGroups }
}

/** Apply-button payload: the reviewed totals as form SpendState. Leftover
 * UNLABELED groups (unknown merchants nobody reassigned) fold into 'other' —
 * the UI says so; labeled groups (explicitly-unmapped registry keys like Bilt
 * rent) are never auto-dumped anywhere: the user assigns them or they stay
 * out. Only detected keys are present; the caller blanks the rest. */
export function toSpendState(
  base: ImportResult,
  assignments: Record<string, string>,
  excludedCategories: ReadonlySet<string>,
  merchants: ConfigMerchant[],
): SpendState {
  const { categoryCents, merchantCents, leftoverGroups } =
    applyReview(base, assignments, excludedCategories, merchants)
  if (!excludedCategories.has('other')) {
    // Positive leftovers add to 'other'; negative ones (unmatched refunds)
    // subtract from it, clamped at zero — never negative spend.
    const leftoverRaw = leftoverGroups
      .filter((g) => g.label === undefined)
      .reduce((s, g) => s + g.rawCents, 0)
    const cents = Math.max(0, (categoryCents['other'] ?? 0) + annualize(leftoverRaw, base.coverageDays))
    if (cents > 0) categoryCents['other'] = cents
    else delete categoryCents['other']
  }
  return { categoryCents, merchantCents }
}
