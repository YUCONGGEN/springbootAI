"""Regression tests for enterprise HTTP, file-I/O and logging boundaries."""
import asyncio
import json
import logging
import re
from collections import namedtuple
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from springbootai.ai.etl import (
    CharacterTextSplitter, DocumentTooLargeError, TextReader, TokenTextSplitter,
)
from springbootai.cli import scaffold
from springbootai.cloud.feign import FeignClientProxy, FeignRequestError
from springbootai.cloud.gateway import GatewayRouter, LoadBalancerStrategy
from springbootai.cloud.gateway import (
    AuthenticationFilter, FilterContext, GatewayFilter, RateLimitFilter,
)
from springbootai.logging.context import (
    get_request_id, redact_log_data, redact_sensitive, request_context,
    sanitize_exception_value, sanitize_url,
)
from springbootai.logging.loguru_logger import (
    SensitiveDataFilter, _patch_loguru_record, _retention_backups,
    _rotation_bytes,
)
from springbootai.web.web_context import WebApplicationContext


def test_logging_context_redacts_secrets_and_adds_request_id():
    message = (
        "Authorization=Bearer top-secret password=hunter2 token=abc123 "
        "https://api.test/items?access_token=query-secret\nforged-record"
    )
    redacted = redact_sensitive(message)
    for secret in ("top-secret", "hunter2", "abc123", "query-secret"):
        assert secret not in redacted
    assert "\n" not in redacted
    quoted = redact_sensitive(
        'password="top secret" Authorization: Basic basic-secret')
    assert "top secret" not in quoted
    assert "basic-secret" not in quoted

    record = logging.LogRecord(
        "Spring.Test", logging.INFO, __file__, 1,
        "password=%s", ("record-secret",), None,
    )
    with request_context("request_123"):
        assert SensitiveDataFilter().filter(record) is True
        assert record.request_id == "request_123"
        assert "record-secret" not in record.getMessage()

    assert sanitize_url(
        "https://user:password@example.test:8443/a?token=secret#fragment"
    ) == "https://example.test:8443/a"
    assert sanitize_url("http://example.test:invalid/a") == "<invalid-url>"
    assert _rotation_bytes("2 MB") == 2 * 1024 * 1024
    assert _retention_backups("14 days") == 14

    ExceptionRecord = namedtuple(
        "ExceptionRecord", ["type", "value", "traceback"])
    structured = {
        "message": "safe",
        "extra": {
            "api_key": "extra-secret",
            "nested": {"password": "bound secret"},
            "request_id": "good\nFORGED level=ERROR",
        },
        "exception": ExceptionRecord(
            ValueError,
            ValueError('password="exception secret"'),
            None,
        ),
    }
    with request_context("trusted-request"):
        _patch_loguru_record(structured)
    assert structured["extra"] == {
        "api_key": "******",
        "nested": {"password": "******"},
        "request_id": "trusted-request",
    }
    assert "exception secret" not in str(structured["exception"].value)

    class AttributeRenderedError(Exception):
        def __init__(self):
            super().__init__("safe args")
            self.secret = "password=custom-secret"

        def __str__(self):
            return self.secret

    structured["exception"] = ExceptionRecord(
        AttributeRenderedError, AttributeRenderedError(), None)
    _patch_loguru_record(structured)
    assert "custom-secret" not in str(structured["exception"].value)

    chained = RuntimeError("safe top-level")
    chained.__cause__ = ValueError("token=chained-secret")
    sanitized = sanitize_exception_value(chained)
    assert sanitized.__cause__ is None
    assert "chained-secret" not in str(redact_log_data({"error": chained}))


def test_web_request_id_is_validated_echoed_and_bound_to_handler():
    class Context:
        @staticmethod
        def get_config():
            return {"server": {"request-id": {"header": "X-Correlation-ID"}}}

    web = WebApplicationContext(Context())
    web._register_request_context_middleware()
    web._register_request_context_middleware()

    @web.fastapi_app.get("/probe")
    async def probe():
        return {"request_id": get_request_id()}

    async def scenario():
        transport = httpx.ASGITransport(app=web.fastapi_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            accepted = await client.get(
                "/probe", headers={"X-Correlation-ID": "caller_42"})
            replaced = await client.get(
                "/probe", headers={"X-Correlation-ID": "../../bad\nvalue"})
            return accepted, replaced

    accepted, replaced = asyncio.run(scenario())
    assert accepted.headers["X-Correlation-ID"] == "caller_42"
    assert accepted.json()["request_id"] == "caller_42"
    generated = replaced.headers["X-Correlation-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert replaced.json()["request_id"] == generated


def test_request_id_wraps_cors_preflight_responses():
    class Context:
        bean_factory = SimpleNamespace(get_bean_definition=lambda _name: None)

        @staticmethod
        def get_config():
            return {"server": {"request-id": {"header": "X-Request-ID"}}}

        @staticmethod
        def get_value(key, default=None):
            if key == "server.cors":
                return {
                    "allow_origins": ["https://frontend.test"],
                    "allow_methods": ["GET", "OPTIONS"],
                    "allow_headers": ["X-Test"],
                }
            return default

        @staticmethod
        def get_bean_names():
            return []

    web = WebApplicationContext(Context())
    web._register_cors_middleware()
    web._register_request_context_middleware()

    async def scenario():
        transport = httpx.ASGITransport(app=web.fastapi_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            return await client.options("/anything", headers={
                "Origin": "https://frontend.test",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Test",
            })

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


class _FeignResponse:
    def __init__(self, content=b'{"ok": true}', headers=None):
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)

    def iter_content(self, chunk_size=64 * 1024):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index:index + chunk_size]

    def close(self):
        self.closed = True


class _FeignSession:
    def __init__(self, response=None):
        self.response = response or _FeignResponse()
        self.calls = []
        self.mounts = {}
        self.closed = False

    def mount(self, prefix, adapter):
        self.mounts[prefix] = adapter

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response

    def close(self):
        self.closed = True


def test_feign_uses_one_safe_request_path_and_closes_response(monkeypatch):
    session = _FeignSession()
    monkeypatch.setattr("requests.Session", lambda: session)
    proxy = FeignClientProxy(
        "inventory", url="https://inventory.test", timeout=2,
        connect_timeout=0.5, read_timeout=1.5,
    )

    with request_context("rid-feign"):
        assert proxy.get("/items", params={"token": "not-logged"}) == {"ok": True}

    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "https://inventory.test/items")
    assert kwargs["headers"]["X-Request-ID"] == "rid-feign"
    assert kwargs["timeout"] == (0.5, 1.5)
    assert kwargs["allow_redirects"] is False
    assert session.response.closed is True
    retry = session.mounts["https://"].max_retries
    assert "POST" not in retry.allowed_methods
    proxy.close()
    assert session.closed is True
    with pytest.raises(RuntimeError, match="closed"):
        proxy.get("/items")


def test_feign_rejects_large_responses_without_leaking_url_secret(monkeypatch):
    response = _FeignResponse(content=b"12345")
    session = _FeignSession(response)
    monkeypatch.setattr("requests.Session", lambda: session)
    proxy = FeignClientProxy(
        "inventory", url="https://inventory.test", max_response_size=4,
    )
    with pytest.raises(FeignRequestError, match="response_too_large") as raised:
        proxy.request("GET", "/items?access_token=do-not-leak")
    assert "do-not-leak" not in str(raised.value)
    assert response.closed is True
    proxy.close()


def test_feign_rejects_redirect_responses(monkeypatch):
    response = _FeignResponse()
    response.status_code = 302
    response.headers = {
        "Location": "https://attacker.test/collect?token=secret"}
    session = _FeignSession(response)
    monkeypatch.setattr("requests.Session", lambda: session)
    proxy = FeignClientProxy("inventory", url="https://inventory.test")
    try:
        with pytest.raises(FeignRequestError, match="redirect_not_allowed"):
            proxy.get("/items")
        assert session.calls[0][2]["allow_redirects"] is False
        assert response.closed is True
    finally:
        proxy.close()


def test_feign_fallback_factory_runs_after_response_is_closed(monkeypatch):
    import requests

    class FailedResponse(_FeignResponse):
        def raise_for_status(self):
            error = requests.HTTPError("private upstream detail")
            error.response = SimpleNamespace(status_code=503)
            raise error

    response = FailedResponse()
    session = _FeignSession(response)
    monkeypatch.setattr("requests.Session", lambda: session)
    observed = []

    class Fallback:
        def items(self):
            observed.append(response.closed)
            return {"source": "fallback"}

    class Factory:
        def create(self, error):
            assert isinstance(error, FeignRequestError)
            return Fallback()

    proxy = FeignClientProxy(
        "inventory", url="https://inventory.test",
        fallback_factory=Factory,
    )
    try:
        assert proxy.request(
            "GET", "/items", fallback_method="items",
        ) == {"source": "fallback"}
        assert observed == [True]
    finally:
        proxy.close()


def test_declared_feign_percent_encodes_path_values(monkeypatch):
    from springbootai.annotations import FeignClient, GetMapping, PathVariable
    from springbootai.cloud.feign import create_declared_feign_client

    @FeignClient("catalog", url="https://catalog.test")
    class CatalogClient:
        @GetMapping("/items/{item_id}")
        def item(self, item_id=PathVariable("item_id")):
            raise NotImplementedError

    annotation = CatalogClient.__spring_annotations__[0]
    client = create_declared_feign_client(CatalogClient, annotation)
    response = _FeignResponse()
    calls = []
    monkeypatch.setattr(
        client.__feign_proxy__._session, "request",
        lambda method, url, **kwargs: calls.append(url) or response,
    )
    try:
        assert client.item("folder/name ?") == {"ok": True}
        assert calls == ["https://catalog.test/items/folder%2Fname%20%3F"]
    finally:
        client.destroy()


def test_declared_feign_rejects_omitted_marker_arguments(monkeypatch):
    from springbootai.annotations import (
        FeignClient, GetMapping, PathVariable, RequestParam,
    )
    from springbootai.cloud.feign import create_declared_feign_client

    @FeignClient("catalog", url="https://catalog.test")
    class CatalogClient:
        @GetMapping("/items/{item_id}")
        def item(self, item_id=PathVariable("item_id")):
            raise NotImplementedError

        @GetMapping("/search")
        def search(self, query=RequestParam("q")):
            raise NotImplementedError

    annotation = CatalogClient.__spring_annotations__[0]
    client = create_declared_feign_client(CatalogClient, annotation)
    calls = []
    monkeypatch.setattr(
        client.__feign_proxy__._session, "request",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _FeignResponse(),
    )
    try:
        with pytest.raises(TypeError, match="path argument"):
            client.item()
        with pytest.raises(TypeError, match="required Feign argument"):
            client.search()
        assert calls == []
    finally:
        client.destroy()


def test_gateway_validates_limits_uri_and_propagates_request_id():
    with pytest.raises(ValueError, match="greater than zero"):
        GatewayRouter(timeout=0)
    gateway = GatewayRouter(default_filters=[])
    with pytest.raises(ValueError, match="embedded credentials"):
        gateway.route("/bad/**", uri="https://user:pass@example.test")
    with pytest.raises(ValueError, match="query or fragment"):
        gateway.route("/bad/**", uri="https://example.test?token=secret")
    with pytest.raises(ValueError, match="requires"):
        gateway.route("/missing/**")

    captured = {}

    async def upstream(request: httpx.Request):
        captured["request_id"] = request.headers.get("X-Request-ID")
        captured["removed_request_header"] = request.headers.get("X-Remove-Me")
        return httpx.Response(
            200, content=b"ok",
            headers=[
                ("connection", "X-Internal-Hop"),
                ("x-internal-hop", "must-not-escape"),
                ("set-cookie", "session=a; Path=/; HttpOnly"),
                ("set-cookie", "csrf=b; Path=/; Secure"),
            ],
        )

    gateway = GatewayRouter(
        default_filters=[], transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test", strip_prefix=True)
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.get(
                    "/api/item",
                    headers={
                        "Connection": "X-Remove-Me",
                        "X-Remove-Me": "must-not-forward",
                    },
                )
        finally:
            await gateway.aclose()

    with request_context("rid-gateway"):
        response = asyncio.run(scenario())
    assert response.status_code == 200
    assert captured["request_id"] == "rid-gateway"
    assert captured["removed_request_header"] is None
    assert "x-internal-hop" not in response.headers
    assert response.headers.get_list("set-cookie") == [
        "session=a; Path=/; HttpOnly", "csrf=b; Path=/; Secure",
    ]


def test_gateway_round_robin_is_deterministic_not_clock_based():
    instances = [
        {"ip": "10.0.0.1", "port": 80},
        {"ip": "10.0.0.2", "port": 80},
        {"ip": "10.0.0.3", "port": 80},
    ]
    LoadBalancerStrategy._round_robin_counters.clear()
    selected = [
        LoadBalancerStrategy.round_robin(instances)["ip"] for _ in range(4)
    ]
    assert selected == ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.1"]


def test_gateway_auth_exclusions_require_a_path_segment_boundary():
    auth = AuthenticationFilter(exclude_paths=["/login", "/health"])

    def context(path):
        return FilterContext(
            route=SimpleNamespace(id="auth"), request_path=path,
            request_headers={}, request_method="GET", request_query={},
        )

    assert auth.pre_filter(context("/login")) is True
    assert auth.pre_filter(context("/login/callback")) is True
    bypass = context("/login-evil")
    assert auth.pre_filter(bypass) is False
    assert bypass.response_status == 401
    assert auth.pre_filter(context("/healthcheck")) is False
    authenticate_every_path = AuthenticationFilter(exclude_paths=[])
    assert authenticate_every_path.pre_filter(context("/login")) is False


def test_gateway_applies_route_predicates_and_route_level_filters():
    observed = []

    class RouteFilter(GatewayFilter):
        def pre_filter(self, ctx):
            ctx.request_headers["X-Route-Filter"] = ctx.route.id
            return True

        def post_filter(self, ctx):
            observed.append((ctx.route.id, ctx.response_status))

    async def upstream(request: httpx.Request):
        return httpx.Response(
            200, json={"route": request.headers["X-Route-Filter"]})

    gateway = GatewayRouter(
        default_filters=[], transport=httpx.MockTransport(upstream))
    gateway.route(
        "/items/**", uri="https://upstream.test", route_id="post-only",
        filters=[RouteFilter()], methods=["POST"], headers={"X-Tenant": "a"},
    )
    gateway.route(
        "/items/**", uri="https://upstream.test", route_id="get-route",
        filters=[RouteFilter()], method="GET",
    )
    with pytest.raises(ValueError, match="Unsupported"):
        gateway.route(
            "/bad/**", uri="https://upstream.test", imaginary="ignored")
    with pytest.raises(TypeError, match="GatewayFilter"):
        gateway.route(
            "/bad/**", uri="https://upstream.test", filters=["auth"])

    app = FastAPI()
    app.add_api_route(
        "/items/{path:path}", gateway.handle_asgi, methods=["GET", "POST"])

    async def scenario():
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                get_response = await client.get("/items/1")
                wrong_tenant = await client.post(
                    "/items/1", headers={"X-Tenant": "b"})
                post_response = await client.post(
                    "/items/1", headers={"X-Tenant": "a"})
                return get_response, wrong_tenant, post_response
        finally:
            await gateway.aclose()

    get_response, wrong_tenant, post_response = asyncio.run(scenario())
    assert get_response.json() == {"route": "get-route"}
    assert wrong_tenant.status_code == 404
    assert post_response.json() == {"route": "post-only"}
    assert observed == [("get-route", 200), ("post-only", 200)]


def test_gateway_reports_final_502_to_post_filters_and_returns_request_id():
    statuses = []

    class Recorder(GatewayFilter):
        def post_filter(self, ctx):
            statuses.append(ctx.response_status)

    async def oversized(_request: httpx.Request):
        return httpx.Response(200, content=b"too-large")

    gateway = GatewayRouter(
        default_filters=[Recorder()], max_response_size=3,
        transport=httpx.MockTransport(oversized),
    )
    gateway.route("/files/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/files/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.get("/files/large")
        finally:
            await gateway.aclose()

    response = asyncio.run(scenario())
    assert response.status_code == 502
    assert statuses == [502]
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_gateway_filters_bad_discovery_records_off_the_event_loop():
    import threading

    caller_thread = threading.get_ident()
    discovery_threads = []

    class Discovery:
        def get_instances(self, _service_id):
            discovery_threads.append(threading.get_ident())
            return [
                "malformed",
                {"ip": "10.0.0.1", "port": 80, "healthy": False},
                {"ip": "10.0.0.2", "port": 80, "enabled": "false"},
                {"ip": "bad host", "port": "invalid"},
                {"ip": "upstream.test", "port": 443, "scheme": "https"},
            ]

    async def upstream(request: httpx.Request):
        assert request.url.host == "upstream.test"
        return httpx.Response(200, text="ok")

    gateway = GatewayRouter(
        discovery_client=Discovery(), default_filters=[],
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/svc/**", service_id="catalog")
    app = FastAPI()
    app.add_api_route("/svc/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.get("/svc/item")
        finally:
            await gateway.aclose()

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert discovery_threads and discovery_threads[0] != caller_thread


def test_gateway_weighted_load_balancer_tolerates_bad_weights():
    instances = [
        {"ip": "10.0.0.1", "weight": "invalid"},
        {"ip": "10.0.0.2", "weight": -1},
    ]
    LoadBalancerStrategy._round_robin_counters.clear()
    assert LoadBalancerStrategy.weighted(instances) == instances[0]
    assert LoadBalancerStrategy.weighted(instances) == instances[1]


def test_gateway_rate_limit_filter_completes_sentinel_entry(monkeypatch):
    class Entry:
        outcome = None

        def success(self):
            self.outcome = "success"

        def error(self):
            self.outcome = "error"

    entry = Entry()
    monkeypatch.setattr(
        "springbootai.cloud.sentinel.sentinel_engine.entry",
        lambda *args, **kwargs: entry,
    )
    rate_limit = RateLimitFilter(default_qps=10)
    ctx = FilterContext(
        route=SimpleNamespace(id="orders"), request_path="/orders",
        request_headers={}, request_method="GET", request_query={},
        response_status=503,
    )
    assert rate_limit.pre_filter(ctx) is True
    rate_limit.post_filter(ctx)
    assert entry.outcome == "error"


def test_text_reader_has_explicit_path_and_size_boundaries(tmp_path):
    path = tmp_path / "large.txt"
    path.write_bytes(b"12345")
    with pytest.raises(DocumentTooLargeError, match="max_bytes=4"):
        TextReader.from_file(path, max_bytes=4).read()
    with pytest.raises(FileNotFoundError):
        TextReader.from_file(tmp_path / "missing.txt").read()
    with pytest.raises(DocumentTooLargeError):
        TextReader(max_bytes=3).read_text("four")
    assert TextReader("inline", max_bytes=10).read()[0].content == "inline"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TokenTextSplitter(chunk_size=0),
        lambda: TokenTextSplitter(chunk_size=10, chunk_overlap=10),
        lambda: TokenTextSplitter(chunk_size=10, min_chunk_size=11),
        lambda: CharacterTextSplitter(chunk_size=0),
        lambda: CharacterTextSplitter(chunk_size=10, chunk_overlap=-1),
    ],
)
def test_text_splitters_reject_non_progressing_sizes(factory):
    with pytest.raises(ValueError):
        factory()


def test_scaffold_atomic_write_preserves_previous_file_on_replace_failure(
        tmp_path, monkeypatch):
    target = tmp_path / "settings.yml"
    scaffold._atomic_write_text(target, "old")
    assert target.read_text(encoding="utf-8") == "old"

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(scaffold.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        scaffold._atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".settings.yml.*.tmp")) == []


def test_banner_reads_the_runtime_package_version(monkeypatch):
    import springbootai
    from springbootai.utils.banner import _default_version

    monkeypatch.setattr(springbootai, "__version__", "9.9.9-test")
    assert _default_version() == "9.9.9-test"


def test_config_center_http_response_is_bounded_encoded_and_closed(monkeypatch):
    from springbootai.cloud.config_center import config_client

    class Response:
        status_code = 200
        closed = False

        payload = json.dumps({"propertySources": [
            {"source": {"priority": "high"}},
            {"source": {"priority": "low", "base": True}},
        ]}).encode()
        headers = {"Content-Length": str(len(payload))}
        content = payload

        def raise_for_status(self):
            return None

        def json(self):
            raise AssertionError("streaming response should be decoded from bounded bytes")

        def iter_content(self, chunk_size=64 * 1024):
            yield self.payload[:10]
            yield self.payload[10:]

        def close(self):
            self.closed = True

    response = Response()
    calls = []
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kwargs: calls.append((url, kwargs)) or response,
    )
    config_client.configure({"spring": {"cloud": {"config": {
        "enabled": True,
        "uri": "https://config.test",
        "name": "team/app",
        "profile": "prod east",
        "label": "main",
        "retry": {"max-attempts": 1},
    }}}})
    try:
        assert config_client.fetch() == {"priority": "high", "base": True}
        assert calls[0][0].endswith("/team%2Fapp/prod%20east/main")
        assert re.fullmatch(
            r"[0-9a-f]{32}", calls[0][1]["headers"]["X-Request-ID"])
        assert response.closed is True
    finally:
        config_client._configured = False


def test_admin_config_boolean_parser_does_not_enable_false_string():
    from springbootai.monitoring.admin_client import AdminClientProperties

    properties = AdminClientProperties.from_config({
        "spring": {"boot": {"admin": {"client": {"enabled": "false"}}}},
    })
    assert properties.enabled is False

    malformed = AdminClientProperties.from_config({
        "spring": {"boot": {"admin": {"client": {
            "enabled": "true", "timeout-seconds": "not-a-number",
            "max-retries": -100, "metadata": ["not", "a", "mapping"],
        }}}},
    })
    assert malformed.enabled is True
    assert malformed.timeout_seconds == 5.0
    assert malformed.max_retries == 0
    assert malformed.metadata == {}


def test_config_center_file_backend_blocks_traversal_and_large_files(tmp_path):
    from springbootai.cloud.config_center import config_client

    config_client.configure({"spring": {"cloud": {"config": {
        "enabled": True, "backend": "file", "name": "../secret",
        "file": {"path": str(tmp_path)},
    }}}})
    assert config_client.fetch() == {}

    (tmp_path / "application.yml").write_bytes(b"value: 12345")
    config_client.configure({"spring": {"cloud": {"config": {
        "enabled": True, "backend": "file", "name": "safe",
        "profile": "prod", "max-response-size": 4,
        "file": {"path": str(tmp_path)},
    }}}})
    try:
        assert config_client.fetch() == {}
    finally:
        config_client._configured = False


def test_config_center_file_profile_overrides_generic_and_fail_fast(tmp_path):
    from springbootai.cloud.config_center import ConfigCenterError, config_client

    (tmp_path / "application.yml").write_text(
        "value: application\napplication_only: true\n", encoding="utf-8")
    (tmp_path / "application-prod.yml").write_text(
        "value: application-prod\nprofile_only: true\n", encoding="utf-8")
    (tmp_path / "orders.yml").write_text(
        "value: orders\norders_only: true\n", encoding="utf-8")
    (tmp_path / "orders-prod.yml").write_text(
        "value: orders-prod\n", encoding="utf-8")
    config_client.configure({"spring": {"cloud": {"config": {
        "enabled": True, "backend": "file", "name": "orders",
        "profile": "prod", "file": {"path": str(tmp_path)},
    }}}})
    merged = config_client.fetch()
    assert merged == {
        "value": "orders-prod", "application_only": True,
        "profile_only": True, "orders_only": True,
    }

    (tmp_path / "orders-prod.yml").write_text("- invalid\n- root\n", encoding="utf-8")
    config_client.configure({"spring": {"cloud": {"config": {
        "enabled": True, "backend": "file", "name": "orders",
        "profile": "prod", "fail-fast": True,
        "file": {"path": str(tmp_path)},
    }}}})
    try:
        with pytest.raises(ConfigCenterError, match="orders-prod.yml"):
            config_client.fetch()
    finally:
        config_client._configured = False


def test_ai_json_fallback_streams_with_a_hard_response_limit(monkeypatch):
    from springbootai.ai.providers import (
        ProviderResponseTooLargeError, _http_post_json,
    )

    class Response:
        status_code = 200
        headers = {}
        closed = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=64 * 1024):
            yield b"123"
            yield b"45"

        def close(self):
            self.closed = True

    response = Response()
    calls = []
    monkeypatch.setattr(
        "requests.post",
        lambda *args, **kwargs: calls.append(kwargs) or response,
    )
    with pytest.raises(ProviderResponseTooLargeError, match="safety limit"):
        _http_post_json(
            "https://provider.test/v1/chat", json_body={}, timeout=1,
            max_retries=0, retry_delay_ms=0, circuit_breaker=None,
            provider="test", max_response_size=4,
        )
    assert response.closed is True
    assert re.fullmatch(
        r"[0-9a-f]{32}", calls[0]["headers"]["X-Request-ID"])
