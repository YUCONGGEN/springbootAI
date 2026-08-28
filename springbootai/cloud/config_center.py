"""
Spring Cloud Config 配置中心客户端（对齐 Spring Cloud Config Client）

提供从配置中心拉取配置、动态刷新配置的能力。

功能：
- 支持HTTP后端（远程配置中心）和本地文件后端（开发环境）
- 启动时拉取配置并合并到应用配置
- 支持 /actuator/refresh 端点触发配置刷新
- 与 @RefreshScope 注解集成，刷新后自动重建Bean

与 Java Spring Cloud Config 的差异：
- Java 默认使用 Git 后端，Python 版本支持 HTTP API 和本地文件
- Java 通过 Spring Cloud Bus 广播刷新，Python 版本提供单节点刷新API
- Java 使用 Environment 对象，Python 使用字典

配置（application.yml）::

    spring:
      cloud:
        config:
          enabled: true
          uri: http://config-server:8888        # 配置中心地址（HTTP后端）
          # 或使用本地文件后端（开发环境）：
          # backend: file
          # file:
          #   path: ./config-repo
          name: myapp                            # 应用名（默认 springbootai.application.name）
          profile: dev                           # 环境（默认 springbootai.profiles.active）
          label: master                          # 分支/标签
          fail-fast: false                       # 拉取失败是否快速失败
          retry:
            max-attempts: 6                      # 最大重试次数
            initial-interval: 1000              # 初始重试间隔（毫秒）
            multiplier: 1.1                     # 重试间隔乘数
          timeout: 5000                          # 请求超时（毫秒）
"""
import hashlib
import json
import logging
import math
import re
import threading
import time
from copy import deepcopy
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import quote, urlsplit

from springbootai.logging.context import outbound_request_id, sanitize_url

logger = logging.getLogger("Spring.Cloud.Config")


def _as_bool(value: Any, default: bool = False) -> bool:
    """解析来自 YAML/环境变量的布尔配置，不让任意字符串被当成 True。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class ConfigCenterError(Exception):
    """配置中心异常"""


class ConfigCenterClient:
    """配置中心客户端

    单例模式，与 NacosDiscoveryClient 对齐。

    Usage::
        from springbootai.cloud.config_center import config_client, init_config_center

        # 在 application.yml 中配置后自动初始化
        # 手动使用：
        config_client.configure(config)
        remote_config = config_client.fetch()
        config_client.refresh()
    """

    _instance = None
    _lock = threading.Lock()
    _DEFAULT_TIMEOUT_MS = 5000
    _MAX_TIMEOUT_MS = 120000
    _DEFAULT_RETRY_MAX = 6
    _MAX_RETRY_MAX = 20
    _MAX_RETRY_INTERVAL_MS = 60000
    _DEFAULT_MAX_RESPONSE_SIZE = 5 * 1024 * 1024
    _MAX_RESPONSE_SIZE = 100 * 1024 * 1024

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._configured = False
        self._backend: str = 'http'  # 'http' 或 'file'
        self._uri: str = ''
        self._name: str = 'application'
        self._profile: str = 'default'
        self._label: str = 'master'
        self._fail_fast: bool = False
        self._timeout: int = 5000
        self._retry_max: int = 6
        self._retry_initial: int = 1000
        self._retry_multiplier: float = 1.1
        self._max_response_size: int = self._DEFAULT_MAX_RESPONSE_SIZE
        self._file_path: str = ''
        # 缓存上次拉取的配置（用于变更检测）
        self._cached_config: Dict[str, Any] = {}
        self._cached_hash: str = ''
        # ``fetch()`` 为了兼容旧 API 仍然以 ``{}`` 表示无数据。
        # 额外记录拉取是否真正成功，避免刷新时把网络故障
        # 返回的 ``{}`` 误当成“远程配置已全部删除”。
        self._last_fetch_succeeded: bool = False
        # 刷新回调列表（@RefreshScope Bean 重建回调）
        self._refresh_callbacks: List[Callable] = []
        # 配置变更监听器
        self._change_listeners: List[Callable[[Dict[str, Any], Dict[str, Any]], None]] = []

    def configure(self, config: dict) -> None:
        """从应用配置初始化配置中心客户端。

        Args:
            config: 应用配置字典（application.yml 解析后的完整配置）
        """
        # 配置可能来自 YAML、Nacos、环境变量或热更新；任何一层都可能是
        # ``null``/列表/标量。将其规范化为映射，避免可选配置中心的坏配置
        # 反向阻断整个应用启动。
        root = config if isinstance(config, Mapping) else {}
        spring = root.get('spring') if isinstance(root.get('spring'), Mapping) else {}
        cloud = spring.get('cloud') if isinstance(spring.get('cloud'), Mapping) else {}
        cloud_config = cloud.get('config') if isinstance(cloud.get('config'), Mapping) else {}
        if not _as_bool(cloud_config.get('enabled', False), False):
            self._configured = False
            # 关闭远程配置时丢弃旧快照，避免下一次重新开启时把上一个应用/环境
            # 的键误当成当前配置，也避免敏感配置在进程中无期限滞留。
            self._cached_config.clear()
            self._cached_hash = ''
            self._last_fetch_succeeded = False
            return

        backend = str(cloud_config.get('backend', 'http') or 'http').strip().lower()
        self._backend = backend if backend in {'http', 'file'} else 'http'
        uri = cloud_config.get('uri', 'http://localhost:8888')
        self._uri = str(uri or 'http://localhost:8888').strip().rstrip('/')
        application = spring.get('application') if isinstance(spring.get('application'), Mapping) else {}
        profiles = spring.get('profiles') if isinstance(spring.get('profiles'), Mapping) else {}
        self._name = str(cloud_config.get(
            'name',
            application.get('name', 'application'),
        ) or 'application').strip()
        self._profile = str(cloud_config.get(
            'profile',
            profiles.get('active', 'default'),
        ) or 'default').strip()
        self._label = str(cloud_config.get('label', 'master') or 'master').strip()
        self._fail_fast = _as_bool(cloud_config.get('fail-fast', False), False)
        self._timeout = self._bounded_int(
            cloud_config.get('timeout', self._DEFAULT_TIMEOUT_MS),
            self._DEFAULT_TIMEOUT_MS, 1, self._MAX_TIMEOUT_MS,
        )

        retry_cfg = cloud_config.get('retry') if isinstance(cloud_config.get('retry'), Mapping) else {}
        self._retry_max = self._bounded_int(
            retry_cfg.get('max-attempts', self._DEFAULT_RETRY_MAX),
            self._DEFAULT_RETRY_MAX, 1, self._MAX_RETRY_MAX,
        )
        self._retry_initial = self._bounded_int(
            retry_cfg.get('initial-interval', 1000), 1000,
            0, self._MAX_RETRY_INTERVAL_MS,
        )
        self._retry_multiplier = self._bounded_float(
            retry_cfg.get('multiplier', 1.1), 1.1, 1.0, 10.0,
        )
        self._max_response_size = self._bounded_int(
            cloud_config.get(
                'max-response-size', self._DEFAULT_MAX_RESPONSE_SIZE),
            self._DEFAULT_MAX_RESPONSE_SIZE, 1, self._MAX_RESPONSE_SIZE,
        )

        file_cfg = cloud_config.get('file') if isinstance(cloud_config.get('file'), Mapping) else {}
        self._file_path = str(file_cfg.get('path', './config-repo') or './config-repo')

        self._configured = True
        logger.info(
            f"ConfigCenter configured: backend={self._backend}, "
            f"name={self._name}, profile={self._profile}, label={self._label}"
        )

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    @staticmethod
    def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            parsed = default
        if not math.isfinite(parsed):
            parsed = default
        return max(minimum, min(parsed, maximum))

    @property
    def configured(self) -> bool:
        return self._configured

    def fetch(self) -> Dict[str, Any]:
        """从配置中心拉取配置。

        Returns:
            配置字典（已扁平化为 {key: value} 格式）

        Raises:
            ConfigCenterError: 拉取失败且 fail_fast=True
        """
        if not self._configured:
            self._last_fetch_succeeded = False
            return {}

        # 只有后端完成校验并显式设置 True 才算成功。
        # 这样任何提前返回或异常都会保留 last-known-good。
        self._last_fetch_succeeded = False
        if self._backend == 'file':
            return self._fetch_from_file()
        return self._fetch_from_http()

    def _fetch_from_http(self) -> Dict[str, Any]:
        """从HTTP配置中心拉取配置。

        请求格式：GET {uri}/{name}/{profile}/{label}
        响应格式（对齐 Spring Cloud Config Server）::
            {
                "name": "myapp",
                "profiles": ["dev"],
                "label": "master",
                "propertySources": [
                    {"name": "file:./config-repo/myapp-dev.yml", "source": {"key": "value"}}
                ]
            }
        """
        import requests

        try:
            parsed = urlsplit(self._uri)
            parsed.port
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                raise ValueError("URI must use http or https and include a host")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("URI must not contain embedded credentials")
        except (TypeError, ValueError) as exc:
            message = "Invalid config center HTTP URI"
            if self._fail_fast:
                raise ConfigCenterError(message) from exc
            logger.error(message)
            return {}

        segments = (self._name, self._profile, self._label)
        url = self._uri + "/" + "/".join(
            quote(str(segment), safe="") for segment in segments)
        safe_url = sanitize_url(url)
        last_error_type = "unknown"
        request_id = outbound_request_id()

        for attempt in range(1, self._retry_max + 1):
            resp = None
            try:
                # timeout 已通过 self._timeout / 1000 传入，Bandit B113 无法
                # 识别变量表达式形式的 timeout 参数，标记为 nosec 抑制误报
                resp = requests.get(  # nosec B113
                    url,
                    timeout=self._timeout / 1000,
                    headers={
                        'Accept': 'application/json',
                        'X-Request-ID': request_id,
                    },
                    stream=True,
                    allow_redirects=False,
                )
                if resp.status_code == 404:
                    logger.warning("Config not found at %s", safe_url)
                    self._last_fetch_succeeded = True
                    return {}
                if 300 <= resp.status_code < 400:
                    raise ConfigCenterError(
                        "Config center redirects are not allowed")
                resp.raise_for_status()
                response_headers = getattr(resp, 'headers', {}) or {}
                declared_size = response_headers.get(
                    'Content-Length', response_headers.get('content-length', ''))
                if declared_size:
                    try:
                        if int(declared_size) > self._max_response_size:
                            raise ConfigCenterError(
                                "Config center response exceeds configured size limit")
                    except ValueError:
                        pass
                iterator = getattr(resp, 'iter_content', None)
                if callable(iterator):
                    chunks = []
                    response_size = 0
                    for chunk in iterator(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        response_size += len(chunk)
                        if response_size > self._max_response_size:
                            raise ConfigCenterError(
                                "Config center response exceeds configured size limit")
                        chunks.append(chunk)
                    raw = b''.join(chunks)
                    data = json.loads(raw.decode('utf-8-sig'))
                else:
                    content = getattr(resp, 'content', None)
                    if (content is not None
                            and len(content) > self._max_response_size):
                        raise ConfigCenterError(
                            "Config center response exceeds configured size limit")
                    data = resp.json()
                if not isinstance(data, Mapping):
                    raise ConfigCenterError(
                        "Config center response must be a JSON object")
                property_sources = data.get('propertySources', [])
                if not isinstance(property_sources, list):
                    raise ConfigCenterError(
                        "Config center propertySources must be a list")
                # 合并所有 propertySources（前面的优先级更高）
                merged: Dict[str, Any] = {}
                for source in reversed(property_sources):
                    if not isinstance(source, Mapping):
                        raise ConfigCenterError(
                            "Config center property source must be an object")
                    values = source.get('source', {})
                    if not isinstance(values, Mapping):
                        raise ConfigCenterError(
                            "Config center property source values must be an object")
                    merged.update(values)
                logger.info(
                    f"Fetched config from {safe_url}: {len(merged)} properties, "
                    f"{len(property_sources)} sources"
                )
                self._last_fetch_succeeded = True
                return merged
            except Exception as exc:
                last_error_type = type(exc).__name__
                status = getattr(resp, 'status_code', None)
                retryable = not (
                    isinstance(exc, ConfigCenterError)
                    or (isinstance(status, int) and 400 <= status < 500 and status != 429)
                )
                if not retryable:
                    break
                if attempt < self._retry_max:
                    delay = min(
                        self._retry_initial * (self._retry_multiplier ** (attempt - 1)),
                        self._MAX_RETRY_INTERVAL_MS,
                    )
                    logger.warning(
                        "Config fetch attempt %d/%d failed error_type=%s; "
                        "retrying in %.0fms",
                        attempt, self._retry_max, last_error_type, delay,
                    )
                    time.sleep(delay / 1000)
            finally:
                closer = getattr(resp, 'close', None)
                if callable(closer):
                    closer()

        error_msg = (
            f"Failed to fetch config from {safe_url}: "
            f"error_type={last_error_type}"
        )
        if self._fail_fast:
            raise ConfigCenterError(error_msg)
        logger.error(error_msg)
        return {}

    def _fetch_from_file(self) -> Dict[str, Any]:
        """从本地文件后端拉取配置（开发环境）。

        查找顺序：
        1. {path}/{name}-{profile}.yml
        2. {path}/{name}.yml
        3. {path}/application-{profile}.yml
        4. {path}/application.yml
        """
        import yaml

        for value, name in ((self._name, 'name'), (self._profile, 'profile')):
            if (not value or value in {'.', '..'}
                    or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', value)):
                message = f"Invalid config center file {name}"
                if self._fail_fast:
                    raise ConfigCenterError(message)
                logger.error(message)
                return {}

        config_dir = Path(self._file_path).resolve()
        candidates = [
            config_dir / f"{self._name}-{self._profile}.yml",
            config_dir / f"{self._name}-{self._profile}.yaml",
            config_dir / f"{self._name}.yml",
            config_dir / f"{self._name}.yaml",
            config_dir / f"application-{self._profile}.yml",
            config_dir / f"application-{self._profile}.yaml",
            config_dir / "application.yml",
            config_dir / "application.yaml",
        ]

        merged: Dict[str, Any] = {}
        found = False
        load_failed = False
        # 从最低优先级向最高优先级合并，使列表前面的应用/Profile 专用
        # 配置最终覆盖通用 application 配置。
        for candidate in reversed(candidates):
            if candidate.exists():
                found = True
                try:
                    resolved_candidate = candidate.resolve()
                    if resolved_candidate.parent != config_dir:
                        raise ConfigCenterError(
                            "Config file resolves outside configured directory")
                    size = resolved_candidate.stat().st_size
                    if size > self._max_response_size:
                        raise ConfigCenterError(
                            "Config file exceeds configured size limit")
                    with open(resolved_candidate, 'rb') as file_handle:
                        raw = file_handle.read(self._max_response_size + 1)
                    if len(raw) > self._max_response_size:
                        raise ConfigCenterError(
                            "Config file exceeds configured size limit")
                    data = yaml.safe_load(raw.decode('utf-8')) or {}
                    if not isinstance(data, dict):
                        raise ConfigCenterError(
                            "Config file root must be a YAML object")
                    # 扁平化嵌套字典
                    flat = self._flatten(data)
                    merged.update(flat)
                    logger.info("Loaded config from %s", resolved_candidate)
                except Exception as exc:
                    load_failed = True
                    logger.warning(
                        "Failed to load config file=%s error_type=%s",
                        candidate.name, type(exc).__name__,
                    )
                    if self._fail_fast:
                        raise ConfigCenterError(
                            f"Failed to load config file: {candidate.name}"
                        ) from exc

        if not found:
            logger.warning(f"No config files found in {config_dir}")
        self._last_fetch_succeeded = found and not load_failed
        return merged

    @staticmethod
    def _flatten(data: Dict[str, Any], prefix: str = '') -> Dict[str, Any]:
        """扁平化嵌套字典为点分隔的key。

        例如: {"spring": {"datasource": {"url": "..."}}} → {"springbootai.datasource.url": "..."}
        """
        result: Dict[str, Any] = {}
        for k, v in data.items():
            # YAML 允许数字/布尔等非字符串键，而配置属性名和
            # ``json.dumps(sort_keys=True)`` 都需要稳定的字符串键。
            component = str(k)
            key = f"{prefix}.{component}" if prefix else component
            if isinstance(v, dict):
                nested = ConfigCenterClient._flatten(v, key)
                duplicate = result.keys() & nested.keys()
                if duplicate:
                    raise ConfigCenterError(
                        f"Duplicate normalized config key: {sorted(duplicate)[0]}")
                result.update(nested)
            else:
                if key in result:
                    raise ConfigCenterError(
                        f"Duplicate normalized config key: {key}")
                result[key] = v
        return result

    def refresh(self) -> Dict[str, Any]:
        """刷新配置并触发回调。

        Returns:
            变更的配置项字典 {key: new_value}
        """
        if not self._configured:
            return {}

        new_config = self.fetch()
        if not self._last_fetch_succeeded:
            logger.warning(
                "Config refresh failed; retaining last-known-good snapshot")
            return {}
        new_hash = hashlib.sha256(
            json.dumps(new_config, sort_keys=True, default=str).encode('utf-8')
        ).hexdigest()

        if new_hash == self._cached_hash:
            logger.info("Config unchanged, no refresh needed")
            return {}

        # 计算变更项
        changes: Dict[str, Any] = {}
        for k, v in new_config.items():
            if self._cached_config.get(k) != v:
                changes[k] = v
        for k in self._cached_config:
            if k not in new_config:
                changes[k] = None  # 已删除

        old_config = deepcopy(self._cached_config)
        self._cached_config = new_config
        self._cached_hash = new_hash

        logger.info(f"Config refreshed: {len(changes)} changes detected")

        # 触发配置变更监听器
        for listener in self._change_listeners:
            try:
                listener(old_config, new_config)
            except Exception as exc:
                logger.error(
                    "Config change listener failed error_type=%s",
                    type(exc).__name__,
                )

        # 触发 @RefreshScope Bean 重建回调
        for callback in self._refresh_callbacks:
            try:
                callback()
            except Exception as exc:
                logger.error(
                    "Refresh callback failed error_type=%s",
                    type(exc).__name__,
                )

        return changes

    def get_config(self) -> Dict[str, Any]:
        """获取缓存的配置。"""
        return deepcopy(self._cached_config)

    def register_refresh_callback(self, callback: Callable[[], None]) -> None:
        """注册配置刷新回调（@RefreshScope Bean 重建时调用）。

        Args:
            callback: 无参数回调函数
        """
        self._refresh_callbacks.append(callback)

    def register_change_listener(
        self, listener: Callable[[Dict[str, Any], Dict[str, Any]], None]
    ) -> None:
        """注册配置变更监听器。

        Args:
            listener: 监听器函数 (old_config, new_config) -> None
        """
        self._change_listeners.append(listener)

    def close(self) -> None:
        """清理资源。"""
        self._refresh_callbacks.clear()
        self._change_listeners.clear()
        self._cached_config.clear()
        self._cached_hash = ''
        self._last_fetch_succeeded = False


# 全局单例
config_client = ConfigCenterClient()


def init_config_center(config: dict) -> None:
    """从应用配置初始化配置中心客户端。

    Args:
        config: 应用配置字典
    """
    config_client.configure(config)
    if config_client.configured:
        try:
            remote_config = config_client.fetch()
            if config_client._last_fetch_succeeded:
                # 首次拉取是变更检测的基线，不应在第一次
                # /actuator/refresh 时把所有键都误报为新增。
                snapshot = deepcopy(remote_config)
                config_client._cached_config = snapshot
                config_client._cached_hash = hashlib.sha256(
                    json.dumps(
                        snapshot, sort_keys=True, default=str,
                    ).encode('utf-8')
                ).hexdigest()
            if remote_config:
                logger.info(f"Config center initialized with {len(remote_config)} properties")
        except ConfigCenterError as exc:
            if config_client._fail_fast:
                raise
            logger.error(
                "Config center init failed error_type=%s",
                type(exc).__name__,
            )


def create_config_refresh_endpoint() -> Callable:
    """创建 /actuator/refresh 端点的处理函数。

    Returns:
        FastAPI 路由处理函数
    """
    def refresh_config():
        changes = config_client.refresh()
        return {
            "status": "refreshed",
            "changed_keys": list(changes.keys()),
            "changed_count": len(changes),
        }
    return refresh_config
