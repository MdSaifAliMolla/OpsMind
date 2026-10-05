import logging

log = logging.getLogger(__name__)


def write_postmortem(state: dict):
    from app.agents.llm import content_to_text, invoke_tracked, llm_enabled

    if not llm_enabled():
        return None
    try:
        res = invoke_tracked(
            "Write a short incident postmortem (markdown: Summary, Timeline, Root cause, "
            "Remediation, Follow-ups) from this investigation result:\n\n"
            f"Incident: {state.get('incident', {}).get('incident_id')} on "
            f"{state.get('incident', {}).get('service')} ({state.get('incident', {}).get('alert_type')})\n"
            f"Severity: {state.get('severity')}\n"
            f"Root cause (confidence {state.get('confidence')}): {state.get('root_cause')}\n"
            f"Hypotheses considered: {[h.get('root_cause') for h in state.get('hypotheses', []) if isinstance(h, dict)]}\n"
            f"Remediation: {state.get('remediation_plan')}\n"
            f"Verification: {state.get('verification_result')}\n",
            where="postmortem",
        )
        return content_to_text(res.content)
    except Exception as e:
        log.debug(f"postmortem failed: {e}")
        return None
