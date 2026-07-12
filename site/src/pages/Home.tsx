import { useEffect, useMemo, useState } from 'react'
import { ApiError, evaluateManual, optimize } from '../api'
import type { OptimizeBundle } from '../types'
import type { Unit } from '../lib/money'
import { buildProfile, MANUAL_MAX_CARDS, type UserState } from '../lib/profile'
import { validate, type SpendState } from '../lib/validation'
import { ManualGrid } from '../components/ManualGrid'
import { AboutYou } from '../components/AboutYou'
import { BrandLoyalty } from '../components/BrandLoyalty'
import { ChecksPanel } from '../components/ChecksPanel'
import { StatementImport } from '../components/import/StatementImport'
import { RentMortgage } from '../components/RentMortgage'
import { RewardPreferences } from '../components/RewardPreferences'
import { ServerBanner } from '../components/ServerBanner'
import { SpendEntry } from '../components/SpendEntry'
import { UsageQuestionnaire } from '../components/UsageQuestionnaire'
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
  const [unit, setUnit] = useState<Unit>('monthly')
  const [spend, setSpend] = useState<SpendState>({ categoryCents: {}, merchantCents: {} })
  const [user, setUser] = useState<UserState>({
    credit_tier: 'excellent',
    optimize_for: 'ongoing',
    accepts_brand_lockin: false,
    rewardKinds: { cashback: true, flights: true, hotels: true },
    confirmed_usage: new Set(),
  })
  const [run, setRun] = useState<RunPhase>({ phase: 'idle' })
  const [elapsed, setElapsed] = useState(0)
  // Auto = optimizer picks the best set (default). Manual = user hand-picks up
  // to MAX_CARDS cards from the grid; the same value math runs on that set.
  const [mode, setMode] = useState<'auto' | 'manual'>('auto')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Seed the option defaults the server declares (single source of truth).
  useEffect(() => {
    if (cfg.phase !== 'ready') return
    setUser((u) => ({
      ...u,
      optimize_for: cfg.config.user_defaults.optimize_for,
      accepts_brand_lockin: cfg.config.user_defaults.accepts_brand_lockin,
    }))
  }, [cfg])

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

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else if (next.size < MANUAL_MAX_CARDS) next.add(id)
      return next
    })

  return (
    <>
      <div className="hero">
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

      {cfg.phase === 'ready' && (
        <>
          <StatementImport
            config={cfg.config}
            onApply={(usageKeys) => {
              // Detection only (plan 14): statements never touch spend —
              // confirmed services merge into the questionnaire state.
              setUser((u) => ({
                ...u,
                confirmed_usage: new Set([...u.confirmed_usage, ...usageKeys]),
              }))
            }}
          />
          <RewardPreferences
            config={cfg.config}
            kinds={user.rewardKinds}
            onChange={(kind, on) =>
              setUser((u) => ({ ...u, rewardKinds: { ...u.rewardKinds, [kind]: on } }))}
          />
          <BrandLoyalty
            config={cfg.config}
            confirmed={user.confirmed_usage}
            onToggle={toggleUsage}
          />
          <RentMortgage
            cents={spend.categoryCents['housing'] ?? null}
            onChange={(cents) =>
              setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, housing: cents } }))}
          />
          <SpendEntry
            config={cfg.config}
            spend={spend}
            unit={unit}
            warnings={warnings}
            onUnitChange={setUnit}
            onCategoryChange={(key, cents) =>
              setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, [key]: cents } }))}
            onMerchantChange={(key, cents) =>
              setSpend((s) => ({ ...s, merchantCents: { ...s.merchantCents, [key]: cents } }))}
          />
          <UsageQuestionnaire
            config={cfg.config}
            confirmed={user.confirmed_usage}
            onToggle={toggleUsage}
          />
          <AboutYou
            config={cfg.config}
            user={user}
            onChange={(patch) => setUser((u) => ({ ...u, ...patch }))}
          />
          <ChecksPanel errors={errors} />
          <div className="mode-toggle" role="tablist" aria-label="Optimization mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'auto'}
              className={mode === 'auto' ? 'active' : ''}
              onClick={() => setMode('auto')}
            >
              Auto
              <span className="mode-hint">we pick the best cards</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'manual'}
              className={mode === 'manual' ? 'active' : ''}
              onClick={() => setMode('manual')}
            >
              Manual
              <span className="mode-hint">you pick, we do the math</span>
            </button>
          </div>
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
                  : `Score selected (${selected.size}/${MANUAL_MAX_CARDS})`}
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
              <span className="status">Pick 1–{MANUAL_MAX_CARDS} cards below to score.</span>
            )}
            {run.phase === 'error' && !run.unreachable && (
              <span className="error">{run.detail}</span>
            )}
          </div>
          {run.phase === 'done' && <ResultsView bundle={run.bundle} />}
          {mode === 'manual' && (
            <ManualGrid selected={selected} max={MANUAL_MAX_CARDS} onToggle={toggleSelect} />
          )}
        </>
      )}
    </>
  )
}
