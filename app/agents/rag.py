from app.agents.state import mark
from app.rag.retrieve import retrieve_runbooks


def rag_node(state: dict):
    incident = state["incident"]
    q = f"{incident.get('alert_type', '')} {incident.get('service', '')} {' '.join(incident.get('logs', []))}"
    try:
        docs = retrieve_runbooks(q, top_k=3)
        return {**mark("rag"),
                "evidence": [{"source": f"rag:{d['source']}", "text": d["text"], "score": d["score"]}
                             for d in docs]}
    except Exception:
        return {**mark("rag"), "evidence": []}
