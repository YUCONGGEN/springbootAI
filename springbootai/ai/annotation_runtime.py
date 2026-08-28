"""AI 注解运行时。

这里集中实现 AI 注解的执行语义，BeanFactory 只负责把包装器接入已有的
方法代理链。所有依赖均在调用时惰性解析，因此 AI 可选模块没有配置时不会
影响普通 Bean 启动。
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from springbootai.ai.annotations import (
    Agent, AiCache, AiRetry, ContentModeration, Embedding, Prompt, RAG,
    StructuredOutput, TokenUsage, VectorStore,
)

logger = logging.getLogger("Spring.AI.Annotations")


class ContentModerationError(ValueError):
    """输入或模型输出命中敏感词时抛出的安全异常。"""


# ``@AiCache`` is intentionally a bounded process-local cache.  The old
# implementation used a plain dictionary and treated ``ttl <= 0`` as an
# infinite TTL, so every distinct prompt/argument combination stayed alive
# forever.  OrderedDict gives us O(1) LRU promotion/eviction while the lock
# protects both readers and writers.  Keep the module-level name for backwards
# compatibility with applications/tests which clear the old cache directly.
_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_CACHE_LOCK = threading.RLock()

# Calls for the same key are coalesced.  A slow model request should not be
# executed N times merely because N requests arrived at the same instant.
# Sync callers use Events (which do not hold the cache lock while waiting),
# async callers use a Future per event loop (a Future cannot be awaited from a
# different loop).  Each value also records its owner so accidental recursive
# calls do not deadlock the owning thread/task.
_CACHE_INFLIGHT: dict[str, tuple[threading.Event, int]] = {}
_ASYNC_CACHE_INFLIGHT: dict[tuple[str, int], tuple[asyncio.Future, int]] = {}

# A hard process-wide ceiling remains in place even when one annotation asks
# for a very large value.  It can be raised for a trusted workload via the
# environment without making an annotation an unbounded memory sink.
_DEFAULT_CACHE_MAX_SIZE = 1024
try:
    _configured_cache_max = int(os.getenv(
        "SPRINGBOOTAI_AI_CACHE_MAX_SIZE", str(_DEFAULT_CACHE_MAX_SIZE)))
except (TypeError, ValueError):
    _configured_cache_max = _DEFAULT_CACHE_MAX_SIZE
_CACHE_MAX_SIZE = max(1, _configured_cache_max)


def _cache_max_size(annotation: AiCache) -> int:
    """Return the effective bounded size for an ``@AiCache`` annotation."""
    try:
        requested = int(getattr(annotation, "max_size", _CACHE_MAX_SIZE))
    except (TypeError, ValueError):
        requested = _CACHE_MAX_SIZE
    # <=0 is a convenient per-method switch to disable cache storage.
    if requested <= 0:
        return 0
    return min(requested, _CACHE_MAX_SIZE)


def _purge_expired_locked(now: float) -> None:
    """Remove expired entries; caller must hold ``_CACHE_LOCK``."""
    # Iterating over a snapshot keeps this safe when an expired entry is
    # removed while walking the OrderedDict.  Cache sizes are deliberately
    # bounded, so a full sweep is cheap and guarantees stale values do not
    # accumulate when their keys are never requested again.
    for key, entry in list(_CACHE.items()):
        if entry[0] <= now:
            _CACHE.pop(key, None)


def _cache_get(key: str, now: float) -> tuple[bool, Any]:
    """Get a fresh value and promote it to the MRU end."""
    with _CACHE_LOCK:
        _purge_expired_locked(now)
        entry = _CACHE.get(key)
        if entry is None:
            return False, None
        # A defensive check handles malformed entries left by old versions or
        # by user code that directly touched the compatibility global.
        try:
            expires_at, value = entry
            if expires_at <= now:
                _CACHE.pop(key, None)
                return False, None
        except (TypeError, ValueError):
            _CACHE.pop(key, None)
            return False, None
        _CACHE.move_to_end(key)
        return True, value


def _cache_claim(key: str, now: float) -> tuple[bool, Any, threading.Event | None, bool]:
    """Return ``(hit, value, event, is_owner)`` for a sync cache lookup.

    ``event`` is the Event belonging to the in-flight owner.  ``is_owner`` is
    true only for the caller which created that Event; other callers should
    wait and retry the lookup.
    """
    with _CACHE_LOCK:
        _purge_expired_locked(now)
        entry = _CACHE.get(key)
        if entry is not None:
            try:
                expires_at, value = entry
                if expires_at > now:
                    _CACHE.move_to_end(key)
                    return True, value, None, False
            except (TypeError, ValueError):
                pass
            _CACHE.pop(key, None)

        current_owner = _CACHE_INFLIGHT.get(key)
        if current_owner is not None:
            event, owner_ident = current_owner
            # Recursive calls from the owner itself must not wait forever.
            if owner_ident == threading.get_ident():
                return False, None, None, False
            return False, None, event, False

        event = threading.Event()
        _CACHE_INFLIGHT[key] = (event, threading.get_ident())
        return False, None, event, True


def _cache_store_and_release(key: str, event: threading.Event, value: Any,
                             expires_at: float, max_size: int) -> None:
    """Store a successful result and wake same-key waiters."""
    with _CACHE_LOCK:
        if max_size > 0:
            _purge_expired_locked(time.monotonic())
            _CACHE[key] = (expires_at, value)
            _CACHE.move_to_end(key)
            # Respect both the annotation limit and the process ceiling.  The
            # lower limit wins for the call which populated this key.
            limit = min(max_size, _CACHE_MAX_SIZE)
            while len(_CACHE) > limit:
                _CACHE.popitem(last=False)
        owner = _CACHE_INFLIGHT.get(key)
        if owner is not None and owner[0] is event:
            _CACHE_INFLIGHT.pop(key, None)
            event.set()


def _cache_release_on_error(key: str, event: threading.Event) -> None:
    """Wake waiters when the owner request fails without caching an error."""
    with _CACHE_LOCK:
        owner = _CACHE_INFLIGHT.get(key)
        if owner is not None and owner[0] is event:
            _CACHE_INFLIGHT.pop(key, None)
            event.set()


def _cache_claim_async(key: str, now: float, loop: asyncio.AbstractEventLoop,
                      task_ident: int) -> tuple[bool, Any, asyncio.Future | None, bool]:
    """Async equivalent of :func:`_cache_claim`, scoped to one event loop."""
    with _CACHE_LOCK:
        _purge_expired_locked(now)
        entry = _CACHE.get(key)
        if entry is not None:
            try:
                expires_at, value = entry
                if expires_at > now:
                    _CACHE.move_to_end(key)
                    return True, value, None, False
            except (TypeError, ValueError):
                pass
            _CACHE.pop(key, None)

        inflight_key = (key, id(loop))
        current_owner = _ASYNC_CACHE_INFLIGHT.get(inflight_key)
        if current_owner is not None:
            future, owner_ident = current_owner
            # As with sync calls, bypass coalescing for accidental recursion
            # by the owner task rather than deadlocking it.
            if owner_ident == task_ident:
                return False, None, None, False
            return False, None, future, False

        future = loop.create_future()
        _ASYNC_CACHE_INFLIGHT[inflight_key] = (future, task_ident)
        return False, None, future, True


def _cache_finish_async(key: str, future: asyncio.Future,
                        loop: asyncio.AbstractEventLoop, value: Any = None,
                        error: BaseException | None = None,
                        expires_at: float | None = None,
                        max_size: int = 0) -> None:
    """Publish an async result (or failure) and wake all same-key waiters."""
    with _CACHE_LOCK:
        if error is None and max_size > 0 and expires_at is not None:
            _purge_expired_locked(time.monotonic())
            _CACHE[key] = (expires_at, value)
            _CACHE.move_to_end(key)
            limit = min(max_size, _CACHE_MAX_SIZE)
            while len(_CACHE) > limit:
                _CACHE.popitem(last=False)
        inflight_key = (key, id(loop))
        current = _ASYNC_CACHE_INFLIGHT.get(inflight_key)
        if current is not None and current[0] is future:
            _ASYNC_CACHE_INFLIGHT.pop(inflight_key, None)
            # Store a tuple instead of setting an exception on an unobserved
            # Future; owners with no waiters then do not emit "Future exception
            # was never retrieved" warnings.  Waiters re-raise the same error.
            if not future.done():
                future.set_result((error is None, value if error is None else error))


def _make_cache_key(method: Callable, annotation: AiCache,
                    values: dict[str, Any]) -> str:
    """Build a deterministic cache key shared by sync and async wrappers."""
    if annotation.key:
        try:
            key_data = annotation.key.format(**values)
        except KeyError as exc:
            raise ValueError(f"@AiCache key 缺少参数: {exc.args[0]}") from exc
    else:
        key_data = json.dumps(_stable(values), ensure_ascii=False, sort_keys=True)
    return f"{method.__module__}.{method.__qualname__}:{key_data}"


def _cached_sync_call(key: str, annotation: AiCache, call: Callable[[], Any]) -> Any:
    """Execute a sync call with bounded TTL/LRU storage and request coalescing."""
    ttl = float(getattr(annotation, "ttl", 0.0) or 0.0)
    max_size = _cache_max_size(annotation)
    # TTL/max_size <= 0 is an explicit cache-off switch.  In particular, it
    # must never create a permanent entry as the legacy implementation did.
    if ttl <= 0 or max_size <= 0:
        return call()

    while True:
        now = time.monotonic()
        hit, value, owner_event, is_owner = _cache_claim(key, now)
        if hit:
            return value
        if is_owner:
            event = owner_event
            assert event is not None
            try:
                result = call()
            except BaseException:
                _cache_release_on_error(key, event)
                raise
            _cache_store_and_release(
                key, event, result, time.monotonic() + ttl, max_size,
            )
            return result
        if owner_event is None:
            # Recursive invocation by the owner itself; bypass coalescing to
            # avoid deadlock rather than waiting on our own Event.
            return call()
        # Another thread owns this key.  Waiting outside the lock allows it to
        # publish the result; retry handles both success and owner failures.
        owner_event.wait()


async def _cached_async_call(key: str, annotation: AiCache,
                             call: Callable[[], Any]) -> Any:
    """Async counterpart with loop-local Future request coalescing."""
    ttl = float(getattr(annotation, "ttl", 0.0) or 0.0)
    max_size = _cache_max_size(annotation)
    if ttl <= 0 or max_size <= 0:
        return await call()

    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    task_ident = id(task)
    while True:
        now = time.monotonic()
        hit, value, owner_future, is_owner = _cache_claim_async(
            key, now, loop, task_ident)
        if hit:
            return value
        if is_owner:
            future = owner_future
            assert future is not None
            try:
                result = await call()
            except BaseException as exc:
                _cache_finish_async(key, future, loop, error=exc)
                raise
            _cache_finish_async(
                key, future, loop, value=result,
                expires_at=time.monotonic() + ttl, max_size=max_size,
            )
            return result
        if owner_future is None:
            # Recursive invocation by this task; do not await our own Future.
            return await call()

        # A waiter may be cancelled without cancelling the owner Future.
        # shield() keeps other callers from losing the in-flight computation.
        ok, payload = await asyncio.shield(owner_future)
        if ok:
            return payload
        # The failed owner has already released its slot; retrying permits one
        # waiter to become the next owner and gives transient errors a chance
        # to recover, while the original failure is not cached.


def _stable(value: Any) -> Any:
    """将常见参数转换成稳定、可 JSON 序列化的结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _stable(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set)):
        return [_stable(v) for v in value]
    try:
        return value.model_dump()  # pydantic v2
    except AttributeError:
        try:
            return value.dict()  # pydantic v1
        except AttributeError:
            return repr(value)


def _arguments(method: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    try:
        bound = inspect.signature(method).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        values = dict(bound.arguments)
    except (TypeError, ValueError):
        values = {f"arg{i}": value for i, value in enumerate(args)}
        values.update(kwargs)
    values.pop("self", None)
    return values


def _resolve(factory: Any, name: str, fallback: Any = None) -> Any:
    if factory is None or not name:
        return fallback
    try:
        return factory.get_bean(name)
    except Exception:
        return fallback


def _render(template: str, values: dict[str, Any]) -> str:
    if not template:
        return ""
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        # Prompt 参数不完整时给出可定位错误，而不是静默发送错误提示词。
        missing = []
        import string
        for _, field, _, _ in string.Formatter().parse(template):
            if field and field not in values:
                missing.append(field)
        raise ValueError(f"@Prompt 模板缺少参数: {', '.join(sorted(set(missing)))}")


def _content(result: Any) -> str:
    if result is None:
        return ""
    if hasattr(result, "content") and callable(result.content):
        return str(result.content())
    if hasattr(result, "output") and getattr(result, "output", None):
        output = result.output
        return str(getattr(output, "content", output))
    return str(result)


def _structured(result: Any, annotation: StructuredOutput) -> Any:
    if isinstance(result, annotation.model):
        return result
    raw = _content(result).strip()
    if not raw:
        if annotation.strict:
            raise ValueError("@StructuredOutput 收到空模型响应")
        return result
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        if not annotation.strict:
            return result
        raise ValueError("@StructuredOutput 模型响应不是合法 JSON") from exc
    model = annotation.model
    if model in (dict, Any) or model is None:
        return payload
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)
    if hasattr(model, "parse_obj"):
        return model.parse_obj(payload)
    if isinstance(payload, model):
        return payload
    try:
        return model(**payload) if isinstance(payload, dict) else model(payload)
    except Exception:
        if annotation.strict:
            raise ValueError(f"@StructuredOutput 无法绑定 {model!r}")
        return payload


def _usage(result: Any) -> dict[str, Any]:
    metadata = getattr(result, "metadata", None) or {}
    usage = metadata.get("usage") or metadata.get("token_usage") or {}
    if not isinstance(usage, dict):
        return {}
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "completion_tokens": ("completion_tokens", "output_tokens"),
        "total_tokens": ("total_tokens",),
    }
    normalized = {}
    for target, keys in aliases.items():
        for key in keys:
            if usage.get(key) is not None:
                normalized[target] = int(usage[key])
                break
    if "total_tokens" not in normalized:
        normalized["total_tokens"] = normalized.get("prompt_tokens", 0) + normalized.get("completion_tokens", 0)
    return normalized


def _moderate(value: Any, annotation: ContentModeration) -> None:
    if not annotation.blocked_terms:
        return
    text = _content(value).casefold()
    for term in annotation.blocked_terms:
        if term.casefold() in text:
            raise ContentModerationError("内容审核未通过")


def _invoke_chat(factory: Any, annotation: Prompt, query: str, values: dict[str, Any]) -> Any:
    client = _resolve(factory, annotation.client)
    if client is None:
        raise RuntimeError(f"未找到 ChatClient Bean: {annotation.client}")
    spec = client.prompt()
    system = _render(annotation.system, values)
    if system:
        spec.system(system)
    spec.user(query)
    for key in ("tenant_id", "user_id", "conversation_id"):
        if values.get(key) is not None:
            spec.param(key, values[key])
    return spec.call()


def _invoke_rag(factory: Any, annotation: RAG, query: str,
                values: Optional[dict[str, Any]] = None) -> Any:
    client = _resolve(factory, annotation.client)
    store = _resolve(factory, annotation.vector_store)
    embedding = _resolve(factory, annotation.embedding)
    if client is None or store is None:
        raise RuntimeError("@RAG 需要 aiChatClient 和 aiVectorStore Bean")
    from springbootai.ai.advisors import QuestionAnswerAdvisor
    advisor = QuestionAnswerAdvisor(
        store, prompt_template=annotation.prompt_template,
        top_k=annotation.top_k, embedding_model=embedding,
    )
    spec = client.prompt().advisors(advisor).user(query)
    # Carry only identity/session fields into AdvisorRequest. Arbitrary method
    # arguments must never become trusted authorization context implicitly.
    values = values or {}
    for key in ("tenant_id", "user_id", "conversation_id"):
        if values.get(key) is not None:
            spec.param(key, values[key])
    return spec.call()


def _invoke_agent(factory: Any, annotation: Agent, query: str) -> Any:
    service = _resolve(factory, annotation.service)
    if service is not None and hasattr(service, "run_agent"):
        return service.run_agent(annotation.tools, query, agent_type=annotation.agent_type,
                                 max_iterations=annotation.max_iterations)
    client = _resolve(factory, annotation.client)
    if client is None:
        raise RuntimeError("@Agent 需要 lcAgentService 或 aiChatClient Bean")
    return client.prompt().user(query).call()


def apply_ai_annotations(factory: Any, instance: Any, method: Callable) -> Callable:
    """按注解包装一个未绑定方法；普通方法会原样返回。"""
    method_annotations = list(getattr(method, "__spring_annotations__", []))
    class_annotations = list(getattr(instance.__class__, "__spring_annotations__", []))
    annotations = method_annotations + [a for a in class_annotations if isinstance(a, Agent)]
    if not any(isinstance(a, (Prompt, RAG, StructuredOutput, Agent, AiRetry,
                              AiCache, TokenUsage, ContentModeration)) for a in annotations):
        return method

    prompt_ann = next((a for a in annotations if isinstance(a, Prompt)), None)
    rag_ann = next((a for a in annotations if isinstance(a, RAG)), None)
    agent_ann = next((a for a in annotations if isinstance(a, Agent)), None)
    output_ann = next((a for a in annotations if isinstance(a, StructuredOutput)), None)
    retry_ann = next((a for a in annotations if isinstance(a, AiRetry)), None)
    cache_ann = next((a for a in annotations if isinstance(a, AiCache)), None)
    token_ann = next((a for a in annotations if isinstance(a, TokenUsage)), None)
    moderation_ann = next((a for a in annotations if isinstance(a, ContentModeration)), None)

    def execute(*args, **kwargs):
        values = _arguments(method, args, kwargs)
        original = None
        if prompt_ann or rag_ann or agent_ann:
            # 原方法可作为无模板注解的 query 工厂；有模板时只读取参数。
            if prompt_ann and prompt_ann.template:
                query = _render(prompt_ann.template, values)
                result = _invoke_chat(factory, prompt_ann, query, values)
            elif rag_ann:
                query = _render(prompt_ann.template, values) if prompt_ann and prompt_ann.template else None
                if query is None:
                    original = method(*args, **kwargs)
                    query = _content(original)
                result = _invoke_rag(factory, rag_ann, query, values)
            elif agent_ann:
                original = method(*args, **kwargs)
                result = _invoke_agent(factory, agent_ann, _content(original))
            else:
                original = method(*args, **kwargs)
                result = _invoke_chat(factory, prompt_ann, _content(original), values)
        else:
            result = method(*args, **kwargs)

        if moderation_ann and moderation_ann.check_output:
            _moderate(result, moderation_ann)
        if token_ann:
            usage = _usage(result)
            if usage:
                try:
                    from springbootai.ai.observability import ai_metrics
                    metadata = getattr(result, "metadata", {}) or {}
                    ai_metrics.record_tokens(
                        token_ann.provider or metadata.get("provider", "unknown"), usage,
                    )
                except Exception:
                    logger.debug("TokenUsage 记录失败", exc_info=True)
        if output_ann:
            result = _structured(result, output_ann)
        if ((prompt_ann and prompt_ann.response == "content") or rag_ann or agent_ann) and not output_ann:
            return _content(result)
        return result

    async def execute_async(*args, **kwargs):
        """异步方法对应的执行路径，避免把 coroutine 当成 Prompt 文本。"""
        values = _arguments(method, args, kwargs)
        if prompt_ann or rag_ann or agent_ann:
            if prompt_ann and prompt_ann.template:
                result = _invoke_chat(factory, prompt_ann, _render(prompt_ann.template, values), values)
            elif rag_ann:
                original = await method(*args, **kwargs)
                result = _invoke_rag(factory, rag_ann, _content(original), values)
            elif agent_ann:
                original = await method(*args, **kwargs)
                result = _invoke_agent(factory, agent_ann, _content(original))
            else:
                original = await method(*args, **kwargs)
                result = _invoke_chat(factory, prompt_ann, _content(original), values)
        else:
            result = await method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        if moderation_ann and moderation_ann.check_output:
            _moderate(result, moderation_ann)
        if token_ann:
            usage = _usage(result)
            if usage:
                try:
                    from springbootai.ai.observability import ai_metrics
                    metadata = getattr(result, "metadata", {}) or {}
                    ai_metrics.record_tokens(token_ann.provider or metadata.get("provider", "unknown"), usage)
                except Exception:
                    logger.debug("TokenUsage 记录失败", exc_info=True)
        if output_ann:
            result = _structured(result, output_ann)
        if ((prompt_ann and prompt_ann.response == "content") or rag_ann or agent_ann) and not output_ann:
            return _content(result)
        return result

    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        values = _arguments(method, args, kwargs)
        if moderation_ann and moderation_ann.check_input:
            _moderate(" ".join(map(str, values.values())), moderation_ann)

        def call_once():
            return execute(*args, **kwargs)

        call = call_once
        if retry_ann:
            from springbootai.ai.resilience import resilient_call
            call = resilient_call(
                call_once, max_retries=max(0, retry_ann.attempts - 1),
                retry_delay_ms=retry_ann.delay_ms,
                retry_exceptions=retry_ann.exceptions,
            )
        if cache_ann:
            key = _make_cache_key(method, cache_ann, values)
            return _cached_sync_call(key, cache_ann, call)
        return call()

    if inspect.iscoroutinefunction(method):
        @functools.wraps(method)
        async def async_wrapped(*args, **kwargs):
            values = _arguments(method, args, kwargs)
            if moderation_ann and moderation_ann.check_input:
                _moderate(" ".join(map(str, values.values())), moderation_ann)
            async def call_async():
                if retry_ann:
                    last = None
                    for attempt in range(retry_ann.attempts):
                        try:
                            return await execute_async(*args, **kwargs)
                        except retry_ann.exceptions as exc:
                            last = exc
                            if attempt + 1 < retry_ann.attempts:
                                await asyncio.sleep(retry_ann.delay_ms / 1000)
                    raise last
                return await execute_async(*args, **kwargs)
            if cache_ann:
                key = _make_cache_key(method, cache_ann, values)
                return await _cached_async_call(key, cache_ann, call_async)
            return await call_async()
        return async_wrapped

    return wrapped


def inject_ai_marker(factory: Any, instance: Any) -> None:
    """解析 ``field = Embedding()`` / ``field = VectorStore()`` 标记。"""
    from springbootai.ai.core import EmbeddingModel
    from springbootai.ai.vectorstore import VectorStore as VectorStoreType
    class_annotations = getattr(instance.__class__, "__spring_annotations__", [])
    # 类级注解提供约定字段，适合只需要一个默认 AI 组件的 Service。
    for annotation, attr, expected in (
        (Embedding, "embedding_model", EmbeddingModel),
        (VectorStore, "vector_store", VectorStoreType),
    ):
        class_marker = next((a for a in class_annotations if isinstance(a, annotation)), None)
        if class_marker and not getattr(instance, attr, None):
            dependency = _resolve(factory, class_marker.bean)
            if dependency is not None and isinstance(dependency, expected):
                setattr(instance, attr, dependency)
    for name, value in vars(instance.__class__).items():
        if isinstance(value, (Embedding, VectorStore)):
            bean_name = value.bean
            expected = EmbeddingModel if isinstance(value, Embedding) else VectorStoreType
            dependency = _resolve(factory, bean_name)
            if dependency is not None and isinstance(dependency, expected):
                setattr(instance, name, dependency)
