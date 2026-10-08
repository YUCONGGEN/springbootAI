"""订单 MCP 服务：默认 HTTP，--stdio 用于由 Agent 自动启动。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from springbootai.mcp import MCPServer, MCPTool, build_mcp_server


@MCPServer(
    name="order-agent-demo",
    transport="streamable-http",
    host="127.0.0.1",
    port=8002,
    path="/mcp",
    json_response=False,
    allowed_tools=["get_order", "get_tracking"],
)
class OrderMCPServer:
    """只读模拟数据；真实业务应在工具内部检查用户和订单归属。"""

    @MCPTool(description="根据订单号查订单状态及运单号；查询物流前先调用此工具")
    def get_order(self, order_id: str) -> dict:
        orders = {
            "A-1001": {"status": "已发货", "tracking_no": "SF-DEMO-1001", "item": "机械键盘"},
            "A-1002": {"status": "待发货", "tracking_no": None, "item": "无线鼠标"},
        }
        order = orders.get(order_id)
        if order is None:
            return {"found": False, "order_id": order_id}
        return {"found": True, "order_id": order_id, **order}

    @MCPTool(description="根据订单工具返回的 tracking_no 查询物流位置及预计送达时间")
    def get_tracking(self, tracking_no: str) -> dict:
        if tracking_no != "SF-DEMO-1001":
            return {"found": False, "tracking_no": tracking_no}
        return {
            "found": True,
            "tracking_no": tracking_no,
            "location": "深圳分拨中心",
            "status": "运输中",
            "estimated_delivery": "明天 18:00 前（模拟时间）",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true", help="通过标准输入输出提供 MCP")
    args = parser.parse_args()
    server = build_mcp_server(OrderMCPServer())
    if args.stdio:
        # stdout 属于 MCP 协议，不要向 stdout 打印业务日志。
        server.native_server.run(transport="stdio")
    else:
        server.run()


if __name__ == "__main__":
    main()
