"""Tests for springbootai.core module (typing_utils, graceful_shutdown)."""
import typing
import time
import threading
import pytest
from unittest.mock import MagicMock, patch

from springbootai.core.typing_utils import unwrap_optional_type
from springbootai.core.graceful_shutdown import (
    GracefulShutdown,
    ShutdownPhase,
    shutdown_handler,
)


class TestUnwrapOptionalType:
    """Tests for unwrap_optional_type utility."""

    def test_unwrap_optional_int(self):
        """Optional[int] should unwrap to int."""
        assert unwrap_optional_type(typing.Optional[int]) is int

    def test_unwrap_optional_str(self):
        """Optional[str] should unwrap to str."""
        assert unwrap_optional_type(typing.Optional[str]) is str

    def test_non_optional_unchanged(self):
        """Non-Optional types should be returned as-is."""
        assert unwrap_optional_type(int) is int
        assert unwrap_optional_type(str) is str
        assert unwrap_optional_type(float) is float

    def test_none_unchanged(self):
        """None should be returned as-is."""
        assert unwrap_optional_type(None) is None

    def test_multi_element_union_unchanged(self):
        """Union[int, str, None] should NOT be unwrapped (multiple non-None types)."""
        tp = typing.Union[int, str, None]
        result = unwrap_optional_type(tp)
        assert result is tp

    def test_direct_union_with_none(self):
        """Union[int, None] should unwrap to int."""
        assert unwrap_optional_type(typing.Union[int, None]) is int

    def test_union_without_none_unchanged(self):
        """Union[int, str] (without None) should be returned as-is."""
        tp = typing.Union[int, str]
        result = unwrap_optional_type(tp)
        assert result is tp


class TestGracefulShutdown:
    """Tests for GracefulShutdown manager."""

    def test_initial_state(self):
        """New shutdown handler should be in RUNNING phase."""
        gs = GracefulShutdown()
        assert gs.phase == ShutdownPhase.RUNNING
        assert not gs.is_draining
        assert not gs.is_shutting_down
        assert gs.inflight_count == 0

    def test_normalize_timeout_valid(self):
        """Valid timeout values should be accepted."""
        gs = GracefulShutdown()
        assert gs._normalize_timeout(10, 30) == 10.0
        assert gs._normalize_timeout(0, 30) == 0.0
        assert gs._normalize_timeout(3.14, 30) == 3.14

    def test_normalize_timeout_invalid(self):
        """Invalid timeout values should fall back to default."""
        gs = GracefulShutdown()
        assert gs._normalize_timeout(-1, 30) == 30.0
        assert gs._normalize_timeout(float('inf'), 30) == 30.0
        assert gs._normalize_timeout(float('nan'), 30) == 30.0
        assert gs._normalize_timeout("not_a_number", 30) == 30.0
        assert gs._normalize_timeout(None, 30) == 30.0

    def test_normalize_timeout_dict(self):
        """Dict timeout config with 'value' or 'timeout' key should be extracted."""
        gs = GracefulShutdown()
        assert gs._normalize_timeout({"value": 15}, 30) == 15.0
        assert gs._normalize_timeout({"timeout": 20}, 30) == 20.0

    def test_request_started_finished(self):
        """request_started/request_finished should track in-flight count."""
        gs = GracefulShutdown()
        assert gs.inflight_count == 0

        assert gs.request_started() is True
        assert gs.inflight_count == 1

        assert gs.request_started() is True
        assert gs.inflight_count == 2

        assert gs.request_finished() is True
        assert gs.inflight_count == 1

        assert gs.request_finished() is True
        assert gs.inflight_count == 0

    def test_request_finished_underflow_protection(self):
        """Calling request_finished when no requests are in-flight should not go negative."""
        gs = GracefulShutdown()
        assert gs.request_finished() is False
        assert gs.inflight_count == 0

    def test_request_started_rejected_when_draining(self):
        """New requests should be rejected once draining starts."""
        gs = GracefulShutdown()
        gs.initiate_shutdown()
        assert gs.request_started() is False

    def test_register_and_run_hook(self):
        """Registered shutdown hooks should execute during shutdown."""
        gs = GracefulShutdown(drain_timeout=0.1, shutdown_timeout=1.0)
        hook_called = threading.Event()

        def my_hook():
            hook_called.set()

        gs.register_hook("test_hook", my_hook)
        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=2.0)
        assert hook_called.is_set()
        assert gs.phase == ShutdownPhase.STOPPED

    def test_hooks_executed_in_order(self):
        """Hooks should execute in ascending 'order' value."""
        gs = GracefulShutdown(drain_timeout=0.1, shutdown_timeout=1.0)
        call_order = []
        lock = threading.Lock()

        def make_hook(name):
            def hook():
                with lock:
                    call_order.append(name)
                time.sleep(0.02)
            return hook

        gs.register_hook("third", make_hook("third"), order=30)
        gs.register_hook("first", make_hook("first"), order=10)
        gs.register_hook("second", make_hook("second"), order=20)

        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=3.0)
        assert call_order == ["first", "second", "third"]

    def test_in_flight_waited_during_drain(self):
        """Shutdown should wait for in-flight requests during drain phase."""
        gs = GracefulShutdown(drain_timeout=2.0, shutdown_timeout=1.0)
        request_finished_event = threading.Event()
        hook_started = threading.Event()

        # Mark one request as in-flight
        gs.request_started()

        def finish_request_soon():
            time.sleep(0.2)
            gs.request_finished()
            request_finished_event.set()

        finisher = threading.Thread(target=finish_request_soon, daemon=True)
        finisher.start()

        def hook():
            hook_started.set()

        gs.register_hook("hook", hook)
        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=3.0)

        assert request_finished_event.is_set()
        assert hook_started.is_set()
        assert gs.phase == ShutdownPhase.STOPPED

    def test_drain_timeout_exceeded(self):
        """Shutdown should proceed if drain timeout is exceeded with in-flight requests."""
        gs = GracefulShutdown(drain_timeout=0.1, shutdown_timeout=0.5)
        hook_called = threading.Event()

        gs.request_started()  # Request that never finishes

        def hook():
            hook_called.set()

        gs.register_hook("hook", hook)
        start = time.monotonic()
        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=2.0)
        elapsed = time.monotonic() - start

        assert hook_called.is_set()
        assert gs.phase == ShutdownPhase.STOPPED
        assert elapsed < 2.0  # Should not hang forever

    def test_initiate_shutdown_idempotent(self):
        """Calling initiate_shutdown twice should have no effect the second time."""
        gs = GracefulShutdown(drain_timeout=0.05, shutdown_timeout=0.1)
        hook_call_count = [0]

        def hook():
            hook_call_count[0] += 1

        gs.register_hook("hook", hook)
        assert gs.initiate_shutdown() is True
        gs.wait_for_shutdown(timeout=2.0)
        assert gs.initiate_shutdown() is False
        assert hook_call_count[0] == 1

    def test_failing_hook_does_not_break_shutdown(self):
        """A hook that raises an exception should not prevent shutdown from completing."""
        gs = GracefulShutdown(drain_timeout=0.05, shutdown_timeout=1.0)
        good_hook_called = threading.Event()

        def bad_hook():
            raise RuntimeError("hook exploded")

        def good_hook():
            good_hook_called.set()

        gs.register_hook("bad", bad_hook, order=10)
        gs.register_hook("good", good_hook, order=20)

        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=2.0)
        assert good_hook_called.is_set()
        assert gs.phase == ShutdownPhase.STOPPED

    def test_wait_for_shutdown_timeout(self):
        """wait_for_shutdown should return False if timeout expires before completion."""
        gs = GracefulShutdown(drain_timeout=5.0, shutdown_timeout=5.0)
        gs.request_started()  # Block shutdown

        # Run shutdown in background
        thread = threading.Thread(target=gs.initiate_shutdown, daemon=True)
        thread.start()

        # Wait a short time - shutdown should still be waiting for in-flight
        result = gs.wait_for_shutdown(timeout=0.1)
        assert result is False
        assert gs.phase != ShutdownPhase.STOPPED

        # Unblock and finish
        gs.request_finished()
        gs.wait_for_shutdown(timeout=3.0)
        assert gs.phase == ShutdownPhase.STOPPED

    def test_properties(self):
        """Test is_draining and is_shutting_down properties across phases."""
        gs = GracefulShutdown(drain_timeout=0.05, shutdown_timeout=0.1)
        assert gs.phase == ShutdownPhase.RUNNING
        assert not gs.is_draining
        assert not gs.is_shutting_down

        gs.initiate_shutdown()
        gs.wait_for_shutdown(timeout=2.0)
        assert gs.phase == ShutdownPhase.STOPPED
        assert gs.is_draining
        assert gs.is_shutting_down
