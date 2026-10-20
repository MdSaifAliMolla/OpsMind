# Eval Report

Source: `app/evaluation/results.json` — n=131, severity 98.5%, RCA 68.7% (gates: 70% / 60%).

## Slices

- known (n=111): severity 98%, RCA 67%
- novel (n=20): severity 100%, RCA 80%

## Calibration (RCA confidence)

ECE: **0.220** (n=129). P(correct | conf >= 0.8) = **66%** (n=61)

| Bin | n | avg conf | accuracy | |
|---|---|---|---|---|
| 0.0-0.1 | 0 | — | — | (no data) |
| 0.1-0.2 | 0 | — | — | (no data) |
| 0.2-0.3 | 0 | — | — | (no data) |
| 0.3-0.4 | 0 | — | — | (no data) |
| 0.4-0.5 | 0 | — | — | (no data) |
| 0.5-0.6 | 16 | 0.594 | 88% | ##################-- |
| 0.6-0.7 | 41 | 0.654 | 80% | ################---- |
| 0.7-0.8 | 15 | 0.763 | 47% | #########----------- |
| 0.8-0.9 | 49 | 0.85 | 74% | ###############----- |
| 0.9-1.0 | 8 | 0.95 | 0% | -------------------- |

Threshold 0.8 NOT justified by this run — re-tune or report as miscalibrated.

## Failure taxonomy (RCA misses only)

- agent_error: 2
- missing_evidence: 0
- retrieval_miss: 3
- wrong_family: 36

## Retrieval (runbook hit@3)

hit@3: **78%** (n=131)

## Remediation safety

allowlist match: **100%** (n=129)
risk correctness: **82%** (n=129)

## Cost / latency per incident

avg **2828** tokens / **$0.0003** / **23.5s** per incident (n=129). CI fails on +25% vs `docs/eval/cost_baseline.json`.

## Ablation / providers / real data

- Real telemetry: `py -m app.evaluation.run_real` — report-only, family-keyword scoring; publish numbers with windowing limits attached.
