"""Posts incident events to a webhook (Slack-compatible) if configured."""
import logging
import os

log = logging.getLogger(__name__)


def notify(event: str, incident: dict, detail: str = ""):
    url = os.getenv("SLACK_WEBHOOK_URL")
    text = f"[opsmind:{event}] {incident.get('incident_id')} on {incident.get('service')} {detail}".strip()
    if not url:
        log.info(text)
        return
    try:
        import requests
        requests.post(url, json={"text": text}, timeout=3)
    except Exception as e:
        log.warning(f"notify failed: {e}")
