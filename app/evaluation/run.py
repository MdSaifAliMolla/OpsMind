import json
import os
import sys

# The gate pins deterministic behavior; the LLM is measured by ablate.py.
os.environ["OPSMIND_DISABLE_LLM"] = "1"

sys.path.insert(0, os.path.join(os.getcwd(), "data"))
from generate_incidents import NOVEL_TYPES

from app.agents.graph import run_incident
from app.rag.embeddings import cosine, local_embed

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
    return cosine(local_embed(p), local_embed(a)) >= RCA_THRESHOLD


def main():
    names = sorted(n for n in os.listdir(INCIDENTS) if n.startswith("incident_"))
    rows = []
    for name in names:
        with open(os.path.join(INCIDENTS, name, "incident.json")) as f:
            rec = json.load(f)
        out, _ = run_incident(rec)
        gt = rec["ground_truth"]
        rows.append({
            "incident": name,
            "novel": rec.get("alert_type") in NOVEL_TYPES,
            "severity_correct": out.get("severity") == gt["severity"],
            "rca_correct": rca_hit(out.get("root_cause"), gt["root_cause"]),
            "predicted_severity": out.get("severity"),
            "actual_severity": gt["severity"],
            "predicted_root_cause": out.get("root_cause"),
            "actual_root_cause": gt["root_cause"],
        })
        print("." if rows[-1]["severity_correct"] else "x", end="", flush=True)
    print()

    sev = sum(r["severity_correct"] for r in rows) / len(rows)
    rca = sum(r["rca_correct"] for r in rows) / len(rows)
    print(f"severity accuracy: {sev:.1%}")
    print(f"rca accuracy: {rca:.1%}")

    for label, subset in [("known", [r for r in rows if not r.get("novel")]),
                          ("novel", [r for r in rows if r.get("novel")])]:
        if not subset:
            continue
        s = sum(r["severity_correct"] for r in subset) / len(subset)
        c = sum(r["rca_correct"] for r in subset) / len(subset)
        print(f"  {label} ({len(subset)}): severity {s:.0%}, rca {c:.0%}")

    with open(os.path.join(os.getcwd(), "app/evaluation/results.json"), "w") as f:
        json.dump({"severity_accuracy": sev, "rca_accuracy": rca, "results": rows}, f, indent=2)

    if sev < 0.7 or rca < 0.6:
        print("below threshold (need 70% severity, 60% rca)")
        sys.exit(1)


if __name__ == "__main__":
    main()
