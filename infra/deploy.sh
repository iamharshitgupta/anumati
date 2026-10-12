#!/usr/bin/env bash
# One-shot deploy: Cloud Run API + Firestore + Firebase Hosting.
# Prereqs: gcloud (authed), firebase CLI (npm i -g firebase-tools; firebase login), billing enabled.
#
#   PROJECT=my-proj REGION=asia-south1 GOOGLE_API_KEY=... ./infra/deploy.sh
#
# Use Vertex AI instead of a Gemini API key:
#   USE_VERTEX=1 PROJECT=my-proj ./infra/deploy.sh
# Before deploying: configure Firebase web config and enable Anonymous Auth.
# Google Auth is optional for approved staff accounts; see docs/AUTH.md.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-anumati-api}"
MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST_URL="https://$PROJECT.web.app"   # default Firebase Hosting site

echo "▶ project=$PROJECT region=$REGION service=$SERVICE"
gcloud config set project "$PROJECT" >/dev/null

echo "▶ enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com firebase.googleapis.com \
  identitytoolkit.googleapis.com >/dev/null

echo "▶ Firestore (native mode) — no-op if it exists"
gcloud firestore databases create --location="$REGION" --type=firestore-native >/dev/null 2>&1 || true

echo "▶ receipt signing key in Secret Manager"
if ! gcloud secrets describe anumati-receipt-key >/dev/null 2>&1; then
  openssl rand -hex 32 | gcloud secrets create anumati-receipt-key --data-file=- >/dev/null
fi
SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding anumati-receipt-key --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null

# CORS is scoped to the Hosting origin (the console is same-origin via the proxy anyway);
# override CORS_ORIGINS if you call the API directly from another browser origin.
ENV_VARS="ANUMATI_STORE=firestore,ANUMATI_AUTH_MODE=firebase,ANUMATI_ENV=production,GOOGLE_CLOUD_PROJECT=$PROJECT,GEMINI_MODEL=$MODEL,RECEIPT_KEY_ID=kms-v1,CORS_ORIGINS=${CORS_ORIGINS:-$HOST_URL}"
if [[ "${USE_VERTEX:-0}" == "1" ]]; then
  ENV_VARS="$ENV_VARS,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=$REGION"
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/aiplatform.user >/dev/null
  SECRETS="RECEIPT_SIGNING_KEY=anumati-receipt-key:latest"
else
  : "${GOOGLE_API_KEY:?set GOOGLE_API_KEY or USE_VERTEX=1}"
  # create the secret if absent, otherwise add a NEW VERSION so a rotated key is actually
  # picked up (the earlier "skip if exists" silently kept a stale key).
  if ! gcloud secrets describe anumati-gemini-key >/dev/null 2>&1; then
    printf '%s' "$GOOGLE_API_KEY" | gcloud secrets create anumati-gemini-key --data-file=- >/dev/null
  else
    printf '%s' "$GOOGLE_API_KEY" | gcloud secrets versions add anumati-gemini-key --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding anumati-gemini-key --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
  SECRETS="RECEIPT_SIGNING_KEY=anumati-receipt-key:latest,GOOGLE_API_KEY=anumati-gemini-key:latest"
fi
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/datastore.user >/dev/null
# Token revocation/disabled-account checks need user lookup, not role-edit rights.
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/firebaseauth.viewer >/dev/null

echo "▶ deploying Cloud Run (min-instances=1 so judges never hit a cold start)"
gcloud run deploy "$SERVICE" --source "$ROOT/backend" --region "$REGION" --allow-unauthenticated \
  --min-instances=1 --max-instances=5 --cpu=1 --memory=512Mi --concurrency=40 --timeout=60 \
  --set-env-vars "$ENV_VARS" --set-secrets "$SECRETS"
API_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "✔ API: $API_URL"
curl -fsS "$API_URL/healthz" && echo

echo "▶ Firebase Hosting + Firestore rules/indexes"
cd "$ROOT/web"
[[ -f .firebaserc ]] || sed "s/YOUR_GCP_PROJECT_ID/$PROJECT/" .firebaserc.example > .firebaserc
# Rewrite region/serviceId into firebase.json for the deploy, then restore the tracked
# file so the working tree is left clean (even on failure).
cp firebase.json firebase.json.orig
trap 'mv -f "$ROOT/web/firebase.json.orig" "$ROOT/web/firebase.json" 2>/dev/null || true' EXIT
sed -i.bak "s/\"region\": \"[a-z0-9-]*\"/\"region\": \"$REGION\"/g; s/\"serviceId\": \"[a-z0-9-]*\"/\"serviceId\": \"$SERVICE\"/g" firebase.json && rm -f firebase.json.bak
firebase deploy --only firestore:rules,firestore:indexes,hosting --project "$PROJECT"
echo
echo "✔ Console: $HOST_URL"
echo "✔ API:     $API_URL   (also proxied at $HOST_URL/v1/*)"
echo
echo "Firebase mode requires web/firebase-config.js and Anonymous Auth; see docs/AUTH.md."
echo "After changing the web config, redeploy hosting:"
echo "  firebase deploy --only hosting --project $PROJECT"
