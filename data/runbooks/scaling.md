# Scaling Runbook

Covers: cpu_starvation, pod_kill_storm, traffic_spike, retry_storm_cascade.

## Symptoms

- CPU saturation or throttling with climbing latency; or ready-replica count
  collapsed after pod kills while traffic is steady.
- Retry storms: duplicate request ids, circuit breakers opening, queue depth
  growing faster than workers drain it.

## Confirm

- Request rate per replica far above headroom (rule of thumb: scale so each
  replica handles ~2000 rps).
- Pod events show OOMKills, evictions, or rapid restarts rather than app errors.
- No recent deploy implicates a code change (otherwise see the deploy runbook).

## Fix

- Scale replicas: replicas = ceil(request_rate / 2000), clamped 2–10.
- Low risk: additive capacity, safe to auto-approve.
- After scaling, verify error rate and p95 latency recover; if retries caused
  the spike, also confirm retry budgets stop tripping.
