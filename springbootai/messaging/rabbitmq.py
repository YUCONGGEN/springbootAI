"""
消息队列模块
集成RabbitMQ实现异步消息处理
"""
import pika
import asyncio
import inspect
import json
import logging
import math
import threading
import queue
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Callable, Dict, Any, Optional

from springbootai.logging.context import safe_log_field

logger = logging.getLogger("Spring.Messaging.RabbitMQ")


class RabbitMQPublishOutcomeUnknown(TimeoutError):
    """The publish entered the broker call but no confirmation was observed."""


class RabbitMQClient:
    """RabbitMQ客户端"""

    # RabbitMQ 是可选组件。连接参数显式使用有限超时和单次尝试，避免
    # ``rabbitmq.enabled=true`` 但服务未启动时，框架在 pika 默认重试中
    # 停留数十秒。长连接保活仍由 heartbeat/blocked_connection_timeout 控制。
    DEFAULT_CONNECTION_TIMEOUT_SECONDS = 5.0
    MAX_CONNECTION_TIMEOUT_SECONDS = 60.0
    DEFAULT_CONNECTION_ATTEMPTS = 1
    MAX_CONNECTION_ATTEMPTS = 10
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, host: str = "localhost", port: int = 5672,
                 username: str = "guest", password: str = "guest",
                 virtual_host: str = "/", connection_timeout: Optional[float] = None,
                 socket_timeout: Optional[float] = None,
                 stack_timeout: Optional[float] = None,
                 connection_attempts: int = DEFAULT_CONNECTION_ATTEMPTS,
                 retry_delay: float = 0.0,
                 blocked_connection_timeout: Optional[float] = 300.0,
                 timeout: Optional[float] = None,
                 publish_timeout: float = 10.0,
                 publish_queue_size: int = 1000,
                 max_delivery_attempts: int = 5,
                 consumer_retry_delay: float = 0.25):
        if hasattr(self, '_initialized'):
            return
        if connection_timeout is None and timeout is not None:
            connection_timeout = timeout
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.virtual_host = virtual_host
        self.connection_timeout = self._normalize_timeout(
            self.DEFAULT_CONNECTION_TIMEOUT_SECONDS
            if connection_timeout is None else connection_timeout
        )
        self.socket_timeout = self._normalize_timeout(
            self.connection_timeout if socket_timeout is None else socket_timeout
        )
        self.stack_timeout = self._normalize_timeout(
            self.connection_timeout if stack_timeout is None else stack_timeout
        )
        self.connection_attempts = self._normalize_attempts(connection_attempts)
        self.retry_delay = self._normalize_delay(retry_delay)
        self.blocked_connection_timeout = self._normalize_optional_timeout(
            blocked_connection_timeout
        )
        self.publish_timeout = self._normalize_timeout(publish_timeout)
        self.publish_queue_size = max(1, min(int(publish_queue_size), 100000))
        self.max_delivery_attempts = max(
            1, min(int(max_delivery_attempts), 100))
        self.consumer_retry_delay = self._normalize_delay(consumer_retry_delay)
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[pika.channel.Channel] = None
        self._consumers: Dict[str, Callable] = {}
        self._consumer_options: Dict[str, Dict[str, Any]] = {}
        self._consumer_thread: Optional[threading.Thread] = None
        self._consumer_connection: Optional[pika.BlockingConnection] = None
        self._consumer_channel: Optional[pika.channel.Channel] = None
        self._consumer_ready = threading.Event()
        self._consumer_start_error: Optional[BaseException] = None
        self._admin_lock = threading.RLock()
        self._publisher_lock = threading.RLock()
        self._publisher_queue: queue.Queue = queue.Queue(
            maxsize=self.publish_queue_size)
        self._publisher_thread: Optional[threading.Thread] = None
        self._publisher_stop = threading.Event()
        self._initialized = True

    def configure(self, host: Optional[str] = None, port: Optional[int] = None,
                  username: Optional[str] = None, password: Optional[str] = None,
                  virtual_host: Optional[str] = None,
                  connection_timeout: Optional[float] = None,
                  socket_timeout: Optional[float] = None,
                  stack_timeout: Optional[float] = None,
                  connection_attempts: Optional[int] = None,
                  retry_delay: Optional[float] = None,
                  blocked_connection_timeout: Optional[float] = None,
                  timeout: Optional[float] = None,
                  timeout_seconds: Optional[float] = None,
                  publish_timeout: Optional[float] = None,
                  publish_queue_size: Optional[int] = None,
                  max_delivery_attempts: Optional[int] = None,
                  consumer_retry_delay: Optional[float] = None) -> None:
        """重新配置单例的 RabbitMQ 连接参数（读取配置后调用）。

        ``RabbitMQClient`` 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止
        后续 ``__init__`` 更新参数。``init_rabbitmq`` 读取 ``application.yml``
        的 ``rabbitmq.*`` 后，必须通过本方法重新配置，否则连接参数停留在默认值。

        重置已建立的连接与消费者，强制下次 ``connect()`` 重建。

        Args:
            host: 主机，None 表示保留原值
            port: 端口，None 表示保留原值
            username: 用户名，None 表示保留原值
            password: 密码，None 表示保留原值
            virtual_host: 虚拟主机，None 表示保留原值
            connection_timeout: 建立连接时的默认超时（秒），None 表示保留原值
            socket_timeout: TCP 连接超时（秒），None 表示保留原值
            stack_timeout: AMQP 握手超时（秒），None 表示保留原值
            connection_attempts: pika 连接尝试次数，None 表示保留原值
            retry_delay: 连接重试间隔（秒），None 表示保留原值
            blocked_connection_timeout: Broker blocked 状态超时（秒）；传入
                ``None`` 表示保留原值，使用 0 可禁用该保护
            timeout/timeout_seconds: ``connection_timeout`` 的兼容别名；
                同时提供时按 ``connection_timeout`` 优先
        """
        # 关闭旧连接，清理消费者状态
        self.close()
        if host is not None:
            self.host = host
        if port is not None:
            self.port = int(port)
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        if virtual_host is not None:
            self.virtual_host = virtual_host
        if connection_timeout is None:
            connection_timeout = timeout if timeout is not None else timeout_seconds
        if connection_timeout is not None:
            self.connection_timeout = self._normalize_timeout(connection_timeout)
            # 只调整总超时时，同步未显式覆盖的 socket/握手超时；如果调用方
            # 同时传入细分字段，则保留它们的精细配置。
            if socket_timeout is None:
                self.socket_timeout = self.connection_timeout
            if stack_timeout is None:
                self.stack_timeout = self.connection_timeout
        if socket_timeout is not None:
            self.socket_timeout = self._normalize_timeout(socket_timeout)
        if stack_timeout is not None:
            self.stack_timeout = self._normalize_timeout(stack_timeout)
        if connection_attempts is not None:
            self.connection_attempts = self._normalize_attempts(connection_attempts)
        if retry_delay is not None:
            self.retry_delay = self._normalize_delay(retry_delay)
        if blocked_connection_timeout is not None:
            self.blocked_connection_timeout = self._normalize_optional_timeout(
                blocked_connection_timeout
            )
        if publish_timeout is not None:
            self.publish_timeout = self._normalize_timeout(publish_timeout)
        if publish_queue_size is not None:
            self.publish_queue_size = max(
                1, min(int(publish_queue_size), 100000))
        if max_delivery_attempts is not None:
            self.max_delivery_attempts = max(
                1, min(int(max_delivery_attempts), 100))
        if consumer_retry_delay is not None:
            self.consumer_retry_delay = self._normalize_delay(
                consumer_retry_delay)
        self._connection = None
        self._channel = None
        self._consumers.clear()
        self._consumer_options.clear()
        self._consumer_thread = None
        self._consumer_connection = None
        self._consumer_channel = None
        self._consumer_ready = threading.Event()
        self._publisher_queue = queue.Queue(maxsize=self.publish_queue_size)
        self._publisher_thread = None
        self._publisher_stop = threading.Event()

    @classmethod
    def _normalize_timeout(cls, value: Any) -> float:
        """返回有限、正数的连接超时；非法配置回退安全默认值。"""
        if isinstance(value, dict):
            value = value.get("seconds", value.get("timeout", value.get("value")))
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            timeout = cls.DEFAULT_CONNECTION_TIMEOUT_SECONDS
        if not math.isfinite(timeout) or timeout <= 0:
            timeout = cls.DEFAULT_CONNECTION_TIMEOUT_SECONDS
        return min(timeout, cls.MAX_CONNECTION_TIMEOUT_SECONDS)

    @classmethod
    def _normalize_optional_timeout(cls, value: Any) -> Optional[float]:
        """规范化可选超时；``None`` 保持 pika 默认行为，0 表示不限制。"""
        if value is None:
            return None
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return cls._normalize_timeout(value)
        if not math.isfinite(timeout) or timeout < 0:
            return cls.DEFAULT_CONNECTION_TIMEOUT_SECONDS
        if timeout == 0:
            return 0.0
        return min(timeout, cls.MAX_CONNECTION_TIMEOUT_SECONDS * 5)

    @classmethod
    def _normalize_attempts(cls, value: Any) -> int:
        try:
            attempts = int(value)
        except (TypeError, ValueError):
            attempts = cls.DEFAULT_CONNECTION_ATTEMPTS
        return max(1, min(attempts, cls.MAX_CONNECTION_ATTEMPTS))

    @staticmethod
    def _normalize_delay(value: Any) -> float:
        try:
            delay = float(value)
        except (TypeError, ValueError):
            delay = 0.0
        if not math.isfinite(delay) or delay < 0:
            return 0.0
        return min(delay, 60.0)
    
    def _connection_parameters(self):
        credentials = pika.PlainCredentials(self.username, self.password)
        parameter_kwargs = dict(
            host=self.host,
            port=self.port,
            credentials=credentials,
            virtual_host=self.virtual_host,
            heartbeat=600,
            blocked_connection_timeout=self.blocked_connection_timeout,
            connection_attempts=self.connection_attempts,
            retry_delay=self.retry_delay,
            socket_timeout=self.socket_timeout,
            stack_timeout=self.stack_timeout,
        )
        try:
            return pika.ConnectionParameters(**parameter_kwargs)
        except TypeError:
            for key in ("stack_timeout", "retry_delay", "connection_attempts"):
                parameter_kwargs.pop(key, None)
            try:
                return pika.ConnectionParameters(**parameter_kwargs)
            except TypeError:
                parameter_kwargs.pop("socket_timeout", None)
                return pika.ConnectionParameters(**parameter_kwargs)

    def _open_connection(self):
        return pika.BlockingConnection(self._connection_parameters())

    @staticmethod
    def _validate_name(value: str, kind: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Invalid RabbitMQ {kind} name")
        name = value
        if ((not name and not allow_empty) or len(name.encode("utf-8")) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            raise ValueError(f"Invalid RabbitMQ {kind} name")
        return name

    def connect(self) -> None:
        """Open the administration connection used during application setup."""
        with self._admin_lock:
            if (self._connection is not None
                    and not getattr(self._connection, "is_closed", True)
                    and self._channel is not None
                    and getattr(self._channel, "is_open", True)):
                return
            try:
                self._connection = self._open_connection()
                self._channel = self._connection.channel()
                logger.info("Connected to RabbitMQ: %s:%s", self.host, self.port)
            except Exception as exc:
                logger.error(
                    "Failed to connect to RabbitMQ error_type=%s",
                    type(exc).__name__,
                )
                failed_connection = self._connection
                self._connection = None
                self._channel = None
                if failed_connection is not None:
                    try:
                        if not getattr(failed_connection, "is_closed", True):
                            failed_connection.close()
                    except Exception:
                        logger.debug(
                            "Unable to close failed RabbitMQ connection",
                            exc_info=True,
                        )
                raise
    
    def get_channel(self) -> pika.channel.Channel:
        """获取通道"""
        with self._admin_lock:
            if (self._channel is None
                    or not getattr(self._channel, "is_open", True)):
                self.connect()
            return self._channel
    
    def declare_queue(self, queue_name: str, durable: bool = True, 
                      exclusive: bool = False, auto_delete: bool = False) -> None:
        """
        声明队列
        
        Args:
            queue_name: 队列名称
            durable: 是否持久化
            exclusive: 是否排他
            auto_delete: 是否自动删除
        """
        queue_name = self._validate_name(queue_name, "queue")
        with self._admin_lock:
            channel = self.get_channel()
            channel.queue_declare(
                queue=queue_name,
                durable=durable,
                exclusive=exclusive,
                auto_delete=auto_delete,
            )
        logger.info("Declared queue=%s", safe_log_field(queue_name))
    
    def declare_exchange(self, exchange_name: str, exchange_type: str = "direct",
                         durable: bool = True) -> None:
        """
        声明交换机
        
        Args:
            exchange_name: 交换机名称
            exchange_type: 交换机类型
            durable: 是否持久化
        """
        exchange_name = self._validate_name(
            exchange_name, "exchange", allow_empty=True)
        with self._admin_lock:
            channel = self.get_channel()
            channel.exchange_declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                durable=durable,
            )
        logger.info("Declared exchange=%s", safe_log_field(exchange_name))
    
    def bind_queue(self, queue_name: str, exchange_name: str, routing_key: str = "") -> None:
        """
        绑定队列到交换机
        
        Args:
            queue_name: 队列名称
            exchange_name: 交换机名称
            routing_key: 路由键
        """
        queue_name = self._validate_name(queue_name, "queue")
        exchange_name = self._validate_name(exchange_name, "exchange")
        routing_key = self._validate_name(
            routing_key, "routing key", allow_empty=True)
        with self._admin_lock:
            channel = self.get_channel()
            channel.queue_bind(
                queue=queue_name,
                exchange=exchange_name,
                routing_key=routing_key,
            )
        logger.info(
            "Bound queue=%s exchange=%s",
            safe_log_field(queue_name), safe_log_field(exchange_name),
        )

    def _ensure_publisher(self) -> None:
        with self._publisher_lock:
            if (self._publisher_thread is not None
                    and self._publisher_thread.is_alive()):
                return
            self._publisher_stop.clear()
            publisher_queue = self._publisher_queue
            stop_event = self._publisher_stop
            self._publisher_thread = threading.Thread(
                target=self._publisher_loop,
                args=(publisher_queue, stop_event),
                name="SpringRabbitPublisher",
                daemon=True,
            )
            self._publisher_thread.start()

    def _publisher_loop(self, publisher_queue, stop_event) -> None:
        """Own the publisher connection on exactly one thread.

        ``BlockingConnection`` and its channels are not shared with request or
        consumer threads.  Every caller waits for broker publisher-confirm
        completion through a ``Future``.
        """
        connection = None
        channel = None
        try:
            while not stop_event.is_set() or not publisher_queue.empty():
                try:
                    item = publisher_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if item is None:
                        return
                    future = item["future"]
                    state_lock = item["state_lock"]
                    with state_lock:
                        if (item["state"] == "cancelled"
                                or future.cancelled()
                                or time.monotonic() >= item["deadline"]):
                            item["state"] = "cancelled"
                            if not future.done():
                                future.set_exception(TimeoutError(
                                    "RabbitMQ publish expired before broker send"))
                            continue
                        item["state"] = "connecting"

                    connection_error = None
                    for attempt in range(2):
                        try:
                            if (connection is None
                                    or getattr(connection, "is_closed", True)
                                    or channel is None
                                    or not getattr(channel, "is_open", True)):
                                connection = self._open_connection()
                                channel = connection.channel()
                                channel.confirm_delivery()
                            connection_error = None
                            break
                        except Exception as exc:
                            connection_error = exc
                            if connection is not None:
                                try:
                                    if not getattr(connection, "is_closed", True):
                                        connection.close()
                                except Exception:
                                    pass
                            connection = None
                            channel = None
                            if (attempt == 0
                                    and time.monotonic() < item["deadline"]):
                                continue
                    if connection_error is not None:
                        with state_lock:
                            item["state"] = "completed"
                        if not future.done():
                            future.set_exception(connection_error)
                        continue
                    if channel is None:
                        channel_error = RuntimeError(
                            "RabbitMQ publisher channel was not initialized")
                        with state_lock:
                            item["state"] = "completed"
                        if not future.done():
                            future.set_exception(channel_error)
                        continue

                    with state_lock:
                        if (item["state"] == "cancelled"
                                or future.cancelled()
                                or time.monotonic() >= item["deadline"]):
                            item["state"] = "cancelled"
                            if not future.done():
                                future.set_exception(TimeoutError(
                                    "RabbitMQ publish expired before broker send"))
                            continue
                        # Once this state is visible, the broker call may have
                        # accepted the message even if the caller later times out.
                        item["state"] = "sending"
                    try:
                        confirmed = channel.basic_publish(
                            exchange=item["exchange"],
                            routing_key=item["routing_key"],
                            body=item["body"],
                            properties=item["properties"],
                            mandatory=True,
                        )
                        if confirmed is False:
                            raise RuntimeError(
                                "RabbitMQ broker did not confirm publish")
                    except Exception as exc:
                        outcome_error = RabbitMQPublishOutcomeUnknown(
                            "RabbitMQ publish outcome is unknown")
                        outcome_error.__cause__ = exc
                        with state_lock:
                            item["state"] = "completed"
                        if not future.done():
                            future.set_exception(outcome_error)
                    else:
                        with state_lock:
                            item["state"] = "completed"
                        if not future.done():
                            future.set_result(None)
                finally:
                    publisher_queue.task_done()
        finally:
            if connection is not None:
                try:
                    if not getattr(connection, "is_closed", True):
                        connection.close()
                except Exception:
                    logger.debug(
                        "Unable to close RabbitMQ publisher connection",
                        exc_info=True,
                    )
    
    def publish(self, exchange_name: str, routing_key: str, body: Any,
                content_type: str = "application/json", persistent: bool = True) -> None:
        """
        发布消息
        
        Args:
            exchange_name: 交换机名称
            routing_key: 路由键
            body: 消息体
            content_type: 内容类型
            persistent: 是否持久化
        """
        exchange_name = self._validate_name(
            exchange_name, "exchange", allow_empty=True)
        routing_key = self._validate_name(
            routing_key, "routing key", allow_empty=True)
        # 序列化消息体
        if isinstance(body, dict):
            body_str = json.dumps(body)
        else:
            body_str = str(body)

        future: Future[Any] = Future()
        state_lock = threading.Lock()
        item = {
            "future": future,
            "state_lock": state_lock,
            "state": "queued",
            "deadline": time.monotonic() + self.publish_timeout,
            "exchange": exchange_name,
            "routing_key": routing_key,
            "body": body_str,
            "properties": pika.BasicProperties(
                content_type=content_type,
                delivery_mode=2 if persistent else 1,
            ),
        }
        with self._publisher_lock:
            self._ensure_publisher()
            try:
                self._publisher_queue.put(item, timeout=self.publish_timeout)
            except queue.Full as exc:
                raise TimeoutError("RabbitMQ publisher queue is full") from exc
        try:
            remaining = max(0.0, item["deadline"] - time.monotonic())
            future.result(timeout=remaining)
        except RabbitMQPublishOutcomeUnknown:
            raise
        except FutureTimeoutError as exc:
            with state_lock:
                state = item["state"]
                if state != "sending":
                    item["state"] = "cancelled"
                    future.cancel()
            if state == "sending":
                raise RabbitMQPublishOutcomeUnknown(
                    "RabbitMQ publisher confirm timed out after broker send began"
                ) from exc
            raise TimeoutError(
                "RabbitMQ publisher confirm timed out; publish was cancelled"
            ) from exc
        logger.debug(
            "Published message exchange=%s routing_key=%s",
            safe_log_field(exchange_name), safe_log_field(routing_key),
        )
    
    def publish_to_queue(self, queue_name: str, body: Any, 
                         content_type: str = "application/json", 
                         persistent: bool = True) -> None:
        """
        直接发布消息到队列
        
        Args:
            queue_name: 队列名称
            body: 消息体
            content_type: 内容类型
            persistent: 是否持久化
        """
        self.publish(
            exchange_name="",
            routing_key=queue_name,
            body=body,
            content_type=content_type,
            persistent=persistent,
        )
    
    def consume(self, queue_name: str, callback: Callable, 
                auto_ack: bool = False, prefetch_count: int = 1) -> None:
        """
        消费消息
        
        Args:
            queue_name: 队列名称
            callback: 回调函数
            auto_ack: 是否自动确认
            prefetch_count: 预取数量
        """
        queue_name = self._validate_name(queue_name, "queue")
        if not callable(callback):
            raise TypeError("RabbitMQ callback must be callable")
        self._consumers[queue_name] = callback
        self._consumer_options[queue_name] = {
            "auto_ack": bool(auto_ack),
            "prefetch_count": max(1, int(prefetch_count)),
        }
        logger.info(
            "Registered RabbitMQ consumer queue=%s",
            safe_log_field(queue_name),
        )
    
    def _create_message_handler(self, callback: Callable,
                                auto_ack: bool = False,
                                queue_name: str = "") -> Callable:
        """创建消息处理器"""
        def handler(ch, method, properties, body):
            try:
                # 解析消息体
                try:
                    message = json.loads(body) if body else None
                except json.JSONDecodeError:
                    message = body.decode('utf-8') if body else None
                
                # 调用回调
                result = callback(message)
                if inspect.isawaitable(result):
                    async def await_result():
                        return await result
                    asyncio.run(await_result())
                
                # 手动确认
                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                
                logger.debug(
                    "Processed RabbitMQ message queue=%s",
                    safe_log_field(queue_name),
                )
            except Exception as exc:
                logger.warning(
                    "RabbitMQ message processing failed queue=%s "
                    "error_type=%s",
                    safe_log_field(queue_name), type(exc).__name__,
                )
                if auto_ack:
                    return

                raw_headers = getattr(properties, "headers", None) or {}
                headers = dict(raw_headers)
                try:
                    attempt = int(headers.get(
                        "x-springbootai-delivery-attempt", 0)) + 1
                except (TypeError, ValueError):
                    attempt = 1
                headers["x-springbootai-delivery-attempt"] = attempt
                try:
                    if properties is None:
                        properties = pika.BasicProperties(headers=headers)
                    else:
                        properties.headers = headers
                    if attempt >= self.max_delivery_attempts:
                        headers["x-springbootai-error-type"] = type(exc).__name__
                        dlq_name = f"{queue_name}.DLQ"
                        ch.queue_declare(queue=dlq_name, durable=True)
                        confirmed = ch.basic_publish(
                            exchange="",
                            routing_key=dlq_name,
                            body=body,
                            properties=properties,
                            mandatory=True,
                        )
                        if confirmed is False:
                            raise RuntimeError(
                                "RabbitMQ dead-letter publish not confirmed")
                    else:
                        if self.consumer_retry_delay:
                            import time as _time
                            _time.sleep(min(
                                self.consumer_retry_delay * (2 ** (attempt - 1)),
                                60.0,
                            ))
                        confirmed = ch.basic_publish(
                            exchange=getattr(method, "exchange", ""),
                            routing_key=getattr(
                                method, "routing_key", queue_name),
                            body=body,
                            properties=properties,
                            mandatory=True,
                        )
                        if confirmed is False:
                            raise RuntimeError(
                                "RabbitMQ retry publish not confirmed")
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as publish_error:
                    logger.error(
                        "RabbitMQ retry/dead-letter publish failed queue=%s "
                        "error_type=%s",
                        safe_log_field(queue_name), type(publish_error).__name__,
                    )
                    # The original message remains the source of truth if the
                    # retry or DLQ publish was not broker-confirmed.
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag, requeue=True)
        
        return handler
    
    def start_consuming(self) -> None:
        """开始消费（阻塞式）"""
        if not self._consumers:
            return
        logger.info("Starting message consumption...")
        connection = None
        try:
            connection = self._open_connection()
            channel = connection.channel()
            channel.confirm_delivery()
            self._consumer_connection = connection
            self._consumer_channel = channel
            self._consumer_ready.set()
            prefetch = max(
                option["prefetch_count"]
                for option in self._consumer_options.values()
            )
            channel.basic_qos(prefetch_count=prefetch)
            for queue_name, callback in list(self._consumers.items()):
                options = self._consumer_options[queue_name]
                if not options["auto_ack"]:
                    channel.queue_declare(
                        queue=f"{queue_name}.DLQ", durable=True)
                channel.basic_consume(
                    queue=queue_name,
                    on_message_callback=self._create_message_handler(
                        callback, options["auto_ack"], queue_name),
                    auto_ack=options["auto_ack"],
                )
            channel.start_consuming()
        except Exception as exc:
            self._consumer_start_error = exc
            logger.error(
                "RabbitMQ consumer stopped error_type=%s",
                type(exc).__name__,
            )
            raise
        finally:
            self._consumer_ready.set()
            self._consumer_channel = None
            self._consumer_connection = None
            if connection is not None:
                try:
                    if not getattr(connection, "is_closed", True):
                        connection.close()
                except Exception:
                    logger.debug(
                        "Unable to close RabbitMQ consumer connection",
                        exc_info=True,
                    )

    def start_consuming_background(self) -> Optional[threading.Thread]:
        """在守护线程中启动已注册的消费者。"""
        if not self._consumers:
            return None
        if self._consumer_thread and self._consumer_thread.is_alive():
            return self._consumer_thread

        self._consumer_thread = threading.Thread(
            target=self._run_consumer_background,
            name="SpringRabbitConsumer",
            daemon=True,
        )
        self._consumer_ready.clear()
        self._consumer_start_error = None
        self._consumer_thread.start()
        if not self._consumer_ready.wait(timeout=self.connection_timeout):
            raise RuntimeError(
                "RabbitMQ consumer did not start within connection timeout")
        if self._consumer_start_error is not None:
            error = self._consumer_start_error
            if self._consumer_thread.is_alive():
                self._consumer_thread.join(timeout=self.connection_timeout)
            raise RuntimeError("RabbitMQ consumer failed to start") from error
        return self._consumer_thread

    def _run_consumer_background(self) -> None:
        """Capture background startup errors for the initiating thread."""
        try:
            self.start_consuming()
        except BaseException as exc:
            self._consumer_start_error = exc
            self._consumer_ready.set()
    
    def stop_consuming(self) -> None:
        """停止消费"""
        channel = self._consumer_channel
        connection = self._consumer_connection
        if (self._consumer_thread and self._consumer_thread.is_alive()
                and channel is None):
            self._consumer_ready.wait(timeout=self.connection_timeout)
            channel = self._consumer_channel
            connection = self._consumer_connection
        consumer_thread = self._consumer_thread
        if channel and consumer_thread and consumer_thread.is_alive():
            if connection and not connection.is_closed:
                connection.add_callback_threadsafe(channel.stop_consuming)
        elif channel and getattr(channel, 'is_open', False):
            channel.stop_consuming()
        if (consumer_thread and consumer_thread.is_alive()
                and threading.current_thread() is not consumer_thread):
            consumer_thread.join(timeout=5)
            if consumer_thread.is_alive():
                logger.error("RabbitMQ consumer did not stop within timeout")
                raise RuntimeError(
                    "RabbitMQ consumer did not stop within timeout")
        logger.info("Stopped message consumption")
    
    def close(self) -> None:
        """关闭连接"""
        self.stop_consuming()
        publisher_stuck = False
        with self._publisher_lock:
            publisher_thread = self._publisher_thread
            if publisher_thread is not None and publisher_thread.is_alive():
                self._publisher_stop.set()
                try:
                    self._publisher_queue.put_nowait(None)
                except queue.Full:
                    # The worker observes the stop event after draining the
                    # bounded queue, so a full queue needs no sentinel.
                    pass
                if threading.current_thread() is not publisher_thread:
                    publisher_thread.join(timeout=self.publish_timeout)
                    if publisher_thread.is_alive():
                        logger.error(
                            "RabbitMQ publisher did not stop within timeout")
                        publisher_stuck = True
            if not publisher_stuck:
                self._publisher_thread = None
        with self._admin_lock:
            if self._connection and not self._connection.is_closed:
                self._connection.close()
                logger.info("Closed RabbitMQ connection")
            self._connection = None
            self._channel = None
        if (self._consumer_thread is None
                or not self._consumer_thread.is_alive()):
            self._consumer_thread = None
            self._consumer_connection = None
            self._consumer_channel = None
        if publisher_stuck:
            raise RuntimeError(
                "RabbitMQ publisher did not stop within timeout")


# 创建全局RabbitMQ客户端实例
rabbitmq_client = RabbitMQClient()


def init_rabbitmq(config: dict) -> None:
    """
    初始化RabbitMQ配置

    通过 ``configure`` 重新配置单例 ``RabbitMQClient``，使 ``rabbitmq.*`` 配置生效。
    直接操作私有字段绕过单例守卫虽能工作，但封装为标准 ``configure`` 方法更稳健，
    未来新增字段不易遗漏。

    Args:
        config: 配置字典，包含host, port, username, password等
    """
    # 单例原地更新配置，避免直接操作私有字段
    if not isinstance(config, dict):
        config = {}
    timeout = _first_timeout(config)
    rabbitmq_client.configure(
        host=config.get('host', 'localhost'),
        port=config.get('port', 5672),
        username=config.get('username', 'guest'),
        password=config.get('password', 'guest'),
        virtual_host=config.get('virtual_host', '/'),
        connection_timeout=timeout,
        socket_timeout=config.get('socket_timeout', timeout),
        stack_timeout=config.get('stack_timeout', timeout),
        connection_attempts=config.get('connection_attempts', 1),
        retry_delay=config.get('retry_delay', 0.0),
        blocked_connection_timeout=config.get('blocked_connection_timeout', 300.0),
        publish_timeout=config.get('publish_timeout', 10.0),
        publish_queue_size=config.get('publish_queue_size', 1000),
        max_delivery_attempts=config.get('max_delivery_attempts', 5),
        consumer_retry_delay=config.get('consumer_retry_delay', 0.25),
    )
    rabbitmq_client.connect()


def _first_timeout(config: dict) -> float:
    """兼容 timeout/connection_timeout 两种配置命名。"""
    for name in ('connection_timeout', 'timeout', 'timeout_seconds'):
        value = config.get(name)
        if value is not None:
            return RabbitMQClient._normalize_timeout(value)
    return RabbitMQClient.DEFAULT_CONNECTION_TIMEOUT_SECONDS
