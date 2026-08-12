"""MCP server adapter for explicitly allowlisted Spring AI tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, AsyncIterator, Callable, Dict, Optional

from spring.mcp.client import MCPDependencyError, require_mcp_sdk
from spring.mcp.config import MCPConfigurationError, MCPServerProperties

logger = logging.getLogger("Spring.MCP.Server")


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    schema = tool.to_schema()["function"]["parameters"]
    return deepcopy(schema)


def _dispatcher_signature(input_schema: Dict[str, Any], context_type: Any) -> inspect.Signature:
    parameters = [
        inspect.Parameter(
            "mcp_context",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=context_type,
        )
    ]
    required = set(input_schema.get("required", []))
    for name, schema in input_schema.get("properties", {}).items():
        if name == "mcp_context":
            raise MCPConfigurationError("tool parameter name mcp_context is reserved")
        default = inspect.Parameter.empty if name in required else schema.get("default", None)
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Any,
                default=default,
            )
        )
    return inspect.Signature(parameters, return_annotation=Any)


class MCPServerAdapter:
    """Expose selected ``spring.ai.ToolRegistry`` entries through MCP.

    Export is fail-closed: the server configuration must explicitly list every
    public tool (or use ``*`` deliberately).  Execution still goes through the
    original ToolRegistry, so its authorizer, approver, timeout, size limits and
    dangerous-tool policy remain authoritative.
    """

    def __init__(
        self,
        properties: MCPServerProperties,
        tool_registry: Any,
        *,
        token_verifier: Any = None,
    ) -> None:
        require_mcp_sdk()
        self.properties = properties.validate()
        self.tool_registry = tool_registry
        self._server = self._create_server(token_verifier)
        self._http_app: Any = None
        self._register_allowlisted_tools()

    def _create_server(self, token_verifier: Any) -> Any:
        from mcp.server import MCPServer

        kwargs: Dict[str, Any] = {
            "name": self.properties.name,
            "description": self.properties.description,
            "version": self.properties.version,
        }
        if self.properties.auth_required:
            if token_verifier is None:
                raise MCPConfigurationError(
                    "MCP server auth_required=true requires an injected token_verifier"
                )
            from mcp.server.auth.settings import AuthSettings

            kwargs["token_verifier"] = token_verifier
            kwargs["auth"] = AuthSettings(
                issuer_url=self.properties.auth_issuer_url,
                resource_server_url=self.properties.resource_server_url,
                required_scopes=list(self.properties.required_scopes) or None,
            )
        return MCPServer(**kwargs)

    @property
    def native_server(self) -> Any:
        """Return the official SDK server for adding resources or prompts."""
        return self._server

    def _register_allowlisted_tools(self) -> None:
        if self.tool_registry is None or not hasattr(self.tool_registry, "names"):
            raise MCPConfigurationError("MCP server requires a spring.ai ToolRegistry")

        exported = 0
        for name in self.tool_registry.names():
            if not self.properties.is_tool_allowed(name):
                continue
            definition = self.tool_registry.get(name)
            if definition is None:
                continue
            if definition.dangerous and not self.properties.allow_dangerous_tools:
                logger.warning("Dangerous tool %s is not exported through MCP", name)
                continue
            self._add_registry_tool(definition)
            exported += 1
        if exported == 0:
            raise MCPConfigurationError("MCP server did not find any allowlisted tools to export")

    def _add_registry_tool(self, definition: Any) -> None:
        from jsonschema import ValidationError, validate
        from mcp.server.mcpserver import Context
        from mcp.types import CallToolResult, TextContent, ToolAnnotations

        input_schema = _tool_input_schema(definition)
        registry = self.tool_registry

        async def dispatch(**kwargs: Any) -> Any:
            context = kwargs.pop("mcp_context", None)
            try:
                validate(instance=kwargs, schema=input_schema)
            except ValidationError as exc:
                raise ValueError(f"invalid tool arguments: {exc.message}") from exc
            result = await asyncio.to_thread(
                registry.execute, definition.name, kwargs, context
            )
            try:
                rendered = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                structured = {"result": result}
            except (TypeError, ValueError):
                rendered = str(result)
                structured = {"result": rendered}
            return CallToolResult(
                content=[TextContent(text=rendered)],
                structured_content=structured,
            )

        dispatch.__name__ = definition.name
        dispatch.__doc__ = definition.description
        dispatch.__signature__ = _dispatcher_signature(input_schema, Context)
        dispatch.__annotations__ = {
            "mcp_context": Context,
            **{name: Any for name in input_schema.get("properties", {})},
            "return": Any,
        }
        annotations = ToolAnnotations(
            destructive_hint=True if definition.dangerous else None,
        )
        self._server.add_tool(
            dispatch,
            name=definition.name,
            description=definition.description,
            annotations=annotations,
            structured_output=False,
        )

        # The SDK builds an execution model from the dynamic signature. Replace
        # only the advertised schema with the richer schema retained by Spring
        # AI; execution is validated against that same schema above.
        sdk_tool = self._server._tool_manager.get_tool(definition.name)
        if sdk_tool is not None:
            sdk_tool.parameters = deepcopy(input_schema)

    def add_resource(
        self,
        uri: str,
        function: Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: str = "",
        mime_type: Optional[str] = None,
    ) -> Callable[..., Any]:
        """Add an MCP resource using the official SDK implementation."""
        self._server.resource(
            uri,
            name=name,
            description=description or None,
            mime_type=mime_type,
        )(function)
        return function

    def add_prompt(
        self,
        function: Callable[..., Any],
        *,
        name: Optional[str] = None,
        description: str = "",
    ) -> Callable[..., Any]:
        """Add an MCP prompt using the official SDK implementation."""
        self._server.prompt(name=name, description=description or None)(function)
        return function

    def streamable_http_app(self) -> Any:
        """Build a standalone ASGI app whose lifespan is already configured."""
        if self.properties.transport != "streamable-http":
            raise MCPConfigurationError("ASGI app is available only for streamable-http")
        if self._http_app is None:
            from mcp.server.transport_security import TransportSecuritySettings

            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(self.properties.allowed_hosts),
                allowed_origins=list(self.properties.allowed_origins),
            )
            self._http_app = self._server.streamable_http_app(
                streamable_http_path=self.properties.path,
                stateless_http=self.properties.stateless_http,
                json_response=self.properties.json_response,
                max_request_body_size=self.properties.max_request_body_bytes,
                transport_security=security,
                host=self.properties.host,
            )
        return self._http_app

    @asynccontextmanager
    async def mounted_lifespan(self) -> AsyncIterator[None]:
        """Lifespan context required when the MCP app is mounted in FastAPI."""
        self.streamable_http_app()
        async with self._server.session_manager.run():
            yield

    def run(self) -> None:
        """Run a standalone stdio or Streamable HTTP MCP server."""
        if self.properties.transport == "stdio":
            self._server.run(transport="stdio")
            return
        from mcp.server.transport_security import TransportSecuritySettings

        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(self.properties.allowed_hosts),
            allowed_origins=list(self.properties.allowed_origins),
        )
        self._server.run(
            transport="streamable-http",
            host=self.properties.host,
            port=self.properties.port,
            streamable_http_path=self.properties.path,
            stateless_http=self.properties.stateless_http,
            json_response=self.properties.json_response,
            max_request_body_size=self.properties.max_request_body_bytes,
            transport_security=security,
        )


__all__ = ["MCPServerAdapter"]
