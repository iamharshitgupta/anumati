# Changelog

All notable changes to Anumati are recorded here. The repository history is organised
as an initial import of the build *as received*, followed by one commit per review
theme, so the before/after of every change is visible in `git log` and `git diff`.

## [0.4.0] — Gemini vs heuristic side-by-side

Makes the Gen-AI layer's contribution visible and measurable — directly serving
the rubric's 40%-weighted "meaningful use of Gen AI" criterion.

- **New `POST /sim/compare`** (read-only): runs one scenario's payment through
  **both** semantic engines — the deterministic heuristic and Gemini — against
  the *same* deterministic policy and the *same* page content, and returns each
  engine's injection/drift scores, reasons, verbatim injected text, and the
  verdict each would yield. Persists nothing. When no Gemini key is configured,
  the `gemini` arm is `null` and `gemini_available` is `false`.
- **New "⚖ Gemini vs heuristic" button** in the sandbox renders the two engines
  side by side with score bars and reasons, and a verdict note that calls out
  agreement, disagreement, or (locally) how to enable Gemini.
- Refactored `semantic.py` into `heuristic_analyse()` and `gemini_analyse()`
  (Gemini-only, returns `None` on absence/failure); `analyse()` is now
  `gemini_analyse(...) or heuristic_analyse(...)` — same production behaviour,
  but each engine is independently callable.
- Added a test asserting the comparison is read-only and that the heuristic arm
  blocks the hidden-injection scenario while the Gemini arm is null in CI.

## [0.3.0] — One-click guided demo walkthrough

- **New "▶ Guided demo" button** in the console header. It drives the *real*
  console through the canonical story end to end (PRD §4/§8), narrating each beat
  in a bottom bar and highlighting the live card:
  1. **The mandate** — authorisation vs faithfulness.
  2. **Clean run → APPROVE** (verified payee, receipt issued).
  3. **Hidden-text redirect → BLOCK** (unverified payee + suspect registry +
     injected text captured verbatim).
  4. **Review injection → STEP_UP → declined** in one tap.
  5. **Dispute → liability attribution** (replays the signed receipt; lands on
     merchant/content provider).
  6. **Tamper-proof evidence** — auto-tampers the blocked receipt and the HMAC
     breaks on screen.
  7. **Recap.**
- Auto-plays with **Pause / Next / Exit / Replay** controls and a progress
  indicator. Each step chains the next by capturing real decision / receipt /
  step-up ids returned by the API — nothing is faked.
- Driver is **re-entrancy-guarded**: a step in flight ignores further
  advance clicks and disables Next, so fast clicking or clashing with auto-play
  can't fire overlapping API calls (the cause of a transient dispute-step 404
  during development).
- Refactored the receipt tamper action into a reusable `tamperReceiptAmount()`
  so the walkthrough and the manual button share one code path.
- `DEMO_SCRIPT.md` notes the one-click walkthrough as the fastest way to show
  the full story; README quick-start points to the button.

## [0.2.0] — Tamper-evident receipt verifier

Makes PRD §8's "a tampered receipt fails verification **on stage**" a one-click
demo, and fixes a correctness bug that quietly broke the receipt's core promise.

### Console
- New **interactive receipt verifier** in the Receipts tab. Opening a receipt
  loads it into an editable panel and verifies it live (`signature valid ✅`).
  Judges can edit any field by hand, hit **Verify signature**, and watch the
  HMAC break; a one-click **Tamper the amount →** does it for them, and **Reset
  to original** restores the signed copy. The result banner explains the outcome
  in dispute terms ("a dispute party would reject it").

### Receipts (correctness)
- **Fixed cross-language canonicalisation.** The signed body contained
  integer-valued floats (`2000.0`, `1041.0`); Python's `json.dumps` emits
  `2000.0` where JavaScript's `JSON.stringify` emits `2000`, so a receipt signed
  by the gateway **failed to verify in any non-Python verifier** (including the
  browser console) — silently breaking the "verifiable offline by any party"
  guarantee (PRD NFR §6). `canonical()` now normalises integer-valued floats to
  integers before hashing, so the canonical form is identical across languages.
  Signing and verification use the same normalisation, so the chain stays intact.
- Added a regression test that re-serialises a receipt the way a browser would
  (collapsing `2000.0 → 2000`) and asserts it still verifies.

## [0.1.1] — Review pass

A correctness, honesty and hardening pass over the initial build. No feature was
removed; the decision engine's behaviour is unchanged except where noted.

### Evaluation (credibility)
- Added a **fair deterministic-policy baseline** (`baseline_policy_only` in
  `backend/app/engine.py`) alongside the existing caps-only control. It runs the full
  policy engine with the semantic layer switched off, is read-only (never persists a
  decision or receipt), and lets the suite isolate the **marginal lift** the semantic
  auditor adds over rules alone.
- Added **4 hard negatives** to `eval/build_cases.py`: legitimate orders that look
  risky but must not be flagged (just under the step-up line; a high-but-legal
  quantity of 8; a benign page with promo/urgency wording; a near-cap order at the
  second allowed merchant). The suite grew from 40 → **44 cases (25 attack / 19 benign)**.
- `eval/run_eval.py` now computes both baselines read-only *before* each decision is
  persisted (so structuring sequences are scored fairly), reports three controls side
  by side, names the attacks only the semantic layer catches, and stamps `RESULTS.md`
  with an explicit regression-suite caveat.
- Honest heuristic-engine result: **Anumati 100% / policy-only 92% / caps-only 12%**
  attacks flagged, **0% false flags** across all pass-benign cases including the hard
  negatives. The semantic layer's unique contribution is **2 of 25 attacks**
  (content-driven upsell/quantity pressure that violates no hard rule).

### Mandate compiler
- The compiler now recognises the demo merchant ("freshkart") and the phrase
  "never pay a new payee", so the heuristic compile of the demo mandate is correct.
- The demo mandate's weekly cap was lowered from ₹6,000 to ₹3,000 so it respects the
  ₹15,000/month UPI Circle ceiling (₹6,000/week ≈ ₹25,800/month exceeded it).
- `seed.py` now runs the real compiler and only reconciles against sandbox invariants
  as a no-op safety net, instead of unconditionally overwriting the compiler output.

### API
- Replaced the deprecated `@app.on_event("startup")` hook with a lifespan handler.

### Security & infra
- `web/firestore.rules`: documented the demo's anonymous-read exposure explicitly and
  shipped a ready-to-enable production per-user ruleset. All writes remain blocked.
- `infra/deploy.sh`: CORS scoped to the Hosting origin instead of `*`; a rotated
  `GOOGLE_API_KEY` now adds a new Secret Manager version instead of being silently
  ignored; `firebase.json` is restored after deploy so the working tree stays clean.

### Docs
- PRD (both copies), README, architecture, demo script and submission pack updated to
  the honest eval framing and the new case counts.

## [0.1.0] — Initial import

The build as received: FastAPI gateway (mandate compiler, policy engine, semantic
audit, receipts, disputes, red-team sandbox), Firebase Hosting console, 40-case eval
suite with a caps-only baseline, one-shot deploy script, and full docs. Built for
AI Builder Cup 2026, BFSI track.
