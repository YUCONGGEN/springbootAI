"""
Event/Listener 事件控制器
============================================================================
测试: publish_event + @EventListener 异步事件分发
"""
from spring.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping, Autowired, Slf4j,
)
from spring.web.result import Result
from example_all.service.EventService import EventService


@RestController
@RequestMapping("/api/event")
@Slf4j
class EventController:
    """事件发布/订阅测试控制器"""

    @Autowired
    def __init__(self, event_service: EventService):
        self.event_service = event_service

    # ==================== 发布事件 ====================

    @PostMapping("/publish/user")
    def publish_user_created(self, username: str, email: str = ""):
        """发布 UserCreatedEvent"""
        from example_all.service.EventService import UserCreatedEvent
        from spring.context.application_context import ApplicationContext
        
        event = UserCreatedEvent(username=username, email=email)
        ctx = ApplicationContext.get_instance()
        if ctx:
            ctx.publish_event(event)
            return Result.success(data={
                "published": "UserCreatedEvent",
                "username": username,
                "email": email,
            })
        return Result.error(message="ApplicationContext not available", code=500)

    @PostMapping("/publish/startup")
    def publish_system_startup(self, message: str = "test startup event"):
        """发布 SystemStartupEvent"""
        from example_all.service.EventService import SystemStartupEvent
        from spring.context.application_context import ApplicationContext

        event = SystemStartupEvent(message=message)
        ctx = ApplicationContext.get_instance()
        if ctx:
            ctx.publish_event(event)
            return Result.success(data={"published": "SystemStartupEvent", "message": message})
        return Result.error(message="ApplicationContext not available", code=500)

    # ==================== 查询状态 ====================

    @GetMapping("/stats")
    def event_stats(self):
        """获取事件统计"""
        return Result.success(data=self.event_service.get_stats())

    @GetMapping("/available")
    def check_available(self):
        """检查 Event/Listener 机制是否可用"""
        return Result.success(data={
            "event_listener_available": True,
            "annotations": {
                "@EventListener": True,
                "ApplicationEvent": True,
                "ApplicationEventPublisher": True,
            },
            "listener_count": self.event_service.user_created_count
                + self.event_service.system_startup_count,
        })

    @PostMapping("/reset")
    def reset_stats(self):
        """重置事件统计"""
        self.event_service.reset()
        return Result.success(data={"reset": "ok"})
