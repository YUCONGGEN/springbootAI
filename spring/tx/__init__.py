"""SpringBootAI 事务扩展模块（对齐 Spring ``@TransactionalEventListener``）。

模块组成：
- ``synchronization``: ``TransactionSynchronizationManager`` + ``TransactionSynchronization`` +
  ``TransactionPhase`` —— 事务同步回调管理（``ContextVar`` 兼容协程）。
- ``events``: ``@TransactionalEventListener`` 注解 + ``TransactionalEventPublisher`` ——
  事务阶段事件监听。

典型用法::

    from spring.tx import (
        TransactionalEventListener, TransactionPhase,
        TransactionalEventPublisher, TransactionSynchronizationManager,
    )

    class OrderCreatedEvent(ApplicationEvent):
        pass

    class OrderService:
        @TransactionalEventListener(phase=TransactionPhase.AFTER_COMMIT)
        def on_order_created(self, event: OrderCreatedEvent):
            ...  # 事务提交后才执行

集成：
- ``@Transactional`` 切面（``bean_factory._wrap_transactional``）在事务边界调用
  ``TransactionSynchronizationManager.init/clear`` 与各 ``trigger_*`` 触发回调。
- ``ApplicationContext`` 扫描 ``@TransactionalEventListener`` 注册到
  ``TransactionalEventPublisher``，``publish_event`` 委托触发。

与 Java 的差异：
- 用 ``ContextVar`` 替代 ``ThreadLocal``，兼容 ``asyncio`` 协程。
- 同步回调抛错统一记录不中断事务（Spring ``beforeCommit`` 抛错会回滚），已在文档标注。
"""
from .synchronization import (
    TransactionPhase,
    TransactionSynchronization,
    TransactionSynchronizationManager,
    transaction_sync_scope,
)
from .events import TransactionalEventListener, TransactionalEventPublisher

__version__ = "2.2.1"

__all__ = [
    "TransactionPhase",
    "TransactionSynchronization",
    "TransactionSynchronizationManager",
    "transaction_sync_scope",
    "TransactionalEventListener",
    "TransactionalEventPublisher",
    "__version__",
]
