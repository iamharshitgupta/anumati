from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

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
def create_dispute(body: DisputeCreate):
    store = get_store()
    dec = store.get("decisions", body.decision_id)
    if not dec:
        raise HTTPException(404, "decision not found")
    rc = store.get("receipts", dec["receipt_id"])
    if not rc:
        raise HTTPException(404, "receipt not found")
    sig_ok = verify_signature(rc)
    prompt = f"RECEIPT (signature_valid={sig_ok}):\n{rc}\n\nDISPUTE raised_by={body.raised_by}:\n{body.claim}"
    out = generate_json(_SYSTEM, prompt, schema=_SCHEMA)
    attribution = {**out, "engine": "gemini"} if out else _heuristic_attribution(rc, body.claim)
    did = f"dsp_{uuid.uuid4().hex[:10]}"
    d = {
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
def list_disputes(limit: int = 50):
    return get_store().query("disputes", order_by="created_at", descending=True, limit=limit)


@router.get("/{dispute_id}")
def get_dispute(dispute_id: str):
    d = get_store().get("disputes", dispute_id)
    if not d:
        raise HTTPException(404, "dispute not found")
    return d


@router.post("/{dispute_id}/resolve")
def resolve(dispute_id: str, body: dict):
    store = get_store()
    d = store.get("disputes", dispute_id)
    if not d:
        raise HTTPException(404, "dispute not found")
    store.update("disputes", dispute_id, {"status": "resolved", "resolution": body.get("resolution"),
                                          "resolved_party": body.get("party"), "resolved_at": utcnow_iso()})
    return store.get("disputes", dispute_id)
