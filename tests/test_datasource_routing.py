"""P0-3 多数据源读写分离测试。

覆盖 ``springbootai.datasource`` 模块：
- ``DataSourceContextHolder`` 路由键的 set/get/reset/clear 与嵌套复位
- ``routing_scope`` 上下文管理器
- ``DynamicRoutingDataSource`` 路由选择、从库轮询、故障回退、连接归还、统计
- ``@DS``/``@Master``/``@Slave`` 注解 AOP 切面（同步 + 异步、嵌套、非受管应用）
- ``comprehensive_aop`` 受管 Bean 集成

测试用伪连接池（记录每次 ``get_connection`` 借用来源）验证路由正确性，不依赖真实 DB。
"""
import asyncio
import logging

import pytest

from springbootai.datasource import (
    DataSourceContextHolder,
    routing_scope,
    DynamicRoutingDataSource,
    DS, Master, Slave,
    ds_decorator_factory,
    apply_ds_annotations,
    is_slave_placeholder,
)


# ==================== 伪连接池 ====================

class FakePool:
    """伪连接池：每次 get_connection 返回带池名标记的 dict，便于断言路由来源。"""

    def __init__(self, name: str):
        self.name = name
        self.borrowed = 0
        self.returned = 0

    def get_connection(self):
        self.borrowed += 1
        return {"pool": self.name, "conn_id": self.borrowed}

    def return_connection(self, conn):
        self.returned += 1

    def get_pool_stats(self):
        return {"name": self.name, "borrowed": self.borrowed, "returned": self.returned}


# ==================== DataSourceContextHolder ====================

class TestDataSourceContextHolder:
    def setup_method(self):
        DataSourceContextHolder.clear()

    def test_default_is_none(self):
        assert DataSourceContextHolder.get() is None

    def test_set_and_get(self):
        token = DataSourceContextHolder.set("slave_1")
        assert DataSourceContextHolder.get() == "slave_1"
        DataSourceContextHolder.reset(token)
        assert DataSourceContextHolder.get() is None

    def test_nested_set_reset_restores_outer(self):
        outer = DataSourceContextHolder.set("master")
        assert DataSourceContextHolder.get() == "master"
        inner = DataSourceContextHolder.set("slave_1")
        assert DataSourceContextHolder.get() == "slave_1"
        DataSourceContextHolder.reset(inner)
        assert DataSourceContextHolder.get() == "master"  # 恢复外层
        DataSourceContextHolder.reset(outer)
        assert DataSourceContextHolder.get() is None

    def test_clear_forgets_current(self):
        DataSourceContextHolder.set("slave_2")
        DataSourceContextHolder.clear()
        assert DataSourceContextHolder.get() is None


class TestRoutingScope:
    def setup_method(self):
        DataSourceContextHolder.clear()

    def test_scope_sets_and_resets(self):
        assert DataSourceContextHolder.get() is None
        with routing_scope("slave_1"):
            assert DataSourceContextHolder.get() == "slave_1"
        assert DataSourceContextHolder.get() is None

    def test_scope_resets_even_on_exception(self):
        with pytest.raises(RuntimeError):
            with routing_scope("slave_1"):
                assert DataSourceContextHolder.get() == "slave_1"
                raise RuntimeError("boom")
        assert DataSourceContextHolder.get() is None

    def test_nested_scope(self):
        with routing_scope("master"):
            with routing_scope("slave_1"):
                assert DataSourceContextHolder.get() == "slave_1"
            assert DataSourceContextHolder.get() == "master"


# ==================== DynamicRoutingDataSource ====================

class TestDynamicRoutingDataSource:
    def setup_method(self):
        DataSourceContextHolder.clear()
        self.master = FakePool("master")
        self.slave1 = FakePool("slave_1")
        self.slave2 = FakePool("slave_2")
        self.report = FakePool("report_db")
        self.dds = DynamicRoutingDataSource(
            target_data_sources={
                "slave_1": self.slave1,
                "slave_2": self.slave2,
                "report_db": self.report,
                "master": self.master,
            },
            default_target_data_source=self.master,
            slave_keys=["slave_1", "slave_2"],
        )

    def test_default_target_when_no_routing_key(self):
        pool = self.dds.determine_target_data_source()
        assert pool is self.master

    def test_named_routing_key_hits_pool(self):
        with routing_scope("report_db"):
            pool = self.dds.determine_target_data_source()
            assert pool is self.report

    def test_master_routing_key_hits_master(self):
        with routing_scope("master"):
            pool = self.dds.determine_target_data_source()
            assert pool is self.master

    def test_slave_placeholder_triggers_round_robin(self):
        with routing_scope(is_slave_placeholder.__doc__ or "@__slave__"):
            pass
        # 直接用占位键
        from springbootai.datasource.annotations import _SLAVE_PLACEHOLDER
        with routing_scope(_SLAVE_PLACEHOLDER):
            pool = self.dds.determine_target_data_source()
            assert pool in (self.slave1, self.slave2)

    def test_slave_round_robin_distributes(self):
        from springbootai.datasource.annotations import _SLAVE_PLACEHOLDER
        selected = []
        with routing_scope(_SLAVE_PLACEHOLDER):
            for _ in range(4):
                selected.append(self.dds.determine_target_data_source())
        # 两个 slave 轮询，4 次应各出现 2 次
        assert selected.count(self.slave1) == 2
        assert selected.count(self.slave2) == 2

    def test_unknown_routing_key_falls_back_to_default(self, caplog):
        with caplog.at_level(logging.WARNING):
            with routing_scope("nonexistent"):
                pool = self.dds.determine_target_data_source()
                assert pool is self.master
        assert any("nonexistent" in r.message for r in caplog.records)

    def test_get_connection_routes_and_tags_source(self):
        with routing_scope("slave_1"):
            conn = self.dds.get_connection()
        assert conn["pool"] == "slave_1"
        assert self.slave1.borrowed == 1
        # dict 连接走侧表记录来源（不支持属性设置）；return 时能正确路由

    def test_return_connection_routes_to_recorded_source(self):
        with routing_scope("slave_2"):
            conn = self.dds.get_connection()
        self.dds.return_connection(conn)
        assert self.slave2.returned == 1

    def test_get_connection_tags_attribute_on_object_connection(self):
        """支持属性设置的真实连接对象：来源直接挂在连接属性上。"""
        class ObjConn:
            pool = "master"

        class ObjPool:
            borrowed = 0
            returned = 0

            def get_connection(self):
                self.borrowed += 1
                return ObjConn()

            def return_connection(self, conn):
                self.returned += 1

            def get_pool_stats(self):
                return {}

        obj_pool = ObjPool()
        dds = DynamicRoutingDataSource(
            target_data_sources={"x": obj_pool},
            default_target_data_source=obj_pool,
        )
        with routing_scope("x"):
            conn = dds.get_connection()
        assert conn.__spring_ds_source__ is obj_pool
        dds.return_connection(conn)
        assert obj_pool.returned == 1
        assert not hasattr(conn, "__spring_ds_source__")

    def test_return_connection_unknown_source_goes_to_default(self):
        conn = {"pool": "external"}  # 无来源标记
        self.dds.return_connection(conn)
        assert self.master.returned == 1

    def test_get_connection_default_when_no_routing_key(self):
        conn = self.dds.get_connection()
        assert conn["pool"] == "master"

    def test_get_pool_stats_includes_all_pools(self):
        stats = self.dds.get_pool_stats()
        assert "__default__" in stats
        assert "slave_1" in stats and "slave_2" in stats
        assert stats["master"]["name"] == "master"

    def test_constructor_validates_inputs(self):
        with pytest.raises(ValueError):
            DynamicRoutingDataSource({}, self.master)
        with pytest.raises(ValueError):
            DynamicRoutingDataSource({"slave_1": self.slave1}, None)

    def test_slave_without_slave_keys_falls_back_to_default(self):
        dds = DynamicRoutingDataSource(
            target_data_sources={"slave_1": self.slave1},
            default_target_data_source=self.master,
            # 无 slave_keys
        )
        from springbootai.datasource.annotations import _SLAVE_PLACEHOLDER
        with routing_scope(_SLAVE_PLACEHOLDER):
            pool = dds.determine_target_data_source()
            assert pool is self.master

    def test_get_target_data_sources_returns_copy(self):
        targets = self.dds.get_target_data_sources()
        targets["injected"] = self.master
        # 原映射不受影响
        assert "injected" not in self.dds.get_target_data_sources()


# ==================== @DS/@Master/@Slave 注解 AOP ====================

class TestDSAnnotations:
    def setup_method(self):
        DataSourceContextHolder.clear()

    def test_master_annotation_sets_master_key(self):
        class Service:
            @Master
            def write(self):
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        assert svc.write() == "master"
        # 方法退出后复位
        assert DataSourceContextHolder.get() is None

    def test_slave_annotation_sets_placeholder(self):
        class Service:
            @Slave
            def read(self):
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        key = svc.read()
        assert is_slave_placeholder(key)
        assert DataSourceContextHolder.get() is None

    def test_ds_named_annotation(self):
        class Service:
            @DS("report_db")
            def report(self):
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        assert svc.report() == "report_db"
        assert DataSourceContextHolder.get() is None

    def test_ds_without_args_defaults_to_none(self):
        class Service:
            @DS
            def default_op(self):
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        assert svc.default_op() is None

    def test_annotation_preserves_method_metadata(self):
        class Service:
            @DS("report_db")
            def report(self):
                """docstring here"""
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        assert svc.report.__name__ == "report"
        assert svc.report.__doc__ == "docstring here"

    def test_nested_calls_restore_outer_key(self):
        class Inner:
            @Slave
            def read(self):
                return DataSourceContextHolder.get()

        class Outer:
            @Master
            def write(self, inner):
                outer_key = DataSourceContextHolder.get()
                inner_key = inner.read()
                after = DataSourceContextHolder.get()
                return outer_key, inner_key, after

        inner = apply_ds_annotations(Inner())
        outer = apply_ds_annotations(Outer())
        outer_key, inner_key, after = outer.write(inner)
        assert outer_key == "master"
        assert is_slave_placeholder(inner_key)
        # 内层退出后恢复外层 master
        assert after == "master"
        assert DataSourceContextHolder.get() is None

    def test_exception_still_resets_routing_key(self):
        class Service:
            @DS("report_db")
            def fail(self):
                raise RuntimeError("boom")

        svc = apply_ds_annotations(Service())
        with pytest.raises(RuntimeError):
            svc.fail()
        assert DataSourceContextHolder.get() is None

    def test_async_annotation(self):
        class Service:
            @DS("report_db")
            async def report(self):
                await asyncio.sleep(0)
                return DataSourceContextHolder.get()

        svc = apply_ds_annotations(Service())
        result = asyncio.run(svc.report())
        assert result == "report_db"
        assert DataSourceContextHolder.get() is None

    def test_ds_decorator_factory_matches_aop_registry(self):
        # comprehensive_aop 约定：factory(annotation)(method)
        ann = DS("report_db")
        decorator = ds_decorator_factory(ann)

        def method():
            return DataSourceContextHolder.get()
        wrapped = decorator(method)
        assert wrapped() == "report_db"
        assert DataSourceContextHolder.get() is None

    def test_annotations_registered_in_comprehensive_aop(self):
        from springbootai.aop.comprehensive_aop import ANNOTATION_DECORATORS
        assert DS in ANNOTATION_DECORATORS
        assert Master in ANNOTATION_DECORATORS
        assert Slave in ANNOTATION_DECORATORS
        assert ANNOTATION_DECORATORS[DS] is ds_decorator_factory


# ==================== 端到端：注解 + 动态数据源 ====================

class TestEndToEndRouting:
    def setup_method(self):
        DataSourceContextHolder.clear()
        self.master = FakePool("master")
        self.slave1 = FakePool("slave_1")
        self.slave2 = FakePool("slave_2")
        self.dds = DynamicRoutingDataSource(
            target_data_sources={"slave_1": self.slave1, "slave_2": self.slave2},
            default_target_data_source=self.master,
            slave_keys=["slave_1", "slave_2"],
        )

    def test_master_write_goes_to_master(self):
        class OrderService:
            def __init__(self, ds):
                self.ds = ds

            @Master
            def create_order(self):
                conn = self.ds.get_connection()
                return conn["pool"]

        svc = apply_ds_annotations(OrderService(self.dds))
        assert svc.create_order() == "master"
        assert self.master.borrowed == 1

    def test_slave_read_distributes_across_slaves(self):
        class OrderService:
            def __init__(self, ds):
                self.ds = ds

            @Slave
            def list_orders(self):
                conn = self.ds.get_connection()
                return conn["pool"]

        svc = apply_ds_annotations(OrderService(self.dds))
        pools = [svc.list_orders() for _ in range(4)]
        # 两个 slave 各 2 次
        assert pools.count("slave_1") == 2
        assert pools.count("slave_2") == 2
        assert self.slave1.borrowed == 2
        assert self.slave2.borrowed == 2
