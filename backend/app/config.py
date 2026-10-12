"""Runtime configuration. Everything is driven by environment variables so the same
image runs locally (in-memory store, heuristic semantics) and on Cloud Run
(Firestore + Gemini on Vertex AI / Gemini API)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Explicit local demo access; production always requires Firebase tokens.
    auth_mode: str = os.getenv("ANUMATI_AUTH_MODE", "firebase")
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

    # --- receipts -------------------------------------------------------
    # HMAC key for Decision Receipts. In production rotate via Secret Manager
    # and/or swap to Cloud KMS asymmetric signing (see receipts.py).
    receipt_signing_key: str = os.getenv("RECEIPT_SIGNING_KEY", "dev-only-insecure-key-change-me")
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
