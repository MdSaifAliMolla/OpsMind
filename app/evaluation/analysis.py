import json
import os

CALIBRATION_BINS = 10
CONFIDENCE_THRESHOLD = 0.8
COST_UPLIFT_LIMIT = 0.25


def ece(conf, correct, bins=10):
    try:
        import numpy as np
    except ImportError:
        conf = [float(c) for c in conf]
        correct = [float(c) for c in correct]
        edges = [i / bins for i in range(bins + 1)]
        total = 0.0
        for lo, hi in zip(edges[:-1], edges[1:]):
            idx = [i for i, c in enumerate(conf) if (c > lo and c <= hi) or (lo == 0 and c == 0)]
            if idx:
                total += len(idx) / len(conf) * abs(
                    sum(conf[i] for i in idx) / len(idx) - sum(correct[i] for i in idx) / len(idx))
        return total
    conf = np.asarray(conf, dtype=float)
    correct = np.asarray(correct, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(total)


def _conf(row):
    try:
        c = float(row.get("confidence"))
        return max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        return None


def calibration_table(rows, bins=10):
    scored = [(c, 1.0 if r.get("rca_correct") else 0.0)
              for r in rows for c in [_conf(r)] if c is not None]
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        members = [(c, y) for c, y in scored
                   if (c > lo and c <= hi) or (b == 0 and c == 0.0)]
        n = len(members)
        table.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "n": n,
            "avg_conf": round(sum(c for c, _ in members) / n, 3) if n else None,
            "accuracy": round(sum(y for _, y in members) / n, 3) if n else None,
        })
    return table


def calibration_summary(rows, threshold=CONFIDENCE_THRESHOLD):
    conf_rows = [r for r in rows if _conf(r) is not None]
    if not conf_rows:
        return {"n_scored": 0, "ece": None, "high_conf_accuracy": None,
                "high_conf_n": 0, "threshold": threshold}
    conf = [_conf(r) for r in conf_rows]
    correct = [1.0 if r.get("rca_correct") else 0.0 for r in conf_rows]
    high = [(c, y) for c, y in zip(conf, correct) if c >= threshold]
    return {
        "n_scored": len(conf_rows),
        "ece": round(ece(conf, correct), 4),
        "high_conf_accuracy": round(sum(y for _, y in high) / len(high), 3) if high else None,
        "high_conf_n": len(high),
        "threshold": threshold,
    }


def _runbook_hit(gold: str, retrieved) -> bool:
    gold = str(gold or "").split("/")[-1]
    for r in retrieved or []:
        cand = str(r or "").split("/")[-1]
        if cand in (gold, f"rag:{gold}") or cand.replace("rag:", "") == gold:
            return True
    return False


def failure_taxonomy(rows):
    counts = {"agent_error": 0, "missing_evidence": 0, "retrieval_miss": 0, "wrong_family": 0}
    for r in rows:
        if r.get("rca_correct"):
            continue
        if str(r.get("predicted_severity", "")).startswith("ERROR") or \
                str(r.get("predicted_root_cause", "")).startswith("ERROR"):
            counts["agent_error"] += 1
        elif (r.get("evidence_count") or 99) <= 3:
            counts["missing_evidence"] += 1
        elif r.get("gold_runbook") and r.get("retrieved_runbooks") is not None and \
                not _runbook_hit(r["gold_runbook"], r["retrieved_runbooks"]):
            counts["retrieval_miss"] += 1
        else:
            counts["wrong_family"] += 1
    return counts


def retrieval_metrics(rows):
    scored = [r for r in rows if r.get("gold_runbook")]
    if not scored:
        return {"n_scored": 0, "hit_at_3": None}
    hits = sum(1 for r in scored if _runbook_hit(r["gold_runbook"], r.get("retrieved_runbooks")))
    return {"n_scored": len(scored), "hit_at_3": round(hits / len(scored), 3)}


def safety_metrics(rows, allowlist=None):
    if allowlist is None:
        try:
            from app.agents.remediation import RISK_TABLE
            allowlist = set(RISK_TABLE)
        except Exception:
            allowlist = set()
    with_action = [r for r in rows if r.get("predicted_action")]
    on_list = sum(1 for r in with_action if r["predicted_action"] in allowlist)
    with_risk = [r for r in rows if r.get("predicted_risk") and r.get("expected_risk")]
    risk_ok = sum(1 for r in with_risk if r["predicted_risk"] == r["expected_risk"])
    return {
        "n_scored": len(with_action),
        "allowlist_match": round(on_list / len(with_action), 3) if with_action else None,
        "n_risk_scored": len(with_risk),
        "risk_correct": round(risk_ok / len(with_risk), 3) if with_risk else None,
    }


def cost_stats(rows):
    tok = [r["tokens"] for r in rows if isinstance(r.get("tokens"), (int, float))]
    cost = [r["cost"] for r in rows if isinstance(r.get("cost"), (int, float))]
    lat = [r["latency_s"] for r in rows if isinstance(r.get("latency_s"), (int, float))]
    return {
        "n_scored": len(rows),
        "n_cost_scored": len(cost),
        "avg_tokens": round(sum(tok) / len(tok), 1) if tok else None,
        "avg_cost": round(sum(cost) / len(cost), 6) if cost else None,
        "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
    }


def cost_gate(avg_cost, baseline_path="docs/eval/cost_baseline.json",
              uplift_limit=COST_UPLIFT_LIMIT):
    if avg_cost is None:
        return True, "cost gate skipped: no cost data in rows"
    path = os.path.join(os.getcwd(), baseline_path)
    if not os.path.exists(path):
        return True, f"cost gate skipped: no baseline at {baseline_path}"
    try:
        with open(path) as f:
            baseline = float(json.load(f)["avg_cost_per_incident"])
    except Exception as e:
        return True, f"cost gate skipped: unreadable baseline ({e})"
    if baseline <= 0:
        return True, "cost gate skipped: baseline is 0 (free-tier run)"
    uplift = (avg_cost - baseline) / baseline
    if uplift > uplift_limit:
        return False, (f"cost gate FAILED: avg ${avg_cost:.4f} vs baseline ${baseline:.4f} "
                       f"(+{uplift:.0%} > +{uplift_limit:.0%} allowed)")
    return True, (f"cost gate passed: avg ${avg_cost:.4f} vs baseline ${baseline:.4f} "
                  f"({uplift:+.0%})")
