"""
消息队列服务 — 封装 RabbitMQ 操作
"""
from spring.annotations.core import Service, Slf4j, PostConstruct


@Slf4j
@Service
class MessagingService:
    """RabbitMQ 消息队列服务"""

    def __init__(self):
        self.received_messages = []

    @PostConstruct
    def init(self):
        self.logger.info("MessagingService 初始化完成")

    def publish_message(self, queue: str, message: str) -> dict:
        """发送消息到队列"""
        try:
            from spring.messaging.rabbitmq import rabbitmq_client
            if rabbitmq_client:
                rabbitmq_client.publish(queue, message)
                return {"published": True, "queue": queue, "message": message[:50]}
        except Exception as e:
            self.logger.warning(f"RabbitMQ 发布失败: {e}")
        return {"published": False, "reason": "RabbitMQ 不可用"}

    def publish_to_exchange(self, exchange: str, routing_key: str, message: str) -> dict:
        """发送消息到交换机"""
        try:
            from spring.messaging.rabbitmq import rabbitmq_client
            if rabbitmq_client:
                rabbitmq_client.publish_exchange(exchange, routing_key, message)
                return {"published": True, "exchange": exchange, "routing_key": routing_key}
        except Exception as e:
            self.logger.warning(f"RabbitMQ 交换机发布失败: {e}")
        return {"published": False, "reason": "RabbitMQ 不可用"}

    def get_status(self) -> dict:
        try:
            from spring.messaging.rabbitmq import rabbitmq_client
            if rabbitmq_client:
                return {"enabled": True, "host": "localhost", "port": 5672}
        except Exception:
            pass
        return {"enabled": False, "status": "disabled"}
