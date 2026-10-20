from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import content_to_text, invoke_tracked
from app.agents.state import mark
from app.rag.retrieve import retrieve_runbooks


def rag_node(state: dict):
    incident = state["incident"]
    q = f"{incident.get('alert_type', '')} {incident.get('service', '')} {' '.join(incident.get('logs', [])[:2])}"

    sys = ("You are a DevOps expert. Given an alert, write a 3-sentence "
           "hypothetical postmortem describing the likely root cause and "
           "how it was fixed. Be highly specific.")
    res = invoke_tracked(
        [SystemMessage(content=sys),
         HumanMessage(content=f"Alert: {q}")],
        where="rag",
    )
    expanded = content_to_text(res.content).strip()
    if expanded:
        q = expanded[:2000]

    fault_family = state.get("fault_family") or (state.get("triage") or {}).get("fault_family")
    docs = retrieve_runbooks(q, top_k=3, fault_family=fault_family)
    if not docs:
        raise RuntimeError("rag: no runbooks retrieved")
    return {**mark("rag"),
            "evidence": [{"source": f"rag:{d['source']}", "text": d["text"], "score": d["score"]}
                         for d in docs]}
