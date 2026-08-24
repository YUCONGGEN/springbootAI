"""声明式 AI 注解的最小运行时回归测试。"""

import asyncio
import threading
import time
from dataclasses import dataclass

from pydantic import BaseModel

from springbootai.ai import ChatClient, ChatModel, ChatResponse, Generation, Message
from springbootai.ai.annotation_runtime import (
    ContentModerationError, _ASYNC_CACHE_INFLIGHT, _CACHE, _CACHE_INFLIGHT,
    apply_ai_annotations,
)
from springbootai.ai.annotations import (
    AiCache, AiRetry, ContentModeration, Prompt, StructuredOutput, TokenUsage,
)


class FakeJsonModel(ChatModel):
    calls = 0

    def _raw_call(self, messages, tool_registry=None, options=None):
        type(self).calls += 1
        return ChatResponse(
            [Generation(Message.assistant('{"passed": true, "reason": "ok"}'))],
            {"usage": {"prompt_tokens": 2, "completion_tokens": 3}},
        )


class Container:
    def __init__(self):
        self.client = ChatClient(FakeJsonModel())

    def get_bean(self, name):
        if name == "aiChatClient":
            return self.client
        raise LookupError(name)


class Result(BaseModel):
    passed: bool
    reason: str


def test_prompt_and_structured_output_and_token_metadata():
    @Prompt("检查：{text}")
    @StructuredOutput(Result)
    @TokenUsage()
    def method(self, text):
        return text

    service = object()
    wrapped = apply_ai_annotations(Container(), service, method)
    result = wrapped(service, "焊缝")
    assert isinstance(result, Result)
    assert result.passed is True


def test_ai_cache_uses_stable_key():
    count = {"n": 0}

    @AiCache(ttl=60)
    def method(self, payload):
        count["n"] += 1
        return count["n"]

    service = object()
    wrapped = apply_ai_annotations(None, service, method)
    assert wrapped(service, {"b": 2, "a": 1}) == 1
    assert wrapped(service, {"a": 1, "b": 2}) == 1
    assert count["n"] == 1


def test_ai_cache_ttl_zero_is_explicitly_disabled():
    """ttl<=0 不得变成永久缓存，也不得在全局缓存中留下条目。"""
    for store in (_CACHE, _CACHE_INFLIGHT, _ASYNC_CACHE_INFLIGHT):
        store.clear()
    count = {"n": 0}

    @AiCache(ttl=0)
    def method(self, value):
        count["n"] += 1
        return count["n"]

    wrapped = apply_ai_annotations(None, object(), method)
    assert wrapped(object(), "same") == 1
    assert wrapped(object(), "same") == 2
    assert len(_CACHE) == 0


def test_ai_cache_uses_bounded_lru_and_expires_unrequested_entries():
    """缓存条目有上限，并在访问任意 key 时清理已经过期的旧条目。"""
    for store in (_CACHE, _CACHE_INFLIGHT, _ASYNC_CACHE_INFLIGHT):
        store.clear()
    count = {"n": 0}

    @AiCache(ttl=0.03, max_size=2)
    def method(self, value):
        count["n"] += 1
        return count["n"]

    wrapped = apply_ai_annotations(None, object(), method)
    assert wrapped(object(), 1) == 1
    assert wrapped(object(), 2) == 2
    # 访问 1 将其提升到 MRU，再加入 3 时应淘汰 2。
    assert wrapped(object(), 1) == 1
    assert wrapped(object(), 3) == 3
    assert len(_CACHE) == 2
    assert wrapped(object(), 2) == 4
    time.sleep(0.05)
    # 即使从不再次访问 key=1/3，下一次查询也会扫除过期条目。
    assert wrapped(object(), 4) == 5
    assert len(_CACHE) == 1


def test_ai_cache_coalesces_concurrent_sync_calls():
    """同一个慢 key 的并发请求只执行一次底层函数。"""
    for store in (_CACHE, _CACHE_INFLIGHT, _ASYNC_CACHE_INFLIGHT):
        store.clear()
    count = {"n": 0}
    lock = threading.Lock()

    @AiCache(ttl=60)
    def method(self, value):
        with lock:
            count["n"] += 1
        time.sleep(0.03)
        return "ok"

    wrapped = apply_ai_annotations(None, object(), method)
    barrier = threading.Barrier(8)
    results = []

    def invoke():
        barrier.wait()
        results.append(wrapped(object(), "same"))

    threads = [threading.Thread(target=invoke) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == ["ok"] * 8
    assert count["n"] == 1


def test_ai_cache_coalesces_concurrent_async_calls():
    """同一个事件循环中异步并发请求共享进行中的模型调用。"""
    for store in (_CACHE, _CACHE_INFLIGHT, _ASYNC_CACHE_INFLIGHT):
        store.clear()
    count = {"n": 0}

    @AiCache(ttl=60)
    async def method(self, value):
        count["n"] += 1
        await asyncio.sleep(0.03)
        return "ok"

    wrapped = apply_ai_annotations(None, object(), method)

    async def run():
        return await asyncio.gather(*[
            wrapped(object(), "same") for _ in range(8)
        ])

    assert asyncio.run(run()) == ["ok"] * 8
    assert count["n"] == 1


def test_content_moderation_rejects_before_model_call():
    @Prompt("回答：{text}")
    @ContentModeration(blocked_terms=["禁止词"])
    def method(self, text):
        return text

    service = object()
    wrapped = apply_ai_annotations(Container(), service, method)
    try:
        wrapped(service, "包含禁止词")
    except ContentModerationError:
        pass
    else:
        raise AssertionError("应拦截敏感输入")


def test_async_prompt_and_retry():
    @Prompt("异步：{text}")
    @AiRetry(attempts=2, delay_ms=1)
    async def method(self, text):
        return text

    service = object()
    wrapped = apply_ai_annotations(Container(), service, method)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        assert isinstance(loop.run_until_complete(wrapped(service, "ok")), str)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
