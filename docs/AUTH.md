# API Authentication and Ownership

This change adds console/API access control to the code merged in PR #8. It does
not replace the payment-risk engine, validate a bank account, or implement real
UAP/AP2 agent credentials. Every payment in this prototype still uses a simulated
rail, including requests tagged `simulated: false`.

## Three Identities

| Caller | How it starts | What it can do |
|---|---|---|
| Local demo | Auto-selected for local in-memory runs (or explicit `ANUMATI_AUTH_MODE=demo`), loopback connection, memory storage | Own `user_demo` sandbox workflow, including simulated dispute closure; no staff rights |
| Sandbox visitor | Firebase anonymous sign-in, created automatically if no session exists | Own synthetic mandate, simulations, receipts, confirmations and simulated disputes |
| Identified user / staff | Google sign-in through **Team sign-in** | Own account operations; analyst/admin permissions only after a trusted role assignment |

Anonymous is still authenticated: Firebase issues a UID and signed ID token. The
UID identifies a browser account, not a named person, genuine app installation,
bank account or trusted shopping agent. Named sign-in alone proves none of those
payment properties either. App Check and payment identity integrations are
separate concerns, not included in this change.

## Token Flow

1. The console checks the API origin against source configuration before probing
   public `/status` to learn its auth mode/project. A health response cannot grant
   trust to a different origin.
2. In Firebase mode, it loads the matching Firebase web configuration, waits for
   the existing session, and signs in anonymously only if no session exists.
3. Firebase returns the UID and ID token. The SDK persists the session and
   refreshes tokens; application code does not log or store tokens itself.
4. Protected requests send `Authorization: Bearer <Firebase ID token>` only to the
   console's origin or `ANUMATI_API_BASE` configured in `web/firebase-config.js`.
   HTTPS is required, except when both console and API are loopback addresses.
   Requests reject redirects, omit cookies and discard caller-supplied Authorization
   headers. Public probes never send a token. A session/project mismatch stops requests.
5. `current_principal()` in `backend/app/auth.py` calls Firebase Admin
   `verify_id_token(..., check_revoked=True)`: signature, expiry, issuer/project,
   revoked sessions and disabled accounts are checked before trusting UID/role.
6. Route helpers check record ownership or trusted permissions before a model
   call, history cleanup or mutation. ADC identifies the server to Google; it is
   not the caller's identity.

Missing/invalid credentials return **401**, denied ownership/role/sandbox actions
return **403**, and unavailable auth configuration returns **503**. Invalid
startup configuration stops the server before seeding. Authentication errors
never fall back to local demo permissions.

## Behaviour Changes

- Auth defaults to **Firebase**, not unauthenticated access. All `/v1/*`, simulator
  execution/session/closure routes, and `/admin/seed` require a caller.
- `/`, `/status`, `/docs`, `/openapi.json`, `/sim/scenarios` and static mock merchant
  pages remain public. They do not disclose per-visitor records or run Gemini.
- New mandates keep the existing `user_id` field, but its value comes from the
  caller's UID, ignoring a submitted user ID in every mode. The console's user
  field is read-only, including local demo. `demo_fixture` is server-assigned.
  The console sends `sandbox: true` when compiling for guests or named users.
  Named API callers may omit it to compile an ordinary mandate; guest/local
  callers are always limited to synthetic mandates. The sign/revoke flow remains.
- Signing/revoking a mandate, authorizing a payment, running/comparing a scenario,
  and approving/declining a step-up require ownership. Analyst/admin is **not**
  permission to consent to someone else's payment.
- Payment requests retain their schema: supplied `user_id` must match the caller,
  and the stored mandate must belong to that caller. A sandbox mandate requires
  `simulated: true`; an ordinary mandate requires `simulated: false`. This applies
  to named users and staff too. Anonymous/local accounts can only use the former.
  Simulator run/compare routes reject ordinary mandates before cleanup/model calls.
  A missing synthetic mandate returns 404; a mode mismatch returns 403.
  Ordinary missing-mandate requests retain the existing engine BLOCK behaviour.
  Both modes still use the stub rail, not real money.
- Ordinary list/detail reads are owner-scoped. Supplying another UID is denied.
  Analyst/admin can review other accounts through API read endpoints; list filters
  may select an account or, where omitted, return all records within existing limits.
- Idempotency lookup now includes user, mandate, agent and simulation mode as well as the key,
  preventing another account's key from returning its decision. This is not an
  atomic concurrent-payment guarantee.
- Policy budget, rate and structuring checks use only same-mode history. Legacy
  mixed-mode records are preserved but cannot influence the other execution mode.
  No changes were made to scoring weights, thresholds or step-up settlement accounting.
- Only admin can register shared agents or call `/admin/seed`. Analyst/admin can
  close disputes through `/v1/disputes/{id}/resolve`. No public role-management
  endpoint or dropdown can assign staff permissions. Anonymous staff claims are
  ignored even if accidentally assigned outside this tool.
- `/sim/session` creates one synthetic mandate per Firebase UID by copying the
  seeded template, without an extra Gemini call. Create-once storage prevents a
  refresh/race from overwriting or reactivating an existing revoked mandate.
- Different visitors get different mandates and histories. Existing `user_demo`
  data is not reassigned. A revoked visitor fixture stays revoked; an owner may
  create and sign a new mandate instead. There is no automatic reset on refresh.
- Seeding marks `mnd_demo0001` as synthetic. An existing template is classified
  only when its owner/agent match the known seed, without changing status,
  signature, expiry or history. Other old mandates are not automatically converted;
  create/sign a new sandbox mandate rather than editing database flags manually.
- Sandbox disputes retain merchant/issuer/agent-provider role-play labels without
  granting those permissions. Their owner can use `/sim/disputes/{id}/resolve`
  only for a dispute tied to their own server-marked synthetic fixture. Non-sandbox
  party attribution/closure remains staff-controlled.
- Step-up records and receipt confirmation addenda record `responded_by` / `by`;
  disputes record `raised_by_uid`, `resolved_by`, ownership, simulation and resolution
  scope. Signed receipt bodies/algorithms are unchanged; confirmation is still an
  addendum outside the original signature.
- The console uses the same Firebase session for API and Firestore reads, disables
  protected actions during setup, and clears private views when switching accounts.
  Failed realtime listeners use authenticated API polling, never unauthenticated
  access. Identity mismatch, sign-in and configuration errors are visible.
- After a session/setup failure, **Team sign-in** remains available only when the
  trusted API health and Firebase configuration identify the same project. It can
  open Google sign-in without refreshing the failed old token first. Protected
  actions remain disabled until authentication and console setup succeed again;
  cancelling/failing the popup does not fall back to anonymous or local demo access.
- Deployed consoles ignore saved API overrides and show a read-only API address.
  Local consoles may select the current console origin, their configured API
  origin, or HTTP port 8080 on localhost/127.0.0.1/[::1]. Other ports/origins require
  changing `ANUMATI_API_BASE` in the source config and reloading. Typing a URL or
  receiving a matching project ID does not authorize token delivery to that URL.
- **Team sign-in** switches to a Google account. A named session survives browser
  reloads/repeat sign-in; **Sign out** starts a new anonymous visitor session. This
  switches identities, rather than linking/migrating the previous anonymous data.
- Anonymous visitors can select **New demo session** after confirmation. This
  signs out locally and creates a new visitor UID without disabling/deleting the
  old account or changing its records. An unlinked anonymous identity cannot
  normally be recovered after sign-out. Private views/listeners are cleared
  before switching; other tabs sharing the Firebase session clear their private
  views and require a refresh. Cancellation changes nothing. Sign-out does not
  revoke already-issued tokens; server-side revocation remains a separate action.
- Browser Firestore rules allow only owner reads on the five console collections,
  deny all writes and default-deny other collections. Staff cross-account reads
  use the API, where revocation is checked; cached browser role claims cannot grant
  such access. Owner reads may still last until an existing ID token expires after
  revocation; no custom Firestore revocation metadata has been added.
- Six query indexes were added to the existing seven: scoped receipt/dispute/all-
  status-step-up reads, pending simulation cleanup and scoped idempotency. The
  generic setup script still reads `web/firestore.indexes.json`; no cloud indexes
  have been changed by this code edit.
  The idempotency definition now includes `request.simulated`; the manifest still
  has 13 indexes, but this replacement definition must be applied before cloud use.
- Cloud Run deployment settings explicitly select Firebase/production and grant
  runtime `roles/firebaseauth.viewer` for revocation/user lookup, not role editing.
  Public Cloud Run transport remains necessary for Firebase visitors; the API
  itself checks tokens. Local demo/emulator auth is rejected on Cloud Run or when
  `ANUMATI_ENV=production`.
- PR #8's receipt verifier, baselines, engine comparison, evidence panels and all
  eight scenarios remain. The guided demo now clears simulated decisions only at
  its first clean step, so later steps can still dispute the earlier blocked decision.
  Long mandate identifiers wrap/fit in mobile layouts.

## Local Setup, No Cloud Needed

From the repository root, using the existing virtual environment:

```bash
env/bin/python -m pip install -r backend/requirements.txt
cd backend
ANUMATI_STORE=memory ANUMATI_GEMINI=false \
  ../env/bin/python -B -m uvicorn app.main:app --port 8080
```

The local in-memory build selects demo auth automatically (see
`config._default_auth_mode`), so no `ANUMATI_AUTH_MODE` is needed — Uvicorn binds
loopback by default and demo mode rejects non-loopback callers regardless. Set
`ANUMATI_AUTH_MODE=firebase` to require real tokens locally, or `=demo` to force
the no-login path. Any deployed (`K_SERVICE`), `ANUMATI_ENV=production`, or
Firestore-backed run switches to Firebase automatically and never accepts demo.

In another terminal, from the repository root:

```bash
env/bin/python -B -m http.server 5173 --bind 127.0.0.1 --directory web
```

Open `http://localhost:5173`. Health/console should show `auth: local demo`. This
mode grants only `user_demo` ownership, not admin/analyst access. It cannot reseed
through `/admin/seed`, register shared agents, or read/change another account's data.
Startup seeding supplies the demo fixtures. Simulated dispute closure remains
available through `/sim/disputes/{id}/resolve` without staff impersonation.

Local no-login mode rejects Firestore storage before creating a store or seeding,
including a Firestore emulator: use Firebase mode for persisted storage testing.
Forwarding headers, non-loopback peers/Host headers and non-loopback browser origins
are rejected. A proxy can strip forwarding metadata, so do not expose this mode
through a tunnel/public reverse proxy or bind it to `0.0.0.0`; use `--no-proxy-headers`.
It is a memory-only development convenience, not proof of who is using the browser.
Memory data disappears on restart. Gemini can still be explicitly enabled and incur
model usage; `ANUMATI_GEMINI=false` above keeps this setup cloud-free.

## Firebase Setup, Including a Local API

Auth providers/rules are configured manually; startup seeding still writes demo
data when enabled. Before switching the backend:

1. In the intended Firebase project, enable **Authentication -> Sign-in method ->
   Anonymous**. Enable Google for identified/team sign-in and configure the
   provider's support email. Add `localhost` and the deployed console domain to
   Authentication's authorized domains as needed.
2. Register/reuse a Firebase web app under project settings; fill
   `web/firebase-config.js` with its web configuration. These client identifiers
   are not Admin/service-account credentials. Never put ADC or private keys there.
3. Ensure local ADC targets the same project and has Firebase Auth user-read rights
   for revoked/disabled-account checks. Your existing Firestore/Gemini permissions
   remain separate. Start the updated API with Firebase mode:

```bash
cd backend
GOOGLE_CLOUD_PROJECT=anumati-511908 ANUMATI_AUTH_MODE=firebase \
  ../env/bin/python -B -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Retain your established `ANUMATI_STORE` and Gemini environment settings when you
want cloud storage/model calls. Set `ANUMATI_STORE=memory ANUMATI_GEMINI=false` to
isolate auth testing; Firebase authentication itself still contacts Firebase.

Before deployed realtime testing, apply the updated rules and indexes deliberately:

```bash
env/bin/python -B infra/firestore_indexes.py --project anumati-511908 --apply --wait
cd web
firebase deploy --only firestore:rules --project anumati-511908
```

These commands **change cloud configuration**; they are instructions, not commands
run as part of this change. The manifest now contains 13 indexes. The deployment
script performs these steps as well; it has not been run, and its existing minimum
Cloud Run instance still has cost implications. Authentication is not an AI quota
or cost cap; the public synthetic demo still needs an agreed abuse/cost policy.

## Assign Repeatable Staff Permissions

1. The teammate uses **Team sign-in** once. Initially they have ordinary user rights.
2. A trusted administrator confirms their named account and copies its UID from
   Firebase Authentication -> Users. Do not approve roles based only on a supplied
   display name or anonymous UID.
3. From a trusted terminal with Firebase Auth user-edit permissions, preview:

```bash
env/bin/python -B infra/firebase_roles.py \
  --project anumati-511908 --uid ACTUAL_FIREBASE_UID --role analyst
```

4. After confirming account/project, add `--apply` to set the claim and revoke old
   sessions. The tool rejects unverified/anonymous staff accounts, preserves other
   custom claims, and accepts `--role user` to remove the staff role. Assign one
   user's claims at a time. Sign out and sign in again afterward.

The named Firebase account/UID persists, so the same teammate can return later with
the same role. This grants an application role, not Google Cloud IAM access. No
backoffice GUI or account-creation endpoint was added. Anonymous-account cleanup
is separate from deleting its Firestore data; neither is automated here. Preserve
judging data throughout evaluation.

## Tests

Normal tests use memory storage and disabled Gemini. Token tests include real SDK
signature/project/expiry/revocation checks against local test keys and mocked user
lookup, not a live cloud account:

```bash
env/bin/python -B -m pytest tests -q -p no:cacheprovider
node --test tests/test_web_auth.mjs tests/test_web_auth_recovery.mjs
```

Optional Firestore rules tests require Firebase CLI, Node and Java 21+. Install
test-only dependencies outside the repository and run against a fake project:

```bash
RULES_DEPS=$(mktemp -d)
npm install --prefix "$RULES_DEPS" --ignore-scripts --no-audit --no-fund \
  @firebase/rules-unit-testing@5 firebase@12
NODE_PATH="$RULES_DEPS/node_modules" firebase emulators:exec \
  --config firebase.test.json --only firestore --project demo-anumati \
  'node --test tests/test_firestore_rules.cjs'
```

The tests require the configured loopback emulator port, deny foreign/unscoped
reads and all browser writes, and never select a live project. Emulator rule tests
do not prove deployed index readiness or live Google sign-in configuration.

## Intentionally Unchanged / Remaining Limits

- Risk scoring, category matching, mandate compiler prompts, policy checks,
  synthetic attack content and stubbed agent credentials are unchanged, apart
  from partitioning policy history by simulation mode.
- Existing mandate signing still accepts guardrail overrides and records a
  confirmation hash; it is not a bank/device-bound signature. Full lifecycle/cap
  validation, step-up TTL enforcement and atomic budget/payment accounting remain
  separate work. This change must not be described as real-payment production readiness.
- Existing shared `user_demo` records are not migrated to Firebase UIDs. Old disputes
  lacking `user_id` are staff-readable through the API, not ordinary visitor data.
- Live Firebase provider/config/rules/index setup and named staff assignment still
  require deliberate operator actions. Nothing here commits, pushes or deploys them.

References: [ID token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens),
[custom claims](https://firebase.google.com/docs/auth/admin/custom-claims),
[anonymous authentication](https://firebase.google.com/docs/auth/web/anonymous-auth),
[anonymous identity boundaries](https://firebase.blog/posts/2023/07/best-practices-for-anonymous-authentication/),
[rule testing](https://firebase.google.com/docs/rules/unit-tests).
