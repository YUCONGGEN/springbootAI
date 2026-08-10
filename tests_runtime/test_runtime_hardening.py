import asyncio
import json
import runpy
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from spring.annotations.cloud import GlobalTransactional, NacosValue
from spring.annotations.core import GetMapping
from spring.aop.cloud_aop import global_transactional_decorator
from spring.cloud.gateway import GatewayFilter, GatewayRouter
from spring.cloud.seata import SeataTransactionManager, init_seata
from spring.config.config_loader import ConfigLoader, ConfigurationError
from spring.context.application_context import ApplicationContext
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


def test_config_injection_does_not_replace_annotated_controller_method():
    class Controller:
        @GetMapping("/config")
        @NacosValue("app.name")
        def get_config(self):
            return {"name": "demo"}

    instance = Controller()

    class BeanFactory:
        @staticmethod
        def get_bean_names():
            return ["controller"]

        @staticmethod
        def get_bean_definition(name):
            return type("Definition", (), {"annotations": {}})()

        @staticmethod
        def get_bean(name):
            return instance

    class Loader:
        @staticmethod
        def resolve_value_expression(value, default=None):
            return "configured-name"

    context = object.__new__(ApplicationContext)
    context.bean_factory = BeanFactory()
    context.config_loader = Loader()
    context._autowire_value_annotations()

    assert callable(instance.get_config)
    assert instance.get_config() == {"name": "demo"}


def test_production_security_check_reads_server_cors(monkeypatch):
    class CapturingLogger:
        def __init__(self):
            self.messages = []

        def warning(self, message):
            self.messages.append(message)

    application = SpringApplication(object)
    logger = CapturingLogger()
    application.logger = logger
    monkeypatch.setenv("SPRING_DISABLE_DOCKER_IP_DETECT", "1")

    application._production_security_check({
        "jwt": {"secret_key": "x" * 40},
        "database": {"enabled": False},
        "server": {"cors": {"allow_origins": ["*"]}},
    })

    assert any("CORS allows all origins" in message for message in logger.messages)


def test_fail_fast_parses_string_boolean_values():
    assert SpringApplication._should_fail_fast({"startup": {"fail_fast": "false"}}) is False
    assert SpringApplication._should_fail_fast({"startup": {"fail_fast": "TRUE"}}) is True


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


def test_gateway_install_assigns_unique_openapi_operation_ids():
    gateway = GatewayRouter(default_filters=[])
    app = FastAPI()
    gateway.install(
        app,
        "/gateway/{path:path}",
        methods=["GET", "POST", "PUT"],
    )

    path_item = app.openapi()["paths"]["/gateway/{path}"]
    operation_ids = [path_item[method]["operationId"] for method in ("get", "post", "put")]

    assert operation_ids == [
        "gateway_get_gateway_path_path",
        "gateway_post_gateway_path_path",
        "gateway_put_gateway_path_path",
    ]
    assert len(operation_ids) == len(set(operation_ids))


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


def test_gateway_response_size_limit_rejects_via_content_length():
    """上游响应 Content-Length 超过 max_response_size → 502（快速路径，不读取响应体）"""
    async def upstream(request: httpx.Request) -> httpx.Response:
        # 返回大 Content-Length 但实际 body 较小（模拟头部声明超限）
        return httpx.Response(
            200, content=b"small",
            headers={"content-length": "999999999"},
        )

    gateway = GatewayRouter(
        default_filters=[], max_response_size=1024,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.get("/api/data")

    response = asyncio.run(scenario())
    assert response.status_code == 502
    assert "too large" in response.json()["error"]


def test_gateway_response_size_limit_rejects_actual_body():
    """上游响应体实际大小超过 max_response_size → 502（预载路径）"""
    large_body = b"x" * 2048  # 2KB，超过 1KB 限制

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=large_body)

    gateway = GatewayRouter(
        default_filters=[], max_response_size=1024,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.get("/api/data")

    response = asyncio.run(scenario())
    assert response.status_code == 502
    assert "too large" in response.json()["error"]


def test_gateway_response_size_limit_allows_within_limit():
    """上游响应体大小在 max_response_size 内 → 正常转发"""
    body = b"x" * 512  # 512B，在 1KB 限制内

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"x-custom": "kept"})

    gateway = GatewayRouter(
        default_filters=[], max_response_size=1024,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.get("/api/data")

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.content == body
    assert response.headers.get("x-custom") == "kept"


def test_gateway_response_size_limit_zero_disables_check():
    """max_response_size=0 → 禁用响应大小检查（向后兼容）"""
    large_body = b"x" * (60 * 1024 * 1024)  # 60MB，超过默认 50MB 限制

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=large_body)

    gateway = GatewayRouter(
        default_filters=[], max_response_size=0,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            return await client.get("/api/data")

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert len(response.content) == 60 * 1024 * 1024


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


def test_http_compensation_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="opt-in"):
        init_seata({"mode": "http"})


def test_async_global_transaction_completion_runs_off_event_loop(monkeypatch):
    manager = SeataTransactionManager()
    manager.set_mode("local")
    event_loop_thread = threading.get_ident()
    completion_threads = []
    original_commit = manager.commit_transaction

    def observed_commit(tx_id):
        completion_threads.append(threading.get_ident())
        time.sleep(0.03)
        return original_commit(tx_id)

    monkeypatch.setattr(manager, "commit_transaction", observed_commit)

    @global_transactional_decorator(GlobalTransactional(name="offload"))
    async def business():
        await asyncio.sleep(0)
        return "done"

    assert asyncio.run(business()) == "done"
    assert completion_threads and completion_threads[0] != event_loop_thread
    assert manager.is_in_transaction() is False


def test_async_http_transaction_coordination_io_runs_off_event_loop(monkeypatch, tmp_path):
    manager = SeataTransactionManager()
    manager.configure(
        mode="http",
        store_path=str(tmp_path / "async-http.sqlite3"),
        recovery_interval_s=0,
    )
    event_loop_thread = threading.get_ident()
    begin_threads = []
    commit_threads = []
    original_begin = manager.begin_transaction
    original_commit = manager.commit_transaction

    def observed_begin(*args, **kwargs):
        begin_threads.append(threading.get_ident())
        return original_begin(*args, **kwargs)

    def observed_commit(*args, **kwargs):
        commit_threads.append(threading.get_ident())
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(manager, "begin_transaction", observed_begin)
    monkeypatch.setattr(manager, "commit_transaction", observed_commit)

    @global_transactional_decorator(GlobalTransactional(name="async-http"))
    async def business():
        await asyncio.sleep(0)
        return "done"

    assert asyncio.run(business()) == "done"
    assert begin_threads and begin_threads[0] != event_loop_thread
    assert commit_threads and commit_threads[0] != event_loop_thread
    assert manager.is_in_transaction() is False
    manager.set_mode("local")
    manager._transaction_store = None
    manager._transaction_store_path = ""


def test_distributed_seata_initialization_fails_closed(monkeypatch):
    """distributed 模式初始化失败时必须 fail-closed，不能静默降级到 local。

    当前实现：``set_mode('distributed')`` 先设置 mode 再调用 ``_init_seata_client()``，
    后者在 ``application_id`` 缺失或 bridge 不可达时抛 ``RuntimeError``。
    即使初始化失败，mode 仍保持 ``distributed``，后续 ``begin_transaction`` 会因
    bridge 未初始化而抛异常，确保不会用 local 模式执行核心业务。
    """
    manager = SeataTransactionManager()
    manager.set_mode("local")
    manager._seata_client_initialized = False
    # application_id 未配置 → _init_seata_client 抛 RuntimeError
    manager.application_id = ""

    with pytest.raises(RuntimeError, match="application_id is required"):
        manager.set_mode("distributed")
    # 即使初始化失败，mode 仍保持 distributed（fail-closed，不降级到 local）
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


def test_health_check_timeout_does_not_leak_threads(monkeypatch):
    """健康检查组件卡死时，线程数应受 _HEALTH_CHECK_POOL.max_workers 限制，不会无限增长。

    修复线程泄漏（P1）：旧版本每次健康检查创建新的 daemon 线程，
    组件永久卡住时线程不断积累。新版本使用模块级有界线程池。
    """
    import spring.web.health as health

    # 模拟永久卡住的组件检查（永远不会返回）
    hang_event = threading.Event()

    def _hanging_check():
        hang_event.wait(timeout=30)  # 永久阻塞
        return {"status": "UP", "enabled": True}

    # 替换组件检查为永久卡住的函数
    monkeypatch.setattr(health, "_COMPONENT_CHECKS", {
        f"hang_{i}": (lambda: _hanging_check()) for i in range(3)
    })
    # 缩短超时以加快测试
    monkeypatch.setattr(health, "_CHECK_TIMEOUT_SECONDS", 0.3)

    # 记录初始线程数
    initial_threads = threading.active_count()

    # 连续调用 5 次健康检查（模拟频繁探针）
    for _ in range(5):
        results = health._collect_component_health()
        # 每次都应返回 DOWN + timeout
        for name, result in results.items():
            assert result["status"] == "DOWN"
            assert "timeout" in result["reason"]

    # 等待一下让线程池稳定
    time.sleep(0.5)

    # 关键断言：线程数不应超过初始值 + max_workers
    # 旧版本会创建 5 × 3 = 15 个新线程；新版本受 max_workers 限制
    max_allowed = initial_threads + health._HEALTH_CHECK_WORKERS + 2  # 容忍少量调度线程
    actual_threads = threading.active_count()
    assert actual_threads <= max_allowed, (
        f"线程泄漏：当前 {actual_threads} 线程，预期不超过 {max_allowed} "
        f"（初始 {initial_threads} + 池大小 {health._HEALTH_CHECK_WORKERS}）"
    )

    # 清理：释放卡住的线程
    hang_event.set()
    time.sleep(0.5)


def test_health_check_pool_is_reused_across_calls(monkeypatch):
    """多次健康检查复用同一个线程池，不创建新的 ThreadPoolExecutor。"""
    import spring.web.health as health

    monkeypatch.setattr(health, "_COMPONENT_CHECKS", {
        "ok": lambda: {"status": "UP", "enabled": True},
    })

    pool_before = id(health._HEALTH_CHECK_POOL)
    health._collect_component_health()
    health._collect_component_health()
    health._collect_component_health()
    pool_after = id(health._HEALTH_CHECK_POOL)

    assert pool_before == pool_after, "线程池应跨调用复用，不应每次创建新池"


def test_run_with_timeout_returns_down_on_exception(monkeypatch):
    """_run_with_timeout 捕获组件异常，返回 DOWN 而非传播异常。"""
    import spring.web.health as health

    def _failing_check():
        raise ConnectionError("component unavailable")

    result = health._run_with_timeout(_failing_check, timeout=1.0)
    assert result["status"] == "DOWN"
    assert result["enabled"] is True
    assert "component unavailable" in result["reason"]


def test_http_compensation_health_reports_store_without_claiming_at(monkeypatch, tmp_path):
    import spring.web.health as health
    from spring.cloud.seata import seata_manager

    seata_manager.configure(
        mode="http",
        store_path=str(tmp_path / "health-seata.sqlite3"),
        recovery_interval_s=0,
    )
    context = type("Context", (), {
        "get_config": lambda self: {"seata": {"enabled": True, "mode": "http"}},
    })()
    monkeypatch.setattr(health, "_application_context", context)

    result = health._check_seata()

    assert result["status"] == "UP"
    assert result["mode"] == "http-compensation"
    assert "no Seata AT" in result["warning"]
    seata_manager.set_mode("local")
    seata_manager._transaction_store = None
    seata_manager._transaction_store_path = ""


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
