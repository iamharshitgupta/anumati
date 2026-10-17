// Firebase web config, required when ANUMATI_AUTH_MODE=firebase (the default when
// deployed or on Firestore). Empty config works only against an explicitly local
// ANUMATI_AUTH_MODE=demo API, so the local no-login demo needs nothing here.
//
// Enable Anonymous in Firebase Authentication -> Sign-in method for visitors;
// enable Google and authorize the console's domain for optional team sign-in.
//
// Web app "Anumati Console" in project anumati-511908. The apiKey is a public
// project identifier (not a secret); restrict it to the Hosting domain under
// GCP → APIs & Services → Credentials for production hygiene.
window.ANUMATI_FIREBASE = {
  apiKey: "AIzaSyBSjYE-jArTZ4auyh1r2JidRPggzAPnP3Q",
  authDomain: "anumati-511908.firebaseapp.com",
  projectId: "anumati-511908",
  appId: "1:227794455624:web:25ddfe11bd934e28ee1c7d",
};
// Trusted API base, configured here rather than granted trust by the header input.
// On Firebase Hosting, "" uses same-origin rewrites. Local consoles also trust
// loopback port 8080; set an explicit base here before using a different port.
// Deployed consoles ignore saved API overrides and keep the address read-only.
window.ANUMATI_API_BASE = "";
