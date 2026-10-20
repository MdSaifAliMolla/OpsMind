const list = document.getElementById("list");
const detail = document.getElementById("detail");
const fireStatus = document.getElementById("fireStatus");
const refreshBtn = document.getElementById("refreshBtn");
const healthDot = document.getElementById("healthDot");
const healthText = document.getElementById("healthText");

refreshBtn.onclick = () => { refreshList(); if (openId) show(openId, true); };
let openId = null;
const ALL_NODES = ["triage", "observability", "rag", "rca", "remediation", "approval", "execute", "verify"];

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function apiHeaders(extra) {
  const h = { "Content-Type": "application/json", ...(extra || {}) };
  try {
    const k = localStorage.getItem("opsmind_api_key");
    if (k) h["X-API-Key"] = k;
  } catch (e) {}
  return h;
}

function sevPill(s) {
  const c = { P1: "p1", P2: "p2", P3: "p3", P4: "p4" }[s] || "p4";
  return `<span class="pill ${c}">${esc(s ?? "?")}</span>`;
}

const statusById = {};

function statusPill(st) {
  const m = {
    resolved: "st-ok", healthy: "st-ok", approved: "st-ok", auto_approved: "st-ok",
    awaiting_human: "st-wait", investigating: "st-wait", remediating: "st-wait",
    denied: "st-bad", failed: "st-bad", rejected: "st-bad", expired: "st-bad",
    unhealthy: "st-bad",
    escalated: "st-info",
  };
  return `<span class="pill ${m[st] || "st-idle"}">${esc(st ?? "?")}</span>`;
}

async function health() {
  try {
    const h = await fetch("/health").then((r) => r.json());
    healthDot.classList.toggle("down", !h.ok);
    healthText.textContent = h.ok ? `live · ${h.pending ?? 0} paused` : "unhealthy";
  } catch (e) {
    healthDot.classList.add("down");
    healthText.textContent = "unreachable";
  }
}

async function refreshList() {
  const res = await fetch("/incidents", { headers: apiHeaders() }).then((r) => r.json()).catch(() => []);
  const items = Array.isArray(res) ? res : [];
  for (const k of Object.keys(statusById)) delete statusById[k];
  for (const it of items) statusById[it.id] = it.status || "";
  let html = `<h4 style="margin-top:0">Investigated (${items.length})</h4>`;
  if (!items.length) {
    html += `<p class="muted">Nothing yet. Fire one above.</p>`;
  }
  for (const it of items.slice().reverse()) {
    const st = it.status || "";
    html += `<div class="listitem${openId === it.id ? " active" : ""}" data-id="${esc(it.id)}">
      <div><div class="id">${esc(it.id)}</div>
      <div class="meta">${esc(it.service || "")} · ${esc(it.namespace || "default")} · ${esc(it.severity || "?")}</div></div>
      <div>${statusPill(st)}</div></div>`;
  }
  list.innerHTML = html;
  list.querySelectorAll(".listitem").forEach((el) => {
    el.onclick = () => { openId = el.dataset.id; refreshList(); show(openId); };
  });
}

function traceHtml(trace, status) {
  const ran = new Set((trace || []).map((t) => t.node));
  const waiting = ran.has("approval") && !ran.has("execute");
  const dead = status === "denied" || status === "failed" || status === "rejected";
  const info = status === "escalated";
  return `<div class="steps">` + ALL_NODES.map((n) => {
    let cls = "step";
    if (ran.has(n)) cls += dead && n === "approval" ? " dead" : info && n === "approval" ? " info" : " done";
    else if (waiting && n === "execute") cls += " wait";
    const at = (trace || []).find((t) => t.node === n);
    const tip = at ? ` title="${esc(at.at || "")}"` : "";
    return `<span class="${cls}"${tip}>${esc(n)}</span>`;
  }).join("") + `</div>`;
}

function hypothesesHtml(hyps, rootCause) {
  if (!hyps || !hyps.length) return `<p class="muted">No hypotheses recorded.</p>`;
  return hyps.map((h) => {
    const top = h.root_cause === rootCause ? " top" : "";
    const conf = typeof h.confidence === "number" ? ` · ${Math.round(h.confidence * 100)}%` : "";
    return `<div class="hyp${top}"><b>${esc(h.root_cause)}</b><span class="conf">${esc(conf)}</span><br/>`
      + `<span class="muted">+ ${(h.supporting || []).map(esc).join("; ")}</span><br/>`
      + `<span class="muted">− ${(h.contradicting || []).map(esc).join("; ")}</span></div>`;
  }).join("");
}

function guidanceHtml(evidence) {
  const notes = (evidence || []).filter((e) => e && e.source === "human:guidance");
  if (!notes.length) return "";
  return `<h4>Human guidance</h4>` + notes.map((e) => {
    const t = typeof e.result === "string" ? e.result : (e.result && e.result.text) || JSON.stringify(e.result ?? "");
    return `<p class="mono" style="border-left:3px solid var(--ink);padding-left:0.6rem">${esc(t)}</p>`;
  }).join("");
}

async function show(id, quiet) {
  const s = await fetch("/incidents/" + encodeURIComponent(id), { headers: apiHeaders() }).then((r) => (r.ok ? r.json() : null));
  if (!s) { if (!quiet) detail.innerHTML = `<p class="muted">Incident not found.</p>`; return; }
  const st = s.approval_status || "";
  const needsDecision = st === "awaiting_human" || statusById[id] === "unhealthy";
  const v = s.verification_result;
  const plan = s.remediation_plan ?? {};
  const params = plan.params ?? {};
  const conf = Math.max(0, Math.min(100, Math.round(Number(s.confidence ?? 0) * 100)));
  const barCls = conf >= 80 ? "bar highc" : conf >= 50 ? "bar" : "bar lowc";

  let actionBlock = "";
  if (st === "escalated") {
    actionBlock = `<div class="esc"><h4>Escalated — needs a human engineer</h4>
      <p>The agent could not fix this safely. Its best estimate:</p>
      <p><b>Estimated cause:</b> ${esc(s.root_cause ?? "—")}</p>
      <p><b>Suggested fix:</b> ${esc(params.suggested_fix ?? plan.action ?? "—")}</p>
      ${params.reason ? `<p class="muted">${esc(params.reason)}</p>` : ""}
      <p class="muted">Full evidence bundle below — no action was executed.</p></div>`;
  } else if (st === "denied") {
    actionBlock = `<div class="deniedbox"><h4 style="margin-top:0;color:var(--red)">Denied</h4>
      <p class="muted" style="margin:0">Fix rejected${s.denied_by ? ` by ${esc(s.denied_by)}` : ""}`
      + `${s.deny_reason ? `: ${esc(s.deny_reason)}` : ""}. Nothing was executed.</p></div>`;
  } else {
    actionBlock = `<p><b>Fix:</b> ${esc(plan.action ?? "—")} `
      + `<span class="pill ${s.risk_level === "low" ? "low" : s.risk_level === "medium" ? "med" : "high"}">${esc(s.risk_level ?? "")}</span> `
      + `<span class="muted mono">${esc(params && Object.keys(params).length ? JSON.stringify(params) : "")}</span></p>`
      + `<p class="muted">Approval: ${esc(st)}${s.approved_by ? ` by ${esc(s.approved_by)}` : ""}</p>`;
  }

  detail.innerHTML = `
    <div class="card">
      <h3>${esc(s.incident?.incident_id)} ${sevPill(s.severity)} ${statusPill(st)}</h3>
      <p class="muted">${esc(s.incident?.service)} · ${esc(s.incident?.namespace ?? "default")} · ${esc(s.incident?.alert_type)}</p>
      ${traceHtml(s.trace, st)}
      <p><b>Root cause:</b> ${esc(s.root_cause ?? "—")}</p>
      <div class="${barCls}"><div style="width:${conf}%"></div></div>
      ${actionBlock}
      ${needsDecision ? `
        <label class="lbl" for="noteInput">Note for the agent (optional — sent back for one more RCA round on deny)</label>
        <textarea id="noteInput" placeholder="e.g. check the database, not the frontend"></textarea>
        <div class="btnrow">
          <button id="approveBtn">Approve &amp; execute</button>
          <button id="denyBtn" class="danger">Deny</button>
        </div>` : ""}
      ${v ? `<h4>Verification</h4><p class="verify">error ${esc(v.before)} &rarr; ${esc(v.after)} —
        ${v.healthy ? `<span class="good">healthy</span>` : `<span class="bad">still failing</span>`}</p>`
        : `<p class="muted">Not executed yet.</p>`}
      ${s.postmortem ? `<h4>Postmortem</h4><pre>${esc(s.postmortem)}</pre>` : ""}
      <h4>Hypotheses</h4>
      ${hypothesesHtml(s.hypotheses, s.root_cause)}
      ${guidanceHtml(s.evidence)}
      <h4>Evidence (${(s.evidence ?? []).length})</h4>
      <pre>${esc(JSON.stringify((s.evidence ?? []).slice(0, 4), null, 2))}</pre>
    </div>`;

  const noteVal = () => (document.getElementById("noteInput")?.value || "").trim().slice(0, 1000);

  const approveBtn = document.getElementById("approveBtn");
  if (approveBtn) approveBtn.onclick = async () => {
    approveBtn.disabled = true;
    try {
      const body = { approved_by: "dashboard" };
      const note = noteVal();
      if (note) body.note = note;
      const h = await planHash(s.remediation_plan).catch(() => null);
      if (h) body.plan_hash = h;
      const headers = apiHeaders();
      headers["X-Approver"] = "dashboard";
      const r = await fetch(`/incidents/${encodeURIComponent(id)}/approve`, { method: "POST", headers, body: JSON.stringify(body) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        fireStatus.textContent = `approve failed: ${r.status} ${d.detail ?? ""}`.trim();
      } else { fireStatus.textContent = ""; }
    } catch (e) {
      fireStatus.textContent = `approve failed: ${e}`;
    }
    refreshList();
    show(id);
  };

  const denyBtn = document.getElementById("denyBtn");
  if (denyBtn) denyBtn.onclick = async () => {
    denyBtn.disabled = true;
    try {
      const r = await fetch(`/incidents/${encodeURIComponent(id)}/deny`,
        { method: "POST", headers: apiHeaders(), body: JSON.stringify({ denied_by: "dashboard", note: noteVal() || null }) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        fireStatus.textContent = `deny failed: ${r.status} ${d.detail ?? ""}`.trim();
      } else {
        const d = await r.json().catch(() => ({}));
        fireStatus.textContent = d.rerun ? "note sent — agent re-investigating…" : "denied.";
      }
    } catch (e) {
      fireStatus.textContent = `deny failed: ${e}`;
    }
    refreshList();
    show(id);
  };
}

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

const metricsStrip = document.getElementById("metricsStrip");
const costSpark = document.getElementById("costSpark");
const sparkCost = [];
const sparkSuccess = [];

function metricVal(text, name, labels) {
  const lines = text.split("\n");
  for (const ln of lines) {
    if (!ln.startsWith(name + "{") && ln !== name && !ln.startsWith(name + " ")) continue;
    if (labels && !ln.includes(labels)) continue;
    const m = ln.trim().split(/\s+/);
    const v = parseFloat(m[m.length - 1]);
    if (!isNaN(v)) return v;
  }
  return null;
}

function fmtUSD(v) { return v == null ? "—" : "$" + v.toFixed(4); }
function fmtPct(v) { return v == null ? "—" : (v * 100).toFixed(1) + "%"; }
function fmtInt(v) { return v == null ? "—" : String(Math.round(v)); }

function drawSpark() {
  if (!costSpark || !costSpark.getContext) return;
  const ctx = costSpark.getContext("2d");
  const W = costSpark.width, H = costSpark.height;
  ctx.clearRect(0, 0, W, H);
  const series = [sparkCost, sparkSuccess];
  const colors = ["#161616", "#9a9a9a"];
  series.forEach((data, si) => {
    if (data.length < 2) return;
    const mx = Math.max(...data, 1e-9);
    ctx.strokeStyle = colors[si];
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = (i / (data.length - 1)) * (W - 4) + 2;
      const y = H - 4 - (v / mx) * (H - 10);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  });
}

async function refreshMetrics() {
  let text = "";
  try {
    text = await fetch("/metrics", { headers: apiHeaders() }).then((r) => r.text());
  } catch (e) {}
  if (!text) return;
  let toks = 0;
  for (const ln of text.split("\n")) {
    if (ln.startsWith("opsmind_llm_tokens_total{")) {
      const v = parseFloat(ln.trim().split(/\s+/).pop());
      if (!isNaN(v)) toks += v;
    }
  }
  const cost = metricVal(text, "opsmind_llm_cost_usd_total");
  const calls = metricVal(text, "opsmind_llm_calls_total");
  const errs = metricVal(text, "opsmind_llm_errors_total");
  const succ = metricVal(text, "opsmind_agent_success_rate");
  const sev = metricVal(text, "opsmind_eval_severity_accuracy");
  const rca = metricVal(text, "opsmind_eval_rca_accuracy");
  metricsStrip.innerHTML =
    `<div class="metric"><div class="k">LLM cost</div><div class="v">${fmtUSD(cost)}</div></div>` +
    `<div class="metric"><div class="k">Tokens</div><div class="v">${fmtInt(toks)}</div></div>` +
    `<div class="metric"><div class="k">LLM calls</div><div class="v">${fmtInt(calls)}</div></div>` +
    `<div class="metric"><div class="k">LLM errors</div><div class="v">${fmtInt(errs)}</div></div>` +
    `<div class="metric"><div class="k">Success rate</div><div class="v">${fmtPct(succ)}</div></div>` +
    `<div class="metric"><div class="k">Eval sev / RCA</div><div class="v">${fmtPct(sev)} / ${fmtPct(rca)}</div></div>`;
  if (cost != null) { sparkCost.push(cost); if (sparkCost.length > 40) sparkCost.shift(); }
  if (succ != null) { sparkSuccess.push(succ); if (sparkSuccess.length > 40) sparkSuccess.shift(); }
  drawSpark();
}

health();
refreshList();
refreshMetrics();
setInterval(() => { refreshList(); health(); refreshMetrics(); if (openId) show(openId, true); }, 15000);
