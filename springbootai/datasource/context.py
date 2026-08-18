"""多数据源路由上下文（对齐 Spring ``AbstractRoutingDataSource``）。

``DataSourceContextHolder`` 用 ``ContextVar`` 保存当前线程/协程的路由键，
``DynamicRoutingDataSource`` 在 ``get_connection`` 时读取该键决定走向哪个物理数据源。

对齐 Spring：
- Spring 用 ``ThreadLocal<Object>``；Python 用 ``ContextVar`` 以兼容 ``asyncio`` 协程。
- ``@DS`` / ``@Master`` / ``@Slave`` 注解在方法执行期间设置路由键，退出后复位（对齐
  ``AbstractRoutingDataSource.determineCurrentLookupKey`` + AOP 切面）。

与 Java 的差异：
- Python ``ContextVar`` 的 ``set`` 返回 token，复位用 ``reset(token)``，天然支持嵌套调用
  （内层方法退出后自动恢复外层路由键），比 Spring 的 ``ThreadLocal`` 手动 push/pop 更简洁。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

# 当前路由键：None 表示使用默认数据源（master）
_routing_key: ContextVar[Optional[str]] = ContextVar(
    "spring_datasource_routing_key", default=None
)


class DataSourceContextHolder:
    """线程/协程安全的数据源路由键持有器（静态方法风格，对齐 Spring 同名类）。"""

    @staticmethod
    def get() -> Optional[str]:
        """返回当前路由键；未设置返回 ``None``。"""
        return _routing_key.get()

    @staticmethod
    def set(routing_key: Optional[str]):
        """设置路由键，返回用于复位的 token。"""
        return _routing_key.set(routing_key)

    @staticmethod
    def reset(token) -> None:
        """用 ``set`` 返回的 token 复位路由键。"""
        _routing_key.reset(token)

    @staticmethod
    def clear() -> None:
        """强制清空路由键（慎用，会丢失嵌套层级）。"""
        _routing_key.set(None)


class _RoutingKeyScope:
    """``with`` 语法糖：进入设置路由键，退出复位。供 ``@DS`` AOP 与手写代码共用。"""

    def __init__(self, routing_key: Optional[str]):
        self._routing_key = routing_key
        self._token = None

    def __enter__(self):
        self._token = DataSourceContextHolder.set(self._routing_key)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._token is not None:
            DataSourceContextHolder.reset(self._token)
        return False


def routing_scope(routing_key: Optional[str]) -> _RoutingKeyScope:
    """便捷工厂：``with routing_scope("slave"): ...``。"""
    return _RoutingKeyScope(routing_key)
