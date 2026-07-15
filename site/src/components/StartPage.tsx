/** Landing page (v1.9.1; three-path chooser v2.2; free keycaps v2.4; fourth
 * compare key plan 20): EVERY visit opens here — returning visitors too, with
 * their saved values intact behind the chooser. Order: hero headline, then the
 * path selector — four XL keycaps sitting directly on the page (no faceplate, no idle
 * animation) with a recessed orange bottom edge so they read as hardware
 * keys; hovering floats a key up, pressing latches it (sinks + LED lights)
 * and hands off: completed visitors to their edit view, everyone else into
 * the wizard. Trust points are bare text columns below — the keys are the
 * only raised tiles on the page. */

import { useState } from 'react'
import type { Mode } from '../hooks/useFormState'

const POINTS = [
  {
    title: 'Enter what you spend',
    body: 'Real monthly categories. No account, no sign-up.',
  },
  {
    title: 'Every combination scored',
    body: 'Fees, caps, and only credits you’d really use.',
  },
  {
    title: 'No affiliate bias',
    body: 'Earns nothing when you apply for a card.',
  },
]

const OPTIONS: { mode: Mode; title: string; subtitle: string }[] = [
  {
    mode: 'generate',
    title: 'Find the best card portfolio for me',
    subtitle: 'Generate from scratch.',
  },
  {
    mode: 'analyze',
    title: 'Analyze my card portfolio',
    subtitle: 'See how good your cards are and how to best split spending across them.',
  },
  {
    mode: 'improve',
    title: 'Improve my existing card portfolio',
    subtitle: 'Keep your cards and find the best one to add.',
  },
  {
    mode: 'compare',
    title: 'Compare card portfolios',
    subtitle: 'Build two to four sets of cards and see which one wins for your spending.',
  },
]

/** How long the pressed key stays latched before navigation — long enough that
 * the sink + LED read as a mechanical action, short enough to feel instant. */
const LATCH_MS = 280

export function StartPage({ onStart }: { onStart: (mode: Mode) => void }) {
  const [pressed, setPressed] = useState<Mode | null>(null)

  const press = (mode: Mode) => {
    if (pressed) return // a key is already latched — ignore double-fires
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onStart(mode)
      return
    }
    setPressed(mode)
    window.setTimeout(() => onStart(mode), LATCH_MS)
  }

  return (
    <div className="start">
      <div className="start-hero">
        <span className="privacy-pill start-pill">
          <span className="dot" aria-hidden="true" />
          Runs in your browser · no accounts, no tracking
        </span>
        <h1>
          Find the credit cards
          <br />
          <span className="shimmer-text">actually worth it for you.</span>
        </h1>
      </div>

      <div className="free-bank" role="group" aria-label="Choose your path">
        <div className="start-bank-legend free-legend">
          <span className="start-bank-title">What do you want to do?</span>
          <span className="start-bank-note">Pick one — you can switch later.</span>
        </div>
        <div className="start-options">
          {OPTIONS.map((o) => (
            <button
              key={o.mode}
              type="button"
              className={`start-option${pressed === o.mode ? ' latched' : ''}`}
              onClick={() => press(o.mode)}
            >
              <span className="start-option-led" aria-hidden="true" />
              <span className="start-option-title">{o.title}</span>
              <span className="start-option-sub">{o.subtitle}</span>
              <span className="start-option-cta" aria-hidden="true">Select ▸</span>
            </button>
          ))}
        </div>
      </div>

      <ul className="points-bare">
        {POINTS.map((p) => (
          <li key={p.title}>
            <span className="txt">
              <strong>{p.title}</strong>
              {p.body}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
