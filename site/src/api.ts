import type { Config, OptimizeBundle, Profile } from './types'

/** API base URL. http://localhost:8000 is correct in every v1 mode: Vite dev,
 * the GitHub Pages build (the user runs the API locally), and the server's
 * own static mount of site/dist (same origin, but the absolute URL still
 * resolves to itself). Override with VITE_API_URL at build time. */
export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

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

export function optimize(profile: Profile, top = 5): Promise<OptimizeBundle> {
  return request('/api/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...profile, top }),
  })
}
