# Submission pack — AI Builder Cup 2026 (BFSI track)

Fill the form fields from here. Deadline **18 Oct 2026, 11:59 PM IST**.

## Challenge
BFSI: Intelligent Risk, Fraud & Financial Experiences

## Prototype link (Cloud Run / Firebase Hosting)
`https://<project>.web.app` — console (proxies the API)
`https://anumati-api-<hash>-<region>.a.run.app` — API (`/docs`, `/status`)

## GitHub
`https://github.com/iamharshitgupta/anumati` — **private during the build; make
public before the 18 Oct 2026 deadline** if the submission form requires a public
link.

## Demo video
≤ 3:00 — see `DEMO_SCRIPT.md`.

## Brief description (≤ 1,024 chars — this is 1,012)

Anumati is a trust, risk and liability gateway for AI-agent-initiated UPI payments. As NPCI's Unified Agent Protocol lets agents pay without per-transaction approval, a signed mandate proves authorisation but not that the agent wasn't steered by hidden page text, poisoned reviews or a payee swap. Anumati sits between agent and rail: Gemini compiles a one-line mandate into enforceable guardrails; every payment is dual-checked by a deterministic policy engine (caps, velocity, structuring, verified-merchant payee resolution, suspect registry) and a Gemini semantic audit of the content the agent read and its reasoning (injection and intent-drift scores); the verdict is APPROVE, STEP_UP or BLOCK; each decision issues a signed, hash-chained receipt that a dispute workbench replays to draft liability attribution. Built on Cloud Run (gateway, policy engine, red-team sandbox), Firestore (mandates, decisions, receipts; realtime step-up listeners), Firebase (Hosting, Auth, console, FCM) and Gemini 2.5 Flash.

## Deck (use the prescribed template → export PDF ≤ 5 MB)

Suggested slide mapping onto the template's sections:

1. **Team / title** — Anumati: the liability layer for agentic UPI payments.
2. **Problem** — UAP/AP2 prove authorisation, not faithfulness; prompt injection is the top agentic risk; legacy fraud engines are blind; ₹ mule-network scale; 30–60 s windows. Liability framework unpublished.
3. **Solution** — mandate compiler → dual-check engine → graduated verdict → signed receipt → dispute attribution. (architecture.png)
4. **Demo** — three screenshots: hidden-injection BLOCK, step-up one-tap, dispute memo.
5. **Why it works** — deterministic + semantic; agent-declared fields untrusted; receipts verifiable offline; fail-safe fallbacks.
6. **Results** — eval table (Anumati vs policy-only vs caps-only), the semantic layer's marginal lift (content-steering attacks no rule catches), 0% false flags incl. hard negatives, latency, 8/8 sandbox scenarios.
7. **Google Cloud** — service-by-service mapping (table in README).
8. **Market & go-to-market** — issuers/PSPs onboarding agents under UAP; agent providers needing a predictable contract; ombudsman evidence standard.
9. **Roadmap** — real AP2 VDC/UAP credential verification, I4C/FRI feeds, Cloud KMS signing, issuer tuning console, agent SDK.
10. **Ask / contact**.

## Judging criteria (weights) — see `THEME_ALIGNMENT.md` for the evidence map
- **Technical Merit & Gen-AI implementation — 40%** (meaningful Gen AI; technical soundness; scalability)
- **Problem Alignment & Impact — 25%** (theme fit; stakeholder value)
- **Innovation & Creativity — 25%** (originality; non-superficial Gen AI)
- **User Experience & Solution Design — 10%** (usability; cohesion)

Required tech: **Gemini/Gemma** (or an agentic platform) + **Cloud Run or Firebase**. Anumati uses Gemini 2.5 Flash on both Cloud Run and Firebase.

## Pre-submission checklist
- [ ] `status` returns `semantic_engine: gemini` on the deployed URL (the 40% Gen-AI score is judged on the Gemini build, not the heuristic default)
- [ ] Cloud Run `min-instances=1`; budget alert set
- [ ] Firebase config pasted; step-up toast works in a fresh incognito window
- [ ] Repo made **public** before the deadline; README renders; `eval/RESULTS.md` committed from a Gemini run
- [ ] Confirm the "Category Specification" label (Healthcare/Education/Sustainability/Accessibility/Social Good) that applies to a BFSI entry
- [ ] Confirm eligibility: working professionals only, 21+, JAPAC, team of 2–4
- [ ] Video ≤ 3:00, public link, plays without login
- [ ] Deck exported from the official template as PDF ≤ 5 MB
