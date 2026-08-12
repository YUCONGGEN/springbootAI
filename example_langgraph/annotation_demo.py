"""Runnable annotation-driven LangGraph example without an API key."""

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
