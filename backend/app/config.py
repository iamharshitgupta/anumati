"""Runtime configuration. Everything is driven by environment variables so the same
image runs locally (in-memory store, heuristic semantics) and on Cloud Run
(Firestore + Gemini on Vertex AI / Gemini API)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# Sentinel for the local-only HMAC key. A deployed service must never sign the
# liability-bearing Decision Receipts with this — see validate_auth_configuration().
DEFAULT_RECEIPT_SIGNING_KEY = "dev-only-insecure-key-change-me"


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _is_deployed() -> bool:
    # Cloud Run sets K_SERVICE; ANUMATI_ENV=production forces the deployed posture
    # even off Cloud Run. Either one means "never serve the no-login demo path".
    return bool(os.getenv("K_SERVICE")) or os.getenv("ANUMATI_ENV", "local") == "production"


def _default_auth_mode() -> str:
    """Zero-config locally, locked down when deployed.

    Honour an explicit ANUMATI_AUTH_MODE if set. Otherwise pick `demo` only when
    running the local in-memory build (no Firebase project needed, so the sandbox
    just works), and `firebase` everywhere else — Cloud Run, production, or any
    Firestore-backed run, all of which require a verified Firebase ID token.
    """
    explicit = os.getenv("ANUMATI_AUTH_MODE")
    if explicit:
        return explicit.strip().lower()
    local_memory = os.getenv("ANUMATI_STORE", "memory") == "memory" and not _is_deployed()
    return "demo" if local_memory else "firebase"


@dataclass(frozen=True)
class Settings:
    # Local in-memory runs default to the no-login demo path; Cloud Run, production,
    # and any Firestore-backed run default to Firebase tokens. Override with
    # ANUMATI_AUTH_MODE. The deployed posture can never fall back to demo.
    auth_mode: str = field(default_factory=_default_auth_mode)
    environment: str = os.getenv("ANUMATI_ENV", "local")

    # --- storage -------------------------------------------------------
    # "firestore" on Cloud Run, "memory" for local demos/tests.
    store_backend: str = os.getenv("ANUMATI_STORE", "memory")
    gcp_project: str | None = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    firestore_database: str = os.getenv("FIRESTORE_DATABASE", "(default)")

    # --- Gemini ---------------------------------------------------------
    # Either GOOGLE_API_KEY (Gemini Developer API) or Vertex AI via ADC.
    gemini_api_key: str | None = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    use_vertex: bool = _bool("GOOGLE_GENAI_USE_VERTEXAI", False)
    vertex_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_enabled: bool = _bool("ANUMATI_GEMINI", True)
    gemini_timeout_s: float = float(os.getenv("GEMINI_TIMEOUT_S", "12"))
    # Cost guardrails: every Gemini path has a heuristic fallback, so when a cap is
    # hit we simply degrade to heuristics instead of spending more. This bounds the
    # credit burn from a scripted caller hammering /sim/compare or /sim/run?mode=gemini
    # behind free anonymous tokens. Override per deploy; 0 disables a cap.
    gemini_max_calls_per_min: int = int(os.getenv("GEMINI_MAX_CALLS_PER_MIN", "30"))
    gemini_max_calls_total: int = int(os.getenv("GEMINI_MAX_CALLS_TOTAL", "5000"))

    # --- receipts -------------------------------------------------------
    # HMAC key for Decision Receipts. In production rotate via Secret Manager
    # and/or swap to Cloud KMS asymmetric signing (see receipts.py).
    receipt_signing_key: str = os.getenv("RECEIPT_SIGNING_KEY", DEFAULT_RECEIPT_SIGNING_KEY)
    receipt_key_id: str = os.getenv("RECEIPT_KEY_ID", "dev-hmac-v1")

    # --- risk policy ----------------------------------------------------
    # UPI Circle full-delegation defaults (₹5,000 / txn, ₹15,000 / month) are the
    # hard ceilings a mandate may not exceed, regardless of what the user writes.
    hard_cap_per_txn: float = float(os.getenv("HARD_CAP_PER_TXN", "5000"))
    hard_cap_per_month: float = float(os.getenv("HARD_CAP_PER_MONTH", "15000"))
    step_up_threshold: int = int(os.getenv("STEP_UP_THRESHOLD", "40"))
    block_threshold: int = int(os.getenv("BLOCK_THRESHOLD", "70"))
    step_up_ttl_s: int = int(os.getenv("STEP_UP_TTL_S", "300"))

    # --- misc -----------------------------------------------------------
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    )
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")
    seed_on_start: bool = _bool("ANUMATI_SEED", True)


settings = Settings()
