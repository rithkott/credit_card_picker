/** Aggregation: parsed files -> DetectionResult (plan 14, detection-only).
 *
 * The server already did the matching — only usage-item hits arrive. This
 * module sums them per usage key (refunds subtract), annualizes over the
 * merged date coverage, and emits the warnings that still matter for a
 * detection pass. There is no category aggregation, no review edits, and no
 * spend payload: spending is entered manually in the form.
 */

import { annualize, mergeIntervals, MIN_COVERAGE_DAYS } from './annualize'
import type { UsageItem } from '../../types'
import type { DetectionResult, ImportWarning, ParsedFile, UsageSuggestion } from './types'

export function aggregate(files: ParsedFile[], usageItems: UsageItem[]): DetectionResult {
  const usageLabels = new Map(usageItems.map((i) => [i.key, i.label]))
  const rawUsage: Record<string, number> = {}
  const wireLabels: Record<string, string> = {}
  const warnings: ImportWarning[] = []

  for (const file of files) {
    for (const txn of file.matches) {
      rawUsage[txn.usageKey] = (rawUsage[txn.usageKey] ?? 0) + txn.amountCents
      wireLabels[txn.usageKey] = txn.usageLabel
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
    // Parse-path disclosures (plan 12): the parse worked, but through a
    // guessing path the user should know about.
    if (file.summary.columnInference?.used) {
      warnings.push({
        code: 'I-inferred-columns',
        message:
          `${file.summary.name}: the column layout wasn't recognized, so the ` +
          `columns were inferred from their content — detected amounts may be off.`,
      })
    }
    if (file.summary.extraction === 'layout') {
      warnings.push({
        code: 'I-layout',
        message:
          `${file.summary.name}: transactions were read from the PDF's column ` +
          `geometry (the usual line patterns didn't match) — detected amounts may be off.`,
      })
    }
  }

  const { days, overlaps } = mergeIntervals(
    files.map((f) => ({ start: f.summary.rangeStart, end: f.summary.rangeEnd })))
  if (days < MIN_COVERAGE_DAYS) {
    warnings.push({
      code: 'W-coverage',
      message:
        `Only ${days} day(s) of statements — annualized amounts extrapolate a lot ` +
        `from that; import ~2+ months for steadier numbers.`,
    })
  }
  if (overlaps) {
    warnings.push({
      code: 'W-overlap',
      message:
        'Statement date ranges overlap — if two files cover the same account ' +
        'and period, detected amounts are counted twice.',
    })
  }
  const rejected = files.reduce((s, f) => s + f.summary.rejectedRows, 0)
  if (rejected > 0) {
    warnings.push({
      code: 'W-rows',
      message: `${rejected} row(s) couldn't be parsed and were skipped.`,
    })
  }

  const usageSuggestions: UsageSuggestion[] = Object.entries(rawUsage)
    .map(([key, raw]) => ({
      key,
      // The config label wins when present (it is what the questionnaire
      // shows); the wire label covers a mid-config-fetch render.
      label: usageLabels.get(key) ?? wireLabels[key] ?? key,
      annualCents: Math.max(0, annualize(raw, days)),
    }))
    .filter((s) => s.annualCents > 0)
    .sort((a, b) => b.annualCents - a.annualCents || (a.key < b.key ? -1 : 1))

  return {
    usageSuggestions,
    coverageDays: days,
    files: files.map((f) => f.summary),
    warnings,
  }
}
