"""Comprehensive tests for SpringBootAI LangGraph module.

Covers:
- LangGraphProperties validation (all bounds, edge cases)
- LangGraphWorkflow construction and validation (node names, edges, conditionals)
- Input validation (JSON serializable, size limits)
- Thread/tenant ID validation (length, requirement)
- Timeout handling
- Error propagation
- LangGraphRuntime (call_model, acall_model)
- build_langgraph annotation validation
- Annotation classes (LangGraph, GraphNode, GraphEdge, GraphRoute, GraphInvoke)
- bind_langgraph_config (env vars, kebab-case)
"""

from __future__ import annotations

import asyncio
from typing import TypedDict

import pytest

pytest.importorskip("langgraph")

from langgraph.graph import END

from spring.context.registry import BeanRegistry
from spring.langgraph.config import (
    LangGraphConfigurationError,
    LangGraphProperties,
    bind_langgraph_config,
    _bool,
    _int,
    _float,
    _value,
)
from spring.langgraph.runtime import (
    LangGraphRuntime,
    LangGraphWorkflow,
)
from spring.langgraph.annotations import (
    GraphEdge,
    GraphInvoke,
    GraphNode,
    GraphRoute,
    LangGraph,
)
from spring.langgraph.annotation_runtime import (
    LangGraphAnnotationRuntime,
    build_langgraph,
)
from spring.langgraph.autoconfig import configure_langgraph


# ============================================================
# Helpers
# ============================================================

class SimpleState(TypedDict, total=False):
    value: int
    path: str


def _workflow(**kwargs) -> LangGraphWorkflow:
    defaults = dict(
        enabled=True,
        name="test_graph",
        max_steps=8,
    )
    defaults.update(kwargs)
    return LangGraphWorkflow(
        LangGraphProperties(**defaults),
        state_schema=SimpleState,
    )


# ============================================================
# LangGraphProperties 验证测试
# ============================================================

class TestLangGraphPropertiesValidation:
    def test_valid_defaults(self):
        props = LangGraphProperties(enabled=True).validate()
        assert props.enabled is True
        assert props.name == "springbootai"
        assert props.timeout_seconds == 60.0
        assert props.max_steps == 25
        assert props.checkpointer == "none"
        assert props.require_thread_id is True

    def test_name_too_long(self):
        with pytest.raises(LangGraphConfigurationError, match="name"):
            LangGraphProperties(enabled=True, name="x" * 129).validate()

    def test_name_empty(self):
        with pytest.raises(LangGraphConfigurationError, match="name"):
            LangGraphProperties(enabled=True, name="").validate()

    def test_timeout_zero(self):
        with pytest.raises(LangGraphConfigurationError, match="timeout"):
            LangGraphProperties(enabled=True, timeout_seconds=0).validate()

    def test_timeout_negative(self):
        with pytest.raises(LangGraphConfigurationError, match="timeout"):
            LangGraphProperties(enabled=True, timeout_seconds=-1).validate()

    def test_timeout_too_large(self):
        with pytest.raises(LangGraphConfigurationError, match="timeout"):
            LangGraphProperties(enabled=True, timeout_seconds=601).validate()

    def test_timeout_boundary_max(self):
        props = LangGraphProperties(enabled=True, timeout_seconds=600).validate()
        assert props.timeout_seconds == 600

    def test_max_steps_zero(self):
        with pytest.raises(LangGraphConfigurationError, match="max_steps"):
            LangGraphProperties(enabled=True, max_steps=0).validate()

    def test_max_steps_negative(self):
        with pytest.raises(LangGraphConfigurationError, match="max_steps"):
            LangGraphProperties(enabled=True, max_steps=-5).validate()

    def test_max_steps_too_large(self):
        with pytest.raises(LangGraphConfigurationError, match="max_steps"):
            LangGraphProperties(enabled=True, max_steps=1001).validate()

    def test_max_steps_boundary(self):
        props = LangGraphProperties(enabled=True, max_steps=1).validate()
        assert props.max_steps == 1
        props = LangGraphProperties(enabled=True, max_steps=1000).validate()
        assert props.max_steps == 1000

    def test_checkpointer_invalid(self):
        with pytest.raises(LangGraphConfigurationError, match="checkpointer"):
            LangGraphProperties(enabled=True, checkpointer="redis").validate()

    def test_checkpointer_memory_without_allow(self):
        with pytest.raises(LangGraphConfigurationError, match="in-memory"):
            LangGraphProperties(enabled=True, checkpointer="memory").validate()

    def test_checkpointer_memory_with_allow(self):
        props = LangGraphProperties(
            enabled=True, checkpointer="memory", allow_in_memory=True
        ).validate()
        assert props.checkpointer == "memory"

    def test_checkpointer_injected(self):
        props = LangGraphProperties(
            enabled=True, checkpointer="injected"
        ).validate()
        assert props.checkpointer == "injected"

    def test_max_input_bytes_too_small(self):
        with pytest.raises(LangGraphConfigurationError, match="max_input_bytes"):
            LangGraphProperties(enabled=True, max_input_bytes=100).validate()

    def test_max_input_bytes_too_large(self):
        with pytest.raises(LangGraphConfigurationError, match="max_input_bytes"):
            LangGraphProperties(enabled=True, max_input_bytes=20 * 1024 * 1024).validate()

    def test_max_input_bytes_boundary(self):
        props = LangGraphProperties(enabled=True, max_input_bytes=1024).validate()
        assert props.max_input_bytes == 1024
        props = LangGraphProperties(enabled=True, max_input_bytes=10 * 1024 * 1024).validate()
        assert props.max_input_bytes == 10 * 1024 * 1024

    def test_stream_mode_invalid(self):
        with pytest.raises(LangGraphConfigurationError, match="stream_mode"):
            LangGraphProperties(enabled=True, stream_mode="invalid").validate()

    def test_stream_mode_valid(self):
        for mode in ["values", "updates", "messages", "debug", "custom"]:
            props = LangGraphProperties(enabled=True, stream_mode=mode).validate()
            assert props.stream_mode == mode


# ============================================================
# bind_langgraph_config 测试
# ============================================================

class TestBindLangGraphConfig:
    def test_basic_binding(self):
        props = bind_langgraph_config({
            "enabled": "true",
            "name": "my_graph",
            "timeout-seconds": "30",
            "max-steps": "10",
            "checkpointer": "none",
            "require-thread-id": "false",
            "stream-mode": "values",
        })
        assert props.enabled is True
        assert props.name == "my_graph"
        assert props.timeout_seconds == 30.0
        assert props.max_steps == 10
        assert props.require_thread_id is False
        assert props.stream_mode == "values"

    def test_defaults(self):
        props = bind_langgraph_config({})
        assert props.enabled is False
        assert props.name == "springbootai"
        assert props.timeout_seconds == 60.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LG_ENABLED", "true")
        monkeypatch.setenv("LG_NAME", "env_graph")
        monkeypatch.setenv("LG_MAX_STEPS", "50")
        props = bind_langgraph_config({"enabled": "false", "name": "dict_graph", "max-steps": "5"})
        assert props.enabled is True
        assert props.name == "env_graph"
        assert props.max_steps == 50

    def test_bool_values(self):
        assert _bool("true") is True
        assert _bool("false") is False
        assert _bool("yes") is True
        assert _bool("on") is True
        assert _bool("1") is True
        assert _bool(True) is True
        assert _bool(False) is False
        assert _bool(None, default=True) is True

    def test_int_values(self):
        assert _int("42", 0) == 42
        assert _int("not-a-number", 10) == 10
        assert _int(None, 5) == 5

    def test_float_values(self):
        assert _float("3.14", 0) == 3.14
        assert _float("abc", 99.9) == 99.9
        assert _float(None, 1.5) == 1.5

    def test_value_lookup(self):
        data = {"key_one": "val1", "key-two": "val2"}
        assert _value(data, "key_one") == "val1"
        assert _value(data, "key_two") == "val2"
        assert _value(data, "missing", default="def") == "def"


# ============================================================
# LangGraphWorkflow 构建与验证测试
# ============================================================

class TestWorkflowConstruction:
    def test_valid_node_name(self):
        g = _workflow()
        g.add_node("validNode", lambda s: s)
        g.add_node("node-1", lambda s: s)
        g.add_node("node_2", lambda s: s)

    def test_invalid_node_name_startswith_digit(self):
        g = _workflow()
        with pytest.raises(LangGraphConfigurationError, match="invalid graph node name"):
            g.add_node("1invalid", lambda s: s)

    def test_invalid_node_name_special_chars(self):
        g = _workflow()
        with pytest.raises(LangGraphConfigurationError, match="invalid graph node name"):
            g.add_node("invalid node", lambda s: s)

    def test_invalid_node_name_too_long(self):
        g = _workflow()
        with pytest.raises(LangGraphConfigurationError, match="invalid graph node name"):
            g.add_node("a" * 65, lambda s: s)

    def test_node_not_callable(self):
        g = _workflow()
        with pytest.raises(TypeError, match="callable"):
            g.add_node("bad_node", "not a function")

    def test_duplicate_node(self):
        g = _workflow()
        g.add_node("node1", lambda s: s)
        with pytest.raises(LangGraphConfigurationError, match="duplicate"):
            g.add_node("node1", lambda s: s)

    def test_invalid_graph_name(self):
        with pytest.raises(LangGraphConfigurationError, match="unsupported"):
            LangGraphWorkflow(
                LangGraphProperties(enabled=True, name="invalid name!"),
                state_schema=SimpleState,
            )

    def test_unknown_edge_source(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        with pytest.raises(LangGraphConfigurationError, match="unknown graph node"):
            g.add_edge("nonexistent", "a")

    def test_unknown_edge_target(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        with pytest.raises(LangGraphConfigurationError, match="unknown graph node"):
            g.add_edge("a", "nonexistent")

    def test_valid_edge(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.add_node("b", lambda s: s)
        g.add_edge("a", "b")

    def test_set_entry_point(self):
        g = _workflow()
        g.add_node("start", lambda s: s)
        g.set_entry_point("start")

    def test_conditional_edges_unknown_source(self):
        g = _workflow()
        with pytest.raises(LangGraphConfigurationError, match="unknown graph node"):
            g.add_conditional_edges("nonexistent", lambda s: "a", {"a": "b"})

    def test_conditional_edges_unknown_target(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.add_node("b", lambda s: s)
        with pytest.raises(LangGraphConfigurationError, match="unknown conditional target"):
            g.add_conditional_edges("a", lambda s: "c", {"c": "nonexistent"})

    def test_conditional_edges_valid(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.add_node("b", lambda s: s)
        g.add_node("c", lambda s: s)
        g.add_conditional_edges("a", lambda s: "b", {"b": "b", "c": "c"})

    def test_conditional_edges_to_end(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.add_node("b", lambda s: s)
        g.add_conditional_edges("a", lambda s: "end", {"end": "__end__", "b": "b"})

    def test_compile_with_debug(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        compiled = g.compile(debug=True)
        assert compiled is not None

    def test_compile_cached(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        c1 = g.compile()
        c2 = g.compile()
        assert c1 is c2

    def test_compile_injected_checkpointer_missing(self):
        g = LangGraphWorkflow(
            LangGraphProperties(
                enabled=True, name="test", checkpointer="injected"
            ),
            state_schema=SimpleState,
        )
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="checkpointer"):
            g.compile()


# ============================================================
# 输入验证测试
# ============================================================

class TestInputValidation:
    def test_invoke_non_serializable(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")

        class BadStr:
            def __str__(self):
                raise TypeError("cannot stringify")
        with pytest.raises(LangGraphConfigurationError, match="JSON serializable"):
            g.invoke({"key": BadStr()}, thread_id="t1")

    def test_invoke_oversized_input(self):
        g = _workflow(max_input_bytes=2048)
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        big_input = {"data": "x" * 5000}
        with pytest.raises(LangGraphConfigurationError, match="exceeds"):
            g.invoke(big_input, thread_id="t1")

    def test_invoke_valid_input(self):
        g = _workflow()
        g.add_node("a", lambda s: {"value": s.get("value", 0) + 1})
        g.set_entry_point("a").add_edge("a", END)
        result = g.invoke({"value": 5}, thread_id="t1")
        assert result["value"] == 6


# ============================================================
# Thread/Tenant ID 验证测试
# ============================================================

class TestThreadTenantValidation:
    def test_thread_id_required(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="thread_id"):
            g.invoke({"value": 1})

    def test_thread_id_too_long(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="thread_id.*too long"):
            g.invoke({"value": 1}, thread_id="x" * 257)

    def test_tenant_id_too_long(self):
        g = _workflow(checkpointer="memory", allow_in_memory=True)
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="tenant_id.*too long"):
            g.invoke({"value": 1}, thread_id="t1", tenant_id="x" * 129)

    def test_recursion_limit_not_int(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="recursion_limit"):
            g.invoke({"value": 1}, thread_id="t1", config={"recursion_limit": "abc"})

    def test_recursion_limit_out_of_range(self):
        g = _workflow()
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="recursion_limit"):
            g.invoke({"value": 1}, thread_id="t1", config={"recursion_limit": 0})

    def test_recursion_limit_exceeds_max(self):
        g = _workflow(max_steps=5)
        g.add_node("a", lambda s: s)
        g.set_entry_point("a")
        with pytest.raises(LangGraphConfigurationError, match="recursion_limit"):
            g.invoke({"value": 1}, thread_id="t1", config={"recursion_limit": 10})

    def test_thread_id_optional_with_property(self):
        g = _workflow(require_thread_id=False)
        g.add_node("a", lambda s: s)
        g.set_entry_point("a").add_edge("a", END)
        result = g.invoke({"value": 1})
        assert result["value"] == 1


# ============================================================
# 超时与错误传播测试
# ============================================================

class TestTimeoutAndErrorPropagation:
    def test_node_exception_propagates(self):
        g = _workflow()
        def failing_node(state):
            raise ValueError("node failed!")
        g.add_node("fail", failing_node)
        g.set_entry_point("fail")
        with pytest.raises(ValueError, match="node failed"):
            g.invoke({"value": 1}, thread_id="t1")

    def test_timeout(self):
        g = _workflow(timeout_seconds=0.05)
        def slow_node(state):
            import time
            time.sleep(2)
            return {"value": 42}
        g.add_node("slow", slow_node)
        g.set_entry_point("slow")
        with pytest.raises(TimeoutError):
            g.invoke({"value": 1}, thread_id="t-timeout")


# ============================================================
# 条件路由测试
# ============================================================

class TestConditionalRouting:
    def test_route_high(self):
        g = _workflow()
        g.add_node("start", lambda s: {"path": "high" if s["value"] > 5 else "low"})
        g.add_node("high", lambda s: {"value": 100})
        g.add_node("low", lambda s: {"value": 10})
        g.set_entry_point("start")
        g.add_conditional_edges("start", lambda s: s["path"], {"high": "high", "low": "low"})
        g.add_edge("high", END).add_edge("low", END)
        result = g.invoke({"value": 10}, thread_id="t1")
        assert result["value"] == 100

    def test_route_low(self):
        g = _workflow()
        g.add_node("start", lambda s: {"path": "high" if s["value"] > 5 else "low"})
        g.add_node("high", lambda s: {"value": 100})
        g.add_node("low", lambda s: {"value": 10})
        g.set_entry_point("start")
        g.add_conditional_edges("start", lambda s: s["path"], {"high": "high", "low": "low"})
        g.add_edge("high", END).add_edge("low", END)
        result = g.invoke({"value": 2}, thread_id="t2")
        assert result["value"] == 10


# ============================================================
# Stream 测试
# ============================================================

class TestStreaming:
    def test_sync_stream(self):
        g = _workflow()
        g.add_node("inc", lambda s: {"value": s.get("value", 0) + 1})
        g.set_entry_point("inc").add_edge("inc", END)
        items = list(g.stream({"value": 1}, thread_id="t-stream"))
        assert len(items) > 0

    def test_async_stream(self):
        g = _workflow()
        g.add_node("inc", lambda s: {"value": s.get("value", 0) + 1})
        g.set_entry_point("inc").add_edge("inc", END)

        async def run():
            items = [item async for item in g.astream({"value": 1}, thread_id="t-astream")]
            return items

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            items = loop.run_until_complete(run())
        finally:
            loop.close()
            asyncio.set_event_loop(asyncio.new_event_loop())
        assert len(items) > 0


# ============================================================
# LangGraphRuntime 测试
# ============================================================

class TestLangGraphRuntime:
    def test_workflow_creation(self):
        props = LangGraphProperties(enabled=True, name="rt_test")
        rt = LangGraphRuntime(props)
        wf = rt.workflow(state_schema=SimpleState, name="wf1")
        assert isinstance(wf, LangGraphWorkflow)
        assert wf.name == "wf1"

    def test_call_model_without_model(self):
        props = LangGraphProperties(enabled=True, name="rt_test")
        rt = LangGraphRuntime(props)
        with pytest.raises(LangGraphConfigurationError, match="no AI ChatModel"):
            rt.call_model([])

    def test_acall_model_without_model(self):
        props = LangGraphProperties(enabled=True, name="rt_test")
        rt = LangGraphRuntime(props)
        with pytest.raises(LangGraphConfigurationError, match="no AI ChatModel"):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(rt.acall_model([]))
            finally:
                loop.close()


# ============================================================
# Annotation 类测试
# ============================================================

class TestAnnotations:
    def test_langgraph_annotation_invalid_schema(self):
        with pytest.raises(TypeError, match="state_schema"):
            LangGraph(state_schema="not_a_type")

    def test_langgraph_annotation_valid(self):
        ann = LangGraph(state_schema=dict, name="test_graph")
        assert ann.name == "test_graph"
        assert ann.state_schema is dict

    def test_graph_node_annotation(self):
        node = GraphNode(name="myNode", entry=True)
        assert node.name == "myNode"
        assert node.entry is True

    def test_graph_node_default(self):
        node = GraphNode()
        assert node.name == ""
        assert node.entry is False
        assert node.end is False

    def test_graph_edge_missing_source(self):
        with pytest.raises(ValueError, match="source"):
            GraphEdge(source="", target="b")

    def test_graph_edge_missing_target(self):
        with pytest.raises(ValueError, match="target"):
            GraphEdge(source="a", target="")

    def test_graph_edge_valid(self):
        edge = GraphEdge(source="a", target="b")
        assert edge.source == "a"
        assert edge.target == "b"

    def test_graph_route_missing_source(self):
        with pytest.raises(ValueError, match="source"):
            GraphRoute(source="", paths={"x": "y"})

    def test_graph_route_missing_paths(self):
        with pytest.raises(ValueError, match="paths"):
            GraphRoute(source="a", paths={})

    def test_graph_route_valid(self):
        route = GraphRoute(source="a", paths={"x": "y"})
        assert route.source == "a"
        assert route.paths == {"x": "y"}


# ============================================================
# build_langgraph 注解运行时测试
# ============================================================

class TestBuildLangGraph:
    def test_missing_langgraph_annotation(self):
        class PlainClass:
            pass
        with pytest.raises(LangGraphConfigurationError, match="@LangGraph"):
            build_langgraph(PlainClass())

    def test_missing_graph_node(self):
        @LangGraph(name="test")
        class NoNode:
            pass
        with pytest.raises(LangGraphConfigurationError, match="@GraphNode"):
            build_langgraph(NoNode())

    def test_no_entry_node(self):
        @LangGraph(name="test")
        class NoEntry:
            @GraphNode(name="a")
            def node_a(self, state):
                return state
        with pytest.raises(LangGraphConfigurationError, match="one entry"):
            build_langgraph(NoEntry())

    def test_multiple_entry_nodes(self):
        @LangGraph(name="test")
        class MultiEntry:
            @GraphNode(name="a", entry=True)
            def node_a(self, state):
                return state

            @GraphNode(name="b", entry=True)
            def node_b(self, state):
                return state
        with pytest.raises(LangGraphConfigurationError, match="one entry"):
            build_langgraph(MultiEntry())

    def test_duplicate_node_names(self):
        @LangGraph(name="test")
        class DupNode:
            @GraphNode(name="dup", entry=True)
            def node_a(self, state):
                return state

            @GraphNode(name="dup")
            def node_b(self, state):
                return state
        with pytest.raises(LangGraphConfigurationError, match="duplicate"):
            build_langgraph(DupNode())

    def test_valid_annotation_build(self):
        @LangGraph(name="test")
        class ValidGraph:
            @GraphNode(name="start", entry=True)
            def node_start(self, state):
                return {"value": state.get("value", 0) + 1}

            @GraphNode(name="end", end=True)
            def node_end(self, state):
                return state

        instance = ValidGraph()
        wf = build_langgraph(instance)
        assert wf is not None
        result = wf.invoke({"value": 1}, thread_id="t-ann")
        assert result["value"] == 2


# ============================================================
# GraphInvoke 注解测试
# ============================================================

class TestGraphInvokeAnnotation:
    def test_graph_invoke_decorator(self):
        @LangGraph(name="invoke_test")
        class InvokeGraph:
            @GraphNode(name="start", entry=True)
            def node_start(self, state):
                return {"value": state.get("value", 0) * 2}

            @GraphNode(name="end", end=True)
            def node_end(self, state):
                return state

            @GraphInvoke(input_name="input_state")
            def run(self, input_state, thread_id=None, tenant_id=None, config=None):
                pass

        instance = InvokeGraph()
        build_langgraph(instance)
        result = instance.run({"value": 5}, thread_id="t-gi")
        assert result["value"] == 10

    def test_graph_invoke_async(self):
        @LangGraph(name="async_invoke_test")
        class AsyncInvokeGraph:
            @GraphNode(name="start", entry=True)
            def node_start(self, state):
                return {"value": state.get("value", 0) + 10}

            @GraphNode(name="end", end=True)
            def node_end(self, state):
                return state

            @GraphInvoke(input_name="input_state")
            async def run_async(self, input_state, thread_id=None, tenant_id=None, config=None):
                pass

        instance = AsyncInvokeGraph()
        build_langgraph(instance)

        async def do_run():
            return await instance.run_async({"value": 5}, thread_id="t-async-gi")

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(do_run())
        finally:
            loop.close()
            asyncio.set_event_loop(asyncio.new_event_loop())
        assert result["value"] == 15

    def test_graph_invoke_unexpected_arg(self):
        @LangGraph(name="bad_invoke")
        class BadInvokeGraph:
            @GraphNode(name="start", entry=True)
            def node_start(self, state):
                return state

            @GraphNode(name="end", end=True)
            def node_end(self, state):
                return state

            @GraphInvoke(input_name="input_state")
            def run(self, input_state, extra_arg):
                pass

        instance = BadInvokeGraph()
        build_langgraph(instance)
        with pytest.raises(TypeError, match="unexpected"):
            instance.run({"value": 1}, extra_arg="oops")


# ============================================================
# 带检查点的图测试
# ============================================================

class TestWorkflowWithCheckpointer:
    def test_invoke_with_memory_checkpointer(self):
        g = _workflow(checkpointer="memory", allow_in_memory=True)
        g.add_node("inc", lambda s: {"value": s.get("value", 0) + 1})
        g.set_entry_point("inc").add_edge("inc", END)
        result = g.invoke({"value": 1}, thread_id="t1", tenant_id="tenant-a")
        assert result["value"] == 2

    def test_state_retrieval(self):
        g = _workflow(checkpointer="memory", allow_in_memory=True)
        g.add_node("inc", lambda s: {"value": s.get("value", 0) + 10})
        g.set_entry_point("inc").add_edge("inc", END)
        g.invoke({"value": 1}, thread_id="t-state", tenant_id="tenant-a")
        config = {"configurable": {"thread_id": "t-state"}}
        state = g.compile().get_state(config)
        assert state is not None


# ============================================================
# LangGraphAnnotationRuntime 门面测试
# ============================================================

class TestLangGraphAnnotationRuntime:
    def test_build_facade(self):
        @LangGraph(name="facade_test")
        class FacadeGraph:
            @GraphNode(name="start", entry=True)
            def node_start(self, state):
                return {"value": state.get("value", 0) + 1}

            @GraphNode(name="end", end=True)
            def node_end(self, state):
                return state

        instance = FacadeGraph()
        wf = LangGraphAnnotationRuntime.build(instance)
        assert wf is not None
        result = wf.invoke({"value": 10}, thread_id="t-facade")
        assert result["value"] == 11


# ============================================================
# configure_langgraph 集成测试
# ============================================================

class TestConfigureLanggraph:
    def test_disabled_by_default(self):
        registry = BeanRegistry()
        registry.clear()
        beans = configure_langgraph(registry=registry)
        assert beans == {}

    def test_enabled_creates_runtime(self):
        registry = BeanRegistry()
        registry.clear()
        beans = configure_langgraph(
            registry=registry,
            config={"spring": {"langgraph": {"enabled": True}}},
            model=object(),
        )
        assert "langGraphRuntime" in beans
        assert "langGraphProperties" in beans
        assert beans["langGraphRuntime"].model is not None

    def test_enabled_without_model(self):
        registry = BeanRegistry()
        registry.clear()
        beans = configure_langgraph(
            registry=registry,
            config={"spring": {"langgraph": {"enabled": True}}},
        )
        assert beans["langGraphRuntime"].model is None


# ============================================================
# 多节点工作流测试
# ============================================================

class TestMultiNodeWorkflow:
    def test_three_node_pipeline(self):
        g = _workflow()
        g.add_node("step1", lambda s: {"value": s.get("value", 0) + 1})
        g.add_node("step2", lambda s: {"value": s["value"] * 2})
        g.add_node("step3", lambda s: {"value": s["value"] - 3})
        g.set_entry_point("step1")
        g.add_edge("step1", "step2")
        g.add_edge("step2", "step3")
        g.add_edge("step3", END)
        result = g.invoke({"value": 0}, thread_id="t-pipeline")
        assert result["value"] == -1  # (0+1)*2-3 = -1

    def test_fan_out_conditional(self):
        g = _workflow()
        g.add_node("check", lambda s: {"path": "a" if s.get("value", 0) > 5 else "b"})
        g.add_node("path_a", lambda s: {"value": 100})
        g.add_node("path_b", lambda s: {"value": 0})
        g.set_entry_point("check")
        g.add_conditional_edges("check", lambda s: s["path"], {"a": "path_a", "b": "path_b"})
        g.add_edge("path_a", END).add_edge("path_b", END)
        assert g.invoke({"value": 10}, thread_id="t-fan1")["value"] == 100
        assert g.invoke({"value": 3}, thread_id="t-fan2")["value"] == 0
