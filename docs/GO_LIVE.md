# Go-live checklist — Anumati on Google Cloud

Everything needed to take the gateway from the local demo to a judge-ready public
deployment. Steps marked **(you)** need a Google account and cannot be scripted
from inside this repo; the rest is already wired into `infra/deploy.sh`.

## 0 · What "live" means here

One command — `infra/deploy.sh` — deploys the FastAPI gateway to Cloud Run,
provisions Firestore (native mode), stores the signing/Gemini keys in Secret
Manager, and publishes the console on Firebase Hosting with the Cloud Run API
proxied behind it. The API is `--allow-unauthenticated` at the Cloud Run layer but
**authenticated at the application layer** (Firebase ID tokens), so the public
endpoint is safe: callers are identified and every record is owner-scoped.

## 1 · Prerequisites **(you)**

Target project: **`anumati-511908`** · deploy account: **`harshitunderscore@gmail.com`**

- [ ] `gcloud auth login harshitunderscore@gmail.com` — I cannot sign in to Google for you.
- [ ] Confirm billing is enabled on `anumati-511908`.
- [ ] `npm i -g firebase-tools && firebase login`.
- [ ] A Gemini key: either `GOOGLE_API_KEY` from AI Studio **or** `USE_VERTEX=1`
      (Vertex AI via ADC). The Gen-AI criterion is scored on the Gemini build, so
      do not skip this for the judged deploy.

## 2 · Firebase Authentication **(you)**

- [ ] Firebase console → Authentication → **enable Anonymous** (lets judges run the
      public sandbox) and **Google** (for identified/team accounts).
- [ ] Project settings → Your apps → (register a web app if none) → copy the
      `apiKey` and `appId` into `web/firebase-config.js`. `projectId` and
      `authDomain` are already set to `anumati-511908`; the key/appId MUST belong to
      that same project or the API will reject the console's tokens.
- [ ] Assign staff roles out-of-band (never in the UI):
      `python infra/firebase_roles.py --project anumati-511908 --uid <uid> --role analyst|admin`.
      Ordinary visitors default to `user`; only trusted claims grant analyst/admin.

## 3 · Deploy

```bash
PROJECT=anumati-511908 REGION=asia-south1 GOOGLE_API_KEY=<gemini key> ./infra/deploy.sh
#   or: USE_VERTEX=1 PROJECT=anumati-511908 ./infra/deploy.sh
```

The script: enables APIs → creates Firestore → generates the receipt HMAC key in
Secret Manager (never a hardcoded key in prod) → deploys Cloud Run
(`ANUMATI_STORE=firestore`, `min-instances=1` so judges never hit a cold start,
CORS scoped to the Hosting origin) → deploys Firestore rules + indexes + Hosting →
prints both URLs. On Cloud Run `K_SERVICE` is set, so auth is Firebase automatically
and the no-login demo path can never activate.

## 4 · Verify the live deployment

- [ ] `curl https://<api-url>/status` → `"auth_mode":"firebase"`,
      `"store":"firestore"`, and `"semantic_engine":"gemini"` (confirms the judged
      Gen-AI build, not heuristics).
- [ ] Unauthenticated `POST /v1/payments/authorize` → **401** (auth is enforced).
- [ ] Open the Hosting URL, sign in anonymously, run the **▶ Guided demo** end to
      end: mandate → approve → block → step-up decline → dispute → tamper-proof
      receipt. The sandbox runs against a per-visitor synthetic mandate via
      `/sim/session`, so it works without touching any real account.
- [ ] Open a decision receipt and tamper the amount → signature flips to INVALID
      offline (the dispute artifact still verifies without trusting the server).

## 5 · Security posture at go-live

- Identity: verified Firebase ID tokens (signature/expiry/project/revocation);
  ownership from the UID, not request bodies.
- Authorization: owner-scoped reads/writes; staff read-only across accounts;
  admin-only seed/agent registration; anonymous visitors limited to synthetic
  sandbox payments.
- Firestore: owner-scoped reads, all browser writes denied (writes go through the
  Admin SDK on Cloud Run).
- Secrets: receipt HMAC key and Gemini key in Secret Manager; the signing key is
  swappable for Cloud KMS without changing the receipt format.
- Data: synthetic only — nothing touches a real UPI rail.

## 6 · Before the submission deadline (2026-10-18) **(you)**

- [ ] Run a Gemini eval (`eval/run_eval.py`) on the deployed build and refresh
      `eval/RESULTS.md`.
- [ ] Make the repository public.
- [ ] Re-export any stale `docs/PRD.pdf`.
