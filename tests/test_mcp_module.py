"""Tests for the optional MCP client, server and Spring AI bridge."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time

import pytest

pytest.importorskip("mcp")

from springbootai.ai.core import ChatClient
from springbootai.ai.providers import FakeChatModel
from springbootai.ai.tools import CompositeToolRegistry, ToolExecutionPolicy, ToolRegistry
from springbootai.context.registry import BeanRegistry
from springbootai.mcp import (
    MCPCall,
    MCPClientConnection,
    MCPClientError,
    MCPClient,
    MCPClientProperties,
    MCPConfigurationError,
    MCPServerAdapter,
    MCPServerProperties,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
    bind_mcp_client,
    bind_mcp_config,
    build_client_manager,
    configure_mcp,
    build_mcp_server,
)


def _run(coroutine):
    return asyncio.run(coroutine)


def _local_registry() -> ToolRegistry:
    registry = ToolRegistry(policy=ToolExecutionPolicy(allowed_tools={"add", "erase"}))

    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    def erase(record_id: str) -> str:
        """Delete one record."""
        return record_id

    registry.register("add", add, description="Add two integers")
    registry.register("erase", erase, description="Delete one record", dangerous=True)
    return registry


def _server(registry=None, **overrides) -> MCPServerAdapter:
    values = {
        "enabled": True,
        "transport": "stdio",
        "allowed_tools": ("add",),
    }
    values.update(overrides)
    return MCPServerAdapter(MCPServerProperties(**values), registry or _local_registry())


def _client(server, **overrides):
    values = {
        "name": "local",
        "transport": "stdio",
        "command": "unused-for-in-process-test",
        "allowed_tools": ("add",),
        "tool_prefix": "remote_",
    }
    values.update(overrides)
    props = MCPClientProperties(**values).validate()
    return MCPClientConnection(props, server=server.native_server)


def test_timed_out_request_cancels_local_execution_task():
    connection = MCPClientConnection(MCPClientProperties(
        name="cancel", transport="stdio", command="unused",
        timeout_seconds=0.02,
    ))

    async def scenario():
        connection._requests = asyncio.Queue()
        cancelled = asyncio.Event()

        async def connected():
            return connection

        connection.connect = connected

        async def consume_request():
            request = await connection._requests.get()
            result_future = request[3]

            async def remote_operation():
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            task = asyncio.create_task(remote_operation())
            connection._active_tasks[result_future] = task
            try:
                result = await task
                if not result_future.done():
                    result_future.set_result(result)
            except BaseException as exc:
                if not result_future.done():
                    result_future.set_exception(exc)
            finally:
                connection._active_tasks.pop(result_future, None)

        consumer = asyncio.create_task(consume_request())
        started = time.perf_counter()
        with pytest.raises(MCPClientError, match="timed out"):
            await connection._request("call_tool")
        elapsed = time.perf_counter() - started
        await consumer
        return elapsed, cancelled.is_set()

    elapsed, cancelled = _run(scenario())
    assert elapsed < 0.2
    assert cancelled is True


def test_disabled_config_is_dependency_free_and_defaults_closed():
    props = bind_mcp_config({})
    assert props.enabled is False
    assert props.clients == ()
    assert props.server.enabled is False


def test_config_binding_client_and_server():
    props = bind_mcp_config({
        "enabled": True,
        "clients": {
            "orders": {
                "transport": "streamable-http",
                "url": "http://127.0.0.1:9000/mcp",
                "allowed-tools": ["get_order"],
                "dangerous-tools": ["cancel_order"],
            }
        },
        "server": {
            "enabled": True,
            "transport": "stdio",
            "allowed-tools": ["lookup"],
        },
    })
    assert props.clients[0].effective_prefix == "orders__"
    assert props.clients[0].is_tool_allowed("get_order")
    assert not props.clients[0].is_tool_allowed("cancel_order")
    assert props.server.is_tool_allowed("lookup")


def test_remote_plain_http_and_public_unauthenticated_server_are_rejected():
    with pytest.raises(MCPConfigurationError, match="requires HTTPS"):
        MCPClientProperties(
            name="remote",
            url="http://mcp.example.com/mcp",
            allowed_tools=("read",),
        ).validate()
    with pytest.raises(MCPConfigurationError, match="require auth"):
        MCPServerProperties(
            enabled=True,
            host="0.0.0.0",
            allowed_tools=("read",),
        ).validate()


def test_tool_registry_preserves_external_nested_json_schema():
    registry = ToolRegistry()
    schema = {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
            }
        },
        "required": ["filters"],
    }
    registry.register_schema("search", lambda **kwargs: kwargs, schema)
    assert registry.schemas()[0]["function"]["parameters"] == schema


def test_server_exports_only_allowlisted_non_dangerous_tools():
    server = _server(allowed_tools=("add", "erase"))
    names = {item.name for item in _run(server.native_server.list_tools())}
    assert names == {"add"}
    with pytest.raises(MCPConfigurationError, match="allowlisted"):
        _server(allowed_tools=("missing",))


def test_in_process_client_server_tool_resource_and_prompt():
    server = _server()

    @server.native_server.resource("greeting://{name}")
    def greeting(name: str) -> str:
        return f"Hello, {name}"

    @server.native_server.prompt(name="review")
    def review(code: str) -> str:
        return f"Review this code: {code}"

    async def scenario():
        connection = _client(server)
        await connection.connect()
        try:
            tools = await connection.list_tools()
            resources = await connection.list_resource_templates()
            prompts = await connection.list_prompts()
            result = await connection.call_tool("add", {"a": 2, "b": 5})
            resource = await connection.read_resource("greeting://Alice")
            prompt = await connection.get_prompt("review", {"code": "x = 1"})
            return tools, resources, prompts, result, resource, prompt
        finally:
            await connection.close()

    tools, resources, prompts, result, resource, prompt = _run(scenario())
    assert tools[0].input_schema["properties"]["a"]["type"] == "integer"
    assert resources[0].uri_template == "greeting://{name}"
    assert prompts[0].name == "review"
    assert result == 7
    assert "Hello, Alice" in str(resource)
    assert "Review this code" in str(prompt)


def test_remote_allowlist_is_enforced_before_network_call():
    connection = _client(_server(), allowed_tools=("other",))
    with pytest.raises(PermissionError, match="not allowed"):
        _run(connection.call_tool("add", {"a": 1, "b": 1}))


def test_direct_client_rejects_dangerous_and_oversized_calls_before_network():
    dangerous = _client(
        _server(),
        allowed_tools=("add",),
        dangerous_tools=("add",),
    )
    with pytest.raises(PermissionError, match="not allowed"):
        _run(dangerous.call_tool("add", {"a": 1, "b": 1}))

    limited = _client(_server(), max_argument_bytes=1024)
    with pytest.raises(ValueError, match="exceed"):
        _run(limited.call_tool("add", {"a": "x" * 1100, "b": 1}))


def test_client_manager_bridges_schema_and_sync_ai_execution():
    server = _server()
    props = _client(server).properties
    manager = build_client_manager([props], {"local": server.native_server})
    try:
        registry = manager.create_tool_registry_sync(
            ToolExecutionPolicy(allowed_tools={"remote_add"}, timeout_seconds=5)
        )
        schema = registry.schemas()[0]["function"]
        assert schema["name"] == "remote_add"
        assert schema["parameters"]["properties"]["a"]["type"] == "integer"
        assert registry.execute("remote_add", {"a": 10, "b": 4}) == 14
    finally:
        manager.close_sync()


def test_client_manager_exposes_spring_destroy_lifecycle_hook():
    server = _server()
    manager = build_client_manager(
        [_client(server).properties],
        {"local": server.native_server},
    )
    manager.connect_all_sync()
    assert manager.health()["local"] == "UP"
    manager.destroy()
    assert manager._thread is None
    assert manager._loop is None


def test_composite_registry_routes_without_bypassing_child_policy():
    local = ToolRegistry(policy=ToolExecutionPolicy(allowed_tools={"local"}))
    local.register("local", lambda: "local")
    remote = ToolRegistry(policy=ToolExecutionPolicy(allowed_tools=set()))
    remote.register("remote", lambda: "remote")
    composite = CompositeToolRegistry(local, remote)
    assert composite.execute("local", {}) == "local"
    with pytest.raises(PermissionError, match="not allowed"):
        composite.execute("remote", {})
    with pytest.raises(ValueError, match="duplicate"):
        CompositeToolRegistry(local, local)


def test_autoconfig_builds_both_sides_and_attaches_tools_to_ai_client():
    bean_registry = BeanRegistry()
    bean_registry.clear()
    local = _local_registry()
    chat_client = ChatClient(FakeChatModel())
    bean_registry.register("aiToolRegistry", local)
    bean_registry.register("aiChatClient", chat_client)
    native = _server(local).native_server
    config = {
        "spring": {
            "mcp": {
                "enabled": True,
                "clients": {
                    "local": {
                        "transport": "stdio",
                        "command": "unused",
                        "allowed-tools": ["add"],
                        "tool-prefix": "remote_",
                    }
                },
                "server": {
                    "enabled": True,
                    "transport": "stdio",
                    "allowed-tools": ["add"],
                },
            }
        }
    }
    beans = configure_mcp(
        bean_registry,
        config,
        ai_tool_registry=local,
        remote_tool_policy=ToolExecutionPolicy(allowed_tools={"remote_add"}),
        in_process_servers={"local": native},
    )
    try:
        assert "mcpClientManager" in beans
        assert "mcpServer" in beans
        assert set(beans["aiEffectiveToolRegistry"].names()) == {"add", "erase", "remote_add"}
        assert chat_client.default_tool_registry is beans["aiEffectiveToolRegistry"]
    finally:
        beans["mcpClientManager"].close_sync()
        bean_registry.clear()


def test_real_streamable_http_transport():
    uvicorn = pytest.importorskip("uvicorn")
    registry = _local_registry()
    adapter = MCPServerAdapter(
        MCPServerProperties(
            enabled=True,
            transport="streamable-http",
            allowed_tools=("add",),
        ),
        registry,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(
        adapter.streamable_http_app(),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started

    async def scenario():
        connection = MCPClientConnection(MCPClientProperties(
            name="http",
            transport="streamable-http",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"X-MCP-Test": "springbootai"},
            allowed_tools=("add",),
        ))
        try:
            return await connection.call_tool("add", {"a": 20, "b": 22})
        finally:
            await connection.close()

    try:
        assert _run(scenario()) == 42
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert not thread.is_alive()


def test_streamable_http_custom_headers_use_declared_httpx_dependency():
    connection = MCPClientConnection(
        MCPClientProperties(
            name="headers",
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer test-token"},
            allowed_tools=("read",),
        )
    )
    transport = connection._transport()
    try:
        assert connection._http_client.headers["Authorization"] == "Bearer test-token"
        assert hasattr(transport, "__aenter__")
    finally:
        _run(connection._http_client.aclose())


def test_annotation_client_executes_sync_and_async_protocol_calls():
    class RecordingManager:
        def __init__(self):
            self.calls = []

        def call_tool_sync(self, client, tool, arguments):
            self.calls.append(("sync", client, tool, arguments))
            return arguments["a"] + arguments["b"]

        async def acall_tool(self, client, tool, arguments):
            self.calls.append(("async", client, tool, arguments))
            return arguments["value"] * 2

    @MCPClient("orders")
    class OrderMCPClient:
        @MCPCall("add")
        def add(self, a: int, b: int = 1) -> int:
            raise AssertionError("declarative method body must not execute")

        @MCPCall("double")
        async def double(self, value: int) -> int:
            raise AssertionError("declarative method body must not execute")

    manager = RecordingManager()
    client = bind_mcp_client(OrderMCPClient(), manager)
    assert client.add(4) == 5
    assert _run(client.double(6)) == 12
    assert manager.calls == [
        ("sync", "orders", "add", {"a": 4, "b": 1}),
        ("async", "orders", "double", {"value": 6}),
    ]


def test_annotation_server_builds_allowlisted_tool_resource_and_prompt():
    @MCPServer(
        name="catalog",
        transport="stdio",
        allowed_tools=["lookup"],
    )
    class CatalogMCPServer:
        @MCPTool(description="Look up one product")
        def lookup(self, product_id: int) -> dict:
            return {"id": product_id, "available": True}

        @MCPTool(dangerous=True)
        def erase(self, product_id: int) -> bool:
            return True

        @MCPResource("catalog://help")
        def help(self) -> str:
            return "Use lookup with a numeric product_id"

        @MCPPrompt(description="Build a product review prompt")
        def review(self, product: str) -> str:
            return f"Review {product}"

    adapter = build_mcp_server(CatalogMCPServer())

    async def scenario():
        connection = MCPClientConnection(
            MCPClientProperties(
                name="catalog",
                transport="stdio",
                command="unused",
                allowed_tools=("lookup",),
            ),
            server=adapter.native_server,
        )
        try:
            tools = await connection.list_tools()
            result = await connection.call_tool("lookup", {"product_id": 7})
            resources = await connection.list_resources()
            prompts = await connection.list_prompts()
            return tools, result, resources, prompts
        finally:
            await connection.close()

    tools, result, resources, prompts = _run(scenario())
    assert [tool.name for tool in tools] == ["lookup"]
    assert tools[0].input_schema["properties"]["product_id"]["type"] == "integer"
    assert result == {"id": 7, "available": True}
    assert str(resources[0].uri) == "catalog://help"
    assert prompts[0].name == "review"


def test_annotation_server_requires_an_explicit_export_allowlist():
    @MCPServer(transport="stdio")
    class UnsafeDefaultServer:
        @MCPTool
        def read(self) -> str:
            return "data"

    with pytest.raises(MCPConfigurationError, match="explicitly list"):
        build_mcp_server(UnsafeDefaultServer())


def test_real_stdio_subprocess_transport():
    async def scenario():
        connection = MCPClientConnection(
            MCPClientProperties(
                name="stdio",
                transport="stdio",
                command=sys.executable,
                args=("-m", "example_mcp.stdio_server"),
                allowed_tools=("multiply",),
                timeout_seconds=10,
            )
        )
        try:
            return await connection.call_tool("multiply", {"a": 6, "b": 7})
        finally:
            await connection.close()

    assert _run(scenario()) == 42
