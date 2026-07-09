#!/usr/bin/env python3
"""Product API for the credit_card_picker web UI (docs/plans/04-tech-stack.md).

Wraps scripts/optimize.py IN-PROCESS — the optimizer stays the repo's single
computation engine; this file only maps HTTP to its functions:

  GET  /api/health    — liveness probe for the frontend's server banner.
  GET  /api/config    — everything the form needs in one call (categories,
                        merchants, usage-question groups, tier order, user
                        defaults, reward kinds, statement-import rules), built
                        from the loaded dataset and optimize.py constants. The
                        site embeds NO registry copies, so it cannot drift
                        from the data.
  POST /api/optimize  — body {spend, merchant_spend?, user, as_of?, top?}.
                        parse_profile is the single validator (no Pydantic
                        mirror — that would be a second drift surface).
                        InputError -> 422 {"detail": msg},
                        DataError  -> 500 {"detail": msg}; the optimizer's
                        messages are already user-directed.

The dataset loads from the compiled SQLite artifact (scripts/build_db.py,
plan 10 §4-5), rebuilt automatically whenever the YAML sources change — a
cheap stat signature is checked per request, so editing a card file is picked
up on the next call, no restart. POST /api/reload forces it. Results are
served from an LRU cache keyed by (profile, as_of, top, dataset_hash): the
optimizer is a pure function, so identical inputs against identical data are
safe to replay; cache hits skip the debug dump. Every computed optimize call
still writes a gitignored debug dump to server/debug-runs/<timestamp>.yaml
with the exact request and the full result (or error), same replay affordance
as the retired POC server.

v1 runs locally only:  pip install -r server/requirements.txt
                       python3 server/app.py          # http://localhost:8000
If site/dist exists (npm run build), it is served at / — the all-localhost
mode that also sidesteps Safari's https->http://localhost restriction.
"""

import hashlib
import json
import sys
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_db  # noqa: E402
import optimize as opt  # noqa: E402

# Origins allowed to call the API: the GitHub Pages site (this repo's project
# page) and the Vite dev server. Update if the repo is renamed or forked.
ALLOWED_ORIGINS = [
    "https://rithkott.github.io",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

DEBUG_DIR = Path(__file__).resolve().parent / "debug-runs"
SITE_DIST = ROOT / "site" / "dist"
DB_PATH = ROOT / "data" / "build" / "cards.sqlite"
RESULT_CACHE_SIZE = 128

STATE: dict = {}

# Serializes load_state: FastAPI runs sync endpoints in a threadpool, so two
# concurrent requests can both see a moved stat signature — without the lock
# both would rebuild the same cards.sqlite and one could read a half-built
# artifact (empty tables, no meta row) and install an empty snapshot.
_RELOAD_LOCK = threading.Lock()


def _stat_signature() -> tuple:
    """Cheap change detector over every dataset source file: (path, mtime_ns,
    size) triples. ~120 stat calls per request — microseconds, not the full
    sha256 manifest (that runs only when this signature moves)."""
    sig = []
    for p in (sorted(Path(opt.CARDS_DIR).glob("*/*.yaml"))
              + sorted(Path(opt.META_DIR).glob("*.yaml"))):
        st = p.stat()
        sig.append((str(p), st.st_mtime_ns, st.st_size))
    return tuple(sig)


def load_state() -> None:
    """(Re)load everything: rebuild the SQLite artifact when the YAML sources
    changed, load the dataset from it (YAML fallback if the artifact cannot be
    built), reset the result cache. Called at startup, on POST /api/reload,
    and whenever the per-request stat signature moves. Callers serialize via
    _RELOAD_LOCK (ensure_fresh, /api/reload, startup)."""
    # Capture the signature BEFORE reading any source: a file written during
    # the ~1s load window then leaves the stored signature stale, so the next
    # request reloads and converges — recording it after the load would absorb
    # the write into the signature while the snapshot still reflects the old
    # content, masking the change until some unrelated edit (plan 11 R4).
    sig = _stat_signature()
    build_db.CARDS_DIR = Path(opt.CARDS_DIR)
    build_db.META_DIR = Path(opt.META_DIR)
    try:
        if not build_db.is_fresh(DB_PATH):
            build_db.build(DB_PATH)
            sys.stderr.write(f"rebuilt {DB_PATH.name} from YAML sources\n")
        dataset = opt.load_dataset_db(DB_PATH)
        dataset_hash = build_db.stored_dataset_hash(DB_PATH)
    except Exception as e:  # artifact problems must never take the API down
        sys.stderr.write(f"DB artifact unavailable ({e}); loading YAML directly\n")
        dataset = opt.load_dataset()
        dataset_hash = build_db.dataset_manifest()[1]
    # Statement-import rules (plan 09): read only here, never by the optimizer.
    # opt.META_DIR (not a local constant) so tests that repoint the dataset
    # repoint these too.
    meta = Path(opt.META_DIR)
    with open(meta / "statement-descriptors.yaml") as f:
        descriptors = yaml.safe_load(f)["descriptors"]
    with open(meta / "category-rules.yaml") as f:
        category_rules = yaml.safe_load(f)
    # Requests run concurrently in FastAPI's threadpool. The snapshot is
    # swapped in with ONE assignment (atomic under the GIL) so no request can
    # ever observe a new dataset paired with an old dataset_hash — that mix
    # could cache a result under a hash that recurs if sources are reverted.
    STATE["snapshot"] = {"dataset": dataset, "dataset_hash": dataset_hash,
                         "result_cache": OrderedDict()}
    # Aliases point at the same objects — kept for tests and simple reads.
    STATE["dataset"] = dataset
    STATE["dataset_hash"] = dataset_hash
    STATE["result_cache"] = STATE["snapshot"]["result_cache"]
    STATE["descriptors"] = descriptors
    STATE["category_rules"] = category_rules
    STATE["stat_signature"] = sig


def ensure_fresh() -> None:
    """Per-request hot reload: if any source file's stat moved, reload (which
    also invalidates the result cache via the new dataset_hash). Double-checked
    locking: the lock-free stat check keeps the hot path at ~µs, and re-checking
    under the lock means concurrent stale requests trigger exactly one reload."""
    if _stat_signature() == STATE.get("stat_signature"):
        return
    with _RELOAD_LOCK:
        if _stat_signature() != STATE.get("stat_signature"):
            load_state()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with _RELOAD_LOCK:
        load_state()
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
    error. A debugging aid must never break the request itself."""
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


@app.post("/api/reload")
def reload_dataset() -> dict:
    """Force a dataset reload (rebuilds the SQLite artifact when stale). The
    per-request stat check makes this mostly redundant, but it is the explicit
    lever when file stats lie (e.g. a mounted volume with frozen mtimes)."""
    with _RELOAD_LOCK:
        load_state()
    return {"ok": True, "cards_total": len(STATE["dataset"]["cards"]),
            "dataset_hash": STATE["dataset_hash"]}


@app.get("/api/config")
def config() -> dict:
    """The form's single source of truth, straight from the registries."""
    ensure_fresh()
    ds = STATE["dataset"]
    return {
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
        # Most recent hand-verification date across the dataset — the site's
        # footer trust line quotes it instead of hardcoding a date.
        "data_last_verified": max(
            c["verification"]["last_verified_date"] for c in ds["cards"]),
        # Rules for the in-browser statement importer (plan 09). Rules travel
        # API -> browser; statement data never travels anywhere.
        "statement_import": {
            "descriptors": [
                {"key": key, "label": entry.get("label", key),
                 "patterns": entry["statement_patterns"]}
                for key, entry in STATE["descriptors"].items()],
            "descriptor_categories": STATE["category_rules"]["descriptor_categories"],
            "aggregator_prefixes": STATE["category_rules"]["aggregator_prefixes"],
            "unmapped": STATE["category_rules"]["unmapped"],
            "keywords": STATE["category_rules"]["keywords"],
            "issuer_categories": STATE["category_rules"]["issuer_categories"],
            "mcc": STATE["category_rules"]["mcc"],
        },
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

    ensure_fresh()
    # One snapshot read (atomic) — dataset, its hash, and its cache always
    # belong together even if a reload swaps them mid-flight.
    snap = STATE["snapshot"]
    dataset, cache = snap["dataset"], snap["result_cache"]
    raw = {k: body[k] for k in ("spend", "merchant_spend", "user") if k in body}
    try:
        profile = opt.parse_profile(raw, dataset)
        # Purity makes replays safe: same profile + as_of + top against the
        # same dataset_hash is byte-identical, so serve it from the LRU cache
        # (and skip the debug dump — the computed run already recorded one).
        key = hashlib.sha256(json.dumps(
            {"profile": profile, "as_of": as_of.isoformat(), "top": top,
             "dataset": snap["dataset_hash"]},
            sort_keys=True).encode()).hexdigest()
        if key in cache:
            cache.move_to_end(key)
            sys.stderr.write(f"cache hit: {key[:12]}\n")
            return cache[key]
        bundle = opt.run(dataset, profile, as_of, top)
    except opt.InputError as e:
        dump_debug_run(body, 422, {"detail": str(e)})
        raise HTTPException(422, detail=str(e))
    except opt.DataError as e:  # incl. the search-budget safety valves
        dump_debug_run(body, 500, {"detail": str(e)})
        raise HTTPException(500, detail=str(e))
    cache[key] = bundle
    while len(cache) > RESULT_CACHE_SIZE:
        cache.popitem(last=False)
    dump_debug_run(body, 200, bundle)
    return bundle


# Serve the built site when present (npm run build) — mounted after the API
# routes so /api/* always wins. This is the fully-local mode: everything on
# http://localhost:8000, no Pages, no cross-origin.
if SITE_DIST.is_dir():
    app.mount("/", StaticFiles(directory=SITE_DIST, html=True), name="site")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
