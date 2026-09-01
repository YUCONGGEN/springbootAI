"""Regression tests for enterprise hardening findings discovered after 2.3.10."""

import asyncio
import datetime
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from springbootai.ai.core import Message
from springbootai.ai.memory import RedisChatMemory
from springbootai.ai.vectorstore import (
    Document,
    LangChainVectorStore,
    SearchRequest,
    SimpleInMemoryVectorStore,
)
from springbootai.cloud.gateway import (
    AuthenticationFilter,
    FilterContext,
    GatewayRouter,
)
from springbootai.orm.pymybatis.security.access_control import (
    RoleBasedAccessControl,
    RowLevelAccessControl,
)
from springbootai.orm.pymybatis.circuit_breaker.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    with_circuit_breaker,
)
from springbootai.orm.pymybatis.transaction.transaction import (
    Transaction,
    TransactionStatus,
)
from springbootai.scheduling.scheduler import Scheduler
from springbootai.security.oauth2 import JwksCache
from springbootai.web.exception_handler import GlobalExceptionHandler
from springbootai.web.result import Result
from springbootai.annotations.cache import CacheConfig
from springbootai.annotations.core import Cacheable
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.bean_factory import BeanFactory


def _filter_context(token: str = "token") -> FilterContext:
    return FilterContext(
        route=SimpleNamespace(id="auth"),
        request_path="/private",
        request_headers={"Authorization": f"Bearer {token}"},
        request_method="GET",
        request_query={},
    )


def test_gateway_awaits_async_authentication_validator_and_fails_closed():
    async def reject(_token):
        await asyncio.sleep(0)
        return False

    context = _filter_context()
    allowed = asyncio.run(
        AuthenticationFilter(exclude_paths=[], validator=reject).pre_filter(context)
    )

    assert allowed is False
    assert context.response_status == 401
    assert "principal" not in context.attributes


def test_gateway_preserves_async_authentication_principal():
    async def accept(token):
        await asyncio.sleep(0)
        return {"sub": token}

    context = _filter_context("alice")
    allowed = asyncio.run(
        AuthenticationFilter(exclude_paths=[], validator=accept).pre_filter(context)
    )

    assert allowed is True
    assert context.attributes["principal"] == {"sub": "alice"}


@pytest.mark.parametrize("expression", ["tenant_id", "tenant_id:", ":A", " : "])
def test_vector_filters_reject_malformed_expressions(expression):
    store = SimpleInMemoryVectorStore()
    store.add([
        Document(id="other", content="secret", embedding=[1.0],
                 metadata={"tenant_id": "B"})
    ])

    with pytest.raises(ValueError, match="filter_expression"):
        store.similarity_search(SearchRequest(
            query="", embedding=[1.0], filter_expression=expression))


def test_langchain_filter_never_falls_back_to_unfiltered_query():
    class Store:
        calls = []

        def similarity_search_by_vector(self, *args, **kwargs):
            self.calls.append(kwargs)
            return [SimpleNamespace(
                id="other", page_content="secret", metadata={"tenant_id": "B"})]

    backend = Store()
    store = LangChainVectorStore(backend)

    with pytest.raises(ValueError, match="filter_expression"):
        store.similarity_search(SearchRequest(
            query="", embedding=[1.0], filter_expression="tenant_id:"))
    assert backend.calls == []


def test_rbac_normalizes_rule_key_and_applies_fields_for_current_role_only():
    access = RoleBasedAccessControl(enabled=True)
    access.add_rule("admin", "Accounts", "select", fields=["id", "secret"])
    access.add_rule("guest", "accounts", "SELECT", fields=["id"])

    assert access.check_access(
        "accounts", "SELECT", {"role": "admin"}, {}) is True
    assert access.check_fields(
        "ACCOUNTS", "select", ["id", "secret"], {"role": "admin"}
    ) == ["id", "secret"]
    assert access.check_fields("accounts", "SELECT", ["id"], None) == []


def test_row_level_access_control_without_filter_fails_closed():
    access = RowLevelAccessControl(enabled=True)

    assert access.check_access("orders", "SELECT", {"tenant_id": "A"}, {}) is False
    assert access.get_access_condition(
        "orders", "SELECT", {"tenant_id": "A"}) is None

    access.set_row_filter("Orders", lambda user: f"tenant_id = '{user['tenant_id']}'")
    assert access.check_access("orders", "SELECT", {"tenant_id": "A"}, {}) is True
    assert access.get_access_condition(
        "ORDERS", "SELECT", {"tenant_id": "A"}) == "tenant_id = 'A'"


def test_gateway_checks_actual_body_size_not_declared_content_length():
    upstream_calls = []

    async def upstream(request: httpx.Request):
        upstream_calls.append(await request.aread())
        return httpx.Response(200, json={"ok": True})

    gateway = GatewayRouter(
        default_filters=[], max_body_size=3,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["POST"])

    async def scenario():
        try:
            async def body():
                yield b"12345"

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.post(
                    "/api/write", content=body(), headers={"content-length": "1"})
        finally:
            await gateway.aclose()

    response = asyncio.run(scenario())
    assert response.status_code == 413
    assert upstream_calls == []


def test_gateway_rewrites_incorrect_small_content_length_to_actual_size():
    observed = {}

    async def upstream(request: httpx.Request):
        payload = await request.aread()
        observed.update(length=request.headers.get("content-length"), body=payload)
        return httpx.Response(200)

    gateway = GatewayRouter(
        default_filters=[], max_body_size=10,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/api/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/api/{path:path}", gateway.handle_asgi, methods=["POST"])

    async def scenario():
        try:
            async def body():
                yield b"12345"

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.post(
                    "/api/write", content=body(), headers={"content-length": "1"})
        finally:
            await gateway.aclose()

    assert asyncio.run(scenario()).status_code == 200
    assert observed == {"length": "5", "body": b"12345"}


def test_database_circuit_breaker_records_async_failure_after_await():
    breaker = CircuitBreaker(failure_threshold=1)

    async def fail():
        await asyncio.sleep(0)
        raise RuntimeError("database unavailable")

    awaitable = breaker.call(fail)
    assert breaker._concurrent_requests == 1
    assert breaker.get_state() == CircuitBreakerState.CLOSED.value

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(awaitable)
    assert breaker._concurrent_requests == 0
    assert breaker.get_state() == CircuitBreakerState.OPEN.value
    assert breaker.get_stats()["total_failures"] == 1


def test_database_circuit_breaker_decorator_preserves_async_function():
    breaker = CircuitBreaker(failure_threshold=1)

    @with_circuit_breaker(breaker)
    async def succeed():
        await asyncio.sleep(0)
        return "ok"

    assert asyncio.iscoroutinefunction(succeed)
    assert asyncio.run(succeed()) == "ok"
    assert breaker.get_stats()["total_successes"] == 1


def test_ai_circuit_breaker_and_retry_track_async_completion():
    from springbootai.ai.resilience import (
        AICircuitBreaker,
        CircuitState,
        TransientError,
        resilient_call,
    )

    breaker = AICircuitBreaker(failure_threshold=1)

    async def fail():
        await asyncio.sleep(0)
        raise TransientError("provider unavailable")

    with pytest.raises(TransientError):
        asyncio.run(breaker.call(fail))
    assert breaker.state == CircuitState.OPEN

    retry_breaker = AICircuitBreaker(failure_threshold=2)
    attempts = 0

    async def flaky():
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0)
        if attempts == 1:
            raise TransientError("temporary")
        return "ok"

    wrapped = resilient_call(
        flaky, max_retries=2, retry_delay_ms=0,
        retry_exceptions=(TransientError,), circuit_breaker=retry_breaker,
        count_as_failure_exc=(TransientError,),
    )
    assert asyncio.run(wrapped()) == "ok"
    assert attempts == 2
    assert retry_breaker.state == CircuitState.CLOSED


def test_five_field_cron_uses_second_zero_and_cron_weekdays():
    scheduler = Scheduler()
    fixed_now = datetime.datetime(2026, 8, 29, 12, 34, 10, 250000)
    with patch("datetime.datetime") as datetime_type:
        datetime_type.now.return_value = fixed_now
        delay = scheduler._parse_cron("* * * * *")

    assert delay == pytest.approx(49.75)
    assert scheduler._matches_weekday(6, "0") is True
    assert scheduler._matches_weekday(6, "7") is True
    assert scheduler._matches_weekday(0, "1") is True


def test_cron_waits_for_first_match_before_invoking():
    scheduler = Scheduler()
    calls = []
    scheduler._parse_cron = lambda _expr: 60.0

    async def scenario():
        task = asyncio.create_task(
            scheduler._schedule_cron("future", lambda: calls.append(1),
                                     "0 0 1 1 *", 0))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert calls == []


def test_transaction_commit_failure_has_recoverable_failed_state():
    class Connection:
        def begin(self):
            pass

        def commit(self):
            raise OSError("connection lost")

        def rollback(self):
            self.rolled_back = True

    connection = Connection()
    transaction = Transaction(connection)
    transaction.begin()

    with pytest.raises(OSError, match="connection lost"):
        transaction.commit()
    assert transaction.status is TransactionStatus.FAILED
    assert transaction.nested_count == 1

    transaction.rollback()
    assert transaction.status is TransactionStatus.ROLLED_BACK
    assert transaction.nested_count == 0
    assert connection.rolled_back is True


def test_jwks_cache_rejects_keys_older_than_maximum_stale_age(monkeypatch):
    cache = JwksCache(
        "https://issuer.example/jwks", refresh_interval=1,
        failure_retry_interval=1, max_stale_age=2,
    )
    cache._keys = {"old": {"kid": "old"}}
    cache._last_fetch = time.time() - 3
    monkeypatch.setattr(
        cache, "_fetch_jwks",
        lambda: (_ for _ in ()).throw(OSError("issuer unavailable")),
    )

    assert cache.get_key("old") is None


def test_gateway_rejects_chunked_oversized_response_before_sending_headers():
    class Chunked(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"12"
            yield b"345"

    async def upstream(_request: httpx.Request):
        return httpx.Response(200, stream=Chunked())

    gateway = GatewayRouter(
        default_filters=[], max_response_size=3,
        transport=httpx.MockTransport(upstream),
    )
    gateway.route("/files/**", uri="https://upstream.test")
    app = FastAPI()
    app.add_api_route("/files/{path:path}", gateway.handle_asgi, methods=["GET"])

    async def scenario():
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway",
            ) as client:
                return await client.get("/files/large")
        finally:
            await gateway.aclose()

    response = asyncio.run(scenario())
    assert response.status_code == 502
    assert response.json()["error"] == "Upstream response too large"


def test_redis_memory_surfaces_write_failure():
    class Pipeline:
        def rpush(self, *_args):
            pass

        def ltrim(self, *_args):
            pass

        def expire(self, *_args):
            pass

        def execute(self):
            raise OSError("redis down")

    class Redis:
        def get_client(self):
            return self

        def pipeline(self, transaction=True):
            assert transaction is True
            return Pipeline()

    memory = RedisChatMemory(redis_client=Redis())
    with pytest.raises(RuntimeError, match="write failed"):
        memory.add("conversation", Message.user("hello"))


def test_redis_memory_round_trips_message_name_and_metadata():
    class Redis:
        def __init__(self):
            self.values = {}

        def list_push(self, key, value):
            self.values.setdefault(key, []).append(value)
            return 1

        def list_length(self, key):
            return len(self.values.get(key, []))

        def list_remove_range(self, *_args):
            pass

        def list_range(self, key, start, end):
            return self.values.get(key, [])[start:]

        def delete_key(self, key):
            self.values.pop(key, None)

        def get_client(self):
            return SimpleNamespace(expire=lambda *_args: True)

    redis = Redis()
    memory = RedisChatMemory(redis_client=redis)
    message = Message(
        content="result", type="tool", name="lookup",
        metadata={"tool_call_id": "call-1"},
    )
    memory.add("conversation", message)

    assert memory.get("conversation") == [message]


def test_vector_stores_enforce_document_resource_limits():
    store = SimpleInMemoryVectorStore(
        max_documents=1, max_content_length=4,
        max_embedding_dimensions=2, max_metadata_size=16,
    )
    store.add([Document(id="one", content="1234", embedding=[1.0, 0.0])])

    with pytest.raises(RuntimeError, match="document limit"):
        store.add([Document(id="two", content="x", embedding=[1.0])])
    with pytest.raises(ValueError, match="content"):
        SimpleInMemoryVectorStore(max_content_length=4).add([
            Document(id="large", content="12345", embedding=[1.0])])
    with pytest.raises(ValueError, match="dimensions"):
        SimpleInMemoryVectorStore(max_embedding_dimensions=2).add([
            Document(id="wide", content="x", embedding=[1.0, 2.0, 3.0])])


def test_exception_handler_uses_specific_async_handler_and_redacts_logs(caplog):
    handler = GlobalExceptionHandler(show_details=True)
    handler.add_exception_handler(Exception, lambda _exc: "broad")

    async def value_error(exc):
        await asyncio.sleep(0)
        return Result.bad_request(str(exc))

    handler.add_exception_handler(ValueError, value_error)
    result = asyncio.run(handler.handle_async(ValueError("invalid")))
    assert result.code == 400
    assert result.message == "invalid"

    with caplog.at_level("ERROR", logger="Spring.ExceptionHandler"):
        response = handler._default_handler(
            RuntimeError("password=super-secret\nforged"))
    assert "super-secret" not in caplog.text
    assert "super-secret" not in response.message
    assert "\nforged" not in caplog.text


def test_rabbitmq_background_startup_failure_is_propagated(monkeypatch):
    from springbootai.messaging.rabbitmq import RabbitMQClient

    monkeypatch.setattr(RabbitMQClient, "_instance", None)
    client = RabbitMQClient(connection_timeout=0.1)
    client._consumers["queue"] = lambda _message: None

    def fail():
        raise OSError("broker unavailable")

    monkeypatch.setattr(client, "start_consuming", fail)
    with pytest.raises(RuntimeError, match="failed to start") as raised:
        client.start_consuming_background()
    assert isinstance(raised.value.__cause__, OSError)


def test_messaging_clients_retain_live_thread_handles_on_stop_timeout(monkeypatch):
    import threading
    from springbootai.messaging.kafka import KafkaClient
    from springbootai.messaging.rabbitmq import RabbitMQClient

    class StuckThread(threading.Thread):
        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.join_timeout = timeout

    monkeypatch.setattr(KafkaClient, "_instance", None)
    kafka = KafkaClient()
    kafka_thread = StuckThread(name="stuck-kafka")
    kafka._consumer_threads = [kafka_thread]
    with pytest.raises(RuntimeError, match="did not stop"):
        kafka.stop_consuming()
    assert kafka._consumer_threads == [kafka_thread]

    monkeypatch.setattr(RabbitMQClient, "_instance", None)
    rabbit = RabbitMQClient(connection_timeout=0.1)
    rabbit_thread = StuckThread(name="stuck-rabbit")
    rabbit._consumer_thread = rabbit_thread
    rabbit._consumer_ready.set()
    with pytest.raises(RuntimeError, match="did not stop"):
        rabbit.stop_consuming()
    assert rabbit._consumer_thread is rabbit_thread


def test_sql_session_enforces_rbac_before_appending_row_condition():
    from springbootai.orm.pymybatis.core.sql_session import SqlSession
    from springbootai.orm.pymybatis.dynamic_sql import SecurityError
    from springbootai.orm.pymybatis.security import AccessCondition

    session = object.__new__(SqlSession)
    session.configuration = SimpleNamespace(access_control_enabled=True)
    session.access_control = RoleBasedAccessControl(enabled=True)
    session._user_context = {"role": "user", "tenant_id": "A"}

    with pytest.raises(SecurityError, match="没有.*权限"):
        session._apply_access_control("SELECT * FROM orders", {})

    session.access_control.add_rule(
        "user", "orders", "select",
        condition=lambda user, _params: AccessCondition(
            "tenant_id = #{tenant_id}", {"tenant_id": user["tenant_id"]}),
    )
    params = {}
    secured_sql = session._apply_access_control(
        "SELECT * FROM orders", params)
    assert secured_sql == (
        "SELECT * FROM orders WHERE ((tenant_id = #{__access_0_tenant_id}))")
    assert params == {"__access_0_tenant_id": "A"}


def test_cache_config_named_key_generator_is_applied_to_cacheable():
    class KeyGenerator:
        def generate(self, _target, _method, params):
            return params[0]

    @CacheConfig(cache_names=["users"], key_generator="userKey")
    class Service:
        def __init__(self):
            self.calls = 0

        @Cacheable()
        def get(self, user_id, noise):
            self.calls += 1
            return {"id": user_id, "noise": noise}

    factory = BeanFactory()
    generator = KeyGenerator()
    factory.register_bean_definition(
        "userKey", BeanDefinition(KeyGenerator, "userKey"))
    factory.register_instance("userKey", generator)
    service = Service()
    factory._apply_aop_proxy(service, BeanDefinition(Service, "service"))

    assert service.get(7, "first") == {"id": 7, "noise": "first"}
    assert service.get(7, "ignored") == {"id": 7, "noise": "first"}
    assert service.calls == 1
    assert next(iter(factory._cache_metadata.values()))["namespace"] == "users"


def test_cache_keys_keep_argument_types_and_container_shapes_distinct():
    class Service:
        def __init__(self):
            self.calls = 0

        @Cacheable("typed")
        def get(self, key):
            self.calls += 1
            return type(key).__name__

    factory = BeanFactory()
    service = Service()
    factory._apply_aop_proxy(service, BeanDefinition(Service, "service"))

    assert service.get(1) == "int"
    assert service.get("1") == "str"
    assert service.get(None) == "NoneType"
    assert service.get("None") == "str"
    assert service.get([1]) == "list"
    assert service.get((1,)) == "tuple"
    assert service.calls == 6


def test_async_synchronized_decorator_supports_multiple_event_loops():
    from springbootai.annotations.core import Synchronized
    from springbootai.aop.comprehensive_aop import synchronized_decorator

    @synchronized_decorator(Synchronized())
    async def guarded(delay=0):
        await asyncio.sleep(delay)
        return "ok"

    async def contend():
        return await asyncio.gather(guarded(0.01), guarded(0))

    assert asyncio.run(contend()) == ["ok", "ok"]
    assert asyncio.run(contend()) == ["ok", "ok"]


def test_distributed_ai_circuit_breaker_increments_failures_atomically():
    from springbootai.ai.resilience import AICircuitBreaker, CircuitState

    class Redis:
        def __init__(self):
            self.hashes = {}
            self.values = {}

        def hgetall(self, key):
            return dict(self.hashes.get(key, {}))

        def hset(self, key, mapping=None, **_kwargs):
            self.hashes.setdefault(key, {}).update(mapping or {})

        def delete(self, key):
            self.values.pop(key, None)

        def set(self, key, value, nx=False, px=None):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

        def eval(self, script, numkeys, *args):
            keys = args[:numkeys]
            argv = args[numkeys:]
            state = self.hashes.setdefault(keys[0], {})
            if "HINCRBY" in script:
                failures = int(state.get("failures", 0)) + 1
                current = state.get("state", "CLOSED")
                if current == "HALF_OPEN" or failures >= int(argv[0]):
                    current = "OPEN"
                state.update(
                    failures=str(failures), state=current,
                    last_failure_time=str(argv[1]),
                )
                return [failures, current]
            if "local last_failure" in script:
                return [state.get("state", "CLOSED"),
                        int(state.get("failures", 0)),
                        float(state.get("last_failure_time", 0))]
            state.update(
                state="CLOSED", failures="0", last_failure_time="0")
            if len(keys) > 1:
                self.delete(keys[1])
            return 1

    redis = Redis()
    first = AICircuitBreaker(
        name="shared", failure_threshold=2, redis_client=redis)
    second = AICircuitBreaker(
        name="shared", failure_threshold=2, redis_client=redis)

    first.record_failure()
    second.record_failure()

    assert second.state == CircuitState.OPEN
    assert int(redis.hashes[second._redis_key]["failures"]) == 2
