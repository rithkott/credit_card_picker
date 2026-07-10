import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, getConfig, optimize } from './api'
import type { Config, OptimizeBundle } from './types'
import type { Unit } from './lib/money'
import { buildProfile, type UserState } from './lib/profile'
import { validate, type SpendState } from './lib/validation'
import { AboutYou } from './components/AboutYou'
import { AuroraBackground } from './components/AuroraBackground'
import { ChecksPanel } from './components/ChecksPanel'
import { StatementImport } from './components/import/StatementImport'
import { RewardPreferences } from './components/RewardPreferences'
import { ServerBanner } from './components/ServerBanner'
import { SpendEntry } from './components/SpendEntry'
import { UsageQuestionnaire } from './components/UsageQuestionnaire'
import { ResultsView } from './components/results/ResultsView'

const REPO = 'https://github.com/rithkott/credit_card_picker'

type ConfigPhase =
  | { phase: 'loading' }
  | { phase: 'unreachable' }
  | { phase: 'ready'; config: Config }

type RunPhase =
  | { phase: 'idle' }
  | { phase: 'running'; startedAt: number }
  | { phase: 'done'; bundle: OptimizeBundle }
  | { phase: 'error'; detail: string; unreachable: boolean }

/** "2026-07-04" -> "July 2026" for the footer trust line. */
function verifiedMonth(isoDate: string): string {
  const [y, m] = isoDate.split('-')
  const names = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December']
  const month = names[Number(m) - 1]
  return month ? `${month} ${y}` : isoDate
}

export default function App() {
  const [cfg, setCfg] = useState<ConfigPhase>({ phase: 'loading' })
  const [unit, setUnit] = useState<Unit>('monthly')
  const [spend, setSpend] = useState<SpendState>({ categoryCents: {}, merchantCents: {} })
  const [user, setUser] = useState<UserState>({
    credit_tier: 'good',
    optimize_for: 'ongoing',
    accepts_brand_lockin: false,
    rewardKinds: { cashback: true, flights: true, hotels: true },
    confirmed_usage: new Set(),
  })
  const [run, setRun] = useState<RunPhase>({ phase: 'idle' })
  const [elapsed, setElapsed] = useState(0)

  const loadConfig = useCallback(() => {
    setCfg({ phase: 'loading' })
    getConfig()
      .then((config) => {
        setCfg({ phase: 'ready', config })
        // Seed the option defaults the server declares (single source of truth).
        setUser((u) => ({
          ...u,
          optimize_for: config.user_defaults.optimize_for,
          accepts_brand_lockin: config.user_defaults.accepts_brand_lockin,
        }))
      })
      .catch(() => setCfg({ phase: 'unreachable' }))
  }, [])
  useEffect(loadConfig, [loadConfig])

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

  const onRun = () => {
    setElapsed(0)
    setRun({ phase: 'running', startedAt: Date.now() })
    optimize(buildProfile(spend, user))
      .then((bundle) => setRun({ phase: 'done', bundle }))
      .catch((err) => {
        if (err instanceof ApiError) {
          setRun({ phase: 'error', detail: err.message, unreachable: false })
        } else {
          setRun({ phase: 'error', detail: String(err), unreachable: true })
        }
      })
  }

  return (
    <>
      <AuroraBackground />
      <div className="page">
        <div className="nav-wrap">
          <div className="nav-pill">
            <span className="wordmark">Card Picker</span>
            <nav>
              <a href={`${REPO}/blob/main/docs/architecture.md`} target="_blank" rel="noreferrer">
                How it works
              </a>
              <a href={`${REPO}/tree/main/data/cards`} target="_blank" rel="noreferrer">
                Data sources
              </a>
              <a href={`${REPO}/blob/main/data/meta/point-valuations.yaml`} target="_blank" rel="noreferrer">
                Assumptions
              </a>
            </nav>
          </div>
        </div>

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

        {cfg.phase === 'loading' && <p style={{ textAlign: 'center' }}>Connecting to the local optimizer…</p>}
        {(cfg.phase === 'unreachable' || (run.phase === 'error' && run.unreachable)) && (
          <ServerBanner onRetry={loadConfig} />
        )}

        {cfg.phase === 'ready' && (
          <>
            <StatementImport
              config={cfg.config}
              formNonEmpty={Object.values(spend.categoryCents)
                .some((c) => c !== null && !Number.isNaN(c) && c > 0)}
              onApply={(imported, usageKeys) => {
                setSpend(imported)
                setUser((u) => ({
                  ...u,
                  confirmed_usage: new Set([...u.confirmed_usage, ...usageKeys]),
                }))
              }}
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
              onToggle={(key, on) =>
                setUser((u) => {
                  const next = new Set(u.confirmed_usage)
                  if (on) next.add(key)
                  else next.delete(key)
                  return { ...u, confirmed_usage: next }
                })}
            />
            <div className="prefs-grid">
              <RewardPreferences
                config={cfg.config}
                kinds={user.rewardKinds}
                onChange={(kind, on) =>
                  setUser((u) => ({ ...u, rewardKinds: { ...u.rewardKinds, [kind]: on } }))}
              />
              <AboutYou
                config={cfg.config}
                user={user}
                onChange={(patch) => setUser((u) => ({ ...u, ...patch }))}
              />
            </div>
            <ChecksPanel errors={errors} />
            <div className="runbar">
              <button
                type="button"
                className="primary"
                disabled={errors.length > 0 || run.phase === 'running'}
                onClick={onRun}
              >
                {run.phase === 'running' ? 'Scoring…' : 'Run the numbers'}
              </button>
              {run.phase === 'running' ? (
                <span className="status">
                  scoring every 1–3 card portfolio — {elapsed}s
                </span>
              ) : (
                <span className="det-note">deterministic — same inputs, same answer</span>
              )}
              {run.phase === 'error' && !run.unreachable && (
                <span className="error">{run.detail}</span>
              )}
            </div>
            {run.phase === 'done' && <ResultsView bundle={run.bundle} />}
          </>
        )}

        <footer className="site">
          <p className="fine">
            This tool has no affiliate links or sponsored placement — it earns nothing when you
            apply for a card. Card data is checked by hand against issuer terms
            {cfg.phase === 'ready' && (
              <> (last verified {verifiedMonth(cfg.config.data_last_verified)})</>
            )}{' '}
            and flagged when it goes stale. Same inputs, same answer, every time.
          </p>
          <nav>
            <a href={`${REPO}/tree/main/data/cards`} target="_blank" rel="noreferrer">
              Data sources
            </a>
            <a href={`${REPO}/blob/main/docs/architecture.md`} target="_blank" rel="noreferrer">
              How the optimizer works
            </a>
            <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
              Report an error
            </a>
          </nav>
        </footer>
      </div>
    </>
  )
}
