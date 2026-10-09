"""Deterministic policy checks. No model in the loop — these are the controls an
auditor can re-run by hand against the receipt.

Each check yields zero or more ``Finding`` objects with a weight. Weights feed the
risk fusion in ``engine.py``. A few findings are *hard fails*: they force BLOCK
regardless of score (expired mandate, unregistered agent, payee on suspect
registry, amount over rail ceiling).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import settings
from .models import Finding, Guardrails, PaymentRequest
from .store import BaseStore

HARD_FAIL_CODES = {
    "MANDATE_INACTIVE",
    "MANDATE_EXPIRED",
    "AGENT_UNREGISTERED",
    "AGENT_MANDATE_MISMATCH",
    "PAYEE_SUSPECT_REGISTRY",
    "RAIL_CEILING_EXCEEDED",
}


def _period_start(period: str, now: datetime) -> datetime:
    if period == "day":
        return now - timedelta(days=1)
    if period == "week":
        return now - timedelta(days=7)
    return now - timedelta(days=30)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _merchant_matches(merchant: str | None, payee_vpa: str, allowed: list[str]) -> bool:
    m = _norm(merchant)
    vpa = _norm(payee_vpa)
    for a in allowed:
        a = _norm(a)
        if not a:
            continue
        if m and (a in m or m in a):
            return True
        if a in vpa.split("@")[0]:
            return True
    return False


def _directory_for(store: BaseStore, merchants: list[str]) -> list[str]:
    out = []
    for m in merchants:
        for row in store.query("merchant_directory", [("merchant", "==", _norm(m))]):
            out.append(row["vpa"])
    return out


def run_policy(req: PaymentRequest, mandate: dict, store: BaseStore) -> tuple[list[Finding], bool]:
    """Return (findings, hard_fail)."""
    findings: list[Finding] = []
    now = datetime.now(timezone.utc)
    g = Guardrails(**mandate["guardrails"])

    # 1. mandate state ------------------------------------------------------
    if mandate.get("status") != "active":
        findings.append(Finding(code="MANDATE_INACTIVE", severity="critical", weight=100, source="policy",
                                message=f"Mandate is {mandate.get('status')}, not active"))
    try:
        exp = datetime.fromisoformat(mandate["expires_at"])
        if exp < now:
            findings.append(Finding(code="MANDATE_EXPIRED", severity="critical", weight=100, source="policy",
                                    message=f"Mandate expired at {mandate['expires_at']}"))
    except Exception:
        pass
    if mandate.get("user_id") != req.user_id:
        findings.append(Finding(code="AGENT_MANDATE_MISMATCH", severity="critical", weight=100, source="policy",
                                message="Request user does not match mandate holder"))

    # 2. agent registry -----------------------------------------------------
    agent = store.get("agents", req.agent_id)
    if not agent:
        findings.append(Finding(code="AGENT_UNREGISTERED", severity="critical", weight=100, source="policy",
                                message=f"Agent {req.agent_id} is not registered"))
    elif mandate.get("agent_id") != req.agent_id:
        findings.append(Finding(code="AGENT_MANDATE_MISMATCH", severity="critical", weight=100, source="policy",
                                message=f"Mandate is bound to {mandate.get('agent_id')}, request came from {req.agent_id}"))

    # 3. amount caps --------------------------------------------------------
    if req.amount > settings.hard_cap_per_txn:
        findings.append(Finding(code="RAIL_CEILING_EXCEEDED", severity="critical", weight=100, source="policy",
                                message=f"₹{req.amount:,.0f} exceeds delegation ceiling ₹{settings.hard_cap_per_txn:,.0f}",
                                evidence={"amount": req.amount, "ceiling": settings.hard_cap_per_txn}))
    if req.amount > g.per_txn_cap:
        findings.append(Finding(code="PER_TXN_CAP", severity="high", weight=45, source="policy",
                                message=f"₹{req.amount:,.0f} exceeds mandate per-transaction cap ₹{g.per_txn_cap:,.0f}",
                                evidence={"amount": req.amount, "cap": g.per_txn_cap}))
    if g.step_up_above is not None and req.amount > g.step_up_above:
        findings.append(Finding(code="STEP_UP_RULE", severity="medium", weight=40, source="policy",
                                message=f"Mandate requires human confirmation above ₹{g.step_up_above:,.0f}",
                                evidence={"amount": req.amount, "step_up_above": g.step_up_above}))

    # 4. velocity / period cap ---------------------------------------------
    since = _period_start(g.period, now).isoformat()
    prior = store.query("decisions", [("request.mandate_id", "==", req.mandate_id)])
    settled = [d for d in prior if d.get("status") in {"final", "settled"} and d.get("verdict") == "APPROVE"
               and d.get("created_at", "") >= since and not d.get("request", {}).get("simulated_discard")]
    spent = sum(d["request"]["amount"] for d in settled)
    if spent + req.amount > g.period_cap:
        findings.append(Finding(code="PERIOD_CAP", severity="high", weight=45, source="policy",
                                message=f"₹{spent:,.0f} already spent this {g.period}; this payment would exceed ₹{g.period_cap:,.0f}",
                                evidence={"spent": spent, "amount": req.amount, "cap": g.period_cap}))
    day_ago = (now - timedelta(days=1)).isoformat()
    today = [d for d in prior if d.get("created_at", "") >= day_ago and d.get("verdict") in {"APPROVE", "STEP_UP"}]
    if len(today) + 1 > g.max_txns_per_day:
        findings.append(Finding(code="TXN_RATE", severity="medium", weight=30, source="policy",
                                message=f"{len(today)} agent payments in the last 24h; mandate allows {g.max_txns_per_day}",
                                evidence={"count_24h": len(today), "max": g.max_txns_per_day}))

    # 5. structuring: several payments just under cap to the same payee ------
    recent_same_payee = [d for d in prior if d.get("created_at", "") >= (now - timedelta(hours=2)).isoformat()
                         and _norm(d["request"].get("payee_vpa")) == _norm(req.payee_vpa)]
    near_cap = [d for d in recent_same_payee if d["request"]["amount"] >= 0.8 * g.per_txn_cap]
    if req.amount >= 0.8 * g.per_txn_cap and len(near_cap) >= 1:
        findings.append(Finding(code="STRUCTURING", severity="high", weight=50, source="policy",
                                message=f"{len(near_cap) + 1} payments ≥80% of cap to the same payee within 2h — pattern consistent with cap splitting",
                                evidence={"prior_near_cap": len(near_cap), "cap": g.per_txn_cap}))

    # 6. payee policy -------------------------------------------------------
    # The agent-declared `merchant` field is untrusted. A payee is allowed when the
    # VPA is explicitly allowlisted OR resolves, via the verified merchant directory
    # (NPCI-verified-merchant analogue), to a merchant the mandate names.
    vpa = _norm(req.payee_vpa)
    known_vpa = vpa in {_norm(v) for v in g.allowed_payee_vpas}
    directory = store.get("merchant_directory", vpa)  # {vpa, merchant, verified}
    directory_merchant = _norm(directory.get("merchant")) if directory else None
    resolved_ok = directory_merchant is not None and any(_norm(a) == directory_merchant or _norm(a) in directory_merchant
                                                         for a in g.allowed_merchants)
    name_claims_allowed = _merchant_matches(req.merchant, req.payee_vpa, g.allowed_merchants)
    if g.allowed_merchants or g.allowed_payee_vpas:
        if not (known_vpa or resolved_ok):
            if name_claims_allowed:
                # merchant name is on the allowlist but this VPA is not that merchant's verified VPA
                code, w = ("NEW_PAYEE", 35) if g.allow_new_payees else ("PAYEE_NOT_ALLOWED", 70)
                findings.append(Finding(code=code, severity="high", weight=w, source="policy",
                                        message=f"'{req.merchant}' is a mandated merchant, but {req.payee_vpa} is not its verified VPA"
                                                + ("" if g.allow_new_payees else " and the mandate forbids new payees"),
                                        evidence={"payee_vpa": req.payee_vpa, "verified_vpas": _directory_for(store, g.allowed_merchants)}))
                findings.append(Finding(code="PAYEE_HANDLE_MISMATCH", severity="high", weight=20, source="policy",
                                        message="Payee substitution pattern: trusted merchant name, unverified VPA",
                                        evidence={"merchant": req.merchant, "payee_vpa": req.payee_vpa}))
            elif g.allow_new_payees:
                findings.append(Finding(code="NEW_PAYEE", severity="medium", weight=35, source="policy",
                                        message=f"Payee {req.payee_vpa} ({req.payee_name}) is not in the mandate allowlist",
                                        evidence={"payee_vpa": req.payee_vpa, "allowed": g.allowed_merchants}))
            else:
                findings.append(Finding(code="PAYEE_NOT_ALLOWED", severity="high", weight=70, source="policy",
                                        message=f"Mandate forbids new payees; {req.payee_vpa} ({req.payee_name}) is not allowed",
                                        evidence={"payee_vpa": req.payee_vpa, "allowed": g.allowed_merchants}))

    # 7. suspect registry (mock of I4C Suspect Registry / FRI) ---------------
    hit = store.get("suspect_registry", _norm(req.payee_vpa))
    if hit:
        findings.append(Finding(code="PAYEE_SUSPECT_REGISTRY", severity="critical", weight=100, source="policy",
                                message=f"Payee {req.payee_vpa} is listed in the suspect registry ({hit.get('reason')})",
                                evidence={"registry_entry": hit}))
    fri = store.get("fri_scores", _norm(req.payee_vpa))
    if fri and fri.get("risk") in {"high", "very_high"}:
        findings.append(Finding(code="PAYEE_FRI_HIGH", severity="high", weight=50, source="policy",
                                message=f"Financial Fraud Risk Indicator for payee is {fri['risk']}",
                                evidence={"fri": fri}))

    # 8. category scope -----------------------------------------------------
    cat = _norm(req.category)
    if cat and g.blocked_categories and cat in {_norm(c) for c in g.blocked_categories}:
        findings.append(Finding(code="CATEGORY_BLOCKED", severity="high", weight=60, source="policy",
                                message=f"Category '{cat}' is blocked by the mandate"))
    elif cat and g.categories and cat not in {_norm(c) for c in g.categories}:
        findings.append(Finding(code="CATEGORY_OUT_OF_SCOPE", severity="medium", weight=35, source="policy",
                                message=f"Category '{cat}' is outside mandate scope {g.categories}"))

    # 9. cart integrity -----------------------------------------------------
    if req.cart:
        total = round(sum(i.qty * i.unit_price for i in req.cart), 2)
        if abs(total - req.amount) > max(1.0, 0.02 * total):
            findings.append(Finding(code="CART_AMOUNT_MISMATCH", severity="high", weight=50, source="policy",
                                    message=f"Cart totals ₹{total:,.2f} but payment requests ₹{req.amount:,.2f}",
                                    evidence={"cart_total": total, "amount": req.amount}))
        if g.categories:
            allowed = {_norm(c) for c in g.categories}
            off = [i for i in req.cart if i.category and _norm(i.category) not in allowed]
            if off:
                findings.append(Finding(code="CART_CATEGORY_OUT_OF_SCOPE", severity="medium", weight=40, source="policy",
                                        message="Cart contains items outside mandate scope: " + ", ".join(f"{i.name} ({i.category})" for i in off),
                                        evidence={"items": [i.model_dump() for i in off], "allowed": g.categories}))
        big_qty = [i for i in req.cart if i.qty >= 10]
        if big_qty:
            findings.append(Finding(code="QUANTITY_ANOMALY", severity="medium", weight=30, source="policy",
                                    message=f"Unusual quantity in cart: {', '.join(f'{i.qty}× {i.name}' for i in big_qty)}",
                                    evidence={"items": [i.model_dump() for i in big_qty]}))

    hard_fail = any(f.code in HARD_FAIL_CODES for f in findings)
    return findings, hard_fail
