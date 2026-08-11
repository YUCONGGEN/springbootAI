"""
测试新特性：Sentinel限流熔断、OpenTelemetry追踪、Seata HTTP补偿事务、
API Gateway、ORM DDL自动建表

运行方式: pytest test_new_features.py -v
"""
import time
import pytest


# ==================== Sentinel 限流熔断测试 ====================

class TestSentinel:
    def setup_method(self):
        from spring.cloud.sentinel import sentinel_engine
        sentinel_engine.reset()

    def test_qps_rate_limiting(self):
        """测试QPS限流"""
        from spring.cloud.sentinel import sentinel_engine, FlowRule, BlockException
        sentinel_engine.load_flow_rules([FlowRule("api_test", count=10.0)])
        
        passed = 0
        blocked = 0
        for _ in range(30):
            try:
                e = sentinel_engine.entry("api_test")
                e.success()
                passed += 1
            except BlockException:
                blocked += 1
        assert passed <= 12, f"QPS限流不生效，passed={passed}"
        assert blocked >= 15, f"应该有更多请求被阻断，blocked={blocked}"

    def test_circuit_breaker_exception_ratio(self):
        """测试异常比例熔断"""
        from spring.cloud.sentinel import sentinel_engine, DegradeRule, BlockException
        sentinel_engine.load_degrade_rules([
            DegradeRule("cb_test", grade="EXCEPTION_RATIO", count=0.5,
                       time_window_sec=5, min_request_amount=3)
        ])
        # 产生错误直到熔断
        errors = 0
        for _ in range(10):
            try:
                e = sentinel_engine.entry("cb_test")
                e.error()
                errors += 1
            except BlockException:
                break
        # 紧接着的请求应当被阻断
        with pytest.raises(BlockException):
            sentinel_engine.entry("cb_test")

    def test_circuit_breaker_recovery(self):
        """测试熔断恢复（半开->闭合）"""
        from spring.cloud.sentinel import sentinel_engine, DegradeRule, BlockException
        sentinel_engine.load_degrade_rules([
            DegradeRule("cb_recover", grade="EXCEPTION_COUNT", count=2,
                       time_window_sec=1, min_request_amount=1)
        ])
        # 触发熔断
        for _ in range(3):
            try:
                e = sentinel_engine.entry("cb_recover")
                e.error()
            except BlockException:
                pass
        # 等待熔断窗口结束
        time.sleep(1.2)
        # 半开状态允许探测请求成功，达到阈值后闭合
        for _ in range(5):
            try:
                e = sentinel_engine.entry("cb_recover")
                e.success()
            except BlockException:
                pass
        stats = sentinel_engine.get_resource_stats("cb_recover")
        assert stats["cb_recover"]["circuit_state"] in ("CLOSED", "HALF_OPEN")

    def test_sentinel_protect_decorator(self):
        """测试sentinel_protect装饰器"""
        from spring.cloud.sentinel import sentinel_protect, sentinel_engine, FlowRule
        sentinel_engine.load_flow_rules([FlowRule("decorated_api", count=100.0)])
        
        results = []
        @sentinel_protect("decorated_api")
        def my_api(x):
            return x * 2
        
        for i in range(5):
            results.append(my_api(i))
        assert results == [0, 2, 4, 6, 8]

    def test_stats_tracking(self):
        """测试统计信息记录"""
        from spring.cloud.sentinel import sentinel_engine
        for _ in range(5):
            e = sentinel_engine.entry("stats_api")
            time.sleep(0.001)
            e.success()
        stats = sentinel_engine.get_resource_stats("stats_api")
        assert "stats_api" in stats
        assert stats["stats_api"]["stats"]["success_count"] >= 5


# ==================== OpenTelemetry 追踪测试 ====================

class TestTracer:
    def test_basic_span(self):
        """测试基本Span创建"""
        from spring.cloud.tracer import Tracer, SpanKind, SpanStatus
        tracer = Tracer("test-svc")
        with tracer.span("hello", SpanKind.SERVER) as span:
            span.set_attribute("http.method", "GET")
            span.set_attribute("http.url", "/api/test")
        assert span.status == SpanStatus.OK
        assert len(span.trace_id) == 32
        assert len(span.span_id) == 16
        assert span.duration_ms >= 0

    def test_nested_spans(self):
        """测试嵌套Span（父子关系）"""
        from spring.cloud.tracer import Tracer
        tracer = Tracer("test-svc")
        with tracer.span("parent") as parent:
            with tracer.span("child") as child:
                assert child.parent_span_id == parent.span_id
                assert child.trace_id == parent.trace_id
        assert parent.parent_span_id is None
        assert child.trace_id == parent.trace_id

    def test_w3c_traceparent_propagation(self):
        """测试W3C traceparent header 传播"""
        from spring.cloud.tracer import Tracer, _parse_traceparent
        tracer = Tracer("test-svc")
        with tracer.span("propagate") as span:
            tp = tracer.get_traceparent_header()
            assert tp.startswith("00-")
            parsed = _parse_traceparent(tp)
            assert parsed is not None
            tid, sid, flags = parsed
            assert tid == span.trace_id
            assert sid == span.span_id

    def test_extract_inject_headers(self):
        """测试headers注入和提取"""
        from spring.cloud.tracer import Tracer
        tracer = Tracer("svc-a")
        with tracer.span("call"):
            headers = {}
            tracer.inject_headers(headers)
            assert "traceparent" in headers
            tp = tracer.extract_from_headers({"traceparent": headers["traceparent"]})
            assert tp is not None

    def test_exception_recording(self):
        """测试异常记录"""
        from spring.cloud.tracer import Tracer, SpanStatus
        tracer = Tracer("test-svc")
        with pytest.raises(ValueError):
            with tracer.span("failing") as span:
                raise ValueError("test error")
        assert span.status == SpanStatus.ERROR
        assert "test error" in span.status_description

    def test_trace_span_decorator(self):
        """测试@trace_span装饰器"""
        from spring.cloud.tracer import trace_span, get_tracer
        tracer = get_tracer("deco-test")
        tracer.clear()

        @trace_span("my_operation")
        def do_work(x):
            return x + 1
        
        result = do_work(41)
        assert result == 42
        spans = tracer.get_spans()
        assert len(spans) >= 1


# ==================== Seata HTTP 补偿事务测试 ====================

class TestSeataHttpAt:
    def setup_method(self):
        from spring.cloud.seata import seata_manager
        seata_manager.set_mode("http")

    def test_begin_commit(self):
        """测试基本的事务开启和提交"""
        from spring.cloud.seata import seata_manager
        commits = []
        def on_commit(xid, bid): commits.append(bid)
        def on_rollback(xid, bid): pass
        
        xid = seata_manager.begin_transaction(name="tx1")
        assert len(xid) == 32
        bid = seata_manager.register_branch(xid, resource_id="db1",
                                            commit_cb=on_commit, rollback_cb=on_rollback)
        assert bid
        ok = seata_manager.commit_transaction(xid)
        assert ok
        assert len(commits) == 1
        assert not seata_manager.is_in_transaction()

    def test_begin_rollback(self):
        """测试事务回滚"""
        from spring.cloud.seata import seata_manager
        rollbacks = []
        def on_commit(xid, bid): pass
        def on_rollback(xid, bid): rollbacks.append(bid)
        
        xid = seata_manager.begin_transaction(name="tx2")
        seata_manager.register_branch(xid, resource_id="db1",
                                      commit_cb=on_commit, rollback_cb=on_rollback)
        ok = seata_manager.rollback_transaction(xid)
        assert ok
        assert len(rollbacks) == 1

    def test_xid_header_propagation(self):
        """测试XID header的注入和提取"""
        from spring.cloud.seata import seata_manager
        xid = seata_manager.begin_transaction(name="tx3")
        headers = {}
        seata_manager.inject_xid_headers(headers, xid)
        assert "X-TX-XID" in headers
        assert headers["X-TX-XID"] == xid
        extracted = seata_manager.get_xid_from_headers(headers)
        assert extracted == xid
        seata_manager.rollback_transaction(xid)

    def test_nested_transaction_returns_same_xid(self):
        """测试嵌套事务（应返回同一XID）"""
        from spring.cloud.seata import seata_manager
        xid1 = seata_manager.begin_transaction(name="outer")
        xid2 = seata_manager.begin_transaction(name="inner")
        assert xid1 == xid2
        seata_manager.commit_transaction(xid1)

    def test_multi_branch_commit(self):
        """测试多分支提交"""
        from spring.cloud.seata import seata_manager
        commits = []
        def mk_cb(name):
            def cb(xid, bid): commits.append(name)
            return cb
        
        xid = seata_manager.begin_transaction(name="multi")
        seata_manager.register_branch(xid, resource_id="order-db", commit_cb=mk_cb("order"), rollback_cb=mk_cb("order-rb"))
        seata_manager.register_branch(xid, resource_id="account-db", commit_cb=mk_cb("account"), rollback_cb=mk_cb("account-rb"))
        seata_manager.register_branch(xid, resource_id="storage-db", commit_cb=mk_cb("storage"), rollback_cb=mk_cb("storage-rb"))
        ok = seata_manager.commit_transaction(xid)
        assert ok
        assert set(commits) == {"order", "account", "storage"}


# ==================== API Gateway 测试 ====================

class TestGateway:
    def test_route_matching(self):
        """测试路由匹配"""
        from spring.cloud.gateway import GatewayRouter
        gw = GatewayRouter()
        gw.route("/api/users/**", service_id="user-svc")
        gw.route("/api/orders/{id}", service_id="order-svc")
        gw.route("/health", uri="http://localhost:8080/actuator/health")
        
        assert gw.match_route("/api/users/123") is not None
        assert gw.match_route("/api/users/123/orders") is not None
        assert gw.match_route("/health") is not None
        assert gw.match_route("/unknown") is None

    def test_strip_prefix(self):
        """测试路径前缀去除"""
        from spring.cloud.gateway import GatewayRouter
        gw = GatewayRouter()
        r = gw.route("/api/users/**", service_id="user-svc", strip_prefix=True)
        assert gw.rewrite_path(r, "/api/users/123") == "/123"

    def test_add_prefix(self):
        """测试添加前缀"""
        from spring.cloud.gateway import GatewayRouter
        gw = GatewayRouter()
        r = gw.route("/ext/**", service_id="ext-svc", prefix="/external", strip_prefix=True)
        rewritten = gw.rewrite_path(r, "/ext/data")
        assert rewritten == "/external/data"

    def test_get_routes(self):
        """测试获取路由列表"""
        from spring.cloud.gateway import GatewayRouter
        gw = GatewayRouter()
        gw.route("/a/**", service_id="a")
        gw.route("/b/**", service_id="b")
        routes = gw.get_routes()
        assert len(routes) == 2


# ==================== ORM DDL 自动建表测试 ====================

class TestDdlAuto:
    def _make_sqlite_pool(self):
        """创建一个简单的SQLite内存数据库pool-like对象"""
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        
        class FakePooled:
            def __init__(self, connection):
                self.connection = connection
        class FakePool:
            def __init__(self, c):
                self._c = c
            def get_connection(self):
                return FakePooled(self._c)
            def return_connection(self, pooled):
                pass
        return FakePool(conn), conn

    def test_generate_create_table_sql(self):
        """测试生成CREATE TABLE语句"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("t_user")
        class User:
            def __init__(self):
                self.id = None
                self.name = ""
                self.age = 0
                self.email = ""
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="create")
        ddl.register_entity(User)
        sqls = ddl.get_generated_sql()
        assert len(sqls) == 1
        assert "CREATE TABLE" in sqls[0]
        assert '"id"' in sqls[0] or '"t_user"' in sqls[0]
        conn.close()

    def test_create_mode_creates_table(self):
        """测试create模式实际创建表"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("products")
        class Product:
            def __init__(self):
                self.id: int = None
                self.name: str = ""
                self.price: float = 0.0
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="create")
        ddl.register_entity(Product)
        executed = ddl.execute()
        assert len(executed) >= 1  # CREATE TABLE
        
        # 验证表已创建
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        assert cur.fetchone() is not None
        
        # 验证列存在
        cur.execute("PRAGMA table_info(products)")
        cols = {r[1] for r in cur.fetchall()}
        assert "id" in cols
        assert "name" in cols
        assert "price" in cols
        conn.close()

    def test_update_mode_adds_columns(self):
        """测试update模式添加新列"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("items_v1")
        class ItemV1:
            def __init__(self):
                self.id: int = None
                self.name: str = ""
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="create")
        ddl.register_entity(ItemV1)
        ddl.execute()
        
        # 现在模拟添加新字段
        @table("items_v1")
        class ItemV2:
            def __init__(self):
                self.id: int = None
                self.name: str = ""
                self.description: str = ""  # 新字段
        
        ddl2 = DdlAutoManager(pool, dialect="sqlite", mode="update")
        ddl2.register_entity(ItemV2)
        executed = ddl2.execute()
        # 应该有一条ALTER TABLE ADD COLUMN
        alter_found = any("ALTER TABLE" in s and "description" in s for s in executed)
        assert alter_found, f"Expected ALTER TABLE ADD COLUMN, got: {executed}"
        conn.close()

    def test_validate_mode_passes_for_matching_schema(self):
        """测试validate模式对匹配的schema通过"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("valid_t")
        class ValidT:
            def __init__(self):
                self.id: int = None
                self.name: str = ""
        
        pool, conn = self._make_sqlite_pool()
        ddl_create = DdlAutoManager(pool, dialect="sqlite", mode="create")
        ddl_create.register_entity(ValidT)
        ddl_create.execute()
        
        ddl_validate = DdlAutoManager(pool, dialect="sqlite", mode="validate")
        ddl_validate.register_entity(ValidT)
        ddl_validate.execute()  # 不应抛出异常
        conn.close()

    def test_validate_mode_fails_for_missing_table(self):
        """测试validate模式对缺失的表抛出异常"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("no_such_table")
        class Missing:
            def __init__(self):
                self.id: int = None
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="validate")
        ddl.register_entity(Missing)
        with pytest.raises(Exception) as exc:
            ddl.execute()
        assert "does not exist" in str(exc.value)
        conn.close()

    def test_dataclass_entity(self):
        """测试dataclass实体"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        from dataclasses import dataclass
        
        @dataclass
        @table("dc_users")
        class DcUser:
            name: str = ""
            age: int = 0
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="create")
        ddl.register_entity(DcUser)
        ddl.execute()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dc_users'")
        assert cur.fetchone() is not None
        conn.close()

    def test_none_mode_does_nothing(self):
        """测试none模式不执行任何DDL"""
        from spring.orm.ddl_auto import DdlAutoManager, table
        
        @table("none_table")
        class Ent:
            def __init__(self):
                self.id: int = None
        
        pool, conn = self._make_sqlite_pool()
        ddl = DdlAutoManager(pool, dialect="sqlite", mode="none")
        ddl.register_entity(Ent)
        executed = ddl.execute()
        assert executed == []
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
