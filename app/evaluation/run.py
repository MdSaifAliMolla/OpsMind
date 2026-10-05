import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "data"))
from generate_incidents import NOVEL_TYPES

from app.agents.graph import run_incident
from app.rag.embeddings import cosine, embed_text

INCIDENTS = os.path.join(os.getcwd(), "data/incidents")
RCA_THRESHOLD = 0.6


def rca_hit(predicted: str, actual: str) -> bool:
    p = (predicted or "").lower()
    a = (actual or "").lower()
    if a in p:
        return True
    first = a.split(" ")[0]
    if len(first) > 3 and first in p:
        return True
    return cosine(embed_text(p), embed_text(a)) >= RCA_THRESHOLD


def is_quota_error(e: Exception) -> bool:
    msg = str(e)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()


def run_names(names, out=None):
    import time

    from app.observability import metrics as _m

    def _snap():
        return {"calls": _m.llm_calls_total, "tokens": sum(_m.llm_tokens.values()),
                "cost": _m.llm_cost_usd_total, "lat": _m.llm_latency_sum}

    rows = []
    done = set()
    if out and os.path.exists(out):
        try:
            with open(out) as f:
                for r in json.load(f)["results"]:
                    rows.append(r)
                    done.add(r["incident"])
        except Exception:
            rows, done = [], set()
    if done:
        print(f"resuming: {len(done)} already done, "
              f"{len(names) - len(done)} to go")

    def checkpoint():
        if out:
            sev = sum(r["severity_correct"] for r in rows) / len(rows)
            rca = sum(r["rca_correct"] for r in rows) / len(rows)
            with open(os.path.join(os.getcwd(), out), "w") as f:
                json.dump({"severity_accuracy": sev, "rca_accuracy": rca,
                           "results": rows}, f, indent=2)

    quota_hit = False
    for name in names:
        if name in done:
            continue
        with open(os.path.join(INCIDENTS, name, "incident.json")) as f:
            rec = json.load(f)
        gt = rec["ground_truth"]
        before = _snap()
        start = time.time()
        try:
            out_v, _ = run_incident(rec)
            after = _snap()
            rag_sources = [str(e.get("source", "")) for e in (out_v.get("evidence") or [])
                           if str(e.get("source", "")).startswith("rag:")]
            rows.append({
                "incident": name,
                "novel": rec.get("alert_type") in NOVEL_TYPES,
                "severity_correct": out_v.get("severity") == gt["severity"],
                "rca_correct": rca_hit(out_v.get("root_cause"), gt["root_cause"]),
                "predicted_severity": out_v.get("severity"),
                "actual_severity": gt["severity"],
                "predicted_root_cause": out_v.get("root_cause"),
                "actual_root_cause": gt["root_cause"],
                "confidence": out_v.get("confidence"),
                "predicted_action": (out_v.get("remediation_plan") or {}).get("action"),
                "predicted_risk": out_v.get("risk_level"),
                "expected_remediation": gt.get("expected_remediation"),
                "expected_risk": gt.get("expected_risk"),
                "gold_runbook": gt.get("runbook"),
                "retrieved_runbooks": rag_sources,
                "evidence_count": len(out_v.get("evidence") or []),
                "calls": after["calls"] - before["calls"],
                "tokens": after["tokens"] - before["tokens"],
                "cost": round(after["cost"] - before["cost"], 6),
                "latency_s": round(time.time() - start, 2),
            })
        except Exception as e:
            if is_quota_error(e):
                print(f"\nQUOTA_EXHAUSTED at {name}: {e}")
                quota_hit = True
                break
            rows.append({
                "incident": name,
                "novel": rec.get("alert_type") in NOVEL_TYPES,
                "severity_correct": False,
                "rca_correct": False,
                "predicted_severity": f"ERROR: {e}",
                "actual_severity": gt["severity"],
                "predicted_root_cause": f"ERROR: {e}",
                "actual_root_cause": gt["root_cause"],
                "confidence": None,
                "gold_runbook": gt.get("runbook"),
                "retrieved_runbooks": [],
                "evidence_count": 0,
            })
        mark = "." if rows[-1]["severity_correct"] and rows[-1]["rca_correct"] \
            else "x" if rows[-1]["severity_correct"] else "E"
        print(mark, end="", flush=True)
        checkpoint()
    print()
    return rows, quota_hit


def report(rows):
    from app.evaluation.analysis import (
        calibration_summary,
        cost_stats,
        failure_taxonomy,
        retrieval_metrics,
        safety_metrics,
    )

    sev = sum(r["severity_correct"] for r in rows) / len(rows)
    rca = sum(r["rca_correct"] for r in rows) / len(rows)
    print(f"severity accuracy: {sev:.1%}")
    print(f"rca accuracy: {rca:.1%}")
    try:
        from app.observability.metrics import record_eval
        record_eval(sev, rca)
    except Exception:
        pass

    for label, subset in [("known", [r for r in rows if not r.get("novel")]),
                          ("novel", [r for r in rows if r.get("novel")])]:
        if not subset:
            continue
        s = sum(r["severity_correct"] for r in subset) / len(subset)
        c = sum(r["rca_correct"] for r in subset) / len(subset)
        print(f"  {label} ({len(subset)}): severity {s:.0%}, rca {c:.0%}")
    failed = sum(1 for r in rows if str(r["predicted_severity"]).startswith("ERROR"))
    if failed:
        print(f"failed investigations (counted as misses): {failed}")

    cal = calibration_summary(rows)
    if cal["n_scored"]:
        print(f"calibration: ECE {cal['ece']:.3f} (n={cal['n_scored']}); "
              f"P(correct|conf>={cal['threshold']}) = "
              f"{cal['high_conf_accuracy']:.0%} (n={cal['high_conf_n']})" if cal["high_conf_accuracy"] is not None
              else f"calibration: ECE {cal['ece']:.3f} (n={cal['n_scored']}); no conf>={cal['threshold']} cases")
    tax = failure_taxonomy(rows)
    if sum(tax.values()):
        print("failure taxonomy: " + ", ".join(f"{k}={v}" for k, v in tax.items()))
    ret = retrieval_metrics(rows)
    if ret["n_scored"]:
        print(f"retrieval hit@3: {ret['hit_at_3']:.0%} (n={ret['n_scored']})")
    saf = safety_metrics(rows)
    if saf["n_scored"]:
        print(f"safety: allowlist {saf['allowlist_match']:.0%} (n={saf['n_scored']})"
              + (f", risk {saf['risk_correct']:.0%} (n={saf['n_risk_scored']})"
                 if saf["risk_correct"] is not None else ""))
    costs = cost_stats(rows)
    if costs["avg_cost"] is not None:
        print(f"cost: avg {costs['avg_tokens']:.0f} tok / ${costs['avg_cost']:.4f} / "
              f"{costs['avg_latency_s']:.1f}s per incident (n={costs['n_cost_scored']})")
    return sev, rca


def main(shard=None, num_shards=1, out="app/evaluation/results.json",
         aggregate=None, cost_baseline="docs/eval/cost_baseline.json"):
    from app.evaluation.analysis import cost_gate, cost_stats

    def _gate(rows):
        ok, msg = cost_gate(cost_stats(rows)["avg_cost"], baseline_path=cost_baseline)
        print(msg)
        return ok

    if aggregate:
        rows = []
        for path in aggregate:
            with open(path) as f:
                rows.extend(json.load(f)["results"])
        rows.sort(key=lambda r: r["incident"])
        sev, rca = report(rows)
        with open(os.path.join(os.getcwd(), out), "w") as f:
            json.dump({"severity_accuracy": sev, "rca_accuracy": rca,
                       "results": rows}, f, indent=2)
        if sev < 0.7 or rca < 0.6:
            print("below threshold (need 70% severity, 60% rca)")
            sys.exit(1)
        if not _gate(rows):
            sys.exit(1)
        return

    names = sorted(n for n in os.listdir(INCIDENTS) if n.startswith("incident_"))
    if num_shards > 1:
        chunk = (len(names) + num_shards - 1) // num_shards
        names = names[(shard - 1) * chunk:shard * chunk]
        print(f"shard {shard}/{num_shards}: {len(names)} incidents "
              f"({names[0]}..{names[-1]})")
    rows, quota_hit = run_names(names, out=out)
    sev, rca = report(rows)
    with open(os.path.join(os.getcwd(), out), "w") as f:
        json.dump({"severity_accuracy": sev, "rca_accuracy": rca,
                   "results": rows}, f, indent=2)
    if quota_hit:
        sys.exit(2)
    if num_shards == 1 and (sev < 0.7 or rca < 0.6):
        print("below threshold (need 70% severity, 60% rca)")
        sys.exit(1)
    if num_shards == 1 and not _gate(rows):
        sys.exit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--shard", type=int, default=None)
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--out", type=str, default="app/evaluation/results.json")
    p.add_argument("--aggregate", nargs="*", default=None,
                   help="shard result files to merge into a final gated report")
    p.add_argument("--cost-baseline", type=str, default="docs/eval/cost_baseline.json",
                   help="baseline for the +25%% cost gate (missing file = skip)")
    args = p.parse_args()
    main(shard=args.shard, num_shards=args.num_shards, out=args.out,
         aggregate=args.aggregate, cost_baseline=args.cost_baseline)
