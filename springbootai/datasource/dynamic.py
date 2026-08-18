"""动态路由数据源（对齐 Spring ``AbstractRoutingDataSource``）。

``DynamicRoutingDataSource`` 持有多个具名物理数据源（连接池），在 ``get_connection`` 时
依据 ``DataSourceContextHolder`` 的路由键选择目标池，无路由键时走默认目标（master）。

设计：
- **接口兼容**：实现 ``get_connection`` / ``return_connection`` / ``get_pool_stats``，
  可作为 ``SqlSessionFactory.connection_pool`` 的 drop-in 替换，无需改动既有 ORM 调用链。
- **从库负载均衡**：多个 slave 用轮询（round-robin）选择，对齐 Spring ``loadBalance`` 语义。
- **故障转移**：路由键指向的池不存在时回退到默认目标并记录告警，避免业务中断。
- **连接归还**：归还时按连接记录的来源池路由，确保借还一致。

与 Java 的差异：
- Spring 的 ``AbstractRoutingDataSource`` 是 ``DataSource`` 接口实现；这里对齐项目既有
  ``ConnectionPool`` 接口（``get_connection``/``return_connection``），不引入 JDBC 概念。
- 不实现 Spring 的 ``lenientFallback`` 配置项，统一回退到默认目标（更安全）。
"""
from __future__ import annotations

import itertools
import logging
import threading
from typing import Any, Dict, List, Optional

from .context import DataSourceContextHolder

logger = logging.getLogger("Spring.DataSource.Dynamic")


class DynamicRoutingDataSource:
    """动态路由数据源：按路由键在多个物理连接池间路由。

    Args:
        target_data_sources: 具名物理池映射，如 ``{"slave_1": pool1, "slave_2": pool2}``。
        default_target_data_source: 默认目标池（路由键为 None 或未命中时使用），通常为 master。
        slave_keys: 标记为从库的路由键列表，用于 ``@Slave`` 注解做负载均衡轮询。
    """

    def __init__(
        self,
        target_data_sources: Dict[str, Any],
        default_target_data_source: Any,
        slave_keys: Optional[List[str]] = None,
    ):
        if not isinstance(target_data_sources, dict) or not target_data_sources:
            raise ValueError("target_data_sources 必须是非空映射")
        if default_target_data_source is None:
            raise ValueError("default_target_data_source 不能为空")
        self._target_data_sources: Dict[str, Any] = dict(target_data_sources)
        self._default_target = default_target_data_source
        self._slave_keys: List[str] = list(slave_keys) if slave_keys else []
        self._lock = threading.Lock()
        # 轮询计数器：每个 slave_key 一个独立游标，分散热点
        self._slave_iterators: Dict[str, itertools.cycle] = {
            key: itertools.cycle(self._slave_keys) for key in self._slave_keys
        } if self._slave_keys else {}
        # 仅对 slave_keys 做轮询共享一个 cycle，简化为单一游标
        self._slave_cycle = itertools.cycle(self._slave_keys) if self._slave_keys else None
        # 侧表：连接不支持附加属性时（如 dict/原生对象）按 id 记录来源池，归还时清理。
        self._connection_sources: Dict[int, Any] = {}

    # ==================== 路由核心 ====================

    def determine_target_data_source(self) -> Any:
        """依据当前路由键选择目标池；未命中回退到默认目标。

        ``@Slave`` 占位键触发从库轮询；显式具名键直接命中对应池。
        """
        from .annotations import is_slave_placeholder
        routing_key = DataSourceContextHolder.get()
        if routing_key is None:
            return self._default_target
        # @Slave 占位：走从库轮询
        if is_slave_placeholder(routing_key):
            return self.determine_slave_data_source()
        pool = self._target_data_sources.get(routing_key)
        if pool is None:
            logger.warning(
                "路由键 '%s' 未找到对应数据源，回退到默认目标", routing_key
            )
            return self._default_target
        return pool

    def determine_slave_data_source(self) -> Any:
        """从 slave 池中轮询选择一个；无 slave 配置则回退到默认目标。"""
        if self._slave_cycle is None:
            return self._default_target
        with self._lock:
            slave_key = next(self._slave_cycle)
        pool = self._target_data_sources.get(slave_key)
        return pool if pool is not None else self._default_target

    # ==================== 连接池接口（drop-in 替换） ====================

    def get_connection(self) -> Any:
        """获取连接：按路由键选择池，借用其 ``get_connection``。"""
        pool = self.determine_target_data_source()
        connection = pool.get_connection()
        # 在连接上记录来源池，便于归还时路由；不支持属性设置时回退到侧表（按 id）
        try:
            connection.__spring_ds_source__ = pool
        except (AttributeError, TypeError):
            with self._lock:
                self._connection_sources[id(connection)] = pool
        return connection

    def return_connection(self, pooled_conn: Any) -> None:
        """归还连接：优先按连接上记录的来源池归还，未知则回到默认目标。"""
        source_pool = getattr(pooled_conn, "__spring_ds_source__", None)
        if source_pool is None:
            with self._lock:
                source_pool = self._connection_sources.pop(id(pooled_conn), None)
        target = source_pool if source_pool is not None else self._default_target
        try:
            target.return_connection(pooled_conn)
        finally:
            try:
                delattr(pooled_conn, "__spring_ds_source__")
            except (AttributeError, TypeError):
                pass

    def get_pool_stats(self) -> Dict[str, Any]:
        """返回各物理池的统计快照。"""
        stats: Dict[str, Any] = {}
        stats["__default__"] = self._safe_stats(self._default_target)
        for key, pool in self._target_data_sources.items():
            stats[key] = self._safe_stats(pool)
        return stats

    @staticmethod
    def _safe_stats(pool: Any) -> Dict[str, Any]:
        try:
            result = pool.get_pool_stats()
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # pragma: no cover - 防御性
            return {"error": str(exc)}

    # ==================== 运维辅助 ====================

    def get_target_data_sources(self) -> Dict[str, Any]:
        """返回具名物理池映射（只读视图）。"""
        return dict(self._target_data_sources)

    def get_default_target_data_source(self) -> Any:
        return self._default_target

    def get_slave_keys(self) -> List[str]:
        return list(self._slave_keys)
