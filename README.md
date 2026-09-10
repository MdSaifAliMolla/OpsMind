# OpsMind

Autonomous incident-response agent in Python. Feed it an infrastructure alert and it
classifies severity, investigates with observability tools, consults runbooks via RAG,
proposes evidence-backed root causes, plans a risk-graded fix, pauses for human approval
before anything risky, executes, verifies, and drafts a postmortem.

Stack: FastAPI + LangGraph + Gemini (with deterministic rules fallback) + XGBoost/MLflow +
Qdrant + Postgres + Prometheus/Grafana. Runs fully offline with no keys.

## How it works

```
alert (API / Alertmanager webhook)
  -> triage (XGBoost severity model)
  -> observability (metrics, logs, deploy history tools)
  -> RAG runbook lookup (Qdrant)
  -> RCA (competing hypotheses + confidence, re-investigates below 0.8)
  -> remediation (action + parameters + risk level)
  -> approval: low risk executes, medium/high pauses for a human (interrupt/resume)
  -> execute -> verify (before/after metric comparison) -> postmortem
```

Checkpoints persist in Postgres (in-memory fallback), so approval survives restarts.
Every run is traced with Langfuse and counted in Prometheus metrics.

## Evaluation

40 synthetic incidents plus a report-only track on the RCAEval benchmark (real
chaos-injection telemetry, scored against its own fault labels):

```
severity accuracy: 100%
rca accuracy: 93% overall (100% on known failure modes)
```

```bash
python -m app.evaluation.run      # gated harness (CI needs 70% / 60%)
python -m app.evaluation.ablate   # rules-vs-LLM ablation (LLM arm needs GOOGLE_API_KEY)
python -m app.evaluation.run_real # real-data track, report-only
```

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   

python data/generate_incidents.py --n 40
python -m app.rag.ingest
python -m app.ml.train

ruff check app tests scripts data
pytest
uvicorn app.api.server:app --port 4000   # API + dashboard at /
```

Full stack (Postgres, Qdrant, MLflow, Prometheus, Alertmanager, Grafana, API, demo service):

```bash
docker compose up -d postgres qdrant mlflow prometheus alertmanager grafana
docker exec -i $(docker compose ps -q postgres) psql -U opsmind -d opsmind < docker/init.sql
docker compose up --build api demo
```

Live demo: `POST demo:8002/chaos/errors` makes the demo service fail, Prometheus fires,
Alertmanager webhooks the agent, and the incident lands on the dashboard awaiting approval.

## API

```bash
curl -X POST localhost:4000/incidents -H "Content-Type: application/json" \
  -d @data/incidents/incident_003/incident.json

curl -X POST localhost:4000/incidents/incident_003/approve \
  -H "Content-Type: application/json" -d '{"approved_by":"sam"}'
```

## Layout

- `app/agents/` — LangGraph nodes, graph wiring, checkpointing, postmortem writer
- `app/tools/` — Prometheus / Loki / Kubernetes clients with offline fallbacks
- `app/rag/` — embeddings, Qdrant ingest + retrieval
- `app/ml/` — features, training, registry, in-process classifier
- `app/api/` — FastAPI server, approval flow, Postgres persistence
- `app/demo/` — toy service with chaos modes for live demos
- `app/observability/` — Langfuse tracing, Prometheus counters, webhook notifier
- `app/evaluation/` — gated harness, ablation, real-data track
- `data/` — incident generator, synthetic incidents, runbooks
- `docker/`, `k8s/` — compose configs, alert rules, provisioned dashboards, manifests

## Configuration

All settings live in `.env` (see `.env.example`) and are optional: `GOOGLE_API_KEY` enables
the Gemini reasoning arm (free tier: https://aistudio.google.com/apikey), `DATABASE_URL`
and `QDRANT_URL` connect infra, `OPSMIND_EXECUTE=true` with a kubeconfig runs real kubectl
operations, `SLACK_WEBHOOK_URL` enables notifications. Without any of them the system runs
on its rules engine, local vector store, and dry-run logging.
