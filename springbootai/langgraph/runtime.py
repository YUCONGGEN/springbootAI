"""Safe, small Spring-style wrapper around the official LangGraph runtime.

This module intentionally does not reimplement a graph engine.  It validates
request boundaries and delegates graph execution to ``langgraph``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import re
import threading
import time
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
        self._compile_lock = threading.RLock()
        self._execution_slots = threading.BoundedSemaphore(
            self.properties.max_concurrent_executions
        )
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
        with self._compile_lock:
            if self._compiled is not None and checkpointer is None:
                return self._compiled
            selected = checkpointer if checkpointer is not None else self._checkpointer
            if selected is None and self.properties.checkpointer == "memory":
                selected = _load_memory_checkpointer()
            if self.properties.checkpointer == "injected" and selected is None:
                raise LangGraphConfigurationError(
                    "checkpointer=injected requires a persistent checkpointer instance"
                )
            compiled = self._builder.compile(
                checkpointer=selected, debug=debug, name=self.name
            )
            # A one-off caller supplied checkpointer must not replace the
            # workflow's default compiled graph for later requests.
            if checkpointer is None:
                self._compiled = compiled
            return compiled

    def _config(self, *, thread_id: Optional[str], tenant_id: Optional[str], config: Optional[dict]) -> dict:
        result = dict(config or {})
        configurable = dict(result.get("configurable") or {})
        if thread_id:
            configurable["thread_id"] = thread_id
        if tenant_id:
            configurable["tenant_id"] = tenant_id
        if self.properties.require_thread_id and not configurable.get("thread_id"):
            raise LangGraphConfigurationError("thread_id is required for every graph invocation")
        if self.properties.checkpointer != "none" and not tenant_id:
            raise LangGraphConfigurationError(
                "tenant_id must be passed explicitly when a checkpointer is enabled"
            )
        if configurable.get("thread_id") and len(str(configurable["thread_id"])) > 256:
            raise LangGraphConfigurationError("thread_id is too long")
        if configurable.get("tenant_id"):
            tenant = str(configurable["tenant_id"])
            if len(tenant) > 128:
                raise LangGraphConfigurationError("tenant_id is too long")
            if any(ord(character) < 32 for character in tenant):
                raise LangGraphConfigurationError("tenant_id contains control characters")
            # This is an authorization boundary, not a caller preference.
            # Always replace a supplied namespace with the trusted tenant.
            configurable["tenant_id"] = tenant
            configurable["checkpoint_ns"] = f"tenant:{tenant}"
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

    def _ensure_runtime_controls(self) -> threading.BoundedSemaphore:
        """Lazily initialize controls for compatibility with lightweight test doubles."""
        slots = getattr(self, "_execution_slots", None)
        if slots is None:
            slots = threading.BoundedSemaphore(
                int(getattr(self.properties, "max_concurrent_executions", 16))
            )
            self._execution_slots = slots
        return slots

    def _acquire_execution(self) -> None:
        timeout = float(getattr(self.properties, "acquire_timeout_seconds", 1.0))
        if not self._ensure_runtime_controls().acquire(timeout=timeout):
            raise TimeoutError("LangGraph execution capacity is exhausted")

    async def _acquire_execution_async(self) -> None:
        await asyncio.to_thread(self._acquire_execution)

    def _release_execution(self) -> None:
        self._ensure_runtime_controls().release()

    def _encoded_output_size(self, value: Any) -> int:
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise LangGraphConfigurationError(
                "graph output must be JSON serializable"
            ) from exc
        return len(encoded.encode("utf-8"))

    def _validate_output(self, value: Any) -> None:
        maximum = int(getattr(
            self.properties, "max_output_bytes", 10 * 1024 * 1024
        ))
        if self._encoded_output_size(value) > maximum:
            raise LangGraphConfigurationError("graph output exceeds max_output_bytes")

    def _run_sync_bounded(self, operation: Callable[[], Any]) -> Any:
        """Run one non-cancellable sync operation without unbounded thread growth.

        A timed-out worker retains its concurrency permit until it actually
        finishes. Repeated timeouts therefore exhaust a bounded capacity
        instead of creating an unlimited number of daemon threads.
        """
        self._acquire_execution()
        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def run() -> None:
            try:
                result = operation()
                self._validate_output(result)
                result_holder["value"] = result
            except BaseException as exc:
                error_holder["error"] = exc
            finally:
                self._release_execution()

        worker = threading.Thread(
            target=run,
            name=f"spring-langgraph-{self.name}",
            daemon=True,
        )
        try:
            worker.start()
        except BaseException:
            self._release_execution()
            raise
        worker.join(self.properties.timeout_seconds)
        if worker.is_alive():
            raise TimeoutError(
                f"LangGraph execution timed out after {self.properties.timeout_seconds}s"
            )
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value")

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
        return self._run_sync_bounded(
            lambda: compiled.invoke(input_state, config=run_config)
        )

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
        await self._acquire_execution_async()
        try:
            task = asyncio.ensure_future(method(input_state, config=run_config))
        except BaseException:
            self._release_execution()
            raise

        def release_when_done(completed: asyncio.Future) -> None:
            try:
                completed.exception()
            except BaseException:
                pass
            self._release_execution()

        try:
            done, _ = await asyncio.wait(
                {task}, timeout=self.properties.timeout_seconds
            )
        except BaseException:
            if task.done():
                self._release_execution()
            else:
                task.add_done_callback(release_when_done)
            raise
        if not done:
            task.add_done_callback(release_when_done)
            raise TimeoutError(
                f"LangGraph execution timed out after {self.properties.timeout_seconds}s"
            )
        try:
            result = task.result()
            self._validate_output(result)
            return result
        finally:
            self._release_execution()

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
        compiled = self.compile()
        messages: queue.Queue = queue.Queue(maxsize=32)
        stopped = threading.Event()
        maximum_events = int(getattr(self.properties, "max_stream_events", 10_000))
        maximum_bytes = int(getattr(
            self.properties, "max_output_bytes", 10 * 1024 * 1024
        ))
        timeout = float(self.properties.timeout_seconds)
        started = time.monotonic()
        self._acquire_execution()

        def publish(kind: str, value: Any = None) -> bool:
            while not stopped.is_set():
                try:
                    messages.put((kind, value), timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def produce() -> None:
            count = 0
            total_bytes = 0
            try:
                iterator = compiled.stream(
                    input_state,
                    config=run_config,
                    stream_mode=stream_mode or self.properties.stream_mode,
                )
                for item in iterator:
                    if stopped.is_set():
                        break
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(
                            f"LangGraph stream timed out after {timeout}s"
                        )
                    count += 1
                    total_bytes += self._encoded_output_size(item)
                    if count > maximum_events:
                        raise LangGraphConfigurationError(
                            "graph stream exceeds max_stream_events"
                        )
                    if total_bytes > maximum_bytes:
                        raise LangGraphConfigurationError(
                            "graph stream exceeds max_output_bytes"
                        )
                    if not publish("item", item):
                        break
            except BaseException as exc:
                publish("error", exc)
            finally:
                publish("done")
                self._release_execution()

        worker = threading.Thread(
            target=produce,
            name=f"spring-langgraph-stream-{self.name}",
            daemon=True,
        )
        try:
            worker.start()
        except BaseException:
            self._release_execution()
            raise
        try:
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError(
                        f"LangGraph stream timed out after {timeout}s"
                    )
                try:
                    kind, value = messages.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError(
                        f"LangGraph stream timed out after {timeout}s"
                    ) from exc
                if kind == "item":
                    yield value
                elif kind == "error":
                    raise value
                else:
                    break
        finally:
            stopped.set()

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
        if method is None:
            # Compatibility fallback delegates to the bounded sync stream.
            items = await asyncio.to_thread(
                lambda: list(self.stream(
                    input_state,
                    thread_id=thread_id,
                    tenant_id=tenant_id,
                    config=config,
                    stream_mode=stream_mode,
                ))
            )
            for item in items:
                yield item
            return

        await self._acquire_execution_async()
        iterator = method(
            input_state,
            config=run_config,
            stream_mode=stream_mode or self.properties.stream_mode,
        ).__aiter__()
        started = time.monotonic()
        count = 0
        total_bytes = 0
        try:
            while True:
                remaining = self.properties.timeout_seconds - (
                    time.monotonic() - started
                )
                if remaining <= 0:
                    raise TimeoutError(
                        f"LangGraph stream timed out after {self.properties.timeout_seconds}s"
                    )
                try:
                    item = await asyncio.wait_for(
                        iterator.__anext__(), timeout=remaining
                    )
                except StopAsyncIteration:
                    break
                count += 1
                total_bytes += self._encoded_output_size(item)
                if count > int(getattr(
                    self.properties, "max_stream_events", 10_000
                )):
                    raise LangGraphConfigurationError(
                        "graph stream exceeds max_stream_events"
                    )
                if total_bytes > int(getattr(
                    self.properties, "max_output_bytes", 10 * 1024 * 1024
                )):
                    raise LangGraphConfigurationError(
                        "graph stream exceeds max_output_bytes"
                    )
                yield item
        finally:
            closer = getattr(iterator, "aclose", None)
            if callable(closer):
                try:
                    await closer()
                except Exception:
                    logger.debug("LangGraph async stream close failed")
            self._release_execution()

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
        compiled = self.compile()
        return self._run_sync_bounded(lambda: compiled.get_state(run_config))


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
