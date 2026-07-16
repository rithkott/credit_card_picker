import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, evaluateManual, optimize, suggestAddition } from '../api'
import type { OptimizeBundle, SuggestAdditionBundle } from '../types'
import { buildProfile } from '../lib/profile'
import { validate } from '../lib/validation'
import { useFormState, type Mode } from '../hooks/useFormState'
import { ManualGrid } from '../components/ManualGrid'
import { ComparePicker } from '../components/ComparePicker'
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
import { CompareResults, type CompareEntry, type CompareOutcome } from '../components/results/CompareResults'
import type { ConfigPhase } from '../App'

type RunPhase =
  | { phase: 'idle' }
  | { phase: 'running'; startedAt: number }
  | { phase: 'done'; bundle: OptimizeBundle | SuggestAdditionBundle }
  // Compare path (plan 20): one evaluate bundle (or error) per hand-built
  // portfolio — a separate variant so the single-bundle 'done' narrowing
  // (ResultsView, 'added_card' in bundle) stays untouched.
  | { phase: 'done-compare'; entries: CompareEntry[] }
  | { phase: 'error'; detail: string; unreachable: boolean }

export function Home({ cfg, onRetryConfig }: {
  cfg: ConfigPhase
  onRetryConfig: () => void
}) {
  const fs = useFormState()
  const {
    spend, setSpend, user, setUser, unit, setUnit, mode, setMode,
    selected, setSelected, excluded, setExcluded,
    comparePortfolios, setComparePortfolios,
  } = fs
  const [run, setRun] = useState<RunPhase>({ phase: 'idle' })
  const [elapsed, setElapsed] = useState(0)
  // First-run wizard step index. In-session only — a mid-wizard refresh restores
  // entered values but returns to step 0 (accepted tradeoff, keeps this simple).
  const [step, setStep] = useState(0)
  const [confirmReset, setConfirmReset] = useState(false)
  const resultsRef = useRef<HTMLDivElement>(null)

  // Autoscroll to results once any scoring run (Auto / Custom / Add-best) lands
  // on 'done'. Keyed on run.phase so it fires once per transition; the effect
  // runs after the commit that mounts ResultsView, so the ref is populated.
  useEffect(() => {
    if (run.phase === 'done' || run.phase === 'done-compare') {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [run.phase])

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

  const onRun = () => startRun(optimize(buildProfile(spend, user, unit, excluded)))
  const onRunManual = () => startRun(evaluateManual(buildProfile(spend, user, unit, excluded), [...selected]))

  // Compare path (plan 20): score every hand-built portfolio in parallel —
  // one /api/evaluate per set, same profile. Each request catches its own
  // error so one bad portfolio renders inline while the rest still show;
  // only the everything-unreachable case falls back to the server banner.
  // Labels + card lists are snapshotted here so picker edits after the run
  // can't desync the rendered results.
  const onRunCompare = () => {
    setElapsed(0)
    setRun({ phase: 'running', startedAt: Date.now() })
    const profile = buildProfile(spend, user, unit, excluded)
    void Promise.all(comparePortfolios.map((cards, i) =>
      evaluateManual(profile, cards)
        .then((bundle): CompareEntry => ({
          label: `Portfolio ${i + 1}`, cards, outcome: { ok: true, bundle },
        }))
        .catch((err: unknown): CompareEntry => ({
          label: `Portfolio ${i + 1}`,
          cards,
          outcome: err instanceof ApiError
            ? { ok: false, detail: err.message, unreachable: false }
            : { ok: false, detail: String(err), unreachable: true },
        })),
    )).then((entries) => {
      const outcomes: CompareOutcome[] = entries.map((e) => e.outcome)
      if (outcomes.every((o) => !o.ok && o.unreachable)) {
        setRun({ phase: 'error', detail: 'Server unreachable', unreachable: true })
      } else {
        setRun({ phase: 'done-compare', entries })
      }
    })
  }

  // Switch journey paths, keeping every entered value (spend, user, selected).
  // Results from another path are cleared so stale bundles never render under
  // the new mode's framing.
  const switchMode = (m: Mode) => {
    if (m === mode) return
    setMode(m)
    setRun({ phase: 'idle' })
  }

  // Improve path: ask the server for the best card to add to the held set,
  // check it in the grid, and show the augmented score — one action. Can't
  // reuse startRun() verbatim because of the extra setSelected side effect on success.
  const onRunImprove = () => {
    setElapsed(0)
    setRun({ phase: 'running', startedAt: Date.now() })
    suggestAddition(buildProfile(spend, user, unit, excluded), [...selected])
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

  // Compare path (plan 20): route a catalog pick into one of the 2–4 sets.
  const toggleCompareCard = (pIdx: number, id: string) =>
    setComparePortfolios((prev) => prev.map((cards, i) => {
      if (i !== pIdx) return cards
      return cards.includes(id) ? cards.filter((c) => c !== id) : [...cards, id]
    }))
  const addComparePortfolio = () =>
    setComparePortfolios((prev) => (prev.length < 4 ? [...prev, []] : prev))
  const removeComparePortfolio = (pIdx: number) =>
    setComparePortfolios((prev) => (prev.length > 2 ? prev.filter((_, i) => i !== pIdx) : prev))

  // Exclude a card from consideration (v2.5.0): the optimizer never picks or
  // suggests an excluded card. Excluding also drops it from the held selection
  // and from every compare portfolio — a card can't be both held and vetoed.
  const toggleExclude = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else {
        next.add(id)
        setSelected((sel) => {
          if (!sel.has(id)) return sel
          const s = new Set(sel)
          s.delete(id)
          return s
        })
        setComparePortfolios((ports) =>
          ports.some((cards) => cards.includes(id))
            ? ports.map((cards) => cards.filter((c) => c !== id))
            : ports)
      }
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

  // The start chooser opens EVERY visit (v2.3.3): its own full-bleed layout,
  // no shared hero. A path press sets the journey mode, then routes a
  // completed visitor straight to their filled-in edit view and everyone
  // else into the guided wizard.
  if (fs.view === 'start') {
    return (
      <StartPage
        onStart={(m) => {
          switchMode(m)
          fs.setView(fs.completed ? 'edit' : 'wizard')
        }}
      />
    )
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
          Enter what you spend. We check <strong>every major card combination</strong> —
          fees, caps, real credits — and <strong>show all the work</strong>.
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

        // Per-path run wiring: label, action, and status line. analyze/improve
        // need at least one held card, compare needs every portfolio non-empty
        // (the server 422s on an empty set).
        const needsCards = mode === 'analyze' || mode === 'improve'
        const isCompare = mode === 'compare'
        const compareReady = comparePortfolios.every((p) => p.length > 0)
        const runLabel = mode === 'generate'
          ? 'Run the numbers'
          : mode === 'analyze'
            ? `Score my cards (${selected.size})`
            : mode === 'improve'
              ? `Find my next card (${selected.size})`
              : `Compare portfolios (${comparePortfolios.length})`
        const runAction = mode === 'generate'
          ? onRun
          : mode === 'analyze'
            ? onRunManual
            : mode === 'improve' ? onRunImprove : onRunCompare
        const runningStatus = mode === 'generate'
          ? `scoring every 1–3 card portfolio — ${elapsed}s`
          : mode === 'analyze'
            ? `scoring your ${selected.size} card${selected.size > 1 ? 's' : ''} — ${elapsed}s`
            : mode === 'improve'
              ? `finding the best card to add to your ${selected.size} — ${elapsed}s`
              : `scoring ${comparePortfolios.length} portfolios — ${elapsed}s`
        const runDisabled = errors.length > 0
          || (needsCards && selected.size === 0)
          || (isCompare && !compareReady)
          || run.phase === 'running'

        const runbar = (
          <div className={`runbar${needsCards || isCompare ? ' runbar--floating' : ''}`}>
            <button
              type="button"
              className="primary"
              disabled={runDisabled}
              onClick={runAction}
            >
              {run.phase === 'running' ? 'Scoring…' : runLabel}
            </button>
            {needsCards && run.phase !== 'running' && selected.size > 0 && (
              <button
                type="button"
                className="ghost"
                onClick={() => setSelected(new Set())}
              >
                Deselect all
              </button>
            )}
            {run.phase === 'running' && (
              <span className="status">{runningStatus}</span>
            )}
            {needsCards && run.phase !== 'running' && selected.size === 0 && (
              <span className="status">Pick the cards you have below.</span>
            )}
            {isCompare && run.phase !== 'running' && !compareReady && (
              <span className="status">Every portfolio needs at least one card.</span>
            )}
            {run.phase === 'error' && !run.unreachable && (
              <span className="error">{run.detail}</span>
            )}
            {excluded.size > 0 && (
              <span className="excluded-chip">
                {excluded.size} card{excluded.size > 1 ? 's' : ''} excluded from consideration
                <button type="button" className="ghost" onClick={() => setExcluded(new Set())}>
                  clear
                </button>
              </span>
            )}
          </div>
        )

        // Journey switcher restyled as the front page's hardware keycaps
        // (raised key, recessed accent bottom edge, status LED); the active
        // key sits latched. Rails fence it off from the About-you form above
        // and the run/results area below.
        const modeToggle = (
          <>
            <hr className="section-rail" aria-hidden="true" />
            <div className="mode-toggle" role="tablist" aria-label="Journey">
              {([
                ['generate', 'Find the best card portfolio for me', 'Generate from scratch.'],
                ['analyze', 'Analyze my card portfolio',
                  'See how good your cards are and how to best split spending across them.'],
                ['improve', 'Improve my existing card portfolio',
                  'Keep your cards and find the best one to add.'],
                ['compare', 'Compare card portfolios',
                  'Hand-pick a few sets and see them scored side by side.'],
              ] as [Mode, string, string][]).map(([m, title, subtitle]) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  className={`mode-key${mode === m ? ' active' : ''}`}
                  onClick={() => switchMode(m)}
                >
                  <span className="mode-key-led" aria-hidden="true" />
                  <span className="mode-key-title">{title}</span>
                  <span className="mode-key-sub">{subtitle}</span>
                </button>
              ))}
            </div>
            <hr className="section-rail" aria-hidden="true" />
          </>
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
                  extras={spend.categoryExtraCents['housing'] ?? []}
                  onChange={(cents) =>
                    setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, housing: cents } }))}
                  onExtrasChange={(extras) =>
                    setSpend((s) => ({ ...s, categoryExtraCents: { ...s.categoryExtraCents, housing: extras } }))}
                />
                <SpendEntry
                  config={config}
                  spend={spend}
                  unit={unit}
                  warnings={warnings}
                  onUnitChange={setUnit}
                  onCategoryChange={(key, cents) =>
                    setSpend((s) => ({ ...s, categoryCents: { ...s.categoryCents, [key]: cents } }))}
                  onCategoryExtrasChange={(key, extras) =>
                    setSpend((s) => ({ ...s, categoryExtraCents: { ...s.categoryExtraCents, [key]: extras } }))}
                  onMerchantChange={(key, cents) =>
                    setSpend((s) => ({ ...s, merchantCents: { ...s.merchantCents, [key]: cents } }))}
                  onMerchantExtrasChange={(key, extras) =>
                    setSpend((s) => ({ ...s, merchantExtraCents: { ...s.merchantExtraCents, [key]: extras } }))}
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
                {needsCards && (
                  <ManualGrid
                    selected={selected}
                    excluded={excluded}
                    onToggle={toggleSelect}
                    onToggleExclude={toggleExclude}
                  />
                )}
                {isCompare && (
                  <ComparePicker
                    portfolios={comparePortfolios}
                    excluded={excluded}
                    onToggleCard={toggleCompareCard}
                    onAdd={addComparePortfolio}
                    onRemove={removeComparePortfolio}
                    onToggleExclude={toggleExclude}
                  />
                )}
                {run.phase === 'done' && (
                  <div ref={resultsRef}>
                    <ResultsView
                      bundle={run.bundle}
                      addedCard={'added_card' in run.bundle ? run.bundle.added_card : undefined}
                      excluded={excluded}
                      onToggleExclude={toggleExclude}
                    />
                  </div>
                )}
                {run.phase === 'done-compare' && (
                  <div ref={resultsRef}>
                    <CompareResults
                      entries={run.entries}
                      excluded={excluded}
                      onToggleExclude={toggleExclude}
                    />
                  </div>
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
              canFinish={errors.length === 0
                && (mode === 'generate' || (isCompare ? compareReady : selected.size > 0))}
              finishLabel={run.phase === 'running' ? 'Scoring…' : runLabel}
              onBack={() => setStep((s) => Math.max(0, s - 1))}
              onNext={() => setStep((s) => Math.min(steps.length - 1, s + 1))}
              onJump={(i) => setStep(i)}
              onFinish={() => {
                // One press ends onboarding and runs the picked path (v1.11.1):
                // collapse to the edit view and kick off the same run the
                // edit-view runbar would.
                fs.setCompleted(true)
                fs.setView('edit')
                runAction()
              }}
            />
          )
        }

        return (
          <div className={needsCards || isCompare ? 'edit-view has-floating-runbar' : 'edit-view'}>
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
              body="This clears everything you've entered and takes you back to the start screen. This can't be undone."
              confirmLabel="Clear and restart"
              cancelLabel="Keep my answers"
              danger
              onConfirm={onStartFromScratch}
              onCancel={() => setConfirmReset(false)}
            />
          </div>
        )
      })()}
    </>
  )
}
