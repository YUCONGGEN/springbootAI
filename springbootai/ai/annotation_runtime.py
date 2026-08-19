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
import threading
import time
from typing import Any, Callable, Iterable

from springbootai.ai.annotations import (
    Agent, AiCache, AiRetry, ContentModeration, Embedding, Prompt, RAG,
    StructuredOutput, TokenUsage, VectorStore,
)

logger = logging.getLogger("Spring.AI.Annotations")


class ContentModerationError(ValueError):
    """输入或模型输出命中敏感词时抛出的安全异常。"""


_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.RLock()


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
    return spec.user(query).call()


def _invoke_rag(factory: Any, annotation: RAG, query: str) -> Any:
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
    return client.prompt().advisors(advisor).user(query).call()


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
                result = _invoke_rag(factory, rag_ann, query)
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
                result = _invoke_rag(factory, rag_ann, _content(original))
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
            if cache_ann.key:
                try:
                    key_data = cache_ann.key.format(**values)
                except KeyError as exc:
                    raise ValueError(f"@AiCache key 缺少参数: {exc.args[0]}") from exc
            else:
                key_data = json.dumps(_stable(values), ensure_ascii=False, sort_keys=True)
            key = f"{method.__module__}.{method.__qualname__}:{key_data}"
            now = time.time()
            with _CACHE_LOCK:
                hit = _CACHE.get(key)
                if hit and (cache_ann.ttl <= 0 or hit[0] > now):
                    return hit[1]
                _CACHE.pop(key, None)
            result = call()
            with _CACHE_LOCK:
                _CACHE[key] = (now + cache_ann.ttl, result)
            return result
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
                if cache_ann.key:
                    try:
                        key_data = cache_ann.key.format(**values)
                    except KeyError as exc:
                        raise ValueError(f"@AiCache key 缺少参数: {exc.args[0]}") from exc
                else:
                    key_data = json.dumps(_stable(values), ensure_ascii=False, sort_keys=True)
                key = f"{method.__module__}.{method.__qualname__}:{key_data}"
                now = time.time()
                with _CACHE_LOCK:
                    hit = _CACHE.get(key)
                    if hit and (cache_ann.ttl <= 0 or hit[0] > now):
                        return hit[1]
                    _CACHE.pop(key, None)
                result = await call_async()
                with _CACHE_LOCK:
                    _CACHE[key] = (now + cache_ann.ttl, result)
                return result
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
