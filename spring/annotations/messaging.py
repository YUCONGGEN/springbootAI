"""
消息队列注解
提供RabbitMQ消息消费和发送功能
"""
from typing import Any, Callable, Dict, List
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
        from spring.messaging.rabbitmq import rabbitmq_client

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
    from spring.messaging.rabbitmq import rabbitmq_client

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
