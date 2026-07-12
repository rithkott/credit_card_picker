import type { AssumptionsResponse, CardsResponse, Config, OptimizeBundle, Profile } from './types'
import type { WireParsedFile } from './lib/statements/types'

/** API base URL. Production builds default to '' (same-origin — Vercel
 * serves the API as a Python function next to the static site, and the local
 * server's static mount of site/dist is same-origin too). Dev keeps the
 * explicit localhost:8000 so the Vite dev server talks to the local API
 * directly. Override with VITE_API_URL at build time (e.g. a GitHub Pages
 * build pointing at a locally-run API). */
export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined)
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')

/** Error carrying the server's {"detail": ...} message (422/500) so the UI
 * can render the server's own user-directed text verbatim. `code` is set by
 * the statement-parse endpoint's error taxonomy (scanned_pdf, too_large, ...). */
export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, detail: string, code?: string) {
    super(detail)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, init)
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    let code: string | undefined
    try {
      const body = (await resp.json()) as { detail?: string; code?: string }
      if (body.detail) detail = body.detail
      code = body.code
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(resp.status, detail, code)
  }
  return (await resp.json()) as T
}

export function getHealth(): Promise<{ ok: boolean; cards_total: number }> {
  return request('/api/health')
}

export function getConfig(): Promise<Config> {
  return request('/api/config')
}

export function getCards(): Promise<CardsResponse> {
  return request('/api/cards')
}

export function getAssumptions(): Promise<AssumptionsResponse> {
  return request('/api/assumptions')
}

export function optimize(profile: Profile, top = 5): Promise<OptimizeBundle> {
  return request('/api/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...profile, top }),
  })
}

/** Manual mode (v1.7): score exactly the user-selected `cardIds` (1-5) instead
 * of the optimizer searching for the best set. Same profile body as optimize(),
 * plus `cards`; returns the identical OptimizeBundle (a single best_by_size). */
export function evaluateManual(profile: Profile, cardIds: string[]): Promise<OptimizeBundle> {
  return request('/api/evaluate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...profile, cards: cardIds }),
  })
}

/** One statement file -> parsed + categorized transactions (plan 12). The
 * server holds the bytes in memory for the request and stores nothing. No
 * Content-Type header: the browser sets the multipart boundary itself. */
export function parseStatement(name: string, bytes: Uint8Array): Promise<WireParsedFile> {
  const form = new FormData()
  // The bytes always come from File.arrayBuffer(), so the buffer is a real
  // ArrayBuffer — the cast only papers over TS's SharedArrayBuffer caution.
  form.append('file', new Blob([bytes as Uint8Array<ArrayBuffer>]), name)
  return request('/api/statements/parse', { method: 'POST', body: form })
}
