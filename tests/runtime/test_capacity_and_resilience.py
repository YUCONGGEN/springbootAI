import asyncio
import inspect
import json
import threading
import time

import httpx
from fastapi import FastAPI

from springbootai.annotations.cloud import FeignClient
from springbootai.annotations.core import GetMapping
from springbootai.cloud.feign import FeignClientProxy, create_declared_feign_client
from springbootai.cloud.gateway import GatewayRouter
from springbootai.web.web_context import WebApplicationContext


def _request(path: str = "/"):
    from starlette.requests import Request

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


def test_sync_handler_capacity_rejects_excess_work_quickly():
    class Context:
        def get_config(self):
            return {
                "server": {
                    "thread_pool": {
                        "max_workers": 1,
                        "max_queue": 0,
                        "queue_timeout": 0.02,
                    }
                }
            }

    entered = threading.Event()

    class Controller:
        def blocking(self):
            entered.set()
            time.sleep(0.12)
            return {"ok": True}

    web = WebApplicationContext(Context())
    endpoint = web._create_endpoint(Controller(), Controller.blocking, "/blocking")

    async def scenario():
        first = asyncio.create_task(endpoint(_request("/blocking")))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        started = time.monotonic()
        rejected = await endpoint(_request("/blocking"))
        rejected_after = time.monotonic() - started
        accepted = await first
        return accepted, rejected, rejected_after

    accepted, rejected, rejected_after = asyncio.run(scenario())
    assert accepted.status_code == 200
    assert rejected.status_code == 503
    assert rejected.headers["retry-after"] == "1"
    assert rejected_after < 0.08
    assert json.loads(rejected.body)["message"] == "Synchronous request capacity exhausted"


def test_gateway_reuses_client_pool_and_closes_on_shutdown():
    calls = []

    async def upstream(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    gateway = GatewayRouter(
        default_filters=[], transport=httpx.MockTransport(upstream)
    )
    gateway.route("/api/**", uri="https://upstream.test", strip_prefix=True)
    app = FastAPI()
    gateway.install(app, "/api/{path:path}", methods=["GET"])

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            first = await client.get("/api/one")
            pooled_client = gateway._client
            second = await client.get("/api/two")
            assert gateway._client is pooled_client
        await gateway.aclose()
        return first, second

    first, second = asyncio.run(scenario())
    assert first.status_code == second.status_code == 200
    assert calls == ["/one", "/two"]
    assert gateway._client is None


def test_gateway_maps_upstream_timeout_and_connection_failure():
    async def timeout(request: httpx.Request):
        raise httpx.ReadTimeout("slow", request=request)

    async def unavailable(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    async def request_with(transport):
        gateway = GatewayRouter(default_filters=[], transport=transport)
        gateway.route("/api/**", uri="https://upstream.test")
        app = FastAPI()
        gateway.install(app, "/api/{path:path}", methods=["GET"])
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                return await client.get("/api/data")
        finally:
            await gateway.aclose()

    timeout_response = asyncio.run(request_with(httpx.MockTransport(timeout)))
    failure_response = asyncio.run(request_with(httpx.MockTransport(unavailable)))
    assert timeout_response.status_code == 504
    assert failure_response.status_code == 502


def test_feign_reuses_session_timeout_and_async_request_does_not_block(monkeypatch):
    proxy = FeignClientProxy("inventory", url="https://inventory.test", timeout=0.25)
    calls = []

    class Response:
        content = b'{"ok": true}'
        text = '{"ok": true}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs["timeout"], threading.get_ident()))
        time.sleep(0.08)
        return Response()

    monkeypatch.setattr(proxy._session, "request", request)

    async def scenario():
        loop_thread = threading.get_ident()
        ticked = False

        async def ticker():
            nonlocal ticked
            await asyncio.sleep(0.01)
            ticked = True

        result, _ = await asyncio.gather(proxy.arequest("GET", "/items"), ticker())
        return result, ticked, loop_thread

    try:
        result, ticked, loop_thread = asyncio.run(scenario())
    finally:
        proxy.close()

    assert result == {"ok": True}
    assert ticked is True
    assert calls[0][:3] == ("GET", "https://inventory.test/items", 0.25)
    assert calls[0][3] != loop_thread


def test_async_declared_feign_method_stays_async(monkeypatch):
    @FeignClient("inventory", url="https://inventory.test")
    class InventoryClient:
        @GetMapping("/items")
        async def items(self):
            raise NotImplementedError

    annotation = InventoryClient.__spring_annotations__[0]
    client = create_declared_feign_client(InventoryClient, annotation)

    class Response:
        content = b'{"items": []}'
        text = '{"items": []}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"items": []}

    monkeypatch.setattr(
        client.__feign_proxy__._session,
        "request",
        lambda *args, **kwargs: Response(),
    )
    try:
        assert inspect.iscoroutinefunction(client.items)
        assert asyncio.run(client.items()) == {"items": []}
    finally:
        client.destroy()
