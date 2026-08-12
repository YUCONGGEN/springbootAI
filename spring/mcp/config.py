"""Typed, fail-closed configuration for the optional MCP integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


class MCPConfigurationError(ValueError):
    """Raised when an MCP setting is invalid or unsafe."""


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise MCPConfigurationError("MCP list settings must be a list or comma-separated string")


def _mapping(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MCPConfigurationError("MCP mapping settings must be objects")
    return {str(key): str(item) for key, item in value.items()}


def _get(data: Mapping[str, Any], name: str, default: Any = None) -> Any:
    if name in data:
        return data[name]
    snake = name.replace("-", "_")
    if snake in data:
        return data[snake]
    kebab = name.replace("_", "-")
    return data.get(kebab, default)


def _is_loopback_host(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class MCPClientProperties:
    """One outbound MCP server connection."""

    name: str
    transport: str = "streamable-http"  # streamable-http | stdio
    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    tool_prefix: str = ""
    allowed_tools: tuple[str, ...] = ()
    dangerous_tools: tuple[str, ...] = ()
    allow_dangerous_tools: bool = False
    max_argument_bytes: int = 65_536
    max_result_chars: int = 100_000
    fail_fast: bool = True
    allow_insecure_http: bool = False

    def validate(self) -> "MCPClientProperties":
        if not self.name or len(self.name) > 64:
            raise MCPConfigurationError("MCP client name must be 1-64 characters")
        if self.transport not in {"streamable-http", "stdio"}:
            raise MCPConfigurationError("MCP client transport must be streamable-http or stdio")
        if not 0 < self.timeout_seconds <= 600:
            raise MCPConfigurationError("MCP client timeout_seconds must be in (0, 600]")
        if not 1024 <= self.max_argument_bytes <= 10 * 1024 * 1024:
            raise MCPConfigurationError(
                "MCP client max_argument_bytes must be in [1024, 10485760]"
            )
        if not 1024 <= self.max_result_chars <= 10_000_000:
            raise MCPConfigurationError(
                "MCP client max_result_chars must be in [1024, 10000000]"
            )
        if self.transport == "streamable-http":
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise MCPConfigurationError(f"MCP client {self.name!r} has an invalid URL")
            if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname or ""):
                if not self.allow_insecure_http:
                    raise MCPConfigurationError(
                        f"MCP client {self.name!r} requires HTTPS outside localhost"
                    )
        elif not self.command:
            raise MCPConfigurationError(f"MCP stdio client {self.name!r} requires command")
        return self

    def is_tool_allowed(self, tool_name: str) -> bool:
        allowlisted = "*" in self.allowed_tools or tool_name in self.allowed_tools
        dangerous = tool_name in self.dangerous_tools
        return allowlisted and (not dangerous or self.allow_dangerous_tools)

    @property
    def effective_prefix(self) -> str:
        prefix = self.tool_prefix.strip()
        return prefix if prefix else f"{self.name}__"


@dataclass(frozen=True)
class MCPServerProperties:
    """Inbound MCP server settings."""

    enabled: bool = False
    name: str = "springbootai"
    description: str = "SpringBootAI MCP Server"
    version: str = ""
    transport: str = "streamable-http"
    host: str = "127.0.0.1"
    port: int = 8001
    path: str = "/mcp"
    stateless_http: bool = True
    json_response: bool = True
    max_request_body_bytes: int = 1_048_576
    allowed_tools: tuple[str, ...] = ()
    allow_dangerous_tools: bool = False
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*")
    allowed_origins: tuple[str, ...] = ()
    auth_required: bool = False
    auth_issuer_url: str = ""
    resource_server_url: str = ""
    required_scopes: tuple[str, ...] = ()

    def validate(self) -> "MCPServerProperties":
        if not self.enabled:
            return self
        if not self.name or len(self.name) > 128:
            raise MCPConfigurationError("MCP server name must be 1-128 characters")
        if self.transport not in {"streamable-http", "stdio"}:
            raise MCPConfigurationError("MCP server transport must be streamable-http or stdio")
        if not self.allowed_tools:
            raise MCPConfigurationError("MCP server allowed_tools must explicitly list exported tools")
        if self.transport == "streamable-http":
            if not 1 <= self.port <= 65535:
                raise MCPConfigurationError("MCP server port must be in [1, 65535]")
            if not self.path.startswith("/"):
                raise MCPConfigurationError("MCP server path must start with /")
            if not 1024 <= self.max_request_body_bytes <= 16 * 1024 * 1024:
                raise MCPConfigurationError(
                    "MCP server max_request_body_bytes must be in [1024, 16777216]"
                )
            if not _is_loopback_host(self.host) and not self.auth_required:
                raise MCPConfigurationError(
                    "non-loopback MCP HTTP servers require auth_required=true"
                )
        if self.auth_required and (not self.auth_issuer_url or not self.resource_server_url):
            raise MCPConfigurationError(
                "authenticated MCP servers require auth_issuer_url and resource_server_url"
            )
        return self

    def is_tool_allowed(self, tool_name: str) -> bool:
        return "*" in self.allowed_tools or tool_name in self.allowed_tools


@dataclass(frozen=True)
class MCPProperties:
    enabled: bool = False
    auto_connect: bool = True
    clients: tuple[MCPClientProperties, ...] = ()
    server: MCPServerProperties = field(default_factory=MCPServerProperties)

    def validate(self) -> "MCPProperties":
        names: set[str] = set()
        for client in self.clients:
            client.validate()
            if client.name in names:
                raise MCPConfigurationError(f"duplicate MCP client name: {client.name}")
            names.add(client.name)
        self.server.validate()
        return self


def _bind_client(name: str, data: Mapping[str, Any]) -> MCPClientProperties:
    return MCPClientProperties(
        name=name,
        transport=str(_get(data, "transport", "streamable-http")).lower(),
        url=str(_get(data, "url", "")),
        command=str(_get(data, "command", "")),
        args=_sequence(_get(data, "args")),
        env=_mapping(_get(data, "env")),
        cwd=str(_get(data, "cwd", "")),
        headers=_mapping(_get(data, "headers")),
        timeout_seconds=_number(_get(data, "timeout-seconds", 30.0), 30.0),
        tool_prefix=str(_get(data, "tool-prefix", "")),
        allowed_tools=_sequence(_get(data, "allowed-tools")),
        dangerous_tools=_sequence(_get(data, "dangerous-tools")),
        allow_dangerous_tools=_bool(_get(data, "allow-dangerous-tools", False), False),
        max_argument_bytes=_integer(_get(data, "max-argument-bytes", 65_536), 65_536),
        max_result_chars=_integer(_get(data, "max-result-chars", 100_000), 100_000),
        fail_fast=_bool(_get(data, "fail-fast", True), True),
        allow_insecure_http=_bool(_get(data, "allow-insecure-http", False), False),
    ).validate()


def _bind_server(data: Mapping[str, Any]) -> MCPServerProperties:
    return MCPServerProperties(
        enabled=_bool(_get(data, "enabled", False), False),
        name=str(_get(data, "name", "springbootai")),
        description=str(_get(data, "description", "SpringBootAI MCP Server")),
        version=str(_get(data, "version", "")),
        transport=str(_get(data, "transport", "streamable-http")).lower(),
        host=str(_get(data, "host", "127.0.0.1")),
        port=_integer(_get(data, "port", 8001), 8001),
        path=str(_get(data, "path", "/mcp")),
        stateless_http=_bool(_get(data, "stateless-http", True), True),
        json_response=_bool(_get(data, "json-response", True), True),
        max_request_body_bytes=_integer(
            _get(data, "max-request-body-bytes", 1_048_576), 1_048_576
        ),
        allowed_tools=_sequence(_get(data, "allowed-tools")),
        allow_dangerous_tools=_bool(_get(data, "allow-dangerous-tools", False), False),
        allowed_hosts=_sequence(
            _get(
                data,
                "allowed-hosts",
                ("127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"),
            )
        ),
        allowed_origins=_sequence(_get(data, "allowed-origins")),
        auth_required=_bool(_get(data, "auth-required", False), False),
        auth_issuer_url=str(_get(data, "auth-issuer-url", "")),
        resource_server_url=str(_get(data, "resource-server-url", "")),
        required_scopes=_sequence(_get(data, "required-scopes")),
    ).validate()


def bind_mcp_config(data: Mapping[str, Any] | None = None) -> MCPProperties:
    """Bind the ``spring.mcp`` mapping into validated properties."""
    data = data or {}
    enabled = _bool(os.getenv("MCP_ENABLED", _get(data, "enabled", False)), False)
    auto_connect = _bool(_get(data, "auto-connect", True), True)

    raw_clients = _get(data, "clients", {}) or {}
    clients: list[MCPClientProperties] = []
    if isinstance(raw_clients, Mapping):
        for name, raw in raw_clients.items():
            if not isinstance(raw, Mapping):
                raise MCPConfigurationError(f"MCP client {name!r} configuration must be an object")
            if _bool(_get(raw, "enabled", True), True):
                clients.append(_bind_client(str(name), raw))
    elif isinstance(raw_clients, Sequence) and not isinstance(raw_clients, str):
        for raw in raw_clients:
            if not isinstance(raw, Mapping) or not _get(raw, "name"):
                raise MCPConfigurationError("MCP client list entries require a name")
            if _bool(_get(raw, "enabled", True), True):
                clients.append(_bind_client(str(_get(raw, "name")), raw))
    else:
        raise MCPConfigurationError("spring.mcp.clients must be an object or list")

    raw_server = _get(data, "server", {}) or {}
    if not isinstance(raw_server, Mapping):
        raise MCPConfigurationError("spring.mcp.server must be an object")
    return MCPProperties(
        enabled=enabled,
        auto_connect=auto_connect,
        clients=tuple(clients),
        server=_bind_server(raw_server),
    ).validate()


__all__ = [
    "MCPClientProperties",
    "MCPConfigurationError",
    "MCPProperties",
    "MCPServerProperties",
    "bind_mcp_config",
]
