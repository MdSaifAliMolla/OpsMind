# Bad Deployment Runbook

Covers: bad_deployment_crashloop, bad_deploy.

## Symptoms

- Error rate jumps within minutes of a deploy; pods in CrashLoopBackOff.
- Logs show panics, nil dereferences, or config errors naming the new version.

## Confirm

- Deployment age under ~15 minutes (`get_deployment_history` minutesAgo small).
- New ReplicaSet unhealthy while the previous revision was fine.
- Rollout status shows unavailable replicas or repeated container restarts.

## Fix

- Roll back the deployment to the previous ReplicaSet revision.
- Medium risk: brief second disruption during rollback, needs human approval.
- After rollback, verify error rate drops below 5% and stays there.
- Follow up: pin the bad image tag so it cannot be re-deployed.
