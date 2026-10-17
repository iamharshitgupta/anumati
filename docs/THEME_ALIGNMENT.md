# Theme & problem-statement alignment — AI Builder Cup 2026

This document validates Anumati against the competition's stated theme, required
technology, and judging rubric (sourced from `aibuildercup.com/themes.html`,
Oct 2026). It is the evidence map for the deck's problem/solution/results slides.

## Chosen track

**BFSI: Intelligent Risk, Fraud & Financial Experiences** — "challenges across
banking, financial services, insurance," spanning fraud/risk reduction, process
automation, and better financial experiences.

Anumati is a **risk, fraud and liability gateway for AI-agent-initiated UPI
payments**. It sits in the BFSI core: payments, fraud prevention, and the
liability/compliance layer an issuer or ombudsman needs. The fit is direct, not
adapted — the problem (agentic payment fraud via prompt injection) only exists in
financial services and is live now (NPCI UAP, UPI Circle, AP2).

## Required technology — met

| Requirement | How Anumati meets it |
|---|---|
| **Gemini or Gemma** (or an agentic platform) | **Gemini 2.5 Flash** via the `google-genai` SDK: mandate compilation (NL → schema-validated guardrails), semantic audit (injection + intent-drift scoring over the content the agent read), and dispute attribution. Each call has a deterministic fallback so the gateway never fails open or closed. |
| **Deploy on Cloud Run or Firebase** | **Both.** Gateway + policy engine + red-team sandbox on **Cloud Run** (`min-instances=1`); console on **Firebase Hosting** (rewrites proxy `/v1/*` to Cloud Run), with Firebase Auth + Firestore + optional FCM. |

Supporting GCP services used: **Firestore** (mandates, decisions, receipts,
realtime step-up listeners), **Secret Manager** (signing + model keys).

> **Submission gate:** the 40%-weighted Gen-AI criterion is judged on the
> *deployed* build, so it must run with `GOOGLE_API_KEY` set (or `USE_VERTEX=1`)
> — `status` must report `semantic_engine: gemini`, and `eval/RESULTS.md` must
> be committed from a Gemini run, not the heuristic default used for local dev.

## Judging rubric — how we score

| Criterion (weight) | Anumati's evidence |
|---|---|
| **Technical Merit & Gen-AI implementation (40%)** | Gen AI is load-bearing, not cosmetic: the semantic auditor is the **only** control that catches content-steering attacks that break no hard rule (see marginal-lift in `eval/RESULTS.md`). Deterministic policy (9 check families) **fuses** with Gemini's injection/drift scores into a graduated verdict. Technically sound: signed hash-chained receipts verifiable offline in any language, idempotency, env-tunable thresholds, 12 s model timeout, fallback engine. Scales: stateless Cloud Run + Firestore. |
| **Problem Alignment & Impact (25%)** | Addresses an unsolved, imminent BFSI problem: UAP/AP2 prove *authorisation*, not *faithfulness*. Clear stakeholders — account holder (narrow, understandable authority), issuer/PSP (auditable controls at UPI speed), ombudsman (neutral liability attribution), agent provider (predictable contract). |
| **Innovation & Creativity (25%)** | Original framing: the **liability layer** for agentic payments, not another fraud model. Signed Decision Receipts as a dispute-settlement artifact, a red-team sandbox that shows the attack and the catch live, and an honest three-control eval that isolates what the LLM uniquely adds. |
| **User Experience & Solution Design (10%)** | One-sentence mandate authoring; one-tap step-up; a six-tab console tying sandbox → decision → receipt → dispute into one narrative; a live, in-browser tamper-evident receipt verifier. |

## Honest risks & how we address them

1. **"Is the Gen AI meaningful, or do rules do the work?"** The eval is
   deliberately honest: deterministic policy catches most attacks, and the
   semantic layer's *marginal* lift is the small set of content-steering attacks
   nothing else catches. We **lead the demo with those catches** — they are
   exactly the novel, agent-specific threat the theme is about, and the thing a
   rules-only or legacy fraud engine is blind to.
2. **Heuristic vs Gemini.** Local dev runs heuristics (no key needed); the
   judged build must run Gemini (see submission gate above).
3. **Category label.** The site's "Category Specification" asks for a label
   (Healthcare / Education / Sustainability / Accessibility / Social Good) that
   does not map onto the six themes — confirm which applies to a BFSI entry
   before submitting.
4. **Eligibility / team.** Working professionals only, 21+, JAPAC, teams of 2–4
   (only 2 travel to the finale). Confirm the team composition meets this.
5. **Repo visibility.** Private during the build; make public before the
   **18 Oct 2026** deadline if the submission form requires a public link.

## Scope honesty (unchanged)

Synthetic data only; the UPI rail is simulated; registries (I4C, DoT FRI, NPCI
verified merchants) are mocks with the right shape. `eval/RESULTS.md` from the
heuristic engine is a regression bound; the Gemini run is the independent number.
