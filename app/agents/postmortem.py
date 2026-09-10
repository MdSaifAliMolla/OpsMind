"""Incident postmortem draft. LLM-only by design: rules can't write prose."""
import logging

log = logging.getLogger(__name__)


def write_postmortem(state: dict):
    from app.agents.llm import get_llm

    llm = get_llm()
    if llm is None:
        return None
    try:
        res = llm.invoke(
            "Write a short incident postmortem (markdown: Summary, Timeline, Root cause, "
            "Remediation, Follow-ups) from this investigation result:\n\n"
            f"Incident: {state['incident'].get('incident_id')} on "
            f"{state['incident'].get('service')} ({state['incident'].get('alert_type')})\n"
            f"Severity: {state.get('severity')}\n"
            f"Root cause (confidence {state.get('confidence')}): {state.get('root_cause')}\n"
            f"Hypotheses considered: {[h['root_cause'] for h in state.get('hypotheses', [])]}\n"
            f"Remediation: {state.get('remediation_plan')}\n"
            f"Verification: {state.get('verification_result')}\n"
        )
        return res.content if isinstance(res.content, str) else str(res.content)
    except Exception as e:
        log.debug(f"postmortem failed: {e}")
        return None
