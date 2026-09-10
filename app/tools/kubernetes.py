import logging
import os

log = logging.getLogger(__name__)

# dry run by default so demos never touch a real cluster.
DRY = os.getenv("OPSMIND_EXECUTE", "true").lower() != "true"

_connected = "unset"


def connected() -> bool:
    """True when a kubeconfig/cluster is reachable. Cheap cached probe."""
    global _connected
    if _connected != "unset":
        return _connected
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        client.VersionApi().get_code()
        _connected = True
    except Exception as e:
        log.debug(f"no kubernetes cluster, dry-run mode: {e}")
        _connected = False
    return _connected


def _sh(cmd: str):
    print(f"[kubectl] {cmd}{' (dry-run)' if DRY or not connected() else ''}")


def get_deployment_history(service: str, incident=None):
    if connected():
        try:
            from kubernetes import client

            apps = client.AppsV1Api()
            deps = apps.list_deployment_for_all_namespaces(
                label_selector=f"app={service}").items
            if deps:
                d = deps[0]
                ts = d.metadata.creation_timestamp
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
                containers = d.spec.template.spec.containers
                return {"minutesAgo": round(age, 1),
                        "version": containers[0].image if containers else "unknown"}
        except Exception as e:
            log.debug(f"k8s deploy history failed: {e}")
    if incident and incident.get("deployment_minutes_ago") is not None:
        return {"minutesAgo": float(incident["deployment_minutes_ago"]), "version": "v-synthetic"}
    return {"minutesAgo": 9999, "version": "unknown"}


def list_pods(service: str):
    if not connected():
        return []
    try:
        from kubernetes import client

        core = client.CoreV1Api()
        pods = core.list_pod_for_all_namespaces(label_selector=f"app={service}").items
        return [{"name": p.metadata.name, "phase": p.status.phase,
                 "restarts": sum(c.restart_count for c in (p.status.container_statuses or []))}
                for p in pods]
    except Exception as e:
        log.debug(f"k8s pod list failed: {e}")
        return []


def rollout_status(service: str):
    """True when the deployment looks fully rolled out, None when unknown."""
    if not connected():
        return None
    try:
        from kubernetes import client

        apps = client.AppsV1Api()
        deps = apps.list_deployment_for_all_namespaces(
            label_selector=f"app={service}").items
        if not deps:
            return None
        d = deps[0].status
        return (d.updated_replicas or 0) == (d.replicas or 0) and \
               (d.unavailable_replicas or 0) == 0
    except Exception as e:
        log.debug(f"k8s rollout status failed: {e}")
        return None


def restart_pods(service: str):
    if connected() and not DRY:
        from kubernetes import client

        apps = client.AppsV1Api()
        deps = apps.list_deployment_for_all_namespaces(
            label_selector=f"app={service}").items
        for d in deps:
            apps.patch_namespaced_deployment(
                d.metadata.name, d.metadata.namespace,
                {"spec": {"template": {"metadata": {"annotations": {"opsmind/restarted": "true"}}}}})
    else:
        _sh(f"rollout restart deployment/{service}")
    return {"ok": True, "action": "restart pods"}


def rollback_deployment(service: str):
    if connected() and not DRY:
        from kubernetes import client

        apps = client.AppsV1Api()
        deps = apps.list_deployment_for_all_namespaces(
            label_selector=f"app={service}").items
        for d in deps:
            hist = apps.list_namespaced_replicaset(
                d.metadata.namespace,
                label_selector=",".join(f"{k}={v}" for k, v in
                                        (d.spec.selector.match_labels or {}).items()))
            prev = sorted([r for r in hist.items
                           if r.metadata.annotations.get("deployment.kubernetes.io/revision")],
                          key=lambda r: r.metadata.annotations["deployment.kubernetes.io/revision"])
            if len(prev) >= 2:
                body = {"spec": {"template": {"spec": {"containers": [
                    {"name": c.name, "image": c.image} for c in prev[-2].spec.template.spec.containers]}}}}
                apps.patch_namespaced_deployment(d.metadata.name, d.metadata.namespace, body)
    else:
        _sh(f"rollout undo deployment/{service}")
    return {"ok": True, "action": "rollback deployment"}


def scale_replicas(service: str, replicas=5):
    if connected() and not DRY:
        from kubernetes import client

        apps = client.AppsV1Api()
        deps = apps.list_deployment_for_all_namespaces(
            label_selector=f"app={service}").items
        for d in deps:
            apps.patch_namespaced_deployment_scale(
                d.metadata.name, d.metadata.namespace, {"spec": {"replicas": replicas}})
    else:
        _sh(f"scale deployment/{service} --replicas={replicas}")
    return {"ok": True, "action": "scale replicas", "replicas": replicas}


def restart_redis():
    _sh("rollout restart statefulset/redis")
    return {"ok": True, "action": "restart redis"}
