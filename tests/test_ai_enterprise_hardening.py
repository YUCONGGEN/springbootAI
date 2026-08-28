"""Regression tests for enterprise AI isolation, safety and resilience."""

import time

import pytest

from springbootai.ai import (
    ChatClientBuilder,
    ChatModel,
    ChatResponse,
    Generation,
    InMemoryChatMemory,
    Message,
    MessageChatMemoryAdvisor,
    ProviderStreamError,
    QuestionAnswerAdvisor,
    SimpleInMemoryVectorStore,
    TokenBudgetExceededError,
    ToolExecutionPolicy,
    ToolLoopLimitExceededError,
    ToolRegistry,
    VectorDocument,
)
from springbootai.ai.core import AdvisorRequest


class _ConstantEmbedding:
    def embed_one(self, _text):
        return [1.0, 0.0]


def test_same_conversation_id_isolated_by_tenant():
    memory = InMemoryChatMemory()
    advisor = MessageChatMemoryAdvisor(memory)

    request_a = AdvisorRequest(
        messages=[Message.user("tenant-a-secret")],
        chat_model=None,
        context={"conversation_id": "shared", "tenant_id": "tenant-a"},
    )
    advisor.advise_request(request_a)
    advisor.advise_response(
        ChatResponse([Generation(Message.assistant("answer-a"))]), request_a)

    request_b = AdvisorRequest(
        messages=[Message.user("tenant-b-question")],
        chat_model=None,
        context={"conversation_id": "shared", "tenant_id": "tenant-b"},
    )
    advisor.advise_request(request_b)

    assert [message.content for message in request_b.messages] == [
        "tenant-b-question"
    ]
    assert [message.content for message in memory.get(
        "shared", namespace="tenant-a")] == ["tenant-a-secret", "answer-a"]


def test_memory_namespace_is_key_safe_and_bounded():
    memory = InMemoryChatMemory()
    long_id = "customer:*:" + "x" * 1000
    memory.add(long_id, Message.user("secret"), namespace="tenant:a")

    assert memory.get(long_id, namespace="tenant:a")[0].content == "secret"
    assert all(len(part) <= 256 for key in memory._store for part in key)


def test_rag_filters_documents_by_verified_tenant_context():
    store = SimpleInMemoryVectorStore()
    store.add([
        VectorDocument("a", "tenant-a-secret", [1.0, 0.0], {"tenant_id": "a"}),
        VectorDocument("b", "tenant-b-secret", [1.0, 0.0], {"tenant_id": "b"}),
    ])
    advisor = QuestionAnswerAdvisor(
        store, embedding_model=_ConstantEmbedding(), top_k=10)
    request = AdvisorRequest(
        messages=[Message.user("secret")],
        chat_model=None,
        context={"tenant_id": "b"},
    )

    advisor.advise_request(request)

    assert "tenant-b-secret" in request.messages[0].content
    assert "tenant-a-secret" not in request.messages[0].content
    assert [doc["id"] for doc in request.context["retrieved_documents"]] == ["b"]


def test_langchain_vector_store_refuses_unfiltered_fallback():
    from springbootai.ai.vectorstore import LangChainVectorStore, SearchRequest

    class LegacyStore:
        def similarity_search_by_vector(self, embedding, k):
            return []

    store = LangChainVectorStore(LegacyStore())
    with pytest.raises(RuntimeError, match="does not support metadata filters"):
        store.similarity_search(SearchRequest(
            query="x", embedding=[1.0], filter_metadata={"tenant_id": "a"}))


def test_tool_authorizer_receives_request_identity_context():
    seen = []
    registry = ToolRegistry(policy=ToolExecutionPolicy(
        authorizer=lambda name, arguments, context: seen.append(context) or True))
    registry.register("identity", lambda: "ok")

    from springbootai.ai.providers import FakeChatModel

    client = (ChatClientBuilder(FakeChatModel(simulate_tool_call=True))
              .default_tools(registry).build())
    response = (client.prompt().user("请调用工具")
                .param("tenant_id", "tenant-42")
                .param("user_id", "user-7").call())

    assert "工具返回: ok" in response.content()
    assert seen == [{"tenant_id": "tenant-42", "user_id": "user-7"}]


def test_non_cooperative_timed_tool_is_rejected_before_side_effect():
    effects = []
    registry = ToolRegistry(policy=ToolExecutionPolicy(timeout_seconds=0.01))

    def unsafe_tool():
        effects.append("started")

    registry.register("unsafe", unsafe_tool)
    with pytest.raises(Exception, match="does not accept.*cancellation_token"):
        registry.execute("unsafe", {})
    assert effects == []


def test_cooperative_timeout_leaves_no_background_side_effect():
    effects = []
    registry = ToolRegistry(policy=ToolExecutionPolicy(
        timeout_seconds=0.02, cancellation_grace_seconds=0.2))

    def bounded_tool(cancellation_token):
        if cancellation_token.wait(1):
            cancellation_token.raise_if_cancelled()
        effects.append("committed")  # pragma: no cover

    definition = registry.register("bounded", bounded_tool)
    assert "cancellation_token" not in definition.to_schema()[
        "function"]["parameters"]["properties"]

    with pytest.raises(Exception, match="timed out"):
        registry.execute("bounded", {})
    time.sleep(0.03)
    assert effects == []


def test_duplicate_tool_registration_is_rejected():
    registry = ToolRegistry()
    registry.register("lookup", lambda: 1)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register("lookup", lambda: 2)


def test_request_tools_do_not_weaken_default_registry_policy():
    from springbootai.ai.providers import FakeChatModel

    registry = ToolRegistry(policy=ToolExecutionPolicy(
        authorizer=lambda name, arguments, context: False))
    registry.register("protected", lambda: "secret")

    def request_tool():
        return "public"

    spec = (ChatClientBuilder(FakeChatModel()).default_tools(registry).build()
            .prompt().tools(request_tool))
    combined = spec._resolve_registry()

    with pytest.raises(PermissionError, match="authorization"):
        combined.execute("protected", {})
    assert combined.execute("request_tool", {}) == "public"


def test_langchain_mapping_tool_calls_close_the_loop_without_shared_mutation():
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage, ToolMessage
    from springbootai.ai.providers import OpenAIChatModel

    class BoundModel:
        def __init__(self, root):
            self.root = root

        def invoke(self, messages):
            self.root.invocations.append(messages)
            if len(self.root.invocations) == 1:
                return AIMessage(content="", tool_calls=[{
                    "id": "call-1", "name": "add", "args": {"a": 2, "b": 3},
                    "type": "tool_call",
                }])
            return AIMessage(content="five", usage_metadata={
                "input_tokens": 5, "output_tokens": 1, "total_tokens": 6})

    class RootModel:
        def __init__(self):
            self.invocations = []
            self.bound_schemas = []

        def bind_tools(self, schemas):
            self.bound_schemas.append(schemas)
            return BoundModel(self)

    root = RootModel()
    model = OpenAIChatModel(api_key="", max_retries=0)
    model._llm = root
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b)

    response = model.call([Message.user("2+3")], registry)

    assert response.content() == "five"
    assert model._llm is root
    assert len(root.bound_schemas) == 2
    assert any(isinstance(message, ToolMessage)
               and message.tool_call_id == "call-1"
               for message in root.invocations[1])


def test_langchain_path_retries_transient_transport_errors():
    import httpx
    from langchain_core.messages import AIMessage
    from springbootai.ai.providers import OpenAIChatModel

    class FlakyModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("temporary")
            return AIMessage(content="ok")

    model = OpenAIChatModel(api_key="", max_retries=2, retry_delay_ms=0)
    model._llm = FlakyModel()

    assert model.call([Message.user("hi")]).content() == "ok"
    assert model._llm.calls == 2


def test_partial_http_stream_is_not_retried_or_duplicated(monkeypatch):
    import json
    import requests
    from springbootai.ai.providers import OpenAIChatModel

    calls = []

    class BrokenResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield "data: " + json.dumps({
                "choices": [{"delta": {"content": "partial"}}]})
            raise requests.ConnectionError("connection details must stay internal")

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return BrokenResponse()

    monkeypatch.setattr(requests, "post", post)
    model = OpenAIChatModel(api_key="")
    model._llm = None
    iterator = model.stream([Message.user("hi")])

    assert next(iterator).content() == "partial"
    with pytest.raises(ProviderStreamError, match="partial response") as raised:
        next(iterator)
    assert len(calls) == 1
    assert "connection details" not in str(raised.value)


class _UsageModel(ChatModel):
    def _raw_call(self, messages, tool_registry=None, options=None):
        return ChatResponse(
            [Generation(Message.assistant("answer"))],
            metadata={"usage": {"prompt_tokens": 4, "completion_tokens": 3}},
        )


def test_request_token_budget_is_enforced_through_prompt_option():
    client = ChatClientBuilder(_UsageModel()).build()
    with pytest.raises(TokenBudgetExceededError, match="token budget"):
        client.prompt().user("hi").option("max_total_tokens", 5).call()


class _LoopingToolModel(ChatModel):
    def __init__(self):
        self.max_tool_iterations = 1
        self.calls = 0

    def _raw_call(self, messages, tool_registry=None, options=None):
        self.calls += 1
        tool_calls = [{
            "id": f"call-{self.calls}",
            "function": {"name": "ping", "arguments": "{}"},
        }]
        return ChatResponse(
            [Generation(Message(
                content="", type="assistant", metadata={"tool_calls": tool_calls}))],
            metadata={"tool_calls": tool_calls, "usage": {"total_tokens": 1}},
        )


def test_tool_loop_limit_raises_instead_of_returning_dangling_call():
    effects = []
    registry = ToolRegistry()
    registry.register("ping", lambda: effects.append("ping") or "pong")
    model = _LoopingToolModel()

    with pytest.raises(ToolLoopLimitExceededError, match="tool loop"):
        model.call([Message.user("loop")], registry)
    assert model.calls == 2
    assert effects == ["ping"]


def test_ai_limits_validate_and_wire_to_provider(monkeypatch):
    from springbootai.ai.autoconfig import _build_chat_model, bind_ai_config

    monkeypatch.setenv("AI_ALLOW_FAKE", "false")
    props = bind_ai_config({
        "default-provider": "openai",
        "request-timeout-seconds": 17,
        "max-output-tokens": 321,
        "max-total-tokens": 654,
        "max-tool-iterations": 2,
        "openai": {"api-key": "sk-test"},
    })
    model = _build_chat_model(props)

    assert model.timeout == 17
    assert model.max_output_tokens == 321
    assert model.max_total_tokens == 654
    assert model.max_tool_iterations == 2

    with pytest.raises(ValueError, match="max_tool_iterations"):
        bind_ai_config({"max-tool-iterations": 101})
