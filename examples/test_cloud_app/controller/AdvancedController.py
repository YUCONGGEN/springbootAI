from spring.annotations.core import (
    RestController,
    RequestMapping,
    GetMapping,
    PostMapping,
    Autowired,
)
from spring.web.result import Result
from spring.aop.comprehensive_aop import (
    get_metrics,
    enable_feature,
    disable_feature,
    reset_circuit_breaker,
)


@RestController
@RequestMapping("/advanced")
class AdvancedController:
    """测试进阶注解的控制器"""
    
    @Autowired
    def __init__(self, advanced_service):
        self.advanced_service = advanced_service
    
    # ==================== RateLimit 测试 ====================
    @GetMapping("/rate-limit")
    def test_rate_limit(self):
        """测试限流注解"""
        try:
            result = self.advanced_service.rate_limited_method()
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=429)
    
    # ==================== CircuitBreaker 测试 ====================
    @GetMapping("/circuit-breaker")
    def test_circuit_breaker(self, fail: bool = False):
        """测试熔断注解"""
        try:
            result = self.advanced_service.flaky_service(fail)
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=503)
    
    @GetMapping("/circuit-breaker/reset")
    def reset_circuit(self):
        """重置熔断状态"""
        reset_circuit_breaker("testapp.service.AdvancedService.flaky_service")
        return Result.success(data={"message": "Circuit breaker reset"})
    
    # ==================== Idempotent 测试 ====================
    @PostMapping("/idempotent")
    def test_idempotent(self, order_id: str, user_id: int):
        """测试幂等性注解"""
        result = self.advanced_service.create_order(order_id, user_id)
        return Result.success(data=result)
    
    # ==================== AuditLog 测试 ====================
    @PostMapping("/audit-log")
    def test_audit_log(self, user_id: int):
        """测试审计日志注解"""
        result = self.advanced_service.delete_user(user_id)
        return Result.success(data=result)
    
    # ==================== FeatureToggle 测试 ====================
    @GetMapping("/feature-toggle")
    def test_feature_toggle(self):
        """测试功能开关注解"""
        try:
            result = self.advanced_service.new_feature_method()
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=403)
    
    @PostMapping("/feature-toggle/enable")
    def enable_feature_endpoint(self, name: str):
        """启用功能"""
        enable_feature(name)
        return Result.success(data={"message": f"Feature '{name}' enabled"})
    
    @PostMapping("/feature-toggle/disable")
    def disable_feature_endpoint(self, name: str):
        """禁用功能"""
        disable_feature(name)
        return Result.success(data={"message": f"Feature '{name}' disabled"})
    
    # ==================== Lock 测试 ====================
    @PostMapping("/lock")
    def test_lock(self, product_id: int, quantity: int):
        """测试分布式锁注解"""
        result = self.advanced_service.deduct_stock(product_id, quantity)
        return Result.success(data=result)
    
    # ==================== Metrics 测试 ====================
    @GetMapping("/metrics")
    def get_metrics_endpoint(self):
        """获取指标数据"""
        metrics = get_metrics()
        return Result.success(data=metrics)
    
    @PostMapping("/metrics/process")
    def test_metrics(self, data: str):
        """测试指标监控注解"""
        result = self.advanced_service.process_data(data)
        return Result.success(data=result)
    
    # ==================== Synchronized 测试 ====================
    @GetMapping("/synchronized")
    def test_synchronized(self):
        """测试方法同步注解"""
        result = self.advanced_service.synchronized_increment()
        return Result.success(data=result)
    
    # ==================== Validate 测试 ====================
    @PostMapping("/validate")
    def test_validate(self, username: str, email: str, age: int):
        """测试参数校验注解"""
        try:
            result = self.advanced_service.validate_user(username, email, age)
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=400)
    
    # ==================== Trace 测试 ====================
    @GetMapping("/trace")
    def test_trace(self, operation_id: str):
        """测试分布式追踪注解"""
        result = self.advanced_service.traced_operation(operation_id)
        return Result.success(data=result)
    
    # ==================== 组合测试 ====================
    @GetMapping("/combined")
    def test_combined(self, param: str):
        """测试注解组合使用"""
        result = self.advanced_service.combined_operation(param)
        return Result.success(data=result)
    
    # ==================== 重置 ====================
    @PostMapping("/reset")
    def reset(self):
        """重置所有状态"""
        self.advanced_service.reset_counter()
        return Result.success(data={"message": "All counters reset"})
