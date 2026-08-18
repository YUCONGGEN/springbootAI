"""P1-4 事务事件监听测试。

覆盖 ``springbootai.tx`` 模块：
- ``TransactionSynchronizationManager`` 同步上下文（init/clear/register/trigger/嵌套）
- ``TransactionSynchronization`` 回调接口与阶段触发
- ``TransactionalEventPublisher`` 事件延迟到事务阶段、``fallback_execution``、事件类型过滤
- ``@TransactionalEventListener`` 注解元数据
- ``@Transactional`` 切面集成（用 ``transaction_sync_scope`` 模拟事务边界，验证阶段触发顺序）
- 异步监听器

测试用 ``transaction_sync_scope`` + 手动 ``trigger_*`` 模拟 ``@Transactional`` 事务边界，
无需真实 MyBatis/DB，覆盖事务事件语义。
"""
import asyncio

import pytest

from springbootai.annotations.core import ApplicationEvent
from springbootai.tx import (
    TransactionPhase,
    TransactionSynchronization,
    TransactionSynchronizationManager,
    transaction_sync_scope,
    TransactionalEventListener,
    TransactionalEventPublisher,
)


# ==================== 测试事件 ====================

class OrderCreatedEvent(ApplicationEvent):
    def __init__(self, order_id, source=None):
        super().__init__(source=source)
        self.order_id = order_id


class OrderCancelledEvent(ApplicationEvent):
    pass


# ==================== TransactionSynchronizationManager ====================

class TestSynchronizationManager:
    def setup_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def teardown_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def test_default_not_active(self):
        assert not TransactionSynchronizationManager.is_synchronization_active()

    def test_init_marks_active(self):
        TransactionSynchronizationManager.init_synchronization()
        assert TransactionSynchronizationManager.is_synchronization_active()

    def test_clear_deactivates(self):
        TransactionSynchronizationManager.init_synchronization()
        TransactionSynchronizationManager.clear_synchronization()
        assert not TransactionSynchronizationManager.is_synchronization_active()

    def test_register_and_get_synchronizations(self):
        TransactionSynchronizationManager.init_synchronization()
        sync = TransactionSynchronization()
        TransactionSynchronizationManager.register_synchronization(sync)
        syncs = TransactionSynchronizationManager.get_synchronizations()
        assert len(syncs) == 1
        assert syncs[0] is sync

    def test_register_without_active_transaction_raises(self):
        sync = TransactionSynchronization()
        with pytest.raises(RuntimeError):
            TransactionSynchronizationManager.register_synchronization(sync)

    def test_get_synchronizations_when_inactive_returns_empty(self):
        assert TransactionSynchronizationManager.get_synchronizations() == []

    def test_trigger_before_commit_invokes_callbacks(self):
        TransactionSynchronizationManager.init_synchronization()
        calls = []
        class Sync(TransactionSynchronization):
            def before_commit(self):
                calls.append("before_commit")
        TransactionSynchronizationManager.register_synchronization(Sync())
        TransactionSynchronizationManager.trigger_before_commit()
        assert calls == ["before_commit"]

    def test_trigger_after_commit_and_completion(self):
        TransactionSynchronizationManager.init_synchronization()
        calls = []
        class Sync(TransactionSynchronization):
            def after_commit(self):
                calls.append("after_commit")
            def after_completion(self, status):
                calls.append(("after_completion", status))
        TransactionSynchronizationManager.register_synchronization(Sync())
        TransactionSynchronizationManager.trigger_after_commit()
        TransactionSynchronizationManager.trigger_after_completion("commit")
        assert calls == ["after_commit", ("after_completion", "commit")]

    def test_trigger_after_rollback(self):
        TransactionSynchronizationManager.init_synchronization()
        calls = []
        class Sync(TransactionSynchronization):
            def after_rollback(self):
                calls.append("after_rollback")
        TransactionSynchronizationManager.register_synchronization(Sync())
        TransactionSynchronizationManager.trigger_after_rollback()
        assert calls == ["after_rollback"]

    def test_trigger_best_effort_does_not_propagate_exception(self, caplog):
        """同步回调抛错应记录日志但不中断后续回调。"""
        import logging
        TransactionSynchronizationManager.init_synchronization()
        calls = []
        class BadSync(TransactionSynchronization):
            def after_commit(self):
                raise RuntimeError("boom")
        class GoodSync(TransactionSynchronization):
            def after_commit(self):
                calls.append("good")
        TransactionSynchronizationManager.register_synchronization(BadSync())
        TransactionSynchronizationManager.register_synchronization(GoodSync())
        with caplog.at_level(logging.ERROR):
            TransactionSynchronizationManager.trigger_after_commit()
        assert calls == ["good"]  # 后续回调仍执行

    def test_transaction_sync_scope_context_manager(self):
        assert not TransactionSynchronizationManager.is_synchronization_active()
        with transaction_sync_scope():
            assert TransactionSynchronizationManager.is_synchronization_active()
        assert not TransactionSynchronizationManager.is_synchronization_active()


# ==================== TransactionalEventListener 注解 ====================

class TestTransactionalEventListenerAnnotation:
    def test_default_phase_is_after_commit(self):
        ann = TransactionalEventListener()
        assert ann.phase == TransactionPhase.AFTER_COMMIT

    def test_custom_phase(self):
        ann = TransactionalEventListener(phase=TransactionPhase.BEFORE_COMMIT)
        assert ann.phase == TransactionPhase.BEFORE_COMMIT

    def test_fallback_execution_default_false(self):
        ann = TransactionalEventListener()
        assert ann.fallback_execution is False

    def test_fallback_execution_true(self):
        ann = TransactionalEventListener(fallback_execution=True)
        assert ann.fallback_execution is True

    def test_annotation_metadata_attached_to_method(self):
        class Service:
            @TransactionalEventListener(phase=TransactionPhase.AFTER_ROLLBACK)
            def on_event(self, event):
                pass
        annotations = getattr(Service.on_event, "__spring_annotations__", [])
        assert any(isinstance(a, TransactionalEventListener) for a in annotations)
        ann = next(a for a in annotations if isinstance(a, TransactionalEventListener))
        assert ann.phase == TransactionPhase.AFTER_ROLLBACK


# ==================== TransactionalEventPublisher ====================

class TestTransactionalEventPublisher:
    def setup_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def teardown_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def test_publish_without_transaction_and_no_fallback_skips(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(lambda e: calls.append(e), fallback_execution=False)
        publisher.publish_event(OrderCreatedEvent(1))
        assert calls == []  # 无事务、不回退 → 丢弃

    def test_publish_without_transaction_with_fallback_executes_immediately(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(lambda e: calls.append(e.order_id), fallback_execution=True)
        publisher.publish_event(OrderCreatedEvent(42))
        assert calls == [42]

    def test_publish_with_transaction_defers_until_after_commit(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append(("after_commit", e.order_id)),
            phase=TransactionPhase.AFTER_COMMIT,
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(7))
            assert calls == []  # 事务未提交，未触发
            TransactionSynchronizationManager.trigger_after_commit()
        assert calls == [("after_commit", 7)]

    def test_publish_defers_until_before_commit(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append("before_commit"),
            phase=TransactionPhase.BEFORE_COMMIT,
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(1))
            assert calls == []
            TransactionSynchronizationManager.trigger_before_commit()
        assert calls == ["before_commit"]

    def test_publish_defers_until_after_rollback(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append("after_rollback"),
            phase=TransactionPhase.AFTER_ROLLBACK,
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(1))
            assert calls == []
            TransactionSynchronizationManager.trigger_after_rollback()
        assert calls == ["after_rollback"]

    def test_publish_defers_until_after_completion(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append(("after_completion", )),
            phase=TransactionPhase.AFTER_COMPLETION,
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_completion("commit")
        assert calls == [("after_completion", )]

    def test_event_type_filtering(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append(e), event_type=OrderCreatedEvent
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCancelledEvent())
            publisher.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_commit()
        assert len(calls) == 1  # 仅 OrderCreatedEvent 命中

    def test_after_commit_not_fired_on_rollback(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append("commit"),
            phase=TransactionPhase.AFTER_COMMIT,
        )
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_rollback()
            # 不触发 after_commit
        assert calls == []  # 回滚后 after_commit 不触发

    def test_multiple_listeners_triggered_in_order(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(lambda e: calls.append("a"))
        publisher.add_listener(lambda e: calls.append("b"))
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_commit()
        assert calls == ["a", "b"]

    def test_after_completion_fires_on_both_commit_and_rollback(self):
        # commit 路径
        calls1 = []
        p1 = TransactionalEventPublisher()
        p1.add_listener(lambda e: calls1.append("done"), phase=TransactionPhase.AFTER_COMPLETION)
        with transaction_sync_scope():
            p1.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_completion("commit")
        assert calls1 == ["done"]
        # rollback 路径
        calls2 = []
        p2 = TransactionalEventPublisher()
        p2.add_listener(lambda e: calls2.append("done"), phase=TransactionPhase.AFTER_COMPLETION)
        with transaction_sync_scope():
            p2.publish_event(OrderCreatedEvent(1))
            TransactionSynchronizationManager.trigger_after_completion("rollback")
        assert calls2 == ["done"]

    def test_clear_and_count(self):
        publisher = TransactionalEventPublisher()
        publisher.add_listener(lambda e: None)
        publisher.add_listener(lambda e: None)
        assert publisher.listener_count() == 2
        publisher.clear()
        assert publisher.listener_count() == 0

    def test_non_application_event_wrapped(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(lambda e: calls.append(e), fallback_execution=True)
        publisher.publish_event("plain-string-event")
        assert len(calls) == 1
        assert isinstance(calls[0], ApplicationEvent)


# ==================== @Transactional 切面集成（模拟事务边界）====================

class TestTransactionalIntegration:
    """模拟 ``@Transactional`` 切面的事务边界，验证事件在正确阶段触发。

    ``bean_factory._wrap_transactional`` 内部调用相同的 ``TransactionSynchronizationManager``
    API，因此用 ``transaction_sync_scope`` + 手动触发可等价验证集成语义。
    """

    def setup_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def teardown_method(self):
        TransactionSynchronizationManager.clear_synchronization()

    def _run_transactional_boundary(self, body, *, succeed=True):
        """复刻 ``bean_factory._wrap_transactional`` 的事务同步生命周期。

        init → body → (成功: before_commit/after_commit | 失败: after_rollback)
        → after_completion → clear。所有触发在 clear 之前完成，对齐真实切面。
        """
        TransactionSynchronizationManager.init_synchronization()
        committed = False
        try:
            try:
                body()
            except Exception:
                if succeed:
                    raise
                TransactionSynchronizationManager.trigger_after_rollback()
                return
            TransactionSynchronizationManager.trigger_before_commit()
            committed = True
            TransactionSynchronizationManager.trigger_after_commit()
        finally:
            TransactionSynchronizationManager.trigger_after_completion(
                "commit" if committed else "rollback"
            )
            TransactionSynchronizationManager.clear_synchronization()

    def test_simulated_successful_transaction_fires_after_commit(self):
        """模拟成功事务：method 内发布事件，提交后触发 AFTER_COMMIT 监听器。"""
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append(("committed", e.order_id)),
            phase=TransactionPhase.AFTER_COMMIT,
        )

        def business_method():
            publisher.publish_event(OrderCreatedEvent(99))

        self._run_transactional_boundary(business_method, succeed=True)
        assert calls == [("committed", 99)]

    def test_simulated_rollback_fires_after_rollback_not_after_commit(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append("commit"), phase=TransactionPhase.AFTER_COMMIT
        )
        publisher.add_listener(
            lambda e: calls.append("rollback"), phase=TransactionPhase.AFTER_ROLLBACK
        )

        def business_method():
            publisher.publish_event(OrderCreatedEvent(1))
            raise RuntimeError("业务异常")

        self._run_transactional_boundary(business_method, succeed=False)
        assert calls == ["rollback"]

    def test_event_published_outside_transaction_with_fallback(self):
        calls = []
        publisher = TransactionalEventPublisher()
        publisher.add_listener(
            lambda e: calls.append(e.order_id), fallback_execution=True
        )
        # 无事务上下文，fallback_execution=True → 立即执行
        publisher.publish_event(OrderCreatedEvent(5))
        assert calls == [5]

    def test_async_listener_fires(self):
        calls = []
        publisher = TransactionalEventPublisher()

        async def async_listener(event):
            calls.append(("async", event.order_id))

        publisher.add_listener(async_listener)
        with transaction_sync_scope():
            publisher.publish_event(OrderCreatedEvent(3))
            TransactionSynchronizationManager.trigger_after_commit()
        # 异步监听器在事件循环中执行；运行循环以收集结果
        asyncio.run(asyncio.sleep(0))
        assert ("async", 3) in calls
