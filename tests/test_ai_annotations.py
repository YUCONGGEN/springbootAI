"""声明式 AI 注解的最小运行时回归测试。"""

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel

from springbootai.ai import ChatClient, ChatModel, ChatResponse, Generation, Message
from springbootai.ai.annotation_runtime import ContentModerationError, apply_ai_annotations
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
