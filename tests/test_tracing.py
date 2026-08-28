"""Tests for springbootai.tracing module (LocalSpan fallback when SkyWalking is unavailable)."""
import time

from springbootai.tracing.skywalking import (
    SkyWalkingTracer,
    LocalSpan,
    skywalking_tracer,
    init_skywalking,
)


class TestLocalSpan:
    """Tests for LocalSpan (fallback when SkyWalking agent not installed)."""

    def test_local_span_creation(self):
        """LocalSpan should be constructible and set attributes."""
        span = LocalSpan("test-op", "Local")
        assert span.operation_name == "test-op"
        assert span.span_type == "Local"
        assert span.peer == ""
        assert span.end_time is None
        assert len(span.trace_id) > 0

    def test_local_span_with_peer(self):
        """LocalSpan should accept peer parameter."""
        span = LocalSpan("http-call", "Remote", peer="example.com:8080")
        assert span.peer == "example.com:8080"

    def test_local_span_tag_with_object(self):
        """tag() should accept objects with key/val attributes."""

        class Tag:
            def __init__(self, k, v):
                self.key = k
                self.val = v

        span = LocalSpan("tag-test", "Local")
        span.tag(Tag("http.method", "GET"))
        assert span.tags["http.method"] == "GET"

    def test_local_span_tag_with_tuple(self):
        """tag() should accept (key, val) tuples."""
        span = LocalSpan("tag-tuple", "Local")
        span.tag(("status_code", 200))
        assert span.tags["status_code"] == 200

    def test_local_span_finish(self):
        """finish() should set end_time."""
        span = LocalSpan("finish-test", "Local")
        time.sleep(0.02)
        assert span.end_time is None
        span.finish()
        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_local_span_context_manager(self):
        """LocalSpan should work as a context manager."""
        with LocalSpan("ctx-mgr", "Local") as span:
            assert span.end_time is None
        # After __exit__, end_time should be set
        assert span.end_time is not None


class TestSkyWalkingTracer:
    """Tests for SkyWalkingTracer (in fallback mode, since agent likely not installed)."""

    def test_singleton_behavior(self):
        """SkyWalkingTracer should be a singleton via __new__."""
        t1 = SkyWalkingTracer(service_name="svc-a")
        t2 = SkyWalkingTracer(service_name="svc-b")
        # Same instance; __init__ should not re-initialize after first call
        assert t1 is t2

    def test_default_service_name(self):
        """Default tracer should have the expected service name."""
        # The module-level singleton uses defaults
        assert skywalking_tracer.service_name == "spring-python-app"

    def test_create_local_span_fallback(self):
        """create_span should return LocalSpan in fallback mode."""
        # Re-instantiate to get a clean tracer for testing init args
        # (note: singleton pattern means we test the module-level instance behavior)
        span = skywalking_tracer.create_span("my-op", "Local")
        assert isinstance(span, LocalSpan)
        assert span.operation_name == "my-op"
        span.finish()

    def test_create_exit_span_fallback(self):
        """create_exit_span should return LocalSpan in fallback mode."""
        span = skywalking_tracer.create_exit_span("call-remote", "remote-svc:9090")
        assert isinstance(span, LocalSpan)
        assert span.operation_name == "call-remote"
        assert span.span_type == "Remote"
        assert span.peer == "remote-svc:9090"
        span.finish()

    def test_trace_id_roundtrip(self):
        """set_trace_id / get_trace_id should roundtrip in fallback mode."""
        skywalking_tracer.set_trace_id("abc-123")
        assert skywalking_tracer.get_trace_id() == "abc-123"

    def test_inject_carrier_fallback(self):
        """inject_carrier should return headers dict unchanged (no SkyWalking to inject)."""
        headers = {"X-Custom": "value"}
        result = skywalking_tracer.inject_carrier(dict(headers))
        assert result == headers

    def test_extract_carrier_fallback(self):
        """extract_carrier should not raise even when SkyWalking is not installed."""
        # Should not raise
        skywalking_tracer.extract_carrier({"sw-header": "dummy"})

    def test_init_skywalking_is_safe_to_call(self):
        """Explicit initialization must apply config to the singleton."""
        init_skywalking({"service_name": "new-svc", "collector_address": "col:11800"})
        assert skywalking_tracer.service_name == "new-svc"
        assert skywalking_tracer.collector_address == "col:11800"

    def test_local_span_tag_with_tuple_and_object(self):
        """tag() should accept both object-style and tuple-style tags in one span."""
        span = LocalSpan("multi-tag", "Local")

        class Tag:
            def __init__(self, k, v):
                self.key = k
                self.val = v

        span.tag(Tag("db.type", "mysql"))
        span.tag(("db.statement", "SELECT 1"))
        assert span.tags["db.type"] == "mysql"
        assert span.tags["db.statement"] == "SELECT 1"
        span.finish()
        assert span.end_time is not None
