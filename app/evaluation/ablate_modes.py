import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.getcwd(), "data"))
from generate_incidents import NOVEL_TYPES  # noqa: E402

from app.agents.graph import run_incident  # noqa: E402
from app.evaluation.run import is_quota_error, rca_hit  # noqa: E402
from app.observability import metrics as _m  # noqa: E402

INCIDENTS = os.path.join(os.getcwd(), "data/incidents")
MODES = ("single", "multi", "debate")


def _snapshot_metrics():
    return {
        "calls": _m.llm_calls_total,
        "tokens": sum(_m.llm_tokens.values()),
        "cost": _m.llm_cost_usd_total,
        "lat": _m.llm_latency_sum,
        "lat_n": _m.llm_latency_count,
    }


def run_mode(mode: str, names: list) -> dict:
    os.environ["OPSMIND_MODE"] = mode
    rows, latencies = [], []
    quota_hit = False
    for name in names:
        with open(os.path.join(INCIDENTS, name, "incident.json")) as f:
            rec = json.load(f)
        gt = rec["ground_truth"]
        before = _snapshot_metrics()
        start = time.time()
        try:
            out, _ = run_incident(rec)
        except Exception as e:
            if is_quota_error(e):
                quota_hit = True
                break
            rows.append({"incident": name, "error": str(e)[:200],
                         "severity_correct": False, "rca_correct": False,
                         "calls": 0, "tokens": 0, "cost": 0.0})
            continue
        elapsed = time.time() - start
        after = _snapshot_metrics()
        rows.append({
            "incident": name,
            "novel": rec.get("alert_type") in NOVEL_TYPES,
            "severity_correct": out.get("severity") == gt["severity"],
            "rca_correct": rca_hit(out.get("root_cause"), gt["root_cause"]),
            "calls": after["calls"] - before["calls"],
            "tokens": after["tokens"] - before["tokens"],
            "cost": round(after["cost"] - before["cost"], 6),
        })
        latencies.append(elapsed)
    n = len(rows) or 1
    return {
        "mode": mode,
        "n": len(rows),
        "quota_hit": quota_hit,
        "severity_acc": sum(r["severity_correct"] for r in rows) / n,
        "rca_acc": sum(r["rca_correct"] for r in rows) / n,
        "avg_latency_s": sum(latencies) / len(latencies) if latencies else 0,
        "avg_tokens": sum(r.get("tokens", 0) for r in rows) / n,
        "avg_cost": sum(r.get("cost", 0.0) for r in rows) / n,
        "rows": rows,
    }


def main(n: int = 12, out: str = "docs/eval/ablation.json"):
    names = sorted(n for n in os.listdir(INCIDENTS) if n.startswith("incident_"))[:n]
    print(f"ablation on {len(names)} incidents: {names[0]}..{names[-1]}")
    report = {}
    for mode in MODES:
        print(f"\nmode={mode} ...")
        report[mode] = run_mode(mode, names)
        r = report[mode]
        print(f"  severity {r['severity_acc']:.0%}  rca {r['rca_acc']:.0%}  "
              f"lat {r['avg_latency_s']:.1f}s  tok {r['avg_tokens']:.0f}  ${r['avg_cost']:.4f}")
        if r["quota_hit"]:
            print("  QUOTA hit — stopping")
            break
    with open(os.path.join(os.getcwd(), out), "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {out}")
    print("\n| Mode | Severity acc | RCA acc | Avg latency | Avg tokens | Avg cost/incident | Notes |")
    for mode in MODES:
        if mode not in report:
            continue
        r = report[mode]
        print(f"| {mode} | {r['severity_acc']:.0%} | {r['rca_acc']:.0%} | "
              f"{r['avg_latency_s']:.1f}s | {r['avg_tokens']:.0f} | ${r['avg_cost']:.4f} | n={r['n']} |")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--out", type=str, default="docs/eval/ablation.json")
    args = p.parse_args()
    main(n=args.n, out=args.out)
