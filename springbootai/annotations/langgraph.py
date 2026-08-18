"""Declarative annotations for the official LangGraph-backed runtime."""

from __future__ import annotations

import functools
import inspect
import threading
from typing import Any, Callable, Mapping, Optional, Type

from springbootai.annotations.core import Component, SpringAnnotation, get_spring_annotations


_BUILD_LOCK = threading.RLock()


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


def _workflow(instance: Any) -> Any:
    workflow = getattr(instance, "_langgraph_workflow", None)
    if workflow is not None:
        return workflow
    from springbootai.langgraph.annotation_runtime import build_langgraph
    with _BUILD_LOCK:
        workflow = getattr(instance, "_langgraph_workflow", None)
        return workflow if workflow is not None else build_langgraph(instance)


def _invocation_arguments(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], input_name: str
) -> tuple[Any, Any, dict[str, Any]]:
    bound = inspect.signature(function).bind(*args, **kwargs)
    bound.apply_defaults()
    instance = bound.arguments.pop("self", None)
    bound.arguments.pop("cls", None)
    arguments = dict(bound.arguments)
    key = input_name or "input_state"
    if key not in arguments:
        raise TypeError(f"GraphInvoke input {key!r} is missing")
    input_state = arguments.pop(key)
    allowed = {"thread_id", "tenant_id", "config"}
    unexpected = set(arguments) - allowed
    if unexpected:
        raise TypeError(
            "GraphInvoke accepts only input_state, thread_id, tenant_id and config; "
            f"unexpected: {', '.join(sorted(unexpected))}"
        )
    return instance, input_state, arguments


class LangGraph(Component):
    """Declare one graph component and its bounded execution policy."""

    _annotation_type = "langgraph"

    def __init__(
        self,
        *,
        state_schema: Type[Any] = dict,
        name: str = "springbootai",
        value: str = "",
        runtime_bean: str = "langGraphRuntime",
        timeout_seconds: Optional[float] = None,
        max_steps: Optional[int] = None,
        checkpointer: str = "",
        allow_in_memory: Optional[bool] = None,
        require_thread_id: Optional[bool] = None,
        max_input_bytes: Optional[int] = None,
        stream_mode: str = "",
    ):
        if not isinstance(state_schema, type):
            raise TypeError("LangGraph state_schema must be a type")
        super().__init__(value=value)
        self.state_schema = state_schema
        self.name = name
        self.runtime_bean = runtime_bean
        self.timeout_seconds = timeout_seconds
        self.max_steps = max_steps
        self.checkpointer = checkpointer
        self.allow_in_memory = allow_in_memory
        self.require_thread_id = require_thread_id
        self.max_input_bytes = max_input_bytes
        self.stream_mode = stream_mode


class GraphNode(SpringAnnotation):
    """Declare a class method as a graph node."""

    _annotation_type = "langgraph_node"

    def __init__(self, name: str = "", *, entry: bool = False, end: bool = False):
        super().__init__(name=name, entry=entry, end=end)


class GraphEdge(SpringAnnotation):
    """Declare an unconditional class-level edge."""

    _annotation_type = "langgraph_edge"

    def __init__(self, source: str, target: str):
        if not source or not target:
            raise ValueError("GraphEdge source and target are required")
        super().__init__(source=source, target=target)


class GraphRoute(SpringAnnotation):
    """Declare a method that chooses a conditional edge for one source node."""

    _annotation_type = "langgraph_route"

    def __init__(self, source: str, paths: Mapping[Any, str]):
        if not source or not paths:
            raise ValueError("GraphRoute source and paths are required")
        super().__init__(source=source, paths=dict(paths))


class GraphInvoke(SpringAnnotation):
    """Make a placeholder method execute the graph built from its class."""

    _annotation_type = "langgraph_invoke"

    def __new__(cls, *args: Any, **kwargs: Any):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            function = args[0]
            instance = object.__new__(cls)
            instance.__init__()
            return instance(function)
        return object.__new__(cls)

    def __init__(self, input_name: str = "input_state"):
        super().__init__(input_name=input_name)

    def __call__(self, function: Callable[..., Any]) -> Callable[..., Any]:
        if not callable(function):
            raise TypeError("GraphInvoke can decorate only a callable")

        if inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, input_state, options = _invocation_arguments(
                    function, args, kwargs, self.input_name
                )
                return await _workflow(instance).ainvoke(input_state, **options)

            wrapper = async_wrapper
        else:

            @functools.wraps(function)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, input_state, options = _invocation_arguments(
                    function, args, kwargs, self.input_name
                )
                return _workflow(instance).invoke(input_state, **options)

            wrapper = sync_wrapper

        wrapper.__spring_annotations__ = list(
            getattr(function, "__dict__", {}).get("__spring_annotations__", [])
        ) + [self]
        self._original_class = function
        return wrapper


__all__ = ["GraphEdge", "GraphInvoke", "GraphNode", "GraphRoute", "LangGraph"]
