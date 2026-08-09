"""事务同步管理器（对齐 Spring ``TransactionSynchronizationManager``）。

跟踪当前事务的同步回调（``TransactionSynchronization``），在事务生命周期各阶段触发：
``BEFORE_COMMIT`` / ``AFTER_COMMIT`` / ``AFTER_ROLLBACK`` / ``AFTER_COMPLETION``。

设计：
- **ContextVar 持有**：用 ``ContextVar`` 保存当前事务的同步列表与活跃标志，兼容 ``asyncio`` 协程，
  对齐 Spring 的 ``ThreadLocal<List<TransactionSynchronization>>``。
- **最佳努力触发**：同步回调抛错时记录日志但不中断事务流程（与 Spring ``after_completion``
  语义一致；``beforeCommit`` 抛错在 Spring 中会触发回滚，此处为安全起见统一记录，避免影响既有事务）。
- **集成点**：``@Transactional`` 切面（``bean_factory._wrap_transactional``）在事务边界调用
  ``init/clear`` 与各 ``trigger_*``；非受管场景可用 ``transaction_sync_scope`` 上下文管理器。

与 Java 的差异：
- Spring 用 ``ThreadLocal``；Python 用 ``ContextVar`` 兼容协程。
- 同步回调抛错统一记录不中断事务（Spring ``beforeCommit`` 抛错会回滚），已在模块文档标注。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Callable, List, Optional

logger = logging.getLogger("Spring.Tx.Synchronization")


class TransactionPhase(Enum):
    """事务事件触发阶段（对齐 Spring ``TransactionPhase``）。"""
    BEFORE_COMMIT = "BEFORE_COMMIT"
    AFTER_COMMIT = "AFTER_COMMIT"
    AFTER_ROLLBACK = "AFTER_ROLLBACK"
    AFTER_COMPLETION = "AFTER_COMPLETION"


class TransactionSynchronization:
    """事务同步回调接口（对齐 Spring ``TransactionSynchronization``）。

    子类按需重写各阶段回调；默认无操作。``@TransactionalEventListener`` 通过本接口的
    适配实现把监听器挂到指定阶段。
    """

    def before_commit(self) -> None:
        """事务提交前调用（同一事务可多次刷新时，仅最终提交前调用一次）。"""

    def after_commit(self) -> None:
        """事务成功提交后调用。"""

    def after_rollback(self) -> None:
        """事务回滚后调用。"""

    def after_completion(self, status: str) -> None:
        """事务完成后调用（``status`` 为 ``'commit'`` 或 ``'rollback'``）。"""


# 当前事务的同步回调列表（None 表示当前无活动事务）
_synchronizations: ContextVar[Optional[List[TransactionSynchronization]]] = ContextVar(
    "spring_tx_synchronizations", default=None
)


class TransactionSynchronizationManager:
    """事务同步管理器（静态方法风格，对齐 Spring 同名类）。"""

    @staticmethod
    def is_synchronization_active() -> bool:
        return _synchronizations.get() is not None

    @staticmethod
    def init_synchronization() -> None:
        """开启一个新的事务同步上下文（``@Transactional`` 入口调用）。"""
        _synchronizations.set([])

    @staticmethod
    def clear_synchronization() -> None:
        """清空当前事务同步上下文（``@Transactional`` 出口调用）。"""
        _synchronizations.set(None)

    @staticmethod
    def get_synchronizations() -> List[TransactionSynchronization]:
        """返回当前事务已注册的同步回调列表（无活动事务返回空列表）。"""
        syncs = _synchronizations.get()
        return list(syncs) if syncs is not None else []

    @staticmethod
    def register_synchronization(sync: TransactionSynchronization) -> None:
        """注册一个同步回调到当前事务；无活动事务时抛错（对齐 Spring）。"""
        syncs = _synchronizations.get()
        if syncs is None:
            raise RuntimeError(
                "注册事务同步回调要求当前存在活动事务；"
                "请在 @Transactional 方法内或 transaction_sync_scope 内调用"
            )
        syncs.append(sync)

    # ==================== 阶段触发 ====================

    @staticmethod
    def trigger_before_commit() -> None:
        TransactionSynchronizationManager._trigger(
            "before_commit", lambda s: s.before_commit()
        )

    @staticmethod
    def trigger_after_commit() -> None:
        TransactionSynchronizationManager._trigger(
            "after_commit", lambda s: s.after_commit()
        )

    @staticmethod
    def trigger_after_rollback() -> None:
        TransactionSynchronizationManager._trigger(
            "after_rollback", lambda s: s.after_rollback()
        )

    @staticmethod
    def trigger_after_completion(status: str) -> None:
        TransactionSynchronizationManager._trigger(
            "after_completion", lambda s: s.after_completion(status)
        )

    @staticmethod
    def _trigger(phase: str, invoker: Callable[[TransactionSynchronization], None]) -> None:
        """最佳努力触发：逐个调用同步回调，单个抛错记录日志但不中断后续。"""
        for sync in TransactionSynchronizationManager.get_synchronizations():
            try:
                invoker(sync)
            except Exception:  # pragma: no cover - 防御性，同步回调实现多样
                logger.exception("事务同步回调 %s 执行失败", phase)


@contextmanager
def transaction_sync_scope():
    """非受管场景的事务同步上下文：进入 init，退出 clear（不触发任何阶段）。

    供独立测试或手动管理事务事件边界使用。``@Transactional`` 切面内部会自行管理。
    """
    TransactionSynchronizationManager.init_synchronization()
    try:
        yield TransactionSynchronizationManager
    finally:
        TransactionSynchronizationManager.clear_synchronization()
