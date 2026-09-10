const list = document.getElementById("list");
const detail = document.getElementById("detail");
const pick = document.getElementById("incidentPick");
const fireBtn = document.getElementById("fireBtn");
const fireStatus = document.getElementById("fireStatus");
document.getElementById("refreshBtn").onclick = () => { refreshList(); if (openId) show(openId, true); };

let openId = null;
const ALL_NODES = ["triage", "observability", "rag", "rca", "remediation", "approval", "execute", "verify"];

async function loadSamples() {
  const ids = [];
  for (let i = 1; i <= 12; i++) ids.push("incident_" + String(i).padStart(3, "0"));
  pick.innerHTML = ids.map((id) => `<option>${id}</option>`).join("");
}

async function refreshList() {
  const res = await fetch("/incidents").then((r) => r.json()).catch(() => []);
  list.innerHTML = "<h3>Investigated</h3>" + (res.length === 0
    ? `<p class="muted">Nothing yet. Fire one above.</p>`
    : res.map((r) => `<div class="card"><b>${r.id}</b> <span class="pill ${r.severity === "P1" ? "p1" : "p2"}">${r.severity ?? ""}</span><br/><span class="muted">${r.service} · ${r.status}</span><br/><button data-id="${r.id}">Open</button></div>`).join(""));
  list.querySelectorAll("button").forEach((b) => (b.onclick = () => { openId = b.dataset.id; show(openId); }));
}

function traceHtml(trace) {
  const ran = new Set((trace ?? []).map((t) => t.node));
  // execute/verify run only after approval; approval rendered as waiting when paused there
  const waiting = ran.has("approval") && !ran.has("execute");
  return `<div class="steps">` + ALL_NODES.map((n) => {
    const cls = ran.has(n) ? (n === "approval" && waiting ? "step wait" : "step done") : "step";
    const at = (trace ?? []).find((t) => t.node === n)?.at?.slice(11, 19) ?? "";
    return `<span class="${cls}" title="${at}">${n}${at ? `<br/><span class="muted">${at}</span>` : ""}</span>`;
  }).join("") + `</div>`;
}

function hypothesesHtml(hyps, rootCause) {
  return (hyps ?? []).map((h) => `
    <div class="hyp ${h.root_cause === rootCause ? "top" : ""}">
      <b>${h.root_cause}</b> <span class="muted">${Math.round(h.confidence * 100)}%</span><br/>
      <span class="muted">for: ${(h.supporting ?? []).join("; ") || "—"}</span><br/>
      <span class="muted">against: ${(h.contradicting ?? []).join("; ") || "—"}</span>
    </div>`).join("");
}

async function show(id, quiet) {
  const s = await fetch("/incidents/" + id).then((r) => (r.ok ? r.json() : null));
  if (!s) { if (!quiet) detail.innerHTML = `<p class="muted">Incident not found.</p>`; return; }
  const needsApproval = s.approval_status === "awaiting_human";
  const v = s.verification_result;
  const plan = s.remediation_plan ?? {};
  detail.innerHTML = `
    <div class="card">
      <h3>${s.incident.incident_id} <span class="pill ${s.severity === "P1" ? "p1" : "p2"}">${s.severity}</span></h3>
      <p class="muted">${s.incident.service} · ${s.incident.alert_type}</p>
      ${traceHtml(s.trace)}
      <p><b>Root cause:</b> ${s.root_cause ?? "—"}</p>
      <div class="bar"><div style="width:${Math.round((s.confidence ?? 0) * 100)}%"></div></div>
      <p><b>Fix:</b> ${plan.action ?? "—"} <span class="pill ${s.risk_level === "low" ? "low" : "med"}">${s.risk_level ?? ""}</span>
      <span class="muted">${plan.params ? JSON.stringify(plan.params) : ""}</span></p>
      <p class="muted">Approval: ${s.approval_status}${s.approved_by ? ` by ${s.approved_by}` : ""}</p>
      ${needsApproval ? `<button id="approveBtn">Approve & execute</button>` : ""}
      ${v ? `<p><b>Verification:</b> error ${v.before} &rarr; ${v.after} — ${v.healthy ? "healthy" : "still failing"}</p>` : `<p class="muted">Not executed yet.</p>`}
      <h4>Hypotheses</h4>
      ${hypothesesHtml(s.hypotheses, s.root_cause)}
      <h4>Evidence (${(s.evidence ?? []).length})</h4>
      <pre>${JSON.stringify((s.evidence ?? []).slice(0, 4), null, 2)}</pre>
    </div>`;
  const btn = document.getElementById("approveBtn");
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    await fetch(`/incidents/${id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    refreshList();
    show(id);
  };
}

fireBtn.onclick = async () => {
  fireBtn.disabled = true;
  fireStatus.textContent = "investigating…";
  const id = pick.value;
  const demo = await fetch(`/demo/${id}.json`).then((r) => (r.ok ? r.json() : null));
  const body = demo ?? { incident_id: id, service: "payment-api", environment: "production", alert_type: "db_pool_exhaustion", metrics: { error_rate: 0.28 } };
  const out = await fetch("/incidents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());
  fireStatus.textContent = `done: ${out.root_cause ?? out.error}`;
  fireBtn.disabled = false;
  openId = out.incident?.incident_id ?? null;
  refreshList();
  if (openId) show(openId);
};

loadSamples();
refreshList();
setInterval(refreshList, 8000);
