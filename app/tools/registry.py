import json

from langchain_core.tools import tool


def build_tools(incident: dict):
    @tool
    def query_metrics(metric: str) -> str:
        """Get a metric value for the incident service (error_rate, p95_latency_ms, cpu_pct, memory_pct, db_connections, redis_up, pods_ready, request_rate)"""
        from app.tools.prometheus import query_metric_synthetic
        return json.dumps(query_metric_synthetic(incident, metric))

    @tool
    def search_logs(query: str) -> str:
        """Search recent logs for the incident service"""
        from app.tools.loki import search_logs as _search
        return json.dumps(_search(incident["service"], query, incident))

    @tool
    def get_deployment_history() -> str:
        """Check when the service was last deployed"""
        from app.tools.kubernetes import get_deployment_history as _history
        return json.dumps(_history(incident["service"], incident))

    return [query_metrics, search_logs, get_deployment_history]
