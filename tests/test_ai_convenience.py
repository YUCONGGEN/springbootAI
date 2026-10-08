"""AI convenience APIs and cancellation/identity regression tests."""

from __future__ import annotations

import asyncio
import threading

import pytest
from pydantic import BaseModel, ValidationError

from springbootai.ai import (
    ChatClient, ChatModel, ChatResponse, FakeChatModel, Generation, Message,
    SimpleInMemoryVectorStore, VectorDocument,
)
from springbootai.ai.annotation_runtime import _CACHE, apply_ai_annotations
from springbootai.ai.annotations import AiCache, Prompt, RAG, StructuredOutput
from springbootai.langgraph.config import LangGraphProperties
from springbootai.langgraph.runtime import LangGraphWorkflow
from springbootai.security.security_context import SecurityContextHolder


class Inspection(BaseModel):
    passed: bool
    reason: str


class RecordingModel(ChatModel):
    def __init__(self, content="answer"):
        self.content = content
        self.messages = []
        self.options = None

    def _raw_call(self, messages, tool_registry=None, options=None):
        self.messages = messages
        self.options = options
        return ChatResponse([Generation(Message.assistant(self.content))])


class Container:
    def __init__(self, model):
        self.beans = {"aiChatClient": ChatClient(model)}

    def get_bean(self, name):
        return self.beans[name]


@pytest.fixture(autouse=True)
def clear_security():
    _CACHE.clear()
    SecurityContextHolder.clear_context()
    yield
    SecurityContextHolder.clear_context()
    _CACHE.clear()


def run(coroutine):
    try:
        return asyncio.run(coroutine)
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("custom_key", ["", "{question}"])
def test_cache_automatically_separates_authenticated_users_and_tenants(asynchronous, custom_key):
    calls = []

    def result():
        auth = SecurityContextHolder.get_authentication()
        value = (auth["details"]["tenant_id"], auth["principal"])
        calls.append(value)
        return value

    if asynchronous:
        @AiCache(ttl=60, key=custom_key)
        async def method(self, question):
            return result()
    else:
        @AiCache(ttl=60, key=custom_key)
        def method(self, question):
            return result()

    wrapped = apply_ai_annotations(None, object(), method)

    async def invoke():
        for tenant, user in [("a", "alice"), ("a", "bob"), ("b", "alice")]:
            SecurityContextHolder.set_authentication({
                "principal": user, "details": {"tenant_id": tenant},
            })
            for _ in range(2):
                value = wrapped(object(), "same question")
                if asynchronous:
                    value = await value
                assert value == (tenant, user)

    run(invoke())
    assert len(calls) == 3


@pytest.mark.parametrize("asynchronous", [False, True])
def test_empty_prompt_body_uses_question_argument(asynchronous):
    if asynchronous:
        @Prompt
        async def method(self, question: str, conversation_id: str = "session") -> str:
            ...
    else:
        @Prompt
        def method(self, question: str, conversation_id: str = "session") -> str:
            ...
    model = RecordingModel()
    wrapped = apply_ai_annotations(Container(model), object(), method)
    value = wrapped(object(), "hello")
    assert (run(value) if asynchronous else value) == "answer"
    assert model.messages[-1].content == "hello"


def test_prompt_query_factory_remains_supported():
    @Prompt
    def method(self, text):
        return f"summarize:{text}"

    model = RecordingModel()
    apply_ai_annotations(Container(model), object(), method)(object(), "hello")
    assert model.messages[-1].content == "summarize:hello"


def test_ambiguous_empty_body_reports_how_to_supply_input():
    @Prompt
    def method(self, left, right):
        ...

    with pytest.raises(ValueError, match="模板"):
        apply_ai_annotations(Container(RecordingModel()), object(), method)(object(), "a", "b")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_return_model_infers_schema_and_validates_output(asynchronous):
    if asynchronous:
        @Prompt("inspect:{text}")
        async def method(self, text: str) -> Inspection:
            ...
    else:
        @Prompt("inspect:{text}")
        def method(self, text: str) -> Inspection:
            ...

    model = RecordingModel('{"passed":true,"reason":"ok"}')
    wrapped = apply_ai_annotations(Container(model), object(), method)
    result = wrapped(object(), "weld")
    if asynchronous:
        result = run(result)
    assert isinstance(result, Inspection)
    assert result.passed is True
    assert any('"required"' in message.content and '"passed"' in message.content
               for message in model.messages)
    model.content = '{"passed":true}'
    with pytest.raises(ValidationError):
        result = wrapped(object(), "weld")
        if asynchronous:
            run(result)


def test_explicit_output_annotation_overrides_return_type():
    @Prompt("inspect:{text}")
    @StructuredOutput(dict)
    def method(self, text: str) -> Inspection:
        ...

    model = RecordingModel('{"other":1}')
    result = apply_ai_annotations(Container(model), object(), method)(object(), "weld")
    assert result == {"other": 1}


def test_declarative_service_works_through_the_real_bean_factory():
    from springbootai.annotations import Service
    from springbootai.context.bean_definition import BeanDefinition
    from springbootai.context.bean_factory import BeanFactory

    @Service
    class Assistant:
        @Prompt("inspect:{text}")
        def inspect(self, text: str) -> Inspection:
            ...

    factory = BeanFactory()
    factory.register_bean_definition("aiChatClient", BeanDefinition(ChatClient, "aiChatClient"))
    factory.register_instance("aiChatClient", ChatClient(RecordingModel(
        '{"passed":true,"reason":"ok"}')))
    factory.register_bean_definition("assistant", BeanDefinition(Assistant, "assistant"))
    result = factory.get_bean("assistant").inspect("weld")
    assert isinstance(result, Inspection)


def test_chat_client_constructor_injection_resolves_postponed_annotations():
    from springbootai.annotations import Autowired
    from springbootai.context.bean_definition import BeanDefinition
    from springbootai.context.bean_factory import BeanFactory

    class Assistant:
        @Autowired
        def __init__(self, chat_client: ChatClient):
            self.client = chat_client

    factory = BeanFactory()
    client = ChatClient(FakeChatModel())
    factory.register_bean_definition("aiChatClient", BeanDefinition(ChatClient, "aiChatClient"))
    factory.register_instance("aiChatClient", client)
    factory.register_bean_definition("assistant", BeanDefinition(Assistant, "assistant"))
    assert factory.get_bean("assistant").client is client


@pytest.mark.parametrize("prefix", ["springbootai.ai", "spring.ai", "ai"])
def test_enabled_application_installs_ai_without_configuration_class(prefix, monkeypatch):
    from springbootai.context.application_context import ApplicationContext
    from springbootai.context.bean_factory import BeanFactory
    from springbootai.context.registry import BeanRegistry

    monkeypatch.setenv("AI_ALLOW_FAKE", "true")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    registry = BeanRegistry()
    monkeypatch.setattr(registry, "_beans", {})
    monkeypatch.setattr(registry, "_types", {})

    class Config:
        def get_prefix_config(self, name):
            return {"enabled": True} if name == prefix else {}

        def get(self, name, default=None):
            return {"enabled": True} if name == prefix else default

    context = object.__new__(ApplicationContext)
    context.config_loader = Config()
    context.bean_factory = BeanFactory()
    context._configure_ai_defaults()
    assert isinstance(context.get_bean("aiChatClient"), ChatClient)
    assert "hello" in context.get_bean("aiChatClient").chat("hello")


def test_disabled_ai_and_custom_client_do_not_build_defaults(monkeypatch):
    from springbootai.ai import autoconfig
    from springbootai.context.application_context import ApplicationContext
    from springbootai.context.bean_definition import BeanDefinition
    from springbootai.context.bean_factory import BeanFactory

    def unexpected(**kwargs):
        raise AssertionError("should not auto-configure")

    monkeypatch.setattr(autoconfig, "configure_ai", unexpected)

    class Config:
        enabled = False

        def get_prefix_config(self, name):
            return {"enabled": self.enabled}

    config = Config()
    context = object.__new__(ApplicationContext)
    context.config_loader = config
    context.bean_factory = BeanFactory()
    context._configure_ai_defaults()
    config.enabled = True
    custom = ChatClient(FakeChatModel())
    context.bean_factory.register_bean_definition("aiChatClient", BeanDefinition(ChatClient, "aiChatClient"))
    context.bean_factory.register_instance("aiChatClient", custom)
    context._configure_ai_defaults()
    assert context.get_bean("aiChatClient") is custom


def test_application_refresh_enables_declarative_service_without_ai_beans(tmp_path, monkeypatch):
    from springbootai.annotations import Service, SpringBootApplication
    from springbootai.config.config_loader import ConfigLoader
    from springbootai.context import application_context as contexts
    from springbootai.context.registry import BeanRegistry

    monkeypatch.setenv("AI_ALLOW_FAKE", "true")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    registry = BeanRegistry()
    monkeypatch.setattr(registry, "_beans", {})
    monkeypatch.setattr(registry, "_types", {})
    monkeypatch.setattr(contexts.ApplicationContext, "_current_context", None)
    monkeypatch.setattr(contexts, "set_global_config_loader", lambda config: config)
    (tmp_path / "application.yml").write_text("spring:\n  ai:\n    enabled: true\n", encoding="utf-8")

    @SpringBootApplication(scan_base_packages=["sample"])
    class Application:
        pass

    @Service
    class Assistant:
        @Prompt("hello:{text}")
        def greet(self, text: str) -> str:
            ...

    context = contexts.ApplicationContext(Application, ConfigLoader(base_path=str(tmp_path)))
    monkeypatch.setattr(context.scanner, "scan", lambda packages: [Assistant])
    try:
        context.refresh()
        assert "hello:world" in context.get_bean("assistant").greet("world")
    finally:
        context.destroy()


def test_auto_configured_client_reuses_custom_model_and_embedding(monkeypatch):
    from springbootai.ai import FakeEmbeddingModel, autoconfig
    from springbootai.context.bean_definition import BeanDefinition
    from springbootai.context.bean_factory import BeanFactory
    from springbootai.context.registry import BeanRegistry

    registry = BeanRegistry()
    monkeypatch.setattr(registry, "_beans", {})
    monkeypatch.setattr(registry, "_types", {})
    factory = BeanFactory()
    model = FakeChatModel()
    embedding = FakeEmbeddingModel()
    for name, value in [("aiChatModel", model), ("aiEmbeddingModel", embedding)]:
        factory.register_bean_definition(name, BeanDefinition(type(value), name))
        factory.register_instance(name, value)

    def unexpected(*args, **kwargs):
        raise AssertionError("custom model should be reused")

    monkeypatch.setattr(autoconfig, "_build_chat_model", unexpected)
    monkeypatch.setattr(autoconfig, "_build_embedding_model", unexpected)

    class Config:
        def get_prefix_config(self, name):
            return {}

        def get(self, name, default=None):
            return default

    beans = autoconfig.configure_ai(config=Config(), bean_factory=factory)
    assert beans["aiChatClient"].chat_model is model
    assert beans["aiEmbeddingModel"] is embedding
    assert factory.get_bean("aiChatClient") is beans["aiChatClient"]


def test_custom_vector_store_can_inject_auto_configured_embedding(monkeypatch):
    from springbootai.annotations import Autowired
    from springbootai.ai import FakeEmbeddingModel, autoconfig
    from springbootai.context.bean_definition import BeanDefinition
    from springbootai.context.bean_factory import BeanFactory
    from springbootai.context.registry import BeanRegistry

    registry = BeanRegistry()
    monkeypatch.setattr(registry, "_beans", {})
    monkeypatch.setattr(registry, "_types", {})
    monkeypatch.setattr(autoconfig, "_build_chat_model", lambda *args, **kwargs: FakeChatModel())
    embedding = FakeEmbeddingModel()
    monkeypatch.setattr(autoconfig, "_build_embedding_model", lambda *args, **kwargs: embedding)

    class CustomStore(SimpleInMemoryVectorStore):
        @Autowired
        def __init__(self, embedding_model: FakeEmbeddingModel):
            super().__init__(embedding_model)

    factory = BeanFactory()
    definition = BeanDefinition(CustomStore, "aiVectorStore")
    definition.add_dependency("embedding_model", FakeEmbeddingModel)
    factory.register_bean_definition("aiVectorStore", definition)

    class Config:
        def get_prefix_config(self, name):
            return {}

        def get(self, name, default=None):
            return default

    beans = autoconfig.configure_ai(config=Config(), bean_factory=factory)
    assert isinstance(beans["aiVectorStore"], CustomStore)
    assert beans["aiVectorStore"]._embedding_model is embedding


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("with_template", [False, True])
def test_rag_empty_body_and_prompt_composition_retrieve_documents(asynchronous, with_template):
    if asynchronous:
        @RAG
        async def method(self, question: str) -> str:
            ...
    else:
        @RAG
        def method(self, question: str) -> str:
            ...
    if with_template:
        method = Prompt("question:{question}")(method)
    model = RecordingModel()
    container = Container(model)
    class ConstantEmbedding:
        def embed_one(self, text):
            return [1.0]

    container.beans["aiEmbeddingModel"] = ConstantEmbedding()
    store = SimpleInMemoryVectorStore()
    store.add([VectorDocument("public", "knowledge", [1.0], {})])
    container.beans["aiVectorStore"] = store
    wrapped = apply_ai_annotations(container, object(), method)
    value = wrapped(object(), "hello")
    assert (run(value) if asynchronous else value) == "answer"
    assert any("knowledge" in message.content for message in model.messages)
    assert model.messages[-1].content == ("question:hello" if with_template else "hello")


def test_chat_shortcuts_keep_defaults_options_and_authenticated_memory():
    from springbootai.ai import InMemoryChatMemory, MessageChatMemoryAdvisor

    memory = InMemoryChatMemory()
    model = RecordingModel()
    client = ChatClient(model).default_system("assistant").default_advisors_set(
        MessageChatMemoryAdvisor(memory))
    SecurityContextHolder.set_authentication({"principal": "alice"})
    assert client.chat("first", conversation_id="same", temperature=0.2) == "answer"
    assert model.options["temperature"] == 0.2
    assert run(client.achat("second", conversation_id="same")) == "answer"
    assert any(message.content == "first" for message in model.messages)
    SecurityContextHolder.set_authentication({"principal": "bob"})
    assert client.chat("third", conversation_id="same") == "answer"
    assert all(message.content != "first" for message in model.messages)
    assert any(message.content == "assistant" for message in model.messages)


def test_text_stream_shortcuts_return_chunks_and_finish_memory():
    from springbootai.ai import InMemoryChatMemory, MessageChatMemoryAdvisor

    memory = InMemoryChatMemory()
    client = ChatClient(FakeChatModel()).default_advisors_set(MessageChatMemoryAdvisor(memory))
    SecurityContextHolder.set_authentication({"principal": "alice"})
    sync = "".join(client.stream_text("hello", conversation_id="sync"))
    assert "hello" in sync

    async def collect():
        return "".join([text async for text in client.astream_text("world", conversation_id="async")])

    assert "world" in run(collect())
    assert memory.get("sync", namespace="alice")[-1].content == sync
    assert "world" in memory.get("async", namespace="alice")[-1].content


@pytest.mark.parametrize("asynchronous", [False, True])
def test_closing_text_stream_immediately_closes_provider(asynchronous):
    closed = []

    class StreamingModel(RecordingModel):
        def stream(self, messages, tool_registry=None, options=None):
            try:
                yield ChatResponse([Generation(Message.assistant("first"))])
                yield ChatResponse([Generation(Message.assistant("second"))])
            finally:
                closed.append(True)

        async def astream(self, messages, tool_registry=None, options=None):
            try:
                yield ChatResponse([Generation(Message.assistant("first"))])
                yield ChatResponse([Generation(Message.assistant("second"))])
            finally:
                closed.append(True)

    client = ChatClient(StreamingModel())
    if asynchronous:
        async def invoke():
            iterator = client.astream_text("hello")
            assert await anext(iterator) == "first"
            await iterator.aclose()
            assert closed == [True]
        run(invoke())
    else:
        iterator = client.stream_text("hello")
        assert next(iterator) == "first"
        iterator.close()
        assert closed == [True]


def test_cancelled_base_acall_keeps_capacity_until_blocking_provider_finishes():
    started = threading.Event()
    finish = threading.Event()

    class BlockingModel(ChatModel):
        max_concurrent_requests = 1
        concurrency_acquire_timeout = 0.1

        def _raw_call(self, messages, tool_registry=None, options=None):
            started.set()
            assert finish.wait(2)
            return ChatResponse([Generation(Message.assistant("done"))])

    model = BlockingModel()

    async def invoke():
        task = asyncio.create_task(model.acall([Message.user("hello")]))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            slots = model._capacity_semaphore()
            available = slots.acquire(blocking=False)
            if available:
                slots.release()
            assert not available
        finally:
            finish.set()

    run(invoke())
    slots = model._capacity_semaphore()
    assert slots.acquire(blocking=False)
    slots.release()


def test_cancelled_graph_capacity_wait_does_not_leak_a_slot():
    workflow = object.__new__(LangGraphWorkflow)
    workflow.properties = LangGraphProperties(max_concurrent_executions=1)
    called = threading.Event()
    blocking = threading.Event()
    finished = threading.Event()

    class ObservedSlots:
        def __init__(self):
            self.slots = threading.BoundedSemaphore(1)

        def acquire(self, *args, **kwargs):
            if kwargs.get("blocking", True):
                blocking.set()
            called.set()
            value = self.slots.acquire(*args, **kwargs)
            if kwargs.get("blocking", True):
                finished.set()
            return value

        def release(self):
            self.slots.release()

    slots = ObservedSlots()
    assert slots.slots.acquire(blocking=False)
    workflow._execution_slots = slots

    async def invoke():
        task = asyncio.create_task(workflow._acquire_execution_async())
        assert await asyncio.to_thread(called.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        slots.release()
        if blocking.is_set():
            assert await asyncio.to_thread(finished.wait, 1)
        available = slots.acquire(blocking=False)
        if available:
            slots.release()
        assert available

    run(invoke())


def test_graph_capacity_wait_still_times_out_without_blocking_event_loop():
    workflow = object.__new__(LangGraphWorkflow)
    workflow.properties = LangGraphProperties(max_concurrent_executions=1, acquire_timeout_seconds=0.03)
    workflow._execution_slots = threading.BoundedSemaphore(1)
    workflow._execution_slots.acquire()

    async def invoke():
        ticks = []

        async def heartbeat():
            await asyncio.sleep(0.005)
            ticks.append(True)

        pulse = asyncio.create_task(heartbeat())
        with pytest.raises(TimeoutError, match="capacity"):
            await workflow._acquire_execution_async()
        await pulse
        assert ticks == [True]

    run(invoke())
