"""Offline bundle eval: RCA + remediation on recorded runs, no cluster.

Reads bundles (bundles.py schema), runs rca_node + remediation_node on each
{incident, evidence}, scores family-exact + action-vs-gold, prints Wilson
intervals. Needs GOOGLE_API_KEY (live LLM) except under test fakes.

Usage:
    py -m app.evaluation.run_offline --dir data/bundles
"""
import argparse
import os
import sys
import time

from app.evaluation.analysis import family_exact, wilson
from app.evaluation.bundles import list_bundles


def score_bundle(bundle: dict) -> dict:
    from app.agents.rca import rca_node
    from app.agents.remediation import remediation_node

    incident = bundle.get("incident") or {}
    label = bundle.get("label") or {}
    state = {"incident": incident, "evidence": list(bundle.get("evidence") or []),
             "investigation_loops": 0}
    start = time.time()
    try:
        rca_out = rca_node(state)
        rem_out = remediation_node({**state, **rca_out})
        action = (rem_out.get("remediation_plan") or {}).get("action")
        gold_fix = label.get("fix")
        if gold_fix is None:
            action_ok = action == "escalate"
        else:
            action_ok = action == gold_fix
        try:
            from app.evaluation.ragas import score_incident
            rag_scores = score_incident({**rca_out, **rem_out}, incident)
        except Exception:
            rag_scores = {"faithfulness": None, "answer_relevancy": None}
        return {
            "incident": incident.get("incident_id"),
            "family_correct": family_exact(rca_out.get("fault_family"),
                                           label.get("fault_family")),
            "predicted_family": rca_out.get("fault_family"),
            "action_correct": bool(action_ok),
            "predicted_action": action,
            "faithfulness": rag_scores.get("faithfulness"),
            "answer_relevancy": rag_scores.get("answer_relevancy"),
            "latency_s": round(time.time() - start, 2),
        }
    except Exception as e:
        return {"incident": incident.get("incident_id"),
                "family_correct": False, "action_correct": False,
                "predicted_family": f"ERROR: {e}",
                "predicted_action": f"ERROR: {e}",
                "latency_s": round(time.time() - start, 2)}


def main(directory: str = "data/bundles"):
    bundles = list_bundles(os.path.join(os.getcwd(), directory))
    if not bundles:
        print(f"no valid bundles in {directory}")
        sys.exit(2)
    rows = []
    for b in bundles:
        r = score_bundle(b)
        rows.append(r)
        print("." if r["family_correct"] and r["action_correct"]
              else "x" if r["family_correct"] else "E", end="", flush=True)
    print()
    fam = wilson(sum(1 for r in rows if r["family_correct"]), len(rows))
    act = wilson(sum(1 for r in rows if r["action_correct"]), len(rows))
    print(f"family top-1: {fam['accuracy']:.1%} "
          f"(95% CI {fam['lo']:.1%}–{fam['hi']:.1%}, n={fam['n']})")
    print(f"action correct: {act['accuracy']:.1%} "
          f"(95% CI {act['lo']:.1%}–{act['hi']:.1%}, n={act['n']})")
    for key in ("faithfulness", "answer_relevancy"):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if vals:
            print(f"{key}: avg {sum(vals) / len(vals):.2f} (n={len(vals)})")
        else:
            print(f"{key}: no scored rows")
    return fam, act


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=str, default="data/bundles")
    args = p.parse_args()
    main(directory=args.dir)
