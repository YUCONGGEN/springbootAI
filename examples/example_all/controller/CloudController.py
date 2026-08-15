"""
微服务 Cloud 控制器 — 测试 Nacos 服务发现、Feign 声明式调用、负载均衡
- @EnableDiscoveryClient, @NacosValue, @RefreshScope
- @EnableFeignClients, @FeignClient
- @LoadBalanced
- @SentinelResource, @EnableGateway
- @GlobalTransactional
"""
from spring.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping,
    Autowired, Slf4j,
)
from spring.annotations.cloud import (
    EnableDiscoveryClient, NacosValue, RefreshScope,
    LoadBalanced, SentinelResource,
    GlobalTransactional,
)
from spring.web.result import Result
from example_all.service.CloudService import CloudService


@RestController
@RequestMapping("/api/cloud")
@Slf4j
@EnableDiscoveryClient
@RefreshScope
class CloudController:
    """Cloud 微服务全注解控制器"""

    @Autowired
    def __init__(self, cloud_service: CloudService):
        self.cloud_service = cloud_service

    # ==================== Nacos 服务发现 ====================

    @GetMapping("/discovery/status")
    def discovery_status(self):
        """@EnableDiscoveryClient — Nacos 服务发现状态"""
        result = self.cloud_service.get_discovery_status()
        return Result.success(data=result)

    @GetMapping("/discovery/services")
    def list_services(self):
        """查询 Nacos 注册的服务列表"""
        result = self.cloud_service.list_registered_services()
        return Result.success(data=result)

    @PostMapping("/discovery/register")
    def register_service(self, service_name: str, ip: str = "127.0.0.1", port: int = 8080):
        """注册服务到 Nacos"""
        result = self.cloud_service.register_service(service_name, ip, port)
        return Result.success(data=result)

    # ==================== @NacosValue 动态配置 ====================

    @GetMapping("/config")
    @NacosValue(value="app.name")
    def get_config_value(self):
        """@NacosValue — 从 Nacos 读取动态配置"""
        result = self.cloud_service.get_nacos_config("app.name")
        return Result.success(data={"nacos_value": result})

    # ==================== Feign 声明式调用 ====================

    @GetMapping("/feign/test")
    def test_feign(self):
        """@FeignClient — 声明式 HTTP 调用"""
        result = self.cloud_service.feign_call_test()
        return Result.success(data=result)

    # ==================== 负载均衡 ====================

    @GetMapping("/loadbalance/status")
    @LoadBalanced
    def loadbalance_status(self):
        """@LoadBalanced — 负载均衡状态"""
        result = self.cloud_service.get_loadbalancer_info()
        return Result.success(data=result)

    # ==================== Sentinel 熔断限流 ====================

    @GetMapping("/sentinel/test")
    @SentinelResource(value="sentinel_test", fallback="sentinel_fallback")
    def sentinel_test(self):
        """@SentinelResource — Sentinel 资源保护"""
        result = self.cloud_service.sentinel_protected_operation()
        return Result.success(data=result)

    def sentinel_fallback(self):
        return Result.error(message="Sentinel fallback triggered", code=503)

    # ==================== 分布式事务 ====================

    @PostMapping("/transaction")
    @GlobalTransactional
    def global_transaction(self, amount: float = 100.0):
        """@GlobalTransactional — 分布式事务"""
        result = self.cloud_service.distributed_transaction(amount)
        return Result.success(data=result)

    # ==================== 综合状态 ====================

    @GetMapping("/status")
    def cloud_status(self):
        """Cloud 全组件状态汇总"""
        return Result.success(data=self.cloud_service.get_full_status())
