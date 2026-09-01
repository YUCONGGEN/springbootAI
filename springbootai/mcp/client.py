"""MCP client runtime and safe bridge to ``springbootai.ai.ToolRegistry``."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from concurrent.futures import Future
from contextlib import suppress
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from springbootai.ai.tools import ToolExecutionPolicy, ToolRegistry
from springbootai.mcp.config import MCPClientProperties, MCPConfigurationError

logger = logging.getLogger("Spring.MCP.Client")


_STDIO_SAFE_ENVIRONMENT_KEYS = (
    # Process creation and basic platform runtime.
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    # Locale and deterministic Python stdio behavior.
    "LANG", "LC_ALL", "LC_CTYPE", "PYTHONIOENCODING", "PYTHONUTF8",
    "PYTHONUNBUFFERED",
)


def _stdio_child_environment(properties: MCPClientProperties) -> Dict[str, str]:
    """Build a least-privilege environment for a local MCP subprocess."""
    if properties.inherit_environment:
        child_env = os.environ.copy()
    else:
        child_env = {
            key: os.environ[key]
            for key in _STDIO_SAFE_ENVIRONMENT_KEYS
            if key in os.environ
        }
    child_env.update(dict(properties.env))
    return child_env


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


def _content_to_value(
    result: Any,
    *,
    max_items: int,
    max_chars: int,
) -> Any:
    """Convert an SDK CallToolResult into an AI-safe Python value."""
    content = getattr(result, "content", [])
    if getattr(result, "is_error", False):
        details: list[str] = []
        remaining = 500
        for index, item in enumerate(content):
            if index >= max_items or remaining <= 0:
                break
            text = str(getattr(item, "text", "")).strip()
            if not text:
                continue
            fragment = text[:remaining]
            details.append(fragment)
            remaining -= len(fragment) + 1
        raise MCPClientError(
            " ".join(details).strip() or "remote MCP tool returned an error"
        )

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured

    rendered: list[Any] = []
    rendered_chars = 0
    for index, item in enumerate(content):
        if index >= max_items:
            raise MCPClientError("MCP tool result contains too many content items")
        item_type = getattr(item, "type", "")
        if item_type == "text":
            value = getattr(item, "text", "")
        elif hasattr(item, "model_dump"):
            value = item.model_dump(by_alias=True, mode="json")
        else:
            value = str(item)
        rendered_chars += len(str(value))
        if rendered_chars > max_chars:
            raise MCPClientError(
                f"MCP tool result exceeds {max_chars} characters"
            )
        rendered.append(value)
    if len(rendered) == 1:
        return rendered[0]
    return rendered


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise TypeError("MCP tool arguments must be JSON serializable") from exc


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _schema_depth(value: Any, current: int = 0) -> int:
    # Configuration caps the accepted depth at 64. Stop descending past that
    # boundary so maliciously deep stdio/in-process payloads cannot exhaust the
    # Python call stack before the normal validation rejects them.
    if current > 64:
        return current
    if isinstance(value, dict):
        if not value:
            return current + 1
        return max(_schema_depth(item, current + 1) for item in value.values())
    if isinstance(value, (list, tuple)):
        if not value:
            return current + 1
        return max(_schema_depth(item, current + 1) for item in value)
    return current


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize timeout wrappers used by asyncio, HTTPX and the MCP SDK."""
    seen: set[int] = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (asyncio.TimeoutError, TimeoutError)):
            return True
        name = type(current).__name__.lower()
        message = str(current).lower()
        if "timeout" in name or "timed out" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


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
        self._active_tasks: Dict[asyncio.Future, asyncio.Task] = {}

    def _transport(self) -> Any:
        require_mcp_sdk()
        if self._in_process_server is not None:
            return self._in_process_server
        if self.properties.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            # The documented ``python -m example_mcp.*`` example runs in a
            # child process, which does not inherit the source checkout path
            # when the library is installed. Add only those import paths; the
            # rest of the parent environment is isolated by default.
            child_env = _stdio_child_environment(self.properties)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))
            examples_dir = os.path.join(project_root, "examples")
            python_path = child_env.get("PYTHONPATH", "")
            paths = [item for item in python_path.split(os.pathsep) if item]
            for candidate in (project_root, examples_dir):
                if os.path.isdir(candidate) and candidate not in paths:
                    paths.append(candidate)
            if paths:
                child_env["PYTHONPATH"] = os.pathsep.join(paths)
            parameters = StdioServerParameters(
                command=self.properties.command,
                args=list(self.properties.args),
                env=child_env,
                cwd=self.properties.cwd or None,
            )
            return stdio_client(parameters)
        # Always own the HTTP client so local MCP endpoints cannot be sent to a
        # machine-wide proxy (a common Windows/Docker setup).  For non-loopback
        # URLs, retain normal ``HTTP_PROXY``/``NO_PROXY`` behavior so enterprise
        # deployments can still use their outbound proxy.  The SDK's implicit
        # client otherwise ignores the caller's intent and may turn a localhost
        # request into an opaque 502 from the proxy.
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        parsed = urlparse(self.properties.url)
        loopback = (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        response_limit = self.properties.max_response_bytes

        class BoundedResponseStream(httpx.AsyncByteStream):
            def __init__(self, stream: Any):
                self.stream = stream
                self.total = 0

            async def __aiter__(self):
                async for chunk in self.stream:
                    self.total += len(chunk)
                    if self.total > response_limit:
                        raise MCPClientError(
                            "MCP HTTP response exceeds max_response_bytes")
                    yield chunk

            async def aclose(self) -> None:
                await self.stream.aclose()

        async def enforce_response_limit(response: Any) -> None:
            content_encoding = response.headers.get(
                "content-encoding", "identity").strip().lower()
            if content_encoding not in {"", "identity"}:
                await response.aclose()
                raise MCPClientError(
                    "compressed MCP responses are disabled to prevent decompression bombs")
            raw_length = response.headers.get("content-length")
            if raw_length:
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    await response.aclose()
                    raise MCPClientError(
                        "MCP HTTP response has an invalid Content-Length") from exc
                if length < 0 or length > response_limit:
                    await response.aclose()
                    raise MCPClientError(
                        "MCP HTTP response exceeds max_response_bytes")
            response.stream = BoundedResponseStream(response.stream)

        headers = dict(self.properties.headers)
        headers.setdefault("Accept-Encoding", "identity")
        self._http_client = httpx.AsyncClient(
            headers=headers,
            timeout=self.properties.timeout_seconds,
            trust_env=not loopback,
            event_hooks={"response": [enforce_response_limit]},
        )
        return streamable_http_client(
            self.properties.url, http_client=self._http_client
        )

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
            self._requests = asyncio.Queue(
                maxsize=self.properties.max_pending_requests)
            self._ready = loop.create_future()
            runner = loop.create_task(
                self._run_client(), name=f"spring-mcp-{self.properties.name}"
            )
            self._runner_task = runner
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._ready),
                    timeout=self.properties.timeout_seconds,
                )
            except BaseException:
                if self._runner_task is runner:
                    self._runner_task = None
                if not runner.done():
                    runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
                self._requests = None
                self._ready = None
                raise
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

                requests = self._requests
                if requests is None:
                    raise MCPClientError("MCP request queue is unavailable")
                while True:
                    request = await requests.get()  # nosec B113 - asyncio.Queue, not HTTP
                    if request is None:
                        break
                    result_future = request[3]
                    # 调用在队列中等待期间已超时/取消，不再把副作用发送给远端。
                    if result_future.done():
                        continue
                    task = asyncio.create_task(execute(request))
                    active.add(task)
                    self._active_tasks[result_future] = task

                    def discard(done_task, future=result_future):
                        active.discard(done_task)
                        self._active_tasks.pop(future, None)

                    task.add_done_callback(discard)
                if active:
                    await asyncio.gather(*active, return_exceptions=True)
        except BaseException as exc:
            failure = exc
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(exc)
        finally:
            active_tasks = list(self._active_tasks.values())
            for task in active_tasks:
                if not task.done():
                    task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            self._active_tasks.clear()
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
        requests = self._requests
        if requests is None:
            raise MCPClientError("MCP request queue is unavailable")
        future = asyncio.get_running_loop().create_future()
        try:
            await asyncio.wait_for(
                requests.put((operation, args, kwargs, future)),  # nosec B113 - asyncio.Queue, not HTTP
                timeout=self.properties.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            future.cancel()
            raise MCPClientError("MCP request queue is full") from exc
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.properties.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            await self._cancel_request(future)
            raise MCPClientError(f"MCP operation timed out: {operation}") from exc
        except asyncio.CancelledError:
            await self._cancel_request(future)
            raise

    async def _cancel_request(self, future: asyncio.Future) -> None:
        """Cancel queued/running work and wait for local transport cancellation."""
        future.cancel()
        task = self._active_tasks.get(future)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        runner, self._runner_task = self._runner_task, None
        active_tasks = list(self._active_tasks.values())
        for future, task in list(self._active_tasks.items()):
            future.cancel()
            if not task.done():
                task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        if runner is not None and not runner.done():
            if self._requests is not None:
                await self._requests.put(None)
            try:
                await asyncio.wait_for(
                    asyncio.shield(runner),
                    timeout=self.properties.timeout_seconds + 1,
                )
            except asyncio.TimeoutError:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
        self._active_tasks.clear()
        self._requests = None
        self._ready = None
        self._connect_lock = None

    async def list_tools(self) -> list[Any]:
        try:
            result = await self._request("list_tools", cache_mode="bypass")
            tools = list(result.tools)
            self._validate_collection(tools, "tools", validate_schemas=True)
            return tools
        except MCPClientError:
            raise
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
            value = _content_to_value(
                result,
                max_items=self.properties.max_collection_items,
                max_chars=self.properties.max_result_chars,
            )
            if _json_size(_json_value(value)) > self.properties.max_response_bytes:
                raise MCPClientError(
                    "MCP tool result exceeds max_response_bytes")
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
            if _is_timeout_error(exc):
                raise MCPClientError(f"MCP tool timed out: {name}") from exc
            raise MCPClientError(f"MCP tool failed: {name}") from exc

    async def list_resources(self) -> list[Any]:
        result = await self._request("list_resources", cache_mode="bypass")
        resources = list(result.resources)
        self._validate_collection(resources, "resources")
        return resources

    async def list_resource_templates(self) -> list[Any]:
        result = await self._request("list_resource_templates", cache_mode="bypass")
        templates = list(result.resource_templates)
        self._validate_collection(templates, "resource templates")
        return templates

    async def read_resource(self, uri: str) -> Any:
        result = await self._request("read_resource", uri, cache_mode="bypass")
        self._validate_payload(result, "resource")
        return result

    async def list_prompts(self) -> list[Any]:
        result = await self._request("list_prompts", cache_mode="bypass")
        prompts = list(result.prompts)
        self._validate_collection(prompts, "prompts")
        return prompts

    async def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None) -> Any:
        result = await self._request("get_prompt", name, arguments)
        self._validate_payload(result, "prompt")
        return result

    def _validate_payload(self, value: Any, label: str) -> None:
        normalized = _json_value(value)
        if _json_size(normalized) > self.properties.max_response_bytes:
            raise MCPClientError(
                f"MCP {label} exceeds max_response_bytes")

    def _validate_collection(
        self,
        values: list[Any],
        label: str,
        *,
        validate_schemas: bool = False,
    ) -> None:
        if len(values) > self.properties.max_collection_items:
            raise MCPClientError(
                f"MCP {label} exceed max_collection_items")
        self._validate_payload(values, label)
        if not validate_schemas:
            return
        for tool in values:
            schema = getattr(tool, "input_schema", None)
            if schema is None:
                schema = getattr(tool, "inputSchema", None)
            normalized = _json_value(schema or {})
            if _schema_depth(normalized) > self.properties.max_schema_depth:
                raise MCPClientError(
                    "MCP tool schema exceeds max_schema_depth")


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
        if self._loop is None:
            raise MCPClientError("MCP client event loop failed to initialize")
        return self._loop

    def submit(self, coroutine: Any, timeout: Optional[float] = None) -> Any:
        loop = self._ensure_loop()
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            # Best-effort propagation to the coroutine/HTTP transport. Once a
            # remote side effect has been accepted, the tool itself still needs
            # an idempotency key because no distributed client can revoke it.
            future.cancel()
            raise

    async def connect_all(self) -> None:
        results = await asyncio.gather(
            *(connection.connect() for connection in self.connections.values()),
            return_exceptions=True,
        )
        for connection, result in zip(
                self.connections.values(), results, strict=True):
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
                # MCPConnection owns an asyncio/httpx timeout and cancels the
                # submitted coroutine. ToolRegistry must not add a second
                # in-process thread timeout around this managed operation.
                invoke_remote.__spring_tool_managed_timeout__ = True  # type: ignore[attr-defined]
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
