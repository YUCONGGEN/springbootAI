"""Runnable annotation-driven LangGraph example without an API key."""

import os
import sys

# 加入项目根到 sys.path，支持直接 python examples/example_langgraph/annotation_demo.py 运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from typing import TypedDict

from spring.langgraph import GraphEdge, GraphInvoke, GraphNode, LangGraph


class CounterState(TypedDict):
    value: int


@GraphEdge("increment", "double")
@LangGraph(state_schema=CounterState, name="annotated_counter")
class CounterWorkflow:
    @GraphNode(entry=True)
    def increment(self, state: CounterState):
        return {"value": state["value"] + 1}

    @GraphNode(end=True)
    def double(self, state: CounterState):
        return {"value": state["value"] * 2}

    @GraphInvoke
    def run(self, input_state: CounterState, thread_id: str):
        """The annotation executes the graph; this body is not called."""
        raise NotImplementedError


if __name__ == "__main__":
    print(CounterWorkflow().run({"value": 2}, thread_id="demo-1"))
