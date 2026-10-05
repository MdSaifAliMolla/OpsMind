import pytest

from app.mcp_server import (
    READ_ONLY_TOOLS,
    get_deployment_history_impl,
    get_traces_impl,
    query_metrics_impl,
    search_logs_impl,
    search_runbooks_impl,
)


def test_tool_set_is_read_only():
    assert READ_ONLY_TOOLS == {"query_metrics", "search_logs", "get_deployment_history",
                               "get_traces", "search_runbooks"}
    for name in READ_ONLY_TOOLS:
        assert not any(v in name for v in ("execut", "scale", "rollback",
                                           "restart", "delete", "patch", "apply"))


def test_service_validation():
    with pytest.raises(ValueError):
        query_metrics_impl("", "error_rate")
    with pytest.raises(ValueError):
        query_metrics_impl("../../etc", "error_rate")
    with pytest.raises(ValueError):
        query_metrics_impl("payment-api", "drop table")


def test_query_metrics_offline_shape():
    out = query_metrics_impl("payment-api", "error_rate")
    assert set(out) >= {"value", "timestamp"}
    assert isinstance(out["value"], float)


def test_search_runbooks_validation_and_shape(monkeypatch):
    # stub retrieval to avoid the ST model load
    monkeypatch.setattr("app.rag.retrieve.retrieve_runbooks",
                        lambda q, top_k=3: [{"source": "database.md",
                                             "text": "pool fix", "score": 0.9}][:top_k])
    out = search_runbooks_impl("pool exhausted", top_k=3)
    assert out[0]["source"] == "database.md"
    with pytest.raises(ValueError):
        search_runbooks_impl("   ")
    assert len(search_runbooks_impl("x", top_k=99)) <= 5


def test_logs_traces_deploy_offline_shape():
    assert isinstance(search_logs_impl("payment-api", "pool"), list)
    assert isinstance(get_traces_impl("payment-api"), list)
    assert isinstance(get_deployment_history_impl("payment-api"), dict)


def test_server_registration():
    mcp_mod = pytest.importorskip("mcp.server.fastmcp")
    assert mcp_mod.FastMCP is not None
    from app.mcp_server import create_server
    mcp = create_server()
    assert mcp is not None
