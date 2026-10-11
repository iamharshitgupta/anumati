/* Anumati console — vanilla JS, no build step.
   Talks to the Cloud Run API; attaches Firestore realtime listeners when a
   Firebase config is present, otherwise polls. */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });

// ---------------------------------------------------------------- API base
const stored = localStorage.getItem("anumati.api");
let API = stored ?? (window.ANUMATI_API_BASE || (location.hostname === "localhost" || location.protocol === "file:" ? "http://localhost:8080" : ""));
$("#apiBase").value = API;
$("#apiBase").addEventListener("change", (e) => { API = e.target.value.replace(/\/$/, ""); localStorage.setItem("anumati.api", API); boot(); });

async function api(path, opts = {}) {
  const r = await fetch(API + path, { headers: { "content-type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
function toast(html) { const t = document.createElement("div"); t.className = "toast"; t.innerHTML = html; document.body.appendChild(t); setTimeout(() => t.remove(), 6000); }

// ---------------------------------------------------------------- tabs
document.querySelectorAll("nav.tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("nav.tabs button, .tab").forEach((x) => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
  refresh(b.dataset.tab);
}));

// ---------------------------------------------------------------- state
let scenarios = [], scenario = "clean", mandates = [], lastRun = null;
const DEMO_USER = "user_demo";

async function boot() {
  try {
    const h = await api("/healthz");
    $("#engineBadge").textContent = `semantic: ${h.semantic_engine}${h.model ? " · " + h.model : ""} · store: ${h.store}`;
    $("#engineBadge").className = "badge " + (h.semantic_engine === "gemini" ? "ok" : "");
  } catch (e) { $("#engineBadge").textContent = "API unreachable"; $("#engineBadge").className = "badge"; return; }
  scenarios = await api("/sim/scenarios");
  renderScenarios(); await loadMandates(); showMerchant(); refresh("stepups"); refresh("feed");
}

// ---------------------------------------------------------------- sandbox
function renderScenarios() {
  $("#scenarioList").innerHTML = scenarios.map((s) => `
    <div class="scenario ${s.key === scenario ? "active" : ""}" data-key="${s.key}">
      <div><div class="t">${esc(s.title)}</div><div class="a">${esc(s.attack || "No attack — control case")}</div></div>
      <div class="exp">expect ${s.expected}${s.multi > 1 ? " ×" + s.multi : ""}</div>
    </div>`).join("");
  document.querySelectorAll(".scenario").forEach((el) => el.addEventListener("click", () => { scenario = el.dataset.key; renderScenarios(); showMerchant(); }));
}
async function showMerchant() {
  const raw = await (await fetch(`${API}/sim/merchant/${scenario}/raw`)).text();
  // visible = strip html comments and display:none blocks
  const visible = raw.replace(/<div[^>]*display:none[^>]*>[\s\S]*?<\/div>/gi, "").replace(/<!--[\s\S]*?-->/g, "");
  const hidden = (raw.match(/<div[^>]*display:none[^>]*>[\s\S]*?<\/div>|<!--[\s\S]*?-->/gi) || []).join("\n");
  $("#merchantView").textContent = visible.trim();
  $("#hiddenPre").textContent = hidden || "(nothing hidden — the steering, if any, is in plain sight)";
}
$("#runBtn").addEventListener("click", async () => {
  const btn = $("#runBtn"); btn.disabled = true; btn.textContent = "Agent is shopping…";
  try {
    lastRun = await api("/sim/run", { method: "POST", body: { mandate_id: $("#sandboxMandate").value, scenario, mode: $("#agentMode").value } });
    renderResult(lastRun); refresh("stepups"); refresh("feed");
  } catch (e) { toast(`<b>Run failed</b><br>${esc(e.message)}`); }
  btn.disabled = false; btn.textContent = "Run attack through Anumati →";
});
function renderResult(r) {
  const d = r.decisions[r.decisions.length - 1];
  $("#result").hidden = false;
  $("#verdict").textContent = d.verdict; $("#verdict").className = "verdict " + d.verdict;
  $("#riskBar").style.width = d.risk_score + "%"; $("#riskLabel").textContent = `risk ${d.risk_score}/100 · ${d.latency_ms} ms · ${d.semantic_engine}`;
  $("#caught").innerHTML = r.caught ? `✅ caught — expected <b>${r.expected}</b>` : `⚠️ expected <b>${r.expected}</b>, got ${d.verdict}`;
  if (r.decisions.length > 1) $("#caught").innerHTML += ` · ${r.decisions.length} payments attempted: ${r.decisions.map((x) => x.verdict).join(" → ")}`;
  $("#caught").innerHTML += ` · agent: ${esc(r.agent_engine)}`;
  $("#findings").innerHTML = d.findings.length ? d.findings.map((f) => `
    <li class="${f.severity}"><code>${f.code}</code> <span class="tag">${f.source}</span> <span class="tag">+${f.weight}</span><br>${esc(f.message)}
      ${f.evidence && Object.keys(f.evidence).length ? `<span class="ev">${esc(JSON.stringify(f.evidence)).slice(0, 400)}</span>` : ""}</li>`).join("")
    : `<li class="info">No findings. Payment is consistent with the mandate.</li>`;
  $("#trace").innerHTML = d.request.agent_trace.map((t) => `<li><span class="k">${t.kind}</span>${esc(t.content)}</li>`).join("");
  $("#attempt").textContent = JSON.stringify({ payee: `${d.request.payee_name} <${d.request.payee_vpa}>`, merchant: d.request.merchant, amount: inr(d.request.amount), category: d.request.category, cart: d.request.cart.map((c) => `${c.qty}× ${c.name} @ ${inr(c.unit_price)}`) }, null, 2);
  $("#stepupNote").textContent = d.verdict === "STEP_UP" ? "Held — the account holder's prompt is waiting in the Step-ups tab." : d.verdict === "BLOCK" ? "Blocked before any UPI collect/pay was created." : "Cleared to the rail.";
  $("#openReceipt").onclick = () => { switchTab("receipts"); openReceipt(d.receipt_id); };
  $("#raiseDispute").onclick = () => { switchTab("disputes"); $("#dDecision").value = d.id; };
}
function switchTab(name) { document.querySelector(`nav.tabs button[data-tab=${name}]`).click(); }

// ---------------------------------------------------------------- mandates
async function loadMandates() {
  mandates = await api(`/v1/mandates?user_id=${DEMO_USER}`);
  $("#sandboxMandate").innerHTML = mandates.filter((m) => m.status === "active").map((m) => `<option value="${m.id}">${m.id} — ${esc(m.natural_language.slice(0, 60))}…</option>`).join("");
  $("#mandateList").innerHTML = mandates.map((m) => `
    <div class="item"><div><span class="tag ${m.status}">${m.status}</span> <b>${inr(m.guardrails.per_txn_cap)}/txn · ${inr(m.guardrails.period_cap)}/${m.guardrails.period}</b>
      <div>${esc(m.natural_language)}</div>
      <div class="meta">${m.id} · agent ${m.agent_id} · merchants ${esc((m.guardrails.allowed_merchants || []).join(", ") || "any")} · new payees ${m.guardrails.allow_new_payees ? "allowed" : "forbidden"} · step-up above ${m.guardrails.step_up_above ? inr(m.guardrails.step_up_above) : "—"} · compiled by ${m.compiler}</div></div>
      <div class="actions">${m.status === "active" ? `<button class="secondary tiny" data-revoke="${m.id}">Revoke</button>` : ""}</div></div>`).join("");
  document.querySelectorAll("[data-revoke]").forEach((b) => b.onclick = async () => { await api(`/v1/mandates/${b.dataset.revoke}/revoke`, { method: "POST" }); loadMandates(); });
}
let draft = null;
$("#compileBtn").addEventListener("click", async () => {
  const btn = $("#compileBtn"); btn.disabled = true;
  try {
    draft = await api("/v1/mandates/compile", { method: "POST", body: { user_id: $("#mUser").value, agent_id: $("#mAgent").value, text: $("#mandateText").value, ttl_days: Number($("#mTtl").value) } });
    $("#compiled").hidden = false; $("#compilerBadge").textContent = draft.compiler;
    $("#guardrails").textContent = JSON.stringify(draft.guardrails, null, 2);
    $("#compilerNotes").innerHTML = draft.compiler_notes.map((n) => `<li>${esc(n)}</li>`).join("");
  } catch (e) { toast(`<b>Compile failed</b><br>${esc(e.message)}`); }
  btn.disabled = false;
});
$("#signBtn").addEventListener("click", async () => {
  if (!draft) return;
  await api(`/v1/mandates/${draft.id}/sign`, { method: "POST", body: {} });
  toast(`<b>Mandate activated</b><br>${draft.id} is now enforceable.`); $("#compiled").hidden = true; draft = null; loadMandates();
});

// ---------------------------------------------------------------- step-ups
async function loadStepups(rows) {
  rows = rows || await api(`/v1/stepups?user_id=${DEMO_USER}&status=pending`);
  $("#suCount").textContent = rows.length;
  $("#stepupList").innerHTML = rows.length ? rows.map((s) => `
    <div class="item"><div><b>${inr(s.amount)}</b> to ${esc(s.payee_name)} <span class="meta">&lt;${esc(s.payee_vpa)}&gt;</span> · risk ${s.risk_score}/100
      <ul class="notes">${(s.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      <div class="meta">${s.id} · agent ${s.agent_id} · ${new Date(s.created_at).toLocaleTimeString()}</div></div>
      <div class="actions"><button class="primary tiny" data-su="${s.id}" data-ok="1">Approve</button><button class="secondary tiny" data-su="${s.id}" data-ok="0">Decline</button></div></div>`).join("")
    : `<p class="hint">Nothing pending.</p>`;
  document.querySelectorAll("[data-su]").forEach((b) => b.onclick = async () => {
    await api(`/v1/stepups/${b.dataset.su}/respond`, { method: "POST", body: { approve: b.dataset.ok === "1", note: b.dataset.ok === "1" ? "confirmed by account holder" : "declined by account holder" } });
    loadStepups(); refresh("feed");
  });
}

// ---------------------------------------------------------------- feed / receipts / disputes
async function loadFeed(rows) {
  rows = rows || await api(`/v1/decisions?user_id=${DEMO_USER}&limit=40`);
  $("#feed").innerHTML = rows.map((d) => `
    <div class="item"><div><span class="tag ${d.verdict}">${d.verdict}</span> <b>${inr(d.request.amount)}</b> → ${esc(d.request.payee_name)} <span class="meta">&lt;${esc(d.request.payee_vpa)}&gt;</span> · risk ${d.risk_score}
      ${d.request.scenario ? `<span class="tag">${esc(d.request.scenario)}</span>` : ""} <span class="tag">${d.status}</span>
      <div class="meta">${d.id} · ${new Date(d.created_at).toLocaleString()} · ${d.findings.map((f) => f.code).join(", ") || "no findings"}</div></div>
      <div class="actions"><button class="secondary tiny" data-rc="${d.receipt_id}">Receipt</button><button class="secondary tiny" data-dsp="${d.id}">Dispute</button></div></div>`).join("");
  document.querySelectorAll("[data-rc]").forEach((b) => b.onclick = () => { switchTab("receipts"); openReceipt(b.dataset.rc); });
  document.querySelectorAll("[data-dsp]").forEach((b) => b.onclick = () => { switchTab("disputes"); $("#dDecision").value = b.dataset.dsp; });
}
async function loadReceipts() {
  const rows = await api(`/v1/receipts?limit=40`);
  $("#receiptList").innerHTML = rows.map((r) => `
    <div class="item"><div><span class="tag ${r.verdict}">${r.verdict}</span> ${inr(r.attempted.amount)} → ${esc(r.attempted.payee_vpa)} · ${r.signature_valid ? "✅ signature valid" : "❌ INVALID"}
      <div class="meta">${r.id} · ${new Date(r.issued_at).toLocaleString()} · hash ${r.hash.slice(0, 16)}… · prev ${r.prev_hash.slice(0, 12)}…</div></div>
      <div class="actions"><button class="secondary tiny" data-open="${r.id}">Open</button></div></div>`).join("");
  document.querySelectorAll("[data-open]").forEach((b) => b.onclick = () => openReceipt(b.dataset.open));
}
// ---- receipt verifier (tamper-evident) ----------------------------------
let openReceiptJson = null;   // the untouched receipt as issued, for "reset"
function setVerifyBadge(state, text) { const b = $("#verifyBadge"); b.textContent = text; b.className = "badge " + (state === "ok" ? "ok" : state === "bad" ? "bad" : "muted"); }
async function openReceipt(id) {
  const r = await api(`/v1/receipts/${id}`);
  openReceiptJson = r;
  $("#receiptView").value = JSON.stringify(r, null, 2);
  $("#verifyResult").innerHTML = "";
  await verifyCurrentReceipt(true);
}
async function verifyCurrentReceipt(quiet) {
  let receipt;
  try { receipt = JSON.parse($("#receiptView").value); }
  catch (e) { setVerifyBadge("bad", "invalid JSON"); $("#verifyResult").innerHTML = `<div class="bad">Receipt is not valid JSON — ${esc(e.message)}</div>`; return; }
  const res = await api("/v1/receipts/verify", { method: "POST", body: receipt });
  if (res.valid) {
    setVerifyBadge("ok", "signature valid ✅");
    $("#verifyResult").innerHTML = `<div class="ok">✅ <b>Signature valid.</b> The HMAC matches the SHA-256 of the canonical body — this receipt is exactly what Anumati signed. Hash <code>${esc((res.hash || "").slice(0, 24))}…</code></div>`;
  } else {
    setVerifyBadge("bad", "signature INVALID ❌");
    $("#verifyResult").innerHTML = `<div class="bad">❌ <b>Signature does not verify.</b> The body no longer hashes to the signed value — this receipt has been altered or the signing key differs. A dispute party would reject it.</div>`;
  }
}
$("#verifyReceiptBtn").addEventListener("click", () => verifyCurrentReceipt(false));
$("#resetReceiptBtn").addEventListener("click", () => { if (openReceiptJson) { $("#receiptView").value = JSON.stringify(openReceiptJson, null, 2); verifyCurrentReceipt(false); } });
$("#tamperBtn").addEventListener("click", () => {
  let r; try { r = JSON.parse($("#receiptView").value); } catch { return; }
  const before = r.attempted?.amount;
  if (r.attempted && typeof r.attempted.amount === "number") r.attempted.amount = r.attempted.amount + 1000;
  else return;
  $("#receiptView").value = JSON.stringify(r, null, 2);
  $("#verifyResult").innerHTML = `<div class="warn">Changed <code>attempted.amount</code> from ₹${before} to ₹${r.attempted.amount} — a single rupee-field edit. Now re-verifying…</div>`;
  setTimeout(() => verifyCurrentReceipt(false), 400);
});
$("#chainBtn").addEventListener("click", async () => { const c = await api(`/v1/receipts/chain/${$("#sandboxMandate").value || "mnd_demo0001"}`); $("#chainResult").textContent = `${c.receipts} receipts · chain ${c.chain_intact ? "intact ✅" : "BROKEN at " + c.broken_at + " ❌"}`; });

$("#disputeBtn").addEventListener("click", async () => {
  const btn = $("#disputeBtn"); btn.disabled = true;
  try {
    const d = await api("/v1/disputes", { method: "POST", body: { decision_id: $("#dDecision").value.trim(), raised_by: $("#dBy").value, claim: $("#dClaim").value } });
    renderDispute(d); loadDisputes();
  } catch (e) { toast(`<b>Dispute failed</b><br>${esc(e.message)}`); }
  btn.disabled = false;
});
function renderDispute(d) {
  const a = d.attribution;
  $("#disputeView").innerHTML = `<div class="memo">
    <div class="party">${esc(a.primary_party)} <span class="tag">${esc(a.confidence)} confidence</span> <span class="tag">${esc(a.engine)}</span> <span class="tag">receipt ${d.receipt_signature_valid ? "verified" : "UNVERIFIED"}</span></div>
    <h4>Memo</h4><p>${esc(a.memo)}</p>
    <h4>Established</h4><ul>${(a.established || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <h4>Unresolved</h4><ul>${(a.unresolved || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
    <h4>Evidence needed</h4><ul>${(a.evidence_needed || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
    <h4>Replay</h4><pre class="mono small">${esc(JSON.stringify(d.replay, null, 2))}</pre>
    <div class="row"><button class="primary tiny" id="resolveBtn">Close case with this attribution</button></div></div>`;
  $("#resolveBtn").onclick = async () => { await api(`/v1/disputes/${d.id}/resolve`, { method: "POST", body: { resolution: "closed per attribution memo", party: a.primary_party } }); toast(`<b>Dispute ${d.id} resolved</b>`); loadDisputes(); };
}
async function loadDisputes() {
  const rows = await api("/v1/disputes");
  $("#disputeList").innerHTML = rows.map((d) => `<div class="item"><div><span class="tag ${d.status}">${d.status}</span> ${esc(d.claim.slice(0, 90))} <div class="meta">${d.id} · by ${d.raised_by} · → ${esc(d.attribution.primary_party)}</div></div>
    <div class="actions"><button class="secondary tiny" data-dv="${d.id}">View</button></div></div>`).join("");
  document.querySelectorAll("[data-dv]").forEach((b) => b.onclick = async () => renderDispute(await api(`/v1/disputes/${b.dataset.dv}`)));
}

function refresh(tab) {
  if (tab === "stepups") loadStepups().catch(() => {});
  if (tab === "feed") loadFeed().catch(() => {});
  if (tab === "receipts") loadReceipts().catch(() => {});
  if (tab === "disputes") loadDisputes().catch(() => {});
  if (tab === "mandates") loadMandates().catch(() => {});
}

// ---------------------------------------------------------------- realtime (Firestore) or polling
async function realtime() {
  const cfg = window.ANUMATI_FIREBASE || {};
  if (!cfg.apiKey) { setInterval(() => { loadStepups().catch(() => {}); }, 4000); return; }
  try {
    const { initializeApp } = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js");
    const { getAuth, signInAnonymously } = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js");
    const { getFirestore, collection, query, where, orderBy, onSnapshot, limit } = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js");
    const app = initializeApp(cfg); await signInAnonymously(getAuth(app)); const db = getFirestore(app);
    onSnapshot(query(collection(db, "stepups"), where("user_id", "==", DEMO_USER), where("status", "==", "pending"), orderBy("created_at", "desc")),
      (snap) => { const rows = snap.docs.map((d) => d.data()); loadStepups(rows); if (snap.docChanges().some((c) => c.type === "added")) toast(`<b>Confirmation needed</b><br>An agent payment is waiting for your one-tap approval.`); });
    onSnapshot(query(collection(db, "decisions"), where("request.user_id", "==", DEMO_USER), orderBy("created_at", "desc"), limit(40)),
      (snap) => loadFeed(snap.docs.map((d) => d.data())));
    $("#rtBadge").textContent = "realtime: Firestore"; $("#rtBadge").className = "badge ok";
  } catch (e) { console.warn("Firestore realtime unavailable, polling", e); setInterval(() => { loadStepups().catch(() => {}); }, 4000); }
}

boot().then(realtime);
