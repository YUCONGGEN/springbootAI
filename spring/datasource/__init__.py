"""SpringPy 多数据源读写分离模块（对齐 Spring ``AbstractRoutingDataSource`` +
``dynamic-datasource-spring-boot-starter`` 的 ``@DS``/``@Master``/``@Slave``）。

模块组成：
- ``context``:  ``DataSourceContextHolder`` —— ``ContextVar`` 持有当前路由键。
- ``dynamic``:  ``DynamicRoutingDataSource`` —— 多池路由 + 从库轮询 + 故障回退。
- ``annotations``: ``@DS``/``@Master``/``@Slave`` 注解 + 方法级 AOP 切面。

典型用法::

    from spring.datasource import (
        DynamicRoutingDataSource, DS, Master, Slave,
        DataSourceContextHolder, apply_ds_annotations,
    )

    # 1. 装配动态数据源（master + 两个 slave）
    dynamic_ds = DynamicRoutingDataSource(
        target_data_sources={"slave_1": pool1, "slave_2": pool2},
        default_target_data_source=master_pool,
        slave_keys=["slave_1", "slave_2"],
    )

    # 2. 注解驱动路由
    class OrderService:
        @Master
        def create_order(self, order): ...   # 走主库写
        @Slave
        def list_orders(self): ...            # 走从库读（轮询）
        @DS("report_db")
        def report(self): ...                 # 走具名数据源

设计原则：**复用项目既有范式**，注解继承 ``SpringAnnotation``，AOP 注册对齐
``@Validate``/``@Cacheable``，连接池接口对齐 ``ConnectionPool``，未引入第三方库。

与 Java 的差异：
- 用 ``ContextVar`` 替代 ``ThreadLocal``，兼容 ``asyncio`` 协程。
- ``@Slave`` 用占位路由键 + ``DynamicRoutingDataSource`` 轮询解析，无需运行时织入具体键。
"""
from .context import DataSourceContextHolder, routing_scope
from .dynamic import DynamicRoutingDataSource
from .annotations import (
    DS, Master, Slave,
    ds_route_decorator, ds_decorator_factory, apply_ds_annotations, is_slave_placeholder,
)

__version__ = "1.0.0"

__all__ = [
    "DataSourceContextHolder",
    "routing_scope",
    "DynamicRoutingDataSource",
    "DS", "Master", "Slave",
    "ds_route_decorator", "ds_decorator_factory",
    "apply_ds_annotations", "is_slave_placeholder",
    "__version__",
]

# 接入 comprehensive_aop 受管 Bean 包装链路（对齐 @Validate/@Cacheable 注册模式）。
# 在受管 Bean 上标注 @DS/@Master/@Slave 时，IoC 容器会通过 apply_annotations 自动包装。
try:
    from spring.aop.comprehensive_aop import ANNOTATION_DECORATORS
    for _ann_cls in (DS, Master, Slave):
        if _ann_cls not in ANNOTATION_DECORATORS:
            ANNOTATION_DECORATORS[_ann_cls] = ds_decorator_factory
except ImportError:  # pragma: no cover - comprehensive_aop 未安装时静默跳过
    pass
