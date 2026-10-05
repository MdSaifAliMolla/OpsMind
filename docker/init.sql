CREATE TABLE IF NOT EXISTS incidents (
  id            TEXT PRIMARY KEY,
  service       TEXT NOT NULL,
  environment   TEXT NOT NULL,
  alert_type    TEXT NOT NULL,
  description   TEXT,
  severity      TEXT,
  status        TEXT DEFAULT 'open',
  created_at    TIMESTAMPTZ DEFAULT now(),
  resolved_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS evidence (
  id            SERIAL PRIMARY KEY,
  incident_id   TEXT REFERENCES incidents(id),
  source        TEXT NOT NULL,
  payload       JSONB NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id            SERIAL PRIMARY KEY,
  incident_id   TEXT REFERENCES incidents(id),
  root_cause    TEXT NOT NULL,
  confidence    FLOAT NOT NULL,
  evidence_ids  INT[],
  selected      BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS remediations (
  id            SERIAL PRIMARY KEY,
  incident_id   TEXT REFERENCES incidents(id),
  action        TEXT NOT NULL,
  risk_level    TEXT NOT NULL,
  status        TEXT DEFAULT 'proposed',
  approved_by   TEXT,
  executed_at   TIMESTAMPTZ,
  verified_at   TIMESTAMPTZ,
  result        JSONB
);

CREATE TABLE IF NOT EXISTS evaluations (
  id              SERIAL PRIMARY KEY,
  incident_id     TEXT REFERENCES incidents(id),
  predicted_severity TEXT,
  actual_severity     TEXT,
  predicted_root_cause TEXT,
  actual_root_cause    TEXT,
  rca_correct       BOOLEAN,
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS state_snapshots (
  incident_id   TEXT PRIMARY KEY REFERENCES incidents(id),
  thread_id     TEXT NOT NULL,
  state         JSONB NOT NULL,
  updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Phase 7: append-only approval audit (hash-chained per incident).
CREATE TABLE IF NOT EXISTS approvals (
  id              SERIAL PRIMARY KEY,
  incident_id     TEXT REFERENCES incidents(id),
  approver        TEXT NOT NULL,
  approver_source TEXT NOT NULL DEFAULT 'body',
  plan_hash       TEXT NOT NULL,
  idempotency_key TEXT NOT NULL DEFAULT '',
  decision        TEXT NOT NULL,
  prev_hash       TEXT NOT NULL DEFAULT '',
  row_hash        TEXT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS approvals_incident_idx ON approvals (incident_id);
