import { useMemo, useRef, useState } from 'react'
import type { Config } from '../../types'
import { createParseSession } from '../../lib/statements'
import type { ParseBatchResult, ParseSession } from '../../lib/statements'
import { aggregate } from '../../lib/statements/aggregate'
import type { DetectionResult } from '../../lib/statements/types'
import { FileDrop } from './FileDrop'
import { UsageSuggestions } from './UsageSuggestions'
import { SectionIcon } from '../SectionIcon'

/** Statement benefit detection (plan 14): upload CSV/OFX/PDF statement
 * exports one at a time to the API, which parses them in memory, stores
 * nothing, and returns only the transactions that match a benefit-relevant
 * service (statement-descriptors.yaml). Confirmed keys merge into the usage
 * questionnaire on Apply — spending itself is entered manually below. */

type Phase =
  | { phase: 'idle' }
  | { phase: 'parsing'; done: number; total: number; current?: string }
  | { phase: 'detected'; batch: ParseBatchResult; result: DetectionResult }
  | { phase: 'applied'; summary: string }

export function StatementImport({ config, onApply }: {
  config: Config
  onApply: (usageKeys: string[]) => void
}) {
  const [state, setState] = useState<Phase>({ phase: 'idle' })
  const [usageChecks, setUsageChecks] = useState<Record<string, boolean>>({})
  // One session per import: extra drops while parsing (or from the detected
  // screen) join it, so dedupe and the file cap span every drop. Cleared on
  // discard/apply so the next import starts fresh.
  const sessionRef = useRef<ParseSession | null>(null)

  const usageItems = useMemo(
    () => config.usage_questions.flatMap((g) => g.items), [config])

  const reset = () => {
    sessionRef.current = null
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
    }
    session.add(inputs)
    const batch = await session.settled()
    if (sessionRef.current !== session) return // discarded mid-parse
    const result = aggregate(batch.files, usageItems)
    // Suggestions start checked; the user unchecks what they don't use. When
    // a later drop re-aggregates, choices already made on earlier suggestions
    // are kept.
    setUsageChecks((prev) => Object.fromEntries(
      result.usageSuggestions.map((s) => [s.key, prev[s.key] ?? true])))
    setState({ phase: 'detected', batch, result })
  }

  const apply = () => {
    if (state.phase !== 'detected') return
    const usageKeys = state.result.usageSuggestions
      .filter((s) => usageChecks[s.key]).map((s) => s.key)
    const summary = `${usageKeys.length} service(s) confirmed from ` +
      `${state.batch.files.length} statement file(s)`
    onApply(usageKeys)
    sessionRef.current = null
    setState({ phase: 'applied', summary }) // raw result dropped from memory
  }

  return (
    <section className="block has-icon">
      <SectionIcon name="document" />
      <div className="panel-head">
        <h2>Spot benefits in your statements <span className="optional">optional</span></h2>
        <span className="spacer" />
        <span className="privacy-pill">
          <span className="dot" />
          Parsed in memory, never stored — files are discarded right after parsing
        </span>
      </div>
      <p className="why">
        Drop in bank statements — we&apos;ll spot services you already pay for that{' '}
        <strong>unlock card credits</strong> below.{' '}
        <strong className="why-emph">Files are parsed in memory and never stored</strong>
        — only matched services come back.
      </p>

      {state.phase !== 'applied' && (
        <FileDrop
          progress={state.phase === 'parsing' ? state : null}
          addMore={state.phase === 'detected'}
          onFiles={onFiles}
        />
      )}

      {state.phase === 'detected' && (
        <>
          <div className="file-chips">
            {state.batch.files.map((f) => (
              <span key={f.summary.name} className="file-chip">
                {f.summary.name} · {f.summary.txns} txns
                {f.summary.rangeStart !== '' &&
                  ` · ${f.summary.rangeStart} → ${f.summary.rangeEnd}`}
              </span>
            ))}
            {state.batch.duplicates.map((name) => (
              <span key={name} className="file-chip muted">{name} · duplicate, skipped</span>
            ))}
            {state.batch.errors.map((e) => (
              <span key={e.name} className="file-chip error" title={e.message}>
                {e.name} · {e.message}
              </span>
            ))}
          </div>
          <p className="coverage">
            {state.batch.files.length} file(s) · {state.result.coverageDays} days of
            activity — detected amounts are scaled to a 12-month year
          </p>
          {state.result.warnings.map((w, i) => (
            <p key={`${w.code}-${i}`} className="issue warning">{w.message}</p>
          ))}
          {state.result.usageSuggestions.length > 0 ? (
            <UsageSuggestions
              suggestions={state.result.usageSuggestions}
              checks={usageChecks}
              onCheck={(key, on) => setUsageChecks((u) => ({ ...u, [key]: on }))}
            />
          ) : (
            <p className="why">
              <strong>No benefit-relevant services found.</strong> Fill in the
              questionnaire below by hand.
            </p>
          )}
          <div className="runbar inline">
            <button
              type="button"
              className="primary"
              onClick={apply}
              disabled={state.result.usageSuggestions.length === 0}
            >
              Confirm checked services
            </button>
            <button type="button" onClick={reset}>
              Discard
            </button>
          </div>
        </>
      )}

      {state.phase === 'applied' && (
        <div className="runbar inline">
          <span className="status">{state.summary} — checked in the questionnaire below.</span>
          <button type="button" onClick={reset}>
            Scan again
          </button>
        </div>
      )}
    </section>
  )
}
