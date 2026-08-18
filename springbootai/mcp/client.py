"""MCP client runtime and safe bridge to ``springbootai.ai.ToolRegistry``."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future
from contextlib import suppress
from typing import Any, Dict, Iterable, Optional

from springbootai.ai.tools import ToolExecutionPolicy, ToolRegistry
from springbootai.mcp.config import MCPClientProperties, MCPConfigurationError

logger = logging.getLogger("Spring.MCP.Client")


class MCPDependencyError(ImportError):
    """Raised when MCP is enabled without the optional official SDK."""


class MCPClientError(RuntimeError):
    """Raised for MCP connection, discovery or remote execution failures."""


def require_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401
        from mcp.client import Client  # noqa: F401
    except ImportError as exc:
        raise MCPDependencyError(
            "MCP support requires the optional dependency: "
            "pip install 'springbootAI[mcp]'"
        ) from exc


def _content_to_value(result: Any) -> Any:
    """Convert an SDK CallToolResult into an AI-safe Python value."""
    if getattr(result, "is_error", False):
        details = " ".join(
            str(getattr(item, "text", "")) for item in getattr(result, "content", [])
            if getattr(item, "text", "")
        ).strip()
        raise MCPClientError(details[:500] or "remote MCP tool returned an error")

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured

    rendered: list[Any] = []
    for item in getattr(result, "content", []):
        item_type = getattr(item, "type", "")
        if item_type == "text":
            rendered.append(getattr(item, "text", ""))
        elif hasattr(item, "model_dump"):
            rendered.append(item.model_dump(by_alias=True, mode="json"))
        else:
            rendered.append(str(item))
    if len(rendered) == 1:
        return rendered[0]
    return rendered


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise TypeError("MCP tool arguments must be JSON serializable") from exc


class MCPClientConnection:
    """One persistent MCP connection owned by an asyncio event loop."""

    def __init__(self, properties: MCPClientProperties, server: Any = None):
        self.properties = properties.validate()
        self._in_process_server = server
        self._client: Any = None
        self._http_client: Any = None
        self._connect_lock: Optional[asyncio.Lock] = None
        self._requests: Optional[asyncio.Queue] = None
        self._runner_task: Optional[asyncio.Task] = None
        self._ready: Optional[asyncio.Future] = None

    def _transport(self) -> Any:
        require_mcp_sdk()
        if self._in_process_server is not None:
            return self._in_process_server
        if self.properties.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            parameters = StdioServerParameters(
                command=self.properties.command,
                args=list(self.properties.args),
                env=dict(self.properties.env) or None,
                cwd=self.properties.cwd or None,
            )
            return stdio_client(parameters)
        if self.properties.headers:
            import httpx
            from mcp.client.streamable_http import streamable_http_client

            self._http_client = httpx.AsyncClient(
                headers=dict(self.properties.headers),
                timeout=self.properties.timeout_seconds,
            )
            return streamable_http_client(
                self.properties.url, http_client=self._http_client
            )
        return self.properties.url

    async def connect(self) -> "MCPClientConnection":
        require_mcp_sdk()
        if self._client is not None and self._runner_task is not None:
            return self
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
            if self._client is not None and self._runner_task is not None:
                return self
            loop = asyncio.get_running_loop()
            self._requests = asyncio.Queue()
            self._ready = loop.create_future()
            self._runner_task = loop.create_task(
                self._run_client(), name=f"spring-mcp-{self.properties.name}"
            )
            await asyncio.wait_for(
                asyncio.shield(self._ready), timeout=self.properties.timeout_seconds
            )
        return self

    async def _run_client(self) -> None:
        from mcp.client import Client

        candidate = Client(
            self._transport(),
            raise_exceptions=True,
            read_timeout_seconds=self.properties.timeout_seconds,
        )
        failure: Optional[BaseException] = None
        try:
            async with candidate as client:
                self._client = client
                if self._ready is not None and not self._ready.done():
                    self._ready.set_result(True)
                active: set[asyncio.Task] = set()

                async def execute(request: Any) -> None:
                    operation, args, kwargs, result_future = request
                    try:
                        result = await getattr(client, operation)(*args, **kwargs)
                    except BaseException as exc:
                        if not result_future.done():
                            result_future.set_exception(exc)
                    else:
                        if not result_future.done():
                            result_future.set_result(result)

                while True:
                    request = await self._requests.get()
                    if request is None:
                        break
                    task = asyncio.create_task(execute(request))
                    active.add(task)
                    task.add_done_callback(active.discard)
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
        except BaseException as exc:
            failure = exc
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            self._client = None
            http_client, self._http_client = self._http_client, None
            if http_client is not None:
                with suppress(BaseException):
                    await http_client.aclose()
            if failure is not None and self._requests is not None:
                while not self._requests.empty():
                    pending = self._requests.get_nowait()
                    if pending is not None:
                        future = pending[3]
                        if not future.done():
                            future.set_exception(failure)

    async def _request(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        await self.connect()
        future = asyncio.get_running_loop().create_future()
        await self._requests.put((operation, args, kwargs, future))
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.properties.timeout_seconds + 1
            )
        except asyncio.TimeoutError as exc:
            future.cancel()
            raise MCPClientError(f"MCP operation timed out: {operation}") from exc

    async def close(self) -> None:
        runner, self._runner_task = self._runner_task, None
        if runner is not None and not runner.done():
            await self._requests.put(None)
            await runner
        self._requests = None
        self._ready = None
        self._connect_lock = None

    async def list_tools(self) -> list[Any]:
        try:
            result = await self._request("list_tools", cache_mode="bypass")
            return list(result.tools)
        except Exception as exc:
            raise MCPClientError(
                f"failed to discover tools from MCP server {self.properties.name!r}"
            ) from exc

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self.properties.is_tool_allowed(name):
            raise PermissionError(
                f"MCP tool {name!r} is not allowed for client {self.properties.name!r}"
            )
        if _json_size(arguments) > self.properties.max_argument_bytes:
            raise ValueError(
                f"MCP tool arguments exceed {self.properties.max_argument_bytes} bytes"
            )
        try:
            result = await self._request(
                "call_tool",
                name,
                arguments,
                read_timeout_seconds=self.properties.timeout_seconds,
            )
            value = _content_to_value(result)
            if len(str(value)) > self.properties.max_result_chars:
                raise MCPClientError(
                    f"MCP tool result exceeds {self.properties.max_result_chars} characters"
                )
            return value
        except asyncio.TimeoutError as exc:
            raise MCPClientError(f"MCP tool timed out: {name}") from exc
        except MCPClientError:
            raise
        except Exception as exc:
            raise MCPClientError(f"MCP tool failed: {name}") from exc

    async def list_resources(self) -> list[Any]:
        result = await self._request("list_resources", cache_mode="bypass")
        return list(result.resources)

    async def list_resource_templates(self) -> list[Any]:
        result = await self._request("list_resource_templates", cache_mode="bypass")
        return list(result.resource_templates)

    async def read_resource(self, uri: str) -> Any:
        return await self._request("read_resource", uri, cache_mode="bypass")

    async def list_prompts(self) -> list[Any]:
        result = await self._request("list_prompts", cache_mode="bypass")
        return list(result.prompts)

    async def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> Any:
        return await self._request("get_prompt", name, arguments)


class MCPClientManager:
    """Manage multiple MCP servers and expose their tools to Spring AI.

    A dedicated background loop owns all SDK clients.  This matters for stdio
    subprocesses and stateful transports: recreating an event loop for every
    synchronous AI tool call would leak sessions and break shutdown ordering.
    """

    def __init__(self, connections: Iterable[MCPClientConnection]):
        self.connections = {item.properties.name: item for item in connections}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None and self._loop.is_running():
            return self._loop
        with self._start_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            ready = threading.Event()

            def run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                loop.run_forever()
                loop.close()

            self._thread = threading.Thread(
                target=run, name="spring-mcp-client-loop", daemon=True
            )
            self._thread.start()
            if not ready.wait(5):
                raise MCPClientError("MCP client event loop failed to start")
        return self._loop

    def submit(self, coroutine: Any, timeout: Optional[float] = None) -> Any:
        loop = self._ensure_loop()
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=timeout)

    async def connect_all(self) -> None:
        results = await asyncio.gather(
            *(connection.connect() for connection in self.connections.values()),
            return_exceptions=True,
        )
        for connection, result in zip(self.connections.values(), results):
            if isinstance(result, BaseException):
                if connection.properties.fail_fast:
                    raise MCPClientError(
                        f"MCP client {connection.properties.name!r} failed to connect"
                    ) from result
                logger.warning(
                    "MCP client %s is unavailable: %s",
                    connection.properties.name,
                    type(result).__name__,
                )

    def connect_all_sync(self) -> None:
        timeout = max(
            (item.properties.timeout_seconds for item in self.connections.values()),
            default=30.0,
        )
        self.submit(self.connect_all(), timeout=timeout + 5)

    async def close(self) -> None:
        await asyncio.gather(
            *(connection.close() for connection in self.connections.values()),
            return_exceptions=True,
        )

    def close_sync(self) -> None:
        if self._loop is None:
            return
        with suppress(Exception):
            self.submit(self.close(), timeout=10)
        loop, thread = self._loop, self._thread
        self._loop = None
        self._thread = None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def destroy(self) -> None:
        """Spring BeanFactory lifecycle hook."""
        self.close_sync()

    async def create_tool_registry(
        self, policy: Optional[ToolExecutionPolicy] = None
    ) -> ToolRegistry:
        """Discover allowlisted remote tools and preserve their MCP schemas."""
        registry = ToolRegistry(policy=policy)
        public_names: set[str] = set()
        for connection in self.connections.values():
            try:
                tools = await connection.list_tools()
            except Exception:
                if connection.properties.fail_fast:
                    raise
                logger.warning(
                    "Skipping tools from unavailable MCP client %s",
                    connection.properties.name,
                )
                continue
            for tool in tools:
                if not connection.properties.is_tool_allowed(tool.name):
                    continue
                public_name = f"{connection.properties.effective_prefix}{tool.name}"
                if public_name in public_names:
                    raise MCPConfigurationError(f"duplicate bridged MCP tool: {public_name}")
                public_names.add(public_name)

                def invoke_remote(_connection=connection, _tool_name=tool.name, **arguments: Any) -> Any:
                    timeout = _connection.properties.timeout_seconds + 2
                    return self.submit(
                        _connection.call_tool(_tool_name, arguments), timeout=timeout
                    )

                invoke_remote.__name__ = public_name
                invoke_remote.__doc__ = tool.description or f"Remote MCP tool {tool.name}"
                registry.register_schema(
                    public_name,
                    invoke_remote,
                    input_schema=dict(tool.input_schema),
                    description=tool.description or "",
                    dangerous=tool.name in connection.properties.dangerous_tools,
                )
        return registry

    def create_tool_registry_sync(
        self, policy: Optional[ToolExecutionPolicy] = None
    ) -> ToolRegistry:
        timeout = sum(
            item.properties.timeout_seconds for item in self.connections.values()
        ) + 5
        return self.submit(self.create_tool_registry(policy), timeout=timeout)

    async def call_tool(self, client_name: str, tool_name: str,
                        arguments: Dict[str, Any]) -> Any:
        connection = self.connections.get(client_name)
        if connection is None:
            raise KeyError(f"unknown MCP client: {client_name}")
        return await connection.call_tool(tool_name, arguments)

    def call_tool_sync(self, client_name: str, tool_name: str,
                       arguments: Dict[str, Any]) -> Any:
        connection = self.connections.get(client_name)
        if connection is None:
            raise KeyError(f"unknown MCP client: {client_name}")
        return self.submit(
            connection.call_tool(tool_name, arguments),
            timeout=connection.properties.timeout_seconds + 2,
        )

    async def acall_tool(self, client_name: str, tool_name: str,
                         arguments: Dict[str, Any]) -> Any:
        loop = self._ensure_loop()
        if loop is asyncio.get_running_loop():
            return await self.call_tool(client_name, tool_name, arguments)
        future = asyncio.run_coroutine_threadsafe(
            self.call_tool(client_name, tool_name, arguments), loop
        )
        return await asyncio.wrap_future(future)

    def health(self) -> Dict[str, str]:
        return {
            name: "UP" if connection._client is not None else "DOWN"
            for name, connection in self.connections.items()
        }


def build_client_manager(
    clients: Iterable[MCPClientProperties],
    in_process_servers: Optional[Dict[str, Any]] = None,
) -> MCPClientManager:
    servers = in_process_servers or {}
    return MCPClientManager(
        MCPClientConnection(properties, server=servers.get(properties.name))
        for properties in clients
    )


__all__ = [
    "MCPClientConnection",
    "MCPClientError",
    "MCPClientManager",
    "MCPDependencyError",
    "build_client_manager",
    "require_mcp_sdk",
]
