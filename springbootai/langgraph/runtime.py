"""Safe, small Spring-style wrapper around the official LangGraph runtime.

This module intentionally does not reimplement a graph engine.  It validates
request boundaries and delegates graph execution to ``langgraph``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any, AsyncIterator, Callable, Dict, Generator, Hashable, Mapping, Optional, Type

from springbootai.langgraph.config import LangGraphConfigurationError, LangGraphProperties

logger = logging.getLogger("Spring.LangGraph")
_NODE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


class LangGraphUnavailableError(ImportError):
    """Raised when the optional ``langgraph`` dependency is not installed."""


def _load_graph_api():
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised without extra installed
        raise LangGraphUnavailableError(
            "LangGraph is not installed. Install it with "
            "pip install springbootAI[langgraph]"
        ) from exc
    return StateGraph, START, END


def _load_memory_checkpointer():
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as exc:  # pragma: no cover
        raise LangGraphUnavailableError(
            "The LangGraph memory checkpointer is unavailable; reinstall the langgraph extra"
        ) from exc
    return InMemorySaver()


class LangGraphWorkflow:
    """Build and execute one typed state graph.

    Nodes may be synchronous or asynchronous.  Use :meth:`ainvoke` and
    :meth:`astream` from an async web handler so synchronous nodes are executed
    by LangGraph's own executor instead of blocking the event loop.
    """

    def __init__(
        self,
        properties: Optional[LangGraphProperties] = None,
        *,
        state_schema: Type[Any] = dict,
        name: Optional[str] = None,
        checkpointer: Any = None,
    ):
        self.properties = (properties or LangGraphProperties()).validate()
        self.name = name or self.properties.name
        if not _NODE_NAME.fullmatch(self.name):
            raise LangGraphConfigurationError("graph name contains unsupported characters")
        self.state_schema = state_schema
        self._checkpointer = checkpointer
        self._builder = None
        self._compiled = None
        self._nodes: set[str] = set()
        self._build_graph()

    def _build_graph(self) -> None:
        StateGraph, _, _ = _load_graph_api()
        self._builder = StateGraph(self.state_schema)

    @property
    def compiled(self) -> Any:
        return self.compile()

    def add_node(self, name: str, action: Callable[..., Any], **kwargs: Any) -> "LangGraphWorkflow":
        if not _NODE_NAME.fullmatch(name):
            raise LangGraphConfigurationError(f"invalid graph node name: {name!r}")
        if not callable(action):
            raise TypeError("graph node must be callable")
        if name in self._nodes:
            raise LangGraphConfigurationError(f"duplicate graph node: {name}")
        self._builder.add_node(name, action, **kwargs)
        self._nodes.add(name)
        self._compiled = None
        return self

    def add_edge(self, source: str, target: str) -> "LangGraphWorkflow":
        _, START, END = _load_graph_api()
        if source not in {START, END} and source not in self._nodes:
            raise LangGraphConfigurationError(f"unknown graph node: {source}")
        if target not in {START, END} and target not in self._nodes:
            raise LangGraphConfigurationError(f"unknown graph node: {target}")
        self._builder.add_edge(source, target)
        self._compiled = None
        return self

    def add_conditional_edges(
        self,
        source: str,
        route: Callable[..., Any],
        path_map: Optional[Mapping[Hashable, str]] = None,
    ) -> "LangGraphWorkflow":
        if source not in self._nodes:
            raise LangGraphConfigurationError(f"unknown graph node: {source}")
        if path_map:
            for target in path_map.values():
                if target not in self._nodes and target != "__end__":
                    raise LangGraphConfigurationError(f"unknown conditional target: {target}")
        self._builder.add_conditional_edges(source, route, dict(path_map) if path_map else None)
        self._compiled = None
        return self

    def set_entry_point(self, node: str) -> "LangGraphWorkflow":
        _, START, _ = _load_graph_api()
        return self.add_edge(START, node)

    def compile(self, *, checkpointer: Any = None, debug: bool = False) -> Any:
        if self._compiled is not None and checkpointer is None:
            return self._compiled
        selected = checkpointer if checkpointer is not None else self._checkpointer
        if selected is None and self.properties.checkpointer == "memory":
            selected = _load_memory_checkpointer()
        if self.properties.checkpointer == "injected" and selected is None:
            raise LangGraphConfigurationError(
                "checkpointer=injected requires a persistent checkpointer instance"
            )
        self._compiled = self._builder.compile(
            checkpointer=selected, debug=debug, name=self.name
        )
        return self._compiled

    def _config(self, *, thread_id: Optional[str], tenant_id: Optional[str], config: Optional[dict]) -> dict:
        result = dict(config or {})
        configurable = dict(result.get("configurable") or {})
        if thread_id:
            configurable["thread_id"] = thread_id
        if tenant_id:
            configurable["tenant_id"] = tenant_id
        if self.properties.require_thread_id and not configurable.get("thread_id"):
            raise LangGraphConfigurationError("thread_id is required for every graph invocation")
        if self.properties.checkpointer != "none" and not configurable.get("tenant_id") and not tenant_id:
            raise LangGraphConfigurationError(
                "tenant_id is required when a checkpointer is enabled to prevent cross-tenant state access"
            )
        if configurable.get("thread_id") and len(str(configurable["thread_id"])) > 256:
            raise LangGraphConfigurationError("thread_id is too long")
        if configurable.get("tenant_id"):
            tenant = str(configurable["tenant_id"])
            if len(tenant) > 128:
                raise LangGraphConfigurationError("tenant_id is too long")
            configurable.setdefault("checkpoint_ns", f"tenant:{tenant}")
        try:
            recursion_limit = int(result.get("recursion_limit", self.properties.max_steps))
        except (TypeError, ValueError) as exc:
            raise LangGraphConfigurationError("recursion_limit must be an integer") from exc
        if recursion_limit < 1 or recursion_limit > self.properties.max_steps:
            raise LangGraphConfigurationError("recursion_limit must be between 1 and max_steps")
        result["recursion_limit"] = recursion_limit
        result["configurable"] = configurable
        return result

    def _validate_input(self, value: Any) -> None:
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise LangGraphConfigurationError("graph input must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > self.properties.max_input_bytes:
            raise LangGraphConfigurationError("graph input exceeds max_input_bytes")

    def invoke(
        self,
        input_state: Any,
        *,
        thread_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Any:
        self._validate_input(input_state)
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        compiled = self.compile()
        return self._invoke_compiled(compiled, input_state, run_config)

    def _invoke_compiled(self, compiled: Any, input_state: Any, run_config: dict) -> Any:
        """Invoke a compiled graph with the same bounded sync policy everywhere."""
        # Keep a bounded caller wait.  A daemon thread prevents a timed out
        # provider call from blocking process shutdown; provider-level timeouts
        # still need to be configured in springbootai.ai for true cancellation.
        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def run() -> None:
            try:
                result_holder["value"] = compiled.invoke(input_state, config=run_config)
            except BaseException as exc:  # propagate the original graph error
                error_holder["error"] = exc

        worker = threading.Thread(target=run, name=f"spring-langgraph-{self.name}", daemon=True)
        worker.start()
        worker.join(self.properties.timeout_seconds)
        if worker.is_alive():
            raise TimeoutError(f"LangGraph execution timed out after {self.properties.timeout_seconds}s")
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value")

    async def ainvoke(
        self,
        input_state: Any,
        *,
        thread_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Any:
        self._validate_input(input_state)
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        compiled = self.compile()
        method = getattr(compiled, "ainvoke", None)
        if method is None:
            method = lambda state, config: asyncio.to_thread(compiled.invoke, state, config=config)
        return await asyncio.wait_for(
            method(input_state, config=run_config), timeout=self.properties.timeout_seconds
        )

    def stream(
        self,
        input_state: Any,
        *,
        thread_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
        stream_mode: Optional[str] = None,
    ) -> Generator[Any, None, None]:
        self._validate_input(input_state)
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        yield from self.compile().stream(
            input_state, config=run_config, stream_mode=stream_mode or self.properties.stream_mode
        )

    async def astream(
        self,
        input_state: Any,
        *,
        thread_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
        stream_mode: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        self._validate_input(input_state)
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        compiled = self.compile()
        method = getattr(compiled, "astream", None)
        if method is not None:
            async for item in method(
                input_state, config=run_config, stream_mode=stream_mode or self.properties.stream_mode
            ):
                yield item
            return
        # Compatibility fallback for a custom compiled graph without astream.
        items = await asyncio.to_thread(
            lambda: list(self.stream(input_state, config=run_config, stream_mode=stream_mode))
        )
        for item in items:
            yield item

    def resume(
        self,
        *,
        thread_id: str,
        resume_value: Any,
        tenant_id: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Any:
        try:
            from langgraph.types import Command
        except ImportError as exc:  # pragma: no cover
            raise LangGraphUnavailableError("LangGraph Command is unavailable") from exc
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        self._validate_input(resume_value)
        return self._invoke_compiled(self.compile(), Command(resume=resume_value), run_config)

    def get_state(self, *, thread_id: str, tenant_id: Optional[str] = None, config: Optional[dict] = None) -> Any:
        run_config = self._config(thread_id=thread_id, tenant_id=tenant_id, config=config)
        return self.compile().get_state(run_config)


class LangGraphRuntime:
    """Spring bean that creates workflows while sharing AI module beans."""

    def __init__(self, properties: LangGraphProperties, *, model: Any = None,
                 tool_registry: Any = None, checkpointer: Any = None):
        self.properties = properties.validate()
        self.model = model
        self.tool_registry = tool_registry
        self.checkpointer = checkpointer

    def workflow(self, *, state_schema: Type[Any] = dict, name: Optional[str] = None,
                 checkpointer: Any = None) -> LangGraphWorkflow:
        selected = checkpointer if checkpointer is not None else self.checkpointer
        return LangGraphWorkflow(
            self.properties,
            state_schema=state_schema,
            name=name,
            checkpointer=selected,
        )

    def call_model(self, messages: Any, *, options: Optional[dict] = None) -> Any:
        """Call the configured Spring AI model and its registered tool policy."""
        if self.model is None:
            raise LangGraphConfigurationError(
                "no AI ChatModel is registered; configure springbootai.ai first"
            )
        return self.model.call(messages, tool_registry=self.tool_registry, options=options)

    async def acall_model(self, messages: Any, *, options: Optional[dict] = None) -> Any:
        """Async counterpart used by async graph nodes."""
        if self.model is None:
            raise LangGraphConfigurationError(
                "no AI ChatModel is registered; configure springbootai.ai first"
            )
        return await self.model.acall(
            messages, tool_registry=self.tool_registry, options=options
        )
