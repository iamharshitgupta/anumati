/* Anumati console — vanilla JS, no build step.
   Talks to the Cloud Run API; attaches Firestore realtime listeners when a
   Firebase config is present, otherwise polls. */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });

// ---------------------------------------------------------------- API base
const localConsole = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const stored = localConsole ? localStorage.getItem("anumati.api") : null;
let API = stored ?? (window.ANUMATI_API_BASE || (localConsole ? "http://localhost:8080" : ""));
$("#apiBase").value = API;
$("#apiBase").readOnly = !localConsole;
$("#apiBase").addEventListener("change", (e) => { API = e.target.value.replace(/\/$/, ""); localStorage.setItem("anumati.api", API); boot(); });

async function api(path, opts = {}) {
  const caller = identity, base = API;
  const { requestJSON } = await import("./auth.js");
  const result = await requestJSON(base, path, opts, caller);
  if (caller !== identity || base !== API) throw new Error("Connection changed; reload this view.");
  return result;
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
let DEMO_USER = "user_demo", identity = null, storeBackend = null, pollingTimer = null, unsubscribeRealtime = [];
let unsubscribeAuth = null, sessionVersion = 0;
let signInRecovery = null;
const isStaff = () => identity && ["analyst", "admin"].includes(identity.role);

function stopRealtime() {
  unsubscribeRealtime.forEach((stop) => stop()); unsubscribeRealtime = [];
  clearInterval(pollingTimer); pollingTimer = null;
}

function setReady(ready) {
  document.querySelectorAll("#runBtn,#compareBtn,#guidedBtn,#compileBtn,#signBtn,#chainBtn,#disputeBtn,#verifyReceiptBtn,#resetReceiptBtn,#tamperBtn,#newDemoSessionBtn").forEach((b) => { b.disabled = !ready; });
}

function clearSession() {
  sessionVersion++;
  unsubscribeAuth?.(); unsubscribeAuth = null;
  stopRealtime(); setReady(false); identity = null; draft = null; lastRun = null; mandates = []; storeBackend = null;
  DEMO_USER = ""; $("#mUser").value = "";
  $("#mandateText").value = $("#mandateText").defaultValue;
  signInRecovery = null;
  $("#apiBase").disabled = true; $("#signInBtn").disabled = true; $("#signOutBtn").hidden = true;
  $("#newDemoSessionBtn").hidden = true;
  $("#identityBadge").textContent = "auth: connecting"; $("#identityBadge").title = "";
  ["#mandateList", "#sandboxMandate", "#stepupList", "#feed", "#receiptList", "#disputeList", "#disputeView"].forEach((s) => { $(s).innerHTML = ""; });
  ["#findings", "#trace", "#attempt", "#evidenceChain", "#baselineComparison", "#compareGrid", "#compareVerdictNote"].forEach((s) => { $(s).innerHTML = ""; });
  $("#compareCard").hidden = true; $("#stepupOutcome").hidden = true;
  $("#receiptView").value = ""; $("#result").hidden = true; $("#compiled").hidden = true;
  openReceiptJson = null; $("#verifyResult").innerHTML = ""; $("#chainResult").textContent = "";
  $("#dDecision").value = ""; $("#dClaim").value = ""; $("#suCount").textContent = "0";
  demoExit();
}

function enableSignInRecovery(health) {
  const config = window.ANUMATI_FIREBASE || {};
  if (health?.auth_mode !== "firebase" || !config.apiKey || !config.projectId || config.projectId !== health.firebase_project_id) return;
  signInRecovery = health;
  $("#signInBtn").disabled = false;
}

async function boot() {
  clearSession();
  const version = sessionVersion;
  let h;
  try {
    h = await api("/healthz");
    if (version !== sessionVersion) return;
    $("#engineBadge").textContent = `semantic: ${h.semantic_engine}${h.model ? " · " + h.model : ""} · store: ${h.store}`;
    $("#engineBadge").className = "badge " + (h.semantic_engine === "gemini" ? "ok" : "");
    const { authenticate } = await import("./auth.js");
    const caller = await authenticate(h, window.ANUMATI_FIREBASE || {});
    if (version !== sessionVersion) return;
    identity = caller; storeBackend = h.store;
    unsubscribeAuth = caller.onAccountChange?.(() => {
      if (identity !== caller) return;
      clearSession();
      enableSignInRecovery(h);
      $("#identityBadge").textContent = "auth: session changed";
      $("#apiBase").disabled = false;
      toast("Sign-in session changed in another tab.");
    }) || null;
    DEMO_USER = identity.uid;
    $("#identityBadge").textContent = identity.mode === "demo" ? "auth: local demo" : `${identity.role} · ${identity.uid.slice(0, 8)}`;
    $("#identityBadge").title = `UID: ${identity.uid}`;
    $("#mUser").value = DEMO_USER; $("#mUser").readOnly = true;
    $("#signInBtn").disabled = identity.mode !== "firebase";
    $("#signOutBtn").hidden = identity.mode !== "firebase" || identity.isAnonymous;
    $("#newDemoSessionBtn").hidden = identity.mode !== "firebase" || !identity.isAnonymous;
    await api("/sim/session", { method: "POST" });
    scenarios = await api("/sim/scenarios");
    renderScenarios(); await loadMandates(); await showMerchant(); await loadStepups(); await loadFeed();
    await realtime();
    if (version === sessionVersion) setReady(true);
  } catch (e) {
    if (version !== sessionVersion) return;
    clearSession(); $("#identityBadge").textContent = "auth: unavailable";
    enableSignInRecovery(h);
    $("#apiBase").disabled = false;
    toast(`<b>Console setup failed</b><br>${esc(e.message)}`);
  } finally { if (version === sessionVersion) $("#apiBase").disabled = false; }
}

$("#signInBtn").onclick = async () => {
  const caller = identity;
  const recovery = signInRecovery;
  if (caller?.mode !== "firebase" && !recovery) return;
  try {
    if (caller?.mode === "firebase") await caller.signInWithGoogle();
    else {
      const { signInWithGoogle } = await import("./auth.js");
      await signInWithGoogle(recovery, window.ANUMATI_FIREBASE || {});
    }
    await boot();
  }
  catch (e) { toast(`<b>Sign-in failed</b><br>${esc(e.message)}`); }
};

async function signOutAndBoot(caller) {
  clearSession();
  await caller.signOut();
  await boot();
}

$("#signOutBtn").onclick = async () => {
  const caller = identity;
  if (caller?.mode !== "firebase") return;
  try { await signOutAndBoot(caller); }
  catch (e) { $("#identityBadge").textContent = "auth: unavailable"; toast(`<b>Sign-out failed</b><br>${esc(e.message)}`); }
};

$("#newDemoSessionBtn").onclick = async () => {
  const caller = identity;
  if (caller?.mode !== "firebase" || !caller.isAnonymous) return;
  const confirmed = window.confirm("Start a new demo session?\n\nYour current records will stay saved under the old visitor UID, but you will lose access to them from this anonymous session. The old account and its records will not be disabled or deleted.\n\nThis changes the sign-in session in other tabs in this browser too.");
  if (!confirmed || caller !== identity) return;
  try { await signOutAndBoot(caller); }
  catch (e) { $("#identityBadge").textContent = "auth: unavailable"; toast(`<b>New demo session failed</b><br>${esc(e.message)}`); }
};

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
async function runScenario() {
  const btn = $("#runBtn"); btn.disabled = true; btn.textContent = "Agent is shopping…";
  try {
    lastRun = await api("/sim/run", { method: "POST", body: { mandate_id: $("#sandboxMandate").value, scenario, mode: $("#agentMode").value } });
    renderResult(lastRun); refresh("stepups"); refresh("feed");
  } catch (e) { toast(`<b>Run failed</b><br>${esc(e.message)}`); }
  btn.disabled = false; btn.textContent = "Run attack through Anumati →";
}
$("#runBtn").addEventListener("click", runScenario);
// ---- Gemini vs heuristic side-by-side ----------------------------------
const GEMINI_HELP = "Gemini isn't configured on this API, so the gateway is running the deterministic heuristic (never failing open). Start the backend with <code>GOOGLE_API_KEY=…</code> (or <code>USE_VERTEX=1</code>) and this column fills in — the engine badge up top will read <b>semantic: gemini</b>.";
function engineCol(title, a, missingHtml) {
  if (!a) return `<div class="cmpcol missing"><div class="cmphead">${title}</div><div class="cmpmissing">${missingHtml}</div></div>`;
  const bar = (label, v) => `<div class="cmpbar"><span class="cmplabel">${label}</span><div class="cmpmeter"><div style="width:${v}%"></div></div><b>${v}</b></div>`;
  const reasons = [...(a.injection_reasons || []), ...(a.drift_reasons || [])].slice(0, 6);
  return `<div class="cmpcol">
    <div class="cmphead">${title}<span class="verdict ${a.verdict} mini">${a.verdict}</span><span class="tag">risk ${a.risk}</span></div>
    ${bar("injection", a.injection_score)}${bar("drift", a.drift_score)}
    ${a.injected_instructions && a.injected_instructions.length ? `<div class="cmpinj"><b>Injected text caught verbatim:</b><ul>${a.injected_instructions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    <ul class="notes">${reasons.map((r) => `<li>${esc(r)}</li>`).join("") || "<li class='muted'>no steering signals</li>"}</ul>
    ${a.summary ? `<div class="cmpsum">${esc(a.summary)}</div>` : ""}
  </div>`;
}
function renderCompare(c) {
  $("#compareCard").hidden = false;
  $("#compareGrid").innerHTML = engineCol("Heuristic <span class='tag'>no LLM</span>", c.heuristic, "") + engineCol("Gemini 2.5 Flash", c.gemini, GEMINI_HELP);
  let note;
  if (!c.gemini_available || !c.gemini) note = `Heuristic verdict on <b>${esc(c.title)}</b>: <b>${c.heuristic.verdict}</b> (policy Σ ${c.policy.policy_sum}). Configure Gemini to compare the model's reading of the same inputs — on a deployed build this is the number judges score.`;
  else if (c.gemini.verdict === c.heuristic.verdict) note = `Both engines land on <b>${c.gemini.verdict}</b> (policy Σ ${c.policy.policy_sum}). Here the Gemini audit <b>corroborates</b> the heuristic — but note the scores and reasons it surfaces independently.`;
  else note = `Engines <b>disagree</b> on identical policy + content: heuristic <b>${c.heuristic.verdict}</b> vs Gemini <b>${c.gemini.verdict}</b>. The semantic reading changed the outcome — exactly the content-steering gap rules can't see.`;
  $("#compareVerdictNote").innerHTML = note;
  $("#compareCard").scrollIntoView({ behavior: "smooth", block: "start" });
}
$("#compareBtn").addEventListener("click", async () => {
  const btn = $("#compareBtn"); btn.disabled = true; btn.textContent = "Comparing…";
  try { renderCompare(await api("/sim/compare", { method: "POST", body: { mandate_id: $("#sandboxMandate").value, scenario } })); }
  catch (e) { toast(`<b>Compare failed</b><br>${esc(e.message)}`); }
  btn.disabled = false; btn.textContent = "⚖ Gemini vs heuristic";
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
  renderEvidence(d);
  renderBaselineComparison(r, d);
  $("#openReceipt").onclick = () => { switchTab("receipts"); openReceipt(d.receipt_id); };
  $("#raiseDispute").onclick = () => { switchTab("disputes"); $("#dDecision").value = d.id; };
}
function switchTab(name) { document.querySelector(`nav.tabs button[data-tab=${name}]`).click(); }

function renderEvidence(decision) {
  const findings = decision.findings.filter((f) => ["INJECTION", "DRIFT"].includes(f.code));
  const effects = [];
  if (decision.findings.some((f) => ["PAYEE_NOT_ALLOWED", "PAYEE_HANDLE_MISMATCH", "NEW_PAYEE", "PAYEE_SUSPECT_REGISTRY"].includes(f.code))) {
    effects.push(`Payee submitted: ${decision.request.payee_vpa}`);
  }
  if (decision.findings.some((f) => ["QUANTITY_ANOMALY", "CART_AMOUNT_MISMATCH", "CART_CATEGORY_OUT_OF_SCOPE", "CATEGORY_OUT_OF_SCOPE"].includes(f.code))) {
    effects.push(`Cart / amount: ${decision.request.cart.map((item) => `${item.qty}× ${item.name}`).join(", ") || inr(decision.request.amount)}`);
  }
  if (!findings.length && !effects.length) {
    $("#evidenceChain").innerHTML = `<p class="hint">No injection or intent drift was detected for this request.</p>`;
    return;
  }
  const sourceQuotes = [];
  const quoteItems = findings.flatMap((finding) => {
    const quotes = finding.evidence?.instructions || finding.evidence?.reasons || [];
    const clearestQuote = [...quotes].sort((left, right) => right.length - left.length)[0];
    if (!clearestQuote) return [];
    const sourceLink = finding.code === "INJECTION"
      ? `<button class="source-link" type="button" data-source-quote="${sourceQuotes.push(clearestQuote) - 1}">Locate in merchant content</button>`
      : "";
    return [`<blockquote><span class="tag">${esc(finding.code)}</span><mark>${esc(clearestQuote)}</mark>${sourceLink}</blockquote>`];
  });
  $("#evidenceChain").innerHTML = `
    <div class="evidence-grid">
      <div><b>Page / agent evidence</b>${quoteItems.join("") || `<p class="hint">The trace shows the agent followed content from the merchant page.</p>`}</div>
      <div><b>Payment fields affected</b>${effects.length ? `<ul>${effects.map((effect) => `<li>${esc(effect)}</li>`).join("")}</ul>` : `<p class="hint">No changed payee or cart field was identified.</p>`}</div>
    </div>
    <p class="hint">Quoted content is untrusted evidence and is displayed as text only.</p>`;
  document.querySelectorAll("[data-source-quote]").forEach((button) => {
    button.onclick = () => highlightSourceQuote(sourceQuotes[Number(button.dataset.sourceQuote)]);
  });
}

function highlightSourceQuote(quote) {
  for (const target of [$("#hiddenPre"), $("#merchantView")]) {
    const content = target.textContent || "";
    const pattern = quote.trim().split(/\s+/).map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
    const match = new RegExp(pattern).exec(content);
    if (!match) continue;
    const mark = document.createElement("mark");
    mark.textContent = match[0];
    target.replaceChildren(document.createTextNode(content.slice(0, match.index)), mark, document.createTextNode(content.slice(match.index + match[0].length)));
    if (target.id === "hiddenPre") $("#hiddenView").open = true;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  toast("Exact quote is not present in the displayed page excerpt.");
}

function renderBaselineComparison(run, decision) {
  const comparison = run.baseline_comparisons?.[run.baseline_comparisons.length - 1];
  $("#baselineNote").textContent = comparison
    ? `Same simulated request · deterministic baselines · semantic engine: ${decision.semantic_engine}.`
    : "Baseline comparison is unavailable for this response.";
  $("#baselineComparison").innerHTML = comparison ? `
    <table class="comparison-table"><thead><tr><th>Control</th><th>Verdict</th><th>What it checks</th></tr></thead><tbody>
      <tr><td>Caps-only</td><td><span class="tag ${comparison.caps_only}">${comparison.caps_only}</span></td><td>Mandate and per-payment amount cap</td></tr>
      <tr><td>Policy-only</td><td><span class="tag ${comparison.policy_only}">${comparison.policy_only}</span></td><td>Deterministic rules, without semantic audit</td></tr>
      <tr><td>Anumati</td><td><span class="tag ${decision.verdict}">${decision.verdict}</span></td><td>Policy plus page-content and intent-drift audit</td></tr>
    </tbody></table>` : "";
}

// ---------------------------------------------------------------- mandates
async function loadMandates() {
  mandates = await api(`/v1/mandates?user_id=${encodeURIComponent(DEMO_USER)}`);
  $("#sandboxMandate").innerHTML = mandates.filter((m) => m.status === "active" && m.demo_fixture).map((m) => `<option value="${m.id}">${m.id} — ${esc(m.natural_language.slice(0, 60))}…</option>`).join("");
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
    draft = await api("/v1/mandates/compile", { method: "POST", body: { user_id: $("#mUser").value, agent_id: $("#mAgent").value, text: $("#mandateText").value, ttl_days: Number($("#mTtl").value), sandbox: true } });
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
  const caller = identity;
  if (!caller) return;
  rows = rows || await api(`/v1/stepups?user_id=${encodeURIComponent(DEMO_USER)}&status=pending`);
  $("#suCount").textContent = rows.length;
  const enriched = await Promise.all(rows.map(async (stepup) => {
    try {
      const [decision, mandate] = await Promise.all([
        api(`/v1/decisions/${stepup.decision_id}`), api(`/v1/mandates/${stepup.mandate_id}`),
      ]);
      return { stepup, decision, mandate };
    } catch { return { stepup, decision: null, mandate: null }; }
  }));
  if (caller !== identity) return;
  $("#stepupList").innerHTML = enriched.length ? enriched.map(({ stepup, decision, mandate }) => {
    const guardrails = mandate?.guardrails || {};
    const rule = guardrails.step_up_above && stepup.amount > guardrails.step_up_above
      ? `Confirmation required above ${inr(guardrails.step_up_above)}.`
      : `Review required by the active mandate and risk findings.`;
    const cart = decision?.request?.cart || [];
    return `
      <article class="stepup-card">
        <div class="stepup-summary"><div><span class="tag pending">PENDING · STEP_UP</span> <span class="tag">risk ${stepup.risk_score}/100</span></div>
          <h3>${inr(stepup.amount)} to ${esc(stepup.payee_name)}</h3><p class="mono-inline">${esc(stepup.payee_vpa)}</p>
          <p><b>Mandate rule</b><br>${esc(rule)} ${esc(mandate?.natural_language || "")}</p>
          <p><b>Why it was paused</b></p><ul class="notes">${(stepup.reasons || []).map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul>
          ${cart.length ? `<p><b>Requested basket</b></p><ul class="cart-lines">${cart.map((item) => `<li>${item.qty}× ${esc(item.name)} · ${inr(item.unit_price)} each</li>`).join("")}</ul>` : ""}
          <div class="meta">${stepup.id} · agent ${esc(stepup.agent_id)} · ${new Date(stepup.created_at).toLocaleTimeString()}</div>
        </div>
        <div class="decision-buttons"><button class="primary" data-su="${stepup.id}" data-ok="1">Approve payment</button><button class="secondary" data-su="${stepup.id}" data-ok="0">Decline payment</button></div>
      </article>`;
  }).join("") : `<p class="hint">Nothing pending. Any new borderline payment will appear here for review.</p>`;
  document.querySelectorAll("[data-su]").forEach((b) => b.onclick = async () => {
    const approve = b.dataset.ok === "1";
    document.querySelectorAll(`[data-su="${b.dataset.su}"]`).forEach((button) => { button.disabled = true; });
    try {
      const result = await api(`/v1/stepups/${b.dataset.su}/respond`, { method: "POST", body: { approve, note: approve ? "confirmed by account holder" : "declined by account holder" } });
      $("#stepupOutcome").hidden = false;
      $("#stepupOutcome").textContent = `Payment ${result.status}. The decision and receipt now record the account holder's response.`;
      await loadStepups(); refresh("feed");
    } catch (error) {
      $("#stepupOutcome").hidden = false;
      $("#stepupOutcome").textContent = `Could not record the response: ${error.message}`;
      document.querySelectorAll(`[data-su="${b.dataset.su}"]`).forEach((button) => { button.disabled = false; });
    }
  });
}

// ---------------------------------------------------------------- feed / receipts / disputes
async function loadFeed(rows) {
  rows = rows || await api(`/v1/decisions?user_id=${encodeURIComponent(DEMO_USER)}&limit=40`);
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
function tamperReceiptAmount() {
  let r; try { r = JSON.parse($("#receiptView").value); } catch { return; }
  const before = r.attempted?.amount;
  if (r.attempted && typeof r.attempted.amount === "number") r.attempted.amount = r.attempted.amount + 1000;
  else return;
  $("#receiptView").value = JSON.stringify(r, null, 2);
  $("#verifyResult").innerHTML = `<div class="warn">Changed <code>attempted.amount</code> from ₹${before} to ₹${r.attempted.amount} — a single rupee-field edit. Now re-verifying…</div>`;
  setTimeout(() => verifyCurrentReceipt(false), 400);
}
$("#tamperBtn").addEventListener("click", tamperReceiptAmount);
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
    ${isStaff() || d.sandbox ? `<div class="row"><button class="primary tiny" id="resolveBtn">${d.sandbox && !isStaff() ? "Close simulated case" : "Close case with this attribution"}</button></div>` : ""}</div>`;
  if ($("#resolveBtn")) $("#resolveBtn").onclick = async () => {
    try {
      const prefix = d.sandbox && !isStaff() ? "/sim" : "/v1";
      await api(`${prefix}/disputes/${d.id}/resolve`, { method: "POST", body: { resolution: "closed per attribution memo", party: a.primary_party } });
      toast(`<b>Dispute ${d.id} resolved${prefix === "/sim" ? " (simulated)" : ""}</b>`); loadDisputes();
    } catch (e) { toast(`<b>Resolution failed</b><br>${esc(e.message)}`); }
  };
}
async function loadDisputes() {
  const rows = await api("/v1/disputes");
  $("#disputeList").innerHTML = rows.map((d) => `<div class="item"><div><span class="tag ${d.status}">${d.status}</span> ${esc(d.claim.slice(0, 90))} <div class="meta">${d.id} · by ${d.raised_by} · → ${esc(d.attribution.primary_party)}</div></div>
    <div class="actions"><button class="secondary tiny" data-dv="${d.id}">View</button></div></div>`).join("");
  document.querySelectorAll("[data-dv]").forEach((b) => b.onclick = async () => renderDispute(await api(`/v1/disputes/${b.dataset.dv}`)));
}

function refresh(tab) {
  if (!identity) return;
  if (tab === "stepups") loadStepups().catch(() => {});
  if (tab === "feed") loadFeed().catch(() => {});
  if (tab === "receipts") loadReceipts().catch(() => {});
  if (tab === "disputes") loadDisputes().catch(() => {});
  if (tab === "mandates") loadMandates().catch(() => {});
}

// ---------------------------------------------------------------- realtime (Firestore) or polling
async function realtime() {
  const caller = identity;
  if (!caller) return;
  const poll = () => {
    if (identity !== caller) return;
    stopRealtime();
    $("#rtBadge").textContent = "realtime: polling"; $("#rtBadge").className = "badge muted";
    pollingTimer = setInterval(() => { loadStepups().catch(() => {}); loadFeed().catch(() => {}); }, 4000);
  };
  if (caller.mode !== "firebase" || storeBackend !== "firestore") { poll(); return; }
  try {
    const { getFirestore, collection, query, where, orderBy, onSnapshot, limit } = await import("https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js");
    if (identity !== caller) return;
    const db = getFirestore(caller.app);
    const failed = (e) => { if (identity !== caller) return; console.warn("Firestore realtime unavailable; using authenticated API polling", e.code); poll(); };
    unsubscribeRealtime.push(onSnapshot(query(collection(db, "stepups"), where("user_id", "==", DEMO_USER), where("status", "==", "pending"), orderBy("created_at", "desc")),
      (snap) => { if (identity !== caller) return; const rows = snap.docs.map((d) => d.data()); loadStepups(rows); if (snap.docChanges().some((c) => c.type === "added")) toast(`<b>Confirmation needed</b><br>An agent payment is waiting for your one-tap approval.`); }, failed));
    unsubscribeRealtime.push(onSnapshot(query(collection(db, "decisions"), where("request.user_id", "==", DEMO_USER), orderBy("created_at", "desc"), limit(40)),
      (snap) => { if (identity === caller) loadFeed(snap.docs.map((d) => d.data())); }, failed));
    $("#rtBadge").textContent = "realtime: Firestore"; $("#rtBadge").className = "badge ok";
  } catch (e) { console.warn("Firestore realtime unavailable; using authenticated API polling", e.code); poll(); }
}

// ---------------------------------------------------------------- guided demo walkthrough
// Drives the *real* console through the canonical story (PRD §4/§8):
// mandate → clean approve → injected block → step-up decline → dispute → tamper-proof receipt.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function demoHighlight(sel) {
  document.querySelectorAll(".demo-highlight").forEach((e) => e.classList.remove("demo-highlight"));
  const el = sel && (typeof sel === "string" ? $(sel) : sel);
  if (el) { el.classList.add("demo-highlight"); el.scrollIntoView({ behavior: "smooth", block: "center" }); }
}
async function demoRunScenario(key) {
  scenario = key; renderScenarios(); await showMerchant();
  lastRun = await api("/sim/run", { method: "POST", body: { mandate_id: $("#sandboxMandate").value, scenario: key, mode: "naive", fresh: key === "clean" } });
  renderResult(lastRun); refresh("feed");
  return lastRun.decisions[lastRun.decisions.length - 1];
}

const demo = { steps: [], i: -1, playing: false, timer: null, ctx: {} };

function buildDemoSteps() {
  const ctx = demo.ctx = {};
  return [
    { hold: 5500, cap: "<b>1 · The mandate.</b> The human delegated to an agent in one sentence; Gemini compiled it into signed guardrails — ₹2,000/order, ₹3,000/week, FreshKart or Zepto only, no new payees, confirm above ₹1,500. A valid mandate proves <i>authorisation</i>, not <i>faithfulness</i>.",
      act: async () => { switchTab("mandates"); await loadMandates(); demoHighlight("#mandateList .item"); } },
    { hold: 5500, cap: "<b>2 · Clean run → APPROVE.</b> The agent does the weekly grocery run at a mandated merchant, to the verified payee. Anumati clears it to the rail in a millisecond and issues a signed receipt.",
      act: async () => { switchTab("sandbox"); await demoRunScenario("clean"); demoHighlight("#result"); } },
    { hold: 7000, cap: "<b>3 · Hidden-text redirect → BLOCK.</b> An invisible &lt;div&gt; tells the agent the UPI id 'migrated' to a mule VPA. The mandate is still valid and the agent still authenticated — but Anumati BLOCKs: payee not verified for the merchant, suspect-registry hit, and the injected text captured verbatim as evidence.",
      act: async () => { const d = await demoRunScenario("hidden_injection"); ctx.blockedDecisionId = d.id; ctx.blockedReceiptId = d.receipt_id; demoHighlight("#result"); } },
    { hold: 7000, cap: "<b>4 · Review injection → STEP_UP → declined.</b> A poisoned 'review' insists the agent add 12 jars of ghee. No hard rule is broken, so Anumati holds it rather than guessing — the account holder gets a one-tap prompt and declines.",
      act: async () => {
        const d = await demoRunScenario("review_upsell_injection"); ctx.stepupId = d.stepup_id;
        await sleep(1400); switchTab("stepups"); await loadStepups(); demoHighlight("#stepupList .stepup-card");
        await sleep(1800);
        if (ctx.stepupId) { await api(`/v1/stepups/${ctx.stepupId}/respond`, { method: "POST", body: { approve: false, note: "declined by account holder" } }); await loadStepups(); refresh("feed"); }
      } },
    { hold: 7000, cap: "<b>5 · Dispute → liability attribution.</b> Later a dispute is raised on the blocked payment. Anumati replays the signed receipt and drafts a neutral attribution across user / agent / merchant / issuer — here the merchant/content provider, with the injected text as evidence. A human closes the case.",
      act: async () => {
        switchTab("disputes");
        $("#dDecision").value = ctx.blockedDecisionId || "";
        $("#dClaim").value = "I never authorised this payee. My mandate said FreshKart only.";
        if (ctx.blockedDecisionId) { const dsp = await api("/v1/disputes", { method: "POST", body: { decision_id: ctx.blockedDecisionId, raised_by: "user", claim: $("#dClaim").value } }); renderDispute(dsp); }
        demoHighlight("#disputeView");
      } },
    { hold: 8000, cap: "<b>6 · Tamper-proof evidence.</b> Every verdict is a signed, hash-chained receipt — the artifact a dispute is settled on. Watch: change a single rupee and the HMAC breaks. It verifies offline, in any language, without trusting the gateway.",
      act: async () => {
        switchTab("receipts"); await loadReceipts();
        if (ctx.blockedReceiptId) { await openReceipt(ctx.blockedReceiptId); demoHighlight("#receiptView"); await sleep(2200); tamperReceiptAmount(); }
      } },
    { hold: 99999, cap: "<b>✓ That's Anumati.</b> mandate → approve → block → step-up → dispute → tamper-proof evidence. A deterministic policy engine fused with a Gemini semantic audit, with a signed receipt for every decision — the trust and liability layer for agentic UPI payments. <i>Press Replay to run it again.</i>",
      act: async () => { demoHighlight(null); $("#demoNext").textContent = "↻ Replay"; } },
  ];
}
function demoShowCaption() {
  const s = demo.steps[demo.i];
  $("#demoCaption").innerHTML = s.cap;
  $("#demoStep").textContent = `${demo.i + 1}/${demo.steps.length}`;
  $("#demoProgress").textContent = demo.steps.map((_, k) => (k <= demo.i ? "●" : "○")).join("");
}
async function demoGo(i) {
  if (demo.busy) return;            // ignore clicks/timers while a step is running (prevents overlap)
  demo.busy = true;
  clearTimeout(demo.timer);
  if (i >= demo.steps.length) i = demo.steps.length - 1;
  demo.i = i;
  if (demo.i < demo.steps.length - 1) $("#demoNext").textContent = "Next ›";
  $("#demoNext").disabled = true;
  demoShowCaption();
  try { await demo.steps[demo.i].act(); }
  catch (e) { $("#demoCaption").innerHTML += ` <span class="demo-err">— ${esc(e.message)}</span>`; }
  demo.busy = false;
  $("#demoNext").disabled = false;
  if (demo.playing && demo.i < demo.steps.length - 1) demo.timer = setTimeout(() => demoGo(demo.i + 1), demo.steps[demo.i].hold);
}
function demoStart() {
  demo.steps = buildDemoSteps(); demo.playing = true; demo.busy = false; demo.i = -1;
  $("#demoBar").hidden = false; $("#guidedBtn").classList.add("running");
  $("#demoPlay").textContent = "⏸ Pause"; $("#demoNext").disabled = false;
  demoGo(0);
}
function demoExit() { clearTimeout(demo.timer); demo.playing = false; demo.busy = false; demo.i = -1; $("#demoBar").hidden = true; $("#guidedBtn").classList.remove("running"); demoHighlight(null); }
$("#guidedBtn").addEventListener("click", () => (demo.i === -1 ? demoStart() : demoExit()));
$("#demoStop").addEventListener("click", demoExit);
$("#demoNext").addEventListener("click", () => { if (demo.i >= demo.steps.length - 1) { demoGo(0); } else { demoGo(demo.i + 1); } });
$("#demoPlay").addEventListener("click", () => {
  demo.playing = !demo.playing; $("#demoPlay").textContent = demo.playing ? "⏸ Pause" : "▶ Play";
  if (demo.playing && demo.i < demo.steps.length - 1) demo.timer = setTimeout(() => demoGo(demo.i + 1), 1200);
  else clearTimeout(demo.timer);
});

boot();
