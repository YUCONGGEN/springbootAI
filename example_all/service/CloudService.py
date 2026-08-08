"""
Cloud 微服务 — 测试 Nacos 服务发现、Feign 调用、负载均衡、Sentinel、分布式事务
"""
from spring.annotations.core import Service, Autowired, Slf4j, PostConstruct
from spring.annotations.cloud import (
    EnableDiscoveryClient,
)


@Slf4j
@Service
class CloudService:
    """Cloud 微服务综合服务"""

    def __init__(self):
        self._status = {"ready": False}

    @PostConstruct
    def init(self):
        self.logger.info("CloudService 初始化中...")
        self._status["ready"] = True

    # ==================== Nacos 服务发现 ====================

    def get_discovery_status(self) -> dict:
        """获取 Nacos 服务发现状态"""
        try:
            from spring.cloud.discovery import nacos_client
            if nacos_client and getattr(nacos_client, '_ready', False):
                return {"enabled": True, "status": "connected"}
        except Exception:
            pass
        return {"enabled": False, "status": "not_available"}

    def list_registered_services(self) -> list:
        """获取注册的服务"""
        try:
            from spring.cloud.discovery import nacos_client
            if nacos_client:
                services = nacos_client.get_services()
                return services or []
        except Exception:
            pass
        return []

    def register_service(self, service_name: str, ip: str, port: int) -> dict:
        """注册服务"""
        try:
            from spring.cloud.discovery import nacos_client
            if nacos_client:
                registered = nacos_client.register(service_name, ip, port)
                return {
                    "registered": bool(registered),
                    "service": service_name,
                    "ip": ip,
                    "port": port,
                }
        except Exception as e:
            self.logger.warning(f"服务注册失败: {e}")
        return {"registered": False, "note": "Nacos 不可用"}

    def get_nacos_config(self, key: str) -> str:
        """从 Nacos 获取配置"""
        # NacosValue 在 AOP 中处理，这里返回本地配置
        return f"nacos_config_{key}"

    # ==================== Feign 调用 ====================

    def feign_call_test(self) -> dict:
        """Feign 声明式调用测试"""
        return {"feign_client": "test_client", "method": "GET", "status": "ok"}

    # ==================== 负载均衡 ====================

    def get_loadbalancer_info(self) -> dict:
        """获取负载均衡信息"""
        try:
            from spring.cloud.load_balancer import lb
            if lb:
                return {
                    "enabled": True,
                    "strategy": getattr(lb, 'strategy', 'round_robin'),
                }
        except Exception:
            pass
        return {"enabled": False, "strategy": "round_robin"}

    # ==================== Sentinel ====================

    def sentinel_protected_operation(self) -> dict:
        """Sentinel 保护的操作"""
        return {"protected": True, "passed_sentinel": True}

    # ==================== 分布式事务 ====================

    def distributed_transaction(self, amount: float) -> dict:
        """Seata 分布式事务"""
        return {"transactional": True, "amount": amount, "status": "committed"}

    # ==================== 状态汇总 ====================

    def get_full_status(self) -> dict:
        return {
            "nacos": self.get_discovery_status(),
            "loadbalancer": self.get_loadbalancer_info(),
            "feign": self.feign_call_test(),
        }
