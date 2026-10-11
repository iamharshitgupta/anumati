/* Anumati console — vanilla JS, no build step.
   Talks to the Cloud Run API; attaches Firestore realtime listeners when a
   Firebase config is present, otherwise polls. */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });

// ---------------------------------------------------------------- API base
const stored = localStorage.getItem("anumati.api");
let API = stored ?? (window.ANUMATI_API_BASE || (location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:" ? "http://localhost:8080" : ""));
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
let walkthroughStep = -1;
let openedReceiptId = null;
const DEMO_USER = "user_demo";
const WALKTHROUGH = [
  { scenario: "clean", title: "A normal payment", reason: "The verified payee and basket fit the active mandate." },
  { scenario: "hidden_injection", title: "A page tries to redirect payment", reason: "The new payee and page instruction do not match the merchant in the mandate." },
  { scenario: "review_upsell_injection", title: "A human reviews a borderline basket", reason: "The page steers the agent to add an unusual quantity, so Anumati pauses for confirmation." },
];

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
async function runScenario() {
  const btn = $("#runBtn"); btn.disabled = true; btn.textContent = "Agent is shopping…";
  try {
    lastRun = await api("/sim/run", { method: "POST", body: { mandate_id: $("#sandboxMandate").value, scenario, mode: $("#agentMode").value } });
    renderResult(lastRun); refresh("stepups"); refresh("feed");
  } catch (e) { toast(`<b>Run failed</b><br>${esc(e.message)}`); }
  btn.disabled = false; btn.textContent = "Run attack through Anumati →";
  renderWalkthrough();
}
$("#runBtn").addEventListener("click", runScenario);
$("#startWalkthrough").addEventListener("click", startWalkthrough);
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
  renderWalkthrough();
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

function renderWalkthrough() {
  const panel = $("#walkthrough");
  if (walkthroughStep < 0) { panel.hidden = true; return; }
  panel.hidden = false;
  if (walkthroughStep >= WALKTHROUGH.length) {
    panel.innerHTML = `<b>Guided demo complete</b><p>You saw a normal approval, a redirected-payee block, and a payment held for human confirmation.</p><button id="restartWalkthrough" class="secondary" type="button">Run it again</button>`;
    $("#restartWalkthrough").onclick = startWalkthrough;
    return;
  }
  const step = WALKTHROUGH[walkthroughStep];
  const hasResult = lastRun?.scenario === step.scenario;
  panel.innerHTML = `<div><strong>Guided demo · ${walkthroughStep + 1} of ${WALKTHROUGH.length}</strong><p>${esc(step.title)}. ${esc(step.reason)}</p></div>
    ${hasResult ? `<button id="walkthroughNext" class="secondary" type="button">${walkthroughStep === 2 ? "Review step-up" : "Next step"}</button>` : `<span class="hint">Run this step to continue.</span>`}`;
  const next = $("#walkthroughNext");
  if (next) next.onclick = () => {
    if (walkthroughStep === 2) { switchTab("stepups"); return; }
    walkthroughStep += 1;
    scenario = WALKTHROUGH[walkthroughStep].scenario;
    renderScenarios(); showMerchant(); renderWalkthrough();
  };
}

function startWalkthrough() {
  walkthroughStep = 0;
  lastRun = null;
  scenario = WALKTHROUGH[0].scenario;
  renderScenarios(); showMerchant(); renderWalkthrough();
}

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
  const enriched = await Promise.all(rows.map(async (stepup) => {
    try {
      const [decision, mandate] = await Promise.all([
        api(`/v1/decisions/${stepup.decision_id}`), api(`/v1/mandates/${stepup.mandate_id}`),
      ]);
      return { stepup, decision, mandate };
    } catch { return { stepup, decision: null, mandate: null }; }
  }));
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
      if (!approve && walkthroughStep === 2) { walkthroughStep = WALKTHROUGH.length; switchTab("sandbox"); renderWalkthrough(); }
    } catch (error) {
      $("#stepupOutcome").hidden = false;
      $("#stepupOutcome").textContent = `Could not record the response: ${error.message}`;
      document.querySelectorAll(`[data-su="${b.dataset.su}"]`).forEach((button) => { button.disabled = false; });
    }
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
async function openReceipt(id) {
  const response = await fetch(`${API}/v1/receipts/${id}`);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const rawReceipt = await response.text();
  const receipt = JSON.parse(rawReceipt);
  openedReceiptId = id;
  $("#receiptView").textContent = JSON.stringify(receipt, null, 2);
  $("#verifyReceiptInput").value = rawReceipt;
  $("#reloadReceiptBtn").disabled = false;
  showReceiptVerification(receipt.signature_valid, "Loaded receipt signature");
}
function showReceiptVerification(valid, label) {
  const result = $("#receiptVerifyResult");
  result.hidden = false;
  result.className = `action-outcome ${valid ? "success" : "failure"}`;
  result.textContent = `${label}: ${valid ? "VALID" : "INVALID"}${valid ? " — receipt data matches its signature." : " — receipt data does not match its signature."}`;
}
async function verifyReceipt() {
  try {
    const payload = $("#verifyReceiptInput").value.trim();
    const receipt = JSON.parse(payload);
    if (!receipt || Array.isArray(receipt) || typeof receipt !== "object") throw new Error("Receipt must be a JSON object.");
    const response = await fetch(`${API}/v1/receipts/verify`, { method: "POST", headers: { "content-type": "application/json" }, body: payload });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    const result = await response.json();
    showReceiptVerification(result.valid, "Signature verification");
  } catch (error) {
    const result = $("#receiptVerifyResult");
    result.hidden = false;
    result.className = "action-outcome failure";
    result.textContent = `Could not verify receipt: ${error.message}`;
  }
}
$("#verifyReceiptBtn").addEventListener("click", verifyReceipt);
$("#reloadReceiptBtn").addEventListener("click", () => {
  if (openedReceiptId) openReceipt(openedReceiptId).catch((error) => toast(`<b>Could not reload receipt</b><br>${esc(error.message)}`));
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
