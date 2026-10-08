"""订单 Agent 集成验证：真实 MCP 子进程/HTTP，无外部模型请求。"""

import socket
import threading
import time

import pytest

pytest.importorskip("mcp")

from example_mcp._agent_demo_model import DemoOrderModel
from example_mcp.agent_demo import OrderAgent, PUBLIC_TOOLS
from example_mcp.order_agent_server import OrderMCPServer
from springbootai.ai.tools import ToolExecutionError
from springbootai.mcp import build_mcp_server


@pytest.fixture(scope="module")
def stdio_agent():
    model = DemoOrderModel()
    with OrderAgent(model) as agent:
        thread = agent.manager._thread
        yield agent, model
    assert thread is not None and not thread.is_alive()
    assert agent.manager._loop is None
    assert all(connection._client is None for connection in agent.manager.connections.values())


@pytest.mark.parametrize("question, expected, calls", [
    (
        "订单 A-1001 到哪了？",
        "深圳分拨中心",
        [("orders__get_order", {"order_id": "A-1001"}),
         ("orders__get_tracking", {"tracking_no": "SF-DEMO-1001"})],
    ),
    (
        "查询 A-1002 的物流",
        "待发货",
        [("orders__get_order", {"order_id": "A-1002"})],
    ),
    (
        "查询 A-9999 的物流",
        "未找到订单 A-9999",
        [("orders__get_order", {"order_id": "A-9999"})],
    ),
    ("没有订单号的提问", "请提供订单号", []),
])
def test_agent_uses_remote_results_and_skips_unnecessary_tools(stdio_agent, question, expected, calls):
    agent, model = stdio_agent
    model.requested_tools.clear()
    assert expected in agent.ask(question)
    assert model.requested_tools == calls


def test_discovery_preserves_remote_schema_and_denies_tools_outside_allowlist(stdio_agent):
    agent, _model = stdio_agent
    assert set(agent.tools.names()) == PUBLIC_TOOLS
    schema = agent.tools.get("orders__get_order").to_schema()["function"]["parameters"]
    assert schema["properties"]["order_id"]["type"] == "string"
    assert schema["required"] == ["order_id"]
    with pytest.raises(ToolExecutionError, match="expected string"):
        agent.tools.execute("orders__get_order", {"order_id": 1001})
    with pytest.raises(PermissionError, match="not allowed"):
        agent.manager.call_tool_sync("orders", "delete_order", {"order_id": "A-1001"})


def test_agent_connects_to_a_real_independent_http_server():
    uvicorn = pytest.importorskip("uvicorn")
    adapter = build_mcp_server(OrderMCPServer())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            adapter.streamable_http_app(), host="127.0.0.1", port=port,
            log_level="warning", lifespan="on",
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            model = DemoOrderModel()
            with OrderAgent(model, mcp_url=f"http://127.0.0.1:{port}/mcp") as agent:
                answer = agent.ask("A-1001 的物流信息是什么？")
                assert "深圳分拨中心" in answer
                assert "SF-DEMO-1001" in answer
                assert [name for name, _arguments in model.requested_tools] == [
                    "orders__get_order", "orders__get_tracking",
                ]
                manager_thread = agent.manager._thread
            assert manager_thread is not None and not manager_thread.is_alive()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert not thread.is_alive()
