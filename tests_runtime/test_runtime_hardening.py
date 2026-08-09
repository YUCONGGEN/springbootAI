import asyncio
import json
import runpy
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from spring.annotations.cloud import GlobalTransactional
from spring.aop.cloud_aop import global_transactional_decorator
from spring.cloud.gateway import GatewayFilter, GatewayRouter
from spring.cloud.seata import SeataTransactionManager, init_seata
from spring.config.config_loader import ConfigLoader, ConfigurationError
from spring.main import SpringApplication
from spring.web.web_context import WebApplicationContext


def _request(path: str = "/") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    })


def test_sync_controller_runs_outside_event_loop():
    class Controller:
        def blocking(self):
            time.sleep(0.15)
            return {"thread": threading.get_ident()}

    web = WebApplicationContext(object())
    controller = Controller()
    endpoint = web._create_endpoint(controller, Controller.blocking, "/blocking")

    async def scenario():
        event_loop_thread = threading.get_ident()
        ticked_at = None
        started = time.monotonic()

        async def ticker():
            nonlocal ticked_at
            await asyncio.sleep(0.02)
            ticked_at = time.monotonic() - started

        response, _ = await asyncio.gather(endpoint(_request("/blocking")), ticker())
        payload = json.loads(response.body)
        return ticked_at, payload["data"]["thread"], event_loop_thread

    ticked_at, handler_thread, event_loop_thread = asyncio.run(scenario())
    assert ticked_at < 0.10
    assert handler_thread != event_loop_thread


def test_gateway_forwards_body_repeated_query_and_status_async():
    captured = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["query"] = list(request.url.params.multi_items())
        captured["body"] = await request.aread()
        return httpx.Response(
            201,
            content=b'{"accepted":true}',
            headers={"content-type": "application/json", "x-upstream": "yes"},
        )

    gateway = GatewayRouter(
        default_filters=[],
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test", strip_prefix=True)
    app = FastAPI()
    app.add_api_route(
        "/api/{path:path}", gateway.handle_asgi,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.post("/api/orders?tag=a&tag=b", content=b"payload")

    response = asyncio.run(scenario())
    assert response.status_code == 201
    assert response.json() == {"accepted": True}
    assert response.headers["x-upstream"] == "yes"
    assert captured == {
        "method": "POST",
        "path": "/orders",
        "query": [("tag", "a"), ("tag", "b")],
        "body": b"payload",
    }


def test_gateway_filter_and_body_limit_fail_before_upstream():
    called = False

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    gateway = GatewayRouter(
        default_filters=[], max_body_size=3,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["POST"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.post("/api/data", content=b"large")

    response = asyncio.run(scenario())
    assert response.status_code == 413
    assert called is False


def test_gateway_supports_async_filters():
    class DenyFilter(GatewayFilter):
        async def pre_filter(self, ctx):
            await asyncio.sleep(0)
            ctx.response_status = 418
            return False

    gateway = GatewayRouter(default_filters=[DenyFilter()])
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.get("/api/data")

    assert asyncio.run(scenario()).status_code == 418


def test_seata_context_is_isolated_between_async_tasks():
    manager = SeataTransactionManager()
    manager.set_mode("local")

    async def worker():
        xid = manager.begin_transaction(name="async")
        await asyncio.sleep(0.01)
        assert manager.get_current_tx_id() == xid
        assert manager.commit_transaction(xid) is True
        return xid

    async def scenario():
        return await asyncio.gather(worker(), worker())

    first, second = asyncio.run(scenario())
    assert first != second
    assert manager.is_in_transaction() is False


def test_async_global_transaction_waits_for_business_completion():
    manager = SeataTransactionManager()
    manager.set_mode("local")
    observations = []

    @global_transactional_decorator(GlobalTransactional(name="async-business"))
    async def business():
        observations.append(manager.is_in_transaction())
        await asyncio.sleep(0.01)
        observations.append(manager.is_in_transaction())
        return "done"

    assert asyncio.run(business()) == "done"
    assert observations == [True, True]
    assert manager.is_in_transaction() is False


def test_experimental_http_transaction_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="experimental"):
        init_seata({"mode": "http"})


def test_distributed_seata_initialization_fails_closed(monkeypatch):
    import spring.cloud.seata as seata_module

    manager = SeataTransactionManager()
    manager.set_mode("local")
    manager._seata_client_initialized = False
    monkeypatch.setattr(seata_module, "_seata_available", False)

    with pytest.raises(RuntimeError, match="compatible Seata Python SDK"):
        manager.set_mode("distributed")
    assert manager.get_mode() == "distributed"
    with pytest.raises(RuntimeError, match="not initialized"):
        manager.begin_transaction(name="must-not-fallback")
    manager.set_mode("local")


@pytest.mark.parametrize("mode", ["local", "http"])
def test_production_rejects_non_distributed_seata(monkeypatch, mode):
    loader = ConfigLoader(config_path="application.yml")
    loader._config["jwt"]["secret_key"] = "x" * 32
    loader._config["seata"] = {"enabled": True, "mode": mode}
    monkeypatch.setenv("SPRING_PROFILES_ACTIVE", "production")

    with pytest.raises(ConfigurationError, match="mode=distributed"):
        loader._validate_config()


def test_http_branch_without_compensation_callback_fails_closed():
    manager = SeataTransactionManager()
    manager.set_mode("http")
    xid = manager.begin_transaction(name="missing-callback")
    manager.register_branch(xid, resource_id="orders")
    assert manager.commit_transaction(xid) is False


def test_health_and_readiness_include_every_enabled_component(monkeypatch):
    import spring.web.health as health

    components = {
        "redis": {"status": "UP", "enabled": True},
        "database": {"status": "UP", "enabled": True},
        "nacos": {"status": "DOWN", "enabled": True, "reason": "offline"},
        "rabbitmq": {"status": "DISABLED", "enabled": False},
        "seata": {"status": "DISABLED", "enabled": False},
    }
    monkeypatch.setattr(health, "_collect_component_health", lambda: components)

    aggregate = health.health_check()
    readiness = health.readiness_check()
    assert aggregate.status_code == 503
    assert json.loads(aggregate.body)["status"] == "DEGRADED"
    assert readiness.status_code == 503
    assert "nacos" in json.loads(readiness.body)["reason"]


def test_prometheus_endpoint_preserves_content_type(monkeypatch):
    import spring.web.health as health
    from spring.monitoring.prometheus import CONTENT_TYPE_LATEST

    context = type("Context", (), {
        "get_config": lambda self: {"prometheus": {"enabled": True}},
    })()
    monkeypatch.setattr(health, "_application_context", context)

    response = health.prometheus_metrics()
    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST


def test_background_clients_start_only_on_worker_startup(monkeypatch):
    from spring.messaging import rabbitmq

    application = SpringApplication(type("Main", (), {}))
    application.application_context = type("Context", (), {
        "get_config": lambda self: {
            "rabbitmq": {"enabled": True},
            "server": {"port": 8080},
        },
    })()
    calls = []
    monkeypatch.setattr(
        rabbitmq.rabbitmq_client,
        "start_consuming_background",
        lambda: calls.append("rabbitmq"),
    )
    monkeypatch.setattr(
        application,
        "_register_discovery_service",
        lambda port: calls.append(("discovery", port)),
    )

    assert calls == []
    application._on_app_startup()
    application._on_app_startup()
    assert calls == ["rabbitmq", ("discovery", 8080)]


def test_gunicorn_does_not_preload_initialized_clients():
    config = runpy.run_path("deploy/gunicorn/gunicorn.conf.py")
    assert config["preload_app"] is False
    assert callable(config["child_exit"])
