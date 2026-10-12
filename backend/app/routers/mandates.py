from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..auth import Caller, require_owner, scoped_user
from ..compiler import compile_mandate
from ..models import Mandate, MandateCompileRequest
from ..receipts import canonical
from ..store import get_store, utcnow_iso

router = APIRouter(prefix="/v1/mandates", tags=["mandates"])


@router.post("/compile", response_model=Mandate)
def compile_endpoint(body: MandateCompileRequest, caller: Caller):
    """Natural language → structured mandate (draft). User must sign to activate."""
    store = get_store()
    g, compiler, notes = compile_mandate(body.text)
    now = datetime.now(timezone.utc)
    m = Mandate(
        id=f"mnd_{uuid.uuid4().hex[:10]}",
        user_id=caller.uid, agent_id=body.agent_id,
        natural_language=body.text, guardrails=g, status="draft",
        created_at=now.isoformat(), expires_at=(now + timedelta(days=body.ttl_days)).isoformat(),
        compiler=compiler, compiler_notes=notes,
        demo_fixture=body.sandbox or caller.is_anonymous or caller.is_demo,
    )
    store.put("mandates", m.id, m.model_dump())
    return m


@router.post("/{mandate_id}/sign", response_model=Mandate)
def sign(mandate_id: str, caller: Caller, body: dict | None = None):
    """User confirms the compiled mandate. In production this is a device-bound
    signature (passkey / UPI PIN flow); here we record a confirmation hash."""
    store = get_store()
    m = store.get("mandates", mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    require_owner(caller, m.get("user_id"))
    if body and body.get("guardrails"):
        m["guardrails"] = {**m["guardrails"], **body["guardrails"]}
        m["version"] = m.get("version", 1) + 1
    sig_body = {k: m[k] for k in ("id", "user_id", "agent_id", "natural_language", "guardrails", "expires_at", "version")}
    sig = hashlib.sha256(canonical(sig_body)).hexdigest()
    m.update({"status": "active", "signed_at": utcnow_iso(), "signature": f"user-confirm:{sig[:32]}"})
    store.put("mandates", mandate_id, m)
    return m


@router.post("/{mandate_id}/revoke", response_model=Mandate)
def revoke(mandate_id: str, caller: Caller):
    store = get_store()
    m = store.get("mandates", mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    require_owner(caller, m.get("user_id"))
    m["status"] = "revoked"
    store.put("mandates", mandate_id, m)
    return m


@router.get("", response_model=list[Mandate])
def list_mandates(caller: Caller, user_id: str | None = None):
    store = get_store()
    user_id = scoped_user(caller, user_id)
    f = [("user_id", "==", user_id)] if user_id else []
    return store.query("mandates", f, order_by="created_at", descending=True, limit=100)


@router.get("/{mandate_id}", response_model=Mandate)
def get_mandate(mandate_id: str, caller: Caller):
    m = get_store().get("mandates", mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    require_owner(caller, m.get("user_id"), staff_read=True)
    return m
