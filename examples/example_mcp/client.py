"""Runnable SpringBootAI MCP Client demo.

Start ``python -m example_mcp.server`` first, then run:
    python -m example_mcp.client
"""

from springbootai.ai import ToolExecutionPolicy
from springbootai.mcp import MCPClientProperties, build_client_manager


def main() -> None:
    properties = MCPClientProperties(
        name="demo",
        transport="streamable-http",
        url="http://127.0.0.1:8001/mcp",
        timeout_seconds=10,
        tool_prefix="demo__",
        allowed_tools=("add", "order_status"),
    )
    manager = build_client_manager([properties])
    try:
        registry = manager.create_tool_registry_sync(
            ToolExecutionPolicy(
                allowed_tools={"demo__add", "demo__order_status"},
                timeout_seconds=10,
            )
        )
        print("Discovered AI tools:", registry.names())
        print("2 + 5 =", registry.execute("demo__add", {"a": 2, "b": 5}))
        print(
            "Order:",
            registry.execute("demo__order_status", {"order_id": "DEMO-001"}),
        )
    finally:
        manager.close_sync()


if __name__ == "__main__":
    main()
