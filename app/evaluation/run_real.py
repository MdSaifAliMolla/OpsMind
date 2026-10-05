import argparse

from app.agents.graph import run_incident
from app.evaluation.real_data import (
    FAMILY_KEYWORDS,
    build_incident,
    family_hit,
    list_cases,
)


def main(per_fault=2):
    cases = list_cases(per_fault=per_fault)
    print(f"scoring {len(cases)} RCAEval cases "
          f"(keywords per family: { {k: sorted(v) for k, v in FAMILY_KEYWORDS.items()} })")
    rows = []
    for case in cases:
        incident = build_incident(case)
        fault = incident["ground_truth"]["fault"]
        try:
            out, _ = run_incident(incident)
            hit = family_hit(out.get("root_cause"), fault)
            rows.append({"case": case, "fault": fault, "predicted": out.get("root_cause"),
                         "hit": hit})
            print(f"[{'HIT' if hit else 'miss'}] {case}: {out.get('root_cause')}")
        except Exception as e:
            rows.append({"case": case, "fault": fault, "predicted": f"ERROR: {e}",
                         "hit": False})
            print(f"[ERROR] {case}: {e}")
    acc = sum(r["hit"] for r in rows) / len(rows)
    print(f"\nreal-track family accuracy: {acc:.0%} (n={len(rows)}, report-only, no gate)")
    return acc


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--per-fault", type=int, default=2)
    args = p.parse_args()
    main(per_fault=args.per_fault)
