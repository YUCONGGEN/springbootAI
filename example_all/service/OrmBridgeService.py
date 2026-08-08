"""
ORM 服务 — 桥接 Controller 和 Mapper，演示 @Transactional, @Cacheable, @Retryable
"""
from spring.annotations.core import Service, Autowired, Slf4j, Transactional, Cacheable, Retryable
from example_all.mappers.UserMapper import UserMapper


@Slf4j
@Service
class OrmBridgeService:
    """ORM 桥接服务 — @Transactional, @Cacheable, @Retryable 在 Service 层的使用"""

    @Autowired
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper

    @Transactional
    def transactional_create(self, username: str, email: str) -> dict:
        """@Transactional — 事务中创建用户"""
        self.user_mapper.insert(username, email, "")
        return {"username": username, "email": email, "transactional": True}

    @Transactional(rollback_for=[RuntimeError])
    def transactional_with_rollback(self, should_rollback: bool) -> str:
        """@Transactional — 带回滚条件"""
        if should_rollback:
            self.logger.warning("事务将回滚!")
            raise RuntimeError("Rollback triggered")
        return "Committed"

    @Cacheable(value="user_cache")
    def cached_get_user(self, user_id: int) -> dict:
        """@Cacheable — 缓存查询"""
        self.logger.info(f"缓存未命中 — user_id={user_id}")
        return {"user_id": user_id, "cached": False}

    @Retryable(max_attempts=3, backoff=500)
    def flaky_network_call(self, should_fail: bool) -> str:
        """@Retryable — 网络调用重试"""
        if should_fail:
            self.logger.warning("网络调用失败")
            raise ConnectionError("Temporary failure")
        return "Success"
