"""Model Context Protocol integration for SpringBootAI.

The module is import-safe without the optional ``mcp`` dependency.  The SDK is
required only when MCP is enabled or a client/server object is created.
"""

from spring.mcp.autoconfig import configure_mcp
from spring.mcp.annotation_runtime import (
    MCPAnnotationRuntime,
    bind_mcp_client,
    build_mcp_server,
)
from spring.mcp.annotations import (
    MCPCall,
    MCPClient,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
)
from spring.mcp.client import (
    MCPClientConnection,
    MCPClientError,
    MCPClientManager,
    MCPDependencyError,
    build_client_manager,
    require_mcp_sdk,
)
from spring.mcp.config import (
    MCPClientProperties,
    MCPConfigurationError,
    MCPProperties,
    MCPServerProperties,
    bind_mcp_config,
)
from spring.mcp.server import MCPServerAdapter

__all__ = [
    "MCPClientConnection",
    "MCPClientError",
    "MCPClientManager",
    "MCPClientProperties",
    "MCPConfigurationError",
    "MCPDependencyError",
    "MCPProperties",
    "MCPServerAdapter",
    "MCPServerProperties",
    "MCPAnnotationRuntime",
    "MCPCall",
    "MCPClient",
    "MCPPrompt",
    "MCPResource",
    "MCPServer",
    "MCPTool",
    "bind_mcp_config",
    "bind_mcp_client",
    "build_mcp_server",
    "build_client_manager",
    "configure_mcp",
    "require_mcp_sdk",
]
