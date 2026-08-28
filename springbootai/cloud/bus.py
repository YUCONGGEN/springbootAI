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
from typing import Any, Callable, Dict, List, Optional

from springbootai.logging.context import redact_sensitive

logger = logging.getLogger("Spring.Cloud.Bus")


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
        event = cls.__new__(cls)
        event.id = data.get('id', str(uuid.uuid4()))
        event.timestamp = data.get('timestamp', int(time.time() * 1000))
        event.origin_service = data.get('originService', 'unknown')
        event.destination_service = data.get('destinationService', '*')
        event.type = data.get('type', '')
        event.data = data.get('data', {})
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
            return

        self._backend = str(bus_config.get('backend', 'local')).lower()
        self._destination = bus_config.get('destination', 'springCloudBus')
        self._service_name = config.get('spring', {}).get('application', {}).get('name', 'application')
        self._configured = True
        logger.info(
            "EventBus configured backend=%s destination=%s service=%s",
            _safe_log_field(self._backend),
            _safe_log_field(self._destination),
            _safe_log_field(self._service_name),
        )

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
        elif self._backend == 'rabbitmq':
            self._deliver_rabbitmq(event)
        elif self._backend == 'kafka':
            self._deliver_kafka(event)
        else:
            logger.warning(
                "Unknown bus backend backend=%s; falling back to local",
                _safe_log_field(self._backend),
            )
            self._deliver_local(event)

        return event.id

    def _deliver_local(self, event: BusEvent) -> None:
        """本地进程内分发事件。"""
        with self._subscription_lock:
            subscriptions = list(self._subscriptions)

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
                self._failed_count += 1
                logger.error(
                    "Bus event delivery failed event_type=%s event_id=%s "
                    "error_type=%s",
                    _safe_log_field(event.type),
                    _safe_log_field(event.id),
                    _safe_log_field(type(exc).__name__),
                )

    def _deliver_rabbitmq(self, event: BusEvent) -> None:
        """通过 RabbitMQ 广播事件。"""
        try:
            from springbootai.messaging.rabbitmq import rabbitmq_client
            message = json.dumps(event.to_dict(), default=str)
            rabbitmq_client.send(self._destination, message)
            # 本地也分发（如果当前服务匹配）
            self._deliver_local(event)
        except ImportError:
            logger.warning("RabbitMQ not installed, falling back to local delivery")
            self._deliver_local(event)
        except Exception as exc:
            logger.error(
                "RabbitMQ bus delivery failed event_type=%s event_id=%s "
                "destination=%s error_type=%s; falling back to local",
                _safe_log_field(event.type),
                _safe_log_field(event.id),
                _safe_log_field(self._destination),
                _safe_log_field(type(exc).__name__),
            )
            self._deliver_local(event)

    def _deliver_kafka(self, event: BusEvent) -> None:
        """通过 Kafka 广播事件。"""
        try:
            from springbootai.messaging.kafka import kafka_client
            kafka_client.send(self._destination, event.to_dict())
            # 本地也分发
            self._deliver_local(event)
        except ImportError:
            logger.warning("Kafka not installed, falling back to local delivery")
            self._deliver_local(event)
        except Exception as exc:
            logger.error(
                "Kafka bus delivery failed event_type=%s event_id=%s "
                "destination=%s error_type=%s; falling back to local",
                _safe_log_field(event.type),
                _safe_log_field(event.id),
                _safe_log_field(self._destination),
                _safe_log_field(type(exc).__name__),
            )
            self._deliver_local(event)

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


# 全局单例
event_bus = EventBus()


def init_bus(config: dict) -> None:
    """从应用配置初始化事件总线。

    Args:
        config: 应用配置字典
    """
    event_bus.configure(config)
    if event_bus.configured:
        logger.info("Spring Cloud Bus initialized")


def create_bus_refresh_endpoint() -> Callable:
    """创建 /actuator/busrefresh 端点的处理函数。

    Returns:
        FastAPI 路由处理函数
    """
    def bus_refresh(destination: str = '*'):
        event_id = event_bus.publish_refresh(destination)
        return {
            'status': 'broadcasted',
            'event_id': event_id,
            'destination': destination,
        }
    return bus_refresh
