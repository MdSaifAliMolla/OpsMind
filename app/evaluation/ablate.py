"""Rules vs LLM ablation: quantifies what the LLM actually adds.

Rules arm always runs. The LLM arm needs GOOGLE_API_KEY; without it we say so
instead of pretending.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "data"))
from generate_incidents import NOVEL_TYPES

from app.agents.graph import run_incident
from app.agents.llm import llm_enabled, reset_llm_cache
from app.evaluation.run import rca_hit

INCIDENTS = os.path.join(os.getcwd(), "data/incidents")


def run_slice(names, label):
    rows = []
    for name in names:
        with open(os.path.join(INCIDENTS, name, "incident.json")) as f:
            rec = json.load(f)
        out, _ = run_incident(rec)
        gt = rec["ground_truth"]
        rows.append({
            "severity_ok": out.get("severity") == gt["severity"],
            "rca_ok": rca_hit(out.get("root_cause"), gt["root_cause"]),
        })
    sev = sum(r["severity_ok"] for r in rows) / len(rows)
    rca = sum(r["rca_ok"] for r in rows) / len(rows)
    print(f"  {label}: severity {sev:.0%}, rca {rca:.0%} (n={len(rows)})")
    return sev, rca


def main(arm="both", sample=None):
    import random

    names = sorted(n for n in os.listdir(INCIDENTS) if n.startswith("incident_"))
    novel = [n for n in names
             if json.load(open(os.path.join(INCIDENTS, n, "incident.json")))["alert_type"] in NOVEL_TYPES]
    if sample:
        # free-tier quotas are tiny (20 req/day on gemini-3.6-flash): sample the
        # novel slice so the LLM arm fits in one day's budget (~3 calls/incident)
        novel = sorted(random.Random(7).sample(novel, min(sample, len(novel))))
        print(f"sampled {len(novel)} novel incidents: {novel}")

    if arm in ("both", "rules"):
        os.environ["OPSMIND_DISABLE_LLM"] = "1"
        reset_llm_cache()
        print("rules-only arm:")
        run_slice(names, "overall")
        run_slice(novel, "novel slice")
        del os.environ["OPSMIND_DISABLE_LLM"]
        reset_llm_cache()

    if arm in ("both", "llm"):
        if not llm_enabled():
            print("\nGOOGLE_API_KEY not set: LLM arm skipped. "
                  "Set it to measure the delta on the novel slice.")
            return
        print("llm arm (novel slice only: this is where reasoning matters, "
              "and it keeps free-tier usage small):")
        run_slice(novel, "novel slice")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=["rules", "llm", "both"], default="both")
    p.add_argument("--sample", type=int, default=None,
                   help="limit the novel slice to N incidents (for LLM quota)")
    args = p.parse_args()
    main(arm=args.arm, sample=args.sample)
