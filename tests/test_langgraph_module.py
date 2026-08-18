"""Real LangGraph integration tests for the optional SpringBootAI wrapper."""

from __future__ import annotations

import asyncio
from typing import TypedDict

import pytest

pytest.importorskip("langgraph")

from langgraph.graph import END
from langgraph.types import interrupt

from springbootai.context.registry import BeanRegistry
from springbootai.langgraph import (
    LangGraphConfigurationError,
    LangGraphProperties,
    LangGraphWorkflow,
    bind_langgraph_config,
    configure_langgraph,
    open_sqlite_checkpointer,
)


class State(TypedDict, total=False):
    value: int
    path: str
    approved: bool


def _workflow(*, checkpointer: str = "none", allow_in_memory: bool = False) -> LangGraphWorkflow:
    return LangGraphWorkflow(
        LangGraphProperties(
            enabled=True,
            name="test_graph",
            checkpointer=checkpointer,
            allow_in_memory=allow_in_memory,
            max_steps=8,
        ),
        state_schema=State,
    )


def test_config_binding_and_fail_closed_memory_default():
    props = bind_langgraph_config({"enabled": "true", "max-steps": "9"})
    assert props.enabled is True
    assert props.max_steps == 9
    with pytest.raises(LangGraphConfigurationError, match="in-memory"):
        LangGraphProperties(enabled=True, checkpointer="memory").validate()


def test_sync_graph_and_recursion_limit():
    graph = _workflow()
    graph.add_node("inc", lambda state: {"value": state["value"] + 1})
    graph.set_entry_point("inc").add_edge("inc", END)
    assert graph.invoke({"value": 1}, thread_id="t-sync") ["value"] == 2
    with pytest.raises(LangGraphConfigurationError, match="thread_id"):
        graph.invoke({"value": 1})


def test_conditional_route():
    graph = _workflow()
    graph.add_node("route", lambda state: {"path": "high" if state["value"] > 5 else "low"})
    graph.add_node("high", lambda state: {"value": 100})
    graph.add_node("low", lambda state: {"value": 10})
    graph.set_entry_point("route")
    graph.add_conditional_edges("route", lambda state: state["path"], {"high": "high", "low": "low"})
    graph.add_edge("high", END).add_edge("low", END)
    assert graph.invoke({"value": 7}, thread_id="t-high")["value"] == 100
    assert graph.invoke({"value": 1}, thread_id="t-low")["value"] == 10


def test_async_invoke_and_stream():
    graph = _workflow()
    graph.add_node("inc", lambda state: {"value": state["value"] + 1})
    graph.set_entry_point("inc").add_edge("inc", END)

    async def run():
        result = await graph.ainvoke({"value": 4}, thread_id="t-async")
        updates = [item async for item in graph.astream({"value": 4}, thread_id="t-stream")]
        return result, updates

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result, updates = loop.run_until_complete(run())
    finally:
        loop.close()
        # Existing project tests use get_event_loop(); leave them a usable loop.
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert result["value"] == 5
    assert updates


def test_interrupt_requires_checkpoint_and_can_resume():
    graph = _workflow(checkpointer="memory", allow_in_memory=True)
    graph.add_node("approve", lambda state: {"approved": bool(interrupt("approve?"))})
    graph.set_entry_point("approve").add_edge("approve", END)
    with pytest.raises(LangGraphConfigurationError, match="tenant_id"):
        graph.invoke({}, thread_id="t-review")
    paused = graph.invoke({}, thread_id="t-review", tenant_id="tenant-a")
    assert paused.get("__interrupt__")
    resumed = graph.resume(thread_id="t-review", tenant_id="tenant-a", resume_value=True)
    assert resumed["approved"] is True


def test_sqlite_checkpoint_survives_connection_restart(tmp_path):
    database = tmp_path / "langgraph-checkpoints.sqlite"

    def build(checkpointer):
        graph = LangGraphWorkflow(
            LangGraphProperties(
                enabled=True,
                name="persistent_graph",
                checkpointer="injected",
                max_steps=8,
            ),
            state_schema=State,
            checkpointer=checkpointer,
        )
        graph.add_node("approve", lambda state: {"approved": bool(interrupt("approve?"))})
        graph.set_entry_point("approve").add_edge("approve", END)
        return graph

    with open_sqlite_checkpointer(database) as saver:
        paused = build(saver).invoke(
            {}, thread_id="order-restart-1", tenant_id="tenant-a"
        )
        assert paused.get("__interrupt__")
        assert saver.serde.pickle_fallback is False
        assert saver.serde._allowed_msgpack_modules is None

    # A new connection represents a worker/process restart. The same tenant
    # namespace and thread id must resume the durable checkpoint.
    with open_sqlite_checkpointer(database) as saver:
        resumed = build(saver).resume(
            thread_id="order-restart-1",
            tenant_id="tenant-a",
            resume_value=True,
        )
        assert resumed["approved"] is True


def test_autoconfig_is_disabled_by_default_and_reuses_ai_model():
    registry = BeanRegistry()
    registry.clear()
    assert configure_langgraph(registry=registry, config={"spring": {"langgraph": {}}}) == {}
    beans = configure_langgraph(
        registry=registry,
        config={"spring": {"langgraph": {"enabled": True}}},
        model=object(),
    )
    assert beans["langGraphRuntime"].model is not None
