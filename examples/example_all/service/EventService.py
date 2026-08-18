"""
Event/Listener 事件发布订阅服务
============================================================================
测试: @EventListener + ApplicationEvent + ApplicationEventPublisher
"""
from typing import List
from springbootai.annotations.core import (
    Service, EventListener, ApplicationEvent, Slf4j, PostConstruct,
)


# ==================== 自定义事件类型 ====================

class UserCreatedEvent(ApplicationEvent):
    """用户创建事件"""

    def __init__(self, username: str, email: str, source: str = "event_service"):
        super().__init__(source=source)
        self.username = username
        self.email = email


class SystemStartupEvent(ApplicationEvent):
    """系统启动事件"""

    def __init__(self, message: str):
        super().__init__(source="system")
        self.message = message


# ==================== Event/Listener 服务 ====================

@Slf4j
@Service
class EventService:
    """事件监听服务 — 测试 @EventListener 注解"""

    def __init__(self):
        self.received_events: List[dict] = []
        self.user_created_count: int = 0
        self.system_startup_count: int = 0

    @PostConstruct
    def init(self):
        self.logger.info("EventService 初始化 — Event/Listener 机制正常")

    # ==================== @EventListener 事件处理器 ====================

    @EventListener(event_type=UserCreatedEvent, order=1)
    def on_user_created(self, event: UserCreatedEvent):
        """监听 UserCreatedEvent — 处理用户创建"""
        self.user_created_count += 1
        self.received_events.append({
            "type": "UserCreatedEvent",
            "username": event.username,
            "email": event.email,
            "source": event.source,
        })
        self.logger.info(f"[EventListener] 用户创建: {event.username} ({event.email})")

    @EventListener(order=10)
    def on_system_startup(self, event: SystemStartupEvent):
        """监听 SystemStartupEvent"""
        self.system_startup_count += 1
        self.received_events.append({
            "type": "SystemStartupEvent",
            "message": event.message,
        })
        self.logger.info(f"[EventListener] 系统事件: {event.message}")

    @EventListener(order=99)
    def on_any_event(self, event: ApplicationEvent):
        """监听所有事件 (兜底处理器)"""
        self.logger.info(f"[EventListener] 兜底: {type(event).__name__}")

    # ==================== 统计 ====================

    def get_stats(self) -> dict:
        """获取事件统计"""
        return {
            "total_received": len(self.received_events),
            "user_created_count": self.user_created_count,
            "system_startup_count": self.system_startup_count,
            "recent_events": self.received_events[-5:],
            "event_listener_available": True,
        }

    def reset(self):
        """重置计数器"""
        self.received_events.clear()
        self.user_created_count = 0
        self.system_startup_count = 0
