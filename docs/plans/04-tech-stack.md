# Step 4 — Tech stack & site build (decision record)

Deferred from plan 03 until the dataset shape and optimizer were proven; both
now are (plans 01–03, 06–07 shipped, 99 golden tests, working POC). This
document records the decisions for the real product web UI that replaces the
POC (`tools/test-ui.html` + `tools/test-server.py`).

## Decisions

| Area | Decision |
|---|---|
| Backend | **FastAPI wrapping `scripts/optimize.py` in-process** (`server/app.py`): import, not subprocess — the optimizer stays the repo's single computation engine, unported. Dataset loaded once at startup. |
| Backend hosting | **Local-only for v1**: the user runs `python3 server/app.py` (http://localhost:8000). Cloud deploy deferred — no auth story, personal-use tool. The app is deploy-ready (stateless per request, single dataset cache). |
| Frontend | **Vite + React + TypeScript**, static build in `site/`. Runtime deps react/react-dom only; plain CSS custom properties (light/dark via `prefers-color-scheme` + manual `data-theme` toggle, the `card-entry-form.html` precedent); no Tailwind/CSS-in-JS. |
| Frontend hosting | **GitHub Pages** via GitHub Actions on push to main (`.github/workflows/deploy-site.yml`), served at `https://rithkott.github.io/credit_card_picker/` (Vite `--base=/credit_card_picker/` passed in CI). |
| v1 scope | POC parity + polish: spend entry (plan 03 UX), usage questionnaire, options, results view. No persistence, no card browser, no analytics, no monetization (docs/research.md), no bank linking. |

## Rejected alternatives

- **POC subprocess model** (temp YAML + `optimize.py --json` per request): re-parses the 114-card dataset on every call and forces string-typed error handling; in-process import gives typed `InputError`/`DataError` and a warm dataset.
- **Flask**: FastAPI provides CORS middleware, lifespan hooks, and TestClient at comparable weight.
- **Next.js / SSR**: nothing to render server-side — the computation engine is Python; a static SPA is the whole frontend story.
- **Pyodide (optimizer in-browser via WASM)**: kept `optimize.py` as the sole engine and would have allowed a fully static site, but adds a ~7MB runtime and multi-x slowdown on an already seconds-long search; the local-API model was chosen instead.
- **TypeScript port of the optimizer**: two engines to keep in lockstep with the golden tests forever — rejected outright.
- **Cloud-hosting the API now**: deferred (no auth, personal use; revisit with Render/Fly when sharing beyond one machine).

## API contract (`server/app.py`)

- `GET /api/health` → `{"ok": true, "cards_total": N}` — the frontend's liveness probe.
- `GET /api/config` → everything the form needs in one call, built from the loaded registries + `optimize.py` constants: `categories` (13, registry order, pseudo filtered), `merchants` (with parent category), `usage_questions` (group order preserved), `tier_order`, `user_defaults`, `reward_kinds`, `max_cards_range`, `cards_total`. **The site embeds no registry copies** — this endpoint is the anti-drift mechanism the `file://` forms couldn't have.
- `POST /api/optimize` — body `{spend, merchant_spend?, user, as_of?, top?}`. **No Pydantic model**: `parse_profile` is the single validator; a Pydantic mirror would be a second drift surface. `as_of` defaults to `date.today()` **at request time** (a long-lived server never serves stale expiry math); accepting it in the body keeps runs reproducible. Response is the `run()` bundle verbatim.
- Errors: `InputError` → `422 {"detail": msg}`; `DataError` (incl. the max_cards search-budget blowout) → `500 {"detail": msg}`. The optimizer's messages are already user-directed and rendered verbatim by the UI.
- The endpoint is a sync `def` (FastAPI threadpool) so long searches don't wedge the event loop.
- Every optimize call writes a gitignored debug dump `server/debug-runs/<timestamp>.yaml` `{timestamp, request, status, result|error}` (carried over from the POC server).

## Secure-context model

GitHub Pages is https; the API is `http://localhost:8000`. Chrome and Firefox
exempt localhost from mixed-content blocking (a "potentially trustworthy
origin" per the Secure Contexts spec), so the deployed site can call the local
API. **Safari does not honor the exemption** — mitigation: `server/app.py`
statically mounts `site/dist` when present, so `npm run build` once gives a
fully-local all-http mode at `localhost:8000`. CORS allowlist (constant at the
top of `app.py`): the Pages origin + Vite dev origins.

## Toolchain

Python ≥ 3.12 (`server/requirements.txt` — the repo's first requirements file,
deliberately scoped to `server/` so the data/optimizer layer stays
stdlib + pyyaml + jsonschema). Node 22 LTS; `site/package-lock.json` is
committed and CI uses `npm ci`; no postinstall scripts.

## Testing

- `tests/test_server_api.py` (unittest, repo convention; skips cleanly when
  fastapi/httpx are absent): `/api/config` mirrored against the registries and
  `optimize.py` constants; **golden equivalence** — POSTing the example
  profile returns byte-for-byte `opt.render_json(opt.run(...))`; the
  422 error contract; debug-dump smoke. The suite pins the real `data/` paths
  explicitly because `test_optimizer.py` repoints the shared module at its
  frozen fixture.
- Frontend: vitest on `site/src/lib/` only (the `parse_profile` mirrors —
  cents math, validation, profile emission); components verified by the manual
  checklist in §Verification.

## CI / CD

- `validate-data.yml`: gains `server/**` + `tests/**` paths and installs
  `server/requirements.txt` so the API tests run rather than skip.
- `deploy-site.yml`: on push to main touching `site/**` — Node 22, `npm ci`,
  `npm run build -- --base=/credit_card_picker/`, `upload-pages-artifact` +
  `deploy-pages`. One-time repo setting: Pages → Source → "GitHub Actions".

## Governance

- CLAUDE.md: changes to `parse_profile`'s contract, `run()`'s bundle shape, or
  `TIER_ORDER`/`USER_DEFAULTS`/`REWARD_KINDS` must update
  `tests/test_server_api.py`, `site/src/types.ts`, and
  `site/src/lib/validation.ts` in the same change. The site embeds no registry
  copies; the embedded-lists rule stays scoped to `tools/card-entry-form.html`.
- `docs/architecture.md` gains the server/site nodes in the commits where each
  ships (the diagram documents only what is built).
- POC retirement: `tools/test-ui.html` + `tools/test-server.py` are deleted
  only after the verification checklist passes — they are the parity baseline.

## Verification (manual end-to-end checklist)

1. `pip install -r server/requirements.txt && python3 server/app.py`; `curl localhost:8000/api/health`.
2. `cd site && npm ci && npm run dev` — 13 categories in registry order/labels; all questionnaire groups render.
3. Golden round-trip: enter the example-profile numbers → results equal `python3 scripts/optimize.py --profile examples/spend-profile.example.yaml --rewards cashback,flights,hotels --json` at the same `as_of`.
4. Monthly/annual toggle round-trips losslessly; carve-out budget line live-updates.
5. E1–E5 each block the run with their messages; W1 nudges without blocking.
6. Checked questionnaire chips appear in the bundle's `confirmed_usage` and flip a gated credit from $0.
7. Kill the server mid-session → banner with start instructions; restart + Retry recovers.
8. `max_cards=5` search-budget blowout → 500 detail rendered legibly.
9. `npm run build` → whole site served from `localhost:8000` (Safari path).
10. Push to main → Pages deploys; assets load under the `/credit_card_picker/` base; reaches the local API in Chrome/Firefox.

## Deferred

Cloud API hosting · profile persistence (localStorage / YAML import-export) ·
card-browser transparency page · Dockerfile · YAML import in the spend form.
