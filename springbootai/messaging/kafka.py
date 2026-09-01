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
import asyncio
import inspect
import time
import re
from typing import Any, Callable, Dict, List, Optional

from springbootai.logging.context import safe_log_field

logger = logging.getLogger("Spring.Messaging.Kafka")
_TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,249}$")


def _validate_topic(topic: str) -> str:
    if not isinstance(topic, str):
        raise ValueError("Invalid Kafka topic name")
    value = topic
    if value in {".", ".."} or not _TOPIC_PATTERN.fullmatch(value):
        raise ValueError("Invalid Kafka topic name")
    return value


def _validate_dead_letter_suffix(value: str) -> str:
    suffix = str(value or "")
    if suffix and (len(suffix) > 64
                   or not re.fullmatch(r"[A-Za-z0-9._-]+", suffix)):
        raise ValueError("Invalid Kafka dead-letter topic suffix")
    return suffix


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
                 auto_offset_reset: str = "latest",
                 max_processing_retries: int = 3,
                 retry_backoff: float = 0.25,
                 dead_letter_suffix: str = ".DLQ",
                 consumer_start_timeout: float = 5.0):
        if hasattr(self, '_initialized'):
            return
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.max_processing_retries = max(0, int(max_processing_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.dead_letter_suffix = _validate_dead_letter_suffix(
            dead_letter_suffix)
        self.consumer_start_timeout = max(
            0.1, min(float(consumer_start_timeout), 60.0))
        self._producer = None
        self._consumers: Dict[str, Callable] = {}
        self._consumer_groups: Dict[str, str] = {}
        self._consumer_threads: List[threading.Thread] = []
        self._running = False
        self._consumer_stop_event = threading.Event()
        self._producer_lock = threading.RLock()
        self._initialized = True

    def configure(self, bootstrap_servers: Optional[str] = None,
                  group_id: Optional[str] = None,
                  auto_offset_reset: Optional[str] = None,
                  max_processing_retries: Optional[int] = None,
                  retry_backoff: Optional[float] = None,
                  dead_letter_suffix: Optional[str] = None,
                  consumer_start_timeout: Optional[float] = None) -> None:
        """重新配置单例的 Kafka 连接参数（读取配置后调用）。"""
        self.close()
        if bootstrap_servers is not None:
            self.bootstrap_servers = bootstrap_servers
        if group_id is not None:
            self.group_id = group_id
        if auto_offset_reset is not None:
            self.auto_offset_reset = auto_offset_reset
        if max_processing_retries is not None:
            self.max_processing_retries = max(
                0, min(int(max_processing_retries), 100))
        if retry_backoff is not None:
            self.retry_backoff = max(0.0, min(float(retry_backoff), 60.0))
        if dead_letter_suffix is not None:
            self.dead_letter_suffix = _validate_dead_letter_suffix(
                dead_letter_suffix)
        if consumer_start_timeout is not None:
            self.consumer_start_timeout = max(
                0.1, min(float(consumer_start_timeout), 60.0))
        self._producer = None
        self._consumers.clear()
        self._consumer_groups.clear()
        self._consumer_threads.clear()
        self._running = False

    def _get_producer(self):
        """获取或创建 KafkaProducer（惰性初始化）。"""
        with self._producer_lock:
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
                    max_in_flight_requests_per_connection=1,
                )
                logger.info("KafkaProducer connected")
                return self._producer
            except ImportError:
                raise ImportError(
                    "kafka-python is not installed. Install with: pip install kafka-python"
                )
            except Exception as exc:
                logger.error(
                    "Failed to create KafkaProducer error_type=%s",
                    type(exc).__name__,
                )
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
        # 安全校验：topic 名不能包含特殊字符
        topic = _validate_topic(topic)
        producer = self._get_producer()

        if headers is not None and not isinstance(headers, dict):
            raise TypeError("Kafka headers must be a mapping")
        kafka_headers = []
        for header_name, header_value in (headers or {}).items():
            if (not isinstance(header_name, str) or not header_name
                    or any(ord(char) < 32 for char in header_name)):
                raise ValueError("Invalid Kafka header name")
            if isinstance(header_value, str):
                encoded_value = header_value.encode("utf-8")
            elif isinstance(header_value, bytes):
                encoded_value = header_value
            else:
                raise TypeError("Kafka header values must be str or bytes")
            kafka_headers.append((header_name, encoded_value))
        future = producer.send(topic, value=value, key=key, headers=kafka_headers)
        logger.debug(
            "Sent message to topic=%s key=%s",
            safe_log_field(topic), safe_log_field(key),
        )
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
        if not callable(callback):
            raise TypeError("Kafka listener callback must be callable")
        normalized_topics = [_validate_topic(topic) for topic in topics]
        for topic in normalized_topics:
            self._consumers[topic] = callback
            self._consumer_groups[topic] = group_id or self.group_id
            logger.info(
                "Registered Kafka listener topic=%s group_id=%s",
                safe_log_field(topic),
                safe_log_field(group_id or self.group_id),
            )

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

        if any(isinstance(thread, threading.Thread) and thread.is_alive()
               for thread in self._consumer_threads):
            raise RuntimeError(
                "Previous Kafka consumer threads have not stopped")
        self._consumer_threads.clear()
        self._consumer_stop_event = threading.Event()
        stop_event = self._consumer_stop_event
        self._running = True
        startup_states = []

        for topic in target_topics:
            callback = self._consumers.get(topic)
            if callback is None:
                logger.warning(
                    "No callback registered for topic=%s",
                    safe_log_field(topic),
                )
                continue

            startup_ready = threading.Event()
            startup_state: Dict[str, Any] = {"error": None}
            thread = threading.Thread(
                target=self._consume_loop,
                args=(topic, callback, self._consumer_groups.get(
                    topic, self.group_id), stop_event, startup_ready,
                    startup_state),
                daemon=True,
                name=f"kafka-consumer-{topic}",
            )
            thread.start()
            self._consumer_threads.append(thread)
            startup_states.append(
                (topic, thread, startup_ready, startup_state))
            logger.info(
                "Started Kafka consumer thread topic=%s",
                safe_log_field(topic),
            )
        if not self._consumer_threads:
            self._running = False
            return

        deadline = time.monotonic() + self.consumer_start_timeout
        startup_error = None
        for topic, _thread, ready, state in startup_states:
            remaining = max(0.0, deadline - time.monotonic())
            if not ready.wait(timeout=remaining):
                startup_error = TimeoutError(
                    f"Kafka consumer startup timed out for topic {topic}")
                break
            if state.get("error") is not None:
                startup_error = state["error"]
                break
        if startup_error is not None:
            self._running = False
            stop_event.set()
            for _topic, thread, _ready, _state in startup_states:
                if thread.is_alive():
                    thread.join(timeout=0.1)
            self._consumer_threads = [
                thread for thread in self._consumer_threads
                if thread.is_alive()
            ]
            raise RuntimeError("Kafka consumer failed to start") from startup_error

    @staticmethod
    def _invoke_callback(callback: Callable, message: Dict[str, Any]) -> None:
        result = callback(message)
        if inspect.isawaitable(result):
            async def await_result():
                return await result
            asyncio.run(await_result())

    @staticmethod
    def _commit_message(consumer, topic_partition, offset: int) -> None:
        try:
            from kafka.structs import OffsetAndMetadata
        except ImportError:
            # Compatibility for light-weight test doubles.  Real kafka-python
            # always provides OffsetAndMetadata.
            consumer.commit()
        else:
            consumer.commit({
                topic_partition: OffsetAndMetadata(offset + 1, None)
            })

    def _dead_letter(self, topic: str, message: Dict[str, Any],
                     error: BaseException) -> bool:
        if not self.dead_letter_suffix:
            return False
        envelope = {
            "source_topic": topic,
            "partition": message.get("partition"),
            "offset": message.get("offset"),
            "key": message.get("key"),
            "value": message.get("value"),
            "error_type": type(error).__name__,
        }
        try:
            self.send_and_wait(
                f"{topic}{self.dead_letter_suffix}", envelope,
                key=message.get("key"), timeout=10.0,
            )
            return True
        except Exception as exc:
            logger.error(
                "Kafka dead-letter publish failed topic=%s error_type=%s",
                topic, type(exc).__name__,
            )
            return False

    def _consume_loop(self, topic: str, callback: Callable,
                      group_id: Optional[str] = None,
                      stop_event: Optional[threading.Event] = None,
                      startup_ready: Optional[threading.Event] = None,
                      startup_state: Optional[Dict[str, Any]] = None) -> None:
        """消费者轮询循环（在独立线程中运行）。"""
        consumer = None
        startup_ready = startup_ready or threading.Event()
        startup_state = startup_state if startup_state is not None else {}
        try:
            from kafka import KafkaConsumer
        except ImportError as exc:
            startup_state["error"] = exc
            startup_ready.set()
            logger.error("kafka-python is not installed. Install with: pip install kafka-python")
            return

        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers.split(','),
                group_id=group_id or self.group_id,
                auto_offset_reset=self.auto_offset_reset,
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')) if v else None,
                consumer_timeout_ms=1000,  # 1秒超时，让线程能检查 _running 标志
            )
            # kafka-python's constructor usually bootstraps metadata.  Calling
            # topics() when available also forces lazy clients to verify broker
            # connectivity before start_consuming reports success.
            topics_probe = getattr(consumer, "topics", None)
            if callable(topics_probe):
                topics_probe()
            startup_ready.set()
            logger.info(
                "KafkaConsumer started: topic=%s, group_id=%s",
                topic, group_id or self.group_id,
            )

            stop_event = stop_event or self._consumer_stop_event
            while not stop_event.is_set():
                try:
                    records = consumer.poll(timeout_ms=500, max_records=100)
                    if not records:
                        continue
                    for tp, messages in records.items():
                        for msg in messages:
                            message = {
                                'topic': msg.topic,
                                'partition': msg.partition,
                                'offset': msg.offset,
                                'key': msg.key.decode('utf-8') if isinstance(msg.key, bytes) else msg.key,
                                'value': msg.value,
                                'timestamp': msg.timestamp,
                            }
                            last_error = None
                            for attempt in range(
                                    self.max_processing_retries + 1):
                                try:
                                    self._invoke_callback(callback, message)
                                    self._commit_message(
                                        consumer, tp, msg.offset)
                                    last_error = None
                                    break
                                except Exception as exc:
                                    last_error = exc
                                    logger.warning(
                                        "Kafka message processing failed "
                                        "topic=%s partition=%s offset=%s "
                                        "attempt=%s error_type=%s",
                                        topic, msg.partition, msg.offset,
                                        attempt + 1, type(exc).__name__,
                                    )
                                    if attempt < self.max_processing_retries:
                                        if stop_event.wait(min(
                                            self.retry_backoff * (2 ** attempt),
                                            60.0,
                                        )):
                                            break
                            if last_error is not None:
                                if stop_event.is_set():
                                    consumer.seek(tp, msg.offset)
                                    break
                                if self._dead_letter(
                                        topic, message, last_error):
                                    self._commit_message(
                                        consumer, tp, msg.offset)
                                else:
                                    # Preserve at-least-once delivery.  Reset
                                    # this partition to the failed record and
                                    # stop processing the already-polled tail.
                                    consumer.seek(tp, msg.offset)
                                    break
                except Exception as exc:
                    if not stop_event.is_set():
                        logger.error(
                            "Kafka consumer poll error topic=%s error_type=%s",
                            topic, type(exc).__name__,
                        )
                        stop_event.wait(
                            min(max(self.retry_backoff, 0.05), 1.0))

        except Exception as exc:
            if not startup_ready.is_set():
                startup_state["error"] = exc
                startup_ready.set()
            logger.error(
                "Failed to start KafkaConsumer topic=%s error_type=%s",
                topic, type(exc).__name__,
            )
        finally:
            startup_ready.set()
            if consumer is not None:
                try:
                    consumer.close()
                except Exception as exc:
                    logger.warning(
                        "Kafka consumer close failed topic=%s error_type=%s",
                        safe_log_field(topic), type(exc).__name__,
                    )
            logger.info(
                "KafkaConsumer stopped topic=%s", safe_log_field(topic))
            current = threading.current_thread()
            if all(thread is current or not thread.is_alive()
                   for thread in list(self._consumer_threads)):
                self._running = False

    def stop_consuming(self) -> None:
        """停止所有消费者线程。"""
        self._running = False
        self._consumer_stop_event.set()
        alive = []
        for thread in self._consumer_threads:
            if not isinstance(thread, threading.Thread):
                logger.warning("Discarding invalid Kafka consumer thread handle")
                continue
            if thread.is_alive():
                thread.join(timeout=5)
            if thread.is_alive():
                alive.append(thread)
        self._consumer_threads = alive
        if alive:
            names = ", ".join(thread.name for thread in alive)
            logger.error(
                "Kafka consumer threads did not stop within timeout threads=%s",
                safe_log_field(names),
            )
            raise RuntimeError("Kafka consumer threads did not stop within timeout")
        logger.info("All Kafka consumers stopped")

    def close(self) -> None:
        """关闭生产者和消费者。"""
        self.stop_consuming()
        with self._producer_lock:
            if self._producer is not None:
                try:
                    self._producer.flush(timeout=5)
                    self._producer.close(timeout=5)
                except Exception as exc:
                    logger.error(
                        "Error closing KafkaProducer error_type=%s",
                        type(exc).__name__,
                    )
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
    max_processing_retries = consumer_cfg.get('max-processing-retries', 3)
    retry_backoff = consumer_cfg.get('retry-backoff', 0.25)
    dead_letter_suffix = consumer_cfg.get('dead-letter-suffix', '.DLQ')
    consumer_start_timeout = consumer_cfg.get('start-timeout', 5.0)

    kafka_client.configure(
        bootstrap_servers=bootstrap,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        max_processing_retries=max_processing_retries,
        retry_backoff=retry_backoff,
        dead_letter_suffix=dead_letter_suffix,
        consumer_start_timeout=consumer_start_timeout,
    )
    logger.info(
        "Kafka configured bootstrap=%s group_id=%s",
        safe_log_field(bootstrap), safe_log_field(group_id),
    )
