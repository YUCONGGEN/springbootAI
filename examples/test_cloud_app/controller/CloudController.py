"""
Cloud注解测试控制器
暴露Cloud注解测试的API端点
"""
from springbootai.annotations.core import (
    RestController,
    GetMapping,
    PostMapping,
    RequestMapping,
    Autowired,
    Slf4j,
)
from springbootai.aop.cloud_aop import (
    get_sentinel_stats,
    get_transaction_context,
    get_refresh_scope_cache,
    trigger_config_refresh,
)


@RestController
@RequestMapping("/cloud")
@Slf4j
class CloudController:
    """Cloud注解测试控制器"""
    
    @Autowired
    def __init__(self, cloud_test_service, load_balanced_config):
        self.cloud_test_service = cloud_test_service
        self.load_balanced_config = load_balanced_config
    
    # ==================== SentinelResource 测试 ====================
    @GetMapping("/sentinel")
    def test_sentinel(self, should_fail: bool = False):
        """测试@SentinelResource"""
        result = self.cloud_test_service.sentinel_test(should_fail)
        return {"code": 200, "message": "success", "data": result}
    
    @GetMapping("/hotkey")
    def test_hotkey(self, product_id: str):
        """测试热点参数限流"""
        result = self.cloud_test_service.hotkey_test(product_id)
        return {"code": 200, "message": "success", "data": result}
    
    # ==================== GlobalTransactional 测试 ====================
    @GetMapping("/transaction")
    def test_transaction(self, should_fail: bool = False):
        """测试@GlobalTransactional"""
        try:
            result = self.cloud_test_service.transaction_test(should_fail)
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 500, "message": str(e), "data": None}
    
    @GetMapping("/transaction-sync")
    def test_transaction_sync(self):
        """测试@GlobalTransactional + @Synchronized组合"""
        try:
            result = self.cloud_test_service.transaction_sync_test()
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 500, "message": str(e), "data": None}
    
    # ==================== 组合测试 ====================
    @PostMapping("/combined")
    def test_combined(self, request_id: str):
        """测试@SentinelResource + @Metrics + @Idempotent组合"""
        try:
            result = self.cloud_test_service.combined_test(request_id)
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 500, "message": str(e), "data": None}
    
    # ==================== Valid/Validated 测试 ====================
    @GetMapping("/valid")
    def test_valid(self, name: str, age: int):
        """测试@Valid参数校验"""
        try:
            result = self.cloud_test_service.valid_test(name, age)
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 400, "message": str(e), "data": None}
    
    @GetMapping("/validated")
    def test_validated(self, id: int, value: str):
        """测试@Validated参数校验"""
        try:
            result = self.cloud_test_service.validated_test(id, value)
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 400, "message": str(e), "data": None}
    
    # ==================== LoadBalanced 测试 ====================
    @GetMapping("/load-balanced")
    def test_load_balanced(self):
        """测试@LoadBalanced"""
        try:
            # 直接调用配置类的 @Bean 方法，验证 @LoadBalanced 注解生效
            result = self.load_balanced_config.rest_template()
            return {"code": 200, "message": "success", "data": result}
        except Exception as e:
            return {"code": 500, "message": str(e), "data": None}
    
    # ==================== 统计信息 ====================
    @GetMapping("/sentinel-stats")
    def get_sentinel_stats(self):
        """获取Sentinel统计信息"""
        stats = get_sentinel_stats()
        return {"code": 200, "message": "success", "data": stats}
    
    @GetMapping("/transaction-context")
    def get_transaction_context(self):
        """获取当前事务上下文"""
        context = get_transaction_context()
        return {"code": 200, "message": "success", "data": context}
    
    @GetMapping("/refresh-cache")
    def get_refresh_cache(self):
        """获取刷新作用域缓存"""
        cache = get_refresh_scope_cache()
        return {"code": 200, "message": "success", "data": cache}
    
    @PostMapping("/refresh")
    def trigger_refresh(self):
        """触发配置刷新"""
        trigger_config_refresh()
        return {"code": 200, "message": "success", "data": {"message": "Config refresh triggered"}}
    
    # ==================== 重置 ====================
    @PostMapping("/reset")
    def reset(self):
        """重置所有计数器"""
        result = self.cloud_test_service.reset_counters()
        return {"code": 200, "message": "success", "data": result}
