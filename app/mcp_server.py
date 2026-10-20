import logging
import re

log = logging.getLogger(__name__)

SERVICE_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,64}$")
METRICS_ALLOWLIST = (
    "error_rate", "p95_latency_ms", "cpu_pct", "memory_pct",
    "db_connections", "redis_up", "pods_ready", "request_rate",
)

READ_ONLY_TOOLS = frozenset({
    "query_metrics", "search_logs", "get_deployment_history",
    "get_traces", "search_runbooks",
})


def _service(name: str) -> str:
    name = str(name or "").strip()
    if not SERVICE_RE.match(name):
        raise ValueError(f"invalid service {name!r}: 1-64 chars of [a-zA-Z0-9_.-]")
    return name


def query_metrics_impl(service: str, metric: str) -> dict:
    from app.tools.prometheus import query_metric

    service = _service(service)
    metric = str(metric or "").strip()
    if metric not in METRICS_ALLOWLIST:
        raise ValueError(f"unknown metric {metric!r}; pick from {list(METRICS_ALLOWLIST)}")
    return query_metric({"service": service, "metrics": {}}, metric)


def search_logs_impl(service: str, query: str, limit: int = 20) -> list:
    from app.tools.loki import search_logs as _search

    service = _service(service)
    query = str(query or "")[:500]
    limit = max(1, min(50, int(limit or 20)))
    return list(_search(service, query, None))[:limit]


def get_deployment_history_impl(service: str) -> dict:
    from app.tools.kubernetes import get_deployment_history as _history

    return _history(_service(service), None)


def get_traces_impl(service: str, limit: int = 5) -> list:
    from app.tools.traces import get_trace as _trace

    limit = max(1, min(20, int(limit or 5)))
    return list(_trace(_service(service), limit=limit))


def search_runbooks_impl(query: str, top_k: int = 3) -> list:
    from app.rag.retrieve import retrieve_runbooks

    query = str(query or "")[:2000]
    if not query.strip():
        raise ValueError("query must not be empty")
    top_k = max(1, min(5, int(top_k or 3)))
    return [
        {"source": str(d.get("source", "unknown"))[:128],
         "text": str(d.get("text", ""))[:2000],
         "score": float(d.get("score", 0) or 0)}
        for d in retrieve_runbooks(query, top_k=top_k)
    ]


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise RuntimeError(
            "mcp is not installed (pip install -r requirements.txt) — "
            "needed to serve MCP; tool impls above still import fine"
        ) from e
    mcp = FastMCP("opsmind-tools")
    mcp.tool(name="query_metrics")(query_metrics_impl)
    mcp.tool(name="search_logs")(search_logs_impl)
    mcp.tool(name="get_deployment_history")(get_deployment_history_impl)
    mcp.tool(name="get_traces")(get_traces_impl)
    mcp.tool(name="search_runbooks")(search_runbooks_impl)
    return mcp


def main(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="OpsMind read-only MCP tools")
    p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args(argv)
    mcp = create_server()
    if args.transport == "http":
        try:
            mcp.run(transport="streamable-http", port=args.port)
        except TypeError:
            log.warning("installed mcp has no streamable-http transport; using stdio")
            mcp.run()
    else:
        mcp.run()


if __name__ == "__main__":
    main()
