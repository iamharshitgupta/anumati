import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { authenticate, requestJSON, signInWithGoogle } from "../web/auth.js";

const source = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
const config = { apiKey: "test", projectId: "demo-anumati" };
const health = { auth_mode: "firebase", firebase_project_id: config.projectId, store: "memory", semantic_engine: "heuristic" };
const settle = () => new Promise(setImmediate);

function consoleFixture({ apiHealth = health, healthError = false, popupError = false } = {}) {
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, {
      value: "", defaultValue: "", textContent: "", innerHTML: "", disabled: false, hidden: false,
      classList: { add() {}, remove() {} }, addEventListener() {}, remove() {},
    });
    return elements.get(selector);
  };
  const document = {
    querySelector: element,
    querySelectorAll: (selector) => selector.startsWith("#") ? selector.split(",").map(element) : [],
    createElement: () => element("toast"), body: { appendChild() {} },
  };
  let popupCalls = 0, anonymousCalls = 0, finishPopup;
  const auth = { currentUser: { uid: "old-user", isAnonymous: false,
    getIdTokenResult: async () => { throw new Error("auth/user-token-expired"); } },
    authStateReady: async () => {} };
  const app = { name: "anumati-console", options: config };
  const sdk = {
    getApps: () => [app], getAuth: () => auth, GoogleAuthProvider: class {},
    signInAnonymously: async () => { anonymousCalls++; throw new Error("Unexpected anonymous fallback"); },
    signInWithPopup: async () => {
      popupCalls++;
      if (popupError) throw new Error("auth/popup-closed-by-user");
      await new Promise((resolve) => { finishPopup = resolve; });
      auth.currentUser = { uid: "fresh-user", isAnonymous: false,
        getIdTokenResult: async () => ({ claims: {} }), getIdToken: async () => "fresh-token" };
      return { user: auth.currentUser };
    },
    onAuthStateChanged: () => () => {},
  };
  const requests = [];
  const fetcher = async (url, opts = {}) => {
    const path = new URL(url).pathname;
    if (path === "/healthz" && healthError) throw new Error("API unreachable");
    requests.push({ path, headers: opts.headers });
    return { ok: true, json: async () => path === "/healthz" ? apiHealth : path === "/sim/session" ? {} : [],
      text: async () => "" };
  };
  const connection = { pageURL: "http://localhost:5173/", configuredBase: "" };
  const context = vm.createContext({
    document, window: { ANUMATI_FIREBASE: config }, location: new URL(connection.pageURL),
    localStorage: { getItem: () => null, setItem() {} }, fetch: fetcher,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, console,
    authModule: {
      authenticate: (h, c) => authenticate(h, c, async () => sdk),
      signInWithGoogle: (h, c) => signInWithGoogle(h, c, async () => sdk),
      requestJSON: (base, path, opts, identity) => requestJSON(base, path, opts, identity, fetcher, connection),
    },
  });
  // Stub the SDK import while executing the console's actual startup and handlers.
  vm.runInContext(source.replaceAll('import("./auth.js")', "Promise.resolve(authModule)"), context);
  return { element, requests, context, popupCalls: () => popupCalls, anonymousCalls: () => anonymousCalls,
    finishPopup: () => finishPopup() };
}

test("failed startup keeps Team sign-in usable but gates protected actions until recovery", async () => {
  const f = consoleFixture();
  await settle();
  assert.equal(f.element("#identityBadge").textContent, "auth: unavailable");
  assert.equal(f.element("#signInBtn").disabled, false);
  assert.equal(f.element("#runBtn").disabled, true);
  await assert.rejects(f.context.api("/v1/mandates"), /not ready/);
  const recovering = f.element("#signInBtn").onclick();
  await settle();
  assert.equal(f.popupCalls(), 1);
  assert.equal(f.element("#runBtn").disabled, true);
  assert.deepEqual(f.requests.map((r) => r.path), ["/healthz"]);
  f.finishPopup();
  await recovering;
  assert.equal(f.element("#identityBadge").textContent, "user · fresh-us");
  assert.equal(f.element("#runBtn").disabled, false);
  assert.equal(f.anonymousCalls(), 0);
  assert.equal(f.requests.find((r) => r.path === "/sim/session").headers.get("Authorization"), "Bearer fresh-token");
});

test("cancelled recovery leaves API actions disabled and permits another sign-in attempt", async () => {
  const f = consoleFixture({ popupError: true });
  await settle();
  await f.element("#signInBtn").onclick();
  assert.equal(f.popupCalls(), 1); assert.equal(f.anonymousCalls(), 0);
  assert.equal(f.element("#signInBtn").disabled, false);
  assert.equal(f.element("#compileBtn").disabled, true);
  assert.deepEqual(f.requests.map((r) => r.path), ["/healthz"]);
});

test("unreachable API or mismatched project cannot offer recovery or load Firebase", async () => {
  for (const options of [{ healthError: true }, { apiHealth: { ...health, firebase_project_id: "wrong" } }]) {
    const f = consoleFixture(options);
    await settle();
    assert.equal(f.element("#signInBtn").disabled, true);
    assert.equal(f.element("#runBtn").disabled, true);
    await f.element("#signInBtn").onclick();
    assert.equal(f.popupCalls(), 0); assert.equal(f.anonymousCalls(), 0);
  }
});
