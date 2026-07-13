import { Fragment, useEffect, useMemo, useState } from 'react'
import { ApiError, evaluateManual, optimize, suggestAddition } from '../api'
import type { OptimizeBundle } from '../types'
import { buildProfile } from '../lib/profile'
import { validate } from '../lib/validation'
import { useFormState } from '../hooks/useFormState'
import { ManualGrid } from '../components/ManualGrid'
import { AboutYou } from '../components/AboutYou'
import { BrandLoyalty } from '../components/BrandLoyalty'
import { ChecksPanel } from '../components/ChecksPanel'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { StatementImport } from '../components/import/StatementImport'
import { RentMortgage } from '../components/RentMortgage'
import { RewardPreferences } from '../components/RewardPreferences'
import { ServerBanner } from '../components/ServerBanner'
import { SpendEntry } from '../components/SpendEntry'
import { StartPage } from '../components/StartPage'
import { UsageQuestionnaire } from '../components/UsageQuestionnaire'
import { WizardShell, type WizardStep } from '../components/wizard/WizardShell'
import { ResultsView } from '../components/results/ResultsView'
import type { ConfigPhase } from '../App'

type RunPhase =
  | { phase: 'idle' }
  | { phase: 'running'; startedAt: number }
  | { phase: 'done'; bundle: OptimizeBundle }
  | { phase: 'error'; detail: string; unreachable: boolean }

export function Home({ cfg, onRetryConfig }: {
  cfg: ConfigPhase
  onRetryConfig: () => void
}) {
  const fs = useFormState()
  const { spend, setSpend, user, setUser, unit, setUnit, mode, setMode, selected, setSelected } = fs
  const [run, setRun] = useState<RunPhase>({ phase: 'idle' })
  const [elapsed, setElapsed] = useState(0)
  // First-run wizard step index. In-session only — a mid-wizard refresh restores
  // entered values but returns to step 0 (accepted tradeoff, keeps this simple).
  const [step, setStep] = useState(0)
  const [confirmReset, setConfirmReset] = useState(false)

  // Seed the option defaults the server declares (single source of truth) — but
  // only for fresh visitors. Returning users have restored values that this
  // effect would otherwise clobber.
  useEffect(() => {
    if (cfg.phase !== 'ready' || fs.restored) return
    setUser((u) => ({
      ...u,
      optimize_for: cfg.config.user_defaults.optimize_for,
      accepts_brand_lockin: cfg.config.user_defaults.accepts_brand_lockin,
    }))
  }, [cfg, fs.restored, setUser])

  // Reconcile persisted reward selections against the server's current
  // reward_kinds vocabulary: drop keys it no longer offers (a pre-v1.11
  // localStorage still holds flights/hotels, which parse_profile now rejects)
  // and default any newly-offered kind to on. Runs for restored users too —
  // that's the whole point. The equality guard keeps it from re-firing.
  useEffect(() => {
    if (cfg.phase !== 'ready') return
    const valid = cfg.config.reward_kinds
    setUser((u) => {
      const reconciled: Record<string, boolean> = {}
      for (const k of valid) reconciled[k] = u.rewardKinds[k] ?? true
      const unchanged = Object.keys(u.rewardKinds).length === valid.length
        && valid.every((k) => u.rewardKinds[k] === reconciled[k])
      return unchanged ? u : { ...u, rewardKinds: reconciled }
    })
  }, [cfg, setUser])

  useEffect(() => {
    if (run.phase !== 'running') return
    const timer = setInterval(
      () => setElapsed(Math.round((Date.now() - run.startedAt) / 1000)),
      1000,
    )
    return () => clearInterval(timer)
  }, [run])

  const categoryLabels = useMemo(() => {
    if (cfg.phase !== 'ready') return {}
    return Object.fromEntries(cfg.config.categories.map((c) => [c.key, c.label]))
  }, [cfg])

  const { errors, warnings } = useMemo(() => {
    if (cfg.phase !== 'ready') return { errors: [], warnings: [] }
    return validate(spend, cfg.config.merchants, user.credit_tier, user.rewardKinds, categoryLabels)
  }, [cfg, spend, user.credit_tier, user.rewardKinds, categoryLabels])

  // Shared by the Brand loyalty block and the usage questionnaire — both edit
  // the same user.confirmed_usage set (keys are globally unique across groups).
  const toggleUsage = (key: string, on: boolean) =>
    setUser((u) => {
      const next = new Set(u.confirmed_usage)
      if (on) next.add(key)
      else next.delete(key)
      return { ...u, confirmed_usage: next }
    })

  // Auto and Manual share the RunPhase lifecycle, error handling, and results
  // view — only the request differs (optimizer search vs. score-these-cards).
  const startRun = (req: Promise<OptimizeBundle>) => {
    setElapsed(0)
    setRun({ phase: 'running', startedAt: Date.now() })
    req
      .then((bundle) => setRun({ phase: 'done', bundle }))
      .catch((err) => {
        if (err instanceof ApiError) {
          setRun({ phase: 'error', detail: err.message, unreachable: false })
        } else {
          setRun({ phase: 'error', detail: String(err), unreachable: true })
        }
      })
  }

  const onRun = () => startRun(optimize(buildProfile(spend, user)))
  const onRunManual = () => startRun(evaluateManual(buildProfile(spend, user), [...selected]))

  // Best-additional-card (v1.10): ask the server for the best card to add to the
  // held set, check it in the grid, and show the augmented score — one action. Can't
  // reuse startRun() verbatim because of the extra setSelected side effect on success.
  const onAddBest = () => {
    setElapsed(0)
    setRun({ phase: 'running', startedAt: Date.now() })
    suggestAddition(buildProfile(spend, user), [...selected])
      .then((bundle) => {
        setSelected((prev) => new Set(prev).add(bundle.added_card))
        setRun({ phase: 'done', bundle })
      })
      .catch((err) => {
        if (err instanceof ApiError) {
          setRun({ phase: 'error', detail: err.message, unreachable: false })
        } else {
          setRun({ phase: 'error', detail: String(err), unreachable: true })
        }
      })
  }

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const onStartFromScratch = () => {
    if (cfg.phase !== 'ready') return
    fs.reset(cfg.config.user_defaults)
    setRun({ phase: 'idle' })
    setElapsed(0)
    setStep(0)
    setConfirmReset(false)
  }

  const inWizard = fs.view === 'wizard'

  // Fresh-visitor splash (v1.9.1): its own full-bleed layout, no shared hero.
  // "Get started" hands off to the guided wizard.
  if (fs.view === 'start') {
    return <StartPage onStart={() => fs.setView('wizard')} />
  }

  return (
    <>
      <div className={`hero${inWizard ? ' compact' : ''}`}>
        <h1>
          Which cards are actually
          <br />
          <span className="shimmer-text">worth it for you?</span>
        </h1>
        <p className="sub">
          Enter what you actually spend. This tool checks every major card combination —
          counting fees, caps, and only the credits you'd really use — and shows all of its work.
        </p>
      </div>

      {cfg.phase === 'loading' && (
        <p style={{ textAlign: 'center' }}>
          Loading… <span style={{ opacity: 0.7 }}>(this can take up to a minute)</span>
        </p>
      )}
      {(cfg.phase === 'unreachable' || (run.phase === 'error' && run.unreachable)) && (
        <ServerBanner onRetry={onRetryConfig} />
      )}

      {cfg.phase === 'ready' && (() => {
        const config = cfg.config

        const runbar = (
          <div className="runbar">
            {mode === 'auto' ? (
              <button
                type="button"
                className="primary"
                disabled={errors.length > 0 || run.phase === 'running'}
                onClick={onRun}
              >
                {run.phase === 'running' ? 'Scoring…' : 'Run the numbers'}
              </button>
            ) : (
              <button
                type="button"
                className="primary"
                disabled={errors.length > 0 || selected.size === 0 || run.phase === 'running'}
                onClick={onRunManual}
              >
                {run.phase === 'running'
                  ? 'Scoring…'
                  : `Score selected (${selected.size})`}
              </button>
            )}
            {/* Best-additional-card (v1.10): appears once a portfolio has been
                scored; adds the single best card and re-scores. */}
            {mode === 'manual' && run.phase === 'done' && (
              <button
                type="button"
                className="accent-add"
                onClick={onAddBest}
              >
                Add best additional card
              </button>
            )}
            {run.phase === 'running' && (
              <span className="status">
                {mode === 'auto'
                  ? `scoring every 1–3 card portfolio — ${elapsed}s`
                  : `scoring your ${selected.size} card${selected.size > 1 ? 's' : ''} — ${elapsed}s`}
              </span>
            )}
            {mode === 'manual' && run.phase !== 'running' && selected.size === 0 && (
              <span className="status">Pick cards below to score.</span>
            )}
            {run.phase === 'error' && !run.unreachable && (
              <span className="error">{run.detail}</span>
            )}
          </div>
        )

        const modeToggle = (
          <div className="mode-toggle" role="tablist" aria-label="Optimization mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'auto'}
              className={mode === 'auto' ? 'active' : ''}
              onClick={() => setMode('auto')}
            >
              Auto
              <ul className="mode-bullets">
                <li>Find the best profile for you automatically</li>
              </ul>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'manual'}
              className={mode === 'manual' ? 'active' : ''}
              onClick={() => setMode('manual')}
            >
              Custom
              <ul className="mode-bullets">
                <li>Check how good your existing card profile is</li>
                <li>Experiment with new card profiles</li>
                <li>Improve an existing profile</li>
              </ul>
            </button>
          </div>
        )

        const steps: WizardStep[] = [
          {
            id: 'rewards',
            title: 'Rewards',
            node: (
              <>
                <RewardPreferences
                  config={config}
                  kinds={user.rewardKinds}
                  onChange={(kind, on) =>
                    setUser((u) => ({ ...u, rewardKinds: { ...u.rewardKinds, [kind]: on } }))}
                />
                <BrandLoyalty config={config} confirmed={user.confirmed_usage} onToggle={toggleUsage} />
              </>
            ),
          },
          {
            id: 'spending',
            title: 'Spending',
            node: (
              <>
                <RentMortgage
                  cents={spend.categoryCents['housing'] ?? null}
                  onChange={(cents) =>
                    setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, housing: cents } }))}
                />
                <SpendEntry
                  config={config}
                  spend={spend}
                  unit={unit}
                  warnings={warnings}
                  onUnitChange={setUnit}
                  onCategoryChange={(key, cents) =>
                    setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, [key]: cents } }))}
                  onMerchantChange={(key, cents) =>
                    setSpend((s) => ({ ...s, merchantCents: { ...s.merchantCents, [key]: cents } }))}
                />
              </>
            ),
          },
          {
            id: 'usage',
            title: 'Services',
            node: (
              <>
                <StatementImport
                  config={config}
                  onApply={(usageKeys) => {
                    // Detection only (plan 14): statements never touch spend —
                    // confirmed services merge into the questionnaire state.
                    setUser((u) => ({
                      ...u,
                      confirmed_usage: new Set([...u.confirmed_usage, ...usageKeys]),
                    }))
                  }}
                />
                <UsageQuestionnaire config={config} confirmed={user.confirmed_usage} onToggle={toggleUsage} />
              </>
            ),
          },
          {
            id: 'about',
            title: 'About you',
            node: (
              <AboutYou
                config={config}
                user={user}
                onChange={(patch) => setUser((u) => ({ ...u, ...patch }))}
              />
            ),
          },
          {
            id: 'review',
            title: 'Review',
            node: (
              <>
                <ChecksPanel errors={errors} />
                {modeToggle}
                {runbar}
                {run.phase === 'done' && <ResultsView bundle={run.bundle} />}
                {mode === 'manual' && (
                  <ManualGrid selected={selected} onToggle={toggleSelect} />
                )}
              </>
            ),
          },
        ]

        if (inWizard) {
          return (
            <WizardShell
              steps={steps}
              index={step}
              canFinish={errors.length === 0}
              onBack={() => setStep((s) => Math.max(0, s - 1))}
              onNext={() => setStep((s) => Math.min(steps.length - 1, s + 1))}
              onJump={(i) => setStep(i)}
              onFinish={() => {
                fs.setCompleted(true)
                fs.setView('edit')
              }}
            />
          )
        }

        return (
          <>
            <div className="edit-toolbar">
              <button type="button" className="ghost start-over" onClick={() => setConfirmReset(true)}>
                Start from scratch
              </button>
            </div>
            {steps.map((s) => (
              <Fragment key={s.id}>{s.node}</Fragment>
            ))}
            <ConfirmDialog
              open={confirmReset}
              title="Start from scratch?"
              body="This clears everything you've entered and reopens the guided setup. This can't be undone."
              confirmLabel="Clear and restart"
              cancelLabel="Keep my answers"
              danger
              onConfirm={onStartFromScratch}
              onCancel={() => setConfirmReset(false)}
            />
          </>
        )
      })()}
    </>
  )
}
