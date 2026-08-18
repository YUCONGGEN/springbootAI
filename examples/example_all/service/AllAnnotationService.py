"""
Service 全注解服务 — 测试所有 Service 层核心注解
- @Service, @Autowired, @Qualifier, @Value
- @Slf4j, @LogExecutionTime
- @PostConstruct, @PreDestroy, @Primary, @Lazy
- @Transactional, @Cacheable, @Retryable
"""
from springbootai.annotations.core import (
    Service, Autowired,
    Slf4j, LogExecutionTime,
    PostConstruct, PreDestroy, Primary, Lazy,
    Transactional, Cacheable, Retryable,
    Async,
)
from example_all.mappers.UserMapper import UserMapper


@Slf4j
@Service
class AllAnnotationService:
    """核心服务 — 测试 @Service, @Autowired, @Slf4j, @PostConstruct, @PreDestroy,
    @Value, @Transactional, @Cacheable, @Retryable, @Async"""

    @Autowired
    def __init__(self, user_mapper: UserMapper, customGreeting: str):
        self.user_mapper = user_mapper
        self.greeting = customGreeting
        self.cache = {}

    @PostConstruct
    def init(self):
        """@PostConstruct — Bean 初始化后回调"""
        self.logger.info(f"AllAnnotationService 初始化: greeting={self.greeting}")

    @PreDestroy
    def cleanup(self):
        """@PreDestroy — Bean 销毁前回调"""
        self.logger.info("AllAnnotationService 销毁中...")
        self.cache.clear()

    # ==================== 基本方法 ====================

    @LogExecutionTime(log_level="info")
    def get_app_info(self) -> dict:
        """@LogExecutionTime — 记录方法执行耗时"""
        return {
            "service": "AllAnnotationService",
            "greeting": self.greeting,
        }

    def get_user_with_config(self, user_id: int, source: str) -> dict:
        return {"user_id": user_id, "source": source, "status": "ok"}

    def create_user(self, user_data: dict) -> dict:
        user_data["created"] = True
        return user_data

    def update_user(self, user_id: int, user_data: dict) -> dict:
        user_data["updated"] = True
        return user_data

    def delete_user(self, user_id: int) -> bool:
        return True

    def get_counter(self) -> int:
        return len(self.cache)

    # ==================== @Transactional 事务测试 ====================

    @Transactional
    def transactional_create(self, username: str, email: str) -> dict:
        """@Transactional — 事务内创建用户"""
        self.logger.info(f"Transactional create: {username}, {email}")
        return {"username": username, "email": email, "transactional": True}

    @Transactional(rollback_for=[RuntimeError])
    def transactional_with_rollback(self, should_rollback: bool) -> str:
        """@Transactional — 带回滚条件"""
        if should_rollback:
            self.logger.warning("事务将回滚")
            raise RuntimeError("Rollback triggered")
        return "Committed successfully"

    # ==================== @Cacheable 缓存测试 ====================

    @Cacheable(value="user_cache")
    def cached_get_user(self, user_id: int) -> dict:
        """@Cacheable — 缓存查询结果"""
        self.logger.info(f"缓存未命中 — 查询 user_id={user_id}")
        return {"user_id": user_id, "cached": False, "data": f"user_data_{user_id}"}

    # ==================== @Retryable 重试测试 ====================

    @Retryable(max_attempts=3, backoff=500)
    def flaky_network_call(self, should_fail: bool = False) -> str:
        """@Retryable — 自动重试（最多3次，间隔500ms）"""
        if should_fail:
            self.logger.warning("网络调用失败，将重试...")
            raise ConnectionError("Temporary network failure")
        return "Network call succeeded"

    # ==================== @Async 异步测试 ====================

    @Async
    def async_operation(self, task_id: int) -> str:
        """@Async — 异步执行"""
        import time
        time.sleep(0.5)
        self.logger.info(f"异步任务 {task_id} 完成")
        return f"Task {task_id} completed"


# ==================== @Primary 和 @Qualifier 测试 ====================

@Service
@Primary
class PrimaryService:
    """@Primary — 优先注入的实现"""

    def identify(self) -> str:
        return "I am the PRIMARY service"


@Service
class SecondaryService:
    """备选实现，通过 @Qualifier 指定"""

    def identify(self) -> str:
        return "I am the SECONDARY service"


@Slf4j
@Service
class ConsumerService:
    """测试 @Autowired + @Qualifier 注入"""

    @Autowired
    def __init__(self, primary_service: PrimaryService, secondaryService: SecondaryService):
        self.primary_service = primary_service
        self.secondary_service = secondaryService

    def get_primary_id(self) -> str:
        return self.primary_service.identify()

    def get_secondary_id(self) -> str:
        return self.secondary_service.identify()


# ==================== @Lazy 懒加载服务 ====================

@Service
@Lazy
class LazyService:
    """@Lazy — 懒加载服务，首次调用时才初始化"""

    def __init__(self):
        print("[LazyService] 初始化!")

    def do_work(self) -> str:
        return "Lazy service work done"
