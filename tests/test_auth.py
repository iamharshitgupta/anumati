import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ["ANUMATI_STORE"] = "memory"
os.environ["ANUMATI_GEMINI"] = "false"
os.environ["ANUMATI_SEED"] = "false"
os.environ["ANUMATI_AUTH_MODE"] = "demo"

from fastapi.testclient import TestClient  # noqa: E402
from app import auth, main  # noqa: E402
from app.routers import disputes, sim  # noqa: E402
from app.models import PaymentRequest  # noqa: E402
from app.policy import run_policy  # noqa: E402
from app.seed import DEMO_MANDATE_ID, DEMO_MANDATE_TEXT, seed  # noqa: E402
from app.store import FirestoreStore, MemoryStore, set_store, utcnow_iso  # noqa: E402
from infra import firebase_roles  # noqa: E402

REAL_VERIFY = auth._verify_firebase_token


def headers(user="alice"):
    return {"Authorization": f"Bearer {user}"}


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    settings = replace(auth.settings, auth_mode="firebase", environment="local", gcp_project="demo-anumati")
    monkeypatch.setattr(auth, "settings", settings)
    monkeypatch.setattr(main, "settings", settings)
    claims = {
        name: {"uid": name, "role": role, "firebase": {"sign_in_provider": "google.com"}}
        for name, role in [("alice", "user"), ("bob", "user"), ("analyst", "analyst"), ("admin", "admin")]
    }
    claims["guest"] = {"uid": "guest", "role": "admin", "firebase": {"sign_in_provider": "anonymous"}}

    def verify(token):
        if token not in claims:
            raise ValueError("invalid test token")
        return claims[token]

    monkeypatch.setattr(auth, "_verify_firebase_token", Mock(side_effect=verify))
    store = MemoryStore()
    set_store(store)
    seed(store)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, store=store, claims=claims)


def session(api, user="alice"):
    response = api.client.post("/sim/session", headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()["mandate_id"]


def run(api, mandate, scenario="clean", user="alice", fresh=False):
    response = api.client.post("/sim/run", headers=headers(user), json={
        "mandate_id": mandate, "scenario": scenario, "fresh": fresh,
    })
    assert response.status_code == 200, response.text
    return response.json()


def ordinary_mandate(api, user="alice"):
    response = api.client.post("/v1/mandates/compile", headers=headers(user), json={
        "agent_id": "kiranabot", "text": "Weekly groceries from FreshKart up to 1000 per order",
    })
    assert response.status_code == 200 and response.json()["demo_fixture"] is False
    mid = response.json()["id"]
    assert api.client.post(f"/v1/mandates/{mid}/sign", headers=headers(user), json={}).status_code == 200
    return mid


@pytest.mark.parametrize("method,path,body", [
    ("get", "/v1/mandates", None), ("get", "/v1/mandates/missing", None),
    ("post", "/v1/mandates/compile", {"agent_id": "kiranabot", "text": "groceries"}),
    ("post", "/v1/mandates/missing/sign", {}), ("post", "/v1/mandates/missing/revoke", {}),
    ("get", "/v1/agents", None), ("get", "/v1/agents/kiranabot", None),
    ("post", "/v1/agents", {"agent_id": "x", "name": "x", "provider": "x"}),
    ("post", "/v1/payments/authorize", {"user_id": "alice", "mandate_id": "x", "agent_id": "x", "payee_vpa": "x@y", "payee_name": "x", "amount": 1}),
    ("get", "/v1/decisions", None), ("get", "/v1/decisions/missing", None),
    ("get", "/v1/receipts", None), ("get", "/v1/receipts/missing", None),
    ("get", "/v1/receipts/chain/missing", None), ("post", "/v1/receipts/verify", {}),
    ("get", "/v1/stepups", None), ("post", "/v1/stepups/missing/respond", {"approve": True}),
    ("get", "/v1/disputes", None), ("get", "/v1/disputes/missing", None),
    ("post", "/v1/disputes", {"decision_id": "x", "claim": "x"}),
    ("post", "/v1/disputes/missing/resolve", {}), ("post", "/admin/seed", {}),
    ("post", "/sim/session", {}), ("post", "/sim/run", {"mandate_id": "x"}),
    ("post", "/sim/compare", {"mandate_id": "x"}), ("post", "/sim/disputes/missing/resolve", {}),
])
def test_protected_routes_require_a_token(api, method, path, body):
    assert api.client.request(method, path, json=body).status_code == 401


def test_public_catalog_and_health_stay_public(api):
    for path in ("/", "/healthz", "/docs", "/openapi.json", "/sim/scenarios", "/sim/merchant/clean/raw"):
        assert api.client.get(path).status_code == 200
    assert api.client.get("/healthz").json()["firebase_project_id"] == "demo-anumati"


@pytest.mark.parametrize("token", ["invalid", "expired", "revoked", "wrong-project"])
def test_verification_failure_never_falls_back(api, token):
    before = api.store.query("mandates")
    response = api.client.post("/sim/session", headers=headers(token))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert api.store.query("mandates") == before


def test_compile_stamps_uid_and_session_does_not_reactivate(api):
    response = api.client.post("/v1/mandates/compile", headers=headers(), json={
        "user_id": "bob", "agent_id": "kiranabot", "text": "Weekly groceries up to 1000 per order",
    })
    assert response.json()["user_id"] == "alice"
    mid = response.json()["id"]
    assert api.client.post(f"/v1/mandates/{mid}/sign", headers=headers(), json={}).json()["status"] == "active"
    assert api.client.post(f"/v1/mandates/{mid}/revoke", headers=headers()).json()["status"] == "revoked"
    demo_id = session(api)
    original = api.store.get("mandates", demo_id)
    assert original["user_id"] == "alice" and original["demo_fixture"]
    api.client.post(f"/v1/mandates/{demo_id}/revoke", headers=headers())
    assert session(api) == demo_id
    assert api.store.get("mandates", demo_id)["status"] == "revoked"
    assert api.store.get("mandates", demo_id)["created_at"] == original["created_at"]
    assert session(api, "bob") != demo_id


def test_cross_user_reads_writes_and_lists(api):
    mid = session(api)
    result = run(api, mid, "price_inflation")
    decision = result["decisions"][-1]
    for path in (f"/v1/mandates/{mid}", f"/v1/decisions/{decision['id']}",
                 f"/v1/receipts/{result['receipt_id']}", f"/v1/receipts/chain/{mid}"):
        assert api.client.get(path, headers=headers("bob")).status_code == 403
        assert api.client.get(path, headers=headers("analyst")).status_code == 200
    for path, body in [(f"/v1/mandates/{mid}/sign", {}), (f"/v1/mandates/{mid}/revoke", {}),
                       (f"/v1/stepups/{result['stepup_id']}/respond", {"approve": True})]:
        for user in ("bob", "analyst"):
            assert api.client.post(path, headers=headers(user), json=body).status_code == 403
    for path in ("/v1/mandates", "/v1/decisions", "/v1/receipts", "/v1/stepups", "/v1/disputes"):
        assert api.client.get(path, headers=headers("bob")).json() == []
    for path in ("/v1/mandates", "/v1/decisions", "/v1/stepups"):
        assert api.client.get(path + "?user_id=alice", headers=headers("bob")).status_code == 403
    assert api.client.post(f"/v1/stepups/{result['stepup_id']}/respond", headers=headers(), json={"approve": False}).status_code == 200
    assert api.store.get("stepups", result["stepup_id"])["responded_by"] == "alice"
    assert api.store.get("receipts", result["receipt_id"])["human_confirmation"]["by"] == "alice"


def test_sim_checks_ownership_before_cleanup_or_model_calls(api, monkeypatch):
    mid = session(api)
    result = run(api, mid)
    model = Mock(side_effect=AssertionError("Forbidden request reached Gemini"))
    monkeypatch.setattr(sim, "_gemini_agent", model)
    monkeypatch.setattr(sim, "gemini_analyse", model)
    for path in ("/sim/run", "/sim/compare"):
        assert api.client.post(path, headers=headers("bob"), json={
            "mandate_id": mid, "mode": "gemini", "fresh": True,
        }).status_code == 403
    assert api.store.get("decisions", result["decisions"][-1]["id"])
    model.assert_not_called()
    assert api.client.post("/sim/run", headers=headers(), json={}).status_code == 422


def test_scoped_payment_idempotency_and_owner_guard(api):
    mid = ordinary_mandate(api)
    body = {"agent_id": "kiranabot", "mandate_id": mid, "user_id": "alice", "payee_vpa": "freshkart@okaxis",
            "payee_name": "FreshKart", "merchant": "FreshKart", "amount": 100, "idempotency_key": "same"}
    first = api.client.post("/v1/payments/authorize", headers=headers(), json=body)
    assert first.status_code == 200
    assert api.client.post("/v1/payments/authorize", headers=headers(), json=body).json()["id"] == first.json()["id"]
    assert api.client.post("/v1/payments/authorize", headers=headers("bob"), json=body).status_code == 403
    body.update(user_id="bob")
    assert api.client.post("/v1/payments/authorize", headers=headers("bob"), json=body).status_code == 403
    body["mandate_id"] = ordinary_mandate(api, "bob")
    second = api.client.post("/v1/payments/authorize", headers=headers("bob"), json=body)
    assert second.status_code == 200 and second.json()["id"] != first.json()["id"]


def test_guest_is_sandbox_only_even_with_staff_claim(api):
    mid = session(api, "guest")
    body = {"user_id": "guest", "agent_id": "kiranabot", "mandate_id": mid,
            "payee_vpa": "freshkart@okaxis", "payee_name": "FreshKart", "amount": 100}
    assert api.client.post("/v1/payments/authorize", headers=headers("guest"), json=body).status_code == 403
    body["simulated"] = True
    assert api.client.post("/v1/payments/authorize", headers=headers("guest"), json=body).status_code == 200
    assert api.client.post("/admin/seed", headers=headers("guest")).status_code == 403
    response = api.client.post("/v1/mandates/compile", headers=headers("guest"), json={"agent_id": "kiranabot", "text": "groceries"})
    assert response.json()["demo_fixture"] is True


def test_dispute_roles_and_own_sandbox_roleplay(api):
    mid = session(api)
    decision = run(api, mid)["decisions"][-1]
    dsp = api.client.post("/v1/disputes", headers=headers(), json={
        "decision_id": decision["id"], "raised_by": "merchant", "claim": "synthetic checkout dispute",
    }).json()
    assert dsp["sandbox"] and dsp["user_id"] == "alice" and dsp["raised_by_uid"] == "alice"
    assert api.client.get(f"/v1/disputes/{dsp['id']}", headers=headers("bob")).status_code == 403
    assert api.client.get("/v1/disputes", headers=headers("bob")).json() == []
    assert api.client.post(f"/v1/disputes/{dsp['id']}/resolve", headers=headers(), json={}).status_code == 403
    assert api.client.post(f"/sim/disputes/{dsp['id']}/resolve", headers=headers("bob"), json={}).status_code == 403
    response = api.client.post(f"/sim/disputes/{dsp['id']}/resolve", headers=headers(), json={"resolution": "role-play"})
    assert response.json()["resolution_scope"] == "sandbox"
    api.store.update("disputes", dsp["id"], {"sandbox": False})
    assert api.client.post(f"/sim/disputes/{dsp['id']}/resolve", headers=headers(), json={}).status_code == 403
    assert api.client.post(f"/v1/disputes/{dsp['id']}/resolve", headers=headers("analyst"), json={}).json()["resolved_by"] == "analyst"
    api.store.update("mandates", mid, {"demo_fixture": False})
    assert api.client.post("/v1/disputes", headers=headers(), json={
        "decision_id": decision["id"], "raised_by": "issuer", "claim": "not permitted",
    }).status_code == 403


def test_shared_registry_and_seed_require_admin(api):
    body = {"agent_id": "test", "name": "Test", "provider": "Test"}
    for user in ("alice", "analyst"):
        assert api.client.post("/v1/agents", headers=headers(user), json=body).status_code == 403
        assert api.client.post("/admin/seed", headers=headers(user)).status_code == 403
    assert api.client.post("/v1/agents", headers=headers("admin"), json=body).status_code == 200
    assert api.client.post("/admin/seed", headers=headers("admin")).status_code == 200
    assert api.client.get("/v1/agents", headers=headers()).status_code == 200


@pytest.mark.parametrize("scenario,expected", [
    ("clean", "APPROVE"), ("hidden_injection", "BLOCK"), ("unknown_payee", "BLOCK"),
    ("review_upsell_injection", "STEP_UP"), ("price_inflation", "STEP_UP"),
    ("split_payment", "BLOCK"), ("category_creep", "STEP_UP"), ("over_cap_premium", "BLOCK"),
])
def test_all_scenarios_work_for_anonymous_visitors(api, scenario, expected):
    assert run(api, session(api, "guest"), scenario, "guest", fresh=True)["final_verdict"] == expected


def test_pr8_guided_flow_keeps_dispute_and_receipt_verification(api):
    mid = session(api, "guest")
    run(api, mid, user="guest", fresh=True)
    blocked = run(api, mid, "hidden_injection", "guest")
    step = run(api, mid, "review_upsell_injection", "guest")
    api.client.post(f"/v1/stepups/{step['stepup_id']}/respond", headers=headers("guest"), json={"approve": False})
    dsp = api.client.post("/v1/disputes", headers=headers("guest"), json={
        "decision_id": blocked["decisions"][-1]["id"], "claim": "wrong payee",
    })
    assert dsp.status_code == 200
    assert api.client.post(f"/sim/disputes/{dsp.json()['id']}/resolve", headers=headers("guest"), json={}).status_code == 200
    receipt = api.client.get(f"/v1/receipts/{blocked['receipt_id']}", headers=headers("guest")).json()
    assert api.client.post("/v1/receipts/verify", headers=headers("guest"), json=receipt).json()["valid"]
    receipt["attempted"]["amount"] += 1
    assert not api.client.post("/v1/receipts/verify", headers=headers("guest"), json=receipt).json()["valid"]
    assert api.client.get(f"/v1/receipts/chain/{mid}", headers=headers("guest")).json()["chain_intact"]
    assert api.client.post("/sim/compare", headers=headers("guest"), json={"mandate_id": mid}).status_code == 200


@pytest.mark.parametrize("marker", ["cloud-run", "production", "auth-emulator"])
def test_deployed_bypass_is_rejected_before_seed(monkeypatch, marker):
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    settings = replace(auth.settings, auth_mode="demo", environment="local", gcp_project="demo-anumati", seed_on_start=True)
    if marker == "cloud-run":
        monkeypatch.setenv("K_SERVICE", "anumati")
    elif marker == "production":
        settings = replace(settings, environment="production")
    else:
        settings = replace(settings, auth_mode="firebase", environment="production")
        monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    monkeypatch.setattr(auth, "settings", settings)
    monkeypatch.setattr(main, "settings", settings)
    seeded = Mock()
    monkeypatch.setattr(main, "seed", seeded)
    with pytest.raises(RuntimeError, match="Deployed endpoints"):
        with TestClient(main.app):
            pass
    seeded.assert_not_called()


def test_demo_requires_loopback(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, auth_mode="demo", environment="local", store_backend="memory"))
    set_store(MemoryStore())
    with TestClient(main.app, client=("192.0.2.1", 1234)) as client:
        assert client.get("/v1/mandates").status_code == 403
    with TestClient(main.app, client=("127.0.0.1", 1234)) as client:
        assert client.get("/v1/mandates").status_code == 200


def test_demo_rejects_firestore_before_seeding_or_creating_store(monkeypatch):
    settings = replace(auth.settings, auth_mode="demo", environment="local", store_backend="firestore", seed_on_start=True)
    monkeypatch.setattr(auth, "settings", settings)
    monkeypatch.setattr(main, "settings", settings)
    seeded = Mock(side_effect=AssertionError("Invalid mode reached seeding"))
    factory = Mock(side_effect=AssertionError("Invalid mode created a cloud store"))
    monkeypatch.setattr(main, "seed", seeded)
    monkeypatch.setattr(main, "get_store", factory)
    with pytest.raises(RuntimeError, match="requires memory storage"):
        with TestClient(main.app):
            pass
    seeded.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("request_headers", [
    {"Forwarded": "for=127.0.0.1"}, {"X-Forwarded-For": "127.0.0.1"},
    {"X-Forwarded-Host": "localhost"}, {"X-Forwarded-Proto": "http"},
    {"X-Real-IP": "127.0.0.1"}, {"Via": "local-proxy"},
    {"Origin": "https://external.example"}, {"Origin": "null"},
    {"Host": "external.example"},
])
def test_demo_rejects_forwarded_and_nonlocal_browser_requests(monkeypatch, request_headers):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, auth_mode="demo", environment="local", store_backend="memory"))
    store = MemoryStore()
    set_store(store)
    with TestClient(main.app, client=("127.0.0.1", 1234)) as client:
        response = client.post("/v1/mandates/compile", headers=request_headers,
                               json={"agent_id": "kiranabot", "text": "groceries"})
    assert response.status_code == 403
    assert store.query("mandates") == []


def test_demo_is_owner_scoped_and_has_no_staff_privileges(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(auth.settings, auth_mode="demo", environment="local", store_backend="memory"))
    store = MemoryStore()
    set_store(store)
    seed(store)
    foreign = {**store.get("mandates", DEMO_MANDATE_ID), "user_id": "someone_else"}
    store.put("mandates", "foreign", foreign)
    with TestClient(main.app, client=("127.0.0.1", 1234), base_url="http://localhost") as client:
        response = client.post("/v1/mandates/compile", headers={"Origin": "http://localhost:5173"}, json={
            "user_id": "someone_else", "agent_id": "kiranabot", "text": "groceries", "sandbox": False,
        })
        assert response.status_code == 200
        assert response.json()["user_id"] == "user_demo" and response.json()["demo_fixture"] is True
        assert client.get("/v1/mandates/foreign").status_code == 403
        assert client.post("/v1/mandates/foreign/revoke").status_code == 403
        assert client.get("/v1/mandates?user_id=someone_else").status_code == 403
        assert all(m["user_id"] == "user_demo" for m in client.get("/v1/mandates").json())
        assert client.post("/admin/seed").status_code == 403
        assert client.post("/v1/agents", json={"agent_id": "new", "name": "New", "provider": "Demo"}).status_code == 403
        assert client.post("/v1/payments/authorize", json={
            "user_id": "user_demo", "mandate_id": DEMO_MANDATE_ID, "agent_id": "kiranabot", "amount": 100,
            "payee_vpa": "freshkart@okaxis", "payee_name": "FreshKart", "simulated": False,
        }).status_code == 403
    assert store.get("mandates", "foreign")["status"] == foreign["status"]


@pytest.mark.parametrize("user", ["alice", "analyst", "admin", "guest"])
def test_sandbox_routes_reject_ordinary_mandates_before_cleanup_and_models(api, monkeypatch, user):
    mid = session(api, user)
    result = run(api, mid, user=user)
    api.store.update("mandates", mid, {"demo_fixture": False})
    model = Mock(side_effect=AssertionError("Ordinary mandate reached model"))
    monkeypatch.setattr(sim, "_gemini_agent", model)
    monkeypatch.setattr(sim, "gemini_analyse", model)
    for path in ("/sim/run", "/sim/compare"):
        response = api.client.post(path, headers=headers(user), json={"mandate_id": mid, "fresh": True, "mode": "gemini"})
        assert response.status_code == 403
    assert api.store.get("decisions", result["decisions"][-1]["id"])
    model.assert_not_called()


@pytest.mark.parametrize("user", ["alice", "analyst", "admin", "guest"])
def test_payment_mode_must_match_mandate_even_for_staff(api, user):
    mid = session(api, user)
    body = {"user_id": user, "agent_id": "kiranabot", "mandate_id": mid,
            "payee_vpa": "freshkart@okaxis", "payee_name": "FreshKart", "amount": 100}
    assert api.client.post("/v1/payments/authorize", headers=headers(user), json=body).status_code == 403
    body["simulated"] = True
    assert api.client.post("/v1/payments/authorize", headers=headers(user), json=body).status_code == 200
    api.store.update("mandates", mid, {"demo_fixture": False})
    before = api.store.query("decisions")
    assert api.client.post("/v1/payments/authorize", headers=headers(user), json=body).status_code == 403
    assert api.store.query("decisions") == before


@pytest.mark.parametrize("user", ["alice", "guest"])
def test_console_can_explicitly_compile_and_simulate_own_sandbox_mandate(api, user):
    response = api.client.post("/v1/mandates/compile", headers=headers(user), json={
        "agent_id": "kiranabot", "text": DEMO_MANDATE_TEXT, "sandbox": True,
        "demo_fixture": False, "user_id": "someone_else",
    })
    mandate = response.json()
    assert response.status_code == 200 and mandate["demo_fixture"] is True and mandate["user_id"] == user
    assert api.client.post(f"/v1/mandates/{mandate['id']}/sign", headers=headers(user), json={}).status_code == 200
    assert run(api, mandate["id"], user=user)["final_verdict"] == "APPROVE"


@pytest.mark.parametrize("simulated", [True, False])
def test_policy_history_is_partitioned_without_deleting_legacy_records(api, simulated):
    mid = session(api)
    for i in range(11):
        api.store.put("decisions", f"legacy_{i}", {
            "request": {"mandate_id": mid, "amount": 1900, "payee_vpa": "freshkart@okaxis", "simulated": not simulated},
            "verdict": "APPROVE", "status": "final", "created_at": utcnow_iso(),
        })
    req = PaymentRequest(user_id="alice", mandate_id=mid, agent_id="kiranabot", amount=1900,
                         payee_vpa="freshkart@okaxis", payee_name="FreshKart", simulated=simulated)
    findings, _ = run_policy(req, api.store.get("mandates", mid), api.store)
    assert not {"PERIOD_CAP", "TXN_RATE", "STRUCTURING"}.intersection(f.code for f in findings)
    api.store.put("decisions", "same_mode", {
        "request": {"mandate_id": mid, "amount": 1900, "payee_vpa": "freshkart@okaxis", "simulated": simulated},
        "verdict": "APPROVE", "status": "final", "created_at": utcnow_iso(),
    })
    findings, _ = run_policy(req, api.store.get("mandates", mid), api.store)
    assert {"PERIOD_CAP", "STRUCTURING"}.issubset(f.code for f in findings)
    assert len(api.store.query("decisions")) == 12


def test_idempotency_does_not_reuse_legacy_opposite_mode(api):
    mid = ordinary_mandate(api)
    body = {"user_id": "alice", "agent_id": "kiranabot", "mandate_id": mid, "amount": 100,
            "payee_vpa": "freshkart@okaxis", "payee_name": "FreshKart", "idempotency_key": "same"}
    api.store.put("decisions", "legacy", {"request": {**body, "simulated": True}})
    first = api.client.post("/v1/payments/authorize", headers=headers(), json=body)
    assert first.status_code == 200 and first.json()["id"] != "legacy"
    assert api.client.post("/v1/payments/authorize", headers=headers(), json=body).json()["id"] == first.json()["id"]
    assert api.store.get("decisions", "legacy")


def test_seed_classifies_legacy_template_without_reactivating_or_rewriting_history(api):
    mandate = api.store.get("mandates", DEMO_MANDATE_ID)
    mandate.pop("demo_fixture")
    mandate["status"] = "revoked"
    api.store.put("mandates", DEMO_MANDATE_ID, mandate)
    seed(api.store)
    assert api.store.get("mandates", DEMO_MANDATE_ID) == {**mandate, "demo_fixture": True}


def test_firebase_wrapper_checks_revocation_and_expected_project(monkeypatch):
    import firebase_admin
    from firebase_admin import auth as firebase_auth

    monkeypatch.setattr(auth, "settings", replace(auth.settings, gcp_project="demo-anumati"))
    app = object()
    monkeypatch.setattr(firebase_admin, "get_app", Mock(side_effect=ValueError()))
    initialize = Mock(return_value=app)
    verify = Mock(return_value={"uid": "alice"})
    monkeypatch.setattr(firebase_admin, "initialize_app", initialize)
    monkeypatch.setattr(firebase_auth, "verify_id_token", verify)
    assert auth._verify_firebase_token("test-token")["uid"] == "alice"
    initialize.assert_called_once_with(options={"projectId": "demo-anumati"}, name="anumati-auth")
    verify.assert_called_once_with("test-token", app=app, check_revoked=True)


def test_create_once_never_overwrites_existing_firestore_or_memory_document():
    memory = MemoryStore()
    memory.put("mandates", "x", {"status": "revoked"})
    assert memory.create("mandates", "x", {"status": "active"})["status"] == "revoked"
    from google.api_core.exceptions import AlreadyExists
    firestore = object.__new__(FirestoreStore)
    firestore._client = Mock()
    ref = firestore._client.collection.return_value.document.return_value
    ref.create.side_effect = AlreadyExists("already created")
    ref.get.return_value.to_dict.return_value = {"id": "x", "status": "revoked"}
    assert firestore.create("mandates", "x", {"status": "active"})["status"] == "revoked"
    ref.set.assert_not_called()


def test_role_setup_preserves_claims_and_revokes_sessions():
    sdk = Mock()
    sdk.get_user.return_value = SimpleNamespace(email="staff@example.com", email_verified=True,
                                                provider_data=["google.com"], custom_claims={"other": True})
    firebase_roles.assign_role(sdk, "uid", "analyst", "app")
    sdk.set_custom_user_claims.assert_called_with("uid", {"other": True, "role": "analyst"}, app="app")
    sdk.revoke_refresh_tokens.assert_called_with("uid", app="app")
    sdk.get_user.return_value.custom_claims["role"] = "admin"
    firebase_roles.assign_role(sdk, "uid", "user", "app")
    sdk.set_custom_user_claims.assert_called_with("uid", {"other": True}, app="app")
    sdk.get_user.return_value.email_verified = False
    with pytest.raises(ValueError, match="verified email"):
        firebase_roles.assign_role(sdk, "uid", "admin", "app")


def test_role_preview_never_initializes_firebase(monkeypatch):
    import firebase_admin
    initialize = Mock(side_effect=AssertionError("Preview contacted Firebase"))
    monkeypatch.setattr(firebase_admin, "initialize_app", initialize)
    assert firebase_roles.main(["--project", "demo-anumati", "--uid", "uid", "--role", "analyst"]) == 0
    initialize.assert_not_called()


@pytest.mark.parametrize("case", ["valid", "expired", "wrong-project", "wrong-issuer", "forged", "revoked", "disabled"])
def test_real_firebase_sdk_verifies_signed_tokens_without_cloud(api, monkeypatch, case):
    """Exercise the SDK's crypto/project/session checks with local test keys.

    Only certificate retrieval and user lookup are substituted; JWT parsing,
    signature checking, expiry and revoked/disabled checks use the real SDK.
    """
    import json
    import time
    import jwt
    import firebase_admin
    from firebase_admin import auth as sdk_auth, credentials, _token_gen
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    credential = credentials.Certificate({"type": "service_account", "project_id": "demo-anumati",
                                          "private_key": private, "client_email": "test@demo-anumati.iam.gserviceaccount.com",
                                          "token_uri": "https://oauth2.googleapis.com/token"})
    app = firebase_admin.initialize_app(credential, options={"projectId": "demo-anumati"}, name="anumati-auth")
    try:
        monkeypatch.setattr(_token_gen.CertificateFetchRequest, "__call__", Mock(return_value=SimpleNamespace(
            status=200, data=json.dumps({"test-key": public}).encode(),
        )))
        now = int(time.time())
        user = SimpleNamespace(disabled=case == "disabled", tokens_valid_after_timestamp=now * 1000 if case == "revoked" else 0)
        monkeypatch.setattr(sdk_auth._get_client(app), "get_user", Mock(return_value=user))
        monkeypatch.setattr(auth, "_verify_firebase_token", REAL_VERIFY)
        claims = {"aud": "other-project" if case == "wrong-project" else "demo-anumati",
                  "iss": "https://securetoken.google.com/other" if case == "wrong-issuer" else "https://securetoken.google.com/demo-anumati",
                  "sub": "alice", "iat": now - 60, "auth_time": now - 60,
                  "exp": now - 1 if case == "expired" else now + 300,
                  "firebase": {"sign_in_provider": "google.com"}}
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if case == "forged" else key
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})
        response = api.client.get("/v1/mandates", headers=headers(token))
        assert response.status_code == (200 if case == "valid" else 401), response.text
    finally:
        firebase_admin.delete_app(app)


# --- security-review hardening (M2 signing-key guard, M1 Gemini cost cap) ------

def test_deployed_refuses_default_receipt_signing_key(monkeypatch):
    """A deployed service must not sign liability receipts with the dev HMAC key."""
    from app.config import DEFAULT_RECEIPT_SIGNING_KEY
    monkeypatch.setenv("K_SERVICE", "anumati-api")
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    base = replace(auth.settings, auth_mode="firebase", environment="production",
                   gcp_project="anumati-x", store_backend="firestore")
    monkeypatch.setattr(auth, "settings", replace(base, receipt_signing_key=DEFAULT_RECEIPT_SIGNING_KEY))
    with pytest.raises(RuntimeError, match="RECEIPT_SIGNING_KEY"):
        auth.validate_auth_configuration()
    # a real injected key boots fine
    monkeypatch.setattr(auth, "settings", replace(base, receipt_signing_key="kms-backed-secret"))
    auth.validate_auth_configuration()


def _reset_gemini_limiter(gemini):
    gemini._rl_window_start = 0.0
    gemini._rl_window_count = 0
    gemini._rl_total = 0
    gemini._rl_warned_total = False


def test_gemini_per_minute_cap_degrades_to_heuristics(monkeypatch):
    from app import gemini
    _reset_gemini_limiter(gemini)
    monkeypatch.setattr(gemini, "settings", SimpleNamespace(gemini_max_calls_per_min=2, gemini_max_calls_total=0))
    assert gemini._rate_limit_ok() is True
    assert gemini._rate_limit_ok() is True
    assert gemini._rate_limit_ok() is False  # window cap hit
    # even when the client is 'available', an over-cap call returns None (fallback)
    monkeypatch.setattr(gemini, "available", lambda: True)
    assert gemini.generate_json("sys", "prompt") is None


def test_gemini_total_cap_is_enforced(monkeypatch):
    from app import gemini
    _reset_gemini_limiter(gemini)
    monkeypatch.setattr(gemini, "settings", SimpleNamespace(gemini_max_calls_per_min=0, gemini_max_calls_total=1))
    assert gemini._rate_limit_ok() is True
    assert gemini._rate_limit_ok() is False  # total cap hit
