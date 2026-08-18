"""
服务注册发现模块
集成 Nacos 作为注册中心
"""
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
from urllib.request import urlopen

# 可选导入Nacos
try:
    from nacos import NacosClient
except ImportError:
    NacosClient = None

logger = logging.getLogger("Spring.Cloud.Discovery")


class NacosDiscoveryClient:
    """Nacos服务注册发现客户端"""
    
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, server_addr: str = "localhost:8848", namespace: str = "", group: str = "DEFAULT_GROUP", username: str = "", password: str = ""):
        if hasattr(self, '_initialized'):
            # 已初始化：委托给 configure() 做原地更新，保持单一更新路径
            self.configure(server_addr=server_addr, namespace=namespace,
                           group=group, username=username, password=password)
            return
        self.server_addr = server_addr
        self.namespace = namespace
        self.group = group
        self.username = username
        self.password = password
        self._client: Optional[NacosClient] = None
        self._ready = False
        self._service_name: Optional[str] = None
        self._ip: str = "127.0.0.1"
        self._port: int = 8080
        self._initialized = True

    def configure(self, server_addr: Optional[str] = None, namespace: Optional[str] = None,
                  group: Optional[str] = None, username: Optional[str] = None,
                  password: Optional[str] = None) -> None:
        """重新配置单例的 Nacos 连接参数（读取配置后调用）。

        ``NacosDiscoveryClient`` 为单例，``__init__`` 的 ``_initialized`` 守卫会
        阻止后续 ``__init__`` 更新参数。``init_discovery`` 读取 ``application.yml``
        的 ``discovery.*`` 后，必须通过本方法重新配置，否则连接参数停留在默认值。

        参数变化时重置已建立的客户端连接，强制下次 ``connect()`` 重建。

        Args:
            server_addr: Nacos 服务地址，None 表示保留原值
            namespace: 命名空间，None 表示保留原值
            group: 分组，None 表示保留原值
            username: 用户名，None 表示保留原值
            password: 密码，None 表示保留原值
        """
        changed = False
        if server_addr is not None and self.server_addr != server_addr:
            self.server_addr = server_addr
            changed = True
        if namespace is not None and self.namespace != namespace:
            self.namespace = namespace
            changed = True
        if group is not None and self.group != group:
            self.group = group
            changed = True
        if username is not None and self.username != username:
            self.username = username
            changed = True
        if password is not None and self.password != password:
            self.password = password
            changed = True
        if changed:
            self._client = None
            self._ready = False
    
    def connect(self) -> None:
        """连接Nacos"""
        if NacosClient is None:
            logger.warning("Nacos SDK not installed, service discovery disabled")
            self._client = None
            self._ready = False
            return

        try:
            # nacos-sdk-python 使用 server_addresses 作为第一个参数
            # 开发环境如果没有配置认证，不传用户名密码也能连接
            client_kwargs = {"namespace": self.namespace}
            
            # 先尝试不带认证参数连接（开发环境常用）
            try:
                self._client = NacosClient(self.server_addr, **client_kwargs)
                # 测试连接是否正常 - 发送一个测试服务注册
                self._client.add_naming_instance(
                    service_name="_health_check",
                    ip="127.0.0.1",
                    port=0,
                    group_name=self.group,
                    ephemeral=True
                )
                # 立即注销测试服务
                try:
                    self._client.remove_naming_instance(
                        service_name="_health_check",
                        ip="127.0.0.1",
                        port=0,
                        group_name=self.group
                    )
                except Exception:
                    pass
            except Exception as e1:
                # 如果失败，尝试带认证参数
                if self.username:
                    client_kwargs.update({
                        "username": self.username,
                        "password": self.password,
                    })
                    try:
                        self._client = NacosClient(self.server_addr, **client_kwargs)
                    except TypeError:
                        client_kwargs.pop("username", None)
                        client_kwargs.pop("password", None)
                        self._client = NacosClient(self.server_addr, **client_kwargs)
                else:
                    raise
            self._ready = True
            logger.info(f"Connected to Nacos: {self.server_addr}")
        except Exception as e:
            logger.error(f"Failed to connect to Nacos: {e}")
            self._client = None
            self._ready = False

    def is_healthy(self, timeout: float = 2.0) -> bool:
        """Check the Nacos server liveness endpoint."""
        if not self._ready or self._client is None:
            return False

        server = self.server_addr.split(",", 1)[0].strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            server = f"http://{server}"
        health_url = f"{server}/nacos/v1/console/health/liveness"
        parsed = urlparse(health_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.error("Nacos health URL must use HTTP(S): %s", health_url)
            return False

        try:
            with urlopen(health_url, timeout=timeout) as response:  # nosec B310 - validated above
                return 200 <= response.status < 300
        except Exception as e:
            logger.debug(f"Nacos health check failed: {e}")
            return False
    
    def register_service(self, service_name: str, ip: str, port: int, metadata: Dict[str, Any] = None) -> bool:
        """
        注册服务到Nacos
        
        Args:
            service_name: 服务名称
            ip: 服务IP
            port: 服务端口
            metadata: 元数据
        
        Returns:
            是否成功
        """
        if self._client is None:
            self.connect()
        
        if self._client is None:
            logger.warning("Nacos client not available, skipping registration")
            return False
        
        try:
            self._service_name = service_name
            self._ip = ip
            self._port = port
            
            self._client.add_naming_instance(
                service_name=service_name,
                ip=ip,
                port=port,
                metadata=metadata or {},
                group_name=self.group
            )
            
            logger.info(f"Registered service: {service_name} at {ip}:{port}")
            return True
        except Exception as e:
            logger.error(f"Failed to register service {service_name}: {e}")
            return False

    # Compatibility aliases used by the example CloudService API.
    def register(self, service_name: str, ip: str, port: int,
                 metadata: Dict[str, Any] = None) -> bool:
        return self.register_service(service_name, ip, port, metadata)

    def get_services(self, page_no: int = 1, page_size: int = 100) -> List[str]:
        """Return registered service names when supported by the SDK."""
        if self._client is None:
            self.connect()
        if self._client is None:
            return []

        try:
            list_services = getattr(self._client, "list_naming_services")
            response = list_services(
                page_no=page_no,
                page_size=page_size,
                group_name=self.group,
            )
            if isinstance(response, dict):
                return response.get("doms") or response.get("serviceList") or []
            return list(response or [])
        except Exception as e:
            logger.error(f"Failed to list Nacos services: {e}")
            return []
    
    def deregister_service(self, service_name: str, ip: str, port: int) -> bool:
        """
        从Nacos注销服务
        
        Args:
            service_name: 服务名称
            ip: 服务IP
            port: 服务端口
        
        Returns:
            是否成功
        """
        if self._client is None:
            return False
        
        try:
            self._client.remove_naming_instance(
                service_name=service_name,
                ip=ip,
                port=port,
                group_name=self.group
            )
            logger.info(f"Deregistered service: {service_name} at {ip}:{port}")
            return True
        except Exception as e:
            logger.error(f"Failed to deregister service {service_name}: {e}")
            return False
    
    def get_service_instances(self, service_name: str) -> List[Dict[str, Any]]:
        """
        获取服务实例列表
        
        Args:
            service_name: 服务名称
        
        Returns:
            实例列表
        """
        if self._client is None:
            self.connect()
        
        if self._client is None:
            logger.warning("Nacos client not available, returning empty list")
            return []
        
        try:
            # SDK方法名是 list_naming_instance（单数）
            list_method = getattr(self._client, 'list_naming_instance', None)
            if list_method is None:
                list_method = getattr(self._client, 'list_naming_instances', None)
            
            instances = list_method(
                service_name=service_name,
                group_name=self.group
            )
            
            result = []
            if instances:
                # 兼容不同SDK版本的返回格式
                if isinstance(instances, dict):
                    hosts = instances.get('hosts', [])
                elif isinstance(instances, (list, tuple)):
                    hosts = instances
                else:
                    hosts = []
                
                for instance in hosts:
                    if hasattr(instance, 'ip'):
                        # 对象格式
                        result.append({
                            'ip': instance.ip,
                            'port': instance.port,
                            'weight': getattr(instance, 'weight', 1.0),
                            'healthy': getattr(instance, 'healthy', True),
                            'metadata': getattr(instance, 'metadata', {})
                        })
                    elif isinstance(instance, dict):
                        # 字典格式
                        result.append({
                            'ip': instance.get('ip', ''),
                            'port': instance.get('port', 0),
                            'weight': instance.get('weight', 1.0),
                            'healthy': instance.get('healthy', True),
                            'metadata': instance.get('metadata', {})
                        })
            
            return result
        except Exception as e:
            logger.error(f"Failed to get instances for {service_name}: {e}")
            return []
    
    def get_service_instance(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        获取单个服务实例（用于负载均衡）
        
        Args:
            service_name: 服务名称
        
        Returns:
            单个实例
        """
        instances = self.get_service_instances(service_name)
        if not instances:
            return None
        
        # 过滤健康实例
        healthy_instances = [i for i in instances if i.get('healthy', True)]
        if not healthy_instances:
            return None
        
        # 使用轮询策略选择实例
        return healthy_instances[0]
    
    def subscribe(self, service_name: str, callback) -> bool:
        """
        订阅服务变更
        
        Args:
            service_name: 服务名称
            callback: 回调函数
        
        Returns:
            是否成功
        """
        if self._client is None:
            self.connect()
        
        if self._client is None:
            return False
        
        try:
            self._client.add_naming_listener(
                service_name=service_name,
                group_name=self.group,
                cb=callback
            )
            logger.info(f"Subscribed to service: {service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe to {service_name}: {e}")
            return False


# 创建全局Nacos客户端实例
nacos_client = NacosDiscoveryClient()


def init_discovery(config: dict) -> None:
    """
    初始化服务注册发现

    通过 ``configure`` 重新配置单例 ``NacosDiscoveryClient``，使 ``discovery.*``
    配置生效。直接 ``NacosDiscoveryClient(...)`` 因单例 ``_initialized`` 守卫不会
    更新参数。

    Args:
        config: 配置字典，包含server_addr, namespace, group等
    """
    # 单例原地更新配置，避免 _initialized 守卫导致配置被忽略
    nacos_client.configure(
        server_addr=config.get('server_addr', 'localhost:8848'),
        namespace=config.get('namespace', ''),
        group=config.get('group', 'DEFAULT_GROUP'),
        username=config.get('username', ''),
        password=config.get('password', ''),
    )
    nacos_client.connect()
    return nacos_client
