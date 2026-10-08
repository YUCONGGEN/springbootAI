"""离线固定步骤模型，仅验证 Agent/MCP 流程，不模拟大模型推理能力。"""

import ast
import json
import re

from springbootai.ai import ChatModel, ChatResponse, Generation, Message, MessageType


class DemoOrderModel(ChatModel):
    """从 MCP 返回的订单数据取运单号，最多查询两次工具。"""

    def __init__(self):
        self.requested_tools: list[tuple[str, dict]] = []

    @staticmethod
    def _answer(text: str, calls=None) -> ChatResponse:
        return ChatResponse(
            generations=[Generation(output=Message.assistant(text))],
            metadata={"provider": "scripted-demo", "tool_calls": calls or []},
        )

    def _request(self, name: str, arguments: dict) -> ChatResponse:
        self.requested_tools.append((name, dict(arguments)))
        calls = [{
            "id": f"demo-{len(self.requested_tools)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        }]
        return self._answer("", calls)

    def _raw_call(self, messages, tool_registry=None, options=None):
        question = next((m.content for m in reversed(messages) if m.type == MessageType.USER), "")
        order_id = re.search(r"\bA-\d{4}\b", question)
        if order_id is None:
            return self._answer("演示模式请提供订单号，例如 A-1001 或 A-1002。")
        observations = {}
        for message in messages:
            if message.type != MessageType.TOOL:
                continue
            try:
                value = ast.literal_eval(message.content)
            except (SyntaxError, ValueError):
                return self._answer("工具未返回有效数据，请检查 MCP 服务；无法确认订单或物流。")
            if not isinstance(value, dict):
                return self._answer("工具返回格式不符合订单示例要求。")
            observations[message.name] = value
        order = observations.get("orders__get_order")
        if order is None:
            return self._request("orders__get_order", {"order_id": order_id.group()})
        if not order.get("found"):
            return self._answer(f"未找到订单 {order['order_id']}。")
        tracking_no = order.get("tracking_no")
        if not tracking_no:
            return self._answer(f"订单 {order['order_id']}（{order['item']}）{order['status']}，暂时没有运单号。")
        tracking = observations.get("orders__get_tracking")
        if tracking is None:
            return self._request("orders__get_tracking", {"tracking_no": tracking_no})
        if not tracking.get("found"):
            return self._answer(f"订单 {order['order_id']} 已发货，但暂时没有查到物流信息。")
        return self._answer(
            f"订单 {order['order_id']}（{order['item']}）{order['status']}。"
            f"运单 {tracking_no} 当前在{tracking['location']}，状态为{tracking['status']}，"
            f"预计{tracking['estimated_delivery']}送达。"
        )
