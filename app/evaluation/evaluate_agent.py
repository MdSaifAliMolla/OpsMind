import json
import os
import sys

import requests

API = os.getenv("OPSMIND_API", "http://localhost:4000")


def rca_hit(predicted, actual):
    p = (predicted or "").lower()
    a = (actual or "").lower()
    if a in p:
        return True
    first = a.split(" ")[0]
    return len(first) > 3 and first in p


def run_eval(incidents_dir=None, api=API):
    if incidents_dir is None:
        incidents_dir = os.path.join(os.getcwd(), "data/incidents")
    names = sorted(n for n in os.listdir(incidents_dir) if n.startswith("incident_"))
    results = []

    for name in names:
        with open(os.path.join(incidents_dir, name, "incident.json")) as f:
            record = json.load(f)
        resp = requests.post(f"{api}/incidents", json=record, timeout=120).json()
        gt = record["ground_truth"]
        results.append({
            "incident": name,
            "severity_correct": resp.get("severity") == gt["severity"],
            "rca_correct": rca_hit(resp.get("root_cause"), gt["root_cause"]),
            "predicted_severity": resp.get("severity"),
            "predicted_root_cause": resp.get("root_cause"),
        })
        print(".", end="", flush=True)
    print()

    sev = sum(r["severity_correct"] for r in results) / len(results)
    rca = sum(r["rca_correct"] for r in results) / len(results)
    print(f"Severity accuracy: {sev:.2%}")
    print(f"RCA accuracy: {rca:.2%}")

    with open(os.path.join(os.getcwd(), "app/evaluation/results.json"), "w") as f:
        json.dump({"severity_accuracy": sev, "rca_accuracy": rca, "results": results}, f, indent=2)

    return sev, rca


if __name__ == "__main__":
    sev, rca = run_eval()
    if sev < 0.7 or rca < 0.6:
        print("below threshold (need 70% severity, 60% rca)")
        sys.exit(1)
