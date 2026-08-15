"""
AOP 注解控制器 — 测试企业级 AOP 注解
@RateLimit, @CircuitBreaker, @Idempotent, @AuditLog,
@FeatureToggle, @Lock, @Metrics, @Synchronized, @Validate, @Trace
"""
from spring.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping,
    Autowired, Slf4j,
)
from spring.web.result import Result
from spring.aop.comprehensive_aop import (
    get_metrics, enable_feature, disable_feature, reset_circuit_breaker,
)
from example_all.service.AopService import AopService
from example_all.service.AsyncService import AsyncService


@RestController
@RequestMapping("/api/aop")
@Slf4j
class AopController:
    """AOP 全注解控制器"""

    @Autowired
    def __init__(self, aop_service: AopService, async_service: AsyncService):
        self.aop_service = aop_service
        self.async_service = async_service

    # ==================== @RateLimit 限流 ====================

    @GetMapping("/rate-limit")
    def test_rate_limit(self):
        """@RateLimit — 10秒内最多5次"""
        try:
            result = self.aop_service.rate_limited_request()
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=429)

    # ==================== @CircuitBreaker 熔断 ====================

    @GetMapping("/circuit-breaker")
    def test_circuit_breaker(self, fail: bool = False):
        """@CircuitBreaker — 熔断降级"""
        try:
            result = self.aop_service.unstable_api_call(fail)
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=503)

    @PostMapping("/circuit-breaker/reset")
    def reset_circuit(self):
        """重置熔断器"""
        reset_circuit_breaker("example_all.service.AopService.unstable_api_call")
        return Result.success(data={"message": "Circuit breaker reset"})

    # ==================== @Idempotent 幂等 ====================

    @PostMapping("/idempotent")
    def test_idempotent(self, request_id: str, amount: float):
        """@Idempotent — 相同 request_id 只处理一次"""
        result = self.aop_service.idempotent_payment(request_id, amount)
        return Result.success(data=result)

    # ==================== @AuditLog 审计日志 ====================

    @PostMapping("/audit-log")
    def test_audit_log(self, target_id: int, action: str):
        """@AuditLog — 自动记录审计日志"""
        result = self.aop_service.audited_action(target_id, action)
        return Result.success(data=result)

    # ==================== @FeatureToggle 功能开关 ====================

    @GetMapping("/feature-toggle")
    def test_feature_toggle(self):
        """@FeatureToggle — 功能开关控制"""
        try:
            result = self.aop_service.beta_feature()
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=403)

    @PostMapping("/feature-toggle/enable")
    def enable_feature(self, name: str):
        enable_feature(name)
        return Result.success(data={"message": f"Feature '{name}' enabled"})

    @PostMapping("/feature-toggle/disable")
    def disable_feature(self, name: str):
        disable_feature(name)
        return Result.success(data={"message": f"Feature '{name}' disabled"})

    # ==================== @Lock 分布式锁 ====================

    @PostMapping("/lock")
    def test_lock(self, resource_id: str):
        """@Lock — 分布式锁"""
        result = self.aop_service.locked_operation(resource_id)
        return Result.success(data=result)

    # ==================== @Metrics 指标监控 ====================

    @GetMapping("/metrics/info")
    def get_metrics_info(self):
        """获取指标数据"""
        metrics = get_metrics()
        return Result.success(data=metrics)

    @PostMapping("/metrics/process")
    def test_metrics(self, data: str):
        """@Metrics — 指标监控"""
        result = self.aop_service.monitorable_process(data)
        return Result.success(data=result)

    # ==================== @Synchronized 同步 ====================

    @GetMapping("/synchronized")
    def test_synchronized(self):
        """@Synchronized — 方法同步"""
        result = self.aop_service.sync_counter_increment()
        return Result.success(data=result)

    # ==================== @Validate 参数验证 ====================

    @PostMapping("/validate")
    def test_validate(self, email: str, username: str, age: int):
        """@Validate — 多字段参数验证"""
        try:
            result = self.aop_service.validate_registration(email, username, age)
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=400)

    # ==================== @Trace 分布式追踪 ====================

    @GetMapping("/trace")
    def test_trace(self, span_name: str = "test_span"):
        """@Trace — 分布式追踪"""
        result = self.aop_service.traced_workflow(span_name)
        return Result.success(data=result)

    # ==================== 注解组合测试 ====================

    @PostMapping("/combined")
    def test_combined(self, param: str):
        """@RateLimit + @AuditLog + @Metrics + @Trace 组合"""
        try:
            result = self.aop_service.multi_annotation_combo(param)
            return Result.success(data=result)
        except Exception as e:
            return Result.error(message=str(e), code=500)

    # ==================== @Async 异步 ====================

    @PostMapping("/async")
    def test_async(self, task_name: str):
        """@Async — 异步执行"""
        result = self.async_service.async_task(task_name)
        return Result.success(data={"task": task_name, "status": "submitted"})

    @PostMapping("/async/batch")
    def test_async_batch(self, tasks: int = 3):
        """@Async — 批量异步"""
        results = self.async_service.batch_async_tasks(tasks)
        return Result.success(data={"count": tasks, "results": results})
