// Firebase web config. Leave `apiKey` empty to run the console against the API
// alone (polling). Fill it in to enable Firestore realtime listeners for step-ups
// and the decision feed, plus anonymous auth.
//
// Firebase console → Project settings → Your apps → SDK setup and configuration.
window.ANUMATI_FIREBASE = {
  apiKey: "",
  authDomain: "",
  projectId: "",
  appId: "",
};
// Default API base (overridable in the header input). On Firebase Hosting this is
// rewritten to the Cloud Run service via firebase.json, so "" (same origin) works.
window.ANUMATI_API_BASE = "";
