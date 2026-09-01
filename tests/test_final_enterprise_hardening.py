"""Regression tests for the final enterprise hardening pass."""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


def test_langchain_tool_bridge_preserves_native_authorization_policy():
    from springbootai.ai.tools import ToolExecutionPolicy, ToolRegistry
    from springbootai.langchain.tools.tools import ToolFactory

    called = []
    registry = ToolRegistry(policy=ToolExecutionPolicy(
        authorizer=lambda _name, _arguments, _context: False,
    ))
    registry.register("safe", lambda value: called.append(value) or value)

    tools = ToolFactory.from_spring_tool_registry(registry)
    assert [tool.name for tool in tools] == ["safe"]
    with pytest.raises(PermissionError, match="authorization denied"):
        tools[0].invoke({"value": "blocked"})
    assert called == []


def test_langchain_tool_bridge_does_not_export_disabled_dangerous_tool():
    from springbootai.ai.tools import ToolRegistry
    from springbootai.langchain.tools.tools import ToolFactory

    registry = ToolRegistry()
    registry.register("erase", lambda: True, dangerous=True)
    assert ToolFactory.from_spring_tool_registry(registry) == []


def _bare_langgraph_workflow(**overrides):
    from springbootai.langgraph.runtime import LangGraphWorkflow

    defaults = dict(
        require_thread_id=True,
        checkpointer="injected",
        max_steps=20,
        max_input_bytes=4096,
        max_output_bytes=4096,
        max_stream_events=10,
        max_concurrent_executions=1,
        acquire_timeout_seconds=0.01,
        timeout_seconds=0.01,
        stream_mode="updates",
    )
    defaults.update(overrides)
    workflow = object.__new__(LangGraphWorkflow)
    workflow.properties = SimpleNamespace(**defaults)
    workflow.name = "regression"
    workflow._execution_slots = threading.BoundedSemaphore(
        workflow.properties.max_concurrent_executions
    )
    return workflow


def test_langgraph_checkpoint_namespace_is_derived_only_from_explicit_tenant():
    from springbootai.langgraph.config import LangGraphConfigurationError

    workflow = _bare_langgraph_workflow()
    config = workflow._config(
        thread_id="thread-1",
        tenant_id="tenant-a",
        config={"configurable": {
            "tenant_id": "tenant-b", "checkpoint_ns": "tenant:tenant-b",
        }},
    )
    assert config["configurable"]["tenant_id"] == "tenant-a"
    assert config["configurable"]["checkpoint_ns"] == "tenant:tenant-a"
    with pytest.raises(LangGraphConfigurationError, match="explicitly"):
        workflow._config(
            thread_id="thread-1", tenant_id=None,
            config={"configurable": {"tenant_id": "tenant-a"}},
        )


def test_langgraph_autoconfig_reads_documented_spring_prefix():
    from springbootai.context.registry import BeanRegistry
    from springbootai.langgraph.autoconfig import configure_langgraph

    class Config:
        def get_prefix_config(self, prefix):
            return {"enabled": True, "checkpointer": "none"} if prefix == "spring.langgraph" else {}

    beans = configure_langgraph(registry=BeanRegistry(), config=Config())
    assert beans["langGraphProperties"].enabled is True


def test_langgraph_timed_out_workers_keep_capacity_bounded():
    workflow = _bare_langgraph_workflow()
    release = threading.Event()

    with pytest.raises(TimeoutError, match="timed out"):
        workflow._run_sync_bounded(lambda: release.wait(1) or {"done": True})
    with pytest.raises(TimeoutError, match="capacity"):
        workflow._run_sync_bounded(lambda: {"second": True})

    release.set()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            assert workflow._run_sync_bounded(lambda: {"recovered": True}) == {
                "recovered": True
            }
            break
        except TimeoutError:
            time.sleep(0.01)
    else:
        pytest.fail("timed-out LangGraph worker never released capacity")


class _CursorProxy:
    def __init__(self, cursor, owner):
        self._cursor = cursor
        self._owner = owner

    def execute(self, sql, params=()):
        if (
            self._owner.fail_baseline
            and sql.lstrip().upper().startswith('INSERT INTO "SCHEMA_VERSION"')
            and params
            and str(params[0]) == "1"
        ):
            raise RuntimeError("forced baseline failure")
        return self._cursor.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ConnectionProxy:
    def __init__(self):
        self.raw = sqlite3.connect(":memory:")
        self.fail_baseline = False

    def cursor(self):
        return _CursorProxy(self.raw.cursor(), self)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class _SingleConnectionPool:
    def __init__(self):
        self.connection = _ConnectionProxy()
        self.borrowed = 0
        self.returned = 0

    def get_connection(self):
        self.borrowed += 1
        return SimpleNamespace(connection=self.connection)

    def return_connection(self, _pooled):
        self.returned += 1


def test_migration_baseline_failure_stops_later_versions_and_returns_connections(tmp_path):
    from springbootai.orm.migration import MigrationError, MigrationManager

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__baseline.sql").write_text(
        "CREATE TABLE first_table(id INTEGER);", encoding="utf-8"
    )
    (migrations / "V2__must_not_run.sql").write_text(
        "CREATE TABLE second_table(id INTEGER);", encoding="utf-8"
    )
    pool = _SingleConnectionPool()
    manager = MigrationManager(pool, str(migrations), dialect="sqlite")
    pool.connection.fail_baseline = True

    with pytest.raises(MigrationError, match="baseline"):
        manager.migrate(baseline=True)
    cursor = pool.connection.raw.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='second_table'"
    )
    assert cursor.fetchone() is None
    assert pool.returned == pool.borrowed


def test_migration_sql_splitter_handles_literals_dollar_blocks_and_delimiter(tmp_path):
    from springbootai.orm.migration import MigrationManager

    manager = object.__new__(MigrationManager)
    statements = manager._split_sql_statements(
        "INSERT INTO t VALUES ('a;b');\n"
        "DO $$ BEGIN PERFORM 'x;y'; END $$;\n"
        "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 'm;n'; END//\n"
        "DELIMITER ;\nSELECT 3;\n"
    )
    assert len(statements) == 4
    assert "'a;b'" in statements[0]
    assert "PERFORM 'x;y'" in statements[1]
    assert "CREATE PROCEDURE" in statements[2]


def test_replay_protection_requires_strong_key_and_signature():
    from springbootai.security.replay_protection import ReplayProtection

    with pytest.raises(ValueError, match="32"):
        ReplayProtection("weak")
    protector = ReplayProtection("s" * 32)
    valid, reason = protector.validate_request(
        str(int(time.time())), "abcdefgh12345678", ""
    )
    assert not valid and "signature" in reason.lower()


def test_replay_invalid_signature_does_not_consume_nonce():
    from springbootai.security.replay_protection import ReplayProtection

    protector = ReplayProtection("s" * 32)
    timestamp = str(int(time.time()))
    nonce = "nonce-abcdefgh"
    valid, _ = protector.validate_request(timestamp, nonce, "0" * 64)
    assert not valid
    signature = protector.generate_signature(timestamp, nonce)
    assert protector.validate_request(timestamp, nonce, signature) == (True, "OK")


def test_replay_redis_outage_fails_closed():
    from springbootai.security.replay_protection import ReplayProtection

    class OfflineRedis:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("offline")

    protector = ReplayProtection("s" * 32, redis_client=OfflineRedis())
    timestamp = str(int(time.time()))
    nonce = "nonce-redis-outage"
    signature = protector.generate_signature(timestamp, nonce)
    valid, reason = protector.validate_request(timestamp, nonce, signature)
    assert not valid and "unavailable" in reason.lower()


def test_async_metrics_and_sentinel_observe_actual_coroutine_failure(monkeypatch):
    import springbootai.aop.cloud_aop as cloud_aop
    import springbootai.aop.comprehensive_aop as aop
    from springbootai.annotations.cloud import SentinelResource
    from springbootai.annotations.core import Metrics

    monkeypatch.setattr(aop.redis_client, "get_client", lambda: None)
    monkeypatch.setattr(cloud_aop.redis_client, "get_client", lambda: None)
    aop._metrics_local_cache.pop("async.failure", None)

    @aop.metrics_decorator(Metrics(name="async.failure"))
    async def measured():
        await asyncio.sleep(0.01)
        raise RuntimeError("secret business detail")

    class Entry:
        successes = 0
        errors = 0

        def success(self):
            self.successes += 1

        def error(self):
            self.errors += 1

    entry = Entry()
    monkeypatch.setattr(
        cloud_aop, "sentinel_engine",
        SimpleNamespace(entry=lambda *_args, **_kwargs: entry),
    )

    @cloud_aop.sentinel_resource_decorator(SentinelResource("async-resource"))
    async def guarded():
        await measured()

    with pytest.raises(RuntimeError):
        asyncio.run(guarded())
    metrics = aop._metrics_local_cache["async.failure"]
    assert metrics["count"] == 1
    assert metrics["errors"] == 1
    assert metrics["total_time"] >= 0.009
    assert entry.successes == 0 and entry.errors == 1


def test_async_synchronized_serializes_coroutine_body():
    import springbootai.aop.comprehensive_aop as aop
    from springbootai.annotations.core import Synchronized

    active = 0
    maximum = 0

    @aop.synchronized_decorator(Synchronized(lock_name="async-test"))
    async def work():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.005)
        active -= 1

    async def scenario():
        await asyncio.gather(*(work() for _ in range(5)))

    asyncio.run(scenario())
    assert maximum == 1


def test_distributed_aop_does_not_fallback_after_redis_was_configured(monkeypatch):
    import springbootai.aop.comprehensive_aop as aop
    from springbootai.annotations.core import Idempotent

    monkeypatch.setattr(aop.redis_client, "_distributed_required", True)
    monkeypatch.setattr(aop.redis_client, "get_client", lambda: None)

    @aop.idempotent_decorator(Idempotent())
    def operation(value):
        return value

    with pytest.raises(aop.DistributedGuardError, match="Redis"):
        operation(1)


def test_loader_rejects_dns_alias_to_loopback(monkeypatch):
    import springbootai.langchain.loaders.loaders as loaders

    monkeypatch.setattr(
        loaders.socket, "getaddrinfo",
        lambda *_args, **_kwargs: [
            (loaders.socket.AF_INET, loaders.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )
    with pytest.raises(PermissionError):
        loaders._validate_url("http://127.0.0.1.nip.io/resource")


def test_loader_file_allowlist_and_size_limit(tmp_path):
    from springbootai.langchain.loaders.loaders import _validate_file_path

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    document = outside / "secret.txt"
    document.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError, match="允许目录"):
        _validate_file_path(str(document), allowed_roots=[str(allowed)])
    with pytest.raises(PermissionError, match="max_source_bytes"):
        _validate_file_path(
            str(document), allowed_roots=[str(outside)], max_source_bytes=2
        )


def test_redis_list_middle_range_and_hash_update_semantics():
    from springbootai.utils.redis_client import RedisClient

    class FakeRedis:
        def __init__(self):
            self.values = [0, 1, 2, 3, 4, 5]

        def eval(self, _script, _keys, _key, start, end, _marker):
            length = len(self.values)
            start = start if start >= 0 else length + start
            end = end if end >= 0 else length + end
            start = max(0, start)
            end = min(length - 1, end)
            if start >= length or end < 0 or start > end:
                return 0
            removed = end - start + 1
            del self.values[start:end + 1]
            return removed

        def hset(self, *_args):
            return 0

    client = RedisClient(timeout=0.1)
    fake = FakeRedis()
    client._client = fake
    assert client.list_remove_range("items", 2, 3) == 2
    assert fake.values == [0, 1, 4, 5]
    assert client.hash_set("hash", "field", "updated") is True


def test_pooled_connection_reports_closed_driver_connection_invalid():
    from springbootai.orm.pymybatis.pool.connection_pool import PooledConnection

    class Closed:
        def isclosed(self):
            return True

    pooled = PooledConnection(Closed(), SimpleNamespace(), time.monotonic())
    assert pooled.is_valid() is False


def test_redis_second_level_cache_is_bounded_and_writes_remote_first(monkeypatch):
    from springbootai.orm.pymybatis.cache.redis_cache import RedisSecondLevelCache

    monkeypatch.setattr(
        RedisSecondLevelCache, "_start_pubsub_listener", lambda self: None
    )

    class Pipeline:
        def __init__(self, fail=False):
            self.fail = fail

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self

        def execute(self):
            if self.fail:
                raise ConnectionError("offline")
            return []

    class Redis:
        def __init__(self):
            self.fail = False

        def pipeline(self, **_kwargs):
            return Pipeline(self.fail)

        def close(self):
            pass

    cache = RedisSecondLevelCache(max_local_entries=2)
    redis = Redis()
    cache._redis = redis
    cache.put("orders", {"id": 1}, {"value": 1})
    cache.put("orders", {"id": 2}, {"value": 2})
    cache.put("orders", {"id": 3}, {"value": 3})
    assert len(cache._local_cache) == 2

    redis.fail = True
    cache.put("orders", {"id": 4}, {"value": 4})
    failed_key = cache._generate_key("orders", {"id": 4})
    assert failed_key not in cache._local_cache
    cache.close()


def test_nacos_single_instance_selection_round_robins():
    from springbootai.cloud.discovery import NacosDiscoveryClient

    client = object.__new__(NacosDiscoveryClient)
    NacosDiscoveryClient.__init__(client)
    instances = [
        {"ip": "10.0.0.1", "port": 8080, "healthy": True, "weight": 1},
        {"ip": "10.0.0.2", "port": 8080, "healthy": True, "weight": 1},
    ]
    client.get_service_instances = lambda _service: list(instances)
    selected = [client.get_service_instance("orders")["ip"] for _ in range(4)]
    assert selected == ["10.0.0.1", "10.0.0.2", "10.0.0.1", "10.0.0.2"]
