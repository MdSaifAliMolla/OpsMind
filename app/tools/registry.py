import json

from langchain_core.tools import tool


def build_tools(incident: dict):
    svc = str((incident or {}).get("service", "unknown"))[:128]

    @tool
    def query_metrics(metric: str) -> str:
        """Get a metric value for the incident service."""
        from app.tools.prometheus import query_metric
        return json.dumps(query_metric(incident, str(metric)[:64]))

    @tool
    def search_logs(query: str) -> str:
        """Search recent logs for the incident service."""
        from app.tools.loki import search_logs as _search
        return json.dumps(_search(svc, str(query or "")[:500], incident))

    @tool
    def get_deployment_history() -> str:
        """Get last deploy info for the service."""
        from app.tools.kubernetes import get_deployment_history as _history
        return json.dumps(_history(svc, incident))

    @tool
    def get_trace() -> str:
        """Get recent traces for the incident service."""
        from app.tools.traces import get_trace as _trace
        return json.dumps(_trace(svc))

    return [query_metrics, search_logs, get_deployment_history, get_trace]
