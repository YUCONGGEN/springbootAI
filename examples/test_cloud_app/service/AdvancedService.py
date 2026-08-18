from springbootai.annotations.core import (
    Service,
    RateLimit,
    CircuitBreaker,
    Idempotent,
    AuditLog,
    FeatureToggle,
    Lock,
    Metrics,
    Synchronized,
    Validate,
    Trace,
    Slf4j,
    PostConstruct,
)


@Service
@Slf4j
class AdvancedService:
    """测试所有进阶注解的服务类"""
    
    def __init__(self):
        self.counter = 0
        self.failure_count = 0
    
    @PostConstruct
    def init(self):
        self.logger.info("AdvancedService initialized")
    
    # ==================== RateLimit 限流测试 ====================
    @RateLimit(max_requests=5, time_window=10)
    def rate_limited_method(self):
        """10秒内最多5次调用"""
        return {"status": "success", "message": "Rate limit test passed"}
    
    # ==================== CircuitBreaker 熔断测试 ====================
    @CircuitBreaker(failure_threshold=3, recovery_timeout=10)
    def flaky_service(self, should_fail: bool = False):
        """测试熔断机制"""
        if should_fail:
            self.failure_count += 1
            raise Exception(f"Simulated failure {self.failure_count}")
        return {"status": "success", "failures_before": self.failure_count}
    
    def flaky_fallback(self):
        """熔断降级方法"""
        return {"status": "fallback", "message": "Service temporarily unavailable"}
    
    # ==================== Idempotent 幂等性测试 ====================
    @Idempotent(key="order_id", expire=60)
    def create_order(self, order_id: str, user_id: int):
        """创建订单（幂等）"""
        self.counter += 1
        return {
            "order_id": order_id,
            "user_id": user_id,
            "create_count": self.counter,
            "message": "Order created"
        }
    
    # ==================== AuditLog 审计日志测试 ====================
    @AuditLog(action="用户删除", target="user", detail="删除用户 {user_id}")
    def delete_user(self, user_id: int, operator: str = "system"):
        """删除用户（带审计日志）"""
        return {"status": "success", "deleted_user_id": user_id}
    
    # ==================== FeatureToggle 功能开关测试 ====================
    @FeatureToggle(name="new_feature", default=False)
    def new_feature_method(self):
        """新功能（默认关闭）"""
        return {"status": "success", "message": "New feature is enabled"}
    
    # ==================== Lock 分布式锁测试 ====================
    @Lock(key="stock_{product_id}", expire=5)
    def deduct_stock(self, product_id: int, quantity: int):
        """扣减库存（带锁）"""
        import time
        time.sleep(0.1)  # 模拟处理时间
        return {
            "product_id": product_id,
            "deducted": quantity,
            "message": "Stock deducted"
        }
    
    # ==================== Metrics 指标监控测试 ====================
    @Metrics(name="advanced_service.process")
    def process_data(self, data: str):
        """处理数据（带指标监控）"""
        import time
        time.sleep(0.01)
        return {"status": "success", "data_length": len(data)}
    
    # ==================== Synchronized 方法同步测试 ====================
    @Synchronized(lock_name="counter_lock")
    def synchronized_increment(self):
        """同步递增计数器"""
        import time
        old_value = self.counter
        time.sleep(0.05)
        self.counter += 1
        return {"old_value": old_value, "new_value": self.counter}
    
    # ==================== Validate 参数校验测试 ====================
    @Validate(field="email", regex=r'^[\w\.-]+@[\w\.-]+\.\w+$', message="Invalid email format")
    @Validate(field="username", min_length=3, max_length=50, message="Username must be 3-50 characters")
    @Validate(field="age", min=18, max=100, message="Age must be between 18 and 100")
    def validate_user(
        self,
        username: str,
        email: str,
        age: int
    ):
        """验证用户参数"""
        return {"status": "validated", "username": username, "email": email, "age": age}
    
    # ==================== Trace 分布式追踪测试 ====================
    @Trace(span_name="advanced_operation")
    def traced_operation(self, operation_id: str):
        """带追踪的操作"""
        return {"status": "success", "operation_id": operation_id}
    
    # ==================== 组合测试 ====================
    @RateLimit(max_requests=10, time_window=30)
    @AuditLog(action="组合操作", target="test")
    @Metrics(name="combined_operation")
    def combined_operation(self, param: str):
        """多个注解组合使用"""
        return {"status": "success", "param": param, "message": "Combined annotation test"}
    
    # ==================== 重置计数器 ====================
    def reset_counter(self):
        """重置计数器"""
        self.counter = 0
        self.failure_count = 0
        return {"status": "reset"}
