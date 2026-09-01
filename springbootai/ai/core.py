"""
SpringBootAI AI 核心抽象 - 对齐 Spring AI 的 ChatClient / ChatModel / EmbeddingModel / Advisor。

设计原则：
- 模型调用层 (ChatModel/EmbeddingModel) 屏蔽 Provider 差异，底层可走 LangChain 或原生 HTTP
- ChatClient 提供链式 API（prompt().user().call().content()），与 Spring AI 风格一致
- Advisor 封装 RAG / Memory 等横切模式，在模型调用前后介入
"""
import logging
import json
import math
import threading
import contextvars
from collections.abc import Mapping
from contextlib import contextmanager
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Spring.AI")


class TokenBudgetExceededError(RuntimeError):
    """Raised when a single model/tool conversation exceeds its token budget."""


class ToolLoopLimitExceededError(RuntimeError):
    """Raised when a model continues requesting tools past the configured limit."""


class AIConcurrencyLimitError(RuntimeError):
    """Raised when provider capacity cannot be acquired within the limit."""


_capacity_owner: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "springbootai_ai_capacity_owner", default=None)


class _StreamCancellation:
    """Thread-safe cancellation callbacks for a blocking provider stream."""

    def __init__(self):
        self._lock = threading.Lock()
        self._callbacks = set()
        self._cancelled = False

    def register(self, callback):
        with self._lock:
            if self._cancelled:
                invoke_now = True
            else:
                self._callbacks.add(callback)
                invoke_now = False
        if invoke_now:
            try:
                callback()
            except Exception:
                pass

        def unregister():
            with self._lock:
                self._callbacks.discard(callback)

        return unregister

    def cancel(self):
        with self._lock:
            self._cancelled = True
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass


_stream_cancellation_owner: contextvars.ContextVar[
    Optional[_StreamCancellation]
] = contextvars.ContextVar(
    "springbootai_ai_stream_cancellation", default=None)


def _register_stream_cancel(callback):
    if not callable(callback):
        return lambda: None
    owner = _stream_cancellation_owner.get()
    if owner is None:
        return lambda: None
    return owner.register(callback)


# ==================== 消息与响应 ====================

class MessageType:
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """单条对话消息"""
    content: str
    type: str = MessageType.USER
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.SYSTEM)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.USER)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.ASSISTANT)

    def to_dict(self) -> Dict[str, str]:
        d = {"role": self.type, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Generation:
    """单次生成结果"""
    output: Message
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """模型响应"""
    generations: List[Generation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> Optional[Message]:
        return self.generations[0].output if self.generations else None

    def content(self) -> str:
        """便捷取值：返回首条生成的文本（对齐 Spring AI 的 call().content()）"""
        if self.generations:
            return self.generations[0].output.content
        return ""


# ==================== 模型抽象 ====================

def _is_tool_registry(obj) -> bool:
    return obj is not None and hasattr(obj, "schemas") and hasattr(obj, "execute")


class ChatModel(ABC):
    """聊天模型抽象 - 屏蔽 OpenAI/Ollama/LangChain 差异。

    函数调用闭环在基类 call() 中实现：Provider 的 _raw_call 把模型请求的
    tool_calls 放入 response.metadata['tool_calls']，基类统一执行→回填→续写。
    """

    MAX_TOOL_ITERATIONS = 5
    MAX_TOTAL_TOKENS = 100_000
    MAX_INPUT_BYTES = 2 * 1024 * 1024
    MAX_CONCURRENT_REQUESTS = 32
    CONCURRENCY_ACQUIRE_TIMEOUT = 30.0
    _capacity_setup_lock = threading.Lock()

    def _capacity_semaphore(self):
        capacity = max(1, int(getattr(
            self, "max_concurrent_requests", self.MAX_CONCURRENT_REQUESTS)))
        state = getattr(self, "_springbootai_capacity_state", None)
        if state is not None and state[0] == capacity:
            return state[1]
        with self._capacity_setup_lock:
            state = getattr(self, "_springbootai_capacity_state", None)
            if state is None or state[0] != capacity:
                state = (capacity, threading.BoundedSemaphore(capacity))
                setattr(self, "_springbootai_capacity_state", state)
            return state[1]

    def _capacity_timeout(self) -> float:
        value = float(getattr(
            self, "concurrency_acquire_timeout",
            self.CONCURRENCY_ACQUIRE_TIMEOUT))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                "concurrency_acquire_timeout must be a positive finite number")
        return value

    @contextmanager
    def _provider_capacity(self):
        if _capacity_owner.get() == id(self):
            yield
            return
        semaphore = self._capacity_semaphore()
        if not semaphore.acquire(timeout=self._capacity_timeout()):
            raise AIConcurrencyLimitError(
                "AI provider concurrency limit acquisition timed out")
        token = _capacity_owner.set(id(self))
        try:
            yield
        finally:
            _capacity_owner.reset(token)
            semaphore.release()

    async def _acquire_provider_capacity_async(self):
        import asyncio
        semaphore = self._capacity_semaphore()
        deadline = asyncio.get_running_loop().time() + self._capacity_timeout()
        while not semaphore.acquire(blocking=False):
            if asyncio.get_running_loop().time() >= deadline:
                raise AIConcurrencyLimitError(
                    "AI provider concurrency limit acquisition timed out")
            await asyncio.sleep(0.01)
        return semaphore

    @staticmethod
    def _estimate_tokens(messages: List[Message], response=None) -> int:
        encoded_units = 0
        for message in messages:
            encoded_units += len(str(getattr(
                message, "content", "")).encode("utf-8")) + 12
            metadata = getattr(message, "metadata", None)
            if metadata:
                try:
                    encoded_units += len(json.dumps(
                        metadata, ensure_ascii=False,
                        default=lambda value: f"<{type(value).__name__}>",
                    ).encode("utf-8"))
                except Exception:
                    encoded_units += 64
        if response is not None:
            for generation in getattr(response, "generations", ()) or ():
                encoded_units += len(str(getattr(
                    getattr(generation, "output", None), "content", ""
                )).encode("utf-8"))
        # Four UTF-8 bytes per token is a local fallback only.  It remains
        # inexpensive for Latin text while charging multi-byte CJK content
        # substantially more than a character-count heuristic.
        return max(1, math.ceil(encoded_units / 4))

    def _validate_input_size(self, messages: List[Message], tool_registry,
                             max_input_bytes: int) -> None:
        if max_input_bytes <= 0:
            raise ValueError("max_input_bytes must be greater than zero")
        payload = []
        for message in messages:
            serialized = message.to_dict()
            if message.metadata:
                serialized["metadata"] = message.metadata
            payload.append(serialized)
        if _is_tool_registry(tool_registry):
            payload.append({"tools": tool_registry.schemas()})
        try:
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"),
                default=lambda value: f"<{type(value).__name__}>",
            ).encode("utf-8")
        except Exception as exc:
            raise ValueError("AI request must be JSON serializable") from exc
        if len(encoded) > max_input_bytes:
            raise TokenBudgetExceededError(
                f"AI input exceeds byte limit ({len(encoded)}>{max_input_bytes})")

    def _prepare_stream_request(self, messages, tool_registry, options):
        if options is not None and not isinstance(options, Mapping):
            raise ValueError("AI provider options must be a mapping")
        provider_options = dict(options or {})
        try:
            max_input_bytes = int(provider_options.pop(
                "max_input_bytes", getattr(
                    self, "max_input_bytes", self.MAX_INPUT_BYTES)))
            token_budget = int(provider_options.pop(
                "max_total_tokens", getattr(
                    self, "max_total_tokens", self.MAX_TOTAL_TOKENS)))
        except (TypeError, ValueError) as exc:
            raise ValueError("AI stream limits must be integers") from exc
        if token_budget <= 0:
            raise ValueError("max_total_tokens must be greater than zero")
        provider_options.pop("max_tool_iterations", None)
        self._validate_input_size(messages, tool_registry, max_input_bytes)
        initial_tokens = self._estimate_tokens(messages)
        if initial_tokens > token_budget:
            raise TokenBudgetExceededError(
                f"AI input exceeds token budget ({initial_tokens}>{token_budget})")
        return provider_options or None, token_budget, initial_tokens

    @staticmethod
    def _bounded_stream(iterator, token_budget: int, initial_tokens: int):
        output_bytes = 0
        for response in iterator:
            for generation in getattr(response, "generations", ()) or ():
                output_bytes += len(str(getattr(
                    getattr(generation, "output", None), "content", ""
                )).encode("utf-8"))
            estimated = initial_tokens + math.ceil(output_bytes / 4)
            metadata = getattr(response, "metadata", None)
            if metadata is None:
                response.metadata = {}
                metadata = response.metadata
            usage = metadata.get("usage") if isinstance(metadata, dict) else None
            reported = usage.get("total_tokens") if isinstance(usage, dict) else None
            try:
                consumed = max(estimated, int(reported or 0))
            except (TypeError, ValueError, OverflowError):
                consumed = estimated
            metadata["cumulative_tokens"] = consumed
            metadata["token_budget"] = token_budget
            if consumed > token_budget:
                raise TokenBudgetExceededError(
                    f"AI stream exceeded token budget ({consumed}>{token_budget})")
            yield response

    @abstractmethod
    def _raw_call(self, messages: List[Message],
                  tool_registry=None,
                  options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """Provider 实现：单次模型调用。若模型请求工具，将 tool_calls 列表
        放入返回的 ChatResponse.metadata['tool_calls']（每项含 id/function{name,arguments}）。
        tool_registry 用于把工具 schema 注入请求体。"""

    def call(self, messages: List[Message],
             tool_registry=None,
             options: Optional[Dict[str, Any]] = None,
             context: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """同步调用 - 含函数调用闭环"""
        import json as _json
        from springbootai.ai.observability import ai_metrics

        working = list(messages)
        provider_options = dict(options or {})
        try:
            max_input_bytes = int(provider_options.pop(
                "max_input_bytes", getattr(
                    self, "max_input_bytes", self.MAX_INPUT_BYTES)))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_input_bytes must be an integer") from exc
        self._validate_input_size(working, tool_registry, max_input_bytes)
        try:
            token_budget = int(provider_options.pop(
                "max_total_tokens", getattr(self, "max_total_tokens",
                                             self.MAX_TOTAL_TOKENS)))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_total_tokens must be an integer") from exc
        if token_budget <= 0:
            raise ValueError("max_total_tokens must be greater than zero")
        initial_estimate = self._estimate_tokens(working)
        if initial_estimate > token_budget:
            raise TokenBudgetExceededError(
                f"AI input exceeds token budget ({initial_estimate}>{token_budget})")
        try:
            max_tool_iterations = int(provider_options.pop(
                "max_tool_iterations", getattr(
                    self, "max_tool_iterations", self.MAX_TOOL_ITERATIONS)))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_tool_iterations must be an integer") from exc
        if max_tool_iterations < 0 or max_tool_iterations > 100:
            raise ValueError("max_tool_iterations must be in [0, 100]")

        cumulative_tokens = 0
        resp = None
        for iteration in range(max_tool_iterations + 1):
            # Tool results become provider input on subsequent rounds. Recheck
            # both byte and cumulative token limits before incurring another
            # external call; validating only the original user prompt lets a
            # large tool response bypass request limits.
            self._validate_input_size(
                working, tool_registry, max_input_bytes)
            if iteration > 0:
                projected = cumulative_tokens + self._estimate_tokens(working)
                if projected > token_budget:
                    raise TokenBudgetExceededError(
                        "AI tool conversation would exceed token budget "
                        f"({projected}>{token_budget})")
            with self._provider_capacity():
                resp = self._raw_call(
                    working, tool_registry, provider_options or None)
            resp.metadata = resp.metadata or {}
            resp.metadata["tool_iterations"] = iteration
            usage = resp.metadata.get("usage") or {}
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            if total is None and isinstance(usage, dict):
                total = (usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0) + (
                    usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
            try:
                numeric_total = max(0, int(total or 0))
            except (TypeError, ValueError):
                logger.debug("Provider returned non-numeric token usage: %r", total)
                numeric_total = 0
            if numeric_total <= 0:
                numeric_total = self._estimate_tokens(working, resp)
                resp.metadata["usage_estimated"] = True
            cumulative_tokens += numeric_total
            resp.metadata["cumulative_tokens"] = cumulative_tokens
            resp.metadata["token_budget"] = token_budget
            if cumulative_tokens > token_budget:
                raise TokenBudgetExceededError(
                    f"AI request exceeded token budget ({cumulative_tokens}>{token_budget})")
            tool_calls = resp.metadata.get("tool_calls")

            # 无工具调用 → 返回最终回复
            if not tool_calls or not _is_tool_registry(tool_registry):
                return resp
            if iteration >= max_tool_iterations:
                raise ToolLoopLimitExceededError(
                    f"AI tool loop exceeded {max_tool_iterations} iterations")

            # 有工具调用 → 追加 assistant 消息 + 执行工具 + 回填
            assistant_message = resp.output or Message.assistant("")
            if not assistant_message.metadata.get("tool_calls"):
                assistant_message.metadata["tool_calls"] = tool_calls
            working.append(assistant_message)
            for tc in tool_calls:
                args: Any = {}
                name = ""
                tool_call_id = ""
                try:
                    if not isinstance(tc, dict):
                        raise ValueError("tool call must be an object")
                    tool_call_id = str(tc.get("id", "") or "")
                    func = tc.get("function", {})
                    if not isinstance(func, dict):
                        raise ValueError("tool call function must be an object")
                    name = str(func.get("name", "") or "")
                    if not name:
                        raise ValueError("tool call name is required")
                    args_raw = func.get("arguments", "{}")
                    args = (_json.loads(args_raw) if isinstance(args_raw, str)
                            else args_raw)
                    # Request-scoped identity and authorization data must reach
                    # the registry policy. Do not ask tools to infer identity
                    # from mutable globals or model-controlled arguments.
                    result = tool_registry.execute(name, args, context=context)
                    metric_name = (
                        name if hasattr(tool_registry, "names")
                        and name in tool_registry.names() else "<invalid>"
                    )
                    ai_metrics.record_tool_call(metric_name, "success")
                except Exception as exc:
                    # 安全：异常消息脱敏后返回，防止泄露连接字符串、路径、凭据等敏感信息
                    # 仅透传异常类型和首段描述，完整 traceback 记录在服务端日志
                    err_type = type(exc).__name__
                    raw_msg = str(exc)
                    # 截断异常消息（最大 200 字符），防止工具异常返回超大字符串
                    from springbootai.logging.context import (
                        redact_log_data, redact_sensitive,
                    )
                    safe_msg = redact_sensitive(raw_msg)[:200]
                    try:
                        safe_args = _json.dumps(
                            redact_log_data(args), ensure_ascii=False,
                            default=lambda value: f"<{type(value).__name__}>",
                        )[:500]
                    except Exception:
                        safe_args = "<unrenderable>"
                    logger.warning("工具执行失败: %s args=%s error=%s", name,
                                   safe_args, safe_msg)
                    result = f"[工具执行错误] {err_type}"
                    metric_name = (
                        name if name and hasattr(tool_registry, "names")
                        and name in tool_registry.names() else "<invalid>"
                    )
                    ai_metrics.record_tool_call(metric_name, "failure")
                working.append(Message(
                    content=str(result)[:10000], type=MessageType.TOOL, name=name,
                    metadata={"tool_call_id": tool_call_id},
                ))

        raise ToolLoopLimitExceededError(
            f"AI tool loop exceeded {max_tool_iterations} iterations")

    def _stream_tool_loop_response(
        self,
        messages: List[Message],
        tool_registry,
        options: Optional[Dict[str, Any]],
    ) -> Optional[ChatResponse]:
        """Run the complete tool loop before yielding a streaming response.

        Provider tool calls arrive as fragmented deltas and cannot safely be
        executed as ordinary text chunks.  Until a provider-native delta
        assembler is used, degrade tool-enabled streaming to one final response
        rather than silently omitting tool schemas or tool execution.
        """
        if not _is_tool_registry(tool_registry):
            return None
        schemas = tool_registry.schemas()
        if not schemas:
            return None
        response = self.call(
            messages, tool_registry=tool_registry, options=options)
        response.metadata = response.metadata or {}
        response.metadata["stream"] = False
        response.metadata["stream_fallback"] = "tool_loop"
        return response

    def stream(self, messages: List[Message],
               tool_registry=None,
               options: Optional[Dict[str, Any]] = None):
        """流式调用（SSE delta 生成器），默认降级为单次 yield"""
        tool_response = self._stream_tool_loop_response(
            messages, tool_registry, options)
        if tool_response is not None:
            yield tool_response
            return
        provider_options, budget, initial = self._prepare_stream_request(
            messages, tool_registry, options)
        with self._provider_capacity():
            iterator = iter((self._raw_call(
                messages, tool_registry, provider_options),))
            yield from self._bounded_stream(iterator, budget, initial)

    async def astream(self, messages: List[Message],
                      tool_registry=None,
                      options: Optional[Dict[str, Any]] = None):
        """在工作线程中按需拉取同步流。

        每次只调用一次 ``next``，因此消费端天然提供背压；
        ``asyncio.to_thread`` 同时复制当前 ContextVar，保证请求 ID
        等请求级上下文在 Provider 线程中可见。
        """
        import asyncio
        import concurrent.futures
        import contextvars
        import threading

        iterator = iter(self.stream(
            messages, tool_registry=tool_registry, options=options))
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        stop = threading.Event()
        capacity_released = threading.Event()
        stream_cancellation = _StreamCancellation()
        context = None
        semaphore = None

        def release_capacity() -> None:
            if (semaphore is not None
                    and not capacity_released.is_set()):
                capacity_released.set()
                semaphore.release()

        def publish(kind: str, value: Any = None,
                    acknowledgement=None) -> bool:
            future = asyncio.run_coroutine_threadsafe(
                queue.put((kind, value, acknowledgement)), loop)
            while True:
                try:
                    future.result(timeout=0.1)
                    return True
                except concurrent.futures.TimeoutError:
                    if stop.is_set():
                        future.cancel()
                        return False
                except (RuntimeError, asyncio.CancelledError,
                        concurrent.futures.CancelledError):
                    return False

        def produce() -> None:
            try:
                while not stop.is_set():
                    try:
                        chunk = next(iterator)
                    except StopIteration:
                        publish("done")
                        return
                    acknowledgement = threading.Event()
                    if stop.is_set() or not publish(
                            "item", chunk, acknowledgement):
                        return
                    # Do not pull another provider chunk until the async
                    # consumer resumes after yielding this one.  A size-one
                    # queue alone still permits one speculative ``next``.
                    while not acknowledgement.wait(0.1):
                        if stop.is_set():
                            return
            except BaseException as exc:
                if not stop.is_set():
                    publish("error", exc)
            finally:
                closer = getattr(iterator, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except (RuntimeError, ValueError):
                        pass
                release_capacity()

        worker = threading.Thread(
            target=lambda: context.run(produce),
            name=f"spring-ai-stream-{type(self).__name__}",
            daemon=True,
        )
        semaphore = await self._acquire_provider_capacity_async()
        capacity_token = _capacity_owner.set(id(self))
        # Capture the ownership marker after acquisition so provider ``stream``
        # does not attempt to acquire the same semaphore again in its worker.
        cancellation_token = _stream_cancellation_owner.set(
            stream_cancellation)
        try:
            context = contextvars.copy_context()
        finally:
            _stream_cancellation_owner.reset(cancellation_token)
        worker_started = False
        try:
            worker.start()
            worker_started = True
            while True:
                kind, value, acknowledgement = await queue.get()
                if kind == "done":
                    break
                if kind == "error":
                    logger.warning(
                        "异步流式生产者异常 error_type=%s",
                        type(value).__name__,
                    )
                    if isinstance(value, (
                            TokenBudgetExceededError,
                            AIConcurrencyLimitError,
                            ToolLoopLimitExceededError)):
                        raise value
                    raise RuntimeError(
                        f"stream error: {type(value).__name__}"
                    ) from None
                try:
                    yield value
                finally:
                    acknowledgement.set()
        finally:
            stop.set()
            # Built-in HTTP providers register the active response's close
            # method, allowing downstream cancellation to interrupt a blocking
            # socket read instead of occupying capacity until read timeout.
            stream_cancellation.cancel()
            # Provider-specific iterators may expose a thread-safe cancellation
            # hook. Generic generators are closed by their owning worker once a
            # bounded socket read returns; no default executor worker is leaked.
            cancel = getattr(iterator, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
            _capacity_owner.reset(capacity_token)
            if not worker_started:
                release_capacity()
            elif not capacity_released.is_set():
                await asyncio.to_thread(capacity_released.wait, 0.5)

    async def acall(self, messages: List[Message],
                    tool_registry=None,
                    options: Optional[Dict[str, Any]] = None,
                    context: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """异步调用，默认降级为同步 call（子类可覆盖实现真异步）"""
        import asyncio
        semaphore = await self._acquire_provider_capacity_async()
        capacity_token = _capacity_owner.set(id(self))
        try:
            return await asyncio.to_thread(
                self.call, messages, tool_registry, options, context)
        finally:
            _capacity_owner.reset(capacity_token)
            semaphore.release()


class EmbeddingModel(ABC):
    """嵌入模型抽象"""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入"""

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


# ==================== Advisor ====================

@dataclass
class AdvisorRequest:
    """Advisor 请求上下文"""
    messages: List[Message]
    chat_model: ChatModel
    tool_registry: Optional[Any] = None
    context: Dict[str, Any] = field(default_factory=dict)
    options: Optional[Dict[str, Any]] = None


class Advisor(ABC):
    """
    Advisor - 封装 RAG / Memory / 日志等横切模式。
    advise_request 在模型调用前转换请求；advise_response 在调用后转换响应。
    """
    order: int = 0

    @abstractmethod
    def advise_request(self, request: AdvisorRequest) -> AdvisorRequest:
        """转换请求"""

    def advise_response(self, response: ChatResponse,
                        request: AdvisorRequest) -> ChatResponse:
        """转换响应（默认透传）"""
        return response


# ==================== ChatClient 链式 API ====================

class PromptSpec:
    """链式 Prompt 构造器"""

    def __init__(self, chat_client: "ChatClient"):
        self._client = chat_client
        self._messages: List[Message] = []
        self._advisors: List[Advisor] = list(chat_client.default_advisors)
        # tool_registry：None 或 ToolRegistry 或待注册的可调用对象列表
        self._tool_registry = chat_client.default_tool_registry
        self._pending_tools: List[Any] = []
        self._context: Dict[str, Any] = {}
        self._options: Dict[str, Any] = {}

    def system(self, text: str) -> "PromptSpec":
        self._messages.append(Message.system(text))
        return self

    def user(self, text: str) -> "PromptSpec":
        self._messages.append(Message.user(text))
        return self

    def messages(self, msgs: List[Message]) -> "PromptSpec":
        self._messages.extend(msgs)
        return self

    def advisors(self, *advisors: Advisor) -> "PromptSpec":
        self._advisors.extend(advisors)
        return self

    def tools(self, *tools: Any) -> "PromptSpec":
        """注册工具 - 可传入 ToolRegistry 或若干可调用函数"""
        for t in tools:
            if t is None:
                continue
            # 已是 ToolRegistry
            if hasattr(t, "schemas") and hasattr(t, "execute"):
                self._tool_registry = t
            else:
                self._pending_tools.append(t)
        return self

    def param(self, key: str, value: Any) -> "PromptSpec":
        self._context[key] = value
        return self

    def option(self, key: str, value: Any) -> "PromptSpec":
        """Set a request-scoped provider/framework option."""
        self._options[key] = value
        return self

    def _resolve_registry(self):
        """合并默认 registry 与本次 pending 工具"""
        from springbootai.ai.tools import CompositeToolRegistry, ToolRegistry
        registry = self._tool_registry
        if self._pending_tools:
            request_registry = ToolRegistry()
            for i, func in enumerate(self._pending_tools):
                name = getattr(func, "__name__", f"tool_{i}")
                desc = (func.__doc__ or "").strip().split("\n")[0]
                request_registry.register(name, func, description=desc)
            if registry is None:
                registry = request_registry
            else:
                # Preserve the default registry's authorization, approval,
                # dangerous-tool and timeout policies. Re-registering its
                # callables into a fresh registry would silently discard them.
                registry = CompositeToolRegistry(registry, request_registry)
        return registry

    def call(self) -> ChatResponse:
        return self._client._execute(
            self._messages, self._advisors,
            self._resolve_registry(), self._context, self._options,
        )

    async def acall(self) -> ChatResponse:
        """异步调用，不阻塞 ASGI 事件循环。"""
        return await self._client._aexecute(
            self._messages, self._advisors,
            self._resolve_registry(), self._context, self._options,
        )

    def stream(self):
        """流式调用生成器"""
        yield from self._client._execute_stream(
            self._messages, self._advisors,
            self._resolve_registry(), self._context, self._options,
        )

    async def astream(self):
        """异步流式调用。"""
        async for chunk in self._client._aexecute_stream(
                self._messages, self._advisors,
                self._resolve_registry(), self._context, self._options):
            yield chunk

    def content(self) -> str:
        return self.call().content()

    async def acontent(self) -> str:
        return (await self.acall()).content()


class ChatClient:
    """
    ChatClient - Spring AI 风格的链式聊天客户端。

    用法：
        client = ChatClient(chat_model).default_system("你是助手").build()
        answer = client.prompt().user("你好").call().content()
    """

    def __init__(self, chat_model: ChatModel):
        self.chat_model = chat_model
        self._default_system: Optional[str] = None
        self.default_advisors: List[Advisor] = []
        self.default_tool_registry: Optional[Any] = None

    def default_system(self, text: str) -> "ChatClient":
        self._default_system = text
        return self

    def default_advisors_set(self, *advisors: Advisor) -> "ChatClient":
        self.default_advisors = list(advisors)
        return self

    def default_tools_set(self, tool_registry: Any) -> "ChatClient":
        """设置默认 ToolRegistry"""
        self.default_tool_registry = tool_registry
        return self

    def build(self) -> "ChatClient":
        return self

    def prompt(self) -> PromptSpec:
        spec = PromptSpec(self)
        if self._default_system:
            spec._messages.insert(0, Message.system(self._default_system))
        return spec

    def _execute(self, messages: List[Message], advisors: List[Advisor],
                 tool_registry, context: Dict[str, Any],
                 options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        # 请求阶段：按 order 升序应用 advisor
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
            options=dict(options or {}) or None,
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = advisor.advise_request(request)

        # 模型调用（携带 tool_registry 以启用函数调用闭环）
        response = self.chat_model.call(
            request.messages, tool_registry=request.tool_registry,
            options=request.options, context=request.context,
        )

        # 响应阶段：按 order 降序应用 advisor
        for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
            response = advisor.advise_response(response, request)
        return response

    @staticmethod
    async def _call_advisor(callback, *args):
        import asyncio
        import inspect
        if inspect.iscoroutinefunction(callback):
            return await callback(*args)
        result = await asyncio.to_thread(callback, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _aexecute(self, messages: List[Message], advisors: List[Advisor],
                        tool_registry, context: Dict[str, Any],
                        options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
            options=dict(options or {}) or None,
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = await self._call_advisor(advisor.advise_request, request)
        response = await self.chat_model.acall(
            request.messages, tool_registry=request.tool_registry,
            options=request.options, context=request.context,
        )
        for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
            response = await self._call_advisor(
                advisor.advise_response, response, request)
        return response

    def _execute_stream(self, messages: List[Message], advisors: List[Advisor],
                        tool_registry, context: Dict[str, Any],
                        options: Optional[Dict[str, Any]] = None):
        # 流式：advisor 先做请求预处理，逐块 yield；全部消费完后再统一回调
        # advise_response（例如 MessageChatMemoryAdvisor 保存会话记忆）。
        # 修复：之前流式模式从不调用 advise_response，导致"流式 + 记忆"时对话
        # 永远不会被持久化。
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
            options=dict(options or {}) or None,
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = advisor.advise_request(request)

        aggregate_limit = 100_000
        aggregate_parts: List[str] = []
        aggregate_size = 0
        aggregate_truncated = False
        last_metadata: Dict[str, Any] = {}

        def remember(chunk: ChatResponse) -> None:
            nonlocal aggregate_size, aggregate_truncated, last_metadata
            last_metadata = chunk.metadata or {}
            content = chunk.content()
            available = aggregate_limit - aggregate_size
            if available <= 0:
                aggregate_truncated = aggregate_truncated or bool(content)
                return
            if len(content) > available:
                content = content[:available]
                aggregate_truncated = True
            aggregate_parts.append(content)
            aggregate_size += len(content)
        has_tools = (
            request.tool_registry is not None
            and hasattr(request.tool_registry, "names")
            and bool(request.tool_registry.names())
        )
        if has_tools:
            # Provider streaming protocols assemble tool-call arguments across
            # deltas and differ substantially. Use the fully validated sync
            # tool loop instead of silently dropping tools in stream mode.
            chunk = self.chat_model.call(
                request.messages,
                tool_registry=request.tool_registry,
                options=request.options,
                context=request.context,
            )
            remember(chunk)
            yield chunk
        else:
            iterator = iter(self.chat_model.stream(
                request.messages, tool_registry=request.tool_registry,
                options=request.options,
            ))
            completed = False
            try:
                for chunk in iterator:
                    remember(chunk)
                    yield chunk
                completed = True
            finally:
                if not completed:
                    closer = getattr(iterator, "close", None)
                    if callable(closer):
                        closer()

        # 聚合全部流式块，回调响应阶段 advisor（触发记忆保存/日志/审计等副作用）
        if aggregate_parts:
            combined = ChatResponse(
                generations=[Generation(output=Message.assistant(
                    "".join(aggregate_parts)))],
                metadata={"provider": last_metadata.get("provider"),
                          "stream": True, "combined": True,
                          "aggregate_truncated": aggregate_truncated},
            )
            for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
                combined = advisor.advise_response(combined, request)

    async def _aexecute_stream(self, messages: List[Message], advisors: List[Advisor],
                               tool_registry, context: Dict[str, Any],
                               options: Optional[Dict[str, Any]] = None):
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
            options=dict(options or {}) or None,
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = await self._call_advisor(advisor.advise_request, request)

        aggregate_limit = 100_000
        aggregate_parts: List[str] = []
        aggregate_size = 0
        aggregate_truncated = False
        last_metadata: Dict[str, Any] = {}

        def remember(chunk: ChatResponse) -> None:
            nonlocal aggregate_size, aggregate_truncated, last_metadata
            last_metadata = chunk.metadata or {}
            content = chunk.content()
            available = aggregate_limit - aggregate_size
            if available <= 0:
                aggregate_truncated = aggregate_truncated or bool(content)
                return
            if len(content) > available:
                content = content[:available]
                aggregate_truncated = True
            aggregate_parts.append(content)
            aggregate_size += len(content)

        has_tools = (
            request.tool_registry is not None
            and hasattr(request.tool_registry, "names")
            and bool(request.tool_registry.names())
        )
        if has_tools:
            chunk = await self.chat_model.acall(
                request.messages, tool_registry=request.tool_registry,
                options=request.options, context=request.context)
            remember(chunk)
            yield chunk
        else:
            iterator = self.chat_model.astream(
                request.messages, tool_registry=request.tool_registry,
                options=request.options)
            completed = False
            try:
                async for chunk in iterator:
                    remember(chunk)
                    yield chunk
                completed = True
            finally:
                if not completed:
                    closer = getattr(iterator, "aclose", None)
                    if callable(closer):
                        await closer()

        if aggregate_parts:
            combined = ChatResponse(
                generations=[Generation(output=Message.assistant(
                    "".join(aggregate_parts)))],
                metadata={"provider": last_metadata.get("provider"),
                          "stream": True, "combined": True,
                          "aggregate_truncated": aggregate_truncated},
            )
            for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
                combined = await self._call_advisor(
                    advisor.advise_response, combined, request)


class ChatClientBuilder:
    """ChatClient 构造器 - 对齐 Spring AI 的 ChatClient.Builder"""

    def __init__(self, chat_model: ChatModel):
        self._client = ChatClient(chat_model)

    def default_system(self, text: str) -> "ChatClientBuilder":
        self._client.default_system(text)
        return self

    def default_advisors(self, *advisors: Advisor) -> "ChatClientBuilder":
        self._client.default_advisors_set(*advisors)
        return self

    def default_tools(self, tool_registry: Any) -> "ChatClientBuilder":
        self._client.default_tools_set(tool_registry)
        return self

    def build(self) -> ChatClient:
        return self._client.build()
