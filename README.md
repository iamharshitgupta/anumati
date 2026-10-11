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
| **Signed Decision Receipts** | Canonical JSON → SHA-256 → HMAC, hash-chained per mandate, verifiable offline **in any language** (the console re-verifies in the browser; edit any field and the signature breaks live); plain-language memo and AP2-style liability hints |
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
Open the console: `cd web && python3 -m http.server 5173` → http://localhost:5173 (it points at `http://localhost:8080` by default). Click **▶ Guided demo** to auto-run the whole story (mandate → approve → block → step-up decline → dispute → tamper-proof receipt) with narration.

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

## Local development

Requires Python 3.12+ and (optionally) the `firebase` CLI for deploys.

```bash
# backend
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8080     # heuristic engine
# with Gemini:  GOOGLE_API_KEY=... ../.venv/bin/python -m uvicorn app.main:app --port 8080

# console (separate shell) — points at http://localhost:8080 by default
cd web && python3 -m http.server 5173     # open http://localhost:5173

# tests + eval (from the repo root)
.venv/bin/python -m pytest tests -q
.venv/bin/python eval/build_cases.py      # regenerate eval/cases.json
.venv/bin/python eval/run_eval.py         # writes eval/RESULTS.md (+ eval/results.json)
```

The store defaults to in-memory and the semantic engine to heuristics, so nothing above
needs a cloud account or an API key. Set `GOOGLE_API_KEY` to switch the semantic audit,
mandate compiler and dispute memo to Gemini; set `ANUMATI_STORE=firestore` (on Cloud Run)
for the Firestore backend. All knobs live in `backend/app/config.py` and are env-driven.

## Evaluation methodology

`eval/run_eval.py` runs every case through the **real** gateway (`decide()`), not a
label-vs-label assertion, and compares three controls on identical inputs:

| Control | What it is |
|---|---|
| **Anumati** | full gateway: deterministic policy **+** semantic audit |
| **Policy-only** | the same deterministic policy with the semantic layer off — the *fair* baseline |
| **Caps-only** | a naive UPI-Circle control that checks amount ceilings and nothing else |

The suite is **44 cases (25 attack / 19 benign)**, the benign set including hard
negatives — legitimate orders that look risky but must not be flagged. Because the
heuristic thresholds were tuned against this suite, `RESULTS.md` is a **regression
suite** (an upper bound), and the independent number is the `GOOGLE_API_KEY=...` Gemini
run. The report isolates the semantic layer's **marginal lift**: the attacks Anumati
flags that deterministic policy alone does not — the content-steering manipulations
that break no hard rule. See [`eval/RESULTS.md`](eval/RESULTS.md).

## Security & trust model

- **Agent-declared fields are untrusted** (`merchant`, `category`, reasoning trace).
  Payee legitimacy is resolved through the verified merchant directory and explicit
  allowlists — never the name the agent typed.
- **Consumed content is hostile by default.** It is only ever an input to scoring;
  nothing in it is executed or followed.
- **Gemini is advisory.** Its scores feed fusion but cannot override a hard policy
  failure, and its absence degrades to heuristics — never to approve-by-default.
- **Firestore rules block all browser writes;** every write goes through the Cloud Run
  API (Admin SDK). The demo rules allow authenticated reads across the single-tenant
  synthetic dataset; a production per-user ruleset ships commented in
  `web/firestore.rules`. Secrets live in Secret Manager; the HMAC signing key is
  swappable for Cloud KMS without changing the receipt format.
- **Receipts verify in any language.** The canonical form normalises
  integer-valued floats so a receipt signed by the Python gateway re-verifies
  byte-for-byte in a browser (or any other) verifier — the Receipts tab proves
  it live, and tampering with any field breaks the signature on screen.

## Version history

The repository history starts with the build as received, then one commit per review
theme — see [`CHANGELOG.md`](CHANGELOG.md) and `git log`.
