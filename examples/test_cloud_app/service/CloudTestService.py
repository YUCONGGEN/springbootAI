"""
Cloud注解测试服务
用于测试安全、性能和组合功能
"""
import threading
from spring.annotations.core import (
    Service,
    Slf4j,
    PostConstruct,
    Configuration,
    Bean,
    Metrics,
    Synchronized,
    Idempotent,
)
from spring.annotations.cloud import (
    SentinelResource,
    GlobalTransactional,
    RefreshScope,
    LoadBalanced,
    Valid,
    Validated,
)


@Service
@Slf4j
class CloudTestService:
    """Cloud注解测试服务"""
    
    def __init__(self):
        self.counter = 0
        self.transaction_counter = 0
        self.fallback_count = 0
        self._counter_lock = threading.Lock()
    
    @PostConstruct
    def init(self):
        self.logger.info("CloudTestService initialized")
    
    # ==================== SentinelResource 测试 ====================
    @SentinelResource(value="cloud-sentinel-test", fallback="handleFallback")
    def sentinel_test(self, should_fail: bool = False):
        """测试Sentinel资源保护"""
        if should_fail:
            raise Exception("Simulated failure")
        return {"status": "success", "data": "Sentinel test passed"}
    
    def handleFallback(self, should_fail: bool = False):
        """Sentinel降级处理"""
        self.fallback_count += 1
        return {"status": "fallback", "message": "Service temporarily unavailable", "fallback_count": self.fallback_count}
    
    @SentinelResource(value="cloud-hotkey-test", hotkey="product_id")
    def hotkey_test(self, product_id: str):
        """测试热点参数限流"""
        return {"status": "success", "product_id": product_id}
    
    # ==================== GlobalTransactional 测试 ====================
    @GlobalTransactional(timeout=60000, name="cloud-transaction-test")
    def transaction_test(self, should_fail: bool = False):
        """测试全局事务"""
        with self._counter_lock:
            self.transaction_counter += 1
            current_count = self.transaction_counter
        
        if should_fail:
            raise Exception("Transaction rollback")
        
        return {"status": "success", "transaction_count": current_count}
    
    @GlobalTransactional
    def nested_transaction_test(self):
        """测试嵌套事务（不支持）"""
        return {"status": "success"}
    
    # ==================== RefreshScope 测试 ====================
    @RefreshScope
    @Service
    class DynamicConfigService:
        """动态配置服务"""
        def __init__(self):
            self.config_value = "initial_value"
        
        def get_config(self):
            return {"config_value": self.config_value, "version": 1}
        
        def update_config(self, new_value):
            self.config_value = new_value
            return {"status": "updated", "config_value": self.config_value}
    
    # ==================== GlobalTransactional + Synchronized 组合测试 ====================
    @GlobalTransactional
    @Synchronized(lock_name="transaction-lock")
    def transaction_sync_test(self):
        """测试事务+同步组合"""
        old_value = self.counter
        self.counter += 1
        return {"old_value": old_value, "new_value": self.counter}
    
    # ==================== SentinelResource + Metrics + Idempotent 组合测试 ====================
    @SentinelResource(value="combined-test", fallback="combinedFallback")
    @Metrics(name="cloud.combined.test")
    @Idempotent(key="request_id", expire=60)
    def combined_test(self, request_id: str):
        """测试多注解组合"""
        return {"status": "success", "request_id": request_id}
    
    def combinedFallback(self, request_id: str):
        """组合测试降级处理"""
        return {"status": "fallback", "request_id": request_id, "message": "Combined fallback"}
    
    # ==================== Valid/Validated 测试 ====================
    @Valid
    def valid_test(self, name: str, age: int):
        """测试@Valid参数校验"""
        return {"status": "validated", "name": name, "age": age}
    
    @Validated
    def validated_test(self, id: int, value: str):
        """测试@Validated参数校验"""
        return {"status": "validated", "id": id, "value": value}
    
    # ==================== 重置方法 ====================
    def reset_counters(self):
        """重置所有计数器"""
        self.counter = 0
        self.transaction_counter = 0
        self.fallback_count = 0
        return {"status": "reset"}


@Configuration
class LoadBalancedConfig:
    """负载均衡配置"""
    
    @Bean
    @LoadBalanced
    def rest_template(self):
        """创建带负载均衡的RestTemplate"""
        return {
            "type": "RestTemplate",
            "load_balanced": False,  # 将被LoadBalanced注解修改为True
            "max_connections": 100,
        }
