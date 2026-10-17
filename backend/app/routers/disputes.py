from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..auth import Caller, require_owner, require_role, scoped_user
from ..gemini import generate_json
from ..models import DisputeCreate
from ..receipts import LIABILITY_HINTS, verify_signature
from ..store import get_store, utcnow_iso

router = APIRouter(prefix="/v1/disputes", tags=["disputes"])

_SYSTEM = """You are a dispute adjudication assistant for AI-agent-initiated UPI payments.
You are given a signed Decision Receipt (mandate, attempted payment, findings with evidence, verdict) and a dispute claim.
Produce a neutral attribution memo following the AP2-style liability matrix:
- user: mandate was clear and the payment matched it, or the user confirmed a step-up
- agent_provider: the agent deviated from the mandate without being deceived by content (drift, cap violations, structuring)
- merchant_or_content_provider: content consumed by the agent contained injected instructions that caused the deviation
- issuer: gateway approved despite findings that should have blocked/held, or blocked a compliant payment
Be specific: cite finding codes and evidence. State what is established, what is unresolved, and what evidence would resolve it.
Never invent facts not in the receipt. Return ONLY JSON."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_party": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "established": {"type": "array", "items": {"type": "string"}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "evidence_needed": {"type": "array", "items": {"type": "string"}},
        "memo": {"type": "string"},
    },
    "required": ["primary_party", "confidence", "established", "unresolved", "memo"],
}


def _heuristic_attribution(receipt: dict, claim: str) -> dict:
    codes = [f["code"] for f in receipt.get("findings", [])]
    hints = [LIABILITY_HINTS[c] for c in codes if c in LIABILITY_HINTS]
    verdict = receipt["verdict"]
    if "INJECTION" in codes:
        party, conf = "merchant_or_content_provider", "high" if receipt["semantic_audit"].get("injection_score", 0) >= 60 else "medium"
    elif any(c in codes for c in ("DRIFT", "PAYEE_NOT_ALLOWED", "STRUCTURING", "PER_TXN_CAP", "PERIOD_CAP", "QUANTITY_ANOMALY")):
        party, conf = "agent_provider", "medium"
    elif verdict == "APPROVE" and not codes:
        party, conf = "user", "medium"
    elif receipt.get("human_confirmation", {}).get("outcome") == "approved":
        party, conf = "user", "high"
    else:
        party, conf = "issuer", "low"
    established = [f"Gateway verdict was {verdict} with risk {receipt['risk_score']}/100"] + [
        f"{f['code']}: {f['message']}" for f in receipt.get("findings", [])[:5]]
    unresolved = [] if codes else ["No gateway findings; deviation (if any) occurred outside observed signals"]
    return {
        "primary_party": party, "confidence": conf, "established": established, "unresolved": unresolved,
        "evidence_needed": ["Agent provider's full session log", "Merchant page snapshot at time of purchase"] if party != "user" else [],
        "memo": f"Heuristic attribution: {party} ({conf} confidence). Liability hints from findings: {sorted(set(hints)) or 'none'}. "
                f"Claim: {claim}",
        "engine": "heuristic",
    }


@router.post("")
def create_dispute(body: DisputeCreate, caller: Caller):
    store = get_store()
    dec = store.get("decisions", body.decision_id)
    if not dec:
        raise HTTPException(404, "decision not found")
    user_id = dec.get("request", {}).get("user_id")
    require_owner(caller, user_id, staff_read=True)
    mandate_id = dec.get("request", {}).get("mandate_id")
    mandate = store.get("mandates", mandate_id) if mandate_id else None
    simulated = bool(dec.get("request", {}).get("simulated"))
    sandbox = bool(simulated and mandate and mandate.get("demo_fixture"))
    if not caller.is_staff and not sandbox and body.raised_by != "user":
        raise HTTPException(403, "Only staff can raise a dispute for another party")
    rc = store.get("receipts", dec["receipt_id"])
    if not rc:
        raise HTTPException(404, "receipt not found")
    sig_ok = verify_signature(rc)
    prompt = f"RECEIPT (signature_valid={sig_ok}):\n{rc}\n\nDISPUTE raised_by={body.raised_by}:\n{body.claim}"
    out = generate_json(_SYSTEM, prompt, schema=_SCHEMA)
    attribution = {**out, "engine": "gemini"} if out else _heuristic_attribution(rc, body.claim)
    did = f"dsp_{uuid.uuid4().hex[:10]}"
    d = {
        "user_id": user_id, "raised_by_uid": caller.uid, "mandate_id": mandate_id,
        "simulated": simulated, "sandbox": sandbox,
        "decision_id": body.decision_id, "receipt_id": rc["id"], "raised_by": body.raised_by, "claim": body.claim,
        "receipt_signature_valid": sig_ok, "attribution": attribution, "status": "open", "created_at": utcnow_iso(),
        "replay": {
            "mandate_text": rc.get("mandate_text"), "attempted": rc.get("attempted"), "verdict": rc.get("verdict"),
            "findings": rc.get("findings"), "semantic_audit": rc.get("semantic_audit"),
            "human_confirmation": rc.get("human_confirmation"),
        },
    }
    store.put("disputes", did, d)
    d["id"] = did
    return d


@router.get("")
def list_disputes(caller: Caller, limit: int = 50):
    user_id = scoped_user(caller)
    filters = [("user_id", "==", user_id)] if user_id else []
    return get_store().query("disputes", filters, order_by="created_at", descending=True, limit=limit)


@router.get("/{dispute_id}")
def get_dispute(dispute_id: str, caller: Caller):
    d = get_store().get("disputes", dispute_id)
    if not d:
        raise HTTPException(404, "dispute not found")
    require_owner(caller, d.get("user_id"), staff_read=True)
    return d


@router.post("/{dispute_id}/resolve")
def resolve(dispute_id: str, body: dict, caller: Caller):
    require_role(caller, "analyst", "admin")
    return resolve_record(dispute_id, body, caller)


def resolve_record(dispute_id: str, body: dict, caller: Caller, *, sandbox: bool = False):
    store = get_store()
    d = store.get("disputes", dispute_id)
    if not d:
        raise HTTPException(404, "dispute not found")
    if sandbox:
        require_owner(caller, d.get("user_id"))
        mandate = store.get("mandates", d.get("mandate_id", "")) if d.get("mandate_id") else None
        if not (d.get("sandbox") and d.get("simulated") and mandate and mandate.get("demo_fixture")):
            raise HTTPException(403, "Sandbox resolution requires a synthetic demo fixture")
        require_owner(caller, mandate.get("user_id"))
    else:
        require_role(caller, "analyst", "admin")
    store.update("disputes", dispute_id, {"status": "resolved", "resolution": body.get("resolution"),
                                          "resolved_party": body.get("party"), "resolved_at": utcnow_iso(),
                                          "resolved_by": caller.uid,
                                          "resolution_scope": "sandbox" if sandbox else "staff"})
    return store.get("disputes", dispute_id)
