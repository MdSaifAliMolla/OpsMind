# Networking / traffic spike runbook

## Symptoms
- CPU pinned high (80%+), p95 latency degrades gradually, moderate error rate from timeouts rather than crashes.
- Logs show `queue depth increasing`, `worker saturation`, upstream timeouts.
- No recent deploy. `request_rate` is well above baseline. This is load, not a bad release.

## Likely causes
1. Genuine traffic surge (launch, retry storm from a client, cron overlap).
2. One slow dependency making every request hold a worker longer.
3. Autoscaler min replicas set too low or scaling capped by quota.

## How to confirm
- Compare `request_rate` now vs same hour last week. 3-5x with no deploy = spike.
- Check CPU vs error shape. Load issues ramp; bad deploys cliff.
- Look at queue depth. Growing queue + high CPU means you are behind, not broken.

## Standard fix
Scale out. It is low risk and reversible.

```
kubectl scale deployment/<service> --replicas=5
```

Then check the autoscaler settings so it holds. If a single upstream is the bottleneck, scaling helps less, throttle or shed load on the expensive endpoint instead.

## Notes
- Don't rollback a deploy that didn't happen. Rolling back during a spike just adds churn.
- After recovery, set a higher min replica count or fix the HPA thresholds. The same spike will come back otherwise.
