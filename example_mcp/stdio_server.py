"""Small stdio MCP Server used by the client example and integration tests."""

from spring.ai import ToolExecutionPolicy, ToolRegistry
from spring.mcp import MCPServerAdapter, MCPServerProperties


tools = ToolRegistry(policy=ToolExecutionPolicy(allowed_tools={"multiply"}))


def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


tools.register("multiply", multiply, description="Multiply two integers")
server = MCPServerAdapter(
    MCPServerProperties(
        enabled=True,
        transport="stdio",
        allowed_tools=("multiply",),
    ),
    tools,
)


if __name__ == "__main__":
    server.run()
