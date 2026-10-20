import logging
import os
import re
import threading

log = logging.getLogger(__name__)

_configure_lock = threading.Lock()
_local = threading.local()

_SERVICE_RE = re.compile(r"^[a-z0-9]([a-z0-9\-.]*[a-z0-9])?$")


def _scope_ok(service: str) -> bool:
    """Service names must be DNS-safe: no traversal, no selectors, no blanks."""
    return bool(_SERVICE_RE.match(str(service or "")))


def _namespace() -> str:
    ns = os.getenv("OPSMIND_NAMESPACE", "").strip()
    if not ns:
        raise RuntimeError("OPSMIND_NAMESPACE is required")
    return ns


def _require_execute():
    if os.getenv("OPSMIND_EXECUTE", "").lower() != "true":
        raise RuntimeError("OPSMIND_EXECUTE must be 'true' (dry-run disabled)")


def _ensure_cluster():
    """Load kube config once per thread (the kubernetes client keeps its
    default Configuration in thread-local storage; langgraph nodes run in
    worker threads). Raises when the cluster is unreachable."""
    if getattr(_local, "ready", False):
        return
    with _configure_lock:
        if getattr(_local, "ready", False):
            return
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        client.VersionApi().get_code()
        _local.ready = True


def connected() -> bool:
    _ensure_cluster()
    return True


def _sh(cmd: str):
    ns = _namespace()
    log.info(f"[kubectl] {cmd} -n {ns}")


def get_deployment_history(service: str, incident=None):
    _ensure_cluster()
    from kubernetes import client

    apps = client.AppsV1Api()
    deps = apps.list_deployment_for_all_namespaces(
        label_selector=f"app={service}").items
    if not deps:
        raise RuntimeError(f"k8s: no deployment for service={service}")
    d = deps[0]
    ts = d.metadata.creation_timestamp
    from datetime import datetime, timezone
    age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    containers = d.spec.template.spec.containers
    return {"minutesAgo": round(age, 1),
            "version": containers[0].image if containers else "unknown"}


def list_pods(service: str):
    _ensure_cluster()
    from kubernetes import client

    core = client.CoreV1Api()
    pods = core.list_pod_for_all_namespaces(label_selector=f"app={service}").items
    if not pods:
        raise RuntimeError(f"k8s: no pods for service={service}")
    return [{"name": p.metadata.name, "phase": p.status.phase,
             "restarts": sum(c.restart_count for c in (p.status.container_statuses or []))}
            for p in pods]


def rollout_status(service: str):
    _ensure_cluster()
    from kubernetes import client

    apps = client.AppsV1Api()
    deps = apps.list_deployment_for_all_namespaces(
        label_selector=f"app={service}").items
    if not deps:
        raise RuntimeError(f"k8s: no deployment for service={service}")
    d = deps[0].status
    return (d.updated_replicas or 0) == (d.replicas or 0) and \
           (d.unavailable_replicas or 0) == 0


def get_events(service: str, limit: int = 20):
    """Recent namespaced events touching the service. Read-only, raises when empty."""
    if not _scope_ok(service):
        raise ValueError(f"refusing unscoped service name: {service!r}")
    _ensure_cluster()
    from kubernetes import client

    core = client.CoreV1Api()
    evts = core.list_namespaced_event(_namespace()).items
    out = []
    for e in evts:
        name = ((e.involved_object or {}).name if hasattr(e.involved_object, "name")
                else getattr(e.involved_object, "name", ""))
        if service.lower() not in str(name or "").lower():
            continue
        out.append({"name": str(name),
                    "reason": str(getattr(e, "reason", "") or "")[:128],
                    "message": str(getattr(e, "message", "") or "")[:300],
                    "count": int(getattr(e, "count", 0) or 0)})
        if len(out) >= max(1, min(50, limit)):
            break
    if not out:
        raise RuntimeError(f"k8s: no events for service={service}")
    return out


def restart_pods(service: str):
    if not _scope_ok(service):
        return {"ok": False, "action": "restart pods",
                "error": f"refusing unscoped service name: {service!r}"}
    _require_execute()
    ns = _namespace()
    _ensure_cluster()
    from kubernetes import client

    apps = client.AppsV1Api()
    deps = apps.list_namespaced_deployment(
        ns, label_selector=f"app={service}").items
    if not deps:
        raise RuntimeError(f"k8s: no deployment for service={service}")
    for d in deps:
        apps.patch_namespaced_deployment(
            d.metadata.name, ns,
            {"spec": {"template": {"metadata": {"annotations": {"opsmind/restarted": "true"}}}}})
    return {"ok": True, "action": "restart pods", "dry_run": False}


def rollback_deployment(service: str):
    if not _scope_ok(service):
        return {"ok": False, "action": "rollback deployment",
                "error": f"refusing unscoped service name: {service!r}"}
    _require_execute()
    ns = _namespace()
    _ensure_cluster()
    from kubernetes import client

    apps = client.AppsV1Api()
    deps = apps.list_namespaced_deployment(
        ns, label_selector=f"app={service}").items
    if not deps:
        raise RuntimeError(f"k8s: no deployment for service={service}")
    for d in deps:
        hist = apps.list_namespaced_replicaset(
            ns,
            label_selector=",".join(f"{k}={v}" for k, v in
                                    (d.spec.selector.match_labels or {}).items()))
        prev = sorted([r for r in hist.items
                       if r.metadata.annotations.get("deployment.kubernetes.io/revision")],
                      key=lambda r: r.metadata.annotations["deployment.kubernetes.io/revision"])
        if len(prev) >= 2:
            body = {"spec": {"template": {"spec": {"containers": [
                {"name": c.name, "image": c.image} for c in prev[-2].spec.template.spec.containers]}}}}
            apps.patch_namespaced_deployment(d.metadata.name, d.metadata.namespace, body)
    return {"ok": True, "action": "rollback deployment", "dry_run": False}


def scale_replicas(service: str, replicas=5):
    if not _scope_ok(service):
        return {"ok": False, "action": "scale replicas",
                "error": f"refusing unscoped service name: {service!r}"}
    _require_execute()
    ns = _namespace()
    _ensure_cluster()
    from kubernetes import client

    apps = client.AppsV1Api()
    deps = apps.list_namespaced_deployment(
        ns, label_selector=f"app={service}").items
    if not deps:
        raise RuntimeError(f"k8s: no deployment for service={service}")
    for d in deps:
        apps.patch_namespaced_deployment_scale(
            d.metadata.name, ns, {"spec": {"replicas": replicas}})
    return {"ok": True, "action": "scale replicas", "replicas": replicas, "dry_run": False}


def restart_redis():
    _require_execute()
    ns = _namespace()
    _ensure_cluster()
    from kubernetes import client

    core = client.CoreV1Api()
    pods = core.list_namespaced_pod(ns, label_selector="app=redis").items
    if not pods:
        raise RuntimeError("k8s: no redis pods")
    for p in pods:
        core.delete_namespaced_pod(p.metadata.name, ns)
    return {"ok": True, "action": "restart redis", "dry_run": False}
