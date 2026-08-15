"""A small LangGraph demo that reuses SpringBootAI's AI ChatModel.

Run with ``python -m example_langgraph.demo``.  It uses FakeChatModel so it
does not need an API key.  Production applications should inject a persistent
checkpointer instead of the in-memory checkpointer used here.
"""

from __future__ import annotations

import os
import sys
from typing import Literal, TypedDict

# 加入项目根和 examples/ 到 sys.path，支持直接 python examples/example_langgraph/demo.py 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_EXAMPLES_DIR)
for _p in (_PROJECT_ROOT, _EXAMPLES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("AI_ALLOW_FAKE", "true")

from langgraph.graph import END
from langgraph.types import interrupt

from spring.ai.core import Message
from spring.ai.providers import FakeChatModel
from spring.langgraph import LangGraphProperties, LangGraphWorkflow


class OrderState(TypedDict, total=False):
    request: str
    amount: float
    risk: str
    answer: str
    approved: bool


def build_order_workflow(model=None) -> LangGraphWorkflow:
    """Build classify -> AI answer -> optional human approval workflow."""
    model = model or FakeChatModel(prefix="[AI]")
    workflow = LangGraphWorkflow(
        LangGraphProperties(
            enabled=True,
            name="order_review_demo",
            checkpointer="memory",
            allow_in_memory=True,
            max_steps=10,
        ),
        state_schema=OrderState,
    )

    def classify(state: OrderState):
        return {"risk": "review" if float(state.get("amount", 0)) >= 1000 else "normal"}

    def answer(state: OrderState):
        response = model.call([Message.user(state.get("request", ""))])
        return {"answer": response.content()}

    def approval(state: OrderState):
        decision = interrupt({
            "type": "order_approval",
            "message": "金额较高，请确认是否继续",
            "amount": state.get("amount", 0),
        })
        return {"approved": decision in (True, "approve", {"type": "approve"})}

    def route(state: OrderState) -> Literal["approval", "finish"]:
        return "approval" if state.get("risk") == "review" else "finish"

    workflow.add_node("classify", classify)
    workflow.add_node("answer", answer)
    workflow.add_node("approval", approval)
    workflow.add_node("finish", lambda state: {})
    workflow.set_entry_point("classify")
    workflow.add_edge("classify", "answer")
    workflow.add_conditional_edges("answer", route, {"approval": "approval", "finish": "finish"})
    workflow.add_edge("approval", "finish")
    workflow.add_edge("finish", END)
    return workflow


def main() -> None:
    workflow = build_order_workflow()
    result = workflow.invoke(
        {"request": "请确认这笔申请", "amount": 99},
        thread_id="demo-safe-1",
        tenant_id="demo-tenant",
    )
    print("普通请求结果:", result)

    paused = workflow.invoke(
        {"request": "请确认大额申请", "amount": 2000},
        thread_id="demo-review-1",
        tenant_id="demo-tenant",
    )
    print("大额请求状态:", paused)
    resumed = workflow.resume(
        thread_id="demo-review-1",
        tenant_id="demo-tenant",
        resume_value="approve",
    )
    print("人工批准后恢复:", resumed)


if __name__ == "__main__":
    main()
