"""
Spring Cloud Bus 事件总线（对齐 Spring Cloud Bus）

在微服务集群中广播事件（配置刷新、应用状态变更等）。

功能：
- 进程内事件总线（默认，无外部依赖）
- 可选的消息队列后端（RabbitMQ/Kafka，分布式广播）
- 发布/订阅模式，支持多订阅者
- 与 ConfigCenter 集成，支持广播配置刷新
- 提供 /actuator/busrefresh 端点

与 Java Spring Cloud Bus 的差异：
- Java 默认使用 RabbitMQ/Kafka 作为传输层
- Python 版本默认使用进程内事件总线（适合单节点开发）
- 分布式场景需显式配置消息队列后端
- Java 使用 @RemoteApplicationEvent，Python 使用 BusEvent 类

配置（application.yml）::

    spring:
      cloud:
        bus:
          enabled: true
          destination: springCloudBus     # 消息目标（topic/exchange名）
          ack-config-service: true        # 配置服务是否ACK
          trace:
            enabled: false                # 事件追踪
          # 可选：使用消息队列后端实现分布式广播
          backend: local                  # local | rabbitmq | kafka
"""
import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from springbootai.logging.context import redact_sensitive

logger = logging.getLogger("Spring.Cloud.Bus")


class BusPublishError(RuntimeError):
    """Raised when a distributed bus publish is not broker-confirmed."""


def _safe_log_field(value: Any, limit: int = 160) -> str:
    """Return a bounded, single-line and credential-redacted log field."""
    try:
        text = redact_sensitive(value)
    except Exception:
        text = f"<unprintable:{type(value).__name__}>"
    text = (
        text.replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return text if len(text) <= limit else text[:limit] + "..."


class BusEvent:
    """事件总线消息

    对齐 Spring Cloud Bus 的 RemoteApplicationEvent。

    Attributes:
        id: 事件ID（UUID）
        timestamp: 发送时间戳
        origin_service: 发送方服务名
        destination_service: 目标服务（*: 所有服务，myapp: 指定服务）
        type: 事件类型（如 refreshConfig）
        data: 事件数据
    """

    def __init__(
        self,
        type: str,
        data: Optional[Dict[str, Any]] = None,
        origin_service: str = 'unknown',
        destination_service: str = '*',
    ):
        self.id = str(uuid.uuid4())
        self.timestamp = int(time.time() * 1000)
        self.origin_service = origin_service
        self.destination_service = destination_service
        self.type = type
        self.data = data or {}

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'originService': self.origin_service,
            'destinationService': self.destination_service,
            'type': self.type,
            'data': self.data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BusEvent':
        """从字典反序列化"""
        if not isinstance(data, Mapping):
            raise ValueError("bus event must be an object")
        event_type = data.get('type', '')
        event_data = data.get('data', {})
        if not isinstance(event_type, str) or not event_type or len(event_type) > 128:
            raise ValueError("bus event type is invalid")
        if not isinstance(event_data, Mapping):
            raise ValueError("bus event data must be an object")
        event = cls.__new__(cls)
        event.id = str(data.get('id', str(uuid.uuid4())))[:128]
        event.timestamp = int(data.get('timestamp', int(time.time() * 1000)))
        event.origin_service = str(data.get('originService', 'unknown'))[:256]
        event.destination_service = str(data.get('destinationService', '*'))[:256]
        event.type = event_type
        event.data = dict(event_data)
        return event

    def matches_service(self, service_name: str) -> bool:
        """判断事件是否匹配目标服务。

        Args:
            service_name: 当前服务名

        Returns:
            True 如果事件应该被当前服务处理
        """
        if self.destination_service == '*':
            return True
        # 支持通配符匹配：myapp:* 匹配 myapp 的所有实例
        if ':' in self.destination_service:
            prefix = self.destination_service.split(':')[0]
            return service_name == prefix or service_name.startswith(prefix + ':')
        return service_name == self.destination_service

    def __repr__(self) -> str:
        return f"BusEvent(type={self.type!r}, id={self.id[:8]}, from={self.origin_service!r}, to={self.destination_service!r})"


class BusSubscription:
    """事件订阅

    Attributes:
        event_type: 订阅的事件类型（* 表示所有类型）
        callback: 回调函数 (event: BusEvent) -> None
    """

    def __init__(self, event_type: str, callback: Callable[[BusEvent], None]):
        self.event_type = event_type
        self.callback = callback


class EventBus:
    """事件总线

    单例模式。

    支持两种工作模式：
    1. local（默认）：进程内事件总线，所有订阅者在同进程内
    2. rabbitmq/kafka：通过消息队列实现分布式广播

    Usage::
        from springbootai.cloud.bus import event_bus, BusEvent

        # 订阅事件
        event_bus.subscribe('refreshConfig', lambda e: print('refreshing...'))

        # 发布事件
        event_bus.publish(BusEvent(type='refreshConfig', data={'keys': ['app.name']}))
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._configured = False
        self._backend: str = 'local'
        self._destination: str = 'springCloudBus'
        self._service_name: str = 'application'
        self._subscriptions: List[BusSubscription] = []
        self._subscription_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._backend_started = False
        self._instance_id = uuid.uuid4().hex[:12]
        self._consumer_name = ''
        self._fallback_local = False
        self._max_event_bytes = 1_048_576
        self._seen_event_ids: Set[str] = set()
        self._processing_event_ids: Set[str] = set()
        self._seen_event_order: Deque[str] = deque(maxlen=10_000)
        self._publish_outcomes: Dict[str, str] = {}
        self._publish_outcome_order: Deque[str] = deque(maxlen=1_000)
        # 统计
        self._published_count = 0
        self._delivered_count = 0
        self._failed_count = 0

    def configure(self, config: dict) -> None:
        """从应用配置初始化事件总线。

        Args:
            config: 应用配置字典
        """
        bus_config = config.get('spring', {}).get('cloud', {}).get('bus', {})
        if not bus_config.get('enabled', False):
            self._configured = False
            self._backend = 'local'
            self._backend_started = False
            return

        self._backend = str(bus_config.get('backend', 'local')).lower()
        if self._backend not in {'local', 'rabbitmq', 'kafka'}:
            raise ValueError("Spring Cloud Bus backend must be local, rabbitmq or kafka")
        self._destination = str(
            bus_config.get('destination', 'springCloudBus')).strip()
        if not self._destination or len(self._destination.encode('utf-8')) > 200:
            raise ValueError("Spring Cloud Bus destination is invalid")
        application = config.get('spring', {}).get('application', {})
        self._service_name = str(application.get('name', 'application')).strip()
        configured_instance = str(
            application.get('instance-id', '') or bus_config.get('instance-id', '')
        ).strip()
        if configured_instance:
            self._instance_id = configured_instance[:64]
        self._fallback_local = bool(bus_config.get('fallback-local', False))
        try:
            self._max_event_bytes = int(
                bus_config.get('max-event-bytes', 1_048_576))
        except (TypeError, ValueError) as exc:
            raise ValueError("Spring Cloud Bus max-event-bytes must be an integer") from exc
        if not 1024 <= self._max_event_bytes <= 10 * 1024 * 1024:
            raise ValueError(
                "Spring Cloud Bus max-event-bytes must be in [1024, 10485760]")
        self._backend_started = self._backend == 'local'
        self._configured = True
        logger.info(
            "EventBus configured backend=%s destination=%s service=%s",
            _safe_log_field(self._backend),
            _safe_log_field(self._destination),
            _safe_log_field(self._service_name),
        )

    def start(self) -> None:
        """Declare transport resources and start a real remote consumer."""
        if not self._configured:
            return
        if self._backend_started:
            return
        if self._backend == 'rabbitmq':
            from springbootai.messaging.rabbitmq import rabbitmq_client

            safe_service = ''.join(
                char if char.isalnum() or char in '._-' else '_'
                for char in self._service_name
            )[:64]
            self._consumer_name = (
                f"{self._destination}.{safe_service}.{self._instance_id}")
            rabbitmq_client.declare_exchange(
                self._destination, exchange_type='fanout', durable=True)
            rabbitmq_client.declare_queue(
                self._consumer_name,
                durable=False,
                exclusive=False,
                auto_delete=True,
            )
            rabbitmq_client.bind_queue(
                self._consumer_name, self._destination, routing_key='')
            rabbitmq_client.consume(
                self._consumer_name, self._receive_remote, auto_ack=False,
                prefetch_count=20,
            )
            rabbitmq_client.start_consuming_background()
        elif self._backend == 'kafka':
            from springbootai.messaging.kafka import kafka_client

            group_id = (
                f"spring-cloud-bus-{self._service_name}-{self._instance_id}")
            kafka_client.register_listener(
                [self._destination], self._receive_remote, group_id=group_id)
            kafka_client.start_consuming([self._destination])
        self._backend_started = True

    def _receive_remote(self, message: Any) -> None:
        """Validate, deduplicate and deliver one broker message locally."""
        payload = message
        if (isinstance(message, Mapping) and 'value' in message
                and {'topic', 'partition', 'offset'}.intersection(message)):
            payload = message.get('value')
        if isinstance(payload, (bytes, bytearray)):
            if len(payload) > self._max_event_bytes:
                raise ValueError("bus event exceeds max-event-bytes")
            payload = payload.decode('utf-8')
        if isinstance(payload, str):
            if len(payload.encode('utf-8')) > self._max_event_bytes:
                raise ValueError("bus event exceeds max-event-bytes")
            payload = json.loads(payload)
        encoded_size = len(json.dumps(
            payload, ensure_ascii=False, separators=(',', ':'),
        ).encode('utf-8'))
        if encoded_size > self._max_event_bytes:
            raise ValueError("bus event exceeds max-event-bytes")
        event = BusEvent.from_dict(payload)
        with self._state_lock:
            if event.id in self._seen_event_ids:
                return
            if event.id in self._processing_event_ids:
                raise RuntimeError("bus event is already being processed")
            self._processing_event_ids.add(event.id)
        try:
            self._deliver_local(event, propagate_failures=True)
        except Exception:
            with self._state_lock:
                self._processing_event_ids.discard(event.id)
            raise
        with self._state_lock:
            self._processing_event_ids.discard(event.id)
            if len(self._seen_event_order) == self._seen_event_order.maxlen:
                expired = self._seen_event_order.popleft()
                self._seen_event_ids.discard(expired)
            self._seen_event_order.append(event.id)
            self._seen_event_ids.add(event.id)

    @property
    def configured(self) -> bool:
        return self._configured

    def subscribe(self, event_type: str, callback: Callable[[BusEvent], None]) -> None:
        """订阅事件。

        Args:
            event_type: 事件类型（'*' 表示订阅所有事件）
            callback: 回调函数，接收 BusEvent 参数
        """
        with self._subscription_lock:
            self._subscriptions.append(BusSubscription(event_type, callback))
        logger.debug(
            "Subscribed to bus event event_type=%s",
            _safe_log_field(event_type),
        )

    def unsubscribe(self, callback: Callable[[BusEvent], None]) -> None:
        """取消订阅。

        Args:
            callback: 要移除的回调函数
        """
        with self._subscription_lock:
            self._subscriptions = [s for s in self._subscriptions if s.callback != callback]

    def publish(self, event: BusEvent) -> str:
        """发布事件。

        Args:
            event: 要发布的事件

        Returns:
            事件ID
        """
        if not event.origin_service or event.origin_service == 'unknown':
            event.origin_service = self._service_name

        serialized = json.dumps(
            event.to_dict(), ensure_ascii=False, separators=(',', ':'),
            default=str,
        )
        if len(serialized.encode('utf-8')) > self._max_event_bytes:
            raise ValueError("bus event exceeds max-event-bytes")
        self._published_count += 1
        # Never log ``event.data``: refresh/custom events routinely contain
        # configuration values, credentials or user-controlled text.
        logger.info(
            "Publishing bus event event_type=%s event_id=%s origin=%s "
            "destination=%s",
            _safe_log_field(event.type),
            _safe_log_field(event.id),
            _safe_log_field(event.origin_service),
            _safe_log_field(event.destination_service),
        )

        if self._backend == 'local':
            self._deliver_local(event)
            self._record_publish_outcome(event.id, 'local-delivered')
            return event.id

        if not self._configured or not self._backend_started:
            self._failed_count += 1
            self._record_publish_outcome(event.id, 'failed')
            raise BusPublishError("distributed bus backend is not ready")

        try:
            if self._backend == 'rabbitmq':
                self._deliver_rabbitmq(event, serialized)
            else:
                self._deliver_kafka(event)
        except Exception as exc:
            self._failed_count += 1
            if self._fallback_local:
                self._deliver_local(event)
                self._record_publish_outcome(event.id, 'degraded-local')
                logger.error(
                    "Bus broker publish failed; explicit local fallback used "
                    "event_type=%s event_id=%s backend=%s error_type=%s",
                    _safe_log_field(event.type), _safe_log_field(event.id),
                    _safe_log_field(self._backend), type(exc).__name__,
                )
                return event.id
            self._record_publish_outcome(event.id, 'failed')
            logger.error(
                "Bus broker publish failed event_type=%s event_id=%s "
                "backend=%s error_type=%s",
                _safe_log_field(event.type), _safe_log_field(event.id),
                _safe_log_field(self._backend), type(exc).__name__,
            )
            raise BusPublishError("distributed bus publish failed") from exc

        self._record_publish_outcome(event.id, 'broadcasted')
        return event.id

    def _record_publish_outcome(self, event_id: str, status: str) -> None:
        with self._state_lock:
            if len(self._publish_outcome_order) == self._publish_outcome_order.maxlen:
                expired = self._publish_outcome_order.popleft()
                self._publish_outcomes.pop(expired, None)
            self._publish_outcome_order.append(event_id)
            self._publish_outcomes[event_id] = status

    def get_publish_outcome(self, event_id: str) -> str:
        with self._state_lock:
            return self._publish_outcomes.get(event_id, 'unknown')

    def _deliver_local(
        self, event: BusEvent, *, propagate_failures: bool = False
    ) -> None:
        """本地进程内分发事件。"""
        with self._subscription_lock:
            subscriptions = list(self._subscriptions)

        failures = 0
        for sub in subscriptions:
            # 类型匹配：'*' 匹配所有，否则精确匹配
            if sub.event_type != '*' and sub.event_type != event.type:
                continue
            # 目标服务匹配
            if not event.matches_service(self._service_name):
                continue
            try:
                sub.callback(event)
                self._delivered_count += 1
            except Exception as exc:
                failures += 1
                self._failed_count += 1
                logger.error(
                    "Bus event delivery failed event_type=%s event_id=%s "
                    "error_type=%s",
                    _safe_log_field(event.type),
                    _safe_log_field(event.id),
                    _safe_log_field(type(exc).__name__),
                )
        if failures and propagate_failures:
            raise RuntimeError("one or more bus subscribers failed")

    def _deliver_rabbitmq(self, event: BusEvent, message: str) -> None:
        """通过 RabbitMQ 广播事件。"""
        from springbootai.messaging.rabbitmq import rabbitmq_client

        rabbitmq_client.publish(
            self._destination,
            '',
            message,
            content_type='application/json',
            persistent=True,
        )

    def _deliver_kafka(self, event: BusEvent) -> None:
        """通过 Kafka 广播事件。"""
        from springbootai.messaging.kafka import kafka_client

        kafka_client.send_and_wait(
            self._destination, event.to_dict(), key=event.id, timeout=10.0)

    def publish_refresh(self, destination: str = '*') -> str:
        """发布配置刷新事件。

        Args:
            destination: 目标服务（默认 *，即所有服务）

        Returns:
            事件ID
        """
        event = BusEvent(
            type='refreshConfig',
            data={'action': 'refresh'},
            origin_service=self._service_name,
            destination_service=destination,
        )
        return self.publish(event)

    def get_stats(self) -> Dict[str, int]:
        """获取事件总线统计信息。"""
        with self._subscription_lock:
            sub_count = len(self._subscriptions)
        return {
            'published': self._published_count,
            'delivered': self._delivered_count,
            'failed': self._failed_count,
            'subscriptions': sub_count,
        }

    def reset(self) -> None:
        """重置事件总线（清空订阅和统计）"""
        with self._subscription_lock:
            self._subscriptions.clear()
        self._published_count = 0
        self._delivered_count = 0
        self._failed_count = 0
        with self._state_lock:
            self._seen_event_ids.clear()
            self._processing_event_ids.clear()
            self._seen_event_order.clear()
            self._publish_outcomes.clear()
            self._publish_outcome_order.clear()


# 全局单例
event_bus = EventBus()


def init_bus(config: dict) -> None:
    """从应用配置初始化事件总线。

    Args:
        config: 应用配置字典
    """
    event_bus.configure(config)
    if event_bus.configured:
        event_bus.start()
        logger.info("Spring Cloud Bus initialized")


def create_bus_refresh_endpoint() -> Callable:
    """创建 /actuator/busrefresh 端点的处理函数。

    Returns:
        FastAPI 路由处理函数
    """
    def bus_refresh(destination: str = '*'):
        try:
            event_id = event_bus.publish_refresh(destination)
        except BusPublishError as exc:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=503,
                detail="Spring Cloud Bus broker publish failed",
            ) from exc
        return {
            'status': event_bus.get_publish_outcome(event_id),
            'event_id': event_id,
            'destination': destination,
        }
    return bus_refresh
