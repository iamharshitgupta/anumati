from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import StepUpResponse
from ..store import get_store, utcnow_iso

router = APIRouter(prefix="/v1/stepups", tags=["step-up"])


@router.get("")
def list_stepups(user_id: str | None = None, status: str | None = "pending"):
    f = []
    if user_id:
        f.append(("user_id", "==", user_id))
    if status:
        f.append(("status", "==", status))
    return get_store().query("stepups", f, order_by="created_at", descending=True, limit=50)


@router.post("/{stepup_id}/respond")
def respond(stepup_id: str, body: StepUpResponse):
    """Account holder's one-tap answer. In the Firebase console this arrives via a
    Firestore realtime listener (and FCM push when configured)."""
    store = get_store()
    su = store.get("stepups", stepup_id)
    if not su:
        raise HTTPException(404, "step-up not found")
    if su["status"] != "pending":
        raise HTTPException(409, f"step-up already {su['status']}")
    new_status = "approved" if body.approve else "declined"
    store.update("stepups", stepup_id, {"status": new_status, "responded_at": utcnow_iso(), "note": body.note})
    dec = store.get("decisions", su["decision_id"])
    if dec:
        store.update("decisions", dec["id"], {"status": "settled" if body.approve else "declined",
                                              "stepup_outcome": new_status})
        # append an addendum receipt-note so the audit trail records the human's call
        rc = store.get("receipts", dec["receipt_id"])
        if rc:
            store.update("receipts", rc["id"], {"human_confirmation": {"outcome": new_status, "at": utcnow_iso(), "note": body.note}})
    return {"stepup_id": stepup_id, "status": new_status, "decision_id": su["decision_id"]}
