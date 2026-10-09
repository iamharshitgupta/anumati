"""Decision Receipts — the liability artifact.

Every verdict (approve, step-up, block) produces a receipt that:
  * contains what the mandate said, what the agent attempted, every finding and
    the evidence behind it, and the verdict;
  * is canonicalised (sorted keys, no whitespace) and hashed with SHA-256;
  * is chained to the previous receipt for the same mandate (``prev_hash``), so
    deleting or reordering history is detectable;
  * is signed with HMAC-SHA256 under a key id. Swap ``_sign`` for Cloud KMS
    asymmetric signing in production — the receipt format does not change.

Anyone holding the receipt and the key (or public key) can re-verify it without
talking to Anumati. That is the point: disputes are settled on evidence, not on
trust in the gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from .config import settings
from .store import BaseStore, utcnow_iso

# AP2-style liability matrix: finding code → party presumptively accountable
LIABILITY_HINTS = {
    "INJECTION": "merchant_or_content_provider",
    "DRIFT": "agent_provider",
    "PAYEE_NOT_ALLOWED": "agent_provider",
    "PAYEE_HANDLE_MISMATCH": "merchant_or_content_provider",
    "PAYEE_SUSPECT_REGISTRY": "issuer_blocked",
    "PER_TXN_CAP": "agent_provider",
    "PERIOD_CAP": "agent_provider",
    "STRUCTURING": "agent_provider",
    "CART_AMOUNT_MISMATCH": "merchant",
    "QUANTITY_ANOMALY": "agent_provider",
    "MANDATE_EXPIRED": "user",
    "MANDATE_INACTIVE": "user",
    "STEP_UP_RULE": "user_confirmation_required",
}


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign(payload_hash: str) -> str:
    return hmac.new(settings.receipt_signing_key.encode(), payload_hash.encode(), hashlib.sha256).hexdigest()


def verify_signature(receipt: dict) -> bool:
    # fields appended after issuance (human step-up outcome, UI flags) are outside the signed body
    unsigned = {"hash", "signature", "key_id", "id", "human_confirmation", "signature_valid"}
    body = {k: v for k, v in receipt.items() if k not in unsigned}
    h = hashlib.sha256(canonical(body)).hexdigest()
    return h == receipt.get("hash") and hmac.compare_digest(_sign(h), receipt.get("signature", ""))


def issue_receipt(store: BaseStore, *, decision_id: str, request: dict, mandate: dict, verdict: str,
                  risk_score: int, findings: list[dict], semantic: dict) -> dict:
    prev = store.query("receipts", [("mandate_id", "==", mandate["id"])], order_by="issued_at", descending=True, limit=1)
    prev_hash = prev[0]["hash"] if prev else "0" * 64
    body = {
        "receipt_version": "1.0",
        "decision_id": decision_id,
        "issued_at": utcnow_iso(),
        "mandate_id": mandate["id"],
        "mandate_version": mandate.get("version", 1),
        "mandate_text": mandate.get("natural_language"),
        "mandate_guardrails": mandate.get("guardrails"),
        "agent_id": request["agent_id"],
        "user_id": request["user_id"],
        "attempted": {
            "payee_vpa": request["payee_vpa"],
            "payee_name": request["payee_name"],
            "merchant": request.get("merchant"),
            "amount": request["amount"],
            "currency": request.get("currency", "INR"),
            "category": request.get("category"),
            "cart": request.get("cart", []),
        },
        "verdict": verdict,
        "risk_score": risk_score,
        "findings": findings,
        "semantic_audit": semantic,
        "liability_hints": sorted({LIABILITY_HINTS[f["code"]] for f in findings if f["code"] in LIABILITY_HINTS}),
        "plain_language": _plain_language(verdict, risk_score, findings, mandate, request),
        "prev_hash": prev_hash,
        "simulated": bool(request.get("simulated")),
    }
    h = hashlib.sha256(canonical(body)).hexdigest()
    receipt = dict(body)
    receipt["hash"] = h
    receipt["signature"] = _sign(h)
    receipt["key_id"] = settings.receipt_key_id
    rid = f"rcpt_{uuid.uuid4().hex[:12]}"
    store.put("receipts", rid, receipt)
    receipt["id"] = rid
    return receipt


def _plain_language(verdict: str, score: int, findings: list[dict], mandate: dict, request: dict) -> str:
    att = f"₹{request['amount']:,.0f} to {request['payee_name']} ({request['payee_vpa']})"
    head = {
        "APPROVE": f"Approved {att}. The payment is consistent with the mandate \"{mandate.get('natural_language')}\".",
        "STEP_UP": f"Held {att} for the account holder's confirmation (risk {score}/100).",
        "BLOCK": f"Blocked {att} (risk {score}/100).",
    }[verdict]
    if not findings:
        return head + " No policy or semantic findings."
    top = sorted(findings, key=lambda f: -f["weight"])[:3]
    return head + " Key findings: " + "; ".join(f["message"] for f in top) + "."
