import { Link } from '../lib/router'

const REPO = 'https://github.com/rithkott/credit_card_picker'

/** Customer-readable walkthrough of the pipeline — the deep-dive stays in
 * docs/architecture.md; this page explains the same system in plain terms. */
export function HowItWorks() {
  return (
    <div className="content-page">
      <div className="hero compact">
        <h1>
          How the <span className="shimmer-text">optimizer</span> works
        </h1>
        <p className="sub">
          No magic, no scores, no sponsorships — a deterministic calculation over a
          hand-curated dataset. Same inputs, same answer, every time.
        </p>
      </div>

      <section className="block prose">
        <h2>1 · The dataset is written by hand</h2>
        <p>
          Every card is a single, human-readable YAML file transcribed from the issuer's own
          terms — earn rates, category caps, statement credits, annual fees, signup bonuses,
          foreign-transaction fees. Nothing is scraped and nothing is generated on the fly:
          if a number couldn't be confirmed against issuer sources, the file says so
          explicitly and carries a low-confidence flag rather than a guess.
        </p>
        <p>
          Anything that spans cards — spending categories, merchants, point valuations —
          lives in shared registries that every card references by key. That means "how much
          is a Chase point worth" is a single global assumption you can read on the{' '}
          <Link to="/assumptions">Assumptions</Link> page, not something tuned per card.
        </p>
        <p>
          A validator runs on every change and blocks anything structurally wrong: unknown
          category keys, caps without fallback rates, credits pointing at usage questions
          that don't exist, stale verification dates.
        </p>
      </section>

      <section className="block prose">
        <h2>2 · Your spending is the only input</h2>
        <p>
          You enter (or import from a statement) what you spend per category and, where it
          matters, per merchant. The optimizer also asks which subscriptions and habits you
          actually have — because a $120 streaming credit is worth $120 only if you'd have
          paid for the subscription anyway. Credits attached to a habit you didn't confirm
          count for nothing.
        </p>
        <p>
          Airlines and hotels are the one exception: if points are among your
          reward priorities, you're assumed to book whichever brand gives the best value,
          so brand-specific airline and hotel credits count (at a conservative capture rate)
          without you naming a brand. Declaring loyalty to a specific brand upgrades it:
          its points are valued at their higher loyal-use rate and its credits at full capture.
        </p>
        <p>
          Statement files never leave your browser: PDF, CSV, and OFX parsing runs entirely
          on your machine, and only the resulting category totals are sent to the optimizer.
        </p>
      </section>

      <section className="block prose">
        <h2>3 · Every portfolio is scored, exhaustively</h2>
        <p>
          The engine scores every eligible combination of cards up to the portfolio size cap.
          For each combination it assigns every dollar of your spending to whichever card in
          the set earns the most on it, honoring category caps (spend past a cap falls back
          to the lower rate), the portal-price haircut on portal-only rates (booking through
          the issuer's portal is assumed, but portal fares often run above direct booking),
          and card-wide reward ceilings.
        </p>
        <p>
          Points are converted to dollars using the shared valuation table: each program has
          a conservative floor (what you can always get) and an optimistic value (transfer
          partners, portal boosts), and the engine uses the average of the two — dropping to
          the floor when the upside depends on a loyalty program or gateway card you don't
          have. Annual fees and any required memberships are subtracted. What's left is the
          number you see: net dollars per year, with a line-by-line receipt showing exactly
          where every dollar came from.
        </p>
      </section>

      <section className="block prose">
        <h2>4 · What it deliberately doesn't do</h2>
        <p>
          There are no affiliate links and no sponsored placement — the tool earns nothing
          when you apply for a card, so nothing nudges the math. It also doesn't model
          credit-score impact, issuer application rules (like 5/24), or manufactured
          spending. It answers one question well: given what you actually spend, which set
          of cards nets you the most.
        </p>
        <p className="src-link">
          Want the full technical detail? The annotated architecture, the validator's rules,
          and every card file are public:{' '}
          <a href={`${REPO}/blob/main/docs/architecture.md`} target="_blank" rel="noreferrer">
            docs/architecture.md on GitHub
          </a>.
        </p>
      </section>
    </div>
  )
}
