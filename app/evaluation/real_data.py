import logging
import os

log = logging.getLogger(__name__)

REPO = "phamquiluan/RCAEval"
CACHE = os.path.join(os.getcwd(), "data/real/rcaeval")

FAMILY_KEYWORDS = {
    "cpu": {"cpu", "throttle", "saturation", "overload", "spike", "traffic", "scale"},
    "mem": {"memory", "leak", "oom", "heap"},
    "disk": {"disk", "pressure", "evict", "space", "storage", "volume"},
    "delay": {"latency", "delay", "slow", "timeout", "traffic", "spike"},
    "loss": {"loss", "packet", "error", "fail", "timeout", "network"},
    "socket": {"socket", "connection", "refused", "exhaust", "pool", "timeout", "reset"},
}

ERROR_HINTS = ("error", "fail", "exception", "timeout", "refused", "evict", "oom",
               "panic", "reset", "unavailable", "denied", "exhaust")


def family_hit(predicted: str, fault: str) -> bool:
    words = set((predicted or "").lower().replace("/", " ").split())
    return bool(words & FAMILY_KEYWORDS[fault])


def fetch_case(case: str):
    from huggingface_hub import hf_hub_download

    token = os.getenv("HF_TOKEN") or None
    out = {}
    for fname in ("metrics.parquet", "logs.parquet", "inject_time.txt"):
        out[fname] = hf_hub_download(REPO, f"{case}/{fname}", repo_type="dataset",
                                     local_dir=CACHE, token=token)
    return out


def list_cases(system="re2ob", faults=None, per_fault=2):
    from huggingface_hub import HfApi

    faults = faults or list(FAMILY_KEYWORDS)
    files = HfApi().list_repo_files(REPO, repo_type="dataset")
    cases = sorted({f.split("/")[0] for f in files if f.startswith(system)})
    picked = []
    for fault in faults:
        matches = [c for c in cases if f"_{fault}_" in c][:per_fault]
        picked.extend(matches)
    return picked


def _series(df, service: str, suffix: str):
    col = f"{service}_{suffix}"
    return col if col in df.columns else None


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def build_incident(case: str):
    import pandas as pd

    paths = fetch_case(case)
    _, service, fault, _ = case.split("_", 3)

    with open(paths["inject_time.txt"]) as f:
        inject_ts = int(f.read().strip())

    metrics_df = pd.read_parquet(paths["metrics.parquet"])
    baseline = metrics_df.head(360)
    abnormal = metrics_df.tail(360)

    def abn(suffix):
        s = _series(metrics_df, service, suffix)
        return float(abnormal[s].mean()) if s is not None else 0.0

    def base(suffix):
        s = _series(metrics_df, service, suffix)
        return float(baseline[s].mean()) if s is not None else 0.0

    mem_base = base("mem") or 1.0
    memory_pct = _clip(50 + 50 * (abn("mem") - mem_base) / mem_base, 0, 99)
    cpu_base = base("cpu") or 1.0

    logs_df = pd.read_parquet(paths["logs.parquet"])
    svc_logs = logs_df[logs_df["container_name"].str.contains(service, na=False)]
    after = svc_logs[svc_logs["timestamp"] >= inject_ts]
    errs = after[after["message"].str.lower().str.contains("|".join(ERROR_HINTS), na=False)]
    lines = errs["message"].head(8).tolist() or after["message"].head(8).tolist()
    error_rate = round(min(0.9, len(errs) / max(1, len(after))), 3) if len(after) else 0.2

    incident = {
        "incident_id": f"real_{case}",
        "service": service,
        "environment": "production",
        "alert_type": "rcaeval_anomaly",
        "description": f"anomaly detected on {service}, cause under investigation",
        "metrics": {
            "error_rate": error_rate,
            "p95_latency_ms": round(abn("latency-90") * 1000, 1),
            "cpu_pct": round(_clip(abn("cpu")), 1),
            "memory_pct": round(memory_pct, 1),
            "open_sockets": round(abn("socket"), 1),
            "cpu_baseline": round(cpu_base, 1),
            "memory_baseline_mb": round(mem_base / 1e6, 1),
        },
        "logs": [str(m)[:300] for m in lines],
        "deployment_minutes_ago": 9999,
        "ground_truth": {"fault": fault, "service": service, "case": case},
    }
    from app.ml.features import DEFAULTS, FEATURE_COLUMNS

    for col in FEATURE_COLUMNS:
        incident["metrics"].setdefault(col, DEFAULTS[col])
    return incident
