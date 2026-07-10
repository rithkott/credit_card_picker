import { useMemo, useState } from 'react'
import type { Config } from '../../types'
import type { SpendState } from '../../lib/validation'
import { parseFiles } from '../../lib/statements'
import type { ParseBatchResult } from '../../lib/statements'
import { aggregate, applyReview, toSpendState } from '../../lib/statements/aggregate'
import { compileRules } from '../../lib/statements/categorize'
import type { ImportResult } from '../../lib/statements/types'
import { FileDrop } from './FileDrop'
import { ImportReview } from './ImportReview'

/** Statement import (plan 09): upload CSV/OFX/PDF statement exports, parse
 * them ENTIRELY in this browser tab, review the categorized annual totals,
 * then apply them to the form. Owns all import state; the app only receives
 * the final onApply payload. Raw transactions are dropped on apply/cancel. */

type Phase =
  | { phase: 'idle' }
  | { phase: 'parsing'; count: number }
  | { phase: 'review'; batch: ParseBatchResult; result: ImportResult }
  | { phase: 'applied'; summary: string }

export function StatementImport({ config, formNonEmpty, onApply }: {
  config: Config
  formNonEmpty: boolean
  onApply: (spend: SpendState, usageKeys: string[]) => void
}) {
  const [state, setState] = useState<Phase>({ phase: 'idle' })
  const [assignments, setAssignments] = useState<Record<string, string>>({})
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set())
  const [usageChecks, setUsageChecks] = useState<Record<string, boolean>>({})

  const usageItems = useMemo(
    () => config.usage_questions.flatMap((g) => g.items), [config])
  const matcher = useMemo(
    () => compileRules(config.statement_import, config.merchants, usageItems),
    [config, usageItems])

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return
    setState({ phase: 'parsing', count: files.length })
    setAssignments({})
    setExcluded(new Set())
    try {
      const inputs = await Promise.all(files.map(async (f) => ({
        name: f.name, bytes: new Uint8Array(await f.arrayBuffer()),
      })))
      const batch = await parseFiles(inputs)
      const result = aggregate(batch.files, matcher)
      // Suggestions start checked; the user unchecks what they don't use.
      setUsageChecks(Object.fromEntries(result.usageSuggestions.map((s) => [s.key, true])))
      setState({ phase: 'review', batch, result })
    } finally {
      // The worker that saw statement bytes dies with the batch.
      const { terminatePdfWorker } = await import('../../lib/statements/pdf')
      await terminatePdfWorker()
    }
  }

  const apply = () => {
    if (state.phase !== 'review') return
    const partial = toSpendState(state.result, assignments, excluded, config.merchants)
    // Detected keys overlay a fully-blank form: Apply replaces, never merges.
    const spend: SpendState = {
      categoryCents: {
        ...Object.fromEntries(config.categories.map((c) => [c.key, null])),
        ...partial.categoryCents,
      },
      merchantCents: {
        ...Object.fromEntries(config.merchants.map((m) => [m.key, null])),
        ...partial.merchantCents,
      },
    }
    const usageKeys = state.result.usageSuggestions
      .filter((s) => usageChecks[s.key]).map((s) => s.key)
    const summary = `Imported from ${state.batch.files.length} statement file(s) · ` +
      `${state.result.coverageDays} days of activity`
    onApply(spend, usageKeys)
    setState({ phase: 'applied', summary }) // raw result dropped from memory
  }

  const reviewTotals = useMemo(() => {
    if (state.phase !== 'review') return null
    return applyReview(state.result, assignments, excluded, config.merchants)
  }, [state, assignments, excluded, config.merchants])

  return (
    <section className="block">
      <div className="panel-head">
        <h2>Start from your statements <span className="optional">optional</span></h2>
        <span className="spacer" />
        <span className="privacy-pill">
          <span className="dot" />
          Parsed on your device — statements are never uploaded
        </span>
      </div>
      <p className="why">
        Already have credit or debit cards? Download statements from your bank and drop them
        in — the spending form below fills itself. Only the totals you approve go into the form.
      </p>

      {(state.phase === 'idle' || state.phase === 'parsing') && (
        <FileDrop parsing={state.phase === 'parsing'} onFiles={onFiles} />
      )}

      {state.phase === 'review' && reviewTotals !== null && (
        <>
          <ImportReview
            config={config}
            batch={state.batch}
            result={state.result}
            totals={reviewTotals}
            assignments={assignments}
            excluded={excluded}
            usageChecks={usageChecks}
            onAssign={(stem, category) =>
              setAssignments((a) => {
                const next = { ...a }
                if (category === '') delete next[stem]
                else next[stem] = category
                return next
              })}
            onExclude={(category, off) =>
              setExcluded((prev) => {
                const next = new Set(prev)
                if (off) next.add(category)
                else next.delete(category)
                return next
              })}
            onUsageCheck={(key, on) => setUsageChecks((u) => ({ ...u, [key]: on }))}
          />
          <div className="runbar inline">
            <button type="button" className="primary" onClick={apply}>
              Apply to the form
            </button>
            <button type="button" onClick={() => setState({ phase: 'idle' })}>
              Discard
            </button>
            {formNonEmpty && (
              <span className="warn-note">This replaces the amounts already entered below.</span>
            )}
          </div>
        </>
      )}

      {state.phase === 'applied' && (
        <div className="runbar inline">
          <span className="status">{state.summary} — applied to the form below.</span>
          <button type="button" onClick={() => setState({ phase: 'idle' })}>
            Import again
          </button>
        </div>
      )}
    </section>
  )
}
