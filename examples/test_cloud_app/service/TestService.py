from spring.annotations.core import Service, Autowired, Transactional, Cacheable, Async, Retryable, Slf4j, PostConstruct, PreDestroy


@Slf4j
@Service
class TestService:
    """测试服务类 - 测试 @Service, @Autowired, @Qualifier, @Transactional, @Cacheable, @Async, @Retryable"""
    
    @Autowired
    def __init__(self, user_repository):
        self.user_repository = user_repository
        self.data = {}
    
    @PostConstruct
    def init(self):
        """初始化方法 - 测试 @PostConstruct"""
        self.logger.info("TestService initialized")
        self.data = {"initialized": True}
    
    @PreDestroy
    def cleanup(self):
        """清理方法 - 测试 @PreDestroy"""
        self.logger.info("TestService cleaning up")
    
    @Transactional
    def create_user(self, user_id: int, name: str) -> dict:
        """创建用户 - 测试 @Transactional"""
        self.logger.info(f"Creating user {user_id}: {name}")
        user = {"id": user_id, "name": name, "created_at": "now"}
        self.user_repository.save(user_id, user)
        return user
    
    @Cacheable(value="user_cache")
    def get_user(self, user_id: int) -> dict:
        """获取用户 - 测试 @Cacheable"""
        self.logger.info(f"Fetching user {user_id} (not from cache)")
        return self.user_repository.find(user_id)
    
    @Async
    def async_task(self, task_id: int) -> str:
        """异步任务 - 测试 @Async"""
        import time
        time.sleep(1)
        self.logger.info(f"Async task {task_id} completed")
        return f"Task {task_id} done"
    
    @Retryable(max_attempts=3, backoff=1000)
    def flaky_operation(self, should_fail: bool = False) -> str:
        """不稳定操作 - 测试 @Retryable"""
        if should_fail:
            self.logger.warning("Flaky operation failed")
            raise RuntimeError("Temporary failure")
        return "Success"
    
    @Autowired
    def set_counter(self, counter: dict):
        """设置计数器 - 测试字段注入 @Autowired"""
        self.counter = counter
    
    @Transactional(rollback_for=[RuntimeError], no_rollback_for=[ValueError])
    def transaction_with_rollback(self, should_rollback: bool) -> str:
        """带回滚控制的事务 - 测试 @Transactional 回滚配置"""
        if should_rollback:
            raise RuntimeError("Should rollback")
        return "Commit success"
    
    def increment_counter(self) -> int:
        """递增计数器"""
        if hasattr(self, 'counter'):
            self.counter["count"] += 1
            return self.counter["count"]
        return 0


@Service
class GreetingService:
    """问候服务"""
    
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


@Service
class FarewellService:
    """告别服务"""
    
    def say_bye(self, name: str) -> str:
        return f"Goodbye, {name}!"
