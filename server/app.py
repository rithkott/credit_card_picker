#!/usr/bin/env python3
"""Product API for the credit_card_picker web UI (docs/plans/04-tech-stack.md).

Wraps scripts/optimize.py IN-PROCESS — the optimizer stays the repo's single
computation engine; this file only maps HTTP to its functions:

  GET  /api/health      — liveness probe for the frontend's server banner.
  GET  /api/cards       — card-summary list for the site's Data-sources page:
                          identity, fee, currency, and the verification block,
                          straight from the loaded card files.
  GET  /api/assumptions — the point-valuation table (data/meta/
                          point-valuations.yaml) for the Assumptions page.
  GET  /api/config      — everything the form needs in one call (categories,
                        merchants, usage-question groups, tier order, user
                        defaults, reward kinds), built from the loaded
                        dataset and optimize.py constants. The site embeds
                        NO registry copies, so it cannot drift from the data.
  POST /api/optimize  — body {spend, merchant_spend?, user, as_of?, top?}.
                        parse_profile is the single validator (no Pydantic
                        mirror — that would be a second drift surface).
                        InputError -> 422 {"detail": msg},
                        DataError  -> 500 {"detail": msg}; the optimizer's
                        messages are already user-directed.
  POST /api/statements/parse — multipart, one statement file (PDF/CSV/OFX)
                        per request (plan 12). Parsed and categorized IN
                        MEMORY by server/statements/; transactions return
                        to the browser, the bytes are discarded — never
                        stored, never debug-dumped. Parse failures are
                        per-file {"detail", "code"} errors the UI renders
                        (422, or 413 for oversize files).

The dataset is loaded once at startup — restart (or run uvicorn --reload)
after editing card YAML. Every optimize call writes a gitignored debug dump to
server/debug-runs/<timestamp>.yaml with the exact request and the full result
(or error), same replay affordance as the retired POC server.

v1 runs locally only:  pip install -r server/requirements.txt
                       python3 server/app.py          # http://localhost:8000
If site/dist exists (npm run build), it is served at / — the all-localhost
mode that also sidesteps Safari's https->http://localhost restriction.
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server"))  # so `import statements` works everywhere
import optimize as opt  # noqa: E402

import statements as stmts  # noqa: E402  (server/statements/, plan 12)
from statements.categorize import Matcher, annotate  # noqa: E402

# Origins allowed to call the API: the GitHub Pages site (this repo's project
# page) and the Vite dev server. Update if the repo is renamed or forked.
ALLOWED_ORIGINS = [
    "https://rithkott.github.io",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

DEBUG_DIR = Path(__file__).resolve().parent / "debug-runs"
SITE_DIST = ROOT / "site" / "dist"

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["dataset"] = opt.load_dataset()
    # Statement-import rules (plan 09): read only here, never by the optimizer.
    # opt.META_DIR (not a local constant) so tests that repoint the dataset
    # repoint these too.
    meta = Path(opt.META_DIR)
    with open(meta / "statement-descriptors.yaml") as f:
        STATE["descriptors"] = yaml.safe_load(f)["descriptors"]
    with open(meta / "category-rules.yaml") as f:
        STATE["category_rules"] = yaml.safe_load(f)
    # Compiled once: the categorizer for POST /api/statements/parse (plan 12).
    STATE["matcher"] = Matcher(STATE["descriptors"], STATE["category_rules"],
                               STATE["dataset"]["merchants"],
                               STATE["dataset"]["usage_questions"])
    yield
    STATE.clear()


app = FastAPI(title="credit_card_picker API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def dump_debug_run(request_body: dict, status: int, payload: dict) -> None:
    """One YAML per optimize call — the exact request plus the full result or
    error. A debugging aid must never break the request itself.

    LOCAL-ONLY BY POLICY: on the hosted deployment (Vercel sets VERCEL=1)
    dumps are disabled outright — the privacy promise is that user spend
    totals are computed on and discarded, never written anywhere. The
    read-only serverless filesystem would make the write fail anyway; this
    guard makes no-storage a guarantee instead of an accident."""
    if os.environ.get("VERCEL"):
        return
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        now = datetime.now()
        record = {"timestamp": now.isoformat(timespec="milliseconds"),
                  "request": request_body, "status": status}
        record["result" if status == 200 else "error"] = payload
        path = DEBUG_DIR / f"{now.strftime('%Y-%m-%dT%H-%M-%S.%f')[:-3]}.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(record, f, sort_keys=False, allow_unicode=True)
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        sys.stderr.write(f"debug dump: {shown}\n")
    except OSError as e:
        sys.stderr.write(f"debug dump FAILED: {e}\n")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "cards_total": len(STATE["dataset"]["cards"])}


@app.get("/api/cards")
def cards() -> dict:
    """Card summaries for the Data-sources page — one row per card file,
    including the verification block so the page can be honest about
    confidence. No registry copy: labels come from the loaded dataset."""
    ds = STATE["dataset"]
    programs = ds["programs"]
    out = []
    for card in ds["cards"]:
        cur = card["currency"]
        ver = card.get("verification", {})
        out.append({
            "id": card["id"],
            "name": card["name"],
            "issuer": card["issuer"],
            "network": card.get("network"),
            "annual_fee_usd": card["fees"]["annual_fee_usd"],
            "currency": {
                "type": cur["type"],
                "program": cur["program"],
                "program_label": programs[cur["program"]].get("label", cur["program"]),
            },
            "base_rate": card.get("base_rate"),
            "verification": {
                "last_verified_date": ver.get("last_verified_date"),
                "confidence": ver.get("confidence"),
                "verified_by": ver.get("verified_by"),
            },
        })
    return {"cards": out, "total": len(out)}


@app.get("/api/assumptions")
def assumptions() -> dict:
    """The shared valuation table for the Assumptions page — the exact
    numbers the optimizer uses, straight from point-valuations.yaml."""
    ds = STATE["dataset"]
    return {
        "programs": [
            {"key": key,
             "label": entry.get("label", key),
             "redeems_for": entry.get("redeems_for", []),
             "floor_cpp": entry["floor_cpp"],
             "optimistic_cpp": entry["optimistic_cpp"],
             "transfer_gateway_required": entry.get("transfer_gateway_required", False),
             "loyalty_keys": entry.get("loyalty_keys", [])}
            for key, entry in ds["programs"].items()],
    }


@app.get("/api/config")
def config() -> dict:
    """The form's single source of truth, straight from the registries."""
    ds = STATE["dataset"]
    verified_dates = [
        d for d in ((c.get("verification") or {}).get("last_verified_date")
                    for c in ds["cards"]) if d]
    return {
        "data_last_verified": max(verified_dates) if verified_dates else None,
        "categories": [
            {"key": key, "label": entry.get("label", key)}
            for key, entry in ds["categories"].items()
            if not (entry or {}).get("pseudo")],
        "merchants": [
            {"key": key, "label": entry.get("label", key),
             "category": entry["category"]}
            for key, entry in ds["merchants"].items()],
        "usage_questions": [
            {"key": gkey, "label": group["label"], "prompt": group["prompt"],
             "items": [{"key": ikey, "label": item["label"]}
                       for ikey, item in group["items"].items()]}
            for gkey, group in ds["usage_questions"].items()],
        "tier_order": opt.TIER_ORDER,
        "user_defaults": opt.USER_DEFAULTS,
        "reward_kinds": opt.REWARD_KINDS,
        "max_cards_range": [1, 5],
        "cards_total": len(ds["cards"]),
        # Statement-import rules are no longer shipped to the browser: since
        # plan 12 the server parses AND categorizes statements itself
        # (POST /api/statements/parse), so the registries stay server-side.
    }


@app.post("/api/optimize")
def optimize(body: dict = Body(...)) -> dict:
    """Sync def on purpose: FastAPI runs it in a threadpool, so a long
    exhaustive search doesn't wedge the event loop."""
    as_of_raw = body.get("as_of")
    top = body.get("top", 5)
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise HTTPException(422, detail=f"top must be an integer >= 1, got {top!r}")
    if as_of_raw is not None:
        try:
            as_of = date.fromisoformat(as_of_raw)
        except (TypeError, ValueError):
            raise HTTPException(422, detail=f"as_of must be YYYY-MM-DD, got {as_of_raw!r}")
    else:
        as_of = date.today()  # per request, so a long-lived server never serves stale expiry math

    raw = {k: body[k] for k in ("spend", "merchant_spend", "user") if k in body}
    try:
        profile = opt.parse_profile(raw, STATE["dataset"])
        bundle = opt.run(STATE["dataset"], profile, as_of, top)
    except opt.InputError as e:
        dump_debug_run(body, 422, {"detail": str(e)})
        raise HTTPException(422, detail=str(e))
    except opt.DataError as e:  # incl. the max_cards search-budget blowout
        dump_debug_run(body, 500, {"detail": str(e)})
        raise HTTPException(500, detail=str(e))
    dump_debug_run(body, 200, bundle)
    return bundle


@app.post("/api/statements/parse")
def parse_statement_upload(file: UploadFile = File(...)):
    """One statement file in, normalized + categorized transactions out.

    Sync def on purpose (threadpool, like /api/optimize) — PDF extraction is
    CPU-bound. EPHEMERAL BY POLICY: the bytes live only in this frame; there
    is no dump_debug_run call on this route, errors are returned without
    statement content, and nothing is written anywhere. The browser keeps
    review/aggregation; this endpoint is one file -> one parse."""
    name = file.filename or "statement"
    data = file.file.read()
    try:
        parsed = stmts.parse_statement(data, name)
        annotate(STATE["matcher"], parsed.txns)
    except stmts.StatementParseError as e:
        status = 413 if e.code == "too_large" else 422
        return JSONResponse(status_code=status,
                            content={"detail": str(e), "code": e.code})
    except Exception:
        # Never leak statement content into logs or the response; the type
        # alone is enough to find the bug with a local reproduction.
        return JSONResponse(status_code=500,
                            content={"detail": f"{name}: unexpected error while parsing.",
                                     "code": "internal"})
    return parsed.to_dict()


# Serve the built site when present (npm run build) — registered after the
# API routes so /api/* always wins. This is the fully-local mode: everything
# on http://localhost:8000, no cross-origin. The catch-all (instead of a
# plain StaticFiles mount) gives the SPA history-router fallback: client
# routes like /how-it-works serve index.html, real files serve themselves.
if SITE_DIST.is_dir():
    from fastapi.responses import FileResponse

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        file = (SITE_DIST / path).resolve()
        if path and file.is_relative_to(SITE_DIST) and file.is_file():
            return FileResponse(file)
        return FileResponse(SITE_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
