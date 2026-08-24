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
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger("Spring.Messaging.RabbitMQ")


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
                 timeout: Optional[float] = None):
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
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[pika.channel.Channel] = None
        self._consumers: Dict[str, Callable] = {}
        self._consumer_thread: Optional[threading.Thread] = None
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
                  timeout_seconds: Optional[float] = None) -> None:
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
        self._connection = None
        self._channel = None
        self._consumers.clear()
        self._consumer_thread = None

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
    
    def connect(self) -> None:
        """连接RabbitMQ"""
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameter_kwargs = dict(
                host=self.host,
                port=self.port,
                credentials=credentials,
                virtual_host=self.virtual_host,
                heartbeat=600,
                blocked_connection_timeout=self.blocked_connection_timeout,
                # pika 默认 connection_attempts 在不同版本/适配器中可能
                # 不同，显式设置为 1，确保服务不可用时快速返回。
                connection_attempts=self.connection_attempts,
                retry_delay=self.retry_delay,
                socket_timeout=self.socket_timeout,
                stack_timeout=self.stack_timeout,
            )

            try:
                parameters = pika.ConnectionParameters(**parameter_kwargs)
            except TypeError:
                # 兼容较老的 pika 或测试替身不认识新字段。至少保留
                # socket_timeout（大多数旧版已支持），不能因兼容性问题
                # 让可选消息模块拖垮整个应用启动。
                for key in ("stack_timeout", "retry_delay", "connection_attempts"):
                    parameter_kwargs.pop(key, None)
                try:
                    parameters = pika.ConnectionParameters(**parameter_kwargs)
                except TypeError:
                    # 极老版本连 socket_timeout 也不接受；最后再退回基础
                    # 参数，让连接错误由 startup.fail_fast 统一处理。
                    parameter_kwargs.pop("socket_timeout", None)
                    parameters = pika.ConnectionParameters(**parameter_kwargs)
            
            self._connection = pika.BlockingConnection(parameters)
            self._channel = self._connection.channel()
            
            logger.info(f"Connected to RabbitMQ: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            # pika 可能在握手失败前已创建底层 socket；清理引用，避免
            # 后续懒加载误把半连接对象当成可用通道。
            failed_connection = self._connection
            self._connection = None
            self._channel = None
            if failed_connection is not None:
                try:
                    if not getattr(failed_connection, "is_closed", True):
                        failed_connection.close()
                except Exception:
                    logger.debug("Unable to close failed RabbitMQ connection", exc_info=True)
            raise
    
    def get_channel(self) -> pika.channel.Channel:
        """获取通道"""
        if self._channel is None:
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
        channel = self.get_channel()
        channel.queue_declare(
            queue=queue_name,
            durable=durable,
            exclusive=exclusive,
            auto_delete=auto_delete,
        )
        logger.info(f"Declared queue: {queue_name}")
    
    def declare_exchange(self, exchange_name: str, exchange_type: str = "direct",
                         durable: bool = True) -> None:
        """
        声明交换机
        
        Args:
            exchange_name: 交换机名称
            exchange_type: 交换机类型
            durable: 是否持久化
        """
        channel = self.get_channel()
        channel.exchange_declare(
            exchange=exchange_name,
            exchange_type=exchange_type,
            durable=durable,
        )
        logger.info(f"Declared exchange: {exchange_name}")
    
    def bind_queue(self, queue_name: str, exchange_name: str, routing_key: str = "") -> None:
        """
        绑定队列到交换机
        
        Args:
            queue_name: 队列名称
            exchange_name: 交换机名称
            routing_key: 路由键
        """
        channel = self.get_channel()
        channel.queue_bind(
            queue=queue_name,
            exchange=exchange_name,
            routing_key=routing_key,
        )
        logger.info(f"Bound queue {queue_name} to exchange {exchange_name}")
    
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
        channel = self.get_channel()
        
        # 序列化消息体
        if isinstance(body, dict):
            body_str = json.dumps(body)
        else:
            body_str = str(body)
        
        # 发布消息
        channel.basic_publish(
            exchange=exchange_name,
            routing_key=routing_key,
            body=body_str,
            properties=pika.BasicProperties(
                content_type=content_type,
                delivery_mode=2 if persistent else 1,
            ),
        )
        logger.debug(f"Published message to {exchange_name}:{routing_key}")
    
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
        channel = self.get_channel()
        
        # 设置预取数量
        channel.basic_qos(prefetch_count=prefetch_count)
        
        # 注册回调
        self._consumers[queue_name] = callback
        
        # 开始消费
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=self._create_message_handler(callback, auto_ack),
            auto_ack=auto_ack,
        )
        
        logger.info(f"Started consuming queue: {queue_name}")
    
    def _create_message_handler(self, callback: Callable, auto_ack: bool = False) -> Callable:
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
                    asyncio.run(result)
                
                # 手动确认
                if not auto_ack:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                
                logger.debug(f"Processed message: {message}")
            except Exception as e:
                logger.error(f"Failed to process message: {e}")
                
                # 处理失败时重新入队
                if not auto_ack:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        return handler
    
    def start_consuming(self) -> None:
        """开始消费（阻塞式）"""
        if not self._consumers:
            return
        logger.info("Starting message consumption...")
        self.get_channel().start_consuming()

    def start_consuming_background(self) -> Optional[threading.Thread]:
        """在守护线程中启动已注册的消费者。"""
        if not self._consumers:
            return None
        if self._consumer_thread and self._consumer_thread.is_alive():
            return self._consumer_thread

        self._consumer_thread = threading.Thread(
            target=self.start_consuming,
            name="SpringRabbitConsumer",
            daemon=True,
        )
        self._consumer_thread.start()
        return self._consumer_thread
    
    def stop_consuming(self) -> None:
        """停止消费"""
        if self._channel and self._consumer_thread and self._consumer_thread.is_alive():
            if self._connection and not self._connection.is_closed:
                self._connection.add_callback_threadsafe(self._channel.stop_consuming)
            if threading.current_thread() is not self._consumer_thread:
                self._consumer_thread.join(timeout=5)
        elif self._channel and getattr(self._channel, 'is_open', False):
            self._channel.stop_consuming()
        logger.info("Stopped message consumption")
    
    def close(self) -> None:
        """关闭连接"""
        self.stop_consuming()
        if self._connection and not self._connection.is_closed:
            self._connection.close()
            logger.info("Closed RabbitMQ connection")
        self._connection = None
        self._channel = None
        self._consumer_thread = None


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
    )
    rabbitmq_client.connect()


def _first_timeout(config: dict) -> float:
    """兼容 timeout/connection_timeout 两种配置命名。"""
    for name in ('connection_timeout', 'timeout', 'timeout_seconds'):
        value = config.get(name)
        if value is not None:
            return RabbitMQClient._normalize_timeout(value)
    return RabbitMQClient.DEFAULT_CONNECTION_TIMEOUT_SECONDS
