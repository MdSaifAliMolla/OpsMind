# Kubernetes runbook

## Symptoms
- Pods stuck in `CrashLoopBackOff` or `OOMKilled` right after a rollout.
- `pods_ready` drops to 0, error rate spikes because there is nothing serving traffic.
- Logs show panics (`nil pointer dereference`) for bad deploys, or `heap allocation failure` / `OOM killer invoked` for memory leaks.

## Telling the two apart
- Crashloop from a bad deploy: starts within minutes of a rollout, every new pod crashes the same way, old ReplicaSet was healthy.
- Memory leak: slow burn over hours. `memory_pct` climbs steadily toward 90%+, restarts buy you a few hours then it comes back.

## Bad deploy fix
Rollback. Don't try to patch forward during an outage.

```
kubectl rollout undo deployment/<service>
kubectl rollout status deployment/<service>
```

Check `kubectl get pods` until ready count recovers, then verify error rate drops.

## Memory leak fix
Restart is the safe immediate move. It buys time, it is low risk, and it works even before you find the leak.

```
kubectl rollout restart deployment/<service>
```

Afterwards pull a heap profile and look at what grew between restarts. Common culprits are unbounded in-memory caches and goroutines or promises that never resolve.

## Notes
- Never delete the deployment itself to "fix" a crashloop, you just lose the rollout history you need for the rollback.
- If restarts stop helping (crash within seconds, not hours), treat it as a bad deploy and roll back.
