"""Regression coverage for defects found by the post-release enterprise audit."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_ai_annotation_identity_comes_only_from_security_context():
    from springbootai.ai.annotation_runtime import _trusted_request_context
    from springbootai.security.security_context import (
        SecurityContext,
        SecurityContextHolder,
    )

    SecurityContextHolder.clear_context()
    assert _trusted_request_context({
        "tenant_id": "victim", "user_id": "victim", "conversation_id": "c1",
    }) == {}

    context = SecurityContext()
    context.authentication = {
        "principal": "trusted-user",
        "details": {"tenant_id": "trusted-tenant", "sub": "trusted-user"},
    }
    context.principal = "trusted-user"
    token = SecurityContextHolder.set_context(context)
    try:
        trusted = _trusted_request_context({
            "tenant_id": "victim", "user_id": "victim",
            "conversation_id": "session-1",
        })
    finally:
        SecurityContextHolder.reset_context(token)

    assert trusted == {
        "tenant_id": "trusted-tenant",
        "user_id": "trusted-user",
        "conversation_id": "session-1",
    }


def test_memory_without_authenticated_namespace_is_disabled_by_default():
    from springbootai.ai.advisors import MessageChatMemoryAdvisor
    from springbootai.ai.core import AdvisorRequest, ChatResponse, Generation, Message
    from springbootai.ai.memory import InMemoryChatMemory

    memory = InMemoryChatMemory()
    advisor = MessageChatMemoryAdvisor(memory)
    request = AdvisorRequest(
        messages=[Message.user("secret")], chat_model=None,
        context={"conversation_id": "shared"},
    )

    advisor.advise_request(request)
    advisor.advise_response(
        ChatResponse([Generation(Message.assistant("answer"))]), request)

    assert request.context["memory_disabled"] is True
    assert memory.get("shared") == []


def test_langchain_adapter_enforces_threshold_and_does_not_copy_query_embedding():
    from springbootai.ai.vectorstore import LangChainVectorStore, SearchRequest

    low = SimpleNamespace(id="low", page_content="low", metadata={})
    high = SimpleNamespace(id="high", page_content="high", metadata={})

    class Backend:
        def similarity_search_with_relevance_scores(self, query, **kwargs):
            return [(low, 0.25), (high, 0.95)]

    store = LangChainVectorStore(Backend())
    documents = store.similarity_search(SearchRequest(
        query="query", embedding=[1.0, 0.0], top_k=2,
        similarity_threshold=0.8,
    ))

    assert [document.id for document in documents] == ["high"]
    assert documents[0].embedding == []


def test_langchain_adapter_rejects_unenforceable_non_default_threshold():
    from springbootai.ai.vectorstore import LangChainVectorStore, SearchRequest

    class LegacyBackend:
        def similarity_search_by_vector(self, embedding, k=4):
            return [SimpleNamespace(page_content="unscored", metadata={})]

    with pytest.raises(RuntimeError, match="cannot enforce"):
        LangChainVectorStore(LegacyBackend()).similarity_search(SearchRequest(
            query="query", embedding=[1.0], similarity_threshold=0.9))


def test_vector_adapters_bound_external_resources_and_redis_scan_bytes():
    from springbootai.ai.vectorstore import (
        Document,
        LangChainVectorStore,
        RedisVectorStore,
    )

    class AddBackend:
        def add_texts(self, *_args, **_kwargs):
            raise AssertionError("oversized input must be rejected first")

    with pytest.raises(ValueError, match="content exceeds"):
        LangChainVectorStore(
            AddBackend(), max_content_length=4,
        ).add([Document("1", "too long")])

    record = json.dumps({
        "id": "1", "content": "x" * 100,
        "embedding": [1.0], "metadata": {},
    })

    class Redis:
        def hgetall(self, _key):
            return {"1": record}

    store = RedisVectorStore(
        Redis(), max_scan_bytes=16, max_content_length=1000)
    with pytest.raises(RuntimeError, match="max_scan_bytes"):
        store._all_docs()


def test_redis_vector_clear_propagates_failure():
    from springbootai.ai.vectorstore import RedisVectorStore

    class Redis:
        def delete(self, _key):
            raise OSError("offline")

    with pytest.raises(RuntimeError, match="clear failed"):
        RedisVectorStore(Redis()).clear()


def test_gateway_sync_validator_does_not_block_event_loop():
    from springbootai.cloud.gateway import (
        AuthenticationFilter,
        FilterContext,
        Route,
    )

    def slow_validator(_token):
        time.sleep(0.15)
        return {"sub": "alice"}

    context = FilterContext(
        route=Route("r", "/**"), request_path="/private",
        request_headers={"Authorization": "Bearer token"},
        request_method="GET", request_query={},
    )

    async def scenario():
        started = time.perf_counter()
        validation = asyncio.create_task(AuthenticationFilter(
            exclude_paths=[], validator=slow_validator).pre_filter(context))
        await asyncio.sleep(0.01)
        ticker_delay = time.perf_counter() - started
        assert await validation is True
        return ticker_delay

    assert asyncio.run(scenario()) < 0.08


def test_websocket_sync_oauth_validation_does_not_block_event_loop(monkeypatch):
    from springbootai.security.oauth2 import oauth2_resource_server
    from springbootai.websocket.router import WebSocketRouter

    def slow_validate(_token):
        time.sleep(0.15)
        return {"sub": "alice"}

    monkeypatch.setattr(oauth2_resource_server, "_configured", True)
    monkeypatch.setattr(oauth2_resource_server, "validate_token", slow_validate)
    websocket = SimpleNamespace(
        headers={"authorization": "Bearer token", "host": "example.test"},
        query_params={},
    )

    async def scenario():
        started = time.perf_counter()
        authorization = asyncio.create_task(
            WebSocketRouter(allowed_origins=["*"])._authorize_handshake(
                websocket))
        await asyncio.sleep(0.01)
        ticker_delay = time.perf_counter() - started
        result = await authorization
        assert result["user"] == "alice"
        return ticker_delay

    assert asyncio.run(scenario()) < 0.08


def test_kafka_startup_failure_is_propagated_and_not_marked_running(monkeypatch):
    from springbootai.messaging.kafka import KafkaClient

    class FailedConsumer:
        def __init__(self, *_args, **_kwargs):
            raise OSError("broker unavailable")

    monkeypatch.setitem(
        sys.modules, "kafka", SimpleNamespace(KafkaConsumer=FailedConsumer))
    monkeypatch.setattr(KafkaClient, "_instance", None)
    client = KafkaClient(consumer_start_timeout=0.2)
    client.register_listener(["orders"], lambda _message: None)

    with pytest.raises(RuntimeError, match="failed to start") as raised:
        client.start_consuming()

    assert isinstance(raised.value.__cause__, OSError)
    assert client._running is False
    assert client._consumer_threads == []


def test_rabbitmq_timed_out_queued_publish_never_reaches_broker(monkeypatch):
    from springbootai.messaging.rabbitmq import RabbitMQClient

    entered_open = threading.Event()
    release_open = threading.Event()
    calls = []

    class Channel:
        is_open = True

        def confirm_delivery(self):
            return None

        def basic_publish(self, **kwargs):
            calls.append(kwargs)
            return True

    class Connection:
        is_closed = False

        def channel(self):
            return Channel()

        def close(self):
            self.is_closed = True

    def delayed_connection():
        entered_open.set()
        release_open.wait(timeout=1)
        return Connection()

    monkeypatch.setattr(RabbitMQClient, "_instance", None)
    client = RabbitMQClient(publish_timeout=0.05)
    monkeypatch.setattr(client, "_open_connection", delayed_connection)
    errors = []
    caller = threading.Thread(
        target=lambda: _capture_exception(
            errors, client.publish, "events", "orders.created", {"id": 1}))
    caller.start()
    assert entered_open.wait(timeout=0.5)
    caller.join(timeout=0.5)
    assert errors and isinstance(errors[0], TimeoutError)

    release_open.set()
    client.close()
    assert calls == []


def _capture_exception(errors, callback, *args):
    try:
        callback(*args)
    except Exception as exc:  # pragma: no branch - test helper
        errors.append(exc)


def test_rabbitmq_close_retains_stuck_publisher_thread(monkeypatch):
    from springbootai.messaging.rabbitmq import RabbitMQClient

    class StuckThread(threading.Thread):
        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.join_timeout = timeout

    monkeypatch.setattr(RabbitMQClient, "_instance", None)
    client = RabbitMQClient(publish_timeout=0.05)
    stuck = StuckThread(name="stuck-publisher")
    client._publisher_thread = stuck

    with pytest.raises(RuntimeError, match="did not stop"):
        client.close()
    assert client._publisher_thread is stuck


@pytest.mark.parametrize("dialect, generated_id", [
    ("mysql", 41),
    ("postgresql", 42),
])
def test_repository_uses_dialect_markers_and_same_cursor_generated_id(
        dialect, generated_id):
    from springbootai.data.repository import PagingAndSortingRepository
    from tests.test_data_repository import User

    class Cursor:
        rowcount = 1
        lastrowid = generated_id

        def __init__(self):
            self.calls = []
            self.closed = False

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return (generated_id,)

        def close(self):
            self.closed = True

    cursor = Cursor()

    class Connection:
        def cursor(self):
            return cursor

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    pool = SimpleNamespace(connection=lambda: Connection())
    repository = PagingAndSortingRepository(pool, User, dialect=dialect)
    user = User(name="Alice", age=30, email="a@example.test")

    repository._insert(user)

    sql = cursor.calls[0][0]
    assert "%s" in sql
    assert len(cursor.calls) == 1
    assert user.id == generated_id
    assert cursor.closed is True
    assert (" RETURNING " in sql) is (dialect == "postgresql")


def test_async_retry_invokes_and_awaits_recover_method():
    from springbootai.annotations.core import Recover
    from springbootai.retry.retry_annotations import Retryable
    from springbootai.retry.retry_decorator import retryable_decorator

    class Service:
        def __init__(self):
            self.calls = 0

        @retryable_decorator(Retryable(
            value=(RuntimeError,), max_attempts=2, backoff=0))
        async def fetch(self, key):
            self.calls += 1
            raise RuntimeError("secret failure")

        @Recover(RuntimeError)
        async def recover(self, error, key):
            await asyncio.sleep(0)
            return f"fallback:{key}:{type(error).__name__}"

    service = Service()
    assert asyncio.run(service.fetch("orders")) == "fallback:orders:RuntimeError"
    assert service.calls == 2


def test_sql_and_retry_logs_do_not_emit_raw_values(caplog):
    from springbootai.orm.pymybatis.dynamic_sql.dynamic_sql import (
        DynamicSQLProcessor,
    )
    from springbootai.orm.pymybatis.security.sql_injection_detector import (
        SQLInjectionDetector,
    )
    from springbootai.retry.retry_annotations import Retryable
    from springbootai.retry.retry_decorator import retryable_decorator

    secret = "super-secret-value"
    with caplog.at_level("DEBUG"):
        DynamicSQLProcessor("?").process(
            "SELECT * FROM users WHERE password = #{password}",
            {"password": secret},
        )
        detector = SQLInjectionDetector(allow_raw_params=True)
        assert detector.detect_raw_param("table", f"{secret};DROP") is False
        assert detector.detect_ddl(f"DROP TABLE {secret}") is True

        @retryable_decorator(Retryable(max_attempts=1, backoff=0))
        def fail():
            raise RuntimeError(secret)

        with pytest.raises(RuntimeError):
            fail()

    assert secret not in caplog.text


def test_publish_workflow_requires_ci_and_matches_coverage_gate():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8")

    assert "workflow_id: 'ci.yml'" in workflow
    assert "--cov-fail-under=68" in workflow
    assert "springbootai/py.typed" in workflow


def test_ci_defers_coverage_gate_until_all_test_slices_finish():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")

    assert "--cov-append --cov-report=term --cov-fail-under=0" in workflow
    assert "--cov-append --cov-report=xml --cov-report=term" in workflow
    assert "--cov-fail-under=68" in workflow
