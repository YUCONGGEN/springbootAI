"""Cloud 内嵌功能完整测试 - 覆盖 Cloud 注解、Sentinel、Tracer、Seata、Gateway、LoadBalancer。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from springbootai.annotations.core import get_spring_annotations
from springbootai.annotations.cloud import (
    EnableDiscoveryClient, NacosValue, RefreshScope, EnableFeignClients,
    FeignClient, SentinelResource, EnableGateway, LoadBalanced,
    GlobalTransactional,
)
from springbootai.cloud.sentinel import (
    sentinel_engine, FlowRule, DegradeRule, BlockException, sentinel_protect,
)
from springbootai.cloud.tracer import (
    Tracer, SpanKind, SpanStatus, trace_span, get_tracer, _parse_traceparent,
)
from springbootai.cloud.seata import seata_manager, BranchStatus
from springbootai.cloud.gateway import GatewayRouter
from springbootai.cloud.load_balancer import LoadBalancer


# ==================== Cloud 注解测试 ====================

class TestEnableDiscoveryClient:
    def test_default_client_type(self):
        ann = EnableDiscoveryClient()
        assert ann.client_type == "nacos"

    def test_custom_client_type(self):
        ann = EnableDiscoveryClient("eureka")
        assert ann.client_type == "eureka"

    def test_attribute_name_is_client_type(self):
        ann = EnableDiscoveryClient("nacos")
        assert hasattr(ann, "client_type")
        assert not hasattr(ann, "value")


class TestNacosValue:
    def test_with_auto_refreshed(self):
        ann = NacosValue("app.name", auto_refreshed=True)
        assert ann.value == "app.name"
        assert ann.auto_refreshed is True

    def test_default_no_refresh(self):
        ann = NacosValue("app.name")
        assert ann.auto_refreshed is False


class TestRefreshScope:
    def test_default(self):
        ann = RefreshScope()
        assert ann._annotation_type == "refresh_scope"

    def test_decorates(self):
        @RefreshScope()
        class S:
            pass

        assert any(isinstance(a, RefreshScope) for a in get_spring_annotations(S))


class TestEnableFeignClients:
    def test_with_packages(self):
        ann = EnableFeignClients(["demo.clients"])
        assert ann.base_packages == ["demo.clients"]

    def test_default_none(self):
        ann = EnableFeignClients()
        assert ann.base_packages is None


class TestFeignClient:
    def test_value_attribute(self):
        ann = FeignClient("inventory", path="/api", url="http://x")
        assert ann.value == "inventory"
        assert ann.path == "/api"
        assert ann.url == "http://x"

    def test_attribute_name_is_value_not_name(self):
        ann = FeignClient("svc")
        assert hasattr(ann, "value")
        assert not hasattr(ann, "name")

    def test_with_fallback(self):
        class FB:
            pass

        ann = FeignClient("svc", fallback=FB)
        assert ann.fallback is FB


class TestSentinelResource:
    def test_with_all_params(self):
        ann = SentinelResource(
            "items", block_handler="blocked", fallback="fallback", hotkey="id",
        )
        assert ann.value == "items"
        assert ann.block_handler == "blocked"
        assert ann.fallback == "fallback"
        assert ann.hotkey == "id"


class TestEnableGateway:
    def test_default(self):
        ann = EnableGateway()
        assert ann._annotation_type == "gateway"

    def test_decorates(self):
        @EnableGateway()
        class G:
            pass

        assert any(isinstance(a, EnableGateway) for a in get_spring_annotations(G))


class TestLoadBalanced:
    def test_strategy_attribute(self):
        ann = LoadBalanced("random")
        assert ann.strategy == "random"

    def test_default_strategy(self):
        ann = LoadBalanced()
        assert ann.strategy == "round_robin"


class TestGlobalTransactional:
    def test_with_params(self):
        ann = GlobalTransactional(
            timeout=5000, name="create-item", rollback_for=[ValueError],
        )
        assert ann.timeout == 5000
        assert ann.name == "create-item"
        assert ann.rollback_for == [ValueError]

    def test_defaults(self):
        ann = GlobalTransactional()
        assert ann.timeout == 60000
        assert ann.name == ""


# ==================== Sentinel 引擎测试 ====================

class TestSentinelEngine:
    def setup_method(self):
        sentinel_engine.reset()

    def teardown_method(self):
        sentinel_engine.reset()

    def test_reset_clears_state(self):
        sentinel_engine.load_flow_rules([FlowRule("r1", count=10.0)])
        sentinel_engine.reset()
        # After reset, no rules → entry should always succeed
        entry = sentinel_engine.entry("r1")
        entry.success()

    def test_load_flow_rules(self):
        rules = [FlowRule("api1", count=100.0), FlowRule("api2", count=50.0)]
        sentinel_engine.load_flow_rules(rules)
        # Verify rules are loaded by checking that entry works
        entry = sentinel_engine.entry("api1")
        entry.success()

    def test_entry_returns_entry_object(self):
        entry = sentinel_engine.entry("test_resource")
        assert hasattr(entry, "success")
        assert hasattr(entry, "error")
        entry.success()

    def test_entry_success_increments_stats(self):
        entry = sentinel_engine.entry("stat_res")
        entry.success()
        stats = sentinel_engine.get_resource_stats("stat_res")
        assert "stat_res" in stats
        assert stats["stat_res"]["stats"]["success_count"] >= 1

    def test_entry_error_increments_exception(self):
        entry = sentinel_engine.entry("err_res")
        entry.error()
        stats = sentinel_engine.get_resource_stats("err_res")
        assert stats["err_res"]["stats"]["exception_count"] >= 1

    def test_flow_rule_blocks_after_threshold(self):
        sentinel_engine.load_flow_rules([FlowRule("limited", count=5.0)])
        # 5 entries should succeed (pass_qps goes 0,1,2,3,4 — all < 5)
        for _ in range(5):
            e = sentinel_engine.entry("limited")
            e.success()
        # 6th entry: pass_qps=5.0 >= 5.0 → blocked
        with pytest.raises(BlockException):
            sentinel_engine.entry("limited")

    def test_get_resource_stats_returns_dict(self):
        entry = sentinel_engine.entry("stats_check")
        entry.success()
        stats = sentinel_engine.get_resource_stats("stats_check")
        assert isinstance(stats, dict)
        assert "stats_check" in stats

    def test_get_all_stats(self):
        e1 = sentinel_engine.entry("r_a")
        e1.success()
        e2 = sentinel_engine.entry("r_b")
        e2.success()
        all_stats = sentinel_engine.get_resource_stats()
        assert isinstance(all_stats, dict)
        assert "r_a" in all_stats
        assert "r_b" in all_stats


class TestFlowRule:
    def test_attributes(self):
        rule = FlowRule("res", count=100.0)
        assert rule.resource == "res"
        assert rule.count == 100.0
        assert rule.grade == "QPS"

    def test_defaults(self):
        rule = FlowRule("r")
        assert rule.strategy == "DIRECT"
        assert rule.control_behavior == "REJECT"


class TestDegradeRule:
    def test_attributes(self):
        rule = DegradeRule("res", count=0.5, time_window_sec=10)
        assert rule.resource == "res"
        assert rule.count == 0.5
        assert rule.time_window_sec == 10

    def test_defaults(self):
        rule = DegradeRule("r")
        assert rule.grade == "EXCEPTION_RATIO"
        assert rule.min_request_amount == 5


class TestBlockException:
    def test_has_resource_and_rule_type(self):
        exc = BlockException("res", "FLOW", "QPS exceeded")
        assert exc.resource == "res"
        assert exc.rule_type == "FLOW"
        assert "FLOW" in str(exc)


class TestSentinelProtect:
    def setup_method(self):
        sentinel_engine.reset()

    def teardown_method(self):
        sentinel_engine.reset()

    def test_success_path(self):
        @sentinel_protect("protect_ok")
        def handler():
            return "ok"

        assert handler() == "ok"

    def test_fallback_on_block(self):
        sentinel_engine.load_flow_rules([FlowRule("protect_fb", count=1.0)])
        # First call succeeds
        @sentinel_protect("protect_fb", fallback=lambda: "fallback")
        def handler():
            return "ok"

        # First call: pass_qps=0 < 1 → success
        assert handler() == "ok"
        # Second call: pass_qps=1.0 >= 1.0 → blocked → fallback
        assert handler() == "fallback"

    def test_block_handler_on_block(self):
        sentinel_engine.load_flow_rules([FlowRule("protect_bh", count=1.0)])

        @sentinel_protect("protect_bh", block_handler=lambda: "blocked_handler")
        def handler():
            return "ok"

        assert handler() == "ok"
        assert handler() == "blocked_handler"


# ==================== Tracer 测试 ====================

class TestTracer:
    def test_creation(self):
        tracer = Tracer("svc-name")
        assert tracer.service_name == "svc-name"
        assert tracer.enabled is True

    def test_span_context_manager(self):
        tracer = Tracer("svc")
        with tracer.span("op", SpanKind.SERVER) as span:
            assert span.name == "op"
            assert span.kind == SpanKind.SERVER

    def test_span_trace_id_is_32_chars(self):
        tracer = Tracer("svc")
        with tracer.span("op") as span:
            assert len(span.trace_id) == 32

    def test_span_id_is_16_chars(self):
        tracer = Tracer("svc")
        with tracer.span("op") as span:
            assert len(span.span_id) == 16

    def test_span_parent_span_id_none_for_root(self):
        tracer = Tracer("svc")
        with tracer.span("root") as span:
            assert span.parent_span_id is None

    def test_span_status_defaults_unset(self):
        tracer = Tracer("svc")
        with tracer.span("op") as span:
            pass
        # After span ends, status should be OK (auto-set on end)
        assert span.status == SpanStatus.OK

    def test_span_attributes(self):
        tracer = Tracer("svc")
        with tracer.span("op") as span:
            span.set_attribute("http.method", "GET")
            assert span.attributes["http.method"] == "GET"

    def test_span_duration_ms_positive(self):
        tracer = Tracer("svc")
        with tracer.span("op") as span:
            pass
        assert span.duration_ms >= 0

    def test_span_record_exception_sets_error(self):
        tracer = Tracer("svc")
        with pytest.raises(ValueError):
            with tracer.span("op") as span:
                raise ValueError("test error")
        assert span.status == SpanStatus.ERROR

    def test_child_span_inherits_trace_id(self):
        tracer = Tracer("svc")
        with tracer.span("parent") as parent:
            with tracer.span("child") as child:
                assert child.trace_id == parent.trace_id
                assert child.parent_span_id == parent.span_id

    def test_extracts_b3_context_case_insensitively(self):
        tracer = Tracer("svc", export_to_log=False)
        trace_id = "a" * 32
        span_id = "b" * 16
        header = tracer.extract_from_headers({
            "x-b3-traceid": trace_id,
            "x-b3-spanid": span_id,
            "x-b3-sampled": "1",
        })

        with tracer.span("server", traceparent=header) as child:
            assert child.trace_id == trace_id
            assert child.parent_span_id == span_id


class TestParseTraceparent:
    def test_valid(self):
        header = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
        result = _parse_traceparent(header)
        assert result is not None
        trace_id, span_id, flags = result
        assert trace_id == "a" * 32
        assert span_id == "b" * 16
        assert flags == "01"

    def test_invalid_short(self):
        assert _parse_traceparent("invalid") is None

    def test_invalid_trace_id_length(self):
        header = "00-short-" + "b" * 16 + "-01"
        assert _parse_traceparent(header) is None

    def test_empty_string(self):
        assert _parse_traceparent("") is None


class TestGetTracer:
    def test_returns_same_instance(self):
        t1 = get_tracer("svc1")
        t2 = get_tracer("svc2")
        assert t1 is t2


class TestTraceSpan:
    def test_preserves_return_value(self):
        @trace_span("my-op")
        def fn(x):
            return x + 1

        assert fn(5) == 6

    def test_preserves_function_name(self):
        @trace_span("my-op")
        def my_func():
            return "ok"

        assert my_func.__name__ == "my_func"

    def test_default_span_name(self):
        @trace_span()
        def named_func():
            return "ok"

        # Should not raise and should use function qualname as span name
        assert named_func() == "ok"

    def test_async_function_span_covers_awaited_work(self, monkeypatch):
        import asyncio
        import springbootai.cloud.tracer as tracer_module

        tracer = Tracer("async-svc", export_to_log=False)
        monkeypatch.setattr(tracer_module, "_tracer_instance", tracer)

        @trace_span("async-op")
        async def async_op():
            await asyncio.sleep(0.02)
            return tracer.get_current_span()

        active_span = asyncio.run(async_op())
        spans = tracer.get_spans()
        assert active_span is spans[0]
        assert spans[0].duration_ms >= 15
        assert tracer.get_current_span() is None


# ==================== Seata 测试 ====================

class TestSeataManager:
    def setup_method(self):
        # Ensure clean state: rollback any pending transaction
        if seata_manager.is_in_transaction():
            tx_id = seata_manager.get_current_tx_id()
            if tx_id:
                try:
                    seata_manager.rollback_transaction(tx_id)
                except Exception:
                    pass

    def teardown_method(self):
        if seata_manager.is_in_transaction():
            tx_id = seata_manager.get_current_tx_id()
            if tx_id:
                try:
                    seata_manager.rollback_transaction(tx_id)
                except Exception:
                    pass

    def test_set_mode_local(self):
        seata_manager.set_mode("local")
        assert seata_manager.get_mode() == "local"

    def test_set_mode_http(self):
        seata_manager.set_mode("http")
        assert seata_manager.get_mode() == "http"
        # Reset to local for other tests
        seata_manager.set_mode("local")

    def test_set_mode_invalid_raises(self):
        with pytest.raises(ValueError):
            seata_manager.set_mode("invalid")

    def test_begin_transaction_returns_32_char_xid(self):
        seata_manager.set_mode("local")
        xid = seata_manager.begin_transaction(name="tx")
        assert len(xid) == 32
        seata_manager.commit_transaction(xid)

    def test_is_in_transaction(self):
        seata_manager.set_mode("local")
        assert seata_manager.is_in_transaction() is False
        xid = seata_manager.begin_transaction(name="tx")
        assert seata_manager.is_in_transaction() is True
        seata_manager.commit_transaction(xid)
        assert seata_manager.is_in_transaction() is False

    def test_nested_transaction_returns_same_xid(self):
        seata_manager.set_mode("local")
        xid1 = seata_manager.begin_transaction(name="outer")
        xid2 = seata_manager.begin_transaction(name="inner")
        assert xid1 == xid2
        seata_manager.commit_transaction(xid1)


class TestSeataBranch:
    def setup_method(self):
        seata_manager.set_mode("http")
        if seata_manager.is_in_transaction():
            tx_id = seata_manager.get_current_tx_id()
            if tx_id:
                try:
                    seata_manager.rollback_transaction(tx_id)
                except Exception:
                    pass

    def teardown_method(self):
        if seata_manager.is_in_transaction():
            tx_id = seata_manager.get_current_tx_id()
            if tx_id:
                try:
                    seata_manager.rollback_transaction(tx_id)
                except Exception:
                    pass
        seata_manager.set_mode("local")

    def test_register_branch_and_commit(self):
        xid = seata_manager.begin_transaction(name="tx")
        committed = []
        rolled_back = []

        def commit_cb(x, b):
            committed.append((x, b))

        def rollback_cb(x, b):
            rolled_back.append((x, b))

        branch_id = seata_manager.register_branch(
            xid, resource_id="db", commit_cb=commit_cb, rollback_cb=rollback_cb,
        )
        assert isinstance(branch_id, str)
        assert seata_manager.commit_transaction(xid) is True
        assert len(committed) == 1

    def test_register_branch_and_rollback(self):
        xid = seata_manager.begin_transaction(name="tx")
        committed = []
        rolled_back = []

        def commit_cb(x, b):
            committed.append((x, b))

        def rollback_cb(x, b):
            rolled_back.append((x, b))

        seata_manager.register_branch(
            xid, resource_id="db", commit_cb=commit_cb, rollback_cb=rollback_cb,
        )
        assert seata_manager.rollback_transaction(xid) is True
        assert len(rolled_back) == 1


class TestSeataHeaders:
    def test_inject_and_extract_xid(self):
        headers = {}
        xid = "test_xid_12345"
        seata_manager.inject_xid_headers(headers, xid)
        assert headers["X-TX-XID"] == xid
        assert headers["X-Seata-XID"] == xid

        extracted = seata_manager.get_xid_from_headers(headers)
        assert extracted == xid

    def test_extract_from_empty_headers(self):
        assert seata_manager.get_xid_from_headers({}) == ""

    def test_extract_case_insensitive(self):
        headers = {"x-tx-xid": "lower_xid"}
        assert seata_manager.get_xid_from_headers(headers) == "lower_xid"


class TestBranchStatus:
    def test_constants(self):
        assert BranchStatus.REGISTERED == "REGISTERED"
        assert BranchStatus.COMMITTED == "COMMITTED"
        assert BranchStatus.ROLLED_BACK == "ROLLED_BACK"
        assert BranchStatus.FAILED == "FAILED"


# ==================== Gateway 测试 ====================

class TestGatewayRouter:
    def test_route_with_service_id(self):
        gw = GatewayRouter()
        r = gw.route("/api/users/**", service_id="user-svc")
        assert r.service_id == "user-svc"
        assert r.path == "/api/users/**"

    def test_route_with_uri(self):
        gw = GatewayRouter()
        r = gw.route("/health", uri="http://localhost:8080/health")
        assert r.uri == "http://localhost:8080/health"

    def test_match_route_wildcard(self):
        gw = GatewayRouter()
        gw.route("/api/users/**", service_id="user-svc")
        matched = gw.match_route("/api/users/123")
        assert matched is not None
        assert matched.service_id == "user-svc"

    def test_match_route_exact(self):
        gw = GatewayRouter()
        gw.route("/health", uri="http://x/health")
        matched = gw.match_route("/health")
        assert matched is not None

    def test_match_route_no_match(self):
        gw = GatewayRouter()
        gw.route("/api/users/**", service_id="user-svc")
        assert gw.match_route("/orders/123") is None

    def test_match_route_disabled(self):
        gw = GatewayRouter()
        r = gw.route("/api/**", service_id="x")
        r.enabled = False
        assert gw.match_route("/api/test") is None

    def test_rewrite_path_with_strip_prefix(self):
        gw = GatewayRouter()
        r = gw.route("/api/**", service_id="x", strip_prefix=True)
        rewritten = gw.rewrite_path(r, "/api/users/123")
        assert rewritten == "/users/123"

    def test_rewrite_path_without_strip_prefix(self):
        gw = GatewayRouter()
        r = gw.route("/api/users/**", service_id="x")
        rewritten = gw.rewrite_path(r, "/api/users/123")
        assert rewritten == "/api/users/123"

    def test_rewrite_path_with_prefix(self):
        gw = GatewayRouter()
        r = gw.route("/api/**", service_id="x", prefix="/v2")
        rewritten = gw.rewrite_path(r, "/api/test")
        assert rewritten == "/v2/api/test"

    def test_get_routes(self):
        gw = GatewayRouter()
        gw.route("/a/**", service_id="a")
        gw.route("/b/**", service_id="b")
        routes = gw.get_routes()
        assert len(routes) == 2
        assert all("id" in r for r in routes)

    def test_add_filter(self):
        from springbootai.cloud.gateway import LoggingFilter
        gw = GatewayRouter()
        initial_count = len(gw.filters)
        gw.add_filter(LoggingFilter())
        assert len(gw.filters) == initial_count + 1


# ==================== LoadBalancer 测试 ====================

class TestLoadBalancer:
    def test_round_robin_select(self):
        lb = LoadBalancer()
        instances = [
            {"ip": "10.0.0.1", "port": 80},
            {"ip": "10.0.0.2", "port": 80},
            {"ip": "10.0.0.3", "port": 80},
        ]
        selected = lb.select_instance(instances, strategy="round_robin")
        assert selected in instances

    def test_random_select(self):
        lb = LoadBalancer()
        instances = [
            {"ip": "10.0.0.1", "port": 80},
            {"ip": "10.0.0.2", "port": 80},
        ]
        selected = lb.select_instance(instances, strategy="random")
        assert selected in instances

    def test_empty_instances_raises(self):
        lb = LoadBalancer()
        with pytest.raises(Exception):
            lb.select_instance([], strategy="round_robin")

    def test_weighted_select(self):
        lb = LoadBalancer()
        instances = [
            {"ip": "10.0.0.1", "port": 80, "weight": 1},
            {"ip": "10.0.0.2", "port": 80, "weight": 10},
        ]
        selected = lb.select_instance(instances, strategy="weighted")
        assert selected in instances

    def test_set_strategy(self):
        lb = LoadBalancer()
        lb.set_strategy("random")
        assert lb.strategy == "random"
        # Reset for other tests
        lb.set_strategy("round_robin")

    def test_filters_healthy_instances(self):
        lb = LoadBalancer()
        instances = [
            {"ip": "10.0.0.1", "port": 80, "healthy": False},
            {"ip": "10.0.0.2", "port": 80, "healthy": True},
        ]
        selected = lb.select_instance(instances, strategy="round_robin")
        assert selected["ip"] == "10.0.0.2"

    def test_returns_dict_not_string(self):
        lb = LoadBalancer()
        instances = [{"ip": "10.0.0.1", "port": 80}]
        selected = lb.select_instance(instances, strategy="round_robin")
        assert isinstance(selected, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
