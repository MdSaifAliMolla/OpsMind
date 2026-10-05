"""Dependency-free Prometheus exposition for the agent itself."""
import threading
import time
from collections import Counter

_lock = threading.Lock()
incidents_by_severity = Counter()
incidents_by_status = Counter()
remediation_by_risk = Counter()
tool_calls = Counter()
confidence_sum = 0.0
confidence_count = 0
failed_total = 0
latency_sum = 0.0
latency_count = 0
rag_queries = 0

# LLM metrics
llm_tokens = Counter()
llm_calls_total = 0
llm_errors_total = 0
llm_cost_usd_total = 0.0
llm_latency_sum = 0.0
llm_latency_count = 0
eval_severity_accuracy = 0.0
eval_rca_accuracy = 0.0
eval_last_unix = 0.0

# per-1M pricing (USD)
MODEL_PRICING = {
    "gemini-3.5-flash-lite": (0.07, 0.28),
    "gemini-2.0-flash": (0.10, 0.40),
    "llama3.1": (0.0, 0.0),
    "llama3": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "default": (0.10, 0.40),
}


def _price(model: str):
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    low = (model or "").lower()
    if low.startswith(("llama", "qwen", "mistral", "phi", "gemma", "ollama/", "vllm/")):
        return (0.0, 0.0)
    return MODEL_PRICING["default"]


def record_result(result: dict):
    global confidence_sum, confidence_count, rag_queries
    with _lock:
        incidents_by_severity[result.get("severity", "unknown")] += 1
        incidents_by_status[result.get("approval_status", "unknown")] += 1
        if (result.get("remediation_plan") or {}).get("action"):
            remediation_by_risk[result.get("risk_level", "unknown")] += 1
        if result.get("confidence") is not None:
            try:
                confidence_sum += float(result["confidence"])
                confidence_count += 1
            except (TypeError, ValueError):
                pass
        for e in result.get("evidence", []) or []:
            tool_calls[e.get("source", "unknown")] += 1
            if str(e.get("source", "")).startswith("rag"):
                rag_queries += 1


def record_failure():
    global failed_total
    with _lock:
        failed_total += 1


def observe_latency(seconds: float):
    global latency_sum, latency_count
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return
    with _lock:
        latency_sum += seconds
        latency_count += 1


def record_llm_call(model: str, input_tokens: int, output_tokens: int, latency_s: float):
    global llm_calls_total, llm_cost_usd_total, llm_latency_sum, llm_latency_count
    try:
        in_t, out_t = int(input_tokens or 0), int(output_tokens or 0)
        lat = float(latency_s or 0)
    except (TypeError, ValueError):
        return
    in_price, out_price = _price(model or "default")
    cost = in_t / 1_000_000 * in_price + out_t / 1_000_000 * out_price
    with _lock:
        llm_tokens[(model, "input")] += in_t
        llm_tokens[(model, "output")] += out_t
        llm_calls_total += 1
        llm_cost_usd_total += cost
        llm_latency_sum += lat
        llm_latency_count += 1


def record_llm_error():
    global llm_errors_total
    with _lock:
        llm_errors_total += 1


def record_eval(severity_accuracy: float, rca_accuracy: float):
    global eval_severity_accuracy, eval_rca_accuracy, eval_last_unix
    with _lock:
        eval_severity_accuracy = float(severity_accuracy)
        eval_rca_accuracy = float(rca_accuracy)
        eval_last_unix = time.time()


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
    avg_lat = latency_sum / latency_count if latency_count else 0
    lines += [
        "# HELP opsmind_rca_confidence_avg Mean RCA confidence",
        "# TYPE opsmind_rca_confidence_avg gauge",
        f"opsmind_rca_confidence_avg {avg:.4f}",
        "# HELP opsmind_incidents_failed_total Incidents that errored out",
        "# TYPE opsmind_incidents_failed_total counter",
        f"opsmind_incidents_failed_total {failed_total}",
        "# HELP opsmind_agent_latency_seconds_avg Mean end-to-end investigation latency",
        "# TYPE opsmind_agent_latency_seconds_avg gauge",
        f"opsmind_agent_latency_seconds_avg {avg_lat:.4f}",
        "# HELP opsmind_tool_calls_total Tool invocations recorded as evidence",
        "# TYPE opsmind_tool_calls_total counter",
    ]
    for tool, n in sorted(tool_calls.items()):
        lines.append(f'opsmind_tool_calls_total{{tool="{tool}"}} {n}')
    with _lock:
        tok = dict(llm_tokens)
        calls, errs, cost = llm_calls_total, llm_errors_total, llm_cost_usd_total
        llm_avg = llm_latency_sum / llm_latency_count if llm_latency_count else 0
        esev, erca, elast = eval_severity_accuracy, eval_rca_accuracy, eval_last_unix
    total_inc = sum(incidents_by_severity.values())
    resolved = incidents_by_status.get("resolved", 0)
    success_rate = (resolved / total_inc) if total_inc else 0
    lines += [
        "# HELP opsmind_rag_queries_total RAG retrieval queries",
        "# TYPE opsmind_rag_queries_total counter",
        f"opsmind_rag_queries_total {rag_queries}",
        "# HELP opsmind_llm_tokens_total LLM tokens by model+direction",
        "# TYPE opsmind_llm_tokens_total counter",
    ]
    for (model, direction), n in sorted(tok.items()):
        lines.append(f'opsmind_llm_tokens_total{{model="{model}",direction="{direction}"}} {n}')
    lines += [
        "# HELP opsmind_llm_calls_total LLM calls",
        "# TYPE opsmind_llm_calls_total counter",
        f"opsmind_llm_calls_total {calls}",
        "# HELP opsmind_llm_errors_total LLM errors",
        "# TYPE opsmind_llm_errors_total counter",
        f"opsmind_llm_errors_total {errs}",
        "# HELP opsmind_llm_cost_usd_total Estimated LLM cost USD",
        "# TYPE opsmind_llm_cost_usd_total counter",
        f"opsmind_llm_cost_usd_total {cost:.6f}",
        "# HELP opsmind_llm_latency_seconds_avg Mean LLM call latency",
        "# TYPE opsmind_llm_latency_seconds_avg gauge",
        f"opsmind_llm_latency_seconds_avg {llm_avg:.4f}",
        "# HELP opsmind_agent_success_rate Resolved / total incidents",
        "# TYPE opsmind_agent_success_rate gauge",
        f"opsmind_agent_success_rate {success_rate:.4f}",
        "# HELP opsmind_eval_severity_accuracy Last gated eval severity accuracy",
        "# TYPE opsmind_eval_severity_accuracy gauge",
        f"opsmind_eval_severity_accuracy {esev:.4f}",
        "# HELP opsmind_eval_rca_accuracy Last gated eval RCA accuracy",
        "# TYPE opsmind_eval_rca_accuracy gauge",
        f"opsmind_eval_rca_accuracy {erca:.4f}",
        "# HELP opsmind_eval_last_unix Last eval run unixtime",
        "# TYPE opsmind_eval_last_unix gauge",
        f"opsmind_eval_last_unix {elast:.0f}",
    ]
    return "\n".join(lines) + "\n"
