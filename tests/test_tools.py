import json
import os

from app.tools.kubernetes import get_deployment_history
from app.tools.loki import search_logs
from app.tools.prometheus import query_metric_synthetic


def load_incident():
    with open(os.path.join(os.getcwd(), "data/incidents/incident_001/incident.json")) as f:
        return json.load(f)


def test_metrics_come_from_incident_blob():
    assert query_metric_synthetic(load_incident(), "error_rate")["value"] > 0


def test_log_search():
    assert len(search_logs("payment-api", "pool", load_incident())) > 0


def test_deploy_history_is_recent():
    assert get_deployment_history("payment-api", load_incident())["minutesAgo"] < 30
