"""多数据源注解（对齐 ``dynamic-datasource-spring-boot-starter`` 的 ``@DS``/``@Master``/``@Slave``）。

注解在方法执行期间设置 ``DataSourceContextHolder`` 路由键，退出后自动复位，使受管/非受管
Bean 方法内的数据访问自动走向指定数据源。

设计：
- **复用既有注解基类**：``@DS`` 继承 ``SpringAnnotation``，元数据挂到 ``__spring_annotations__``。
- **薄 AOP 包装**：``ds_route_decorator`` 为方法切面，``@DS``/``@Master``/``@Slave`` 通过
  ``comprehensive_aop.ANNOTATION_DECORATORS`` 注册即可接入受管 Bean 包装链路；
  非受管场景用 ``apply_ds_annotations`` 手动包装（与既有 ``@Validate``/``@Cacheable`` 一致）。
- **嵌套复位**：用 ``ContextVar.reset(token)`` 保证内层方法退出后恢复外层路由键，
  对齐 Spring ``AbstractRoutingDataSource`` 的栈式语义。

与 Java 的差异：
- ``dynamic-datasource`` starter 用 ``ThreadLocal`` + AOP；这里用 ``ContextVar`` 兼容协程。
- ``@Master``/``@Slave`` 为 ``@DS`` 的语义快捷方式，路由键分别为 ``"master"`` 与 ``"@slave"`` 占位
  （``@slave`` 占位由 ``DynamicRoutingDataSource`` 在切面内解析为轮询选定的具体 slave 键）。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from spring.annotations.core import SpringAnnotation
from .context import DataSourceContextHolder, routing_scope

# 占位路由键：``@Slave`` 标记进入从库轮询逻辑，由装饰器解析为具体 slave。
_SLAVE_PLACEHOLDER = "@__slave__"


class DS(SpringAnnotation):
    """``@DS("name")`` 指定方法走具名数据源。``@DS`` 不带参数等价于默认（master）。"""

    _annotation_type = "datasource"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class Master(SpringAnnotation):
    """``@Master`` 显式走主库（等价于 ``@DS("master")``）。"""

    _annotation_type = "datasource"

    def __init__(self):
        super().__init__(value="master")


class Slave(SpringAnnotation):
    """``@Slave`` 走从库（负载均衡轮询，由 ``DynamicRoutingDataSource`` 解析）。"""

    _annotation_type = "datasource"

    def __init__(self):
        super().__init__(value=_SLAVE_PLACEHOLDER)


def _resolve_routing_key(ds_annotation: SpringAnnotation) -> Optional[str]:
    """从注解实例解析路由键。

    ``@Slave`` 始终返回占位键，由 ``DynamicRoutingDataSource`` 在连接时解析为轮询 slave；
    若未接入动态数据源，占位键命中不到任何池，``determine_target_data_source`` 回退默认目标，
    行为安全。``@DS("")``/``@DS`` 不带参数返回 ``None``（默认目标）。
    """
    value = getattr(ds_annotation, "value", "") or ""
    if value == _SLAVE_PLACEHOLDER:
        return _SLAVE_PLACEHOLDER
    return value or None


def ds_route_decorator(method: Callable, ds_annotation: SpringAnnotation) -> Callable:
    """``@DS``/``@Master``/``@Slave`` 的方法级切面：进入设路由键，退出复位。

    保留双参数签名供手写调用；``comprehensive_aop`` 注册使用 ``ds_decorator_factory`` 工厂形式。
    """
    routing_key = _resolve_routing_key(ds_annotation)

    if inspect.iscoroutinefunction(method):
        @functools.wraps(method)
        async def async_wrapper(*args, **kwargs):
            with routing_scope(routing_key):
                return await method(*args, **kwargs)
        return async_wrapper

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        with routing_scope(routing_key):
            return method(*args, **kwargs)
    return wrapper


def ds_decorator_factory(ds_annotation: SpringAnnotation) -> Callable:
    """AOP 装饰器工厂（对齐 ``comprehensive_aop.ANNOTATION_DECORATORS`` 注册约定）。

    ``comprehensive_aop.apply_annotations`` 调用形如 ``factory(annotation)(method)``，
    本工厂返回的装饰器会把方法包装为路由键作用域切面。
    """
    def decorator(method: Callable) -> Callable:
        return ds_route_decorator(method, ds_annotation)
    return decorator


def apply_ds_annotations(instance: Any) -> Any:
    """为非受管实例上带 ``@DS``/``@Master``/``@Slave`` 的方法手动应用切面。

    受管 Bean 由 ``comprehensive_aop`` 经 ``ANNOTATION_DECORATORS`` 注册自动包装，
    无需调用本函数。对齐既有 ``apply_annotations`` 的使用模式。
    """
    cls = instance.__class__
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        annotations = getattr(method, "__spring_annotations__", [])
        ds_ann = next(
            (a for a in annotations if isinstance(a, (DS, Master, Slave))),
            None,
        )
        if ds_ann is None:
            continue
        # ds_route_decorator 内部已用 functools.wraps；这里直接绑定到实例
        wrapped = ds_route_decorator(method, ds_ann)
        setattr(instance, name, wrapped.__get__(instance))
    return instance


def is_slave_placeholder(routing_key: Optional[str]) -> bool:
    """供 ``DynamicRoutingDataSource`` 判断当前路由键是否为 ``@Slave`` 占位。"""
    return routing_key == _SLAVE_PLACEHOLDER


__all__ = [
    "DS", "Master", "Slave",
    "ds_route_decorator", "apply_ds_annotations", "is_slave_placeholder",
]
