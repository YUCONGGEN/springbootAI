"""Runnable SpringBootAI MCP Server demo.

Run from the project root:
    python examples/example_mcp/server.py

The endpoint is http://127.0.0.1:8001/mcp.
"""

import os
import sys

# 加入项目根和 examples/ 到 sys.path，支持直接 python examples/example_mcp/server.py 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_EXAMPLES_DIR)
for _p in (_PROJECT_ROOT, _EXAMPLES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spring.ai import ToolExecutionPolicy, ToolRegistry
from spring.mcp import MCPServerAdapter, MCPServerProperties


def build_server() -> MCPServerAdapter:
    policy = ToolExecutionPolicy(
        allowed_tools={"add", "order_status"},
        allow_dangerous=False,
        timeout_seconds=10,
        max_argument_bytes=8_192,
        max_result_chars=5_000,
    )
    tools = ToolRegistry(policy=policy)

    def add(a: int, b: int) -> int:
        """Add two integers and return the result."""
        return a + b

    def order_status(order_id: str) -> dict:
        """Return a demonstration order status without accessing a real database."""
        return {"order_id": order_id, "status": "PAID"}

    tools.register("add", add, description="Add two integers")
    tools.register(
        "order_status",
        order_status,
        description="Read a demonstration order status",
    )

    properties = MCPServerProperties(
        enabled=True,
        name="springbootai-demo",
        description="SpringBootAI MCP beginner demo",
        transport="streamable-http",
        host="127.0.0.1",
        port=8001,
        path="/mcp",
        stateless_http=True,
        json_response=True,
        allowed_tools=("add", "order_status"),
    )
    server = MCPServerAdapter(properties, tools)

    @server.native_server.resource("guide://quickstart")
    def quickstart() -> str:
        """Return a small help resource."""
        return "Call add with two integers, or order_status with an order_id."

    @server.native_server.prompt(name="explain_order")
    def explain_order(order_id: str) -> str:
        """Build a prompt that asks an AI to explain an order."""
        return f"Explain the current state of order {order_id} in simple language."

    return server


mcp_server = build_server()
app = mcp_server.streamable_http_app()


if __name__ == "__main__":
    mcp_server.run()
