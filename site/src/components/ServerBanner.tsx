import { API_URL } from '../api'

/** Shown when /api/config (or a mid-session call) can't reach the local API.
 * v1 is local-only: the user runs the server on their own machine. */
export function ServerBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="banner">
      <h2>Local optimizer server not reachable</h2>
      <p>
        This site computes nothing itself — it talks to the optimizer running on{' '}
        <code>{API_URL}</code> on your machine (your spending data never leaves your computer).
        Start it from the repo root:
      </p>
      <pre className="cmd">{`pip install -r server/requirements.txt
python3 server/app.py`}</pre>
      <p>
        Safari blocks calls from an https page to localhost — there, build the site once
        (<code>cd site && npm run build</code>) and open <code>http://localhost:8000</code> instead.
      </p>
      <button type="button" className="primary" onClick={onRetry}>Retry</button>
    </div>
  )
}
