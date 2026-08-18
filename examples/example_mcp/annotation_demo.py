"""Annotation-driven MCP client/server example.

Run ``python -m example_mcp.server`` first, then execute this module. The
``DemoMCPClient.add`` method body is never called; ``@MCPCall`` sends a real
MCP request to the configured server.
"""

from springbootai.mcp import (
    MCPCall,
    MCPClient,
    MCPClientProperties,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
    bind_mcp_client,
    build_client_manager,
    build_mcp_server,
)


@MCPClient("demo")
class DemoMCPClient:
    @MCPCall("add")
    def add(self, a: int, b: int) -> int:
        """The annotation replaces this declarative placeholder."""
        raise NotImplementedError


@MCPServer(
    name="annotated-demo",
    transport="streamable-http",
    allowed_tools=["add"],
)
class DemoMCPServer:
    @MCPTool(description="Add two integers")
    def add(self, a: int, b: int) -> int:
        return a + b

    @MCPResource("guide://quickstart")
    def quickstart(self) -> str:
        return "Call add with two integers."

    @MCPPrompt(description="Explain a calculation")
    def explain(self, expression: str) -> str:
        return f"Explain {expression} to a beginner."


def main() -> None:
    manager = build_client_manager(
        [
            MCPClientProperties(
                name="demo",
                transport="streamable-http",
                url="http://127.0.0.1:8001/mcp",
                allowed_tools=("add",),
            )
        ]
    )
    client = bind_mcp_client(DemoMCPClient(), manager)
    try:
        print("2 + 5 =", client.add(2, 5))
    finally:
        manager.close_sync()


if __name__ == "__main__":
    main()


# Standalone annotated server alternative:
annotated_server = build_mcp_server(DemoMCPServer())
