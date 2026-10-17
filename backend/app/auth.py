"""API identity and permissions, separate from Anumati's payment-risk checks.

Firebase mode (the default): send a Firebase ID token as Authorization: Bearer
<token>. GOOGLE_CLOUD_PROJECT identifies the token's expected project; ADC is
the server credential, not the visiting user's identity. Tokens are checked for
expiry, signature, project, revocation and disabled accounts. Trusted custom
claim `role` may be `analyst` or `admin`; ordinary/anonymous accounts are users.
Only a trusted administrator should assign these claims outside the console UI.

Local demo: the local in-memory build selects this automatically (see
config._default_auth_mode), so `uvicorn app.main:app` just works with no Firebase
setup; set ANUMATI_AUTH_MODE=demo to force it, or =firebase to require tokens
locally. It preserves the synthetic user_demo workflow, granting only user_demo
ownership in memory storage, never staff permissions or access to live Firestore.
Forwarded requests and non-local browser origins are rejected, but this is not
proxy attestation: do not expose it through a tunnel. Cloud Run (K_SERVICE) and
ANUMATI_ENV=production never select or accept this mode — they always require a
verified Firebase ID token, and Firebase Auth emulator credentials are rejected
when deployed.

This authenticates the hackathon console, not real UAP/AP2 agent credentials or
a bank account holder. Those payment identity/signature integrations remain
stubbed as the PRD specifies. Authentication is not a rate limit or spend cap.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import threading
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

log = logging.getLogger("anumati.auth")
_bearer = HTTPBearer(auto_error=False)
_app_lock = threading.Lock()


@dataclass(frozen=True)
class Principal:
    uid: str
    role: str = "user"
    is_demo: bool = False
    is_anonymous: bool = False

    @property
    def is_staff(self) -> bool:
        return self.role in {"analyst", "admin"}


def validate_auth_configuration() -> None:
    deployed = bool(os.getenv("K_SERVICE")) or settings.environment == "production"
    if settings.auth_mode not in {"firebase", "demo"}:
        raise RuntimeError("ANUMATI_AUTH_MODE must be firebase or demo")
    if deployed and (settings.auth_mode != "firebase" or os.getenv("FIREBASE_AUTH_EMULATOR_HOST")):
        raise RuntimeError("Deployed endpoints require real Firebase authentication")
    if settings.auth_mode == "firebase" and not settings.gcp_project:
        raise RuntimeError("Firebase authentication requires GOOGLE_CLOUD_PROJECT")
    if settings.auth_mode == "demo" and settings.store_backend != "memory":
        raise RuntimeError("Local demo authentication requires memory storage; use Firebase authentication for Firestore")


def _verify_firebase_token(token: str) -> dict:
    import firebase_admin
    from firebase_admin import auth

    with _app_lock:
        try:
            app = firebase_admin.get_app("anumati-auth")
        except ValueError:
            app = firebase_admin.initialize_app(options={"projectId": settings.gcp_project}, name="anumati-auth")
    return auth.verify_id_token(token, app=app, check_revoked=True)


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    try:
        validate_auth_configuration()
    except RuntimeError as exc:
        raise HTTPException(503, "Authentication is not configured") from exc
    if settings.auth_mode == "demo":
        host = request.client.host if request.client else ""
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "testclient" and settings.store_backend == "memory"
        if not local:
            raise HTTPException(403, "Local demo mode only accepts loopback callers")
        forwarded = {"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "via"}
        if any(header in request.headers for header in forwarded):
            raise HTTPException(403, "Local demo mode does not accept forwarded requests")
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                local_origin = parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            except ValueError:
                local_origin = False
            if not local_origin:
                raise HTTPException(403, "Local demo mode requires a loopback browser origin")
        host = request.url.hostname
        test_server = request.scope.get("server") == ["testserver", 80] or request.scope.get("server") == ("testserver", 80)
        if host not in {"localhost", "127.0.0.1", "::1"} and not (test_server and host == "testserver"):
            raise HTTPException(403, "Local demo mode requires a loopback host")
        return Principal("user_demo", is_demo=True)
    if not credentials:
        raise HTTPException(401, "Firebase ID token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = _verify_firebase_token(credentials.credentials)
        uid = claims["uid"]
        if not isinstance(uid, str) or not uid:
            raise ValueError("missing uid")
        provider = claims.get("firebase", {})
        if not isinstance(provider, dict):
            raise ValueError("invalid provider claims")
    except ImportError as exc:
        raise HTTPException(503, "Firebase authentication dependency unavailable") from exc
    except Exception as exc:
        log.warning("Token verification failed (%s)", type(exc).__name__)
        raise HTTPException(401, "Invalid or expired Firebase ID token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    anonymous = provider.get("sign_in_provider") == "anonymous"
    role = claims.get("role")
    return Principal(uid, role if not anonymous and role in ("analyst", "admin") else "user",
                     is_anonymous=anonymous)


Caller = Annotated[Principal, Depends(current_principal)]


def require_owner(caller: Principal, user_id: str | None, *, staff_read: bool = False) -> None:
    if not (caller.uid == user_id or (staff_read and caller.is_staff)):
        raise HTTPException(403, "Not permitted for this account")


def require_sandbox_mandate(caller: Principal, mandate: dict) -> None:
    require_owner(caller, mandate.get("user_id"))
    if mandate.get("demo_fixture") is not True:
        raise HTTPException(403, "Simulation requires a synthetic sandbox mandate")


def scoped_user(caller: Principal, requested: str | None = None) -> str | None:
    if caller.is_staff:
        return requested
    require_owner(caller, requested or caller.uid)
    return caller.uid


def require_role(caller: Principal, *roles: str) -> None:
    if caller.role not in roles:
        raise HTTPException(403, "Insufficient permissions")
