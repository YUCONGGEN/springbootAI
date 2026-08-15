"""
Kafka 消息队列模块
集成 Kafka 实现高吞吐量异步消息处理

依赖：kafka-python（pip install kafka-python）

与 RabbitMQ 的差异：
- Kafka 是拉取模型（Consumer 主动 poll），RabbitMQ 是推送模型（Broker 推送）
- Kafka 消息持久化到磁盘（按 offset），RabbitMQ 消息确认后删除
- Kafka 支持消息回溯（重置 offset），RabbitMQ 不支持
- Kafka 适合日志/流处理/事件溯源，RabbitMQ 适合任务队列/RPC

配置（application.yml）：
    spring:
      kafka:
        bootstrap-servers: localhost:9092
        consumer:
          group-id: my-group
          auto-offset-reset: latest
        producer:
          acks: all
          retries: 3
"""
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Spring.Messaging.Kafka")


class KafkaClient:
    """Kafka 客户端（生产者 + 消费者管理）。

    单例模式，与 RabbitMQClient 对齐。
    使用 kafka-python 库（BlockingConnection API），适合同步场景。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, bootstrap_servers: str = "localhost:9092",
                 group_id: str = "default-group",
                 auto_offset_reset: str = "latest"):
        if hasattr(self, '_initialized'):
            return
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self._producer = None
        self._consumers: Dict[str, Callable] = {}
        self._consumer_threads: List[threading.Thread] = []
        self._running = False
        self._initialized = True

    def configure(self, bootstrap_servers: Optional[str] = None,
                  group_id: Optional[str] = None,
                  auto_offset_reset: Optional[str] = None) -> None:
        """重新配置单例的 Kafka 连接参数（读取配置后调用）。"""
        self.close()
        if bootstrap_servers is not None:
            self.bootstrap_servers = bootstrap_servers
        if group_id is not None:
            self.group_id = group_id
        if auto_offset_reset is not None:
            self.auto_offset_reset = auto_offset_reset
        self._producer = None
        self._consumers.clear()
        self._consumer_threads.clear()
        self._running = False

    def _get_producer(self):
        """获取或创建 KafkaProducer（惰性初始化）。"""
        if self._producer is not None:
            return self._producer
        try:
            from kafka import KafkaProducer
            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers.split(','),
                value_serializer=lambda v: json.dumps(v).encode('utf-8') if not isinstance(v, bytes) else v,
                key_serializer=lambda k: k.encode('utf-8') if isinstance(k, str) else k,
                acks='all',
                retries=3,
                max_in_flight_requests_per_connection=5,
            )
            logger.info(f"KafkaProducer connected to {self.bootstrap_servers}")
            return self._producer
        except ImportError:
            raise ImportError(
                "kafka-python is not installed. Install with: pip install kafka-python"
            )
        except Exception as e:
            logger.error(f"Failed to create KafkaProducer: {e}")
            raise

    def send(self, topic: str, value: Any, key: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None) -> Any:
        """发送消息到指定 topic。

        Args:
            topic: Kafka 主题
            value: 消息体（自动 JSON 序列化）
            key: 分区键（可选，相同 key 路由到同一分区）
            headers: 消息头（可选）

        Returns:
            kafka.FutureRecordMetadata（可调用 .get() 等待确认）
        """
        producer = self._get_producer()
        # 安全校验：topic 名不能包含特殊字符
        if not topic or any(c in topic for c in ' \t\n'):
            raise ValueError(f"Invalid Kafka topic name: {topic!r}")

        kafka_headers = [(k, v.encode('utf-8')) for k, v in (headers or {}).items()]
        future = producer.send(topic, value=value, key=key, headers=kafka_headers)
        logger.debug(f"Sent message to topic={topic}, key={key}")
        return future

    def send_and_wait(self, topic: str, value: Any, key: Optional[str] = None,
                      timeout: float = 10.0) -> Any:
        """发送消息并等待确认（同步发送）。"""
        future = self.send(topic, value, key=key)
        return future.get(timeout=timeout)

    def register_listener(self, topics: List[str], callback: Callable,
                          group_id: Optional[str] = None) -> None:
        """注册消费者监听器。

        Args:
            topics: 要订阅的 topic 列表
            callback: 消息回调函数，签名为 callback(message) 其中 message 是 dict
            group_id: 消费者组（默认使用全局 group_id）
        """
        for topic in topics:
            if not topic or any(c in topic for c in ' \t\n'):
                raise ValueError(f"Invalid Kafka topic name: {topic!r}")
            self._consumers[topic] = callback
            logger.info(f"Registered Kafka listener for topic={topic}, group_id={group_id or self.group_id}")

    def start_consuming(self, topics: Optional[List[str]] = None) -> None:
        """启动消费者线程（在后台线程中轮询消息）。

        Args:
            topics: 要消费的 topic 列表（默认消费所有已注册的 topic）
        """
        if self._running:
            logger.warning("Kafka consumers are already running")
            return

        target_topics = topics or list(self._consumers.keys())
        if not target_topics:
            logger.warning("No topics to consume")
            return

        self._running = True

        for topic in target_topics:
            callback = self._consumers.get(topic)
            if callback is None:
                logger.warning(f"No callback registered for topic={topic}")
                continue

            thread = threading.Thread(
                target=self._consume_loop,
                args=(topic, callback),
                daemon=True,
                name=f"kafka-consumer-{topic}",
            )
            thread.start()
            self._consumer_threads.append(thread)
            logger.info(f"Started Kafka consumer thread for topic={topic}")

    def _consume_loop(self, topic: str, callback: Callable) -> None:
        """消费者轮询循环（在独立线程中运行）。"""
        try:
            from kafka import KafkaConsumer
        except ImportError:
            logger.error("kafka-python is not installed. Install with: pip install kafka-python")
            return

        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers.split(','),
                group_id=self.group_id,
                auto_offset_reset=self.auto_offset_reset,
                enable_auto_commit=True,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')) if v else None,
                consumer_timeout_ms=1000,  # 1秒超时，让线程能检查 _running 标志
            )
            logger.info(f"KafkaConsumer started: topic={topic}, group_id={self.group_id}")

            while self._running:
                try:
                    records = consumer.poll(timeout_ms=500, max_records=100)
                    if not records:
                        continue
                    for tp, messages in records.items():
                        for msg in messages:
                            try:
                                message = {
                                    'topic': msg.topic,
                                    'partition': msg.partition,
                                    'offset': msg.offset,
                                    'key': msg.key.decode('utf-8') if isinstance(msg.key, bytes) else msg.key,
                                    'value': msg.value,
                                    'timestamp': msg.timestamp,
                                }
                                callback(message)
                            except Exception as e:
                                logger.error(f"Error processing Kafka message (topic={topic}, offset={msg.offset}): {e}")
                except Exception as e:
                    if self._running:
                        logger.error(f"Kafka consumer poll error (topic={topic}): {e}")

            consumer.close()
            logger.info(f"KafkaConsumer stopped: topic={topic}")

        except Exception as e:
            logger.error(f"Failed to start KafkaConsumer for topic={topic}: {e}")

    def stop_consuming(self) -> None:
        """停止所有消费者线程。"""
        self._running = False
        for thread in self._consumer_threads:
            if thread.is_alive():
                thread.join(timeout=5)
        self._consumer_threads.clear()
        logger.info("All Kafka consumers stopped")

    def close(self) -> None:
        """关闭生产者和消费者。"""
        self.stop_consuming()
        if self._producer is not None:
            try:
                self._producer.flush(timeout=5)
                self._producer.close(timeout=5)
            except Exception as e:
                logger.error(f"Error closing KafkaProducer: {e}")
            finally:
                self._producer = None


# 全局单例
kafka_client = KafkaClient()


def init_kafka(config: dict) -> None:
    """从配置初始化 Kafka 客户端。

    Args:
        config: 应用配置字典，从 application.yml 读取
    """
    kafka_config = config.get('spring', {}).get('kafka', {})
    if not kafka_config:
        return

    bootstrap = kafka_config.get('bootstrap-servers', 'localhost:9092')
    consumer_cfg = kafka_config.get('consumer', {})
    group_id = consumer_cfg.get('group-id', 'default-group')
    auto_offset_reset = consumer_cfg.get('auto-offset-reset', 'latest')

    kafka_client.configure(
        bootstrap_servers=bootstrap,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
    )
    logger.info(f"Kafka configured: bootstrap={bootstrap}, group_id={group_id}")
