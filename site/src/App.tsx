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

        {page}

        <footer className="site">
          <p className="fine">
            This tool has no affiliate links or sponsored placement — it earns nothing when you
            apply for a card. Card data is checked by hand against issuer terms
            {cfg.phase === 'ready' && cfg.config.data_last_verified && (
              <> (last verified {verifiedMonth(cfg.config.data_last_verified)})</>
            )}{' '}
            and flagged when it goes stale. Same inputs, same answer, every time.
          </p>
          <p className="fine">
            Statements are parsed in your browser and never uploaded. Only the category
            totals you approve are sent to compute your results — nothing is stored, and
            there are no accounts, cookies, or analytics.
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
