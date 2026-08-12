"""Build a LangGraph workflow from Spring-style annotation metadata."""

from __future__ import annotations

import inspect
from typing import Any

from spring.annotations.core import get_spring_annotations
from spring.annotations.langgraph import GraphEdge, GraphNode, GraphRoute, LangGraph
from spring.context.registry import BeanRegistry
from spring.langgraph.config import LangGraphConfigurationError, LangGraphProperties
from spring.langgraph.runtime import LangGraphRuntime, LangGraphWorkflow, _load_graph_api


def _class_annotation(instance: Any) -> Any:
    target = instance if inspect.isclass(instance) else type(instance)
    return next(
        (
            item
            for item in reversed(get_spring_annotations(target))
            if isinstance(item, LangGraph)
        ),
        None,
    )


def _endpoint(value: Any) -> Any:
    _, START, END = _load_graph_api()
    if value in {"START", "__start__"}:
        return START
    if value in {"END", "__end__"}:
        return END
    return value


def build_langgraph(
    instance: Any,
    *,
    runtime: LangGraphRuntime | None = None,
    checkpointer: Any = None,
) -> LangGraphWorkflow:
    """Build, validate, compile, and attach an annotation-defined workflow."""
    annotation = _class_annotation(instance)
    if annotation is None:
        raise LangGraphConfigurationError("graph component must use @LangGraph")

    if runtime is None:
        runtime = BeanRegistry().get(annotation.runtime_bean)
    if runtime is not None and not isinstance(runtime, LangGraphRuntime):
        raise LangGraphConfigurationError(
            f"bean {annotation.runtime_bean!r} is not a LangGraphRuntime"
        )

    base = runtime.properties if runtime is not None else LangGraphProperties()
    properties = LangGraphProperties(
        enabled=True,
        name=annotation.name or base.name,
        timeout_seconds=(
            annotation.timeout_seconds
            if annotation.timeout_seconds is not None
            else base.timeout_seconds
        ),
        max_steps=annotation.max_steps if annotation.max_steps is not None else base.max_steps,
        checkpointer=annotation.checkpointer or base.checkpointer,
        allow_in_memory=(
            annotation.allow_in_memory
            if annotation.allow_in_memory is not None
            else base.allow_in_memory
        ),
        require_thread_id=(
            annotation.require_thread_id
            if annotation.require_thread_id is not None
            else base.require_thread_id
        ),
        max_input_bytes=(
            annotation.max_input_bytes
            if annotation.max_input_bytes is not None
            else base.max_input_bytes
        ),
        stream_mode=annotation.stream_mode or base.stream_mode,
    ).validate()
    selected_checkpointer = checkpointer
    if selected_checkpointer is None and runtime is not None:
        selected_checkpointer = runtime.checkpointer
    workflow = LangGraphWorkflow(
        properties,
        state_schema=annotation.state_schema,
        checkpointer=selected_checkpointer,
    )

    nodes: dict[str, tuple[Any, GraphNode]] = {}
    routes: list[tuple[Any, GraphRoute]] = []
    for method_name, function in inspect.getmembers(type(instance), predicate=inspect.isfunction):
        for item in get_spring_annotations(function):
            if isinstance(item, GraphNode):
                node_name = item.name or method_name
                if node_name in nodes:
                    raise LangGraphConfigurationError(f"duplicate graph node: {node_name}")
                nodes[node_name] = (getattr(instance, method_name), item)
            elif isinstance(item, GraphRoute):
                routes.append((getattr(instance, method_name), item))

    if not nodes:
        raise LangGraphConfigurationError("@LangGraph component must declare @GraphNode")
    entries = [name for name, (_, item) in nodes.items() if item.entry]
    if len(entries) != 1:
        raise LangGraphConfigurationError(
            "@LangGraph component must declare exactly one entry @GraphNode"
        )

    for node_name, (action, _) in nodes.items():
        workflow.add_node(node_name, action)
    workflow.set_entry_point(entries[0])

    for item in get_spring_annotations(type(instance)):
        if isinstance(item, GraphEdge):
            workflow.add_edge(_endpoint(item.source), _endpoint(item.target))
    for node_name, (_, item) in nodes.items():
        if item.end:
            workflow.add_edge(node_name, _endpoint("END"))
    for route, item in routes:
        workflow.add_conditional_edges(
            item.source,
            route,
            {key: _endpoint(target) for key, target in item.paths.items()},
        )

    workflow.compile()
    instance._langgraph_workflow = workflow
    return workflow


class LangGraphAnnotationRuntime:
    """Facade for application bootstrap and explicit testing."""

    @staticmethod
    def build(
        instance: Any,
        *,
        runtime: LangGraphRuntime | None = None,
        checkpointer: Any = None,
    ) -> LangGraphWorkflow:
        return build_langgraph(
            instance,
            runtime=runtime,
            checkpointer=checkpointer,
        )


__all__ = ["LangGraphAnnotationRuntime", "build_langgraph"]
