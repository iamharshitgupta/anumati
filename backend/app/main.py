from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .gemini import engine_name
from .routers import agents, decisions, disputes, mandates, sim, stepups
from .seed import seed
from .store import get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(
    title="Anumati — trust & liability gateway for AI-agent payments",
    version=__version__,
    description=(
        "Sits between an AI agent's payment request and the UPI rail. Compiles natural-language "
        "mandates into policy, dual-checks every agent payment (deterministic policy + Gemini semantic audit), "
        "returns APPROVE / STEP_UP / BLOCK, and issues signed, hash-chained Decision Receipts for dispute resolution."
    ),
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (mandates, agents, decisions, stepups, disputes, sim):
    app.include_router(r.router)


@app.on_event("startup")
def _startup():
    if settings.seed_on_start:
        info = seed(get_store())
        logging.getLogger("anumati").info("seeded demo data: %s", info)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "store": settings.store_backend, "semantic_engine": engine_name(),
            "model": settings.gemini_model if engine_name() == "gemini" else None}


@app.get("/")
def root():
    return {"service": "anumati", "docs": "/docs", "health": "/healthz"}


@app.post("/admin/seed")
def reseed():
    return seed(get_store())
