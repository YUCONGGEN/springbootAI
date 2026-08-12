"""Runtime builders for annotation-driven MCP clients and servers."""

from __future__ import annotations

import inspect
from typing import Any

from spring.annotations.core import get_spring_annotations
from spring.ai.tools import ToolExecutionPolicy, ToolRegistry
from spring.mcp.annotations import (
    MCPClient,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
)
from spring.mcp.config import MCPConfigurationError, MCPServerProperties
from spring.mcp.server import MCPServerAdapter


def bind_mcp_client(instance: Any, manager: Any) -> Any:
    """Inject a client manager into an ``@MCPClient`` instance explicitly."""
    if not isinstance(_find_class_annotation(instance, MCPClient), MCPClient):
        raise MCPConfigurationError("bind_mcp_client target must use @MCPClient")
    instance._mcp_client_manager = manager
    return instance


def _find_class_annotation(instance: Any, annotation_type: type) -> Any:
    target = instance if inspect.isclass(instance) else type(instance)
    return next(
        (item for item in reversed(get_spring_annotations(target)) if isinstance(item, annotation_type)),
        None,
    )


def build_mcp_server(instance: Any, *, token_verifier: Any = None) -> MCPServerAdapter:
    """Build an official MCP server from an ``@MCPServer`` component instance."""
    annotation = _find_class_annotation(instance, MCPServer)
    if annotation is None:
        raise MCPConfigurationError("server component must use @MCPServer")

    methods: list[tuple[str, Any, list[Any]]] = []
    tool_names: set[str] = set()
    for method_name, function in inspect.getmembers(type(instance), predicate=inspect.isfunction):
        annotations = get_spring_annotations(function)
        if not annotations:
            continue
        methods.append((method_name, getattr(instance, method_name), annotations))
        for item in annotations:
            if isinstance(item, MCPTool):
                tool_names.add(item.name or method_name)

    if not tool_names:
        raise MCPConfigurationError("@MCPServer component must declare at least one @MCPTool")
    if not annotation.allowed_tools:
        raise MCPConfigurationError(
            "@MCPServer allowed_tools must explicitly list exported @MCPTool methods"
        )
    allowed_tools = set(annotation.allowed_tools)
    unknown = allowed_tools - tool_names
    if unknown:
        raise MCPConfigurationError(
            "@MCPServer allowed_tools references unknown @MCPTool entries: "
            + ", ".join(sorted(unknown))
        )

    registry = ToolRegistry(policy=ToolExecutionPolicy(
        allowed_tools=allowed_tools,
        allow_dangerous=annotation.allow_dangerous_tools,
    ))
    for method_name, bound_method, annotations in methods:
        for item in annotations:
            if not isinstance(item, MCPTool):
                continue
            public_name = item.name or method_name
            if public_name not in allowed_tools:
                continue
            registry.register(
                public_name,
                bound_method,
                description=item.description,
                dangerous=item.dangerous,
            )

    adapter = MCPServerAdapter(
        MCPServerProperties(
            enabled=True,
            name=annotation.name,
            description=annotation.description,
            transport=annotation.transport,
            host=annotation.host,
            port=annotation.port,
            path=annotation.path,
            stateless_http=annotation.stateless_http,
            json_response=annotation.json_response,
            max_request_body_bytes=annotation.max_request_body_bytes,
            allowed_tools=tuple(sorted(allowed_tools)),
            allow_dangerous_tools=annotation.allow_dangerous_tools,
            allowed_hosts=annotation.allowed_hosts,
            allowed_origins=annotation.allowed_origins,
            auth_required=annotation.auth_required,
            auth_issuer_url=annotation.auth_issuer_url,
            resource_server_url=annotation.resource_server_url,
            required_scopes=annotation.required_scopes,
        ),
        registry,
        token_verifier=token_verifier,
    )

    for method_name, bound_method, annotations in methods:
        for item in annotations:
            if isinstance(item, MCPResource):
                adapter.add_resource(
                    item.uri,
                    bound_method,
                    name=item.name or method_name,
                    description=item.description,
                    mime_type=item.mime_type,
                )
            elif isinstance(item, MCPPrompt):
                adapter.add_prompt(
                    bound_method,
                    name=item.name or method_name,
                    description=item.description,
                )
    return adapter


class MCPAnnotationRuntime:
    """Small facade used by application bootstrap code and tests."""

    @staticmethod
    def bind_client(instance: Any, manager: Any) -> Any:
        return bind_mcp_client(instance, manager)

    @staticmethod
    def build_server(instance: Any, *, token_verifier: Any = None) -> MCPServerAdapter:
        return build_mcp_server(instance, token_verifier=token_verifier)


__all__ = ["MCPAnnotationRuntime", "bind_mcp_client", "build_mcp_server"]
