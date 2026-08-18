"""Tests for springbootai.retry module (Retryable, Backoff, retry decorator, recovery)."""
import time
import pytest
from unittest.mock import MagicMock, patch

from springbootai.retry.retry_annotations import Retryable as StandaloneRetryable, Backoff
from springbootai.retry import retryable_decorator, Recover
from springbootai.retry.recovery import (
    RecoveryMethod,
    resolve_recovery_method,
    invoke_recovery,
)


class TestBackoff:
    """Tests for Backoff configuration class."""

    def test_default_values(self):
        """Backoff should have sensible defaults."""
        b = Backoff()
        assert b.delay == 1000
        assert b.max_delay == 10000
        assert b.multiplier == 2.0
        assert b.random_factor == 0.1

    def test_custom_values(self):
        """Backoff should accept custom configuration."""
        b = Backoff(delay=500, max_delay=5000, multiplier=1.5, random_factor=0.2)
        assert b.delay == 500
        assert b.max_delay == 5000
        assert b.multiplier == 1.5
        assert b.random_factor == 0.2


class TestRetryableAnnotation:
    """Tests for Retryable annotation validation (standalone version)."""

    def test_default_values(self):
        """Retryable should have sensible defaults."""
        r = StandaloneRetryable()
        assert r.value == (Exception,)
        assert r.max_retries == 3
        assert isinstance(r.backoff, Backoff)
        assert r.exclude == ()
        assert r.recover == ""

    def test_max_retries_validation(self):
        """max_retries must be > 0."""
        with pytest.raises(ValueError, match="max_retries 必须大于0"):
            StandaloneRetryable(max_retries=0)
        with pytest.raises(ValueError, match="max_retries 必须大于0"):
            StandaloneRetryable(max_retries=-1)

    def test_max_attempts_alias(self):
        """max_attempts should be an alias for max_retries."""
        r = StandaloneRetryable(max_attempts=5)
        assert r.max_retries == 5

    def test_max_attempts_conflict(self):
        """Setting max_retries (non-default) and max_attempts to different values should raise."""
        with pytest.raises(ValueError, match="不能设置为不同值"):
            StandaloneRetryable(max_retries=4, max_attempts=5)

    def test_numeric_backoff_shorthand(self):
        """A numeric backoff value should create a fixed-delay Backoff."""
        r = StandaloneRetryable(backoff=500)
        assert isinstance(r.backoff, Backoff)
        assert r.backoff.delay == 500
        assert r.backoff.max_delay == 500
        assert r.backoff.multiplier == 1.0
        assert r.backoff.random_factor == 0.0

    def test_numeric_backoff_negative(self):
        """Negative numeric backoff should raise."""
        with pytest.raises(ValueError, match="backoff 延迟不能小于0"):
            StandaloneRetryable(backoff=-100)

    def test_custom_exception_types(self):
        """Should accept specific exception types to retry."""
        r = StandaloneRetryable(value=(ValueError, TypeError))
        assert r.value == (ValueError, TypeError)

    def test_excluded_exceptions(self):
        """Should accept exception types to exclude from retry."""
        r = StandaloneRetryable(exclude=(RuntimeError,))
        assert r.exclude == (RuntimeError,)


class TestRetryableDecorator:
    """Tests for the retryable_decorator behavior on plain functions."""

    def test_successful_call_no_retry(self):
        """A function that succeeds on first try should not retry."""
        call_count = [0]

        annotation = StandaloneRetryable(
            max_retries=3,
            backoff=Backoff(delay=0, random_factor=0),
        )

        @retryable_decorator(annotation)
        def succeed():
            call_count[0] += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count[0] == 1

    def test_retry_then_succeed(self):
        """A function that fails a few times then succeeds should retry."""
        call_count = [0]

        annotation = StandaloneRetryable(
            value=(ValueError,),
            max_retries=4,
            backoff=Backoff(delay=0, random_factor=0),
        )

        @retryable_decorator(annotation)
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient")
            return "success"

        result = flaky()
        assert result == "success"
        assert call_count[0] == 3

    def test_exhausted_retries_raises(self):
        """A function that always fails should raise after max retries."""
        call_count = [0]

        annotation = StandaloneRetryable(
            value=(ValueError,),
            max_retries=3,
            backoff=Backoff(delay=0, random_factor=0),
        )

        @retryable_decorator(annotation)
        def always_fails():
            call_count[0] += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            always_fails()
        assert call_count[0] == 3

    def test_non_matching_exception_not_retried(self):
        """Exceptions not in the retry list should propagate immediately."""
        call_count = [0]

        annotation = StandaloneRetryable(
            value=(ValueError,),
            max_retries=5,
            backoff=Backoff(delay=0, random_factor=0),
        )

        @retryable_decorator(annotation)
        def raise_type_error():
            call_count[0] += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            raise_type_error()
        assert call_count[0] == 1

    def test_excluded_exception_not_retried(self):
        """Exceptions in the exclude list should propagate immediately."""
        call_count = [0]

        annotation = StandaloneRetryable(
            value=(Exception,),
            exclude=(RuntimeError,),
            max_retries=5,
            backoff=Backoff(delay=0, random_factor=0),
        )

        @retryable_decorator(annotation)
        def raise_excluded():
            call_count[0] += 1
            raise RuntimeError("excluded")

        with pytest.raises(RuntimeError, match="excluded"):
            raise_excluded()
        assert call_count[0] == 1

    def test_retry_with_explicit_legacy_recover_name(self):
        """Legacy explicit recover (no @Recover annotation, no exception arg) works standalone."""

        class Service:
            def __init__(self):
                self.fallback_called = False

            @retryable_decorator(
                StandaloneRetryable(
                    value=(ValueError,),
                    max_retries=2,
                    backoff=Backoff(delay=0, random_factor=0),
                    recover="handle_failure",
                )
            )
            def do_work(self):
                raise ValueError("boom")

            # Legacy recover: does NOT receive exception as first arg
            def handle_failure(self):
                self.fallback_called = True
                return "fallback-value"

        svc = Service()
        result = svc.do_work()
        assert result == "fallback-value"
        assert svc.fallback_called is True

    def test_recover_method_via_annotation_standalone(self):
        """@Recover-annotated method on instance is auto-discovered by retryable_decorator."""

        class Service:
            def __init__(self):
                self.recovered = False
                self.recovered_exc = None

            @retryable_decorator(
                StandaloneRetryable(
                    value=(ValueError,),
                    max_retries=2,
                    backoff=Backoff(delay=0, random_factor=0),
                )
            )
            def do_work(self):
                raise ValueError("always fail")

            @Recover
            def _recover_value_error(self, exc: ValueError):
                self.recovered = True
                self.recovered_exc = exc
                return "recovered"

        svc = Service()
        result = svc.do_work()
        assert result == "recovered"
        assert svc.recovered is True
        assert isinstance(svc.recovered_exc, ValueError)

    def test_recover_passes_arguments(self):
        """@Recover method receives exception + original args/kwargs."""

        class Service:
            def __init__(self):
                self.received_args = None
                self.received_kwargs = None

            @retryable_decorator(
                StandaloneRetryable(
                    value=(RuntimeError,),
                    max_retries=2,
                    backoff=Backoff(delay=0, random_factor=0),
                )
            )
            def compute(self, a, b, *, flag=False):
                raise RuntimeError("fail")

            @Recover
            def fallback(self, exc, a, b, *, flag=False):
                self.received_args = (a, b)
                self.received_kwargs = {"flag": flag}
                return a + b

        svc = Service()
        result = svc.compute(2, 3, flag=True)
        assert result == 5
        assert svc.received_args == (2, 3)
        assert svc.received_kwargs == {"flag": True}

    def test_convenient_retry_decorator(self):
        """The @retry() convenience decorator should also work on plain functions."""
        from springbootai.retry.retry_decorator import retry

        call_count = [0]

        @retry(max_retries=3, delay=0, exceptions=(ValueError,))
        def flaky():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError()
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count[0] == 2


class TestCalculateBackoff:
    """Tests for the backoff calculation logic."""

    def test_fixed_delay(self):
        """multiplier=1 should produce fixed delay."""
        from springbootai.retry.retry_decorator import _calculate_backoff

        b = Backoff(delay=100, multiplier=1.0, max_delay=10000, random_factor=0.0)
        assert _calculate_backoff(b, 1) == 100
        assert _calculate_backoff(b, 2) == 100
        assert _calculate_backoff(b, 5) == 100

    def test_exponential_backoff(self):
        """multiplier=2 should double the delay each attempt."""
        from springbootai.retry.retry_decorator import _calculate_backoff

        b = Backoff(delay=100, multiplier=2.0, max_delay=10000, random_factor=0.0)
        assert _calculate_backoff(b, 1) == 100
        assert _calculate_backoff(b, 2) == 200
        assert _calculate_backoff(b, 3) == 400
        assert _calculate_backoff(b, 4) == 800

    def test_max_delay_cap(self):
        """Delay should never exceed max_delay."""
        from springbootai.retry.retry_decorator import _calculate_backoff

        b = Backoff(delay=100, multiplier=2.0, max_delay=500, random_factor=0.0)
        assert _calculate_backoff(b, 1) == 100
        assert _calculate_backoff(b, 2) == 200
        assert _calculate_backoff(b, 3) == 400
        assert _calculate_backoff(b, 4) == 500
        assert _calculate_backoff(b, 10) == 500

    def test_random_factor_bounds(self):
        """With random_factor > 0, delay should be within the expected range."""
        from springbootai.retry.retry_decorator import _calculate_backoff

        b = Backoff(delay=1000, multiplier=1.0, max_delay=10000, random_factor=0.5)
        results = [_calculate_backoff(b, 1) for _ in range(50)]
        for d in results:
            assert 500 <= d <= 1500


class TestRecoveryModule:
    """Direct unit tests for recovery.resolve_recovery_method and invoke_recovery."""

    def test_resolve_recovery_explicit_name_legacy(self):
        """Explicit legacy recover name (no @Recover, receives_exception=False).

        The legacy explicit-name path sets receives_exception based on whether
        the method itself is annotated with @Recover, so we need the method
        signature to match the original call args (no exception prepended).
        """

        class S:
            def my_fallback(self):
                return "fb"

        s = S()
        ann = MagicMock()
        ann.recover = "my_fallback"

        rec = resolve_recovery_method(s, ann, ValueError("x"), (), {})
        assert rec is not None
        assert rec.method.__name__ == "my_fallback"
        assert rec.receives_exception is False

    def test_resolve_recovery_explicit_name_not_found(self):
        """Should raise AttributeError if explicit recover method does not exist."""

        class S:
            pass

        s = S()
        ann = MagicMock()
        ann.recover = "does_not_exist"

        with pytest.raises(AttributeError):
            resolve_recovery_method(s, ann, ValueError("x"), (), {})

    def test_resolve_recovery_picks_most_specific(self):
        """Should pick the @Recover method matching the most specific exception type."""

        class Service:
            @Recover
            def handle_generic(self, exc: Exception):
                return "generic"

            @Recover
            def handle_value_error(self, exc: ValueError):
                return "value_error"

        s = Service()
        ann = MagicMock()
        ann.recover = ""

        rec = resolve_recovery_method(s, ann, ValueError("x"), (), {})
        assert rec is not None
        assert rec.method.__name__ == "handle_value_error"

    def test_resolve_recovery_ambiguous_raises(self):
        """Two @Recover methods with same specificity should raise ValueError."""

        class Service:
            @Recover
            def handle_one(self, exc: ValueError):
                return "one"

            @Recover
            def handle_two(self, exc: ValueError):
                return "two"

        s = Service()
        ann = MagicMock()
        ann.recover = ""

        with pytest.raises(ValueError, match="Ambiguous"):
            resolve_recovery_method(s, ann, ValueError("x"), (), {})

    def test_resolve_recovery_returns_none_when_no_match(self):
        """Should return None when no @Recover method matches the exception type."""

        class Service:
            @Recover
            def handle_type_error(self, exc: TypeError):
                return "type"

        s = Service()
        ann = MagicMock()
        ann.recover = ""

        rec = resolve_recovery_method(s, ann, ValueError("x"), (), {})
        assert rec is None

    def test_invoke_recovery_passes_args(self):
        """invoke_recovery should call the method with exception + args + kwargs."""
        captured = {}

        def my_method(exc, a, b, *, key=None):
            captured["exc"] = exc
            captured["args"] = (a, b)
            captured["kwargs"] = {"key": key}
            return "done"

        rm = RecoveryMethod(
            method=my_method,
            exception_types=(ValueError,),
            receives_exception=True,
        )
        exc = ValueError("test")
        result = invoke_recovery(rm, exc, (1, 2), {"key": "v"})
        assert result == "done"
        assert captured["exc"] is exc
        assert captured["args"] == (1, 2)
        assert captured["kwargs"] == {"key": "v"}
