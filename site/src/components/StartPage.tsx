/** First-run landing (v1.9.1): a calm splash shown before the wizard for fresh
 * visitors. Its only job is to set the frame and hand off to the guided setup —
 * the "Get started" button flips the form view to 'wizard'. Returning visitors
 * (completed) never see this; they land straight in the 'edit' view. */

const svg = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

const POINTS = [
  {
    icon: (
      <svg {...svg}>
        <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
        <path d="M2.5 9.5h19" />
        <path d="M6 14.5h4" />
      </svg>
    ),
    title: 'Enter what you spend',
    body: 'Your real monthly categories — groceries, travel, dining. No account, no sign-up.',
  },
  {
    icon: (
      <svg {...svg}>
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    ),
    title: 'Every combination scored',
    body: 'We check each major card combo — counting fees, caps, and only the credits you’d really use.',
  },
  {
    icon: (
      <svg {...svg}>
        <path d="M12 2.5 4 6v5c0 4.5 3.2 8.4 8 9.5 4.8-1.1 8-5 8-9.5V6z" />
        <path d="M9 12l2 2 4-4.5" />
      </svg>
    ),
    title: 'No affiliate bias',
    body: 'Same inputs, same answer, every time. This tool earns nothing when you apply for a card.',
  },
]

export function StartPage({ onStart }: { onStart: () => void }) {
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
        <p className="sub">
          A deterministic optimizer built on a hand-curated dataset. Tell it what you spend and it
          shows every major card combination, ranked — and all of its work.
        </p>
        <div className="start-cta">
          <button type="button" className="primary" onClick={onStart}>
            Get started
          </button>
          <span className="start-cta-note">Takes about two minutes.</span>
        </div>
      </div>

      <ul className="start-points">
        {POINTS.map((p) => (
          <li key={p.title} className="start-point">
            <span className="start-point-icon" aria-hidden="true">{p.icon}</span>
            <span className="start-point-title">{p.title}</span>
            <span className="start-point-body">{p.body}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
