import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["ANUMATI_STORE"] = "memory"
os.environ["ANUMATI_GEMINI"] = "false"
os.environ["ANUMATI_SEED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.compiler import heuristic_compile  # noqa: E402
from app.main import app  # noqa: E402
from app.receipts import verify_signature  # noqa: E402
from app.seed import DEMO_MANDATE_ID, seed  # noqa: E402
from app.store import MemoryStore, set_store  # noqa: E402


@pytest.fixture()
def client():
    store = MemoryStore()
    set_store(store)
    seed(store)
    return TestClient(app)


def test_heuristic_compiler_extracts_caps_and_merchants():
    g, _ = heuristic_compile("Weekly groceries from BigBasket or Zepto, up to ₹1,500 per order and ₹5k a week. Only these two. Ask me above ₹1,000.")
    assert g.per_txn_cap == 1500 and g.period_cap == 5000 and g.period == "week"
    assert set(g.allowed_merchants) == {"bigbasket", "zepto"}
    assert g.allow_new_payees is False and g.step_up_above == 1000


def test_compile_sign_clamps_to_rail_ceiling(client):
    r = client.post("/v1/mandates/compile", json={"user_id": "u1", "agent_id": "kiranabot", "text": "Pay anyone up to ₹50,000 per transaction for shopping"})
    assert r.status_code == 200
    m = r.json()
    assert m["guardrails"]["per_txn_cap"] <= 5000 and m["status"] == "draft"
    s = client.post(f"/v1/mandates/{m['id']}/sign", json={})
    assert s.json()["status"] == "active" and s.json()["signature"].startswith("user-confirm:")


@pytest.mark.parametrize("scenario,expected", [
    ("clean", "APPROVE"), ("hidden_injection", "BLOCK"), ("unknown_payee", "BLOCK"), ("review_upsell_injection", "STEP_UP"),
    ("price_inflation", "STEP_UP"), ("split_payment", "BLOCK"), ("category_creep", "STEP_UP"), ("over_cap_premium", "BLOCK"),
])
def test_sandbox_scenarios(client, scenario, expected):
    r = client.post("/sim/run", json={"mandate_id": DEMO_MANDATE_ID, "scenario": scenario})
    assert r.status_code == 200, r.text
    assert r.json()["final_verdict"] == expected


def test_receipt_signed_and_chained(client):
    client.post("/sim/run", json={"mandate_id": DEMO_MANDATE_ID, "scenario": "clean"})
    client.post("/sim/run", json={"mandate_id": DEMO_MANDATE_ID, "scenario": "hidden_injection"})
    rows = client.get(f"/v1/receipts?mandate_id={DEMO_MANDATE_ID}").json()
    assert len(rows) >= 2 and all(r["signature_valid"] for r in rows)
    chain = client.get(f"/v1/receipts/chain/{DEMO_MANDATE_ID}").json()
    assert chain["chain_intact"] is True
    tampered = dict(rows[0])
    tampered["risk_score"] = 0
    assert verify_signature(tampered) is False
    assert client.post("/v1/receipts/verify", json=tampered).json()["valid"] is False


def test_receipt_verifies_after_cross_language_number_roundtrip(client):
    """A receipt must still verify after a non-Python verifier (e.g. a browser)
    re-serialises it, collapsing integer-valued floats like 2000.0 -> 2000.
    Guards the 'verifiable offline by any party' guarantee."""
    import json as _json

    client.post("/sim/run", json={"mandate_id": DEMO_MANDATE_ID, "scenario": "clean"})
    receipt = client.get(f"/v1/receipts?mandate_id={DEMO_MANDATE_ID}").json()[0]

    def jsify(o):  # emulate JavaScript's JSON.stringify number handling
        if isinstance(o, bool):
            return o
        if isinstance(o, float) and o.is_integer():
            return int(o)
        if isinstance(o, dict):
            return {k: jsify(v) for k, v in o.items()}
        if isinstance(o, list):
            return [jsify(v) for v in o]
        return o

    roundtripped = _json.loads(_json.dumps(jsify(receipt)))
    assert verify_signature(roundtripped) is True
    assert client.post("/v1/receipts/verify", json=roundtripped).json()["valid"] is True


def test_stepup_flow_and_dispute(client):
    r = client.post("/sim/run", json={"mandate_id": DEMO_MANDATE_ID, "scenario": "price_inflation"}).json()
    su = r["stepup_id"]
    assert su
    assert client.post(f"/v1/stepups/{su}/respond", json={"approve": False, "note": "no"}).json()["status"] == "declined"
    assert client.post(f"/v1/stepups/{su}/respond", json={"approve": True}).status_code == 409
    dec = client.get(f"/v1/decisions/{r['decisions'][-1]['id']}").json()
    assert dec["status"] == "declined"
    d = client.post("/v1/disputes", json={"decision_id": dec["id"], "raised_by": "merchant", "claim": "valid checkout abandoned"}).json()
    assert d["receipt_signature_valid"] is True and d["attribution"]["primary_party"]
    rc = client.get(f"/v1/receipts/{dec['receipt_id']}").json()
    assert rc["signature_valid"] is True and rc["human_confirmation"]["outcome"] == "declined"


def test_unregistered_agent_is_hard_blocked(client):
    body = {"agent_id": "rogue", "mandate_id": DEMO_MANDATE_ID, "user_id": "user_demo", "payee_vpa": "freshkart@okaxis",
            "payee_name": "FreshKart", "merchant": "FreshKart", "amount": 100}
    r = client.post("/v1/payments/authorize", json=body).json()
    assert r["verdict"] == "BLOCK" and any(f["code"] == "AGENT_UNREGISTERED" for f in r["findings"])


def test_idempotency(client):
    body = {"agent_id": "kiranabot", "mandate_id": DEMO_MANDATE_ID, "user_id": "user_demo", "payee_vpa": "freshkart@okaxis",
            "payee_name": "FreshKart", "merchant": "FreshKart", "amount": 400, "idempotency_key": "k1"}
    a = client.post("/v1/payments/authorize", json=body).json()
    b = client.post("/v1/payments/authorize", json=body).json()
    assert a["id"] == b["id"]
