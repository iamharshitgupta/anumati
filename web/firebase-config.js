// Firebase web config, required when ANUMATI_AUTH_MODE=firebase (the default).
// Empty config works only against an explicitly local ANUMATI_AUTH_MODE=demo API.
// Enable Anonymous in Firebase Authentication -> Sign-in method for visitors;
// enable Google and authorize the console's domain for optional team sign-in.
//
// Firebase console → Project settings → Your apps → SDK setup and configuration.
window.ANUMATI_FIREBASE = {
  apiKey: "AIzaSyCC1I6yOYAZss6kRg74kYC4KcdPi_YBuqA",
  authDomain: "anumati-511213.firebaseapp.com",
  projectId: "anumati-511213",
  appId: "1:437712036451:web:5965ee1464fe7ab8c00e56",
};
// Trusted API base, configured here rather than granted trust by the header input.
// On Firebase Hosting, "" uses same-origin rewrites. Local consoles also trust
// loopback port 8080; set an explicit base here before using a different port.
// Deployed consoles ignore saved API overrides and keep the address read-only.
window.ANUMATI_API_BASE = "";
