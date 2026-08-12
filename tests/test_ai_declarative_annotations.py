"""Behavior tests for LangChain and LangGraph executable annotations."""

from __future__ import annotations

import asyncio
from typing import TypedDict

import pytest

from spring.langchain import LangChainCall, LangChainClient, bind_langchain_client


def _run(coroutine):
    """Run one coroutine without leaving older tests without a current loop."""
    try:
        return asyncio.run(coroutine)
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())


class FakeChainService:
    def __init__(self):
        self.calls = []

    def run_llm_chain(self, prompt, **inputs):
        self.calls.append(("chain", prompt, inputs))
        return prompt.format(**inputs)

    def run_conversation(self, user_input, memory=None):
        self.calls.append(("conversation", user_input, memory))
        return f"answer:{user_input}"

    def run_summarize(self, texts):
        self.calls.append(("summarize", texts))
        return " | ".join(texts)


class FakeAgentService:
    def __init__(self):
        self.calls = []

    def run_agent(self, tools, user_input, agent_type="react"):
        self.calls.append((tools, user_input, agent_type))
        return f"agent:{user_input}"


def test_langchain_annotations_delegate_all_modes_and_preserve_defaults():
    @LangChainClient
    class Assistant:
        @LangChainCall("Translate {text} to {language}")
        def translate(self, text: str, language: str = "Chinese") -> str:
            raise AssertionError("placeholder body must not execute")

        @LangChainCall(mode="conversation", input_name="question")
        def chat(self, question: str) -> str:
            raise AssertionError("placeholder body must not execute")

        @LangChainCall(mode="summarize", input_name="documents")
        def summarize(self, documents: list[str]) -> str:
            raise AssertionError("placeholder body must not execute")

        @LangChainCall(mode="agent", input_name="task", tools_bean="safeTools")
        def act(self, task: str) -> str:
            raise AssertionError("placeholder body must not execute")

    chains = FakeChainService()
    agents = FakeAgentService()
    safe_tools = [object()]
    service = bind_langchain_client(
        Assistant(),
        chain_service=chains,
        agent_service=agents,
        tools=safe_tools,
    )

    assert service.translate("hello") == "Translate hello to Chinese"
    assert service.chat("status?") == "answer:status?"
    assert service.summarize(["a", "b"]) == "a | b"
    assert service.act("calculate") == "agent:calculate"
    assert agents.calls == [(safe_tools, "calculate", "react")]


def test_async_langchain_annotation_moves_synchronous_service_off_event_loop():
    @LangChainClient
    class Assistant:
        @LangChainCall("Hello {name}")
        async def greet(self, name: str) -> str:
            raise AssertionError("placeholder body must not execute")

    service = bind_langchain_client(Assistant(), chain_service=FakeChainService())
    assert _run(service.greet("Alice")) == "Hello Alice"


def test_langchain_agent_requires_preconfigured_tools():
    with pytest.raises(ValueError, match="tools_bean"):
        LangChainCall(mode="agent")


def test_langchain_annotation_rejects_oversized_or_invalid_summary_input():
    @LangChainClient
    class Assistant:
        @LangChainCall("Echo {text}", max_input_bytes=1024)
        def echo(self, text: str) -> str:
            raise NotImplementedError

        @LangChainCall(mode="summarize")
        def summarize(self, texts: list[str]) -> str:
            raise NotImplementedError

    service = bind_langchain_client(Assistant(), chain_service=FakeChainService())
    with pytest.raises(ValueError, match="exceeds"):
        service.echo("x" * 1100)
    with pytest.raises(TypeError, match="list of strings"):
        service.summarize("not-a-list")


pytest.importorskip("langgraph")

from spring.langgraph import (  # noqa: E402
    GraphEdge,
    GraphInvoke,
    GraphNode,
    GraphRoute,
    LangGraph,
    LangGraphConfigurationError,
    build_langgraph,
    LangGraphProperties,
    LangGraphRuntime,
)


class FlowState(TypedDict, total=False):
    value: int
    path: str


def test_langgraph_annotations_build_and_directly_invoke_workflow():
    @GraphEdge("increment", "finish")
    @LangGraph(state_schema=FlowState, name="annotation_linear")
    class LinearFlow:
        @GraphNode(entry=True)
        def increment(self, state: FlowState):
            return {"value": state["value"] + 1}

        @GraphNode(end=True)
        def finish(self, state: FlowState):
            return {"value": state["value"] * 2}

        @GraphInvoke
        def run(self, input_state: FlowState, thread_id: str):
            raise AssertionError("placeholder body must not execute")

        @GraphInvoke
        async def arun(self, input_state: FlowState, thread_id: str):
            raise AssertionError("placeholder body must not execute")

    flow = LinearFlow()
    assert flow.run({"value": 2}, "linear-sync")["value"] == 6
    assert _run(flow.arun({"value": 3}, "linear-async"))["value"] == 8
    assert flow._langgraph_workflow.name == "annotation_linear"


def test_langgraph_conditional_route_annotation():
    @LangGraph(state_schema=FlowState, name="annotation_route")
    class RoutedFlow:
        @GraphNode(entry=True)
        def choose(self, state: FlowState):
            return {"path": "high" if state["value"] > 5 else "low"}

        @GraphRoute("choose", {"high": "high", "low": "low"})
        def route(self, state: FlowState):
            return state["path"]

        @GraphNode(end=True)
        def high(self, state: FlowState):
            return {"value": 100}

        @GraphNode(end=True)
        def low(self, state: FlowState):
            return {"value": 10}

    graph = build_langgraph(RoutedFlow())
    assert graph.invoke({"value": 8}, thread_id="route-high")["value"] == 100
    assert graph.invoke({"value": 1}, thread_id="route-low")["value"] == 10


def test_langgraph_annotation_requires_exactly_one_entry_node():
    @LangGraph(state_schema=FlowState, name="invalid_annotation")
    class InvalidFlow:
        @GraphNode
        def only(self, state: FlowState):
            return state

    with pytest.raises(LangGraphConfigurationError, match="exactly one entry"):
        build_langgraph(InvalidFlow())


def test_langgraph_annotation_inherits_runtime_safety_properties():
    runtime = LangGraphRuntime(
        LangGraphProperties(
            enabled=True,
            name="global",
            timeout_seconds=7,
            max_steps=6,
            max_input_bytes=2048,
            require_thread_id=True,
        )
    )

    @LangGraph(state_schema=FlowState, name="inherited")
    class InheritedFlow:
        @GraphNode(entry=True, end=True)
        def only(self, state: FlowState):
            return state

    workflow = build_langgraph(InheritedFlow(), runtime=runtime)
    assert workflow.properties.timeout_seconds == 7
    assert workflow.properties.max_steps == 6
    assert workflow.properties.max_input_bytes == 2048
