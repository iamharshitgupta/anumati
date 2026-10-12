import test from "node:test";
import assert from "node:assert/strict";
import { apiDestination, authenticate, requestJSON, signInWithGoogle } from "../web/auth.js";

const config = { apiKey: "test", projectId: "demo-anumati" };
const health = { auth_mode: "firebase", firebase_project_id: config.projectId };
const connection = { pageURL: "https://console.example/index.html", configuredBase: "https://api.example" };

function fixture(existing = false) {
  let signIns = 0, signOuts = 0, googleSignIns = 0, token = "first-token";
  const listeners = new Set();
  const user = { uid: "alice", isAnonymous: !existing,
    getIdTokenResult: async () => ({ claims: { role: existing ? "analyst" : "user" } }),
    getIdToken: async () => token };
  const auth = { currentUser: existing ? user : null, authStateReady: async () => {} };
  const setUser = (current) => {
    auth.currentUser = current;
    for (const listener of listeners) listener(current);
  };
  const app = { name: "anumati-console", options: config };
  const sdk = { getApps: () => [], initializeApp: () => app, getAuth: () => auth,
    GoogleAuthProvider: class {},
    signInWithPopup: async () => {
      googleSignIns++;
      const current = { ...user, uid: "google-user", isAnonymous: false,
        getIdTokenResult: async () => ({ claims: {} }) };
      setUser(current); return { user: current };
    },
    signInAnonymously: async () => {
      signIns++;
      const current = signIns === 1 ? user : { ...user, uid: `alice-${signIns}` };
      setUser(current); return { user: current };
    },
    signOut: async () => { signOuts++; setUser(null); },
    onAuthStateChanged: (_, listener) => {
      listeners.add(listener);
      queueMicrotask(() => { if (listeners.has(listener)) listener(auth.currentUser); });
      return () => listeners.delete(listener);
    },
  };
  return { sdk, auth, user, setUser, signIns: () => signIns, signOuts: () => signOuts,
    googleSignIns: () => googleSignIns,
    changeToken: () => { token = "refreshed-token"; } };
}

test("explicit demo mode never loads Firebase", async () => {
  const identity = await authenticate({ auth_mode: "demo" }, {}, () => { throw new Error("Firebase loaded"); });
  assert.equal(identity.uid, "user_demo"); assert.equal(identity.role, "user");
  assert.equal(await identity.getToken(), null);
});

test("missing mode or wrong project fails before loading SDK", async () => {
  const fail = () => { throw new Error("SDK should not load"); };
  await assert.rejects(authenticate({}, config, fail), /authentication mode/);
  await assert.rejects(authenticate(health, { ...config, projectId: "wrong" }, fail), /match/);
});

test("anonymous signup happens only if no persisted user exists", async () => {
  const f = fixture();
  assert.equal((await authenticate(health, config, async () => f.sdk)).uid, "alice");
  await authenticate(health, config, async () => f.sdk);
  assert.equal(f.signIns(), 1);
});

test("existing identified user keeps their verified role and session", async () => {
  const f = fixture(true);
  const identity = await authenticate(health, config, async () => f.sdk);
  assert.equal(identity.role, "analyst"); assert.equal(f.signIns(), 0);
});

test("anonymous users cannot display staff permissions even with a role claim", async () => {
  const f = fixture();
  f.user.getIdTokenResult = async () => ({ claims: { role: "admin" } });
  assert.equal((await authenticate(health, config, async () => f.sdk)).role, "user");
});

test("Firebase signup errors never downgrade to demo", async () => {
  const f = fixture(); f.sdk.signInAnonymously = async () => { throw new Error("provider disabled"); };
  await assert.rejects(authenticate(health, config, async () => f.sdk), /provider disabled/);
});

test("Google recovery does not refresh a revoked user before opening sign-in", async () => {
  const f = fixture(true);
  let oldTokenReads = 0;
  f.user.getIdTokenResult = async () => { oldTokenReads++; throw new Error("auth/user-token-expired"); };
  await assert.rejects(authenticate(health, config, async () => f.sdk), /user-token-expired/);
  const result = await signInWithGoogle(health, config, async () => f.sdk);
  assert.equal(result.user.uid, "google-user");
  assert.equal(oldTokenReads, 1);
  assert.equal(f.signIns(), 0); assert.equal(f.googleSignIns(), 1);
  const identity = await authenticate(health, config, async () => f.sdk);
  assert.equal(identity.uid, "google-user"); assert.equal(identity.role, "user");
});

test("Google recovery validates mode, configuration and existing app project", async () => {
  const fail = () => { throw new Error("SDK should not load"); };
  await assert.rejects(signInWithGoogle({ auth_mode: "demo" }, config, fail), /authentication mode/);
  await assert.rejects(signInWithGoogle(health, {}, fail), /match/);
  await assert.rejects(signInWithGoogle(health, { ...config, projectId: "wrong" }, fail), /match/);
  const f = fixture();
  f.sdk.getApps = () => [{ name: "anumati-console", options: { projectId: "wrong" } }];
  await assert.rejects(signInWithGoogle(health, config, async () => f.sdk), /Reload/);
  assert.equal(f.googleSignIns(), 0); assert.equal(f.signIns(), 0);
});

test("cancelled Google recovery preserves the session without anonymous fallback", async () => {
  const f = fixture(true);
  f.sdk.signInWithPopup = async () => { throw new Error("auth/popup-closed-by-user"); };
  await assert.rejects(signInWithGoogle(health, config, async () => f.sdk), /popup-closed/);
  assert.equal(f.auth.currentUser, f.user); assert.equal(f.signIns(), 0);
});

test("sign-out followed by startup creates a new anonymous UID without modifying the old user", async () => {
  const f = fixture();
  const old = await authenticate(health, config, async () => f.sdk);
  await old.signOut();
  assert.equal(f.auth.currentUser, null);
  const current = await authenticate(health, config, async () => f.sdk);
  assert.notEqual(current.uid, old.uid); assert.equal(current.isAnonymous, true);
  assert.equal(f.user.uid, "alice"); assert.equal(f.user.isAnonymous, true);
  assert.equal(f.signOuts(), 1); assert.equal(f.signIns(), 2);
  await assert.rejects(old.getToken(), /Account changed/);
});

test("stale identities cannot sign out a changed account", async () => {
  const f = fixture(), identity = await authenticate(health, config, async () => f.sdk);
  for (const current of [{ ...f.user, uid: "bob" }, null, { ...f.user, isAnonymous: false }]) {
    f.setUser(current);
    assert.throws(() => identity.signOut(), /Account changed/);
    assert.equal(f.auth.currentUser, current);
  }
  assert.equal(f.signOuts(), 0);
});

test("sign-out errors leave the existing account intact", async () => {
  const f = fixture(), identity = await authenticate(health, config, async () => f.sdk);
  f.sdk.signOut = async () => { throw new Error("sign-out unavailable"); };
  await assert.rejects(identity.signOut(), /sign-out unavailable/);
  assert.equal(f.auth.currentUser, f.user); assert.equal(f.signIns(), 1);
});

test("account-change subscription ignores the same session and can be stopped", async () => {
  const f = fixture(), identity = await authenticate(health, config, async () => f.sdk);
  let changes = 0;
  const stop = identity.onAccountChange(() => changes++);
  await Promise.resolve();
  f.setUser({ ...f.user }); assert.equal(changes, 0);
  f.setUser({ ...f.user, uid: "bob" }); assert.equal(changes, 1);
  f.setUser(null); assert.equal(changes, 2);
  stop(); f.setUser(f.user); assert.equal(changes, 2);
});

test("linking an anonymous identity to a named account invalidates its old session", async () => {
  const f = fixture(), identity = await authenticate(health, config, async () => f.sdk);
  let changes = 0;
  const stop = identity.onAccountChange(() => changes++);
  f.user.isAnonymous = false;
  f.setUser(f.user); assert.equal(changes, 1);
  assert.throws(() => identity.signOut(), /Account changed/);
  stop();
});

test("API helper attaches the current token, preserves headers, and encodes JSON", async () => {
  const f = fixture(true), identity = await authenticate(health, config, async () => f.sdk);
  const fetcher = async (url, opts) => {
    assert.equal(url, "https://api.example/v1/mandates/compile");
    assert.equal(opts.headers.get("X-Test"), "yes");
    assert.equal(opts.headers.get("Authorization"), "Bearer refreshed-token");
    assert.deepEqual(JSON.parse(opts.body), { text: "groceries" });
    assert.equal(opts.redirect, "error"); assert.equal(opts.credentials, "omit");
    return { ok: true, json: async () => ({ id: "m1" }) };
  };
  f.changeToken();
  assert.equal((await requestJSON("https://api.example", "/v1/mandates/compile", {
    method: "POST", headers: { "X-Test": "yes", "Authorization": "untrusted" }, body: { text: "groceries" },
    redirect: "follow", credentials: "include",
  }, identity, fetcher, connection)).id, "m1");
});

test("public health probe does not send a user token", async () => {
  const identity = { mode: "firebase", getToken: () => { throw new Error("token requested"); } };
  await requestJSON("https://api.example", "/healthz", { headers: { Authorization: "supplied-token" } }, identity, async (_, opts) => {
    assert.equal(opts.headers.get("Authorization"), null);
    return { ok: true, json: async () => ({ ok: true }) };
  }, connection);
});

test("uninitialized identity, account switch and insecure transport fail closed", async () => {
  const failFetch = () => { throw new Error("unexpected fetch"); };
  await assert.rejects(requestJSON("https://api.example", "/v1/mandates", {}, null, failFetch, connection), /not ready/);
  const f = fixture(true), identity = await authenticate(health, config, async () => f.sdk);
  await assert.rejects(requestJSON("http://api.example", "/v1/mandates", {}, identity, failFetch, {
    ...connection, configuredBase: "http://api.example",
  }), /HTTPS/);
  f.auth.currentUser = { uid: "bob" };
  await assert.rejects(requestJSON("https://api.example", "/v1/mandates", {}, identity, failFetch, connection), /Account changed/);
});

test("untrusted API origins fail before token retrieval or a public health probe", async () => {
  const identity = { mode: "firebase", getToken: () => { throw new Error("unexpected token retrieval"); } };
  const fetcher = () => { throw new Error("unexpected fetch"); };
  for (const path of ["/v1/mandates", "/healthz", "/sim/scenarios"]) {
    await assert.rejects(requestJSON("https://unconfigured.example", path, {}, identity, fetcher, connection), /not trusted/);
  }
});

test("same-origin rewrites and explicitly configured HTTPS APIs are trusted", () => {
  assert.equal(apiDestination("", "/v1/mandates", connection), "https://console.example/v1/mandates");
  assert.equal(apiDestination("https://api.example", "/sim/session", connection), "https://api.example/sim/session");
  for (const base of ["https://api.example.other", "https://api.example:444", "https://user:password@api.example"]) {
    assert.throws(() => apiDestination(base, "/v1/mandates", connection), /not trusted/);
  }
});

test("local port 8080 aliases work; other local ports require source configuration", () => {
  const local = { pageURL: "http://localhost:5173/index.html", configuredBase: "" };
  for (const host of ["localhost", "127.0.0.1", "[::1]"]) {
    assert.equal(apiDestination(`http://${host}:8080`, "/healthz", local), `http://${host}:8080/healthz`);
  }
  assert.throws(() => apiDestination("http://localhost:8091", "/healthz", local), /not trusted/);
  assert.equal(apiDestination("http://localhost:8091", "/healthz", {
    ...local, configuredBase: "http://localhost:8091",
  }), "http://localhost:8091/healthz");
  assert.throws(() => apiDestination("http://localhost:8080", "/healthz", connection), /not trusted/);
  assert.throws(() => apiDestination("http://localhost:8080", "/healthz", {
    ...connection, configuredBase: "http://localhost:8080",
  }), /HTTPS/);
});

test("local demo requests cannot forward a supplied authorization header", async () => {
  const identity = await authenticate({ auth_mode: "demo" }, {});
  await requestJSON("https://api.example", "/v1/mandates", { headers: { Authorization: "supplied-token" } }, identity,
    async (_, opts) => {
      assert.equal(opts.headers.get("Authorization"), null);
      return { ok: true, json: async () => [] };
    }, connection);
});
