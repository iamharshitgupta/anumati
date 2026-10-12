/* Optional emulator suite. See docs/AUTH.md for temporary test dependencies.
   A demo-* project and loopback emulator are mandatory: never use cloud data. */
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { initializeTestEnvironment, assertSucceeds, assertFails } = require("@firebase/rules-unit-testing");
const { doc, getDoc, setDoc, deleteDoc, collection, query, where, getDocs } = require("firebase/firestore");

let env;
const collections = ["mandates", "receipts", "stepups", "disputes", "decisions"];
const projectId = "demo-anumati";
function database(uid, role = "user", provider = "google.com") {
  return env.authenticatedContext(uid, { role, firebase: { sign_in_provider: provider } }).firestore();
}
function ownedQuery(db, name, uid) {
  return query(collection(db, name), where(name === "decisions" ? "request.user_id" : "user_id", "==", uid));
}

before(async () => {
  assert.match(process.env.FIRESTORE_EMULATOR_HOST || "", /^127\.0\.0\.1:18080$/);
  env = await initializeTestEnvironment({ projectId, firestore: {
    host: "127.0.0.1", port: 18080,
    rules: readFileSync(join(__dirname, "../web/firestore.rules"), "utf8"),
  } });
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const name of collections) {
      for (const uid of ["alice", "bob"]) {
        const body = name === "decisions" ? { request: { user_id: uid } } : { user_id: uid };
        await setDoc(doc(db, name, uid), body);
      }
    }
    await setDoc(doc(db, "agents", "private"), { user_id: "alice" });
  });
});
after(async () => { if (env) await env.cleanup(); });

for (const name of collections) {
  test(`${name}: owner reads work; foreign and unscoped reads are denied`, async () => {
    const db = database("alice");
    await assertSucceeds(getDoc(doc(db, name, "alice")));
    await assertFails(getDoc(doc(db, name, "bob")));
    const rows = await assertSucceeds(getDocs(ownedQuery(db, name, "alice")));
    assert.equal(rows.size, 1);
    await assertFails(getDocs(collection(db, name)));
    await assertFails(getDocs(ownedQuery(db, name, "bob")));
  });
  test(`${name}: staff browser reads stay owner-only and all writes are denied`, async () => {
    for (const role of ["analyst", "admin"]) {
      const db = database("alice", role);
      await assertSucceeds(getDoc(doc(db, name, "alice")));
      await assertFails(getDoc(doc(db, name, "bob")));
      await assertFails(getDocs(collection(db, name)));
      await assertFails(setDoc(doc(db, name, "new"), { user_id: role }));
      await assertFails(deleteDoc(doc(db, name, "alice")));
    }
    await assertFails(setDoc(doc(database("alice"), name, "alice"), { user_id: "alice" }));
    await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), name, "alice")));
  });
}

test("anonymous visitors stay owner-scoped even with a staff claim", async () => {
  for (const role of ["user", "admin"]) {
    const db = database("alice", role, "anonymous");
    await assertSucceeds(getDoc(doc(db, "mandates", "alice")));
    await assertFails(getDoc(doc(db, "mandates", "bob")));
    await assertFails(getDocs(collection(db, "mandates")));
  }
});

test("undeclared collections stay denied even for staff", async () => {
  const db = database("admin", "admin");
  await assertFails(getDoc(doc(db, "agents", "private")));
  await assertFails(setDoc(doc(db, "agents", "new"), {}));
});
