"""RAGAS-lite: faithfulness + answer relevancy, LLM-judged.

Standard RAGAS asks: are the retrieved contexts relevant, and is the answer
grounded in them? Context precision/recall are already covered by hit@3
(analysis.retrieval_metrics); this module adds the two LLM-judged halves:

- faithfulness: fraction of hypothesis claims supported by the evidence.
- answer relevancy: does the root cause actually address the alert?

Both return None (not zero) when the judge fails — unevaluated, not bad.
No reranker by decision: single-stage cosine + healthy-postmortem boost.
"""
import json

from app.agents.llm import content_to_text, invoke_tracked


def _judge(prompt: str):
    try:
        res = invoke_tracked(prompt, where="ragas")
        data = json.loads(content_to_text(res.content).strip())
        return data if isinstance(data, dict) else None
    except Exception:
        try:
            text = content_to_text(res.content)
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(text[start:end + 1])
                return data if isinstance(data, dict) else None
        except Exception:
            pass
    return None


def faithfulness(hypotheses, evidence) -> float | None:
    """Supported factual claims / total claims across hypotheses."""
    hyps = hypotheses or []
    if not hyps:
        return None
    claims = []
    for h in hyps[:3]:
        if not isinstance(h, dict):
            continue
        for key in ("supporting", "contradicting"):
            for c in (h.get(key) or [])[:8]:
                claims.append(str(c)[:300])
    if not claims:
        return None
    ev_text = "\n".join(
        str(e.get("result") if isinstance(e, dict) else e)[:500]
        for e in (evidence or [])[:12])[:8000]
    data = _judge(
        "For each numbered claim, say supported(true/false) by the evidence. "
        'Reply ONLY JSON: {"supported": <int>, "total": <int>}.\n\nClaims:\n'
        + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims[:20]))
        + f"\n\nEvidence:\n{ev_text}")
    if not data:
        return None
    try:
        total = int(data.get("total", 0))
        if total <= 0:
            return None
        return round(max(0, min(total, int(data.get("supported", 0)))) / total, 3)
    except (TypeError, ValueError):
        return None


def answer_relevancy(root_cause: str, incident: dict) -> float | None:
    """0-1: does the diagnosis address this alert?"""
    if not root_cause:
        return None
    incident = incident or {}
    data = _judge(
        "Rate 0-1 how directly the diagnosis addresses the alert "
        "(1 = names this failure, 0 = unrelated). "
        'Reply ONLY JSON: {"score": <float>}.\n\nAlert: '
        f"{incident.get('alert_type')} on {incident.get('service')}\n"
        f"Diagnosis: {root_cause}")
    if not data:
        return None
    try:
        return round(max(0.0, min(1.0, float(data.get("score")))), 3)
    except (TypeError, ValueError):
        return None


def score_incident(result: dict, incident: dict) -> dict:
    return {
        "faithfulness": faithfulness(result.get("hypotheses"),
                                     result.get("evidence")),
        "answer_relevancy": answer_relevancy(result.get("root_cause"), incident),
    }
