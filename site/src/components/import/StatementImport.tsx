import { useMemo, useRef, useState } from 'react'
import type { Config } from '../../types'
import type { SpendState } from '../../lib/validation'
import { createParseSession } from '../../lib/statements'
import type { ParseBatchResult, ParseSession } from '../../lib/statements'
import { aggregate, applyReview, toSpendState } from '../../lib/statements/aggregate'
import type { ImportResult } from '../../lib/statements/types'
import { FileDrop } from './FileDrop'
import { ImportReview } from './ImportReview'

/** Statement import (plan 09; server-side parsing since plan 12): upload
 * CSV/OFX/PDF statement exports one at a time to the API, which parses and
 * categorizes them in memory and stores nothing; review the annual totals in
 * this tab, then apply them to the form. Owns all import state; the app only
 * receives the final onApply payload. Raw transactions are dropped on
 * apply/cancel. */

type Phase =
  | { phase: 'idle' }
  | { phase: 'parsing'; done: number; total: number; current?: string }
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
  // One session per import: extra drops while parsing (or from the review
  // screen) join it, so dedupe and the file cap span every drop. Cleared on
  // discard/apply so the next import starts fresh.
  const sessionRef = useRef<ParseSession | null>(null)

  const usageItems = useMemo(
    () => config.usage_questions.flatMap((g) => g.items), [config])

  const reset = () => {
    sessionRef.current = null
    setAssignments({})
    setExcluded(new Set())
    setUsageChecks({})
    setState({ phase: 'idle' })
  }

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return
    const inputs = await Promise.all(files.map(async (f) => ({
      name: f.name, bytes: new Uint8Array(await f.arrayBuffer()),
    })))
    let session = sessionRef.current
    if (session === null) {
      session = createParseSession((done, total, current) =>
        setState({ phase: 'parsing', done, total, current }))
      sessionRef.current = session
      setAssignments({})
      setExcluded(new Set())
    }
    session.add(inputs)
    const batch = await session.settled()
    if (sessionRef.current !== session) return // discarded mid-parse
    const result = aggregate(batch.files, config.merchants, usageItems)
    // Suggestions start checked; the user unchecks what they don't use. When
    // a later drop re-aggregates, choices already made on earlier suggestions
    // are kept.
    setUsageChecks((prev) => Object.fromEntries(
      result.usageSuggestions.map((s) => [s.key, prev[s.key] ?? true])))
    setState({ phase: 'review', batch, result })
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
    sessionRef.current = null
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
          Parsed in memory, never stored — files are discarded right after parsing
        </span>
      </div>
      <p className="why">
        Already have credit or debit cards? Download statements from your bank and drop them
        in — each file is parsed by our server in memory and immediately discarded; nothing is
        saved or logged. The spending form below fills itself, and only the totals you approve
        go into it.
      </p>

      {state.phase !== 'applied' && (
        <FileDrop
          progress={state.phase === 'parsing' ? state : null}
          addMore={state.phase === 'review'}
          onFiles={onFiles}
        />
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
            onAssignMany={(entries) =>
              // Bulk "Accept all guesses": fills only unassigned stems — the
              // caller already excludes stems the user placed by hand.
              setAssignments((a) => ({ ...entries, ...a }))}
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
            <button type="button" onClick={reset}>
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
          <button type="button" onClick={reset}>
            Import again
          </button>
        </div>
      )}
    </section>
  )
}
