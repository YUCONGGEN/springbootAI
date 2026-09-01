"""Regression coverage for the latest enterprise robustness audit."""

import asyncio
import gzip
import re
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


def _secured_session():
    from springbootai.orm.pymybatis.core.sql_session import SqlSession
    from springbootai.orm.pymybatis.security import RoleBasedAccessControl

    session = object.__new__(SqlSession)
    session.configuration = SimpleNamespace(access_control_enabled=True)
    session.access_control = RoleBasedAccessControl(enabled=True)
    session._user_context = {"role": "user", "tenant_id": "A"}
    return session


def _execute_bound(connection, sql, params):
    values = []

    def bind(match):
        values.append(params[match.group(1)])
        return "?"

    prepared = re.sub(r"#\{([^}]+)\}", bind, sql)
    return connection.execute(prepared, values).fetchall()


def test_join_access_control_attributes_fields_and_preserves_left_join():
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    session.access_control.add_rule(
        "user", "orders", "select", fields=["id"],
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
    )
    session.access_control.add_rule(
        "user", "payments", "select", fields=["amount"],
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
    )

    params = {}
    secured = session._apply_access_control(
        "SELECT o.id, p.amount FROM orders o "
        "LEFT JOIN payments p ON p.order_id = o.id",
        params,
        "SELECT",
    )
    assert secured.count("SELECT * FROM") == 2

    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE orders(id INTEGER, tenant_id TEXT);
        CREATE TABLE payments(order_id INTEGER, amount INTEGER, tenant_id TEXT);
        INSERT INTO orders VALUES(1, 'A');
        INSERT INTO orders VALUES(2, 'A');
        INSERT INTO payments VALUES(1, 9, 'A');
        INSERT INTO payments VALUES(2, 7, 'B');
    """)
    assert _execute_bound(connection, secured, params) == [(1, 9), (2, None)]


def test_comma_join_secures_every_physical_source():
    from springbootai.orm.pymybatis.security import AccessCondition

    session = _secured_session()
    for table in ("orders", "payments"):
        session.access_control.add_rule(
            "user", table, "select",
            condition=lambda user, _params: AccessCondition(
                "tenant_id = #{tenant}", {"tenant": user["tenant_id"]}),
        )
    params = {}
    secured = session._apply_access_control(
        "SELECT o.id, p.amount FROM orders o, payments p "
        "WHERE p.order_id = o.id",
        params,
        "SELECT",
    )
    assert secured.count("tenant_id") == 2
    assert len(params) == 2


def test_gateway_bounds_decoded_compressed_response_and_cleans_error_headers():
    from springbootai.cloud.gateway import GatewayRouter

    expanded = b"x" * (1024 * 1024)
    compressed = gzip.compress(expanded)
    observed_headers = {}

    class OneChunk(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield compressed

    async def upstream(request):
        observed_headers.update(request.headers)
        return httpx.Response(
            200,
            stream=OneChunk(),
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(compressed)),
            },
        )

    gateway = GatewayRouter(
        default_filters=[],
        max_response_size=2048,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://gateway",
            ) as client:
                return await client.get("/api/data")
        finally:
            await gateway.aclose()

    response = asyncio.run(scenario())
    assert response.status_code == 502
    assert response.json()["error"] == "Upstream response too large"
    assert "content-encoding" not in response.headers
    assert observed_headers["accept-encoding"] == "identity"


def test_transactional_cancellation_fires_rollback_synchronizations(monkeypatch):
    import springbootai.orm.mybatis_integration as integration
    from springbootai.annotations.core import Transactional
    from springbootai.context.bean_factory import BeanFactory
    from springbootai.tx.synchronization import (
        TransactionSynchronization,
        TransactionSynchronizationManager,
    )

    events = []

    class Sync(TransactionSynchronization):
        def after_rollback(self):
            events.append("after_rollback")

        def after_completion(self, status):
            events.append(f"after_completion:{status}")

    @contextmanager
    def fake_transaction(*_args, **_kwargs):
        try:
            yield object()
        except BaseException:
            events.append("db_rollback")
            raise

    monkeypatch.setattr(integration, "mybatis_transaction", fake_transaction)
    factory = BeanFactory()
    monkeypatch.setattr(factory, "get_bean", lambda _name: object())

    class Service:
        pass

    async def work(_self):
        TransactionSynchronizationManager.register_synchronization(Sync())
        raise asyncio.CancelledError()

    wrapped = factory._wrap_transactional(Service(), work, Transactional())

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await wrapped(Service())

    asyncio.run(scenario())
    assert events == [
        "db_rollback", "after_rollback", "after_completion:rollback"]
    assert not TransactionSynchronizationManager.is_synchronization_active()


def test_nested_transaction_cancellation_cleans_registered_transaction():
    from springbootai.orm.pymybatis.transaction.transaction import (
        TransactionManager,
        TransactionStatus,
    )

    connection = sqlite3.connect(":memory:")
    manager = TransactionManager()
    transaction = manager.begin(connection)
    with pytest.raises(asyncio.CancelledError), manager.transaction():
        raise asyncio.CancelledError()

    assert manager.current_transaction is None
    assert transaction.status is TransactionStatus.ROLLED_BACK
    assert transaction.nested_count == 0
    assert not connection.in_transaction


def test_async_cache_single_flight_and_mutable_value_isolation():
    from springbootai.annotations.core import Cacheable
    from springbootai.context.bean_factory import BeanFactory

    factory = BeanFactory()
    calls = 0

    class Service:
        pass

    async def load(_self, item_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"id": item_id, "items": []}

    service = Service()
    wrapped = factory._wrap_cacheable(
        service, load, Cacheable(value="items", key="{item_id}"))

    async def scenario():
        values = await asyncio.gather(
            *(wrapped(service, 1) for _ in range(20)))
        values[0]["items"].append("request-local")
        later = await wrapped(service, 1)
        return values, later

    values, later = asyncio.run(scenario())
    assert calls == 1
    assert later == {"id": 1, "items": []}
    assert len({id(value) for value in values}) == len(values)


def test_mcp_stdio_environment_isolated_by_default(monkeypatch):
    from springbootai.mcp.client import _stdio_child_environment
    from springbootai.mcp.config import MCPClientProperties, bind_mcp_config

    monkeypatch.setenv("DATABASE_PASSWORD", "must-not-leak")
    isolated = MCPClientProperties(
        name="safe",
        transport="stdio",
        command="python",
        env={"TOOL_MODE": "production"},
    )
    child_env = _stdio_child_environment(isolated)
    assert "DATABASE_PASSWORD" not in child_env
    assert child_env["TOOL_MODE"] == "production"

    inherited = bind_mcp_config({
        "enabled": True,
        "clients": {
            "legacy": {
                "transport": "stdio",
                "command": "python",
                "inherit-environment": True,
            },
        },
    }).clients[0]
    assert _stdio_child_environment(inherited)["DATABASE_PASSWORD"] == "must-not-leak"
