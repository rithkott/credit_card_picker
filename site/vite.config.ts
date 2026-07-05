import { defineConfig } from 'vitest/config'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/* Strict CSP for production builds (plan 09): no external hosts at all —
 * scripts/workers/styles are self-hosted, the only network peer is the local
 * optimizer API. Build-only because the dev server needs inline scripts for
 * React fast-refresh. */
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "worker-src 'self' blob:",
  "connect-src 'self' http://localhost:8000",
  "img-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "object-src 'none'",
  "base-uri 'none'",
].join('; ')

const injectCsp: Plugin = {
  name: 'inject-csp',
  apply: 'build',
  transformIndexHtml: (html) => ({
    html,
    tags: [{
      tag: 'meta',
      attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP },
      injectTo: 'head-prepend',
    }],
  }),
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), injectCsp],
  test: {
    // Node has no DOMMatrix/Worker: tests get pdf.js's legacy build (its
    // fake worker runs in-process), browsers get the standard one — and the
    // legacy build stays out of the production bundle.
    alias: [{ find: /^pdfjs-dist$/, replacement: 'pdfjs-dist/legacy/build/pdf.mjs' }],
  },
})
