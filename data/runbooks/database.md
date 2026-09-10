# Database runbook

## Symptoms
- Error rate jumps right after a deploy, p95 latency climbs into seconds.
- Logs show `connection pool exhausted`, `timeout acquiring connection`, or `remaining connection slots are reserved`.
- `db_connections` metric sits near the pool max (90+), CPU on the app itself looks normal.

## Likely causes
1. New code path opens connections without closing them, or raises per-request connection count.
2. Pool size set too low for the traffic the deploy enabled.
3. Slow queries introduced by a migration hold connections longer than before.

## How to confirm
- Check `db_connections` over the last 30m. Flat line at max = pool exhaustion, not a traffic spike.
- Look for a deploy in the last 15 minutes. Pool exhaustion that lines up with a deploy is almost always the deploy.
- Scan logs for the first `timeout acquiring connection` timestamp and diff the deploy that landed just before it.

## Standard fix
Rollback the deployment first. That restores the old connection behavior in under a minute and is safe to do even if you are not 100% sure yet.

```
kubectl rollout undo deployment/<service>
```

Then investigate the slow query or leak offline. Only bump the pool size as a follow-up once you know the new steady state, otherwise you just move the failure to the database itself.

## When not to use this
If `db_connections` is low and errors are high, this is not the pool. Check redis or upstream dependencies instead.
