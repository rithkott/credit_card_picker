#!/usr/bin/env python3
"""Business product API (plan 22D) — /api/business/*.

Wraps scripts/optimize_business.py IN-PROCESS, the same relationship
server/app.py has with the consumer engine: this file only maps HTTP to the
engine's functions, and parse_business_profile stays the single validator (no
Pydantic mirror — that would be a second drift surface).

  GET  /api/business/health       — liveness + business-corpus size.
  GET  /api/business/cards        — card summaries for the business
                                    data-sources page (identity, pricing,
                                    approval axis, employee-card economics,
                                    verification block).
  GET  /api/business/assumptions  — the business point-valuation table.
  GET  /api/business/config       — everything the business form needs in one
                                    call: categories, merchants, usage
                                    questions, company/personal field enums +
                                    defaults, issuer application rules,
                                    personal gateway choices. The business
                                    frontend embeds NO registry copies.
  POST /api/business/optimize     — body {spend, merchant_spend?, company,
                                    personal?, user?, exclude_cards?, as_of?,
                                    top?} → the business OptimizeBundle.
  POST /api/business/evaluate     — + required `cards` id list (Manual mode).
  POST /api/business/suggest-addition — + required `cards` held list; returns
                                    the evaluate bundle for held + best pick
                                    with `added_card`.

Error mapping mirrors the consumer API: InputError → 422 {"detail": msg},
DataError → 500 {"detail": msg}. Debug dumps reuse app.py's dump_debug_run
policy via a callback injected at include time (local-only, disabled on
Vercel) — this module never writes files itself.

The business dataset is loaded once by app.py's lifespan into BIZ_STATE.
The consumer API is untouched: its endpoints, shapes, and tests are pinned by
tests/test_server_api.py, and this router adds only /api/business/* routes.
"""

import sys
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import optimize_business as bopt  # noqa: E402

router = APIRouter(prefix="/api/business")

BIZ_STATE: dict = {}

# Injected by app.py at include time so business runs share the consumer
# debug-dump policy (local-only, never on Vercel). Default: no-op.
_dump = lambda body, status, payload: None  # noqa: E731


def configure(dump_debug_run=None) -> None:
    """Called by app.py: share its debug-dump function."""
    global _dump
    if dump_debug_run is not None:
        _dump = dump_debug_run


def load() -> None:
    """Load the business dataset (called from app.py's lifespan)."""
    BIZ_STATE["dataset"] = bopt.load_dataset()


def unload() -> None:
    BIZ_STATE.clear()


def _parse_as_of(raw):
    if raw is None:
        return date.today()  # per request — never stale expiry math
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, detail=f"as_of must be YYYY-MM-DD, got {raw!r}")


PROFILE_KEYS = ("spend", "merchant_spend", "company", "personal", "user",
                "exclude_cards")


@router.get("/health")
def health() -> dict:
    return {"ok": True, "cards_total": len(BIZ_STATE["dataset"]["cards"])}


@router.get("/cards")
def cards() -> dict:
    """Business card summaries — one row per card file, including the
    approval axis and employee-card economics the consumer list has no
    analog for, plus the verification block for honesty about confidence."""
    ds = BIZ_STATE["dataset"]
    programs = ds["programs"]
    out = []
    for card in ds["cards"]:
        cur = card["currency"]
        ver = card.get("verification", {})
        pricing = card["pricing"]
        ba = card["business_approval"]
        ec = card.get("employee_cards") or {}
        out.append({
            "id": card["id"],
            "name": card["name"],
            "issuer": card["issuer"],
            "network": card.get("network"),
            "availability": card.get("availability", "active"),
            "pricing": {
                "model": pricing["model"],
                "annual_fee_usd": pricing.get("annual_fee_usd"),
                "first_year_waived": bool(pricing.get("first_year_waived")),
                "fee_refund_spend_usd": pricing.get("fee_refund_spend_usd"),
                "per_seat_monthly_usd": pricing.get("per_seat_monthly_usd"),
                "free_tier": pricing.get("free_tier"),
            },
            "business_approval": {
                "personal_guarantee": ba["personal_guarantee"],
                "min_personal_fico_tier": ba.get("min_personal_fico_tier"),
                "entity_types": ba["entity_types"],
                "requires_ein": bool(ba.get("requires_ein")),
                "min_cash_balance_usd": ba.get("min_cash_balance_usd"),
                "min_annual_revenue_usd": ba.get("min_annual_revenue_usd"),
                "funding_qualifies": bool(ba.get("funding_qualifies")),
            },
            "employee_cards": {
                "fee_usd": ec.get("fee_usd", 0),
                "controls": sorted(ec.get("controls") or []),
            },
            "payment_type": card.get("payment_type"),
            "integrations": sorted(card.get("integrations") or []),
            "virtual_cards": bool(card.get("virtual_cards")),
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


@router.get("/assumptions")
def assumptions() -> dict:
    """The business valuation table — the exact numbers the business engine
    uses, straight from data/business/meta/point-valuations.yaml."""
    ds = BIZ_STATE["dataset"]
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


@router.get("/config")
def config() -> dict:
    """The business form's single source of truth, straight from the
    registries and optimize_business.py constants."""
    ds = BIZ_STATE["dataset"]
    verified_dates = [
        d for d in ((c.get("verification") or {}).get("last_verified_date")
                    for c in ds["cards"]) if d]
    return {
        "data_last_verified": max(verified_dates) if verified_dates else None,
        "categories": [
            {"key": key, "label": entry.get("label", key)}
            for key, entry in ds["categories"].items()],
        "merchants": [
            {"key": key, "label": entry.get("label", key),
             "category": entry["category"]}
            for key, entry in ds["merchants"].items()],
        "usage_questions": [
            {"key": gkey, "label": group["label"], "prompt": group["prompt"],
             "assumed_reward_kind": group.get("assumed_reward_kind"),
             "items": [{"key": ikey, "label": item["label"]}
                       for ikey, item in group["items"].items()]}
            for gkey, group in ds["usage_questions"].items()],
        "issuer_rules": {
            issuer: {
                "gate_524": bool(rules.get("gate_524")),
                "adds_to_524": bool(rules.get("adds_to_524")),
                "adds_to_524_exceptions": rules.get("adds_to_524_exceptions", []),
                "credit_card_limit": rules.get("credit_card_limit"),
                "charge_exempt": bool(rules.get("charge_exempt")),
                "once_per_lifetime_bonus": bool(rules.get("once_per_lifetime_bonus")),
                "velocity_note": rules.get("velocity_note"),
            }
            for issuer, rules in sorted((ds["issuer_rules"] or {}).items())},
        "tier_order": bopt.TIER_ORDER,
        "entity_types": bopt.ENTITY_TYPES,
        "personal_gateways": bopt.PERSONAL_GATEWAYS,
        "user_defaults": bopt.USER_DEFAULTS,
        "company_defaults": bopt.COMPANY_DEFAULTS,
        "personal_defaults": bopt.PERSONAL_DEFAULTS,
        "reward_kinds": bopt.REWARD_KINDS,
        "max_cards_range": [1, 5],
        "cards_total": len(ds["cards"]),
    }


@router.post("/optimize")
def optimize(body: dict = Body(...)) -> dict:
    """Sync def on purpose (threadpool): the exhaustive subset search is
    CPU-bound, same rationale as the consumer /api/optimize."""
    top = body.get("top", 5)
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise HTTPException(422, detail=f"top must be an integer >= 1, got {top!r}")
    as_of = _parse_as_of(body.get("as_of"))
    raw = {k: body[k] for k in PROFILE_KEYS if k in body}
    try:
        profile = bopt.parse_business_profile(raw, BIZ_STATE["dataset"])
        bundle = bopt.run(BIZ_STATE["dataset"], profile, as_of, top)
    except bopt.InputError as e:
        _dump(body, 422, {"detail": str(e)})
        raise HTTPException(422, detail=str(e))
    except bopt.DataError as e:  # incl. the search-budget blowout
        _dump(body, 500, {"detail": str(e)})
        raise HTTPException(500, detail=str(e))
    _dump(body, 200, bundle)
    return bundle


@router.post("/evaluate")
def evaluate(body: dict = Body(...)) -> dict:
    """Manual mode: score exactly the user-picked business cards. Same
    profile contract as /api/business/optimize plus a required `cards` list;
    returns the identical bundle shape (single best_by_size entry)."""
    as_of = _parse_as_of(body.get("as_of"))
    cards_ids = body.get("cards")
    raw = {k: body[k] for k in PROFILE_KEYS if k in body}
    try:
        profile = bopt.parse_business_profile(raw, BIZ_STATE["dataset"])
        bundle = bopt.evaluate(BIZ_STATE["dataset"], profile, as_of, cards_ids)
    except bopt.InputError as e:
        _dump(body, 422, {"detail": str(e)})
        raise HTTPException(422, detail=str(e))
    except bopt.DataError as e:
        _dump(body, 500, {"detail": str(e)})
        raise HTTPException(500, detail=str(e))
    _dump(body, 200, bundle)
    return bundle


@router.post("/suggest-addition")
def suggest_addition(body: dict = Body(...)) -> dict:
    """Best-additional-card: given the held set (`cards`), return the
    evaluate bundle for held + the best eligible addition, with `added_card`
    naming the pick. Candidates honor the Auto filters and issuer limits."""
    as_of = _parse_as_of(body.get("as_of"))
    cards_ids = body.get("cards")
    raw = {k: body[k] for k in PROFILE_KEYS if k in body}
    try:
        profile = bopt.parse_business_profile(raw, BIZ_STATE["dataset"])
        bundle = bopt.augment(BIZ_STATE["dataset"], profile, as_of, cards_ids)
    except bopt.InputError as e:
        _dump(body, 422, {"detail": str(e)})
        raise HTTPException(422, detail=str(e))
    except bopt.DataError as e:
        _dump(body, 500, {"detail": str(e)})
        raise HTTPException(500, detail=str(e))
    _dump(body, 200, bundle)
    return bundle
