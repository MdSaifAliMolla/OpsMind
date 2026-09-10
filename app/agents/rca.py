import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm, note_llm_error
from app.agents.state import mark

SYSTEM = ("You are an SRE root-cause-analysis agent. Given evidence (metrics, logs, deployment "
          "history, runbook excerpts), propose 2-3 competing hypotheses for the root cause. For each, "
          "list supporting and contradicting evidence, then assign a confidence score 0-1. Respond ONLY "
          'as JSON: {"hypotheses": [{"root_cause": str, "supporting": [str], "contradicting": [str], '
          '"confidence": float}]}')


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of free-form model output."""
    try:
        return json.loads(text)
    except Exception:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    start = text.index("{")
    depth, end = 0, None
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end])


def rule_hypotheses(incident: dict):
    m = incident.get("metrics", {})
    logs = json.dumps(incident.get("logs", [])).lower()
    age = incident.get("deployment_minutes_ago", 99999)
    recent = age < 20
    cands = []

    if m.get("db_connections", 0) > 80 or "pool exhausted" in logs or "connection slots" in logs:
        cands.append({
            "root_cause": "database connection pool exhaustion",
            "supporting": [f"db_connections={m.get('db_connections')}",
                           "logs mention pool exhaustion",
                           f"deployed {age}m ago" if recent else "pool saturated"],
            "contradicting": [] if recent else ["no recent deploy, leak possible"],
            "confidence": 0.9 if recent else 0.82,
        })
    if m.get("pods_ready", 1) == 0 or "crashloop" in logs or "panic" in logs:
        cands.append({
            "root_cause": "bad deployment causing crashloop",
            "supporting": [f"pods_ready={m.get('pods_ready')}", "crashloop/panic in logs",
                           f"deployed {age}m ago" if recent else "all new pods crashing"],
            "contradicting": [],
            "confidence": 0.93,
        })
    if m.get("redis_up", 1) == 0 or "econnrefused" in logs or "redis" in logs:
        cands.append({
            "root_cause": "redis connection refused",
            "supporting": [f"redis_up={m.get('redis_up')}", "ECONNREFUSED in logs"],
            "contradicting": [],
            "confidence": 0.92,
        })
    if m.get("memory_pct", 0) > 85 or "oom" in logs or "heap" in logs:
        cands.append({
            "root_cause": "application memory leak",
            "supporting": [f"memory_pct={m.get('memory_pct')}", "OOM/heap messages in logs"],
            "contradicting": ["recent deploy, could be bad release instead"] if recent else [],
            "confidence": 0.88,
        })
    if m.get("cpu_pct", 0) > 75 or m.get("request_rate", 0) > 3000 or "queue depth" in logs:
        cands.append({
            "root_cause": "unprovisioned traffic spike",
            "supporting": [f"cpu={m.get('cpu_pct')}%", f"request_rate={m.get('request_rate')}",
                           "queue depth growing, no recent deploy"],
            "contradicting": ["deploy happened recently, check release first"] if recent else [],
            "confidence": 0.55 if recent else 0.85,
        })

    if not cands:
        cands.append({"root_cause": incident.get("alert_type", "unknown").replace("_", " "),
                      "supporting": ["matches incoming alert type"],
                      "contradicting": ["limited evidence"], "confidence": 0.6})

    cands.sort(key=lambda h: h["confidence"], reverse=True)
    while len(cands) < 2:
        cands.append({"root_cause": "unknown transient fault", "supporting": [],
                      "contradicting": ["no evidence"], "confidence": 0.2})
    return cands[:3]


def rca_node(state: dict):
    evidence_text = json.dumps(state.get("evidence", []), indent=2)
    llm = get_llm()
    if llm is not None:
        try:
            res = llm.invoke([
                SystemMessage(content=SYSTEM),
                HumanMessage(content=f"Incident: {state['incident'].get('alert_type')} on "
                                     f"{state['incident'].get('service')}\n\nEvidence:\n{evidence_text}"),
            ])
            text = res.content if isinstance(res.content, str) else json.dumps(res.content)
            hyps = extract_json(text)["hypotheses"]
            hyps.sort(key=lambda h: h["confidence"], reverse=True)
            return {**mark("rca"), "hypotheses": hyps, "confidence": hyps[0]["confidence"],
                    "root_cause": hyps[0]["root_cause"],
                    "investigation_loops": state.get("investigation_loops", 0) + 1}
        except Exception as e:
            note_llm_error("rca", e)

    hyps = rule_hypotheses(state["incident"])
    return {**mark("rca"), "hypotheses": hyps, "confidence": hyps[0]["confidence"],
            "root_cause": hyps[0]["root_cause"],
            "investigation_loops": state.get("investigation_loops", 0) + 1}
