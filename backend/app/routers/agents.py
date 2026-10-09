from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import AgentRegistration
from ..store import get_store, utcnow_iso

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post("", response_model=dict)
def register(body: AgentRegistration):
    """Agent registry — the UAP/AP2 notion that an agent must be registered and
    attested before it may touch a payment rail."""
    store = get_store()
    d = body.model_dump()
    d.update({"registered_at": utcnow_iso(), "status": "active"})
    store.put("agents", body.agent_id, d)
    return d


@router.get("", response_model=list[dict])
def list_agents():
    return get_store().query("agents", order_by="registered_at", descending=True, limit=100)


@router.get("/{agent_id}", response_model=dict)
def get_agent(agent_id: str):
    a = get_store().get("agents", agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    return a
