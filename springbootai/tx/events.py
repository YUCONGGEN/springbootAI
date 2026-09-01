"""事务事件监听（对齐 Spring ``@TransactionalEventListener`` + ``TransactionalEventPublisher``）。

``@TransactionalEventListener(phase=...)`` 标记的监听器在事务达到指定阶段时才触发：
- ``BEFORE_COMMIT``：事务提交前
- ``AFTER_COMMIT``：事务提交后（默认）
- ``AFTER_ROLLBACK``：事务回滚后
- ``AFTER_COMPLETION``：事务完成后（提交或回滚）

设计：
- **事件延迟**：``TransactionalEventPublisher.publish_event`` 发布事件时，若当前存在活动事务，
  把事务监听器包装为 ``TransactionSynchronization`` 注册到 ``TransactionSynchronizationManager``，
  等待 ``@Transactional`` 切面在对应阶段触发；无活动事务时按 ``fallback_execution`` 决定是否立即执行。
- **复用既有事件基础设施**：普通 ``@EventListener`` 由 ``ApplicationEventPublisher`` 立即触发，
  本模块仅处理事务监听器；可委托 ``ApplicationEventPublisher`` 处理普通监听器以共存的。
- **注解基类**：``TransactionalEventListener`` 继承 ``SpringAnnotation``，元数据挂到
  ``__spring_annotations__``，由 ``ApplicationContext._register_event_listeners`` 扫描注册。

与 Java 的差异：
- Spring ``@TransactionalEventListener`` 默认 ``AFTER_COMMIT``，无事务时不执行；本实现一致。
- 监听器顺序由注册顺序决定（Spring 支持 ``@Order``，本实现保留 ``order`` 字段供扩展）。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, List, Optional, Tuple, Type

from springbootai.annotations.core import ApplicationEvent, SpringAnnotation
from .synchronization import (
    TransactionPhase,
    TransactionSynchronization,
    TransactionSynchronizationManager,
)

logger = logging.getLogger("Spring.Tx.Events")


class TransactionalEventListener(SpringAnnotation):
    """``@TransactionalEventListener`` 标记方法为事务阶段事件监听器。

    Args:
        phase: 触发阶段，默认 ``AFTER_COMMIT``。
        fallback_execution: 无活动事务时是否立即执行（默认 ``False``，对齐 Spring）。
        event_type: 监听的事件类型；未指定时从方法首参类型推断。
        order: 监听器顺序（保留字段，当前按注册顺序触发）。
    """

    _annotation_type = "tx_event_listener"

    def __init__(
        self,
        phase: TransactionPhase = TransactionPhase.AFTER_COMMIT,
        fallback_execution: bool = False,
        event_type: Optional[Type[ApplicationEvent]] = None,
        order: int = 0,
    ):
        # 支持装饰器简写：@TransactionalEventListener(SomeEvent)
        super().__init__(
            phase=phase,
            fallback_execution=fallback_execution,
            event_type=event_type,
            order=order,
        )


# 事务监听器条目：(event_type, callback, phase, fallback_execution, order)
_TxListenerEntry = Tuple[Optional[Type[ApplicationEvent]], Callable, TransactionPhase, bool, int]


class _ListenerSynchronization(TransactionSynchronization):
    """把一个事务监听器适配为事务同步回调，在指定阶段触发。"""

    def __init__(
        self,
        callback: Callable,
        event: Any,
        phase: TransactionPhase,
        order: int,
    ):
        self._callback = callback
        self._event = event
        self._phase = phase
        self._order = order
        # AFTER_COMPLETION 阶段在 after_completion 中触发；其它阶段在对应方法触发。
        self._fired = False

    def _invoke(self) -> None:
        if self._fired:
            return
        self._fired = True
        result = self._callback(self._event)
        if inspect.isawaitable(result):
            self._finish_awaitable(result)

    @staticmethod
    def _finish_awaitable(awaitable) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)
        else:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise RuntimeError(
                "transactional async listeners cannot be detached from an "
                "active event loop; execute the transaction boundary in a "
                "worker thread or use a synchronous listener"
            )

    def before_commit(self) -> None:
        if self._phase == TransactionPhase.BEFORE_COMMIT:
            self._invoke()

    def after_commit(self) -> None:
        if self._phase == TransactionPhase.AFTER_COMMIT:
            self._invoke()

    def after_rollback(self) -> None:
        if self._phase == TransactionPhase.AFTER_ROLLBACK:
            self._invoke()

    def after_completion(self, status: str) -> None:
        if self._phase == TransactionPhase.AFTER_COMPLETION:
            self._invoke()


class TransactionalEventPublisher:
    """事务事件发布器：管理事务监听器并在事务阶段触发。

    与 ``ApplicationEventPublisher`` 平行存在；可单独使用，也可由 ``ApplicationContext``
    注册为 Bean 供 ``publish_event`` 统一委托。
    """

    def __init__(self):
        self._listeners: List[_TxListenerEntry] = []

    def add_listener(
        self,
        callback: Callable,
        event_type: Optional[Type[ApplicationEvent]] = None,
        phase: TransactionPhase = TransactionPhase.AFTER_COMMIT,
        fallback_execution: bool = False,
        order: int = 0,
    ) -> None:
        self._listeners.append((event_type, callback, phase, fallback_execution, order))

    def clear(self) -> None:
        self._listeners.clear()

    def listener_count(self) -> int:
        return len(self._listeners)

    def publish_event(self, event: Any) -> Any:
        """发布事件：匹配的事务监听器按事务阶段触发或回退立即执行。"""
        if not isinstance(event, ApplicationEvent):
            event = ApplicationEvent(source=event)

        tx_active = TransactionSynchronizationManager.is_synchronization_active()
        for event_type, callback, phase, fallback, _order in list(self._listeners):
            if event_type is not None and not isinstance(event, event_type):
                continue
            if tx_active:
                sync = _ListenerSynchronization(callback, event, phase, _order)
                TransactionSynchronizationManager.register_synchronization(sync)
            elif fallback:
                # 无活动事务且允许回退执行：立即触发
                result = callback(event)
                if inspect.isawaitable(result):
                    _ListenerSynchronization._finish_awaitable(result)
            # 否则丢弃（对齐 Spring 默认：无事务不执行）
        return event

    async def publish_event_async(self, event: Any) -> Any:
        """Await fallback listeners; transaction-phase callbacks stay registered."""
        if not isinstance(event, ApplicationEvent):
            event = ApplicationEvent(source=event)

        tx_active = TransactionSynchronizationManager.is_synchronization_active()
        for event_type, callback, phase, fallback, order in list(self._listeners):
            if event_type is not None and not isinstance(event, event_type):
                continue
            if tx_active:
                TransactionSynchronizationManager.register_synchronization(
                    _ListenerSynchronization(callback, event, phase, order)
                )
            elif fallback:
                result = callback(event)
                if inspect.isawaitable(result):
                    await result
        return event


__all__ = [
    "TransactionalEventListener",
    "TransactionalEventPublisher",
]
