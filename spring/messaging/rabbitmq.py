"""
消息队列模块
集成RabbitMQ实现异步消息处理
"""
import pika
import asyncio
import inspect
import json
import logging
import threading
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger("Spring.Messaging.RabbitMQ")


class RabbitMQClient:
    """RabbitMQ客户端"""
    
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
                 virtual_host: str = "/"):
        if hasattr(self, '_initialized'):
            return
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.virtual_host = virtual_host
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[pika.channel.Channel] = None
        self._consumers: Dict[str, Callable] = {}
        self._consumer_thread: Optional[threading.Thread] = None
        self._initialized = True
    
    def connect(self) -> None:
        """连接RabbitMQ"""
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                credentials=credentials,
                virtual_host=self.virtual_host,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
            
            self._connection = pika.BlockingConnection(parameters)
            self._channel = self._connection.channel()
            
            logger.info(f"Connected to RabbitMQ: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
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
    
    Args:
        config: 配置字典，包含host, port, username, password等
    """
    # Preserve references imported by RabbitTemplate and listener registration.
    rabbitmq_client.close()
    rabbitmq_client.host = config.get('host', 'localhost')
    rabbitmq_client.port = int(config.get('port', 5672))
    rabbitmq_client.username = config.get('username', 'guest')
    rabbitmq_client.password = config.get('password', 'guest')
    rabbitmq_client.virtual_host = config.get('virtual_host', '/')
    rabbitmq_client._connection = None
    rabbitmq_client._channel = None
    rabbitmq_client._consumers.clear()
    rabbitmq_client._consumer_thread = None
    rabbitmq_client.connect()
