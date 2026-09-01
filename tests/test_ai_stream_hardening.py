import asyncio
import json
import sys
import threading
import time
import types

import pytest
import requests

from springbootai.ai.core import ChatModel, ChatResponse, Generation, Message
from springbootai.ai.providers import (
    FakeChatModel,
    OllamaChatModel,
    OpenAIChatModel,
    OpenAICompatChatModel,
    ProviderProtocolError,
    ProviderResponseTooLargeError,
    ProviderStreamError,
    _http_post_json,
)
from springbootai.ai.tools import ToolRegistry
from springbootai.ai.resilience import AICircuitBreaker, TransientError
from springbootai.logging.context import request_context


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, *, lines=(), payload=None):
        self.lines = list(lines)
        self.payload = payload
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)

    def iter_content(self, chunk_size=64 * 1024):
        yield json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


def _openai_model():
    model = OpenAIChatModel(api_key="", max_retries=1, retry_delay_ms=0)
    model._llm = None
    return model


def _compat_model():
    model = OpenAICompatChatModel(
        provider="compat", base_url="https://provider.test",
        max_retries=1, retry_delay_ms=0,
    )
    model._llm = None
    return model


@pytest.mark.parametrize("model_factory", [_openai_model, _compat_model])
def test_openai_stream_accepts_usage_only_chunk(monkeypatch, model_factory):
    lines = [
        "data: " + json.dumps({
            "choices": [{"delta": {"content": "ok"}}],
        }),
        "data: " + json.dumps({
            "choices": [], "usage": {"total_tokens": 3},
        }),
        "data: [DONE]",
    ]
    response = _Response(lines=lines)
    captured = {}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", post)
    chunks = list(model_factory().stream(
        [Message.user("hello")],
        options={"stream": False,
                 "stream_options": {"include_usage": True}},
    ))

    assert "".join(chunk.content() for chunk in chunks) == "ok"
    assert captured["json"]["stream"] is True
    assert response.closed is True


@pytest.mark.parametrize(
    ("model_factory", "line"),
    [
        (_openai_model, "data: " + json.dumps({
            "choices": [{"delta": {"content": "partial"}}],
        })),
        (_compat_model, "data: " + json.dumps({
            "choices": [{"delta": {"content": "partial"}}],
        })),
        (lambda: OllamaChatModel(max_retries=1, retry_delay_ms=0),
         json.dumps({"message": {"content": "partial"}, "done": False})),
    ],
)
def test_provider_stream_rejects_clean_eof_without_terminal_marker(
        monkeypatch, model_factory, line):
    response = _Response(lines=[line])
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)
    model = model_factory()
    model._llm = None
    iterator = model.stream([Message.user("hello")])

    assert next(iterator).content() == "partial"
    with pytest.raises(ProviderStreamError, match="partial response"):
        next(iterator)
    assert response.closed is True


def test_http_200_error_envelope_is_not_an_empty_success(monkeypatch):
    response = _Response(payload={
        "error": {"message": "api_key=must-not-leak"},
    })
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)

    with pytest.raises(ProviderProtocolError, match="error response") as raised:
        _http_post_json(
            "https://provider.test/chat", json_body={}, timeout=1,
            max_retries=1, retry_delay_ms=0, circuit_breaker=None,
            provider="test",
        )

    assert "must-not-leak" not in str(raised.value)
    assert response.closed is True


def test_provider_http_rejects_redirects_without_following(monkeypatch):
    class RedirectResponse(_Response):
        status_code = 302

    response = RedirectResponse(payload={"ok": True})
    captured = {}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ProviderProtocolError, match="redirects"):
        _http_post_json(
            "https://provider.test/chat", json_body={}, timeout=1,
            max_retries=1, retry_delay_ms=0, circuit_breaker=None,
            provider="test",
        )

    assert captured["allow_redirects"] is False
    assert response.closed is True


def test_openai_options_cannot_replace_prompt_model_or_output_cap(monkeypatch):
    captured = {}

    def fake_http(_url, **kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(
        "springbootai.ai.providers._http_post_json", fake_http)
    model = _openai_model()
    model.max_output_tokens = 32
    response = model._raw_call(
        [Message.user("trusted")], options={
            "model": "attacker-model",
            "messages": [{"role": "user", "content": "replaced"}],
            "stream": True,
            "max_tokens": 100_000,
            "temperature": 0.1,
        },
    )

    payload = captured["json_body"]
    assert response.content() == "ok"
    assert payload["model"] == model.model
    assert payload["messages"][0]["content"] == "trusted"
    assert payload["stream"] is False
    assert payload["max_tokens"] == 32
    assert payload["temperature"] == 0.1


def test_stream_event_size_is_bounded(monkeypatch):
    monkeypatch.setattr(
        "springbootai.ai.providers._MAX_STREAM_EVENT_BYTES", 16)
    response = _Response(lines=["data: " + "x" * 32])
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)

    with pytest.raises(ProviderResponseTooLargeError, match="event"):
        list(_openai_model().stream([Message.user("hello")]))
    assert response.closed is True


def test_langchain_request_options_are_bound_and_capped():
    class Result:
        content = "ok"
        usage_metadata = {}
        tool_calls = []

    class LLM:
        def __init__(self):
            self.bound = None

        def bind(self, **kwargs):
            self.bound = kwargs
            return self

        def invoke(self, _messages):
            return Result()

    model = _openai_model()
    model.max_output_tokens = 20
    model._llm = LLM()
    response = model._raw_call(
        [Message.user("hello")], options={
            "max_tokens": 999, "temperature": 0.2, "model": "ignored",
        },
    )

    assert response.content() == "ok"
    assert model._llm.bound == {"max_tokens": 20, "temperature": 0.2}


def test_chunked_transfer_failure_is_retried_and_responses_are_closed(
        monkeypatch):
    responses = []

    class BrokenResponse(_Response):
        def iter_content(self, chunk_size=64 * 1024):
            raise requests.exceptions.ChunkedEncodingError("internal details")

    def post(*_args, **_kwargs):
        response = BrokenResponse()
        responses.append(response)
        return response

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(TransientError, match="ChunkedEncodingError") as raised:
        _http_post_json(
            "https://provider.test/chat", json_body={}, timeout=1,
            max_retries=3, retry_delay_ms=0, circuit_breaker=None,
            provider="test",
        )

    assert len(responses) == 3
    assert all(response.closed for response in responses)
    assert "internal details" not in str(raised.value)


def test_circuit_breaker_reads_default_redis_byte_keys():
    class Redis:
        def hgetall(self, _key):
            return {
                b"state": b"OPEN",
                b"failures": b"9",
                b"last_failure_time": b"9999999999",
            }

        def hset(self, *_args, **_kwargs):
            return None

    breaker = AICircuitBreaker(redis_client=Redis())

    assert breaker.state == "OPEN"
    assert breaker.allow() is False


def test_astream_preserves_request_context(monkeypatch):
    captured = {}
    response = _Response(lines=["data: [DONE]"])

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", post)

    async def scenario():
        with request_context("rid-async-stream"):
            return [chunk async for chunk in _openai_model().astream(
                [Message.user("hello")])]

    assert asyncio.run(scenario()) == []
    assert captured["headers"]["X-Request-ID"] == "rid-async-stream"


class _PullModel(ChatModel):
    def __init__(self):
        self.pulls = 0
        self.closed = threading.Event()

    def _raw_call(self, messages, tool_registry=None, options=None):
        return ChatResponse([Generation(Message.assistant("unused"))])

    def stream(self, messages, tool_registry=None, options=None):
        try:
            for value in ("one", "two", "three"):
                self.pulls += 1
                yield ChatResponse([Generation(Message.assistant(value))])
        finally:
            self.closed.set()


def test_astream_has_pull_backpressure_and_aclose_closes_iterator():
    model = _PullModel()

    async def scenario():
        iterator = model.astream([Message.user("hello")])
        first = await anext(iterator)
        await asyncio.sleep(0.03)
        pulls_before_close = model.pulls
        await iterator.aclose()
        return first, pulls_before_close

    first, pulls_before_close = asyncio.run(scenario())
    assert first.content() == "one"
    assert pulls_before_close == 1
    assert model.closed.wait(0.2)


def test_astream_does_not_expose_provider_exception_text():
    class ErrorModel(_PullModel):
        def stream(self, messages, tool_registry=None, options=None):
            if False:
                yield None
            raise RuntimeError("api_key=SUPERSECRET")

    async def scenario():
        return [chunk async for chunk in ErrorModel().astream(
            [Message.user("hello")])]

    with pytest.raises(RuntimeError, match="stream error: RuntimeError") as raised:
        asyncio.run(scenario())
    assert "SUPERSECRET" not in str(raised.value)


def test_tool_enabled_stream_executes_the_complete_tool_loop():
    registry = ToolRegistry()
    registry.register("lookup", lambda: "tool-result")
    model = FakeChatModel(prefix="AI:", simulate_tool_call=True)

    chunks = list(model.stream(
        [Message.user("调用工具 lookup")], tool_registry=registry))

    assert len(chunks) == 1
    assert chunks[0].content() == "AI: 工具返回: tool-result"
    assert chunks[0].metadata["stream_fallback"] == "tool_loop"
    assert model.call_count == 2


def test_astream_cancellation_closes_active_http_response_and_releases_capacity(
        monkeypatch):
    started = threading.Event()

    class BlockingResponse(_Response):
        def __init__(self):
            super().__init__()
            self.unblocked = threading.Event()

        def iter_lines(self, decode_unicode=True):
            started.set()
            self.unblocked.wait(2)
            yield "data: [DONE]"

        def close(self):
            self.closed = True
            self.unblocked.set()

    response = BlockingResponse()
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)
    model = _openai_model()
    model.max_concurrent_requests = 1
    model.concurrency_acquire_timeout = 0.2

    async def scenario():
        iterator = model.astream([Message.user("hello")])
        pending = asyncio.create_task(anext(iterator))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await iterator.aclose()

    asyncio.run(scenario())
    assert response.closed is True
    semaphore = model._capacity_semaphore()
    assert semaphore.acquire(timeout=0.2)
    semaphore.release()


@pytest.mark.parametrize(
    ("model_factory", "lines"),
    [
        (_compat_model, [
            "data: " + json.dumps({
                "choices": [{"delta": {"content": "ok"}}],
            }),
            "data: [DONE]",
        ]),
        (lambda: OllamaChatModel(max_retries=1, retry_delay_ms=0), [
            json.dumps({"message": {"content": "ok"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]),
    ],
)
def test_compat_and_ollama_astream_do_not_block_event_loop(
        monkeypatch, model_factory, lines):
    class SlowResponse(_Response):
        def iter_lines(self, decode_unicode=True):
            time.sleep(0.08)
            yield from self.lines

    response = SlowResponse(lines=lines)
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)
    model = model_factory()
    model._llm = None

    async def scenario():
        heartbeat_ran = asyncio.Event()

        async def heartbeat():
            await asyncio.sleep(0.01)
            heartbeat_ran.set()

        heartbeat_task = asyncio.create_task(heartbeat())
        iterator = model.astream([Message.user("hello")])
        first = await anext(iterator)
        progressed = heartbeat_ran.is_set()
        await iterator.aclose()
        await heartbeat_task
        return first, progressed

    first, progressed = asyncio.run(scenario())
    assert first.content() == "ok"
    assert progressed is True
    assert response.closed is True


def test_ollama_http_fallback_keeps_tools_and_request_options(monkeypatch):
    captured = {}
    tool_calls = [{
        "function": {"name": "lookup", "arguments": {"id": 1}},
    }]

    def fake_http(_url, **kwargs):
        captured.update(kwargs)
        return {"message": {"content": "", "tool_calls": tool_calls}}

    class Registry:
        def names(self):
            return ["lookup"]

        def schemas(self):
            return [{"type": "function", "function": {"name": "lookup"}}]

        def execute(self, *_args, **_kwargs):
            return "done"

    monkeypatch.setattr(
        "springbootai.ai.providers._http_post_json", fake_http)
    model = OllamaChatModel(max_retries=1)
    model._llm = None

    response = model._raw_call(
        [Message.user("hello")], Registry(), {"seed": 42})

    payload = captured["json_body"]
    assert payload["stream"] is False
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["options"]["seed"] == 42
    assert response.metadata["tool_calls"] == tool_calls


def test_langchain_openai_uses_framework_timeout_and_single_retry_owner(
        monkeypatch):
    import springbootai.ai.providers as providers

    captured = {}
    module = types.ModuleType("langchain_openai")

    class ChatOpenAI:
        def __init__(self, **kwargs):
            captured["chat"] = kwargs

    class OpenAIEmbeddings:
        def __init__(self, **kwargs):
            captured["embedding"] = kwargs

    module.ChatOpenAI = ChatOpenAI
    module.OpenAIEmbeddings = OpenAIEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.setattr(providers, "_has_langchain_openai", lambda: True)

    providers.OpenAIChatModel(
        api_key="sk-test", timeout=17, max_retries=5)
    providers.OpenAIEmbeddingModel(
        api_key="sk-test", timeout=19, max_retries=7)

    assert captured["chat"]["timeout"] == 17
    assert captured["chat"]["max_retries"] == 0
    assert captured["embedding"]["timeout"] == 19
    assert captured["embedding"]["max_retries"] == 0
