"""
模型 Provider 适配层 - OpenAI 兼容 + Ollama（企业级）。

已落地的企业能力：
1. 函数调用闭环 - tools 注入请求体，tool_call 解析→执行→回填→续写循环
2. 真流式 SSE - stream=True 解析 data: 增量，逐块 yield
3. async - acall/astream 异步入口
4. 韧性 - 复用 springbootai.retry 重试 + AICircuitBreaker 熔断
5. 可观测 - ai_metrics 记录调用/token/延迟

底层优先复用 LangChain 生态（langchain_openai/langchain_community）做模型适配，
未安装时降级原生 HTTP（requests），保证开箱即用。
"""
import atexit
import json
import logging
import math
import threading
import time
import weakref
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

import requests as _requests

from springbootai.ai.core import (
    ChatModel, ChatResponse, EmbeddingModel, Generation, Message, MessageType,
    _register_stream_cancel,
)
from springbootai.logging.context import outbound_request_id

logger = logging.getLogger("Spring.AI")


_ORIGINAL_REQUESTS_POST = _requests.post
_PROVIDER_HTTP_LOCAL = threading.local()
_PROVIDER_HTTP_SESSIONS = weakref.WeakSet()
_PROVIDER_HTTP_SESSIONS_LOCK = threading.Lock()


def _provider_http_session():
    """Return a thread-confined pooled HTTP session."""
    session = getattr(_PROVIDER_HTTP_LOCAL, "session", None)
    if session is None:
        session = _requests.Session()
        adapter = _requests.adapters.HTTPAdapter(
            pool_connections=16,
            pool_maxsize=32,
            max_retries=0,
            pool_block=False,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _PROVIDER_HTTP_LOCAL.session = session
        with _PROVIDER_HTTP_SESSIONS_LOCK:
            _PROVIDER_HTTP_SESSIONS.add(session)
    return session


def _provider_post(*args, **kwargs):
    """POST through a pool while retaining the public monkeypatch seam."""
    timeout = kwargs.pop("timeout", None)
    if timeout is None:
        raise ValueError("AI provider HTTP timeout is required")
    if _requests.post is not _ORIGINAL_REQUESTS_POST:
        return _requests.post(*args, timeout=timeout, **kwargs)
    return _provider_http_session().post(*args, timeout=timeout, **kwargs)


def _close_provider_http_sessions() -> None:
    with _PROVIDER_HTTP_SESSIONS_LOCK:
        sessions = list(_PROVIDER_HTTP_SESSIONS)
    for session in sessions:
        try:
            session.close()
        except Exception:
            pass


atexit.register(_close_provider_http_sessions)


class ProviderStreamError(RuntimeError):
    """Raised when a provider stream cannot complete truthfully."""


class ProviderResponseTooLargeError(RuntimeError):
    """Raised when a provider ignores response bounds and sends excessive data."""


class ProviderProtocolError(RuntimeError):
    """Raised when a successful HTTP response violates the provider protocol."""


class _IncompleteProviderStream(ProviderStreamError):
    """Internal retryable marker for a stream without its terminal event."""


_MAX_STREAM_EVENT_BYTES = 1024 * 1024
_MAX_STREAM_TOTAL_BYTES = 50 * 1024 * 1024


def _reject_provider_redirect(response, provider: str) -> None:
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and 300 <= status < 400:
        raise ProviderProtocolError(
            f"{provider} redirects are not allowed")


def _decode_stream_line(raw: bytes, provider: str) -> str:
    if len(raw) > _MAX_STREAM_EVENT_BYTES:
        raise ProviderResponseTooLargeError(
            f"{provider} stream event exceeds configured safety limit")
    try:
        return raw.rstrip(b"\r").decode("utf-8")
    except UnicodeDecodeError:
        raise ProviderProtocolError(
            f"{provider} returned an invalid stream event") from None


def _bounded_stream_lines(response, provider: str):
    """Yield UTF-8 lines with per-event and total decompressed byte limits.

    Real requests responses are read in bounded chunks so an upstream that
    never emits a newline cannot force ``iter_lines`` to grow without limit.
    Lightweight response adapters retain their conventional ``iter_lines``
    path while receiving the same post-yield bounds.
    """
    import requests

    declared = (getattr(response, "headers", {}) or {}).get("Content-Length")
    if declared:
        try:
            if int(declared) > _MAX_STREAM_TOTAL_BYTES:
                raise ProviderResponseTooLargeError(
                    f"{provider} stream exceeds configured safety limit")
        except ValueError:
            pass

    if isinstance(response, requests.Response):
        buffer = bytearray()
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_STREAM_TOTAL_BYTES:
                raise ProviderResponseTooLargeError(
                    f"{provider} stream exceeds configured safety limit")
            buffer.extend(chunk)
            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    break
                raw = bytes(buffer[:newline])
                del buffer[:newline + 1]
                yield _decode_stream_line(raw, provider)
            if len(buffer) > _MAX_STREAM_EVENT_BYTES:
                raise ProviderResponseTooLargeError(
                    f"{provider} stream event exceeds configured safety limit")
        if buffer:
            yield _decode_stream_line(bytes(buffer), provider)
        return

    total = 0
    for line in response.iter_lines(decode_unicode=True):
        raw = line if isinstance(line, bytes) else str(line).encode("utf-8")
        total += len(raw) + 1
        if total > _MAX_STREAM_TOTAL_BYTES:
            raise ProviderResponseTooLargeError(
                f"{provider} stream exceeds configured safety limit")
        yield _decode_stream_line(raw, provider)


def _openai_request_options(options, max_output_tokens: int) -> Dict[str, Any]:
    try:
        output_cap = int(max_output_tokens)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("max_output_tokens must be a positive integer") from exc
    if output_cap <= 0:
        raise ValueError("max_output_tokens must be a positive integer")
    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise ValueError("AI provider options must be a mapping")
    if any(not isinstance(key, str) for key in options):
        raise ValueError("AI provider option names must be strings")
    # These fields are framework-owned security/protocol boundaries.
    normalized = {
        key: value for key, value in options.items()
        if key not in {
            "model", "messages", "tools", "stream",
            "max_total_tokens", "max_tool_iterations",
        }
    }
    for key in ("max_tokens", "max_completion_tokens"):
        if key not in normalized:
            continue
        try:
            requested = int(normalized[key])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{key} must be a positive integer") from exc
        if requested <= 0:
            raise ValueError(f"{key} must be a positive integer")
        normalized[key] = min(requested, output_cap)
    return normalized


def _bind_request_options(llm, options, max_output_tokens: int, provider: str):
    normalized = _openai_request_options(options, max_output_tokens)
    if not normalized:
        return llm
    binder = getattr(llm, "bind", None)
    if not callable(binder):
        raise ValueError(
            f"{provider} backend does not support request-scoped options")
    return binder(**normalized)


def _observed_stream(iterator, *, provider: str, model: str):
    """Record streaming success/failure without treating early close as success."""
    from springbootai.ai.observability import ai_metrics

    started = time.time()
    try:
        yield from iterator
    except Exception:
        ai_metrics.record_call(
            provider, model, "failure", time.time() - started)
        raise
    else:
        ai_metrics.record_call(
            provider, model, "success", time.time() - started)


def _has_langchain_openai() -> bool:
    try:
        import langchain_openai  # noqa: F401
        return True
    except ImportError:
        return False


def _has_langchain_community() -> bool:
    try:
        import langchain_community  # noqa: F401
        return True
    except ImportError:
        return False


def _has_langchain(module: str) -> bool:
    """按模块名探测是否安装了某个 langchain-* 包。"""
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _is_tool_registry(obj) -> bool:
    return obj is not None and hasattr(obj, "schemas") and hasattr(obj, "execute")


# 瞬态 HTTP 状态码：超时/冲突/限流/服务端故障应触发重试与熔断。
_TRANSIENT_STATUS = (408, 409, 425, 429)


def _is_transient_status(status) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return code in _TRANSIENT_STATUS or 500 <= code <= 599


def _validate_provider_payload(data, provider: str):
    """Reject error envelopes and malformed success bodies without leaking details."""
    if not isinstance(data, Mapping):
        raise ProviderProtocolError(
            f"{provider} returned a malformed response")
    if "error" in data and data.get("error") not in (None, False, ""):
        raise ProviderProtocolError(
            f"{provider} returned an error response")
    return data


def _validate_embeddings(vectors: Any, expected_count: int,
                         provider: str) -> List[List[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ProviderProtocolError(
            f"{provider} returned an invalid embedding count")
    normalized: List[List[float]] = []
    dimension = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ProviderProtocolError(
                f"{provider} returned an invalid embedding")
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError):
            raise ProviderProtocolError(
                f"{provider} returned a non-numeric embedding") from None
        if not all(math.isfinite(value) for value in converted):
            raise ProviderProtocolError(
                f"{provider} returned a non-finite embedding")
        if dimension is None:
            dimension = len(converted)
        elif len(converted) != dimension:
            raise ProviderProtocolError(
                f"{provider} returned inconsistent embedding dimensions")
        normalized.append(converted)
    return normalized


def _first_provider_choice(data: Mapping, provider: str) -> Mapping:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(
            choices[0], Mapping):
        raise ProviderProtocolError(
            f"{provider} returned a response without a valid choice")
    return choices[0]


def _http_post_json(url, *, json_body, headers=None, timeout,
                    max_retries, retry_delay_ms, circuit_breaker, provider,
                    max_response_size=10 * 1024 * 1024):
    """
    统一 HTTP POST + 重试 + 熔断（DRY 重构）。

    将网络连接失败/超时/429/5xx 归类为瞬态（TransientError → 重试 + 熔断计数），
    其余错误（如 401/403/400 鉴权或参数错误）原样抛出，不做无意义重试。

    修复：此前各 Provider 的 HTTP 调用逻辑重复且瞬态分类不一致
    （OllamaEmbeddingModel 漏掉 HTTPError 的 429/5xx 归类，导致瞬态不重试；
    OpenAI 流式对 401/403 也重试，浪费并掩盖真实错误）。
    """
    from springbootai.ai.resilience import resilient_call, TransientError
    import requests
    request_headers = dict(headers or {})
    supplied_request_id = next((
        value for key, value in request_headers.items()
        if key.lower() == "x-request-id"
    ), None)
    request_id = outbound_request_id(supplied_request_id)
    request_headers = {
        key: value for key, value in request_headers.items()
        if key.lower() != "x-request-id"
    }
    request_headers["X-Request-ID"] = request_id

    def _do_post():
        resp = None
        try:
            resp = _provider_post(
                url, json=json_body, headers=request_headers,
                timeout=timeout, stream=True, allow_redirects=False,
            )
            _reject_provider_redirect(resp, provider)
            resp.raise_for_status()
            response_headers = getattr(resp, "headers", {}) or {}
            declared_size = response_headers.get(
                "Content-Length", response_headers.get("content-length", ""))
            if declared_size:
                try:
                    if int(declared_size) > max_response_size:
                        raise ProviderResponseTooLargeError(
                            "AI provider response exceeds configured safety limit")
                except ValueError:
                    pass
            iterator = getattr(resp, "iter_content", None)
            if callable(iterator):
                chunks = []
                size = 0
                for chunk in iterator(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_response_size:
                        raise ProviderResponseTooLargeError(
                            "AI provider response exceeds configured safety limit")
                    chunks.append(chunk)
                return _validate_provider_payload(
                    json.loads(b"".join(chunks)), provider)
            content = getattr(resp, "content", None)
            if content is not None and len(content) > max_response_size:
                raise ProviderResponseTooLargeError(
                    "AI provider response exceeds configured safety limit")
            return _validate_provider_payload(resp.json(), provider)
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        ) as exc:
            raise TransientError(
                f"{provider} transport failure: {type(exc).__name__}") from exc
        except requests.HTTPError as exc:
            if _is_transient_status(getattr(resp, "status_code", None)):
                raise TransientError(
                    f"{provider} HTTP failure: status={resp.status_code}") from exc
            raise
        finally:
            closer = getattr(resp, "close", None)
            if callable(closer):
                closer()

    return resilient_call(
        _do_post, max_retries=max_retries, retry_delay_ms=retry_delay_ms,
        retry_exceptions=(TransientError,), circuit_breaker=circuit_breaker,
        count_as_failure_exc=(TransientError,), provider=provider,
    )()


def _is_transient_http_exc(exc, resp) -> bool:
    """判断流式场景下异常是否为瞬态（连接/超时/429/5xx）。"""
    import requests
    if isinstance(exc, (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        _IncompleteProviderStream,
    )):
        return True
    if isinstance(exc, requests.HTTPError):
        return _is_transient_status(getattr(resp, "status_code", None))
    return False


def _is_transient_provider_exc(exc: BaseException) -> bool:
    """Classify common SDK/LangChain transport and rate-limit failures."""
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
    except ImportError:  # pragma: no cover - httpx is a core dependency
        pass
    try:
        import requests
        if isinstance(exc, (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
            _IncompleteProviderStream,
        )):
            return True
    except ImportError:  # pragma: no cover
        pass
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    if _is_transient_status(status):
        return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in (
        "timeout", "connection", "ratelimit", "rate_limit",
        "internalserver", "serviceunavailable",
    ))


def _provider_invoke(func, *, max_retries: int, retry_delay_ms: int,
                     circuit_breaker, provider: str):
    """Apply the framework retry/circuit policy to an SDK/LangChain call."""
    from springbootai.ai.resilience import resilient_call, TransientError

    def invoke_once():
        try:
            return func()
        except Exception as exc:
            if _is_transient_provider_exc(exc):
                raise TransientError(
                    f"{provider} transient provider failure: {type(exc).__name__}"
                ) from exc
            raise

    return resilient_call(
        invoke_once,
        max_retries=max_retries,
        retry_delay_ms=retry_delay_ms,
        retry_exceptions=(TransientError,),
        circuit_breaker=circuit_breaker,
        count_as_failure_exc=(TransientError,),
        provider=provider,
    )()


def _provider_stream(factory, *, max_retries: int, retry_delay_ms: int,
                     circuit_breaker, provider: str):
    """Retry a provider stream only before its first emitted chunk."""
    from springbootai.ai.observability import ai_metrics
    from springbootai.ai.resilience import CircuitOpenError

    attempts = max(1, int(max_retries))
    if circuit_breaker is not None and not circuit_breaker.allow():
        ai_metrics.record_circuit_state(provider, circuit_breaker.state)
        raise CircuitOpenError(f"AI provider circuit is open: {provider}")

    for attempt in range(attempts):
        emitted = False
        try:
            for item in factory():
                emitted = True
                yield item
            if circuit_breaker is not None:
                circuit_breaker.record_success()
                ai_metrics.record_circuit_state(provider, "CLOSED")
            return
        except Exception as exc:
            transient = _is_transient_provider_exc(exc)
            if emitted:
                if circuit_breaker is not None and transient:
                    circuit_breaker.record_failure()
                    ai_metrics.record_circuit_state(
                        provider, circuit_breaker.state)
                raise ProviderStreamError(
                    f"{provider} stream interrupted after partial response; "
                    "retry the request"
                ) from exc
            if not transient:
                raise
            if attempt >= attempts - 1:
                if circuit_breaker is not None:
                    circuit_breaker.record_failure()
                    ai_metrics.record_circuit_state(
                        provider, circuit_breaker.state)
                raise ProviderStreamError(
                    f"{provider} stream unavailable after retry"
                ) from exc
            time.sleep(max(0, retry_delay_ms) / 1000.0)


def _stream_circuit_start(circuit_breaker, provider: str) -> None:
    if circuit_breaker is None:
        return
    if not circuit_breaker.allow():
        from springbootai.ai.observability import ai_metrics
        from springbootai.ai.resilience import CircuitOpenError
        ai_metrics.record_circuit_state(provider, circuit_breaker.state)
        raise CircuitOpenError(f"AI provider circuit is open: {provider}")


def _stream_circuit_result(circuit_breaker, provider: str, success: bool) -> None:
    if circuit_breaker is None:
        return
    from springbootai.ai.observability import ai_metrics
    if success:
        circuit_breaker.record_success()
        ai_metrics.record_circuit_state(provider, "CLOSED")
    else:
        circuit_breaker.record_failure()
        ai_metrics.record_circuit_state(provider, circuit_breaker.state)


def _messages_to_langchain(messages: List[Message]):
    """Preserve assistant tool calls and tool_call_id across model turns."""
    from langchain_core.messages import (
        AIMessage, HumanMessage, SystemMessage, ToolMessage,
    )

    converted = []
    for message in messages:
        if message.type == MessageType.SYSTEM:
            converted.append(SystemMessage(content=message.content))
        elif message.type == MessageType.ASSISTANT:
            tool_calls = []
            for item in message.metadata.get("tool_calls", []) or []:
                function = item.get("function", {}) if isinstance(item, Mapping) else {}
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                tool_calls.append({
                    "name": function.get("name", ""),
                    "args": arguments if isinstance(arguments, dict) else {},
                    "id": item.get("id", ""),
                    "type": "tool_call",
                })
            converted.append(AIMessage(
                content=message.content, tool_calls=tool_calls or []))
        elif message.type == MessageType.TOOL:
            converted.append(ToolMessage(
                content=message.content,
                tool_call_id=str(message.metadata.get("tool_call_id", "")),
                name=message.name or None,
            ))
        else:
            converted.append(HumanMessage(content=message.content))
    return converted


# ==================== OpenAI 兼容 ====================

class OpenAIChatModel(ChatModel):
    """
    OpenAI 兼容聊天模型 - 支持 OpenAI / Azure / DeepSeek / Moonshot 等兼容接口。

    企业能力：函数调用闭环 / 真流式 / 重试 / 熔断 / Prometheus 观测。
    """

    # 函数调用最大往返轮数（防止模型无限调用工具）
    MAX_TOOL_ITERATIONS = 5

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "gpt-4o-mini", temperature: float = 0.7,
                 timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None, max_output_tokens: int = 4096,
                 max_total_tokens: int = 100_000,
                 max_tool_iterations: int = 5):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self.max_output_tokens = max_output_tokens
        self.max_total_tokens = max_total_tokens
        self.max_tool_iterations = max_tool_iterations
        self._llm = None
        if _has_langchain_openai() and api_key:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    api_key=api_key,
                    base_url=self.base_url if base_url else None,
                    model=model, temperature=temperature, timeout=timeout,
                    max_tokens=max_output_tokens,
                    # Framework resilience owns the retry budget. Disable the
                    # SDK default to avoid multiplicative hidden retries.
                    max_retries=0,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "ChatOpenAI 初始化失败，降级原生HTTP error_type=%s",
                    type(exc).__name__,
                )
                self._llm = None

    # ---------- 公共入口 ----------

    def call(self, messages: List[Message],
             tool_registry=None,
             options: Optional[Dict[str, Any]] = None,
             context: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """同步调用（基类闭环 + 整体指标）"""
        from springbootai.ai.observability import ai_metrics
        start = time.time()
        try:
            resp = super().call(messages, tool_registry, options, context)
            usage = (resp.metadata or {}).get("usage") if resp else None
            ai_metrics.record_call("openai", self.model, "success",
                                   time.time() - start, usage)
            return resp
        except Exception:
            ai_metrics.record_call("openai", self.model, "failure",
                                   time.time() - start)
            raise

    async def acall(self, messages: List[Message],
                    tool_registry=None,
                    options: Optional[Dict[str, Any]] = None,
                    context: Optional[Dict[str, Any]] = None) -> ChatResponse:
        import asyncio
        return await asyncio.to_thread(
            self.call, messages, tool_registry, options, context)

    def stream(self, messages: List[Message],
               tool_registry=None,
               options: Optional[Dict[str, Any]] = None):
        """真流式 - SSE 增量生成器"""
        tool_response = self._stream_tool_loop_response(
            messages, tool_registry, options)
        if tool_response is not None:
            yield tool_response
            return
        provider_options, budget, initial = self._prepare_stream_request(
            messages, tool_registry, options)
        with self._provider_capacity():
            if self._llm is not None:
                iterator = self._stream_via_langchain(
                    messages, provider_options)
            else:
                iterator = self._stream_via_http(messages, provider_options)
            yield from _observed_stream(
                self._bounded_stream(iterator, budget, initial),
                provider="openai", model=self.model,
            )

    async def astream(self, messages: List[Message],
                      tool_registry=None,
                      options: Optional[Dict[str, Any]] = None):
        # Reuse the pull-based bridge from ChatModel: one in-flight chunk,
        # ContextVar propagation and best-effort iterator close on aclose.
        async for chunk in super().astream(
                messages, tool_registry=tool_registry, options=options):
            yield chunk

    # ---------- Provider 单次调用 ----------

    def _raw_call(self, messages, tool_registry=None, options=None) -> ChatResponse:
        if self._llm is not None:
            return self._call_via_langchain(messages, tool_registry, options)
        return self._call_via_http(messages, tool_registry, options)

    def _call_via_langchain(self, messages, tool_registry, options) -> ChatResponse:
        lc_messages = _messages_to_langchain(messages)
        # 传递 tool_registry：若 langchain-openai 版本支持 bind_tools，
        # 把 ToolRegistry 的 schema 绑定到 LLM，使 Function Calling 在 LangChain 路径下也生效
        llm = self._llm
        if tool_registry is not None and hasattr(tool_registry, "schemas"):
            try:
                schemas = tool_registry.schemas()
                if schemas:
                    # bind_tools returns a request-local Runnable. Never mutate
                    # the shared model bean across concurrent requests.
                    llm = self._llm.bind_tools(schemas)
            except Exception as exc:
                raise RuntimeError("LangChain provider cannot bind tool schemas") from exc
        llm = _bind_request_options(
            llm, options, self.max_output_tokens, "openai")
        result = _provider_invoke(
            lambda: llm.invoke(lc_messages),
            max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider="openai",
        )
        content = result.content if hasattr(result, "content") else str(result)
        usage = getattr(result, "usage_metadata", None) or {}
        # 提取 langchain 返回的 tool_calls（如有）
        tool_calls = self._extract_lc_tool_calls(result)
        meta = {"provider": "openai", "backend": "langchain", "usage": usage}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta,
        )

    @staticmethod
    def _extract_lc_tool_calls(result) -> Optional[List[Dict]]:
        """从 langchain AIMessage 提取 tool_calls（兼容 langchain 1.x 格式）。"""
        lc_tc = getattr(result, "tool_calls", None) or []
        if not lc_tc:
            return None
        out = []
        for tc in lc_tc:
            if isinstance(tc, Mapping):
                tool_id = tc.get("id", "") or ""
                name = tc.get("name", "") or ""
                arguments = tc.get("args", {}) or {}
            else:
                tool_id = getattr(tc, "id", "") or ""
                name = getattr(tc, "name", "") or ""
                arguments = getattr(tc, "args", {}) or {}
            if not name:
                logger.warning("Ignoring malformed LangChain tool call without a name")
                continue
            out.append({
                "id": tool_id,
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            })
        return out if out else None

    def _stream_via_langchain(self, messages, options):
        if self._llm is None:
            return
        llm = _bind_request_options(
            self._llm, options, self.max_output_tokens, "openai")

        def factory():
            for chunk in llm.stream(_messages_to_langchain(messages)):
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                if content:
                    yield ChatResponse(generations=[Generation(
                        output=Message.assistant(content))],
                        metadata={"provider": "openai", "stream": True})

        yield from _provider_stream(
            factory, max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker, provider="openai",
        )

    def _call_via_http(self, messages, tool_registry, options) -> ChatResponse:
        """单次 HTTP 调用 - 注入 tools schema，解析 tool_calls 到 metadata"""
        payload = {
            "model": self.model,
            "messages": [self._serialize_msg(m) for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        payload.update(_openai_request_options(
            options, self.max_output_tokens))
        # A generic options dictionary must not change this method's wire mode.
        payload["stream"] = False
        # 注入 tools schema（基类闭环依赖此）
        if _is_tool_registry(tool_registry) and tool_registry.names():
            payload["tools"] = tool_registry.schemas()

        data = _http_post_json(
            f"{self.base_url}/chat/completions",
            json_body=payload,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider="openai",
        )

        choice = _first_provider_choice(data, "openai")
        msg_obj = choice.get("message", {})
        if not isinstance(msg_obj, Mapping):
            raise ProviderProtocolError(
                "openai returned a response without a valid message")
        tool_calls = msg_obj.get("tool_calls")
        usage = data.get("usage", {})
        content = msg_obj.get("content", "") or ""
        meta = {"provider": "openai", "backend": "http", "usage": usage}
        if tool_calls:
            # 标记 tool_calls，由基类 call() 闭环执行；assistant 消息保留 tool_calls 元数据以便重发
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta,
        )

    def _stream_via_http(self, messages, options):
        """真流式：解析 SSE data: 行，逐块 yield 增量内容（含网络中断重试降级）"""
        import requests
        import time as _time
        payload = {
            "model": self.model,
            "messages": [self._serialize_msg(m) for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "stream": True,
        }
        payload.update(_openai_request_options(
            options, self.max_output_tokens))
        # A generic options dictionary must not change this method's wire mode.
        payload["stream"] = True
        _stream_circuit_start(self.circuit_breaker, "openai")
        max_attempts = max(1, self.max_retries)
        request_id = outbound_request_id()
        for attempt in range(max_attempts):
            emitted = False
            try:
                with _provider_post(
                    f"{self.base_url}/chat/completions", json=payload, stream=True,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json",
                             "X-Request-ID": request_id},
                    timeout=self.timeout, allow_redirects=False,
                ) as resp:
                    _register_stream_cancel(getattr(resp, "close", None))
                    _reject_provider_redirect(resp, "openai")
                    resp.raise_for_status()
                    for line in _bounded_stream_lines(resp, "openai"):
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            _stream_circuit_result(
                                self.circuit_breaker, "openai", True)
                            return
                        try:
                            chunk = _validate_provider_payload(
                                json.loads(data_str), "openai")
                        except json.JSONDecodeError as exc:
                            raise ProviderProtocolError(
                                "openai returned an invalid stream event"
                            ) from exc
                        choices = chunk.get("choices") or []
                        # With stream_options.include_usage=true OpenAI sends
                        # a final usage-only chunk whose choices list is empty.
                        if not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, Mapping):
                            raise ProviderProtocolError(
                                "openai returned an invalid stream event")
                        delta_obj = choice.get("delta") or {}
                        if not isinstance(delta_obj, Mapping):
                            raise ProviderProtocolError(
                                "openai returned an invalid stream event")
                        delta = delta_obj.get("content", "")
                        if delta:
                            emitted = True
                            yield ChatResponse(
                                generations=[Generation(output=Message.assistant(delta))],
                                metadata={"provider": "openai", "stream": True},
                            )
                # A clean TCP EOF is not a protocol completion. Accepting it
                # would return a plausible but truncated answer as success.
                raise _IncompleteProviderStream(
                    "openai stream ended before the completion marker")
            except Exception as exc:
                if emitted:
                    _stream_circuit_result(
                        self.circuit_breaker, "openai", False)
                    raise ProviderStreamError(
                        "openai stream interrupted after partial response; retry the request"
                    ) from exc
                # 仅对瞬态（连接/超时/429/5xx）重试；401/403/400 等永久错误直接抛
                if not _is_transient_http_exc(exc, locals().get("resp", None)):
                    raise
                logger.warning(
                    "流式 SSE 第 %d 次尝试失败 error_type=%s",
                    attempt + 1, type(exc).__name__,
                )
                if attempt < max_attempts - 1:
                    _time.sleep(max(0, self.retry_delay_ms) / 1000.0)
                    continue
                logger.error("流式 SSE 重试耗尽: %s", type(exc).__name__)
                _stream_circuit_result(
                    self.circuit_breaker, "openai", False)
                raise ProviderStreamError(
                    "openai stream unavailable after retry"
                ) from exc

    # ---------- 消息序列化 ----------

    def _serialize_msg(self, m: Message) -> Dict[str, Any]:
        d = m.to_dict()
        if m.type == MessageType.TOOL:
            d["role"] = "tool"
            if m.metadata.get("tool_call_id"):
                d["tool_call_id"] = m.metadata["tool_call_id"]
        # assistant 消息携带 tool_calls 时重发（OpenAI 协议要求）
        if m.type == MessageType.ASSISTANT and m.metadata.get("tool_calls"):
            d["tool_calls"] = m.metadata["tool_calls"]
        return d


class OpenAIEmbeddingModel(EmbeddingModel):
    """OpenAI 兼容嵌入模型"""

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "text-embedding-3-small", timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self._embedder = None
        if _has_langchain_openai() and api_key:
            try:
                from langchain_openai import OpenAIEmbeddings
                self._embedder = OpenAIEmbeddings(
                    api_key=api_key,
                    base_url=self.base_url if base_url else None,
                    model=model,
                    timeout=timeout,
                    max_retries=0,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "OpenAIEmbeddings 初始化失败，降级HTTP error_type=%s",
                    type(exc).__name__,
                )
                self._embedder = None

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self._embedder is not None:
            vectors = _provider_invoke(
                lambda: self._embedder.embed_documents(texts),
                max_retries=self.max_retries,
                retry_delay_ms=self.retry_delay_ms,
                circuit_breaker=self.circuit_breaker,
                provider="openai-embedding",
            )
            return _validate_embeddings(vectors, len(texts), "openai")
        return self._embed_via_http(texts)

    def _embed_via_http(self, texts: List[str]) -> List[List[float]]:
        data = _http_post_json(
            f"{self.base_url}/embeddings",
            json_body={"model": self.model, "input": texts},
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider="openai",
        )
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderProtocolError(
                "openai returned an invalid embedding response")
        ordered = []
        for position, item in enumerate(items):
            if not isinstance(item, Mapping) or "embedding" not in item:
                raise ProviderProtocolError(
                    "openai returned an invalid embedding response")
            try:
                index = int(item.get("index", position))
            except (TypeError, ValueError):
                raise ProviderProtocolError(
                    "openai returned an invalid embedding index") from None
            ordered.append((index, item["embedding"]))
        ordered.sort(key=lambda entry: entry[0])
        if [index for index, _ in ordered] != list(range(len(texts))):
            raise ProviderProtocolError(
                "openai returned duplicate or missing embedding indices")
        return _validate_embeddings(
            [vector for _, vector in ordered], len(texts), "openai")


# ==================== OpenAI 兼容多 Provider（DeepSeek/Moonshot/ZhipuAI） ====================

class OpenAICompatChatModel(ChatModel):
    """
    OpenAI 兼容多厂商聊天模型 - 对齐"能用 LangChain 就用 LangChain"方向。

    用于 DeepSeek / Moonshot(Kimi) / ZhipuAI(GLM) 等提供 OpenAI 兼容
    /chat/completions 接口的厂商：
    - 优先：若安装了对应的专用 langchain-* 包（langchain_deepseek /
      langchain_moonshot / langchain_zhipuai）且配置了 api_key，
      则经 LangChain 调用（backend=langchain），复用其成熟生态
    - 降级：未安装/初始化失败时走原生 HTTP（backend=http），
      统一复用 _http_post_json 的重试/熔断/工具闭环，保证开箱即用

    参数 langchain_module / langchain_class 指定要优先使用的 LangChain 包，
    未指定或不可用时自动回退 HTTP。
    """

    def __init__(self, provider: str, api_key: str = "", base_url: str = "",
                 model: str = "", temperature: float = 0.7, timeout: int = 120,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None, langchain_module: Optional[str] = None,
                 langchain_class: str = "", default_base_url: str = "",
                 default_model: str = "", max_output_tokens: int = 4096,
                 max_total_tokens: int = 100_000,
                 max_tool_iterations: int = 5):
        self._provider = provider
        self.api_key = api_key
        self.base_url = (base_url or default_base_url).rstrip("/")
        self.model = model or default_model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self.max_output_tokens = max_output_tokens
        self.max_total_tokens = max_total_tokens
        self.max_tool_iterations = max_tool_iterations
        self._llm = None
        if langchain_module and api_key and _has_langchain(langchain_module):
            try:
                mod = __import__(langchain_module, fromlist=[langchain_class])
                cls = getattr(mod, langchain_class)
                kwargs: Dict[str, Any] = {
                    "api_key": api_key, "model": self.model,
                    "temperature": temperature, "timeout": timeout,
                    "max_tokens": max_output_tokens,
                }
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._llm = cls(**kwargs)
            except Exception as exc:  # pragma: no cover
                logger.warning("%s LangChain 初始化失败，降级HTTP: %s",
                               provider, exc)
                self._llm = None

    def call(self, messages, tool_registry=None, options=None, context=None):
        """同步调用（基类闭环 + 整体指标）"""
        from springbootai.ai.observability import ai_metrics
        start = time.time()
        try:
            resp = super().call(messages, tool_registry, options, context)
            usage = (resp.metadata or {}).get("usage") if resp else None
            ai_metrics.record_call(self._provider, self.model, "success",
                                   time.time() - start, usage)
            return resp
        except Exception:
            ai_metrics.record_call(self._provider, self.model, "failure",
                                   time.time() - start)
            raise

    def _raw_call(self, messages, tool_registry=None, options=None):
        if self._llm is not None:
            return self._call_via_langchain(messages, tool_registry, options)
        return self._call_via_http(messages, tool_registry, options)

    def _call_via_langchain(self, messages, tool_registry, options):
        """LangChain 路径：传递 tool_registry 使 Function Calling 生效。"""
        lc_msgs = _messages_to_langchain(messages)
        llm = self._llm
        if tool_registry is not None and hasattr(tool_registry, "schemas"):
            try:
                schemas = tool_registry.schemas()
                if schemas:
                    llm = self._llm.bind_tools(schemas)
            except Exception as exc:
                raise RuntimeError(
                    f"{self._provider} LangChain provider cannot bind tool schemas"
                ) from exc
        llm = _bind_request_options(
            llm, options, self.max_output_tokens, self._provider)
        result = _provider_invoke(
            lambda: llm.invoke(lc_msgs),
            max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider=self._provider,
        )
        content = result.content if hasattr(result, "content") else str(result)
        tool_calls = OpenAIChatModel._extract_lc_tool_calls(result)
        meta = {"provider": self._provider, "backend": "langchain",
                "usage": getattr(result, "usage_metadata", None) or {}}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta)

    def _call_via_http(self, messages, tool_registry, options):
        payload = {"model": self.model,
                   "messages": [self._serialize_msg(m) for m in messages],
                   "temperature": self.temperature,
                   "max_tokens": self.max_output_tokens}
        payload.update(_openai_request_options(
            options, self.max_output_tokens))
        payload["stream"] = False
        if _is_tool_registry(tool_registry) and tool_registry.names():
            payload["tools"] = tool_registry.schemas()

        data = _http_post_json(
            f"{self.base_url}/chat/completions",
            json_body=payload,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=self.timeout, max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider=self._provider,
        )
        choice = _first_provider_choice(data, self._provider)
        msg_obj = choice.get("message", {})
        if not isinstance(msg_obj, Mapping):
            raise ProviderProtocolError(
                f"{self._provider} returned a response without a valid message")
        tool_calls = msg_obj.get("tool_calls")
        content = msg_obj.get("content", "") or ""
        meta = {"provider": self._provider, "backend": "http",
                "usage": data.get("usage", {})}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta)

    def stream(self, messages, tool_registry=None, options=None):
        tool_response = self._stream_tool_loop_response(
            messages, tool_registry, options)
        if tool_response is not None:
            yield tool_response
            return
        provider_options, budget, initial = self._prepare_stream_request(
            messages, tool_registry, options)
        with self._provider_capacity():
            if self._llm is not None:
                llm = _bind_request_options(
                    self._llm, provider_options,
                    self.max_output_tokens, self._provider)

                def factory():
                    for chunk in llm.stream(_messages_to_langchain(messages)):
                        content = (chunk.content if hasattr(chunk, "content")
                                   else str(chunk))
                        if content:
                            yield ChatResponse(
                                generations=[Generation(
                                    output=Message.assistant(content))],
                                metadata={"provider": self._provider,
                                          "stream": True})

                iterator = _provider_stream(
                    factory, max_retries=self.max_retries,
                    retry_delay_ms=self.retry_delay_ms,
                    circuit_breaker=self.circuit_breaker,
                    provider=self._provider,
                )
            else:
                iterator = self._stream_via_http(
                    messages, provider_options)
            yield from _observed_stream(
                self._bounded_stream(iterator, budget, initial),
                provider=self._provider, model=self.model,
            )

    def _stream_via_http(self, messages, options):
        import requests
        import time as _time
        payload = {"model": self.model, "temperature": self.temperature,
                   "messages": [self._serialize_msg(m) for m in messages],
                   "max_tokens": self.max_output_tokens,
                   "stream": True}
        payload.update(_openai_request_options(
            options, self.max_output_tokens))
        payload["stream"] = True
        _stream_circuit_start(self.circuit_breaker, self._provider)
        max_attempts = max(1, self.max_retries)
        request_id = outbound_request_id()
        for attempt in range(max_attempts):
            emitted = False
            try:
                with _provider_post(
                    f"{self.base_url}/chat/completions", json=payload,
                    stream=True,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json",
                             "X-Request-ID": request_id},
                    timeout=self.timeout, allow_redirects=False,
                ) as resp:
                    _register_stream_cancel(getattr(resp, "close", None))
                    _reject_provider_redirect(resp, self._provider)
                    resp.raise_for_status()
                    for line in _bounded_stream_lines(resp, self._provider):
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            _stream_circuit_result(
                                self.circuit_breaker, self._provider, True)
                            return
                        try:
                            chunk = _validate_provider_payload(
                                json.loads(data_str), self._provider)
                        except json.JSONDecodeError as exc:
                            raise ProviderProtocolError(
                                f"{self._provider} returned an invalid stream event"
                            ) from exc
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        if not isinstance(choice, Mapping):
                            raise ProviderProtocolError(
                                f"{self._provider} returned an invalid stream event")
                        delta_obj = choice.get("delta") or {}
                        if not isinstance(delta_obj, Mapping):
                            raise ProviderProtocolError(
                                f"{self._provider} returned an invalid stream event")
                        delta = delta_obj.get("content", "")
                        if delta:
                            emitted = True
                            yield ChatResponse(
                                generations=[Generation(output=Message.assistant(delta))],
                                metadata={"provider": self._provider, "stream": True})
                raise _IncompleteProviderStream(
                    f"{self._provider} stream ended before the completion marker")
            except Exception as exc:
                if emitted:
                    _stream_circuit_result(
                        self.circuit_breaker, self._provider, False)
                    raise ProviderStreamError(
                        f"{self._provider} stream interrupted after partial response; "
                        "retry the request"
                    ) from exc
                if not _is_transient_http_exc(exc, locals().get("resp", None)):
                    raise
                logger.warning(
                    "%s 流式第 %d 次尝试失败 error_type=%s",
                    self._provider, attempt + 1, type(exc).__name__,
                )
                if attempt < max_attempts - 1:
                    _time.sleep(max(0, self.retry_delay_ms) / 1000.0)
                    continue
                _stream_circuit_result(
                    self.circuit_breaker, self._provider, False)
                raise ProviderStreamError(
                    f"{self._provider} stream unavailable after retry"
                ) from exc

    def _serialize_msg(self, m: Message) -> Dict[str, Any]:
        d = m.to_dict()
        if m.type == MessageType.TOOL:
            d["role"] = "tool"
            if m.metadata.get("tool_call_id"):
                d["tool_call_id"] = m.metadata["tool_call_id"]
        if m.type == MessageType.ASSISTANT and m.metadata.get("tool_calls"):
            d["tool_calls"] = m.metadata["tool_calls"]
        return d


# ==================== Ollama ====================

class OllamaChatModel(ChatModel):
    """Ollama 本地聊天模型（Llama3/Qwen/Phi3 等）"""

    MAX_TOOL_ITERATIONS = 5

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "llama3", temperature: float = 0.7,
                 timeout: int = 120, max_retries: int = 3,
                 retry_delay_ms: int = 500, circuit_breaker=None,
                 max_output_tokens: int = 4096,
                 max_total_tokens: int = 100_000,
                 max_tool_iterations: int = 5):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self.max_output_tokens = max_output_tokens
        self.max_total_tokens = max_total_tokens
        self.max_tool_iterations = max_tool_iterations
        self._llm = None
        if _has_langchain_community():
            try:
                from langchain_community.chat_models import ChatOllama
                self._llm = ChatOllama(
                    base_url=self.base_url, model=model,
                    temperature=temperature, timeout=timeout,
                    num_predict=max_output_tokens,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "ChatOllama 初始化失败，降级HTTP error_type=%s",
                    type(exc).__name__,
                )
                self._llm = None

    def call(self, messages, tool_registry=None, options=None, context=None):
        """同步调用（基类闭环 + 整体指标）"""
        from springbootai.ai.observability import ai_metrics
        start = time.time()
        try:
            resp = super().call(messages, tool_registry, options, context)
            ai_metrics.record_call("ollama", self.model, "success",
                                   time.time() - start)
            return resp
        except Exception:
            ai_metrics.record_call("ollama", self.model, "failure",
                                   time.time() - start)
            raise

    def _raw_call(self, messages, tool_registry=None, options=None):
        if self._llm is not None:
            lc_messages = _messages_to_langchain(messages)
            llm = self._llm
            if _is_tool_registry(tool_registry) and tool_registry.names():
                if not hasattr(llm, "bind_tools"):
                    raise RuntimeError("Ollama LangChain provider cannot bind tools")
                llm = llm.bind_tools(tool_registry.schemas())
            result = _provider_invoke(
                lambda: llm.invoke(lc_messages),
                max_retries=self.max_retries,
                retry_delay_ms=self.retry_delay_ms,
                circuit_breaker=self.circuit_breaker,
                provider="ollama",
            )
            content = result.content if hasattr(result, "content") else str(result)
            tool_calls = OpenAIChatModel._extract_lc_tool_calls(result)
            return ChatResponse(
                generations=[Generation(output=Message(
                    content=content, type=MessageType.ASSISTANT,
                    metadata={"tool_calls": tool_calls or []}))],
                metadata={"provider": "ollama", "backend": "langchain",
                          "usage": getattr(result, "usage_metadata", None) or {},
                          **({"tool_calls": tool_calls} if tool_calls else {})})
        return self._call_via_http(
            messages, options=options, tool_registry=tool_registry)

    def _serialize_msg(self, message: Message) -> Dict[str, Any]:
        data = message.to_dict()
        if (message.type == MessageType.ASSISTANT
                and message.metadata.get("tool_calls")):
            data["tool_calls"] = message.metadata["tool_calls"]
        return data

    def _request_payload(self, messages, options, *, stream: bool):
        if options is not None and not isinstance(options, Mapping):
            raise ValueError("Ollama options must be a mapping")
        provider_options = dict(options or {})
        for reserved in (
                "model", "messages", "tools", "stream",
                "max_total_tokens", "max_tool_iterations"):
            provider_options.pop(reserved, None)
        nested_options = provider_options.pop("options", {})
        if nested_options is None:
            nested_options = {}
        if not isinstance(nested_options, Mapping):
            raise ValueError("Ollama options must be a mapping")
        ollama_options = {
            "temperature": self.temperature,
            "num_predict": self.max_output_tokens,
        }
        ollama_options.update(nested_options)
        # PromptSpec.option("seed", ...) and similar request-scoped Ollama
        # generation options belong in Ollama's nested options object.
        ollama_options.update(provider_options)
        try:
            requested_output = int(ollama_options["num_predict"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Ollama num_predict must be a positive integer") from exc
        if requested_output <= 0:
            raise ValueError("Ollama num_predict must be a positive integer")
        ollama_options["num_predict"] = min(
            requested_output, int(self.max_output_tokens))
        return {
            "model": self.model,
            "stream": stream,
            "messages": [self._serialize_msg(m) for m in messages],
            "options": ollama_options,
        }

    def _call_via_http(self, messages, options=None, tool_registry=None):
        payload = self._request_payload(messages, options, stream=False)
        if _is_tool_registry(tool_registry) and tool_registry.names():
            payload["tools"] = tool_registry.schemas()
        data = _http_post_json(
            f"{self.base_url}/api/chat",
            json_body=payload,
            timeout=self.timeout,
            max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            circuit_breaker=self.circuit_breaker,
            provider="ollama",
        )
        message_obj = data.get("message") or {}
        if not isinstance(message_obj, Mapping):
            raise ProviderProtocolError(
                "ollama returned a response without a valid message")
        content = message_obj.get("content", "")
        tool_calls = message_obj.get("tool_calls") or None
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata={"provider": "ollama", "backend": "http", "usage": usage,
                      **({"tool_calls": tool_calls} if tool_calls else {})})

    def stream(self, messages, tool_registry=None, options=None):
        tool_response = self._stream_tool_loop_response(
            messages, tool_registry, options)
        if tool_response is not None:
            yield tool_response
            return
        provider_options, budget, initial = self._prepare_stream_request(
            messages, tool_registry, options)
        with self._provider_capacity():
            yield from _observed_stream(
                self._bounded_stream(
                    self._stream_impl(messages, provider_options),
                    budget, initial,
                ),
                provider="ollama", model=self.model,
            )

    def _stream_impl(self, messages, options):
        import requests
        import time as _time
        payload = self._request_payload(messages, options, stream=True)
        _stream_circuit_start(self.circuit_breaker, "ollama")
        max_attempts = max(1, self.max_retries)
        request_id = outbound_request_id()
        for attempt in range(max_attempts):
            emitted = False
            try:
                with _provider_post(
                    f"{self.base_url}/api/chat", stream=True, timeout=self.timeout,
                    headers={"X-Request-ID": request_id},
                    json=payload, allow_redirects=False,
                ) as resp:
                    _register_stream_cancel(getattr(resp, "close", None))
                    _reject_provider_redirect(resp, "ollama")
                    resp.raise_for_status()
                    for line in _bounded_stream_lines(resp, "ollama"):
                        if not line:
                            continue
                        try:
                            chunk = _validate_provider_payload(
                                json.loads(line), "ollama")
                        except json.JSONDecodeError as exc:
                            raise ProviderProtocolError(
                                "ollama returned an invalid stream event"
                            ) from exc
                        message_obj = chunk.get("message") or {}
                        if not isinstance(message_obj, Mapping):
                            raise ProviderProtocolError(
                                "ollama returned an invalid stream event")
                        delta = message_obj.get("content", "")
                        if delta:
                            emitted = True
                            yield ChatResponse(
                                generations=[Generation(output=Message.assistant(delta))],
                                metadata={"provider": "ollama", "stream": True})
                        if chunk.get("done") is True:
                            _stream_circuit_result(
                                self.circuit_breaker, "ollama", True)
                            return
                raise _IncompleteProviderStream(
                    "ollama stream ended before the completion marker")
            except Exception as exc:
                if emitted:
                    _stream_circuit_result(
                        self.circuit_breaker, "ollama", False)
                    raise ProviderStreamError(
                        "ollama stream interrupted after partial response; retry the request"
                    ) from exc
                # 仅对瞬态（连接/超时/429/5xx）重试；其余错误直接抛
                if not _is_transient_http_exc(exc, locals().get("resp", None)):
                    raise
                logger.warning(
                    "Ollama 流式第 %d 次尝试失败 error_type=%s",
                    attempt + 1, type(exc).__name__,
                )
                if attempt < max_attempts - 1:
                    _time.sleep(max(0, self.retry_delay_ms) / 1000.0)
                    continue
                logger.error("Ollama 流式重试耗尽: %s", type(exc).__name__)
                _stream_circuit_result(
                    self.circuit_breaker, "ollama", False)
                raise ProviderStreamError(
                    "ollama stream unavailable after retry"
                ) from exc


class OllamaEmbeddingModel(EmbeddingModel):
    """Ollama 嵌入模型"""

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "llama3", timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker

    def embed(self, texts: List[str]) -> List[List[float]]:
        def _embed_one(text):
            data = _http_post_json(
                f"{self.base_url}/api/embeddings",
                json_body={"model": self.model, "prompt": text},
                timeout=self.timeout,
                max_retries=self.max_retries,
                retry_delay_ms=self.retry_delay_ms,
                circuit_breaker=self.circuit_breaker,
                provider="ollama",
            )
            return _validate_embeddings(
                [data.get("embedding", [])], 1, "ollama")[0]

        return _validate_embeddings(
            [_embed_one(t) for t in texts], len(texts), "ollama")


# ==================== 测试用 Fake ====================

class FakeChatModel(ChatModel):
    """
    确定性聊天模型 - 测试用，不依赖网络。
    回复 echo 输入的最后一句话。
    支持模拟函数调用：当 tool_registry 非空且用户消息含 "调用工具" 时，
    第一轮在 metadata['tool_calls'] 标记工具调用（由基类闭环执行），
    下一轮返回工具结果摘要，验证闭环。
    """

    def __init__(self, prefix: str = "AI:", simulate_tool_call: bool = False):
        self.prefix = prefix
        self.simulate_tool_call = simulate_tool_call
        self.call_count = 0
        # Synthetic LangChain agent tests deliberately echo their full prompt
        # over several parser-recovery rounds. Keep production model defaults
        # bounded while giving the non-network fake enough headroom to reach
        # AgentExecutor's own iteration limit.
        self.max_total_tokens = 1_000_000

    def _raw_call(self, messages, tool_registry=None, options=None):
        self.call_count += 1
        last_user = ""
        for msg in reversed(messages):
            if msg.type == "user":
                last_user = msg.content
                break

        # 模拟函数调用闭环：检测 tool 消息回填后给出最终回复
        has_tool_result = any(m.type == MessageType.TOOL for m in messages)
        if (self.simulate_tool_call and _is_tool_registry(tool_registry)
                and "调用工具" in last_user and not has_tool_result
                and tool_registry.names()):
            # 第一轮：在 metadata 标记 tool_calls，基类 call() 闭环执行
            tool_name = tool_registry.names()[0]
            return ChatResponse(
                generations=[Generation(output=Message(
                    content=f"[需要调用工具 {tool_name}]",
                    type=MessageType.ASSISTANT,
                    metadata={"tool_calls": [{"id": "call_fake",
                                              "function": {"name": tool_name,
                                                           "arguments": "{}"}}]}))],
                metadata={"provider": "fake", "tool_calls": [
                    {"id": "call_fake",
                     "function": {"name": tool_name, "arguments": "{}"}}]},
            )

        # 普通回复或工具回填后回复
        content = f"{self.prefix} {last_user}"
        if has_tool_result:
            tool_msgs = [m for m in messages if m.type == MessageType.TOOL]
            content = f"{self.prefix} 工具返回: {tool_msgs[-1].content}"
        return ChatResponse(
            generations=[Generation(output=Message.assistant(content))],
            metadata={"provider": "fake", "call_count": self.call_count},
        )

    def stream(self, messages, tool_registry=None, options=None):
        """模拟流式：普通回复逐 2 字符，工具调用安全降级为最终回复。"""
        tool_response = self._stream_tool_loop_response(
            messages, tool_registry, options)
        if tool_response is not None:
            yield tool_response
            return
        provider_options, budget, initial = self._prepare_stream_request(
            messages, tool_registry, options)

        def chunks():
            resp = self._raw_call(messages, tool_registry, provider_options)
            content = resp.content()
            for i in range(0, len(content), 2):
                yield ChatResponse(
                    generations=[Generation(
                        output=Message.assistant(content[i:i+2]))],
                    metadata={"provider": "fake", "stream": True},
                )

        with self._provider_capacity():
            yield from self._bounded_stream(chunks(), budget, initial)


class FakeEmbeddingModel(EmbeddingModel):
    """确定性嵌入模型 - 哈希到固定维度向量，测试用"""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.call_count = 0

    def embed(self, texts: List[str]) -> List[List[float]]:
        self.call_count += 1
        results = []
        for text in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(text):
                vec[i % self.dim] += (ord(ch) % 10) / 10.0
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results
