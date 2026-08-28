"""
服务注册发现模块
集成 Nacos 作为注册中心
"""
import logging
import math
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
from urllib.request import urlopen

from springbootai.logging.context import redact_sensitive, sanitize_url

# 可选导入Nacos
try:
    from nacos import NacosClient
except ImportError:
    NacosClient = None

logger = logging.getLogger("Spring.Cloud.Discovery")


def _safe_log_field(value: Any, limit: int = 160) -> str:
    """Return a bounded, single-line and credential-redacted log field."""
    try:
        text = redact_sensitive(value)
    except Exception:
        text = f"<unprintable:{type(value).__name__}>"
    text = (
        text.replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return text if len(text) <= limit else text[:limit] + "..."


def _safe_endpoint(value: Any) -> str:
    """Sanitize one or more comma-separated Nacos endpoints for logs."""
    endpoints = []
    for item in str(value or "").split(","):
        item = item.strip()
        endpoints.append(
            sanitize_url(item) if "://" in item else _safe_log_field(item)
        )
    return _safe_log_field(",".join(endpoints))


class NacosDiscoveryClient:
    """Nacos服务注册发现客户端"""

    # Nacos SDK 的 ``default_timeout`` 是每个 HTTP 请求的超时时间。
    # 这里提供一个有限且较短的默认值，避免可选的 Nacos 服务不可用时
    # 阻塞应用启动；用户仍可通过 discovery.timeout（或环境变量）调大。
    DEFAULT_TIMEOUT_SECONDS = 3.0
    MAX_TIMEOUT_SECONDS = 60.0
    
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, server_addr: str = "localhost:8848", namespace: str = "", group: str = "DEFAULT_GROUP", username: str = "", password: str = "", timeout: Optional[float] = None):
        if hasattr(self, '_initialized'):
            # 已初始化：委托给 configure() 做原地更新，保持单一更新路径
            self.configure(server_addr=server_addr, namespace=namespace,
                           group=group, username=username, password=password,
                           timeout=timeout)
            return
        self.server_addr = server_addr
        self.namespace = namespace
        self.group = group
        self.username = username
        self.password = password
        self.timeout = self._normalize_timeout(
            self.DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
        )
        self._client: Optional[NacosClient] = None
        self._ready = False
        self._service_name: Optional[str] = None
        self._ip: str = "127.0.0.1"
        self._port: int = 8080
        self._initialized = True

    def configure(self, server_addr: Optional[str] = None, namespace: Optional[str] = None,
                  group: Optional[str] = None, username: Optional[str] = None,
                  password: Optional[str] = None,
                  timeout: Optional[float] = None,
                  timeout_seconds: Optional[float] = None,
                  connect_timeout: Optional[float] = None,
                  request_timeout: Optional[float] = None) -> None:
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
            timeout: Nacos HTTP 请求超时时间（秒），None 表示保留原值。
                超时时间始终限制在 (0, 60] 秒，防止误配置导致启动无限等待。
            timeout_seconds/connect_timeout/request_timeout: ``timeout`` 的
                兼容别名；同时提供时按 ``timeout`` 优先。
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
        timeout = next(
            (item for item in (timeout, timeout_seconds, connect_timeout, request_timeout)
             if item is not None),
            None,
        )
        if timeout is not None:
            normalized_timeout = self._normalize_timeout(timeout)
            if self.timeout != normalized_timeout:
                self.timeout = normalized_timeout
                changed = True
        if changed:
            self._client = None
            self._ready = False

    @classmethod
    def _normalize_timeout(cls, value: Any) -> float:
        """将超时配置规范化为安全的有限值。

        配置通常来自 YAML、环境变量或 Nacos，可能出现空字符串、字典或
        ``NaN``。可选组件不应因这些输入让整个应用启动失败，因此统一回退
        到默认值；极大值则截断到上限，确保网络调用不会无限期阻塞。
        """
        if isinstance(value, dict):
            value = value.get("seconds", value.get("timeout", value.get("value")))
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            timeout = cls.DEFAULT_TIMEOUT_SECONDS
        if not math.isfinite(timeout) or timeout <= 0:
            timeout = cls.DEFAULT_TIMEOUT_SECONDS
        return min(timeout, cls.MAX_TIMEOUT_SECONDS)

    def _apply_client_timeout(self, client: Any) -> None:
        """把框架超时应用到 Nacos SDK 实例。

        ``nacos-sdk-python`` 不同版本没有统一的构造器 timeout 参数，直接
        传参会在旧版本抛 ``TypeError``。SDK 实例都暴露 ``default_timeout``，
        因而在构造成功后赋值，兼容各版本并覆盖 SDK 默认值。
        """
        try:
            client.default_timeout = self.timeout
        except Exception as exc:
            # 第三方替身或未来 SDK 可能使用只读属性；连接本身仍可继续，
            # 但不会把兼容性问题升级为应用启动异常。
            logger.debug(
                "Unable to apply Nacos request timeout error_type=%s",
                _safe_log_field(type(exc).__name__),
            )
    
    def connect(self) -> None:
        """连接Nacos"""
        if NacosClient is None:
            logger.warning("Nacos SDK not installed, service discovery disabled")
            self._client = None
            self._ready = False
            return

        try:
            # nacos-sdk-python 使用 server_addresses 作为第一个参数
            # 先无认证构造客户端，再把用户名密码写入实例后探测。这样可以
            # 在构造器触发登录请求前应用自定义 timeout；否则 SDK 构造器会
            # 使用其硬编码的默认 3 秒，导致认证连接忽略框架配置。
            client_kwargs = {"namespace": self.namespace}
            self._client = NacosClient(self.server_addr, **client_kwargs)
            self._apply_client_timeout(self._client)
            if self.username:
                # nacos-sdk-python 通过实例属性决定是否在请求中获取 token；
                # setattr 也兼容只实现了最小构造器的测试替身/旧 SDK。
                try:
                    self._client.username = self.username
                    self._client.password = self.password
                except Exception as exc:
                    logger.debug(
                        "Unable to apply Nacos credentials error_type=%s",
                        _safe_log_field(type(exc).__name__),
                    )
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
            self._ready = True
            logger.info(
                "Connected to Nacos endpoint=%s",
                _safe_endpoint(self.server_addr),
            )
        except Exception as exc:
            logger.error(
                "Failed to connect to Nacos endpoint=%s error_type=%s",
                _safe_endpoint(self.server_addr),
                _safe_log_field(type(exc).__name__),
            )
            self._client = None
            self._ready = False

    def is_healthy(self, timeout: Optional[float] = None) -> bool:
        """Check the Nacos server liveness endpoint."""
        if not self._ready or self._client is None:
            return False

        server = self.server_addr.split(",", 1)[0].strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            server = f"http://{server}"
        health_url = f"{server}/nacos/v1/console/health/liveness"
        parsed = urlparse(health_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            logger.error(
                "Nacos health URL must use HTTP(S) endpoint=%s",
                sanitize_url(health_url),
            )
            return False

        probe_timeout = self.timeout if timeout is None else self._normalize_timeout(timeout)
        try:
            with urlopen(health_url, timeout=probe_timeout) as response:  # nosec B310 - validated above
                return 200 <= response.status < 300
        except Exception as exc:
            logger.debug(
                "Nacos health check failed endpoint=%s error_type=%s",
                sanitize_url(health_url),
                _safe_log_field(type(exc).__name__),
            )
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
            
            logger.info(
                "Registered Nacos service service=%s endpoint=%s:%s",
                _safe_log_field(service_name),
                _safe_log_field(ip),
                _safe_log_field(port),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to register Nacos service service=%s error_type=%s",
                _safe_log_field(service_name),
                _safe_log_field(type(exc).__name__),
            )
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
        except Exception as exc:
            logger.error(
                "Failed to list Nacos services error_type=%s",
                _safe_log_field(type(exc).__name__),
            )
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
            logger.info(
                "Deregistered Nacos service service=%s endpoint=%s:%s",
                _safe_log_field(service_name),
                _safe_log_field(ip),
                _safe_log_field(port),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to deregister Nacos service service=%s error_type=%s",
                _safe_log_field(service_name),
                _safe_log_field(type(exc).__name__),
            )
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
        except Exception as exc:
            logger.error(
                "Failed to get Nacos instances service=%s error_type=%s",
                _safe_log_field(service_name),
                _safe_log_field(type(exc).__name__),
            )
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
            logger.info(
                "Subscribed to Nacos service service=%s",
                _safe_log_field(service_name),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to subscribe to Nacos service service=%s error_type=%s",
                _safe_log_field(service_name),
                _safe_log_field(type(exc).__name__),
            )
            return False


# 创建全局Nacos客户端实例
nacos_client = NacosDiscoveryClient()


def _first_timeout(config: dict) -> float:
    """从 discovery 配置读取兼容的超时字段。

    早期版本没有超时选项，调用方可能只提供 ``connect_timeout`` 或
    ``request_timeout``。统一接受这些别名，且把非法值交给客户端规范化，
    这样 YAML、环境变量和 Nacos 热更新都走同一条安全路径。
    """
    if not isinstance(config, dict):
        return NacosDiscoveryClient.DEFAULT_TIMEOUT_SECONDS
    for name in ("timeout", "timeout_seconds", "connect_timeout", "request_timeout"):
        value = config.get(name)
        if value is not None:
            return value
    return NacosDiscoveryClient.DEFAULT_TIMEOUT_SECONDS


def init_discovery(config: dict) -> None:
    """
    初始化服务注册发现

    通过 ``configure`` 重新配置单例 ``NacosDiscoveryClient``，使 ``discovery.*``
    配置生效。直接 ``NacosDiscoveryClient(...)`` 因单例 ``_initialized`` 守卫不会
    更新参数。

    Args:
        config: 配置字典，包含 server_addr、namespace、group 及可选 timeout（秒）
    """
    if not isinstance(config, dict):
        # 可选组件配置缺失/类型错误时采用安全默认，不让启动阶段
        # 因 ``None.get`` 这类低级异常中断整个应用。
        config = {}
    # 单例原地更新配置，避免 _initialized 守卫导致配置被忽略
    nacos_client.configure(
        server_addr=config.get('server_addr', 'localhost:8848'),
        namespace=config.get('namespace', ''),
        group=config.get('group', 'DEFAULT_GROUP'),
        username=config.get('username', ''),
        password=config.get('password', ''),
        timeout=_first_timeout(config),
    )
    nacos_client.connect()
    return nacos_client
