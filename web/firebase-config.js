// Firebase web config, required when ANUMATI_AUTH_MODE=firebase (the default when
// deployed or on Firestore). Empty config works only against an explicitly local
// ANUMATI_AUTH_MODE=demo API, so the local no-login demo needs nothing here.
//
// Enable Anonymous in Firebase Authentication -> Sign-in method for visitors;
// enable Google and authorize the console's domain for optional team sign-in.
//
// projectId/authDomain are set for the deploy target (anumati-511908). The apiKey
// and appId are per-web-app values — paste them from the Firebase console:
//   Project settings → Your apps → (web app) → SDK setup and configuration.
// They MUST belong to anumati-511908, or the console's tokens will be rejected by
// the API (which verifies tokens against GOOGLE_CLOUD_PROJECT=anumati-511908).
window.ANUMATI_FIREBASE = {
  apiKey: "",
  authDomain: "anumati-511908.firebaseapp.com",
  projectId: "anumati-511908",
  appId: "",
};
// Trusted API base, configured here rather than granted trust by the header input.
// On Firebase Hosting, "" uses same-origin rewrites. Local consoles also trust
// loopback port 8080; set an explicit base here before using a different port.
// Deployed consoles ignore saved API overrides and keep the address read-only.
window.ANUMATI_API_BASE = "";
