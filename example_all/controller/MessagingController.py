"""
消息队列控制器 — 测试 RabbitMQ 消息收发
- @RabbitListener, RabbitTemplate
"""
from spring.annotations.core import RestController, RequestMapping, GetMapping, PostMapping, Autowired, Slf4j
from spring.annotations.messaging import RabbitListener, rabbit_template
from spring.web.result import Result
from example_all.service.MessagingService import MessagingService


@RestController
@RequestMapping("/api/messaging")
@Slf4j
class MessagingController:
    """消息队列全注解控制器"""

    @Autowired
    def __init__(self, messaging_service: MessagingService):
        self.messaging_service = messaging_service

    # ==================== RabbitMQ 消息发送 ====================

    @PostMapping("/publish")
    def publish_message(self, queue: str = "test_queue", message: str = "Hello RabbitMQ!"):
        """发送消息到指定队列 — 使用 RabbitTemplate"""
        result = self.messaging_service.publish_message(queue, message)
        return Result.success(data=result)

    @PostMapping("/exchange")
    def publish_to_exchange(self, exchange: str = "test_exchange", routing_key: str = "test.key", message: str = "test"):
        """发送消息到交换机"""
        result = self.messaging_service.publish_to_exchange(exchange, routing_key, message)
        return Result.success(data=result)

    # ==================== RabbitMQ 消息消费 ====================

    @GetMapping("/status")
    def messaging_status(self):
        """消息队列状态"""
        return Result.success(data=self.messaging_service.get_status())

    @GetMapping("/messages/received")
    def get_received_messages(self):
        """查看已接收的消息"""
        return Result.success(data={
            "count": len(self.messaging_service.received_messages),
            "messages": self.messaging_service.received_messages[-20:],
        })

    # ==================== @RabbitListener 测试 ====================

    @PostMapping("/listener/test")
    def test_listener(self, message: str = "test_listener_message"):
        """发布消息并等待 @RabbitListener 消费"""
        self.messaging_service.publish_message("example_all_queue", message)
        return Result.success(data={"published": message, "queue": "example_all_queue"})


# ==================== @RabbitListener 消息消费者 ====================

@RestController
@Slf4j
class MessageConsumer:
    """@RabbitListener 消息消费者"""

    @RabbitListener(queue="example_all_queue")
    def on_message(self, message: str):
        """监听 example_all_queue 队列"""
        self.logger.info(f"[RabbitListener] 收到消息: {message}")
