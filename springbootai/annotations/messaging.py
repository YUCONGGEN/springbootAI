"""
消息队列注解
提供RabbitMQ消息消费和发送功能
"""
from typing import Any, Callable, Dict, Optional
import functools
from .core import SpringAnnotation


class RabbitListener(SpringAnnotation):
    """
    RabbitMQ消息监听注解

    使用示例：
    @RabbitListener(queue="order.create")
    def handle_order_created(self, message):
        print(f"Received order: {message}")
    """

    _annotation_type = "messaging"

    def __init__(self, queue: str, exchange: str = "", routing_key: str = "",
                 auto_ack: bool = False, prefetch_count: int = 1):
        super().__init__(
            queue=queue,
            exchange=exchange,
            routing_key=routing_key or queue,
            auto_ack=auto_ack,
            prefetch_count=prefetch_count,
        )


class RabbitTemplate:
    """
    RabbitMQ消息发送模板
    
    使用示例：
    rabbit_template = RabbitTemplate()
    rabbit_template.send("order.create", {"order_id": 1})
    """
    
    def send(self, queue: str, body: Any, exchange: str = "", 
             routing_key: str = "", persistent: bool = True):
        """
        发送消息
        
        Args:
            queue: 队列名称
            body: 消息体
            exchange: 交换机名称
            routing_key: 路由键
            persistent: 是否持久化
        """
        from springbootai.messaging.rabbitmq import rabbitmq_client

        if exchange:
            # 通过交换机发送
            rabbitmq_client.publish(
                exchange_name=exchange,
                routing_key=routing_key or queue,
                body=body,
                persistent=persistent,
            )
        else:
            # 直接发送到队列
            rabbitmq_client.publish_to_queue(
                queue_name=queue,
                body=body,
                persistent=persistent,
            )


def rabbit_listener_decorator(annotation: RabbitListener):
    """
    RabbitListener注解切面
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def register_rabbit_listener(annotation: RabbitListener, callback: Callable) -> None:
    """Declare and register one listener using an already-bound Bean method."""
    from springbootai.messaging.rabbitmq import rabbitmq_client

    rabbitmq_client.declare_queue(annotation.queue)
    if annotation.exchange:
        rabbitmq_client.declare_exchange(annotation.exchange)
        rabbitmq_client.bind_queue(
            queue_name=annotation.queue,
            exchange_name=annotation.exchange,
            routing_key=annotation.routing_key,
        )
    rabbitmq_client.consume(
        queue_name=annotation.queue,
        callback=callback,
        auto_ack=annotation.auto_ack,
        prefetch_count=annotation.prefetch_count,
    )


# 创建全局RabbitMQ模板实例
rabbit_template = RabbitTemplate()


# ==================== Kafka 注解 ====================


class KafkaListener(SpringAnnotation):
    """Kafka 消息监听注解

    使用示例：
    @KafkaListener(topics=["order-events"], groupId="order-service")
    def handle_order_event(self, message):
        print(f"Received: {message['value']}")

    与 @RabbitListener 的差异：
    - Kafka 监听 topics（数组），Rabbit 监听 queue（单个）
    - Kafka 需要 groupId（消费者组），Rabbit 不需要
    - Kafka 消息包含 partition/offset，Rabbit 只有 body
    """

    _annotation_type = "messaging"

    def __init__(self, topics, groupId: str = ""):
        # topics 支持单个字符串或列表
        if isinstance(topics, str):
            topics = [topics]
        super().__init__(
            topics=topics,
            groupId=groupId,
        )


class KafkaTemplate:
    """Kafka 消息发送模板

    使用示例：
    kafka_template = KafkaTemplate()
    kafka_template.send("order-events", {"order_id": 1})
    kafka_template.send("order-events", value={"order_id": 1}, key="order-1")
    """

    def send(self, topic: str, value: Any = None, key: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None):
        """发送消息到 Kafka topic

        Args:
            topic: Kafka 主题
            value: 消息体（自动 JSON 序列化）
            key: 分区键（可选）
            headers: 消息头（可选）
        """
        from springbootai.messaging.kafka import kafka_client
        return kafka_client.send(topic=topic, value=value, key=key, headers=headers)

    def send_and_wait(self, topic: str, value: Any = None, key: Optional[str] = None,
                      timeout: float = 10.0):
        """同步发送消息并等待确认"""
        from springbootai.messaging.kafka import kafka_client
        return kafka_client.send_and_wait(topic=topic, value=value, key=key, timeout=timeout)


def kafka_listener_decorator(annotation: KafkaListener):
    """KafkaListener 注解切面"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


def register_kafka_listener(annotation: KafkaListener, callback: Callable) -> None:
    """注册 Kafka 消费者"""
    from springbootai.messaging.kafka import kafka_client
    kafka_client.register_listener(
        topics=annotation.topics,
        callback=callback,
        group_id=annotation.groupId or None,
    )


# 全局 Kafka 模板实例
kafka_template = KafkaTemplate()
