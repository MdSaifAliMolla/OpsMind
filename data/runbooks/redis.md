# Redis runbook

## Symptoms
- Sharp error spike on anything session- or cache-dependent.
- Logs full of `ECONNREFUSED redis:6379`, `READONLY`, or `connection timed out`.
- `redis_up` metric drops to 0 while app CPU stays low. The app is fine, it just can't reach its store.

## Likely causes
1. Redis pod or node restarted and didn't come back (persistence or scheduling issue).
2. A config or network policy change cut the app off from redis.
3. Failover stuck halfway in sentinel/cluster mode.

## How to confirm
- `redis-cli -h redis ping` from inside the cluster. No `PONG` means redis itself is down, not the app.
- Check recent deploys to both the app and redis. A 2-minute-old change plus `ECONNREFUSED` is usually the change.
- Look at redis memory and eviction stats. OOM with `noeviction` policy looks like refused writes rather than refused connections, so read the error closely.

## Standard fix
Restart redis if the process is down, otherwise roll back the app deploy that broke connectivity.

```
kubectl rollout restart statefulset/redis
# or, if an app deploy caused it:
kubectl rollout undo deployment/<service>
```

Verify with a ping and a quick session write/read before closing out. Watch error rate for 5 minutes, redis blips tend to leave a tail of retries.

## Notes
- Don't flush the cache (`FLUSHALL`) to fix connectivity. You will turn a short outage into a cold-cache thundering herd.
- If this recurs, check redis resource limits. Under-provisioned redis fails exactly this way under load.
