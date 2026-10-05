const list = document.getElementById("list");
const detail = document.getElementById("detail");
const pick = document.getElementById("incidentPick");
const fireBtn = document.getElementById("fireBtn");
const fireStatus = document.getElementById("fireStatus");
document.getElementById("refreshBtn").onclick = () => { refreshList(); if (openId) show(openId, true); };

let openId = null;
const ALL_NODES = ["triage", "observability", "rag", "rca", "remediation", "approval", "execute", "verify"];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function apiHeaders(extra) {
  const h = { "Content-Type": "application/json", ...(extra || {}) };
  try {
    const k = localStorage.getItem("opsmind_api_key");
    if (k) h["X-API-Key"] = k;
  } catch (_) { /* private mode */
  }
  return h;
}

async function loadSamples() {
  const ids = [];
  for (let i = 1; i <= 12; i++) ids.push("incident_" + String(i).padStart(3, "0"));
  pick.innerHTML = ids.map((id) => `<option>${esc(id)}</option>`).join("");
}

async function refreshList() {
  const res = await fetch("/incidents", { headers: apiHeaders() }).then((r) => r.json()).catch(() => []);
  const rows = Array.isArray(res) ? res : [];
  list.innerHTML = "<h3>Investigated</h3>" + (rows.length === 0
    ? `<p class="muted">Nothing yet. Fire one above.</p>`
    : rows.map((r) => `<div class="card"><b>${esc(r.id)}</b> <span class="pill ${r.severity === "P1" ? "p1" : "p2"}">${esc(r.severity ?? "")}</span><br/><span class="muted">${esc(r.service)} · ${esc(r.status)}</span><br/><button data-id="${esc(r.id)}">Open</button></div>`).join(""));
  list.querySelectorAll("button").forEach((b) => (b.onclick = () => { openId = b.dataset.id; show(openId); }));
}

function traceHtml(trace) {
  const ran = new Set((trace ?? []).map((t) => t.node));
  // execute/verify run only after approval; approval rendered as waiting when paused there
  const waiting = ran.has("approval") && !ran.has("execute");
  return `<div class="steps">` + ALL_NODES.map((n) => {
    const cls = ran.has(n) ? (n === "approval" && waiting ? "step wait" : "step done") : "step";
    const at = (trace ?? []).find((t) => t.node === n)?.at?.slice(11, 19) ?? "";
    return `<span class="${cls}" title="${esc(at)}">${esc(n)}${at ? `<br/><span class="muted">${esc(at)}</span>` : ""}</span>`;
  }).join("") + `</div>`;
}

function hypothesesHtml(hyps, rootCause) {
  return (hyps ?? []).map((h) => `
    <div class="hyp ${h.root_cause === rootCause ? "top" : ""}">
      <b>${esc(h.root_cause)}</b> <span class="muted">${Math.round(Number(h.confidence ?? 0) * 100)}%</span><br/>
      <span class="muted">for: ${esc((h.supporting ?? []).join("; ") || "—")}</span><br/>
      <span class="muted">against: ${esc((h.contradicting ?? []).join("; ") || "—")}</span>
    </div>`).join("");
}

async function show(id, quiet) {
  const s = await fetch("/incidents/" + encodeURIComponent(id), { headers: apiHeaders() }).then((r) => (r.ok ? r.json() : null));
  if (!s) { if (!quiet) detail.innerHTML = `<p class="muted">Incident not found.</p>`; return; }
  const needsApproval = s.approval_status === "awaiting_human";
  const v = s.verification_result;
  const plan = s.remediation_plan ?? {};
  const confPct = Math.max(0, Math.min(100, Math.round((Number(s.confidence ?? 0)) * 100)));
  detail.innerHTML = `
    <div class="card">
      <h3>${esc(s.incident?.incident_id)} <span class="pill ${s.severity === "P1" ? "p1" : "p2"}">${esc(s.severity)}</span></h3>
      <p class="muted">${esc(s.incident?.service)} · ${esc(s.incident?.alert_type)}</p>
      ${traceHtml(s.trace)}
      <p><b>Root cause:</b> ${esc(s.root_cause ?? "—")}</p>
      <div class="bar"><div style="width:${confPct}%"></div></div>
      <p><b>Fix:</b> ${esc(plan.action ?? "—")} <span class="pill ${s.risk_level === "low" ? "low" : "med"}">${esc(s.risk_level ?? "")}</span>
      <span class="muted">${esc(plan.params ? JSON.stringify(plan.params) : "")}</span></p>
      <p class="muted">Approval: ${esc(s.approval_status)}${s.approved_by ? ` by ${esc(s.approved_by)}` : ""}</p>
      ${needsApproval ? `<button id="approveBtn">Approve & execute</button>` : ""}
      ${v ? `<p><b>Verification:</b> error ${esc(v.before)} &rarr; ${esc(v.after)} — ${v.healthy ? "healthy" : "still failing"}</p>` : `<p class="muted">Not executed yet.</p>`}
      <h4>Hypotheses</h4>
      ${hypothesesHtml(s.hypotheses, s.root_cause)}
      <h4>Evidence (${(s.evidence ?? []).length})</h4>
      <pre>${esc(JSON.stringify((s.evidence ?? []).slice(0, 4), null, 2))}</pre>
    </div>`;
  const btn = document.getElementById("approveBtn");
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    try {
      const body = { approved_by: "dashboard" };
      const h = await planHash(s.remediation_plan).catch(() => null);
      if (h) body.plan_hash = h;
      const headers = apiHeaders();
      headers["X-Approver"] = "dashboard";
      const r = await fetch(`/incidents/${encodeURIComponent(id)}/approve`, { method: "POST", headers, body: JSON.stringify(body) });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        fireStatus.textContent = `approve failed: ${r.status} ${detail.detail ?? ""}`.trim();
      }
    } catch (e) {
      fireStatus.textContent = `approve failed: ${e}`;
    }
    refreshList();
    show(id);
  };
}

// plan_hash parity with server (sha256 of JSON with sorted keys, ", "/": " separators, first 16 hex).
// Best-effort: crypto.subtle needs a secure context; without it we omit plan_hash
// and the server approves without binding (still logged in the audit trail).
function stableStringify(v) {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(stableStringify).join(", ") + "]";
  return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ": " + stableStringify(v[k])).join(", ") + "}";
}

async function planHash(plan) {
  if (!plan || !crypto.subtle) return null;
  const bytes = new TextEncoder().encode(stableStringify(plan));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

fireBtn.onclick = async () => {
  fireBtn.disabled = true;
  fireStatus.textContent = "investigating…";
  try {
    const id = pick.value;
    const demo = await fetch(`/demo/${encodeURIComponent(id)}.json`, { headers: apiHeaders() }).then((r) => (r.ok ? r.json() : null));
    const body = demo ?? { incident_id: id, service: "payment-api", environment: "production", alert_type: "db_pool_exhaustion", metrics: { error_rate: 0.28 } };
    const out = await fetch("/incidents", { method: "POST", headers: apiHeaders(), body: JSON.stringify(body) }).then((r) => r.json());
    fireStatus.textContent = `done: ${out.root_cause ?? out.detail ?? out.error ?? "see list"}`;
    fireBtn.disabled = false;
    openId = out.incident?.incident_id ?? null;
    refreshList();
    if (openId) show(openId);
  } catch (e) {
    fireStatus.textContent = `failed: ${e}`;
    fireBtn.disabled = false;
  }
};

loadSamples();
refreshList();
setInterval(() => { refreshList(); }, 15000);
