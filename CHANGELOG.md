# Changelog

All notable changes to Anumati are recorded here. The repository history is organised
as an initial import of the build *as received*, followed by one commit per review
theme, so the before/after of every change is visible in `git log` and `git diff`.

## [0.6.0] — Go-live hardening: Firebase authentication and owner-scoped permissions

Makes the gateway safe to expose on a public Cloud Run endpoint. Until now the API
trusted a client-supplied `user_id` and had no authentication, so anyone could act
as anyone and read any account's receipts — a non-starter for a live payment
gateway. This release adds real identity and ownership without breaking the
one-command local demo.

### Identity & permissions
- **Firebase ID-token auth** on every protected route: tokens are verified for
  signature, expiry, project, revocation and disabled-account status. Account
  ownership now comes from the verified Firebase UID, never from a submitted
  `user_id`.
- **Owner-scoped everything** — mandates, payments, simulations, decisions,
  receipts and step-ups are scoped to their owner. Trusted custom claims identify
  `analyst`/`admin`; ordinary and anonymous accounts are `user`. Staff may *read*
  across accounts for review but **cannot** approve another user's STEP_UP, and
  claims are assigned out-of-band (`infra/firebase_roles.py`), never through the UI.
- **Admin-gated operations**: `/admin/seed` and shared agent registration now
  require an `admin` claim.
- **Public demo still works for visitors**: `/sim/session` mints a per-visitor
  *synthetic* sandbox mandate (a copy of the demo fixture, owned by the caller's
  UID), so an anonymous judge can run the whole red-team sandbox on the live site
  without ever touching another account's data.

### Zero-config local demo (the DX refinement)
- The local in-memory build now **auto-selects the no-login demo path** — plain
  `uvicorn app.main:app` just works, scoped to the synthetic demo user,
  loopback-only. No `ANUMATI_AUTH_MODE`, no `--host`, no `--no-proxy-headers`.
- The demo path is **refused whenever deployed** (`K_SERVICE`), in
  `ANUMATI_ENV=production`, or on any Firestore-backed run — those always require a
  verified Firebase token. Forwarded headers and non-loopback origins/hosts are
  rejected; startup `validate_auth_configuration()` fails fast on a misconfig.

### Security-review hardening
- **Refuse to boot with the dev receipt key when deployed**: `validate_auth_configuration()`
  now raises if a deployed service still has the default `RECEIPT_SIGNING_KEY`, so the
  liability-bearing Decision Receipts can never be signed with a world-known HMAC key.
- **Gemini cost guardrail**: a process-wide per-minute and total call cap sits in front
  of every model call (`gemini.py`). Since every Gemini path has a heuristic fallback,
  exceeding a cap degrades gracefully instead of spending — bounding credit burn from a
  scripted caller hammering `/sim/compare` or `/sim/run?mode=gemini` behind free anonymous
  tokens. Env-tunable (`GEMINI_MAX_CALLS_PER_MIN`, `GEMINI_MAX_CALLS_TOTAL`).
- **Defense-in-depth id validation** on body-supplied `decision_id` (reject empty / `/`),
  matching the sandbox mandate-id check.
- Reviewed and confirmed safe: no authN bypass, no anonymous→staff escalation, no
  cross-user IDOR on any router, demo mode unreachable when deployed, owner-scoped
  Firestore rules, and token attachment limited to trusted origins.

### Frontend & rules
- Console signs in with Firebase (anonymous for the public demo; Google for
  identified/team accounts) and attaches the ID token **only** to trusted origins
  (page origin or the source-configured API origin) — never to an arbitrary
  address typed into the console.
- `web/firestore.rules` switched to the **owner-scoped** ruleset (per-document
  reads by `user_id`, all browser writes denied).
- `deploy.sh`, README and `docs/AUTH.md` document the token model; new
  `docs/GO_LIVE.md` is the pre-deploy checklist.

## [0.5.0] — Integration: evidence chain, baseline comparison, Firestore index tooling

Integrates the contributed demo and infrastructure work on top of the review
stack (0.2.0–0.4.0), reconciling overlaps so the console has exactly one receipt
verifier and one guided demo.

### Sandbox & console
- **Evidence-chain panel** on the sandbox result: quotes the injection/intent-drift
  findings verbatim and offers "Locate in merchant content" to jump to the exact
  span in the (hidden or visible) page text. Quoted content is rendered as text
  only and labelled untrusted.
- **"How other controls would decide"** — every `/sim/run` now returns a
  per-attempt `baseline_comparisons` block (caps-only, policy-only), rendered as a
  three-row table (Caps-only / Policy-only / Anumati) so the marginal value of the
  policy and semantic layers is visible inline, on the same request. This
  complements the Gemini-vs-heuristic compare (0.4.0), which isolates the Gen-AI
  layer specifically.
- **Richer Step-ups tab**: each pending confirmation now shows the triggering
  mandate rule, the requested basket, the risk reasons, and an outcome banner;
  buttons disable while a response is in flight.
- **Fixed stale step-up accumulation**: a fresh sandbox run now clears the pending
  *simulated* step-ups tied to the decisions it resets, so the Step-ups tab no
  longer carries confirmations from a previous scenario.
- `127.0.0.1` is now treated as a local host for the default API base, alongside
  `localhost` and `file:`.
- Reconciled two parallel implementations: kept the browser-side, offline receipt
  verifier (0.2.0) over a server-round-trip variant, and the auto-playing 7-beat
  guided demo (0.3.0) over a lighter manual walkthrough — dropping the duplicates
  so there is a single verifier and a single demo.

### Infrastructure
- Added `infra/firestore_indexes.py` and `tests/test_firestore_indexes.py` — a
  programmatic definition and test of the composite indexes the Firestore backend
  needs, alongside the `web/firestore.indexes.json` that `deploy.sh` ships.

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

## [0.2.1] — Theme & rubric alignment

- Added `docs/THEME_ALIGNMENT.md`: validates Anumati against the AI Builder Cup
  2026 BFSI track, the required technology (Gemini/Gemma + Cloud Run/Firebase),
  and the judging rubric (Technical/Gen-AI 40%, Problem/Impact 25%, Innovation
  25%, UX 10%), with an evidence map per criterion and an honest list of risks
  (Gen-AI weighting, heuristic-vs-Gemini judged build, category label,
  eligibility, repo visibility).
- `docs/SUBMISSION.md`: corrected the repo-visibility note (private during the
  build, make public before the deadline), added the judging criteria and
  weights, and expanded the pre-submission checklist (Gemini build, category
  label, eligibility).

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
