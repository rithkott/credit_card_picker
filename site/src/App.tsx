import { useCallback, useEffect, useState } from 'react'
import { getConfig } from './api'
import type { Config } from './types'
import { AuroraBackground } from './components/AuroraBackground'
import { Link, Router, usePath } from './lib/router'
import { Home } from './pages/Home'
import { HowItWorks } from './pages/HowItWorks'
import { DataSources } from './pages/DataSources'
import { Assumptions } from './pages/Assumptions'

const REPO = 'https://github.com/rithkott/credit_card_picker'

export type ConfigPhase =
  | { phase: 'loading' }
  | { phase: 'unreachable' }
  | { phase: 'ready'; config: Config }

/** "2026-07-04" -> "July 2026" for the footer trust line. */
function verifiedMonth(isoDate: string): string {
  const [y, m] = isoDate.split('-')
  const names = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December']
  const month = names[Number(m) - 1]
  return month ? `${month} ${y}` : isoDate
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const path = usePath()
  return (
    <Link to={to} className={path === to ? 'active' : undefined}>
      {children}
    </Link>
  )
}

function Shell() {
  const [cfg, setCfg] = useState<ConfigPhase>({ phase: 'loading' })
  const path = usePath()

  const loadConfig = useCallback(() => {
    setCfg({ phase: 'loading' })
    getConfig()
      .then((config) => setCfg({ phase: 'ready', config }))
      .catch(() => setCfg({ phase: 'unreachable' }))
  }, [])
  useEffect(loadConfig, [loadConfig])

  let page: React.ReactNode
  switch (path) {
    case '/how-it-works':
      page = <HowItWorks />
      break
    case '/data-sources':
      page = <DataSources />
      break
    case '/assumptions':
      page = <Assumptions />
      break
    default:
      page = <Home cfg={cfg} onRetryConfig={loadConfig} />
  }

  return (
    <>
      <AuroraBackground />
      <div className="page">
        <div className="nav-wrap">
          <div className="nav-pill">
            <Link to="/" className="wordmark">Card Picker</Link>
            <nav>
              <NavLink to="/how-it-works">How it works</NavLink>
              <NavLink to="/data-sources">Data sources</NavLink>
              <NavLink to="/assumptions">Assumptions</NavLink>
            </nav>
          </div>
        </div>
        <a
          className="github-corner"
          href={REPO}
          target="_blank"
          rel="noreferrer"
          aria-label="View the source on GitHub — this project is open source"
        >
          <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
              0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01
              1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
              0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09
              2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15
              0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2
              0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
          </svg>
          <span>Open source</span>
        </a>

        {page}

        <footer className="site">
          <p className="fine">
            This tool has no affiliate links or sponsored placement — it earns nothing when you
            apply for a card. Card data is checked by hand against issuer terms
            {cfg.phase === 'ready' && cfg.config.data_last_verified && (
              <> (last verified {verifiedMonth(cfg.config.data_last_verified)})</>
            )}{' '}
            and flagged when it goes stale. Same inputs, same answer, every time. The whole
            project is open source — every line of code and data is{' '}
            <a href={REPO} target="_blank" rel="noreferrer">on GitHub</a>.
          </p>
          <p className="fine">
            Statements are parsed in your browser and never uploaded. Only the category
            totals you approve are sent to compute your results. Your entries are saved
            in this browser so a refresh won't lose them, and never leave it — there are
            no accounts, cookies, or analytics.
          </p>
          <nav>
            <Link to="/data-sources">Data sources</Link>
            <Link to="/how-it-works">How the optimizer works</Link>
            <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
              Report an error
            </a>
          </nav>
        </footer>
      </div>
    </>
  )
}

export default function App() {
  return (
    <Router>
      <Shell />
    </Router>
  )
}
