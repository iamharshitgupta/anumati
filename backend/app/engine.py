"""Decision engine: deterministic policy + semantic audit → verdict + receipt.

Fusion rules (kept simple and explainable on purpose):
  * any hard-fail policy finding            → BLOCK
  * risk = min(100, Σ policy weights) blended with semantic scores:
        risk = max(policy_sum, injection, drift, 0.6*policy_sum + 0.4*max(injection, drift))
  * risk ≥ block_threshold                   → BLOCK
  * risk ≥ step_up_threshold or STEP_UP_RULE → STEP_UP (human one-tap confirm)
  * otherwise                                 → APPROVE
"""

from __future__ import annotations

import time
import uuid

from .config import settings
from .models import Decision, Finding, PaymentRequest
from .policy import run_policy
from .receipts import issue_receipt
from .semantic import SemanticResult, analyse
from .store import BaseStore, utcnow_iso


def _semantic_findings(s: SemanticResult) -> list[Finding]:
    out: list[Finding] = []
    if s.injection_score >= 20:
        sev = "critical" if s.injection_score >= 70 else "high" if s.injection_score >= 45 else "medium"
        out.append(Finding(code="INJECTION", severity=sev, weight=s.injection_score, source="semantic",
                           message="Merchant content contains instructions aimed at the agent: " + "; ".join(s.injection_reasons[:3]),
                           evidence={"score": s.injection_score, "instructions": s.injected_instructions}))
    if s.drift_score >= 20:
        sev = "critical" if s.drift_score >= 70 else "high" if s.drift_score >= 45 else "medium"
        out.append(Finding(code="DRIFT", severity=sev, weight=s.drift_score, source="semantic",
                           message="Payment drifts from mandate intent: " + "; ".join(s.drift_reasons[:3]),
                           evidence={"score": s.drift_score, "reasons": s.drift_reasons}))
    return out


def fuse(policy_sum: int, injection: int, drift: int) -> int:
    sem = max(injection, drift)
    return int(min(100, max(policy_sum, sem, 0.6 * policy_sum + 0.4 * sem)))


def decide(req: PaymentRequest, store: BaseStore, *, run_semantic: bool = True) -> Decision:
    t0 = time.perf_counter()
    mandate = store.get("mandates", req.mandate_id)
    if not mandate:
        mandate = {"id": req.mandate_id, "status": "missing", "user_id": req.user_id, "agent_id": req.agent_id,
                   "guardrails": {"per_txn_cap": 1, "period_cap": 1}, "natural_language": "(no such mandate)",
                   "expires_at": "1970-01-01T00:00:00+00:00"}

    policy_findings, hard_fail = run_policy(req, mandate, store) if mandate.get("status") != "missing" else (
        [Finding(code="MANDATE_INACTIVE", severity="critical", weight=100, source="policy", message="Mandate not found")], True)
    policy_sum = min(100, sum(f.weight for f in policy_findings))

    # Semantic audit runs even on hard policy failures: the receipt is the dispute
    # evidence, and *why* the agent was steered (injection vs. drift) decides who is liable.
    if run_semantic and mandate.get("status") != "missing":
        sem = analyse(req, mandate)
    else:
        sem = SemanticResult(engine="skipped", summary="Semantic audit skipped")
    findings = policy_findings + _semantic_findings(sem)
    risk = 100 if hard_fail else fuse(policy_sum, sem.injection_score, sem.drift_score)

    if hard_fail or risk >= settings.block_threshold:
        verdict = "BLOCK"
    elif risk >= settings.step_up_threshold or any(f.code == "STEP_UP_RULE" for f in findings):
        verdict = "STEP_UP"
    else:
        verdict = "APPROVE"

    decision_id = f"dec_{uuid.uuid4().hex[:12]}"
    findings_d = [f.model_dump() for f in findings]
    receipt = issue_receipt(
        store, decision_id=decision_id, request=req.model_dump(), mandate=mandate, verdict=verdict,
        risk_score=risk, findings=findings_d,
        semantic={"engine": sem.engine, "injection_score": sem.injection_score, "drift_score": sem.drift_score,
                  "injection_reasons": sem.injection_reasons, "drift_reasons": sem.drift_reasons,
                  "injected_instructions": sem.injected_instructions, "summary": sem.summary},
    )

    stepup_id = None
    status = "final"
    if verdict == "STEP_UP":
        stepup_id = f"su_{uuid.uuid4().hex[:10]}"
        status = "pending_stepup"
        store.put("stepups", stepup_id, {
            "decision_id": decision_id, "user_id": req.user_id, "mandate_id": req.mandate_id, "agent_id": req.agent_id,
            "amount": req.amount, "payee_vpa": req.payee_vpa, "payee_name": req.payee_name, "merchant": req.merchant,
            "risk_score": risk, "reasons": [f.message for f in sorted(findings, key=lambda f: -f.weight)[:3]],
            "status": "pending", "created_at": utcnow_iso(), "expires_in_s": settings.step_up_ttl_s,
            "simulated": req.simulated,
        })

    dec = Decision(
        id=decision_id, request=req, verdict=verdict, risk_score=risk, findings=findings,
        policy_passed=not policy_findings, semantic_engine=sem.engine,
        drift_score=sem.drift_score if sem.engine != "skipped" else None,
        injection_score=sem.injection_score if sem.engine != "skipped" else None,
        receipt_id=receipt["id"], stepup_id=stepup_id, status=status, created_at=utcnow_iso(),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    store.put("decisions", decision_id, dec.model_dump())
    return dec


def baseline_caps_only(req: PaymentRequest, store: BaseStore) -> str:
    """What a naive 'UPI Circle caps only' control would do. Used by the eval suite."""
    mandate = store.get("mandates", req.mandate_id)
    if not mandate or mandate.get("status") != "active":
        return "BLOCK"
    g = mandate["guardrails"]
    if req.amount > g["per_txn_cap"] or req.amount > settings.hard_cap_per_txn:
        return "BLOCK"
    return "APPROVE"
