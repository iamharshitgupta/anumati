"""Pydantic schemas.

Mandate shape mirrors Google's AP2 *Intent Mandate* (natural-language
description, allowed merchants, expiry, refundability) and adds Anumati
guardrails that UPI Circle / Reserve Pay–style delegation needs: per-txn and
period caps, payee policy, category scope and step-up rules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Mandates
# ---------------------------------------------------------------------------
class Guardrails(BaseModel):
    per_txn_cap: float = Field(..., gt=0, description="INR ceiling per transaction")
    period_cap: float = Field(..., gt=0, description="INR ceiling per period")
    period: Literal["day", "week", "month"] = "month"
    allowed_merchants: list[str] = Field(default_factory=list, description="merchant names/domains the agent may pay")
    allowed_payee_vpas: list[str] = Field(default_factory=list, description="explicit VPAs; empty = derive from merchants")
    allow_new_payees: bool = False
    categories: list[str] = Field(default_factory=list, description="e.g. groceries, transport, subscriptions")
    blocked_categories: list[str] = Field(default_factory=list)
    requires_refundability: bool = False
    max_txns_per_day: int = 10
    step_up_above: float | None = Field(None, description="force human confirm above this INR amount")


class MandateCompileRequest(BaseModel):
    user_id: str | None = None  # compatibility only; the backend always stamps the caller's UID
    agent_id: str
    text: str = Field(..., description="natural-language mandate from the user")
    ttl_days: int = Field(30, ge=1, le=365)
    sandbox: bool = False  # named callers can explicitly request a synthetic mandate


class Mandate(BaseModel):
    id: str
    user_id: str
    agent_id: str
    natural_language: str
    guardrails: Guardrails
    status: Literal["draft", "active", "revoked", "expired"] = "draft"
    created_at: str
    expires_at: str
    signed_at: str | None = None
    signature: str | None = None  # user's confirmation signature over canonical mandate
    version: int = 1
    compiler: Literal["gemini", "heuristic"] = "heuristic"
    compiler_notes: list[str] = Field(default_factory=list)
    demo_fixture: bool = False  # server-assigned for synthetic session/guest mandates


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
class AgentRegistration(BaseModel):
    agent_id: str
    name: str
    provider: str
    platform: Literal["merchant_app", "payment_app", "assistant", "agent_platform"] = "assistant"
    public_key: str | None = None
    attestation: str | None = None  # placeholder for UAP/AP2 agent credential


# ---------------------------------------------------------------------------
# Payment requests & decisions
# ---------------------------------------------------------------------------
class CartItem(BaseModel):
    sku: str
    name: str
    qty: int = 1
    unit_price: float
    category: str | None = None


class TraceStep(BaseModel):
    step: int
    kind: Literal["observe", "think", "act"]
    content: str


class PaymentRequest(BaseModel):
    agent_id: str
    mandate_id: str
    user_id: str
    payee_vpa: str
    payee_name: str
    merchant: str | None = None
    amount: float = Field(..., gt=0)
    currency: Literal["INR"] = "INR"
    category: str | None = None
    cart: list[CartItem] = Field(default_factory=list)
    agent_trace: list[TraceStep] = Field(default_factory=list)
    consumed_content: str | None = Field(None, description="merchant page/content the agent read before deciding")
    idempotency_key: str | None = None
    simulated: bool = False
    scenario: str | None = None  # sandbox tag


class Finding(BaseModel):
    code: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    weight: int
    message: str
    evidence: dict = Field(default_factory=dict)
    source: Literal["policy", "semantic"]


class Decision(BaseModel):
    id: str
    request: PaymentRequest
    verdict: Literal["APPROVE", "STEP_UP", "BLOCK"]
    risk_score: int
    findings: list[Finding]
    policy_passed: bool
    semantic_engine: Literal["gemini", "heuristic", "skipped"]
    drift_score: int | None = None
    injection_score: int | None = None
    receipt_id: str
    stepup_id: str | None = None
    status: Literal["final", "pending_stepup", "settled", "declined"]
    created_at: str
    latency_ms: int


class StepUpResponse(BaseModel):
    approve: bool
    note: str | None = None


class DisputeCreate(BaseModel):
    decision_id: str
    raised_by: Literal["user", "merchant", "issuer", "agent_provider"] = "user"
    claim: str
