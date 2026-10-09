from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..engine import decide
from ..models import Decision, PaymentRequest
from ..receipts import verify_signature
from ..store import get_store

router = APIRouter(prefix="/v1", tags=["decisions"])


@router.post("/payments/authorize", response_model=Decision)
def authorize(req: PaymentRequest):
    """The gateway call an agent (or the PSP fronting it) makes before a UPI
    collect/pay is initiated. Returns APPROVE / STEP_UP / BLOCK plus receipt id."""
    store = get_store()
    if req.idempotency_key:
        prior = store.query("decisions", [("request.idempotency_key", "==", req.idempotency_key)], limit=1)
        if prior:
            return prior[0]
    return decide(req, store)


@router.get("/decisions", response_model=list[Decision])
def list_decisions(user_id: str | None = None, limit: int = 50):
    store = get_store()
    f = [("request.user_id", "==", user_id)] if user_id else []
    return store.query("decisions", f, order_by="created_at", descending=True, limit=min(limit, 200))


@router.get("/decisions/{decision_id}", response_model=Decision)
def get_decision(decision_id: str):
    d = get_store().get("decisions", decision_id)
    if not d:
        raise HTTPException(404, "decision not found")
    return d


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: str):
    r = get_store().get("receipts", receipt_id)
    if not r:
        raise HTTPException(404, "receipt not found")
    r["signature_valid"] = verify_signature(r)
    return r


@router.get("/receipts")
def list_receipts(mandate_id: str | None = None, limit: int = 50):
    f = [("mandate_id", "==", mandate_id)] if mandate_id else []
    rows = get_store().query("receipts", f, order_by="issued_at", descending=True, limit=min(limit, 200))
    for r in rows:
        r["signature_valid"] = verify_signature(r)
    return rows


@router.post("/receipts/verify")
def verify_receipt(receipt: dict):
    """Offline verification: anyone with the receipt JSON can check hash + signature."""
    return {"valid": verify_signature(receipt), "hash": receipt.get("hash")}


@router.get("/receipts/chain/{mandate_id}")
def verify_chain(mandate_id: str):
    rows = get_store().query("receipts", [("mandate_id", "==", mandate_id)], order_by="issued_at")
    ok = True
    prev = "0" * 64
    broken_at = None
    for r in rows:
        if r.get("prev_hash") != prev or not verify_signature(r):
            ok, broken_at = False, r.get("id")
            break
        prev = r["hash"]
    return {"mandate_id": mandate_id, "receipts": len(rows), "chain_intact": ok, "broken_at": broken_at}
