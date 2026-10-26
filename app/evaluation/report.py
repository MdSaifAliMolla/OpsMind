import argparse
import json
import os

from app.evaluation.analysis import (
    CONFIDENCE_THRESHOLD,
    calibration_summary,
    calibration_table,
    cost_stats,
    failure_taxonomy,
    retrieval_metrics,
    safety_metrics,
)


def _bar(frac, width=20):
    if frac is None:
        return "(no data)"
    filled = int(round(max(0.0, min(1.0, frac)) * width))
    return "#" * filled + "-" * (width - filled)


def render(results_path: str) -> str:
    with open(results_path) as f:
        data = json.load(f)
    rows = data.get("results", [])
    n = len(rows)
    sev = sum(r.get("severity_correct", False) for r in rows) / n if n else 0
    rca = sum(r.get("rca_correct", False) for r in rows) / n if n else 0
    known = [r for r in rows if not r.get("novel")]
    novel = [r for r in rows if r.get("novel")]
    cal = calibration_summary(rows)
    table = calibration_table(rows)
    tax = failure_taxonomy(rows)
    ret = retrieval_metrics(rows)
    saf = safety_metrics(rows)
    costs = cost_stats(rows)

    lines = [
        "# Eval Report",
        "",
        f"Source: `{results_path}` — n={n}, "
        f"severity {sev:.1%}, RCA {rca:.1%} (gates: 70% / 60%).",
        "",
        "## Slices",
        "",
    ]
    for label, subset in (("known", known), ("novel", novel)):
        if not subset:
            continue
        s = sum(r.get("severity_correct", False) for r in subset) / len(subset)
        c = sum(r.get("rca_correct", False) for r in subset) / len(subset)
        lines.append(f"- {label} (n={len(subset)}): severity {s:.0%}, RCA {c:.0%}")
    lines += ["", "## Calibration (RCA confidence)", ""]
    if cal["n_scored"]:
        lines.append(f"ECE: **{cal['ece']:.3f}** (n={cal['n_scored']}). "
                     f"P(correct | conf >= {cal['threshold']}) = "
                     f"**{cal['high_conf_accuracy']:.0%}** (n={cal['high_conf_n']})"
                     if cal["high_conf_accuracy"] is not None else
                     f"ECE: **{cal['ece']:.3f}** (n={cal['n_scored']}). "
                     f"No conf >= {cal['threshold']} cases — threshold unjustified.")
        lines += ["", "| Bin | n | avg conf | accuracy | |", "|---|---|---|---|---|"]
        for b in table:
            acc = f"{b['accuracy']:.0%}" if b["accuracy"] is not None else "—"
            lines.append(f"| {b['bin']} | {b['n']} | {b['avg_conf'] or '—'} | {acc} | {_bar(b['accuracy'])} |")
        lines.append("")
        if cal["high_conf_accuracy"] is not None and cal["high_conf_accuracy"] >= 0.8:
            lines.append(f"Threshold {CONFIDENCE_THRESHOLD} justified: high-confidence cases are right "
                         f"{cal['high_conf_accuracy']:.0%} of the time.")
        else:
            lines.append(f"Threshold {CONFIDENCE_THRESHOLD} NOT justified by this run — "
                         "re-tune or report as miscalibrated.")
    else:
        lines.append("No confidence data in rows (old harness version) — re-run to calibrate.")
    lines += ["", "## Failure taxonomy (RCA misses only)", ""]
    if sum(tax.values()):
        for k, v in tax.items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("No misses (or no rows).")
    lines += ["", "## Retrieval (runbook hit@3)", ""]
    lines.append(f"hit@3: **{ret['hit_at_3']:.0%}** (n={ret['n_scored']})" if ret["hit_at_3"] is not None
                 else "No gold-runbook data — re-run with current harness.")
    lines += ["", "## Remediation safety", ""]
    if saf["n_scored"]:
        lines.append(f"allowlist match: **{saf['allowlist_match']:.0%}** (n={saf['n_scored']})")
        if saf["risk_correct"] is not None:
            lines.append(f"risk correctness: **{saf['risk_correct']:.0%}** (n={saf['n_risk_scored']})")
    else:
        lines.append("No action data — re-run with current harness.")
    lines += ["", "## Cost / latency per incident", ""]
    if costs["avg_cost"] is not None:
        lines.append(f"avg **{costs['avg_tokens']:.0f}** tokens / **${costs['avg_cost']:.4f}** / "
                     f"**{costs['avg_latency_s']:.1f}s** per incident (n={costs['n_cost_scored']}). "
                     "CI fails on +25% vs `docs/eval/cost_baseline.json`.")
    else:
        lines.append("No cost data (old harness) — re-run to populate; cost gate skips without it.")
    return "\n".join(lines)


def main(results="app/evaluation/results.json", out="docs/eval/REPORT.md"):
    md = render(results)
    out_path = os.path.join(os.getcwd(), out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"wrote {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=str, default="app/evaluation/results.json")
    p.add_argument("--out", type=str, default="docs/eval/REPORT.md")
    args = p.parse_args()
    main(results=args.results, out=args.out)
