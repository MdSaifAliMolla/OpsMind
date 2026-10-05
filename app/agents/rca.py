import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import content_to_text, invoke_tracked
from app.agents.state import mark
from app.security.untrusted import (
    PROMPT_RULE,
    build_wrapped_evidence_text,
    injection_evidence_item,
    scan_state_for_injection,
)

SYSTEM = ("You are an SRE root-cause-analysis agent. Given evidence (metrics, logs, deployment "
          "history, runbook excerpts), propose 2-3 competing hypotheses for the root cause. For each, "
          "list supporting and contradicting evidence, then assign a confidence score 0-1. Respond ONLY "
          'as JSON: {"hypotheses": [{"root_cause": str, "supporting": [str], "contradicting": [str], '
          '"confidence": float}]}'
          f"\n\n{PROMPT_RULE}")


def extract_json(text: str) -> dict:
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


def rca_node(state: dict):
    incident = state.get("incident") or {}
    evidence = state.get("evidence", []) or []
    injected = scan_state_for_injection(incident, evidence)
    evidence_text = build_wrapped_evidence_text(incident, evidence)
    alert = str(incident.get("alert_type", "unknown"))[:128]
    service = str(incident.get("service", "unknown"))[:128]
    try:
        res = invoke_tracked([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=f"Incident: {alert} on "
                                 f"{service}\n\nEvidence:\n{evidence_text}"),
        ], where="rca")
        text = content_to_text(res.content)
        hyps = extract_json(text)["hypotheses"]
    except Exception as e:
        raise RuntimeError(f"rca llm call failed: {e}") from e
    if not isinstance(hyps, list) or not hyps:
        raise RuntimeError("rca llm returned no hypotheses")
    cleaned = []
    for h in hyps[:3]:
        if not isinstance(h, dict) or not h.get("root_cause"):
            continue
        try:
            conf = float(h.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        cleaned.append({
            "root_cause": str(h["root_cause"])[:300],
            "supporting": [str(x)[:300] for x in (h.get("supporting") or [])][:8],
            "contradicting": [str(x)[:300] for x in (h.get("contradicting") or [])][:8],
            "confidence": max(0.0, min(1.0, conf)),
        })
    if not cleaned:
        raise RuntimeError("rca llm returned no valid hypotheses")
    hyps = cleaned
    hyps.sort(key=lambda h: h["confidence"], reverse=True)
    out = {**mark("rca"), "hypotheses": hyps, "confidence": hyps[0]["confidence"],
           "root_cause": hyps[0]["root_cause"],
           "investigation_loops": state.get("investigation_loops", 0) + 1}
    if injected or state.get("injection_suspected"):
        out["injection_suspected"] = True
        out["evidence"] = [injection_evidence_item("rca input matched injection heuristic")]
    return out
