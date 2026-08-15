"""Spring Cloud Bus 事件总线测试"""
import pytest

from spring.cloud.bus import (
    BusEvent,
    EventBus,
    event_bus,
    init_bus,
)


@pytest.fixture(autouse=True)
def reset_event_bus():
    """每个测试前重置事件总线单例"""
    event_bus.reset()
    event_bus._configured = False
    yield
    event_bus.reset()
    event_bus._configured = False


class TestBusEvent:
    """BusEvent 测试"""

    def test_create_event(self):
        event = BusEvent(
            type='refreshConfig',
            data={'key': 'value'},
            origin_service='myapp',
            destination_service='*',
        )
        assert event.type == 'refreshConfig'
        assert event.data == {'key': 'value'}
        assert event.origin_service == 'myapp'
        assert event.destination_service == '*'
        assert event.id  # UUID 已生成
        assert event.timestamp > 0

    def test_event_serialization(self):
        event = BusEvent(type='test', data={'a': 1}, origin_service='svc1')
        d = event.to_dict()
        assert d['type'] == 'test'
        assert d['data'] == {'a': 1}
        assert d['originService'] == 'svc1'

        restored = BusEvent.from_dict(d)
        assert restored.type == 'test'
        assert restored.data == {'a': 1}
        assert restored.origin_service == 'svc1'
        assert restored.id == event.id

    def test_matches_service_wildcard(self):
        event = BusEvent(type='test', destination_service='*')
        assert event.matches_service('myapp') is True
        assert event.matches_service('any') is True

    def test_matches_service_exact(self):
        event = BusEvent(type='test', destination_service='myapp')
        assert event.matches_service('myapp') is True
        assert event.matches_service('other') is False

    def test_matches_service_prefix(self):
        event = BusEvent(type='test', destination_service='myapp:*')
        assert event.matches_service('myapp') is True
        assert event.matches_service('myapp:8080') is True
        assert event.matches_service('other') is False


class TestEventBusConfigure:
    """事件总线配置测试"""

    def test_configure_disabled(self):
        init_bus({'spring': {'cloud': {'bus': {'enabled': False}}}})
        assert event_bus.configured is False

    def test_configure_enabled(self):
        init_bus({
            'spring': {
                'application': {'name': 'testapp'},
                'cloud': {'bus': {
                    'enabled': True,
                    'backend': 'local',
                    'destination': 'myBus',
                }},
            }
        })
        assert event_bus.configured is True
        assert event_bus._backend == 'local'
        assert event_bus._destination == 'myBus'
        assert event_bus._service_name == 'testapp'


class TestEventBusPublishSubscribe:
    """发布/订阅测试"""

    def test_subscribe_and_publish(self):
        received = []
        event_bus.subscribe('test_event', lambda e: received.append(e))

        event = BusEvent(type='test_event', data={'msg': 'hello'})
        event_bus.publish(event)

        assert len(received) == 1
        assert received[0].type == 'test_event'
        assert received[0].data == {'msg': 'hello'}

    def test_subscribe_wildcard(self):
        received = []
        event_bus.subscribe('*', lambda e: received.append(e))

        event_bus.publish(BusEvent(type='type1'))
        event_bus.publish(BusEvent(type='type2'))

        assert len(received) == 2

    def test_unsubscribe(self):
        received = []

        def callback(e):
            received.append(e)

        event_bus.subscribe('test', callback)
        event_bus.publish(BusEvent(type='test'))
        assert len(received) == 1

        event_bus.unsubscribe(callback)
        event_bus.publish(BusEvent(type='test'))
        assert len(received) == 1  # 没有新增

    def test_multiple_subscribers(self):
        received1 = []
        received2 = []
        event_bus.subscribe('test', lambda e: received1.append(e))
        event_bus.subscribe('test', lambda e: received2.append(e))

        event_bus.publish(BusEvent(type='test'))
        assert len(received1) == 1
        assert len(received2) == 1

    def test_type_filtering(self):
        received = []
        event_bus.subscribe('type_a', lambda e: received.append(e))

        event_bus.publish(BusEvent(type='type_a'))
        event_bus.publish(BusEvent(type='type_b'))

        assert len(received) == 1

    def test_callback_error_isolated(self):
        """一个回调出错不影响其他回调"""
        received = []

        def error_callback(e):
            raise ValueError("intentional error")

        event_bus.subscribe('test', error_callback)
        event_bus.subscribe('test', lambda e: received.append(e))

        event_bus.publish(BusEvent(type='test'))
        assert len(received) == 1  # 第二个回调仍执行

    def test_destination_filtering(self):
        """目标服务过滤"""
        received = []
        event_bus.configure({
            'spring': {
                'application': {'name': 'myapp'},
                'cloud': {'bus': {'enabled': True}},
            }
        })
        event_bus.subscribe('test', lambda e: received.append(e))

        # 目标为其他服务，不应收到
        event_bus.publish(BusEvent(type='test', destination_service='other'))
        assert len(received) == 0

        # 目标为所有服务，应收到
        event_bus.publish(BusEvent(type='test', destination_service='*'))
        assert len(received) == 1

        # 目标为当前服务，应收到
        event_bus.publish(BusEvent(type='test', destination_service='myapp'))
        assert len(received) == 2


class TestEventBusRefresh:
    """配置刷新事件测试"""

    def test_publish_refresh(self):
        received = []
        event_bus.subscribe('refreshConfig', lambda e: received.append(e))

        event_id = event_bus.publish_refresh()
        assert event_id  # 返回事件ID
        assert len(received) == 1
        assert received[0].type == 'refreshConfig'
        assert received[0].data == {'action': 'refresh'}

    def test_publish_refresh_with_destination(self):
        received = []
        event_bus.configure({
            'spring': {
                'application': {'name': 'svc1'},
                'cloud': {'bus': {'enabled': True}},
            }
        })
        event_bus.subscribe('refreshConfig', lambda e: received.append(e))

        # 只发给 svc2，svc1 不应收到
        event_bus.publish_refresh(destination='svc2')
        assert len(received) == 0

        # 发给所有
        event_bus.publish_refresh(destination='*')
        assert len(received) == 1


class TestEventBusStats:
    """统计信息测试"""

    def test_stats(self):
        event_bus.subscribe('test', lambda e: None)
        event_bus.publish(BusEvent(type='test'))
        event_bus.publish(BusEvent(type='test'))

        stats = event_bus.get_stats()
        assert stats['published'] == 2
        assert stats['delivered'] == 2
        assert stats['failed'] == 0
        assert stats['subscriptions'] == 1

    def test_stats_with_failure(self):
        def error_cb(e):
            raise ValueError("error")

        event_bus.subscribe('test', error_cb)
        event_bus.publish(BusEvent(type='test'))

        stats = event_bus.get_stats()
        assert stats['published'] == 1
        assert stats['delivered'] == 0
        assert stats['failed'] == 1
