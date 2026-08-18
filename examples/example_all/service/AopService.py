"""
AOP 企业级注解服务 — 测试所有 AOP 切面注解
@RateLimit, @CircuitBreaker, @Idempotent, @AuditLog,
@FeatureToggle, @Lock, @Metrics, @Synchronized, @Validate, @Trace
"""
from springbootai.annotations.core import (
    Service, Slf4j, PostConstruct,
    RateLimit, CircuitBreaker, Idempotent, AuditLog,
    FeatureToggle, Lock, Metrics, Synchronized,
    Validate, Trace, Retryable, Cacheable,
)


@Slf4j
@Service
class AopService:
    """AOP 全注解服务 — 测试所有企业级切面注解"""

    def __init__(self):
        self.counter = 0
        self.failure_count = 0

    @PostConstruct
    def init(self):
        self.logger.info("AopService 初始化完成")

    # ==================== @RateLimit 限流 ====================

    @RateLimit(max_requests=5, time_window=10)
    def rate_limited_request(self) -> dict:
        """10秒内最多5次 — 超出抛异常"""
        return {"status": "allowed", "message": "Rate limit OK"}

    # ==================== @CircuitBreaker 熔断 ====================

    @CircuitBreaker(failure_threshold=3, recovery_timeout=10)
    def unstable_api_call(self, should_fail: bool = False) -> dict:
        """3次失败后熔断，10秒后恢复"""
        if should_fail:
            self.failure_count += 1
            raise RuntimeError(f"API failure #{self.failure_count}")
        return {"status": "success", "failures": self.failure_count}

    # ==================== @Idempotent 幂等性 ====================

    @Idempotent(key="request_id", expire=60)
    def idempotent_payment(self, request_id: str, amount: float) -> dict:
        """相同 request_id 只会执行一次支付"""
        return {"request_id": request_id, "amount": amount, "status": "processed"}

    # ==================== @AuditLog 审计日志 ====================

    @AuditLog(action="安全操作", target="audit_test", detail="操作目标: {target_id}, 动作: {action}")
    def audited_action(self, target_id: int, action: str) -> dict:
        """自动记录审计日志"""
        return {"target_id": target_id, "action": action, "audited": True}

    # ==================== @FeatureToggle 功能开关 ====================

    @FeatureToggle(name="beta_feature", default=False)
    def beta_feature(self) -> dict:
        """功能开关控制的新功能（默认关闭）"""
        return {"feature": "beta_feature", "enabled": True}

    # ==================== @Lock 分布式锁 ====================

    @Lock(key="resource_{resource_id}", expire=10)
    def locked_operation(self, resource_id: str) -> dict:
        """带分布式锁的并发安全操作"""
        return {"resource_id": resource_id, "locked": True, "status": "processed"}

    # ==================== @Metrics 指标监控 ====================

    @Metrics(name="aop_service.process")
    def monitorable_process(self, data: str) -> dict:
        """带 Prometheus 指标的操作"""
        import time
        time.sleep(0.01)
        return {"status": "processed", "length": len(data)}

    # ==================== @Synchronized 同步 ====================

    @Synchronized(lock_name="aop_counter")
    def sync_counter_increment(self) -> dict:
        """线程安全的计数器递增"""
        import time
        old = self.counter
        time.sleep(0.02)
        self.counter += 1
        return {"old": old, "new": self.counter}

    # ==================== @Validate 参数验证 ====================

    @Validate(field="email", regex=r'^[\w\.-]+@[\w\.-]+\.\w+$', message="邮箱格式不正确")
    @Validate(field="username", min_length=3, max_length=50, message="用户名需要3-50个字符")
    @Validate(field="age", min=18, max=120, message="年龄需要在18-120之间")
    def validate_registration(self, email: str, username: str, age: int) -> dict:
        """多字段 @Validate 参数验证"""
        return {"email": email, "username": username, "age": age, "validated": True}

    # ==================== @Trace 分布式追踪 ====================

    @Trace(span_name="workflow_trace")
    def traced_workflow(self, span_name: str) -> dict:
        """带分布式追踪跨度的工作流"""
        return {"span_name": span_name, "traced": True}

    # ==================== 注解组合测试 ====================

    @RateLimit(max_requests=20, time_window=30)
    @AuditLog(action="组合注解测试", target="combo_test")
    @Metrics(name="aop_service.combined")
    @Trace(span_name="combo_operation")
    def multi_annotation_combo(self, param: str) -> dict:
        """@RateLimit + @AuditLog + @Metrics + @Trace 四合一"""
        return {
            "param": param,
            "rate_limited": True,
            "audited": True,
            "metered": True,
            "traced": True,
        }

    # ==================== @Retryable + @Cacheable 组合 ====================

    @Retryable(max_attempts=3, backoff=500)
    @Cacheable(value="external_data")
    def cache_with_retry(self, key: str, should_fail: bool = False) -> dict:
        """@Retryable + @Cacheable 组合"""
        if should_fail:
            raise ConnectionError("External service unavailable")
        return {"key": key, "source": "external_api"}

    # ==================== 辅助方法 ====================

    def reset(self):
        """重置所有状态"""
        self.counter = 0
        self.failure_count = 0
        return {"status": "reset"}
