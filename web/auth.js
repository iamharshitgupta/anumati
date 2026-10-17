/* Shared identity for API calls and Firestore listeners. Firebase credentials
   never fall back to demo access. Only the backend selects explicit demo mode. */

async function loadFirebase() {
  const apps = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js");
  const auth = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js");
  return { ...apps, ...auth };
}

async function firebaseSession(health, config, loadSDK) {
  if (health.auth_mode !== "firebase") throw new Error("API must declare its authentication mode; restart the updated backend.");
  if (!config.apiKey || !config.projectId || config.projectId !== health.firebase_project_id) {
    throw new Error("Firebase web configuration must match the API project.");
  }
  const sdk = await loadSDK();
  const app = sdk.getApps().find((a) => a.name === "anumati-console") || sdk.initializeApp(config, "anumati-console");
  if (app.options.projectId !== config.projectId) throw new Error("Reload the console before switching Firebase projects.");
  const auth = sdk.getAuth(app);
  await auth.authStateReady();
  return { sdk, app, auth };
}

export async function signInWithGoogle(health, config, loadSDK = loadFirebase) {
  const { sdk, auth } = await firebaseSession(health, config, loadSDK);
  return sdk.signInWithPopup(auth, new sdk.GoogleAuthProvider());
}

export async function authenticate(health, config, loadSDK = loadFirebase) {
  if (health.auth_mode === "demo") {
    return { mode: "demo", uid: "user_demo", role: "user", getToken: async () => null };
  }
  const { sdk, app, auth } = await firebaseSession(health, config, loadSDK);
  const user = auth.currentUser || (await sdk.signInAnonymously(auth)).user;
  const { claims } = await user.getIdTokenResult(true);
  const isAnonymous = user.isAnonymous;
  return {
    mode: "firebase", app, uid: user.uid, isAnonymous,
    role: !isAnonymous && ["analyst", "admin"].includes(claims.role) ? claims.role : "user",
    async getToken() {
      if (auth.currentUser?.uid !== user.uid) throw new Error("Account changed; reload the console.");
      return user.getIdToken();
    },
    signInWithGoogle: () => sdk.signInWithPopup(auth, new sdk.GoogleAuthProvider()),
    signOut() {
      if (auth.currentUser?.uid !== user.uid || auth.currentUser.isAnonymous !== isAnonymous) {
        throw new Error("Account changed; reload the console.");
      }
      return sdk.signOut(auth);
    },
    onAccountChange(callback) {
      return sdk.onAuthStateChanged(auth, (current) => {
        if (current?.uid !== user.uid || current.isAnonymous !== isAnonymous) callback();
      });
    },
  };
}

export function apiDestination(base, path, connection = {
  pageURL: globalThis.location?.href,
  configuredBase: globalThis.ANUMATI_API_BASE || "",
}) {
  const page = new URL(connection.pageURL);
  const configured = new URL(connection.configuredBase || "", page);
  const destination = new URL(base + path, page);
  const loopback = (url) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  const development = ["http:", "https:"].includes(page.protocol) && loopback(page);
  const trusted = new Set([page.origin, configured.origin]);
  if (development) {
    for (const host of ["localhost", "127.0.0.1", "[::1]"]) trusted.add(`http://${host}:8080`);
  }
  if (destination.username || destination.password || !trusted.has(destination.origin)) {
    throw new Error("API origin is not trusted; configure ANUMATI_API_BASE in firebase-config.js.");
  }
  if (destination.protocol !== "https:" && !(destination.protocol === "http:" && development && loopback(destination))) {
    throw new Error("API requests require HTTPS except for a local console and loopback API.");
  }
  return destination.href;
}

export async function requestJSON(base, path, opts = {}, identity = null, fetcher = fetch, connection) {
  // The health response and editable API field cannot grant trust to an origin.
  const destination = apiDestination(base, path, connection);
  const publicRequest = path === "/status" || path === "/sim/scenarios";
  const headers = new Headers(opts.headers);
  headers.delete("Authorization");
  headers.set("content-type", "application/json");
  if (!publicRequest) {
    if (!identity) throw new Error("Authentication is not ready.");
    if (identity.mode === "firebase") {
      headers.set("Authorization", `Bearer ${await identity.getToken()}`);
    }
  }
  const response = await fetcher(destination, {
    ...opts, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    redirect: "error", credentials: "omit",
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}
