"""Executable Spring-style annotations for MCP clients and servers."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from springbootai.annotations.core import Component, SpringAnnotation, get_spring_annotations
from springbootai.ai.annotations import Tool


def _class_annotation(instance: Any, annotation_type: type) -> Any:
    target = instance if inspect.isclass(instance) else type(instance)
    return next(
        (item for item in reversed(get_spring_annotations(target)) if isinstance(item, annotation_type)),
        None,
    )


def _resolve_manager(instance: Any, bean_name: str) -> Any:
    for attribute in ("_mcp_client_manager", "mcp_client_manager"):
        manager = getattr(instance, attribute, None)
        if manager is not None:
            return manager
    from springbootai.context.registry import BeanRegistry

    manager = BeanRegistry().get(bean_name)
    if manager is None:
        raise RuntimeError(
            f"MCP client manager bean {bean_name!r} is unavailable; "
            "enable springbootai.mcp or inject _mcp_client_manager"
        )
    return manager


def _arguments(function: Callable[..., Any], args: tuple[Any, ...],
               kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    bound = inspect.signature(function).bind(*args, **kwargs)
    bound.apply_defaults()
    instance = bound.arguments.pop("self", None)
    bound.arguments.pop("cls", None)
    return instance, dict(bound.arguments)


class MCPClient(Component):
    """Mark a component as a declarative client for one configured MCP server.

    ``name`` must match an entry under ``springbootai.mcp.clients``. Methods annotated
    with :class:`MCPCall` perform real protocol calls when invoked.
    """

    _annotation_type = "mcp_client"

    def __init__(self, name: str, value: str = "", manager_bean: str = "mcpClientManager"):
        if not name:
            raise ValueError("MCPClient name is required")
        super().__init__(value=value)
        self.name = name
        self.manager_bean = manager_bean


class MCPCall(SpringAnnotation):
    """Turn a method into a synchronous or asynchronous remote MCP tool call."""

    _annotation_type = "mcp_call"

    def __new__(cls, *args: Any, **kwargs: Any):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            function = args[0]
            instance = object.__new__(cls)
            instance.__init__()
            return instance(function)
        return object.__new__(cls)

    def __init__(self, tool: str = "", client: str = ""):
        super().__init__(tool=tool, client=client)

    def __call__(self, function: Callable[..., Any]) -> Callable[..., Any]:
        if not callable(function):
            raise TypeError("MCPCall can decorate only a callable")
        tool_name = self.tool or function.__name__

        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, arguments = _arguments(function, args, kwargs)
                class_config = _class_annotation(instance, MCPClient)
                client_name = self.client or (class_config.name if class_config else "")
                if not client_name:
                    raise RuntimeError("MCPCall requires @MCPClient or client='name'")
                bean_name = class_config.manager_bean if class_config else "mcpClientManager"
                manager = _resolve_manager(instance, bean_name)
                return await manager.acall_tool(client_name, tool_name, arguments)

            wrapper = async_wrapper
        else:
            @functools.wraps(function)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, arguments = _arguments(function, args, kwargs)
                class_config = _class_annotation(instance, MCPClient)
                client_name = self.client or (class_config.name if class_config else "")
                if not client_name:
                    raise RuntimeError("MCPCall requires @MCPClient or client='name'")
                bean_name = class_config.manager_bean if class_config else "mcpClientManager"
                manager = _resolve_manager(instance, bean_name)
                return manager.call_tool_sync(client_name, tool_name, arguments)

            wrapper = sync_wrapper

        wrapper.__spring_annotations__ = list(
            getattr(function, "__dict__", {}).get("__spring_annotations__", [])
        ) + [self]
        self._original_class = function
        return wrapper


class MCPServer(Component):
    """Mark a component class as an annotation-driven MCP Server definition."""

    _annotation_type = "mcp_server"

    def __init__(
        self,
        name: str = "springbootai",
        value: str = "",
        description: str = "SpringBootAI MCP Server",
        transport: str = "streamable-http",
        host: str = "127.0.0.1",
        port: int = 8001,
        path: str = "/mcp",
        stateless_http: bool = True,
        json_response: bool = True,
        max_request_body_bytes: int = 1_048_576,
        allowed_tools: Optional[list[str]] = None,
        allow_dangerous_tools: bool = False,
        allowed_hosts: Optional[list[str]] = None,
        allowed_origins: Optional[list[str]] = None,
        auth_required: bool = False,
        auth_issuer_url: str = "",
        resource_server_url: str = "",
        required_scopes: Optional[list[str]] = None,
    ):
        super().__init__(value=value)
        self.name = name
        self.description = description
        self.transport = transport
        self.host = host
        self.port = port
        self.path = path
        self.stateless_http = stateless_http
        self.json_response = json_response
        self.max_request_body_bytes = max_request_body_bytes
        self.allowed_tools = tuple(allowed_tools or ())
        self.allow_dangerous_tools = allow_dangerous_tools
        self.allowed_hosts = tuple(
            allowed_hosts
            or ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*")
        )
        self.allowed_origins = tuple(allowed_origins or ())
        self.auth_required = auth_required
        self.auth_issuer_url = auth_issuer_url
        self.resource_server_url = resource_server_url
        self.required_scopes = tuple(required_scopes or ())


class MCPTool(Tool):
    """Expose a method as an MCP tool when its containing server is built."""

    _annotation_type = "mcp_tool"

    def __init__(self, name: str = "", description: str = "",
                 dangerous: bool = False):
        super().__init__(name=name, description=description, return_description="")
        self.dangerous = dangerous


class MCPResource(SpringAnnotation):
    """Expose a method as an MCP resource or URI template."""

    _annotation_type = "mcp_resource"

    def __init__(self, uri: str, name: str = "", description: str = "",
                 mime_type: str = "text/plain"):
        if not uri:
            raise ValueError("MCPResource uri is required")
        super().__init__(
            uri=uri,
            name=name,
            description=description,
            mime_type=mime_type,
        )


class MCPPrompt(SpringAnnotation):
    """Expose a method as a reusable MCP prompt."""

    _annotation_type = "mcp_prompt"

    def __init__(self, name: str = "", description: str = ""):
        super().__init__(name=name, description=description)


__all__ = [
    "MCPCall",
    "MCPClient",
    "MCPPrompt",
    "MCPResource",
    "MCPServer",
    "MCPTool",
]
