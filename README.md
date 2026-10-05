# OpsMind — Autonomous Incident-Response Agent

![ci-cd](https://github.com/MdSaifAliMolla/OpsMind/actions/workflows/ci-cd.yml/badge.svg)

OpsMind is an on-call engineer in software. Hand it an infrastructure alert, and it
figures out what's wrong, proposes a fix, waits for approval, applies it, checks
that it actually worked, and writes the postmortem. The whole thing runs on Kubernetes
with real observability.

## Contents

- [How it works](#how-it-works)
- [Results](#results)
- [Try it](#try-it)
- [Full stack with Docker Compose](#full-stack-with-docker-compose)
- [Live end-to-end demo](#live-end-to-end-demo)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Agent in detail](#agent-in-detail)
- [RAG in detail](#rag-in-detail)
- [ML in detail](#ml-in-detail)
- [Evaluation](#evaluation)
- [Observability](#observability)
- [Safety model](#safety-model)
- [CI/CD and deploy](#cicd-and-deploy)
- [Project layout](#project-layout)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [What's next](#whats-next)

## How it works

An alert comes in through the API (or straight from Alertmanager), and then:

1. **Triage** — an XGBoost model grades severity P1–P4. Simple tabular problem, so no
   LLM needed here. Fast, cheap, testable.
2. **Investigate** — the agent pulls metrics, logs, traces, and deployment history,
   then searches the team's runbooks with RAG for matching cases.
3. **Diagnose** — Gemini writes up 2–3 competing hypotheses with confidence scores.
   If confidence is low, it goes back and digs for more evidence (up to 3 rounds).
4. **Plan** — it picks a fix from a strict allowlist (restart, scale, rollback…) and
   prices the risk. Anything destructive simply isn't on the list.
5. **Approve** — low-risk fixes run on their own. Anything else pauses and waits for
   a human to click approve in the dashboard. Approvals expire, are tied to the exact
   plan reviewed, and every decision lands in an audit trail.
6. **Execute & verify** — it applies the fix, re-reads the live error rate to prove
   recovery, and drafts a postmortem.

Every LLM call is metered (tokens, cost, latency) and traced, so there's a Grafana
dashboard and a Langfuse trace for everything it does.

A concrete example helps. Say `payment-api` starts timing out on connections. You (or
Alertmanager) post the alert. Triage sees error_rate 0.28 with a saturated connection
pool and grades it P1. The investigator finds `connection pool exhausted` in the logs,
RAG surfaces the database runbook, and RCA comes back with "database connection pool
exhaustion" at 0.9 confidence. The planner picks `rollback deployment` (the deploy
went out 7 minutes ago — suspicious timing), marks it medium risk, and pauses. You
click approve, it rolls back, the error rate drops from 0.28 to near zero, and you get
a postmortem describing the whole thing. That's the entire thesis in one incident.

## Results

Measured with the built-in eval harness running the live agent (Gemini
`gemini-3.5-flash-lite`, sequential mode):

| | Severity accuracy | RCA accuracy |
|---|---|---|
| 131 synthetic incidents (111 known / 20 novel faults) | 98.5% | 68.7% |
| Known faults | 98% | 67% |
| Novel faults (never in runbooks) | 100% | 80% |

Around those headline numbers, the harness also reports:

- **Runbook retrieval hit@3: 78%** — how often the right runbook was in the top 3.
  This is the RAG quality signal, and the most direct lever for lifting RCA.
- **Remediation safety: allowlist match 100%, risk grading 82%** — it never invents
  an action outside the allowlist, and usually prices the risk right.
- **Cost: ~2828 tokens / ~$0.0003 / ~24s per incident.** Cheap enough to run the full
  suite on the free tier if you shard it (more on that below).
- **Calibration: ECE 0.220.** High-confidence calls (≥0.8) land at 66%, so the
  re-investigation threshold wants tuning.

CI gates on 70% severity / 60% RCA, plus a cost gate that fails if the average cost
per incident jumps more than 25% over baseline.

## Try it

Python 3.11+ is required (3.13 works locally; Docker uses 3.11), plus a `GOOGLE_API_KEY`.
That's it for the local path — no Docker, no cluster.

```bash
py -m venv .venv && .venv\Scripts\activate   # Windows; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # Windows cmd: copy .env.example .env — then add your GOOGLE_API_KEY
py data/generate_incidents.py --n 160
py -m app.rag.ingest
py -m app.ml.train
py -m uvicorn app.api.server:app --port 4000
```

What each step does: `generate_incidents` writes 160 synthetic incidents (11 fault
families, seeded, reproducible) into `data/incidents/`. `ingest` chunks the runbooks,
embeds them, and writes the local vector store (plus Qdrant if it's up). `train`
fits the XGBoost severity model with a small grid search and saves artifacts plus an
MLflow run. The server warms the embedding model in the background, so the first
incident takes ~30–60 seconds and everything after is fast.

Then in another terminal:

```bash
curl -X POST localhost:4000/incidents -H "Content-Type: application/json" \
  -d @data/incidents/incident_003/incident.json | py -m json.tool
curl -X POST localhost:4000/incidents/incident_003/approve \
  -H "Content-Type: application/json" -d '{"approved_by":"sam"}'
```

Dashboard at `http://localhost:4000`, ML metrics at `/metrics`, health at `/health`.

No key? Triage and evidence collection still run (they don't need the LLM), but RCA
and remediation will fail by design — there's deliberately no rules-engine fallback
that pretends to reason. The API retries twice, then records the incident as failed
rather than guessing.

## Full stack with Docker Compose

Twelve services: Postgres, Qdrant, MLflow, Prometheus, Alertmanager, Loki, Promtail,
Jaeger, the OTel collector, Grafana, the API, and a demo checkout service you can
break on purpose.

```bash
docker compose up -d postgres qdrant mlflow prometheus alertmanager loki promtail jaeger grafana
docker exec -i $(docker compose ps -q postgres) psql -U opsmind -d opsmind < docker/init.sql
docker compose up --build api demo
```

First boot is slow — the image bakes the embedding model in so runtime loads from
cache instead of hitting HuggingFace. Watch `docker compose logs -f api` for the
Uvicorn line. One gotcha: compose doesn't forward your host `.env` key into the API
container automatically, so set `GOOGLE_API_KEY` in the `api` environment if you want
real reasoning in compose.

| Service | Port | What it's for |
|---|---|---|
| API / dashboard | 4000 | The agent itself |
| Demo checkout | 8002 | The service you break |
| Prometheus | 9090 | Scrapes the agent + demo, fires alert rules |
| Alertmanager | 9093 | Webhooks firing alerts back into the agent |
| Grafana | 3001 (admin/admin) | AI dashboard: tokens, cost, latency, success rate |
| Jaeger | 16686 | OTel traces, one per incident |
| Qdrant | 6333 | Runbook vectors |
| MLflow | 5000 | Training runs + model registry |
| Loki | 3100 | Log aggregation |

## Live end-to-end demo

The full loop takes about two minutes:

1. `POST demo:8002/chaos/errors`, then send some traffic to `/checkout`. The demo's
   error counter climbs.
2. Prometheus fires `DemoHighErrors` (error rate over 10% for 30s). Alertmanager
   webhooks the agent. An incident appears in the dashboard and the trace timeline
   starts filling in as it investigates.
3. It lands on a medium-risk fix like `rollback deployment` and pauses. The
   dashboard shows the competing hypotheses, confidences, and the exact proposed plan.
4. Click **Approve & execute**. It runs the fix (dry-run unless you set
   `OPSMIND_EXECUTE=true` with a real cluster), re-reads the error rate to prove
   recovery, and drafts the postmortem.
5. Flip to Grafana for the money slide: tokens, cost, latency, success rate — plus
   the Langfuse trace with a span per node.

## API reference

Base `http://localhost:4000`. The dashboard at `/` is a static page (no build step).
If `OPSMIND_API_KEY` is set, send it as `X-API-Key` on the incident routes;
`/health`, `/metrics`, and the dashboard stay open for probes and scrapes.

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Liveness (`{ok, pending}`) |
| `GET` | `/metrics` | Prometheus exposition: incidents, AI usage, eval scores |
| `GET` | `/incidents` | List investigations (in-memory; Postgres holds the audit trail) |
| `GET` | `/incidents/{id}` | Full live state, or the persisted snapshot after restart |
| `POST` | `/incidents` | Submit an alert, get back the full investigation |
| `POST` | `/incidents/{id}/approve` | Resume a paused fix with `{"approved_by":"sam"}` |
| `POST` | `/incidents/alertmanager` | Alertmanager webhook; `resolved` alerts are skipped |

Inputs are bounded everywhere: incident ids are alphanumeric plus dash/underscore,
descriptions cap at 2000 chars, logs at 20 entries of 500 chars, metrics at 32 keys.
Anything bigger gets trimmed before it can touch a prompt.

Approvals have teeth. The dashboard sends a hash of the exact plan it displayed; if
the plan changed since (mismatch), approval fails with 409 and the attempt is
audited. Approvals older than the TTL (default 60 min) fail with 410 and the
incident is marked expired. With `OPSMIND_REQUIRE_APPROVER=true`, the approver
identity header is mandatory (401 without it). Double-clicks are safe — an
idempotency key plus a per-incident lock means one approval runs the fix exactly
once.

## Configuration

Everything lives in `.env` (copy `.env.example`, never commit real keys). The only
one you truly need is `GOOGLE_API_KEY`; the rest have working defaults.

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_API_KEY` | — | **Required** for RCA, remediation, postmortem. No fallback, by design |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | The reasoning model; priced for cost math |
| `DATABASE_URL` | local Postgres | Checkpoints + audit tables; unset → in-memory (loses resume on restart) |
| `QDRANT_URL` | `localhost:6333` | Vector DB; unreachable → local cosine fallback, automatically |
| `MLFLOW_TRACKING_URI` | `localhost:5000` | Empty → train locally, artifacts still written |
| `PROMETHEUS_URL`, `LOKI_URL`, `JAEGER_URL` | localhost defaults | Real clients with short timeouts, synthetic/empty fallbacks |
| `OPSMIND_EXECUTE` | `false` | `true` plus a reachable cluster → real kubectl patches; otherwise dry-run |
| `OPSMIND_API_KEY` | — | Optional shared-secret auth on the incident routes |
| `OPSMIND_APPROVAL_TTL_MIN` | `60` | Approval lifetime (`0` disables); `OPSMIND_REQUIRE_APPROVER` enforces identity |
| `OPSMIND_RATE_LIMIT_PER_MIN` | `0` | Per-IP POST limit for public demos (`0` = off) |
| `SLACK_WEBHOOK_URL` | — | P1 / approval-needed / executed pings; console log otherwise |
| `LANGFUSE_*` | — | Tracing; unset → clean no-op, nothing breaks |

## Architecture

The system has four layers: intake (FastAPI), brain (LangGraph), evidence (tools +
vector DB), and proof (metrics, traces, eval). The key idea is that the graph can
*pause in the middle* — the approval gate is structural, not a polite suggestion.

```text
                          ┌─────────────┐
                          │ Prometheus  │── alert rules (DemoHighErrors, OpsMind*)
                          └──────┬──────┘
                                 │ Alertmanager webhook
                                 v
┌──────────┐  POST /incidents   ┌──────────────────────────────────────────┐
│ dashboard│───────────────────▶│ FastAPI: validate → run → persist        │
│ (static) │  ◀──────────────── │ threads map + snapshots + audit trail    │
└──────────┘  approve (hash)    └────────────────────┬─────────────────────┘
                                                     │ LangGraph (checkpoints in Postgres)
                                                     v
                      ┌────────────────────────────────────────────────┐
                      │ triage: XGBoost grades P1–P4 (no LLM)          │
                      │ observability: LLM tool-loop + deterministic   │
                      │   backfill (metrics, logs, deploys, traces)    │
                      │ rag: top-3 runbook chunks → evidence           │
                      │ rca: 2–3 hypotheses + confidence; loops back   │
                      │   for more evidence while confidence < 0.8     │
                      │ remediation: allowlisted fix + grounded params │
                      │ approval: low → auto, medium/high → PAUSE ─/─ │
                      │ execute → verify (error rate before vs after)  │
                      └─────────┬──────────────────────┬───────────────┘
                                │ LLM calls            │ evidence reads
                                v                      v
                   ┌─────────────────────┐  ┌──────────────────────────┐
                   │ Gemini (metered:    │  │ Prometheus, Loki, Jaeger │
                   │ tokens/cost/latency)│  │ Qdrant, k8s, Postgres    │
                   └──────────┬──────────┘  └──────────────────────────┘
                              │ traces + numbers
                              v
               ┌─────────────────────────────────────┐
               │ Langfuse │ Jaeger │ Prometheus/Grafana │
               └─────────────────────────────────────┘
```

**Three paths through the graph.** Low-risk incidents auto-execute: the graph still
pauses at the gate, but the wrapper sees `auto_approved` and resumes immediately, so
it looks like one smooth run. Medium/high-risk incidents stop cold — state is
checkpointed to Postgres, the dashboard shows the proposed fix with its evidence, and
nothing moves until `POST /incidents/{id}/approve` resumes that exact thread. One
resume equals one execution; if verification fails, it re-pauses and needs a fresh
approval to retry (max 2 executions). Alertmanager alerts take a third path in:
firing alerts are normalized (fingerprint → id, labels → service) and investigated
exactly like hand-submitted ones.

**State and memory.** Each node reads and writes a shared typed state: the raw
incident, severity, an append-only evidence list, a trace timeline (which powers the
dashboard), hypotheses with confidence, the remediation plan plus risk level, approval
status, and the verification result. Evidence and trace *append* rather than
overwrite, so parallel investigators and re-investigation loops merge cleanly instead
of clobbering each other. Thread id is `incident-id + short uuid`, carried on every
invoke — that's what lets a paused approval be resumed by a different process after
a restart, falling back to a deterministic re-run from the Postgres snapshot when the
in-memory thread map is gone.

**Tools are honest.** Every external integration tries the real client with a short
timeout, then falls back: synthetic metrics shaped by the incident, empty log/trace
lists, local cosine search over `store.json` when Qdrant is down. Fallbacks are
logged, never silent — the graph always completes with *something*, and the eval
harness scores what actually happened rather than what was hoped.

## Agent in detail

Node by node, since this is where most of the interesting decisions live:

- **Triage** builds a 9-feature row and calls the XGBoost model, falling back to
  plain threshold rules if the model file is missing. No LLM involved — severity is
  classification, not reasoning.
- **Observability** first lets the LLM drive: one round of tool calls (query metrics,
  search logs, deployment history, traces). Then a deterministic pass fills any gaps,
  so the evidence set is complete even if the model under-called tools or there's no
  key at all. Belt and suspenders.
- **RAG** queries with alert type + service + log lines, takes the top 3 chunks, and
  tags them `rag:<file>` so every grounded claim carries its provenance.
- **RCA** prompts for strict JSON only, then parses defensively (raw → fenced block →
  brace scan) because models love wrapping JSON in prose. Output is shape-checked and
  confidence-validated; failures raise instead of guessing.
- **Remediation** lets the LLM choose, but only from the allowlist — an unknown
  string raises. Parameters are grounded, not hallucinated: replica counts derive
  from the actual request rate, rollback targets from deploy evidence. Risk comes
  from a static table, not vibes.
- **Approval** is a pure router: forbidden → rejected, low → auto-approved, anything
  else → waiting on a human.
- **Execute** snapshots the pre-fix error rate, runs the action (or logs the dry-run
  command), and counts executions.
- **Verify** re-reads the same metric through the same tool path and calls it healthy
  only if the rate dropped below 5% *and* below its starting value. On real clusters
  it also gates on rollout status.
- **Postmortem** drafts the writeup. Best-effort by design — it can never block an
  approval.

The routers encode the loops: RCA goes back to observability while confidence is
under 0.8 (max 3 investigation rounds); verification routes back to remediation
while unhealthy (max 2 executions). The graph always terminates.

## RAG in detail

Embeddings load `all-MiniLM-L6-v2` locally (384-d,
baked into the Docker image), with a deterministic hash fallback if even that is
unavailable. Measured separation is healthy: paraphrases score ~0.74, unrelated text
~0.01. First model load costs ~30–40 seconds per process (weights + Hub check); the
API warms it in the background at startup and compose sets offline mode against the
baked cache.

Ingest chunks the runbooks at 500 chars with 50 overlap, drops scraps under 40
chars, embeds, and writes both `app/rag/store.json` and the Qdrant `runbooks`
collection (dimension inferred from the actual vectors, so backends can't mismatch).
Retrieval TCP-probes Qdrant first and permanently flags it down per process on first
failure — this matters because dead localhost ports on Docker Desktop hang instead
of refusing, which once cost 40 seconds per incident before the flag existed.

## ML in detail

Nine features: error rate, p95 latency, CPU, memory, request rate, deploy age, DB
connections, redis up/down, pods ready — with documented defaults so unknown fields
mean "assume healthy," not zero (that distinction once fabricated fake pods-down
evidence, which is how the defaults earned their comment).

The dataset generator writes 160 incidents across 11 fault families (56 P1 / 45 P2 /
32 P3 / 27 P4), seed 42, with the first five pinned as classics for fixtures and
rarer sampling for novel families. Training splits 70/15/15 stratified, grids three
(depth, learning-rate) configs on validation macro-F1, and reports once on the
held-out test set — val and test F1 both 1.0, which reflects a dataset separable
by construction, not a modeling breakthrough. Artifacts (model, labels, metrics with
confusion matrix) land in `app/ml/artifacts/`; MLflow logs params, metrics, and the
model, registering the champion as `incident-severity-model`. One real gotcha baked
in: XGBoost 3.x returns a probability matrix from `predict`, so inference
argmax-normalizes.

## Evaluation

Two tracks, both running the live agent (budget ~3 LLM calls per incident):

```bash
py -m app.evaluation.run                  # gated: 70% severity / 60% RCA to pass
py -m app.evaluation.run_real --per-fault 2   # report-only, real RCAEval telemetry
```

The gated harness scores severity against labels and RCA through a cascade —
substring match, then first-word match, then embedding cosine at 0.6 — sliced into
known vs novel families. It checkpoints every incident and skips done rows, so a
killed run resumes with zero waste; quota exhaustion stops the run with its own exit
code instead of recording fake misses. The report step needs no key and prints
slices, calibration, failure taxonomy, retrieval, safety, and cost lines.

On the free tier, don't run all 160 at once. Shard it:

```bash
py -m app.evaluation.run --shard 1 --num-shards 4 --out app/evaluation/results_s1.json
# ... repeat per shard, then:
py -m app.evaluation.run --aggregate app/evaluation/results_s*.json --out app/evaluation/results.json
py -m app.evaluation.report --results app/evaluation/results.json
```

The real-data track maps RCAEval chaos cases to incidents and scores fault-family
hits with published keyword sets — report-only on purpose, since real telemetry
doesn't respect synthetic thresholds and gating on it would be theater.

## Observability

`GET /metrics` exposes hand-rolled Prometheus exposition: incidents by severity and
status, remediations by risk, mean RCA confidence, tool call counts — plus the AI
layer: tokens by direction, call/error counts, total cost in USD, average latency,
agent success rate, and the latest eval scores (pushed by the harness after each
run). Token usage prefers real provider metadata and falls back to a length-based
estimate, so the cost graphs never go blank.

Grafana ships a provisioned AI dashboard (success rate, confidence gauge, cost,
tokens, eval trend), Prometheus ships rules that page on agent failures, low success
rate, eval regression, and LLM errors. Langfuse gets a trace per run with a span per
node — auto-approved runs show two segments (pre-pause + post-resume), which is
expected, not a bug. OpenTelemetry GenAI spans flow through the bundled collector
into Jaeger; raw prompt content stays off by default and only attaches when you
explicitly opt in, since incident text can carry secrets.

## Safety model

Three layers, each independent:

1. **Untrusted content is delimited.** Log lines, alert text, runbook chunks, and
   tool output get wrapped in `<untrusted>` tags with a standing prompt rule: tagged
   content is data, never instructions. A scanner flags classic injection phrasing,
   and any hit forces human approval regardless of risk.
2. **Approval is structural.** The graph literally cannot reach `execute` unapproved
   (`interrupt_before`). TTL expiry, plan-hash binding, approver identity, and
   idempotency are covered in the API section above; the audit table hash-chains
   every decision including rejections.
3. **Execution is allowlisted.** The remediation choice is validated against the
   risk table, parameters are schema-bounded, `delete database`-class actions map to
   `forbidden` and can never route to execute. Dry-run is the default; real kubectl
   patches need the flag *and* a reachable cluster.

Separately, the investigation tools are also exposed over MCP (`app/mcp_server.py`)
as five strictly read-only operations — metrics, logs, deploy history, traces,
runbook search. Execution is deliberately not on MCP. The agent itself calls the
Python functions directly; MCP exists so outside clients (Claude Desktop, other
agents) can borrow the read path.

## CI/CD and deploy

GitHub Actions (`ci-cd.yml`) runs lint → tests → small train → ingest → a gated
eval on main, then builds and pushes the image to GHCR, lints the Helm chart,
dry-runs it against kubectl, and validates Terraform. ArgoCD syncs `helm/opsmind`
automatically; Argo Rollouts promotes the canary in steps (25% → analysis → 50% →
100%) gated on the agent's own success-rate metric via Prometheus.

Three ways to deploy, same chart:

- **kind (free, ~15 min):** `bash scripts/kind-argo.sh`, port-forward, open the
  dashboard. Best for interviews and recording.
- **Public URL (~$0):** `fly.toml` and `render.yaml` are checked in with the demo
  shield on (6 req/min per IP, 30-min approvals, memory checkpointer, no real
  execution). Add Neon Postgres + Qdrant Cloud free tiers, set secrets, deploy.
- **AWS EKS (~$70–90/mo, destroy after):** Terraform up, push to ECR, Helm install
  with ingress, apply the ArgoCD app and canary. Teardown same day
  (`cd terraform/eks && terraform destroy`) — it bills while the cluster exists,
  not while you watch.

## Project layout

```text
app/
  agents/         graph, state, triage, observability, rag, rca, remediation,
                  approval, execute, verify, postmortem, llm + gemini provider
  tools/          prometheus, loki, traces, kubernetes, registry (LLM tool bindings)
  rag/            embeddings, ingest, retrieve (+ store.json, gitignored)
  ml/             features, train, classifier (+ artifacts/, gitignored models)
  api/            FastAPI server, postgres store, approval hardening, rate limiting
  demo/           toy checkout service with /chaos/{ok,errors,slow}
  observability/  prometheus metrics, langfuse, otel tracing, slack notifier
  evaluation/     gated harness, real-data track, report generator
  security/       untrusted-content wrapping + injection scanner
  mcp_server.py   read-only tools over MCP
data/             generator, synthetic incidents (gitignored), runbooks (the RAG corpus)
docker/           prometheus/alertmanager/loki/promtail/otel/grafana configs, init.sql
helm/opsmind/     chart: api, demo, ingress, HPA, serviceaccount, config
terraform/eks/    VPC + EKS + ECR
kind/  argocd/  rollouts/  public/  (static dashboard)  scripts/
```

Design calls are on record as ADRs in the repo history: why LangGraph over chains
(loops + branches + restart-proof pauses), why approval sits before execute, why
XGBoost instead of an LLM for severity, why Postgres backs the checkpointer, and why
the action list is closed.

## Tests

```bash
py -m ruff check app tests data
py -m pytest tests/ -q    # 70 passed, 1 skipped
```

No LLM key needed for any of it. Injection tests use a fake model that *obeys*
injections, which proves the gates hold rather than the model being polite. Approval
tests cover expiry, stale hashes, double-execution, and identity precedence. Team,
provider, tracing, MCP, and rate-limit suites pin the rest. The LLM itself is
measured by the eval harness, never by unit tests — that's a deliberate split.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `GOOGLE_API_KEY is not set` / incidents marked `failed` | Copy `.env.example` to `.env`, set the key, restart the API (the LLM client caches per process) |
| `429 RESOURCE_EXHAUSTED` / eval exits 2 | Free-tier quota, not a bug. Wait for reset and re-run — done rows are skipped. Shard next time |
| First incident takes ~40s | Normal: embedding weights + warmup load once, then cache |
| `qdrant query failed, using local store` | Normal offline behavior; check `QDRANT_URL` if you expected a server |
| `postgres checkpointer unavailable, using memory` | Check `DATABASE_URL`; memory mode loses pause/resume across restarts |
| Prometheus shows API down in compose | Check `docker compose logs api` — usually the model bake or a missing key |
| Helm `ServiceMonitor` error | Needs the prometheus-operator CRD; disable it or install the operator |
| Windows `curl -d @file` fails | Use Git Bash, or `curl.exe ... --data "@path"` in PowerShell |

And the standing rule: `.env` is gitignored. If a key ever leaks into a log,
screenshot, or commit, rotate it at the provider immediately.

## FAQ

**Why LangGraph instead of a plain chain?** Chains can't loop (re-investigate under
0.8), branch (risk routing), or pause mid-run and resume days later from another
process. A checkpointed graph expresses all three, and the dashboard timeline falls
out for free.

**What if the human never approves?** The thread sits paused indefinitely and
nothing executes. A background sweeper expires idle approvals past the TTL. No
timeout has ever auto-approved anything, and none ever will.

**What if the model fails or the key is missing?** The node raises, the API retries
twice, then records the incident as failed. There's no silent rules-engine fallback
— a guess dressed as reasoning is worse than an honest failure.

**Why not let the LLM grade severity too?** Classification over nine numeric
features is a gradient-boosting problem: faster, cheaper, deterministic, and unit
testable. Save the LLM for what it's good at — reading messy evidence and arguing
with itself about root causes.

**Biggest production gap, honestly?** Single-process API, per-process TTL and
idempotency stores (fine for one replica, needs Postgres backing to scale), asserted
rather than authenticated approver identity, and no approval-timeout sweeper paging
beyond Slack. Each has a known fix; none is architecturally load-bearing.

## What's next

Full 160-incident sweep refresh, permanent public demo URL, and the canary rollback
clip. The eval harness already supports all of it — mostly a matter of key budget
and recording time.
