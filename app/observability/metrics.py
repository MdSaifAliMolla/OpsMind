"""Dependency-free Prometheus exposition for the agent itself."""
from collections import Counter

incidents_by_severity = Counter()
incidents_by_status = Counter()
remediation_by_risk = Counter()
confidence_sum = 0.0
confidence_count = 0
failed_total = 0


def record_result(result: dict):
    global confidence_sum, confidence_count
    incidents_by_severity[result.get("severity", "unknown")] += 1
    incidents_by_status[result.get("approval_status", "unknown")] += 1
    if (result.get("remediation_plan") or {}).get("action"):
        remediation_by_risk[result.get("risk_level", "unknown")] += 1
    if result.get("confidence") is not None:
        confidence_sum += result["confidence"]
        confidence_count += 1


def record_failure():
    global failed_total
    failed_total += 1


def render() -> str:
    lines = [
        "# HELP opsmind_incidents_total Incidents investigated by the agent",
        "# TYPE opsmind_incidents_total counter",
    ]
    for sev, n in sorted(incidents_by_severity.items()):
        lines.append(f'opsmind_incidents_total{{severity="{sev}"}} {n}')
    lines += [
        "# HELP opsmind_incidents_by_status Incidents by approval status",
        "# TYPE opsmind_incidents_by_status gauge",
    ]
    for st, n in sorted(incidents_by_status.items()):
        lines.append(f'opsmind_incidents_by_status{{status="{st}"}} {n}')
    lines += [
        "# HELP opsmind_remediation_by_risk Executed/proposed remediations by risk",
        "# TYPE opsmind_remediation_by_risk counter",
    ]
    for risk, n in sorted(remediation_by_risk.items()):
        lines.append(f'opsmind_remediation_by_risk{{level="{risk}"}} {n}')
    avg = confidence_sum / confidence_count if confidence_count else 0
    lines += [
        "# HELP opsmind_rca_confidence_avg Mean RCA confidence",
        "# TYPE opsmind_rca_confidence_avg gauge",
        f"opsmind_rca_confidence_avg {avg:.4f}",
        "# HELP opsmind_incidents_failed_total Incidents that errored out",
        "# TYPE opsmind_incidents_failed_total counter",
        f"opsmind_incidents_failed_total {failed_total}",
    ]
    return "\n".join(lines) + "\n"
