"""Regression tests for the 2.3.11 enterprise follow-up fixes."""

import asyncio
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


def _secured_session():
    from springbootai.orm.pymybatis.core.sql_session import SqlSession
    from springbootai.orm.pymybatis.security import RoleBasedAccessControl

    session = object.__new__(SqlSession)
    session.configuration = SimpleNamespace(access_control_enabled=True)
    session.access_control = RoleBasedAccessControl(enabled=True)
    session._user_context = {
        "role": "user",
        "tenant_id": "x' OR 1=1 --",
    }
    return session


def test_access_control_binds_claims_before_order_by_and_rejects_raw_literals():
    from springbootai.orm.pymybatis.dynamic_sql import SecurityError
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    session.access_control.add_rule(
        "user",
        "orders",
        "select",
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
    )
    params = {}
    secured = session._apply_access_control(
        "SELECT * FROM orders WHERE active = 1 ORDER BY id", params, "SELECT")
    assert "ORDER BY id AND" not in secured
    assert secured.index("tenant_id") < secured.index("ORDER BY")
    assert "OR 1=1" not in secured
    assert list(params.values()) == ["x' OR 1=1 --"]

    unsafe = _secured_session()
    unsafe.access_control.add_rule(
        "user", "orders", "select",
        condition=lambda user, _params: f"tenant_id = '{user['tenant_id']}'",
    )
    with pytest.raises(SecurityError, match="参数化|不安全"):
        unsafe._apply_access_control("SELECT * FROM orders", {}, "SELECT")


def test_access_control_covers_writes_and_field_permissions():
    from springbootai.orm.pymybatis.dynamic_sql import SecurityError
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    with pytest.raises(SecurityError, match="UPDATE"):
        session._apply_access_control(
            "UPDATE orders SET status = #{status} WHERE id = #{id}",
            {"status": "paid", "id": 1},
            "UPDATE",
        )

    session.access_control.add_rule(
        "user", "orders", "update", fields=["status"],
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
    )
    params = {"status": "paid", "id": 1}
    secured = session._apply_access_control(
        "UPDATE orders SET status = #{status} WHERE id = #{id} RETURNING id",
        params,
        "UPDATE",
    )
    assert secured.index("tenant_id") < secured.index("RETURNING")
    assert "x' OR 1=1" not in secured

    with pytest.raises(SecurityError, match="字段"):
        session._apply_access_control(
            "UPDATE orders SET owner = #{owner} WHERE id = #{id}",
            {"owner": "other", "id": 1},
            "UPDATE",
        )

    with pytest.raises(SecurityError, match="INSERT"):
        session._apply_access_control(
            "INSERT INTO orders (status) VALUES (#{status})",
            {"status": "new"},
            "INSERT",
        )


def test_access_control_secures_every_union_branch_and_field_list():
    from springbootai.orm.pymybatis.dynamic_sql import SecurityError
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    session._user_context = {"role": "user", "tenant_id": "A"}
    session.access_control.add_rule(
        "user", "orders", "select", fields=["id"],
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
    )
    params = {}
    secured = session._apply_access_control(
        "SELECT id FROM orders UNION ALL SELECT id FROM orders",
        params,
        "SELECT",
    )
    assert secured.count("tenant_id") == 2
    assert len(params) == 2

    with pytest.raises(SecurityError, match="字段"):
        session._apply_access_control(
            "SELECT id FROM orders UNION ALL SELECT secret FROM orders",
            {},
            "SELECT",
        )
    quoted = session._apply_access_control(
        'SELECT id FROM "orders"', {}, "SELECT")
    assert "tenant_id" in quoted


def test_access_control_filters_subqueries_in_their_own_scope_and_count_wrapper():
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    session._user_context = {"role": "user", "tenant_id": "A"}
    for table in ("orders", "payments"):
        session.access_control.add_rule(
            "user", table, "select",
            condition=lambda user, _params: AccessCondition(
                "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
        )

    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders(id INTEGER, tenant_id TEXT)")
    connection.execute(
        "CREATE TABLE payments(order_id INTEGER, tenant_id TEXT, secret TEXT)")
    connection.execute("INSERT INTO orders VALUES (1, 'A')")
    connection.executemany(
        "INSERT INTO payments VALUES (?, ?, ?)",
        [(1, "B", "TENANT-B-SECRET"), (1, "A", "tenant-a-data")],
    )

    def execute(sql, params):
        values = []

        def bind(match):
            values.append(params[match.group(1)])
            return "?"

        prepared = re.sub(r"#\{([^}]+)\}", bind, sql)
        return connection.execute(prepared, values).fetchall()

    params = {}
    secured = session._apply_access_control(
        "SELECT id, (SELECT secret FROM payments p "
        "WHERE p.order_id = orders.id LIMIT 1) AS payment_secret FROM orders",
        params,
        "SELECT",
    )
    assert execute(secured, params) == [(1, "tenant-a-data")]

    count_params = {}
    secured_count = session._apply_access_control(
        "SELECT COUNT(*) AS total FROM (SELECT id FROM orders) t",
        count_params,
        "SELECT",
    )
    assert execute(secured_count, count_params) == [(1,)]

    cte_params = {}
    secured_cte = session._apply_access_control(
        "WITH visible AS (SELECT id FROM orders) SELECT id FROM visible",
        cte_params,
        "SELECT",
    )
    assert execute(secured_cte, cte_params) == [(1,)]


def test_before_commit_veto_propagates_but_after_commit_remains_best_effort():
    from springbootai.tx.synchronization import (
        TransactionSynchronization,
        TransactionSynchronizationManager,
    )

    calls = []

    class Sync(TransactionSynchronization):
        def before_commit(self):
            raise RuntimeError("veto")

        def after_commit(self):
            calls.append("after")
            raise RuntimeError("too late")

    token = TransactionSynchronizationManager.init_synchronization()
    try:
        TransactionSynchronizationManager.register_synchronization(Sync())
        with pytest.raises(RuntimeError, match="veto"):
            TransactionSynchronizationManager.trigger_before_commit()
        TransactionSynchronizationManager.trigger_after_commit()
        assert calls == ["after"]
    finally:
        TransactionSynchronizationManager.restore_synchronization(token)


def test_transaction_synchronization_restores_outer_context():
    from springbootai.tx.synchronization import (
        TransactionSynchronization,
        TransactionSynchronizationManager,
    )

    outer_token = TransactionSynchronizationManager.init_synchronization()
    outer = TransactionSynchronization()
    TransactionSynchronizationManager.register_synchronization(outer)
    inner_token = TransactionSynchronizationManager.init_synchronization()
    inner = TransactionSynchronization()
    TransactionSynchronizationManager.register_synchronization(inner)
    assert TransactionSynchronizationManager.get_synchronizations() == [inner]
    TransactionSynchronizationManager.restore_synchronization(inner_token)
    assert TransactionSynchronizationManager.get_synchronizations() == [outer]
    TransactionSynchronizationManager.restore_synchronization(outer_token)


def _rabbit_bus_config():
    return {
        "spring": {
            "application": {"name": "orders", "instance-id": "test-1"},
            "cloud": {"bus": {
                "enabled": True,
                "backend": "rabbitmq",
                "destination": "springCloudBus",
            }},
        }
    }


def test_rabbit_bus_registers_consumer_and_delivers_only_broker_message(monkeypatch):
    from springbootai.cloud.bus import BusEvent, event_bus
    from springbootai.messaging.rabbitmq import rabbitmq_client

    captured = {}
    monkeypatch.setattr(rabbitmq_client, "declare_exchange", lambda *a, **k: None)
    monkeypatch.setattr(rabbitmq_client, "declare_queue", lambda *a, **k: None)
    monkeypatch.setattr(rabbitmq_client, "bind_queue", lambda *a, **k: None)
    monkeypatch.setattr(
        rabbitmq_client,
        "consume",
        lambda queue, callback, **kwargs: captured.update(callback=callback),
    )
    monkeypatch.setattr(
        rabbitmq_client, "start_consuming_background", lambda: object())
    monkeypatch.setattr(
        rabbitmq_client,
        "publish",
        lambda exchange, routing_key, body, **kwargs: captured.update(body=body),
    )

    event_bus.reset()
    event_bus.configure(_rabbit_bus_config())
    event_bus.start()
    received = []
    event_bus.subscribe("refreshConfig", received.append)
    event = BusEvent(type="refreshConfig")
    event_bus.publish(event)
    assert received == []
    assert event_bus.get_publish_outcome(event.id) == "broadcasted"
    captured["callback"](captured["body"])
    assert [item.id for item in received] == [event.id]
    event_bus.configure({"spring": {"cloud": {"bus": {"enabled": False}}}})


def test_rabbit_bus_failure_is_visible_and_does_not_fake_local_success(monkeypatch):
    from springbootai.cloud.bus import BusEvent, BusPublishError, event_bus
    from springbootai.messaging.rabbitmq import rabbitmq_client

    monkeypatch.setattr(rabbitmq_client, "declare_exchange", lambda *a, **k: None)
    monkeypatch.setattr(rabbitmq_client, "declare_queue", lambda *a, **k: None)
    monkeypatch.setattr(rabbitmq_client, "bind_queue", lambda *a, **k: None)
    monkeypatch.setattr(rabbitmq_client, "consume", lambda *a, **k: None)
    monkeypatch.setattr(
        rabbitmq_client, "start_consuming_background", lambda: object())

    def fail(*_args, **_kwargs):
        raise TimeoutError("broker unavailable")

    monkeypatch.setattr(rabbitmq_client, "publish", fail)
    event_bus.reset()
    event_bus.configure(_rabbit_bus_config())
    event_bus.start()
    delivered = []
    event_bus.subscribe("audit", delivered.append)
    event = BusEvent(type="audit")
    with pytest.raises(BusPublishError):
        event_bus.publish(event)
    assert delivered == []
    assert event_bus.get_publish_outcome(event.id) == "failed"
    assert event_bus.get_stats()["failed"] == 1
    event_bus.configure({"spring": {"cloud": {"bus": {"enabled": False}}}})


def test_mcp_collections_results_and_schema_depth_are_bounded():
    from springbootai.mcp.client import MCPClientConnection, MCPClientError
    from springbootai.mcp.config import MCPClientProperties

    props = MCPClientProperties(
        name="bounded",
        transport="stdio",
        command="unused",
        allowed_tools=("*",),
        max_response_bytes=4096,
        max_collection_items=1,
        max_schema_depth=2,
    )
    connection = MCPClientConnection(props)

    async def too_many(*_args, **_kwargs):
        return SimpleNamespace(tools=[SimpleNamespace(), SimpleNamespace()])

    connection._request = too_many
    with pytest.raises(MCPClientError, match="max_collection_items"):
        asyncio.run(connection.list_tools())

    async def deep_schema(*_args, **_kwargs):
        tool = SimpleNamespace(input_schema={"a": {"b": {"c": "x"}}})
        return SimpleNamespace(tools=[tool])

    connection._request = deep_schema
    with pytest.raises(MCPClientError, match="max_schema_depth"):
        asyncio.run(connection.list_tools())

    async def huge_result(*_args, **_kwargs):
        return SimpleNamespace(
            is_error=False,
            structured_content={"result": "x" * 5000},
            content=[],
        )

    connection._request = huge_result
    with pytest.raises(MCPClientError, match="max_response_bytes"):
        asyncio.run(connection.call_tool("anything", {}))


def test_mcp_url_rejects_embedded_credentials_and_fragments():
    from springbootai.mcp.config import MCPClientProperties, MCPConfigurationError

    with pytest.raises(MCPConfigurationError, match="credentials or fragments"):
        MCPClientProperties(
            name="bad",
            url="https://user:secret@example.com/mcp#fragment",
        ).validate()


def test_ai_tool_schema_rejects_redos_patterns():
    from springbootai.ai.tools import (
        ToolExecutionError,
        ToolExecutionPolicy,
        ToolRegistry,
    )

    registry = ToolRegistry(ToolExecutionPolicy(allowed_tools={"match"}))
    registry.register_schema(
        "match",
        lambda value: value,
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string", "pattern": "(a+)+$"},
            },
            "required": ["value"],
        },
    )
    with pytest.raises(ToolExecutionError, match="unsafe or invalid pattern"):
        registry.execute("match", {"value": "a" * 100 + "!"})


def test_prometheus_summary_and_tracer_storage_are_bounded():
    from springbootai.cloud.tracer import Tracer
    from springbootai.monitoring.prometheus import PrometheusMetrics

    metrics = PrometheusMetrics(
        namespace=f"test_{uuid4().hex}", subsystem="hardening")
    assert metrics.create_summary("latency", "latency") is not None
    with pytest.raises(ValueError, match="Histogram"):
        metrics.create_summary("quantiles", "quantiles", objectives={0.9: 0.01})

    tracer = Tracer("bounded", export_to_log=False, max_finished_spans=2)
    for index in range(3):
        span = tracer.start_span(f"span-{index}")
        tracer.end_span(span)
    assert [span.name for span in tracer.get_spans()] == ["span-1", "span-2"]


def test_actuator_does_not_return_prometheus_exception_text(monkeypatch):
    from springbootai.monitoring.prometheus import prometheus_metrics
    from springbootai.web.actuator import prometheus_endpoint

    def fail():
        raise RuntimeError("password=super-secret")

    monkeypatch.setattr(prometheus_metrics, "generate_metrics_data", fail)
    response = prometheus_endpoint(None)
    assert response.status_code == 500
    assert b"super-secret" not in response.body
    assert response.body == b"# error: metrics unavailable\n"


def test_runtime_and_distribution_versions_match():
    import springbootai

    pyproject = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    assert springbootai.__version__ == match.group(1) == "2.3.11"
