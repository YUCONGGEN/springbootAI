"""AOP 注解完整测试 - 覆盖限流/熔断/重试/缓存/调度/审计/锁等横切关注点注解。"""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.annotations.core import (
    RateLimit, CircuitBreaker, Idempotent, AuditLog, FeatureToggle,
    Lock, Metrics, Synchronized, Validate, Trace, LogExecutionTime,
    Transactional, Cacheable, Retryable, Async, Scheduled, AsyncResult,
    get_spring_annotations,
)
from spring.retry.retry_annotations import Backoff


class TestRateLimit:
    def test_defaults(self):
        ann = RateLimit()
        assert ann.max_requests == 100
        assert ann.time_window == 60
        assert ann.key is None

    def test_custom(self):
        ann = RateLimit(max_requests=100, time_window=60, key="user")
        assert ann.max_requests == 100
        assert ann.time_window == 60
        assert ann.key == "user"

    def test_decorates(self):
        @RateLimit(max_requests=5, time_window=10, key="user")
        def api():
            pass

        anns = get_spring_annotations(api)
        assert len(anns) == 1
        assert isinstance(anns[0], RateLimit)


class TestCircuitBreaker:
    def test_defaults(self):
        ann = CircuitBreaker()
        assert ann.failure_threshold == 5
        assert ann.recovery_timeout == 30
        assert ann.fallback_method is None

    def test_custom(self):
        ann = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=4,
            fallback_method="fallback",
        )
        assert ann.failure_threshold == 2
        assert ann.recovery_timeout == 4
        assert ann.fallback_method == "fallback"


class TestIdempotent:
    def test_defaults(self):
        ann = Idempotent()
        assert ann.expire == 300
        assert ann.prefix == "idempotent"

    def test_custom(self):
        ann = Idempotent(key="#request_id", expire=60)
        assert ann.key == "#request_id"
        assert ann.expire == 60


class TestAuditLog:
    def test_defaults(self):
        ann = AuditLog()
        assert ann.action == ""
        assert ann.level == "INFO"

    def test_custom(self):
        ann = AuditLog(action="create", target="item", level="WARN")
        assert ann.action == "create"
        assert ann.target == "item"
        assert ann.level == "WARN"


class TestFeatureToggle:
    def test_with_default_true(self):
        ann = FeatureToggle("new-items", default=True)
        assert ann.name == "new-items"
        assert ann.default is True

    def test_default_false(self):
        ann = FeatureToggle("feat")
        assert ann.default is False


class TestLock:
    def test_defaults(self):
        ann = Lock()
        assert ann.expire == 10
        assert ann.wait_timeout == 5
        assert ann.prefix == "lock"

    def test_custom(self):
        ann = Lock(key="#item_id", expire=8, wait_timeout=2)
        assert ann.key == "#item_id"
        assert ann.expire == 8
        assert ann.wait_timeout == 2


class TestMetrics:
    def test_with_tags(self):
        ann = Metrics(name="items.created", tags=["region"])
        assert ann.name == "items.created"
        assert ann.tags == ["region"]

    def test_default_tags_empty(self):
        ann = Metrics(name="x")
        assert ann.tags == []


class TestSynchronized:
    def test_with_lock_name(self):
        ann = Synchronized("items-lock")
        assert ann.lock_name == "items-lock"

    def test_default_none(self):
        ann = Synchronized()
        assert ann.lock_name is None


class TestValidate:
    def test_with_field(self):
        ann = Validate(field="name", min_length=2, max_length=30)
        assert ann.field == "name"
        assert ann.min_length == 2
        assert ann.max_length == 30

    def test_with_range(self):
        ann = Validate(field="age", min=0, max=120)
        assert ann.min == 0
        assert ann.max == 120


class TestTrace:
    def test_defaults(self):
        ann = Trace()
        assert ann.trace_id_key == "X-Trace-ID"
        assert ann.span_name is None

    def test_custom(self):
        ann = Trace(trace_id_key="X-Request-ID", span_name="items")
        assert ann.trace_id_key == "X-Request-ID"
        assert ann.span_name == "items"


class TestLogExecutionTime:
    def test_sync_preserves_return_value(self):
        @LogExecutionTime("info")
        def sync(value):
            return value + 1

        assert sync(1) == 2

    def test_sync_preserves_function_name(self):
        @LogExecutionTime("info")
        def sync(value):
            return value + 1

        assert sync.__name__ == "sync"

    def test_async_preserves_return_value(self):
        @LogExecutionTime("info")
        async def asynchronous(value):
            return value + 2

        assert asyncio.run(asynchronous(2)) == 4

    def test_async_preserves_function_name(self):
        @LogExecutionTime("info")
        async def asynchronous(value):
            return value + 2

        assert asynchronous.__name__ == "asynchronous"

    def test_default_log_level(self):
        ann = LogExecutionTime()
        assert ann.log_level == "info"


class TestTransactional:
    def test_defaults(self):
        ann = Transactional()
        assert ann.propagation == "REQUIRED"
        assert ann.rollback_for == []
        assert ann.no_rollback_for == []

    def test_custom(self):
        ann = Transactional(
            propagation="REQUIRES_NEW",
            rollback_for=[ValueError],
            no_rollback_for=[KeyError],
        )
        assert ann.propagation == "REQUIRES_NEW"
        assert ann.rollback_for == [ValueError]
        assert ann.no_rollback_for == [KeyError]


class TestCacheable:
    def test_with_key_and_condition(self):
        ann = Cacheable("items", key="#id", condition="id > 0")
        assert ann.value == "items"
        assert ann.key == "#id"
        assert ann.condition == "id > 0"

    def test_value_only(self):
        ann = Cacheable("items")
        assert ann.value == "items"
        assert ann.key is None


class TestRetryable:
    def test_defaults(self):
        ann = Retryable()
        assert ann.max_retries == 3
        assert ann.value == (Exception,)

    def test_with_value_tuple(self):
        ann = Retryable(value=(ValueError,), max_retries=2)
        assert ann.value == (ValueError,)
        assert ann.max_retries == 2

    def test_max_retries_zero_raises(self):
        with pytest.raises(ValueError):
            Retryable(max_retries=0)

    def test_max_retries_ne_max_attempts_raises(self):
        with pytest.raises(ValueError):
            Retryable(max_retries=2, max_attempts=3)

    def test_max_attempts_sets_max_retries(self):
        ann = Retryable(max_retries=3, max_attempts=3)
        assert ann.max_retries == 3

    def test_with_backoff_object(self):
        backoff = Backoff(delay=100, max_delay=5000, multiplier=2.0, random_factor=0.1)
        ann = Retryable(max_retries=3, backoff=backoff)
        assert ann.backoff is backoff

    def test_numeric_backoff_converted_to_object(self):
        ann = Retryable(max_retries=2, backoff=500)
        assert isinstance(ann.backoff, Backoff)
        assert ann.backoff.delay == 500

    def test_negative_backoff_raises(self):
        with pytest.raises(ValueError):
            Retryable(max_retries=2, backoff=-1)

    def test_exclude(self):
        ann = Retryable(max_retries=2, exclude=(KeyError,))
        assert ann.exclude == (KeyError,)


class TestAsync:
    def test_default(self):
        ann = Async()
        assert ann._annotation_type == "aop"

    def test_decorates(self):
        @Async()
        def task():
            pass

        anns = get_spring_annotations(task)
        assert len(anns) == 1
        assert isinstance(anns[0], Async)


class TestScheduled:
    def test_fixed_rate(self):
        ann = Scheduled(fixed_rate=1000, initial_delay=5)
        assert ann.fixed_rate == 1000
        assert ann.initial_delay == 5
        assert ann.fixed_delay is None
        assert ann.cron is None

    def test_fixed_delay(self):
        ann = Scheduled(fixed_delay=2000)
        assert ann.fixed_delay == 2000
        assert ann.fixed_rate is None

    def test_cron(self):
        ann = Scheduled(cron="0 * * * *")
        assert ann.cron == "0 * * * *"

    def test_fixed_rate_and_delay_raises(self):
        with pytest.raises(ValueError):
            Scheduled(fixed_rate=1000, fixed_delay=2000)

    def test_fixed_rate_zero_raises(self):
        with pytest.raises(ValueError):
            Scheduled(fixed_rate=0)

    def test_fixed_delay_zero_raises(self):
        with pytest.raises(ValueError):
            Scheduled(fixed_delay=0)

    def test_no_config_raises(self):
        with pytest.raises(ValueError):
            Scheduled()

    def test_initial_delay_negative_raises(self):
        with pytest.raises(ValueError):
            Scheduled(fixed_rate=1000, initial_delay=-1)


class TestAsyncResult:
    def test_with_value(self):
        ann = AsyncResult("done")
        assert ann.value == "done"

    def test_default_none(self):
        ann = AsyncResult()
        assert ann.value is None


class TestBackoff:
    def test_defaults(self):
        b = Backoff()
        assert b.delay == 1000
        assert b.max_delay == 10000
        assert b.multiplier == 2.0
        assert b.random_factor == 0.1

    def test_custom(self):
        b = Backoff(delay=100, max_delay=5000, multiplier=2.0, random_factor=0.1)
        assert b.delay == 100
        assert b.max_delay == 5000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
