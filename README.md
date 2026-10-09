# Anumati (अनुमति)

**A trust, risk and liability gateway for payments initiated by AI agents on UPI.**
AI Builder Cup 2026 · BFSI: Intelligent Risk, Fraud & Financial Experiences

> India is about to let AI agents pay on UPI without per-transaction approval (NPCI's Unified Agent Protocol, UPI Circle delegation, Google's AP2 mandates). Mandates prove the human *authorised* an agent. Nothing proves the agent wasn't **steered** between the mandate and the rail — by hidden page text, poisoned reviews, or a payee swap. Anumati answers that question per payment, in real time, and signs the evidence.

![Architecture](docs/architecture.png)

## What it does

| Capability | How |
|---|---|
| **Mandate compiler** | "Weekly groceries from FreshKart or Zepto, ≤₹2,000/order, never a new payee, confirm above ₹1,500" → schema-validated guardrails via **Gemini** structured output, clamped to UPI Circle ceilings, signed by the user |
| **Dual-check decision engine** | Deterministic policy (caps, velocity, structuring, verified-merchant payee resolution, suspect registry, category scope, cart integrity) **+** Gemini semantic audit of the content the agent read and the reasoning it produced (injection score, intent-drift score) |
| **Graduated verdict** | APPROVE · STEP_UP (one-tap human confirm via **Firestore** realtime listener) · BLOCK |
| **Signed Decision Receipts** | Canonical JSON → SHA-256 → HMAC, hash-chained per mandate, verifiable offline; plain-language memo and AP2-style liability hints |
| **Dispute workbench** | Replays the receipt; Gemini drafts a neutral attribution across user / agent provider / merchant / issuer; a human closes the case |
| **Red-team sandbox** | Eight mock merchant pages (clean + seven attacks) and a steerable shopping agent, so judges watch the attack and the catch live |
| **Evaluation** | 44 synthetic cases (25 attack / 19 benign, incl. hard negatives) vs. a *fair* deterministic-policy baseline **and** a caps-only baseline, with the semantic layer's marginal lift isolated — see [`eval/RESULTS.md`](eval/RESULTS.md) |

## Google Cloud services

- **Gemini 2.5 Flash** (Gemini API or Vertex AI) — mandate compilation, injection/drift audit, dispute attribution. Every call has a heuristic fallback; the gateway never fails open or closed because a model is slow.
- **Cloud Run** — the gateway API, policy engine and sandbox (`backend/`), pinned to `min-instances=1`.
- **Firestore** — mandates, agents, decisions, step-ups, receipts, disputes, registries; realtime listeners drive the one-tap step-up UX.
- **Firebase** — Hosting (proxies `/v1/*` to Cloud Run), anonymous Auth, Firestore SDK, optional FCM.
- **Secret Manager** — receipt signing key and Gemini key.

## Quick start (local, no cloud account needed)

```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --port 8080            # in-memory store, heuristic semantics
# GOOGLE_API_KEY=... uvicorn app.main:app --port 8080   # with Gemini
```
Open the console: `cd web && python3 -m http.server 5173` → http://localhost:5173 (it points at `http://localhost:8080` by default).

Try an attack from the shell:
```bash
curl -s -X POST localhost:8080/sim/run -H 'content-type: application/json' \
  -d '{"mandate_id":"mnd_demo0001","scenario":"hidden_injection"}' | python3 -m json.tool | head -40
```

Tests and eval:
```bash
python -m pytest tests -q
python eval/run_eval.py          # writes eval/RESULTS.md
```

## Deploy

```bash
PROJECT=<gcp-project> REGION=asia-south1 GOOGLE_API_KEY=<gemini key> ./infra/deploy.sh
#   or: USE_VERTEX=1 PROJECT=<gcp-project> ./infra/deploy.sh
```
The script enables APIs, creates Firestore, stores secrets, deploys Cloud Run from source, deploys Firestore rules/indexes and Firebase Hosting, and prints both URLs. Paste your Firebase web config into `web/firebase-config.js` and redeploy hosting to turn on realtime step-ups.

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/mandates/compile` · `/{id}/sign` · `/{id}/revoke` | mandate lifecycle |
| POST | `/v1/agents` | agent registry |
| POST | `/v1/payments/authorize` | **the gateway call** → `Decision` |
| GET | `/v1/decisions`, `/v1/decisions/{id}` | decision feed |
| GET | `/v1/stepups` · POST `/v1/stepups/{id}/respond` | human one-tap |
| GET | `/v1/receipts/{id}` · `/v1/receipts/chain/{mandate}` · POST `/v1/receipts/verify` | receipts & offline verification |
| POST | `/v1/disputes` · `/{id}/resolve` | dispute replay & attribution |
| GET/POST | `/sim/scenarios` · `/sim/merchant/{s}` · `/sim/run` | red-team sandbox |

Interactive docs at `/docs`.

## Repository layout

```
backend/   FastAPI service (Cloud Run)         docs/     PRD, architecture (svg/png/md), demo script, submission
web/       Firebase console + rules/indexes    eval/     synthetic suite, baseline runner, RESULTS.md
tests/     pytest                              infra/    deploy.sh
```

## Documents

- [Product Requirements](docs/PRD.md) · [Architecture](docs/ARCHITECTURE.md) · [Demo script](docs/DEMO_SCRIPT.md) · [Submission text](docs/SUBMISSION.md) · [Eval results](eval/RESULTS.md)

## Honest scope

Synthetic data only. No real UPI integration; the rail is simulated. Registries (I4C suspect registry, DoT FRI, NPCI verified merchants) are mocks with the right shape. The heuristic semantic engine was tuned on the included suite — treat `RESULTS.md` as a regression suite and the Gemini run as the independent number.
