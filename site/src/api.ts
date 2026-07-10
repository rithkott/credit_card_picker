import type { AssumptionsResponse, CardsResponse, Config, OptimizeBundle, Profile } from './types'

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
 * can render the optimizer's own user-directed text verbatim. */
export class ApiError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, init)
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = (await resp.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(resp.status, detail)
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
