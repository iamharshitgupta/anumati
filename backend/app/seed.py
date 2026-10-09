"""Demo seed: a user, a registered agent, an active mandate, a suspect registry
and FRI scores. Idempotent — safe to run on every cold start."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .compiler import compile_mandate
from .scenarios import MULE_VPA
from .store import BaseStore, utcnow_iso

DEMO_USER = "user_demo"
DEMO_AGENT = "kiranabot"
DEMO_MANDATE_ID = "mnd_demo0001"
DEMO_MANDATE_TEXT = ("Buy my weekly groceries from FreshKart or Zepto, up to ₹2,000 per order and ₹3,000 a week. "
                     "Never pay a new payee. Confirm with me for anything above ₹1,500.")


def seed(store: BaseStore) -> dict:
    store.put("agents", DEMO_AGENT, {
        "agent_id": DEMO_AGENT, "name": "KiranaBot", "provider": "Demo Agents Pvt Ltd", "platform": "assistant",
        "attestation": "uap-sandbox-attestation-0001", "status": "active", "registered_at": utcnow_iso(),
    })
    now = datetime.now(timezone.utc)
    if not store.get("mandates", DEMO_MANDATE_ID):
        g, compiler, notes = compile_mandate(DEMO_MANDATE_TEXT)
        # The compiler (heuristic or Gemini) already yields these guardrails from the text
        # above. We reconcile against the sandbox invariants so the demo stays deterministic
        # if a model drifts — but when the compile is correct (it is, for the heuristic path)
        # nothing is overwritten and `compiler`/`compiler_notes` reflect the real compile.
        invariants = {"per_txn_cap": 2000, "period_cap": 3000, "period": "week",
                      "allowed_merchants": ["freshkart", "zepto"], "allow_new_payees": False,
                      "categories": ["groceries"], "step_up_above": 1500}
        for field, want in invariants.items():
            if getattr(g, field) != want:
                notes.append(f"demo-seed reconciliation: {field} set to {want} (compiler gave {getattr(g, field)!r})")
                setattr(g, field, want)
        store.put("mandates", DEMO_MANDATE_ID, {
            "id": DEMO_MANDATE_ID, "user_id": DEMO_USER, "agent_id": DEMO_AGENT, "natural_language": DEMO_MANDATE_TEXT,
            "guardrails": g.model_dump(), "status": "active", "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(), "signed_at": now.isoformat(),
            "signature": "user-confirm:demo", "version": 1, "compiler": compiler, "compiler_notes": notes,
        })
    # verified merchant directory (NPCI verified-merchant analogue)
    for vpa, merchant in [("freshkart@okaxis", "freshkart"), ("zepto@axisbank", "zepto"), ("bigbasket@hdfcbank", "bigbasket"),
                          ("swiggy@icici", "swiggy"), ("zomato@ybl", "zomato")]:
        store.put("merchant_directory", vpa, {"vpa": vpa, "merchant": merchant, "verified": True, "source": "mock-npci-verified-merchant"})
    for vpa, reason in [
        (MULE_VPA, "I4C suspect registry — Layer-1 mule (reported 2026-09-14)"),
        ("quickcash.refund@ybl", "FRI very_high — 37 complaints linked"),
        ("kyc-update-help@paytm", "I4C suspect registry — digital-arrest proceeds"),
    ]:
        store.put("suspect_registry", vpa.lower(), {"vpa": vpa, "reason": reason, "source": "mock-i4c", "listed_at": "2026-09-14T00:00:00+00:00"})
    store.put("fri_scores", "quickcash.refund@ybl", {"vpa": "quickcash.refund@ybl", "risk": "very_high", "source": "mock-dot-fri"})
    store.put("fri_scores", "freshkart.pay247@paytm", {"vpa": "freshkart.pay247@paytm", "risk": "medium", "source": "mock-dot-fri"})
    return {"user_id": DEMO_USER, "agent_id": DEMO_AGENT, "mandate_id": DEMO_MANDATE_ID}
