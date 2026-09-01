"""Nacos Config 启动引导与动态刷新支持。

本模块只负责 Nacos 的配置发布/读取，不与 ``discovery.py`` 的服务注册发现
混用。应用启动时由 :class:`ConfigLoader` 在创建 IoC 容器前调用，因此远程 YAML
可以配置端口、数据源、JWT 等启动期组件。

本地 ``application.yml`` 不是必需的。部署环境只要提供 ``NACOS_CONFIG_*`` 引导
变量即可，例如 ``NACOS_CONFIG_ENABLED=true``、``NACOS_CONFIG_DATA_ID=app-dev.yml``。
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import yaml

logger = logging.getLogger("Spring.Cloud.NacosConfig")


class NacosConfigError(RuntimeError):
    """Nacos Config 无法读取或内容无法解析时抛出的异常。"""


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _as_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _as_bounded_positive_int(value: Any, default: int, maximum: int) -> int:
    """解析正整数并限制上界，防止错误配置造成超长阻塞或休眠。"""
    number = _as_positive_int(value, default)
    return min(number, maximum)


@dataclass(frozen=True)
class NacosConfigProperties:
    """Nacos Config 的最小引导信息。"""

    enabled: bool
    server_addr: str
    data_id: str
    group: str = "DEFAULT_GROUP"
    namespace: str = ""
    username: str = ""
    password: str = ""
    timeout_ms: int = 5000
    fail_fast: bool = False
    refresh_enabled: bool = True
    refresh_interval_seconds: int = 5

    @classmethod
    def from_sources(cls, config: Dict[str, Any]) -> "NacosConfigProperties":
        """从本地引导 YAML 和环境变量读取配置。

        环境变量优先级最高，因此生产环境可完全不放本地业务配置。
        标准路径为 ``spring.cloud.nacos.config``，同时兼容 ``nacos.config``。
        """
        config = config if isinstance(config, dict) else {}
        spring = config.get("spring", {}) if isinstance(config.get("spring"), dict) else {}
        cloud = spring.get("cloud", {}) if isinstance(spring.get("cloud"), dict) else {}
        nacos = cloud.get("nacos", {}) if isinstance(cloud.get("nacos"), dict) else {}
        nacos_config = nacos.get("config", {}) if isinstance(nacos.get("config"), dict) else {}
        if not nacos_config:
            root_nacos = config.get("nacos", {}) if isinstance(config.get("nacos"), dict) else {}
            nacos_config = root_nacos.get("config", {}) if isinstance(root_nacos.get("config"), dict) else {}

        profiles = spring.get("profiles", {}) if isinstance(spring.get("profiles"), dict) else {}
        application = spring.get("application", {}) if isinstance(spring.get("application"), dict) else {}
        profile = os.getenv("SPRING_PROFILES_ACTIVE") or profiles.get("active") or "default"
        app_name = os.getenv("SPRING_APPLICATION_NAME") or application.get("name") or "application"
        default_data_id = f"{app_name}-{profile}.yml" if profile != "default" else f"{app_name}.yml"

        def value(env_name: str, *keys: str, default: Any = "") -> Any:
            env_value = os.getenv(env_name)
            if env_value is not None:
                return env_value
            for key in keys:
                if key in nacos_config and nacos_config[key] is not None:
                    return nacos_config[key]
            return default

        enabled = _as_bool(value("NACOS_CONFIG_ENABLED", "enabled", default=False))
        return cls(
            enabled=enabled,
            server_addr=str(value(
                "NACOS_CONFIG_SERVER_ADDR", "server-addr", "server_addr",
                default=os.getenv("NACOS_SERVER", "127.0.0.1:8848"),
            )).strip(),
            data_id=str(value("NACOS_CONFIG_DATA_ID", "data-id", "data_id", default=default_data_id)).strip(),
            group=str(value("NACOS_CONFIG_GROUP", "group", default="DEFAULT_GROUP")).strip() or "DEFAULT_GROUP",
            namespace=str(value("NACOS_CONFIG_NAMESPACE", "namespace", default="")).strip(),
            username=str(value("NACOS_CONFIG_USERNAME", "username", default="")).strip(),
            password=str(value("NACOS_CONFIG_PASSWORD", "password", default="")),
            # SDK 请求超时最多 120 秒；监听周期最多 1 小时。超过上限时
            # 自动收敛到安全上限，避免误填大整数让启动/关闭看似“卡死”。
            timeout_ms=_as_bounded_positive_int(
                value("NACOS_CONFIG_TIMEOUT_MS", "timeout-ms", "timeout_ms", default=5000),
                5000, 120_000,
            ),
            fail_fast=_as_bool(value("NACOS_CONFIG_FAIL_FAST", "fail-fast", "fail_fast", default=False)),
            refresh_enabled=_as_bool(value("NACOS_CONFIG_REFRESH_ENABLED", "refresh-enabled", "refresh_enabled", default=True), True),
            refresh_interval_seconds=_as_bounded_positive_int(
                value("NACOS_CONFIG_REFRESH_INTERVAL_SECONDS", "refresh-interval-seconds", "refresh_interval_seconds", default=5),
                5, 3600,
            ),
        )


class NacosConfigClient:
    """Nacos Config 客户端，支持 YAML 拉取和受控后台轮询监听。"""

    def __init__(self, properties: NacosConfigProperties):
        self.properties = properties
        self._client = None
        # 缓存两种认证模式的 SDK 客户端。轮询线程会频繁读取配置，不能在
        # 每次轮询时重新创建带用户名密码的 NacosClient，否则会不断建立
        # 登录会话并泄漏连接。
        self._clients: Dict[bool, Any] = {}
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._change_callback: Optional[Callable[[], None]] = None
        self._last_content: Optional[str] = None
        # 监听、reload 与 close 可能并发访问 SDK 客户端和版本字段。
        self._state_lock = threading.RLock()
        self._content_lock = threading.RLock()
        # stop_event 会在新线程启动时清空，generation 防止旧线程复活。
        self._listener_generation = 0
        self._listener_failures = 0

    def configure(self, properties: NacosConfigProperties) -> None:
        """更新引导参数；地址、Data ID 等变更时安全重建 SDK 客户端。"""
        with self._state_lock:
            if properties == self.properties:
                return
        self.close()
        with self._state_lock:
            self.properties = properties
            self._client = None
            self._clients.clear()
            with self._content_lock:
                self._last_content = None
            self._listener_failures = 0

    def _new_client(self, authenticated: bool = False):
        try:
            import nacos
        except ImportError as exc:
            raise NacosConfigError(
                "未安装 nacos-sdk-python；请安装 springbootAI[nacos]"
            ) from exc

        kwargs: Dict[str, Any] = {"namespace": self.properties.namespace}
        if authenticated and self.properties.username and self.properties.password:
            kwargs.update(username=self.properties.username, password=self.properties.password)
        return nacos.NacosClient(self.properties.server_addr, **kwargs)

    def _get_content(self) -> Optional[str]:
        """优先无认证读取，认证服务拒绝后再带账号密码重试。"""
        errors = []
        # 创建/复用客户端与 properties 读取串行，避免 close 清空正在使用的 SDK。
        with self._state_lock:
            properties = self.properties
            clients = []
            if self._client is not None:
                clients.append(self._client)
            else:
                anonymous = self._clients.get(False)
                if anonymous is None:
                    anonymous = self._new_client(False)
                    self._clients[False] = anonymous
                clients.append(anonymous)
            if properties.username and properties.password:
                authenticated = self._clients.get(True)
                if authenticated is None:
                    authenticated = self._new_client(True)
                    self._clients[True] = authenticated
                if authenticated not in clients:
                    clients.append(authenticated)
            for client in clients:
                try:
                    content = client.get_config(
                        properties.data_id, properties.group,
                        timeout=properties.timeout_ms / 1000,
                    )
                    self._client = client
                    return content
                except Exception as exc:
                    errors.append(exc)
        detail = errors[-1] if errors else "unknown error"
        raise NacosConfigError(
            f"无法读取 Nacos 配置 dataId={properties.data_id!r}, "
            f"group={properties.group!r}, server={properties.server_addr!r}: {detail}"
        )

    def fetch(self) -> Dict[str, Any]:
        """读取并解析 Nacos 中的 YAML 配置。"""
        content = self._get_content()
        if content is None or not str(content).strip():
            raise NacosConfigError(
                f"Nacos 配置不存在或为空: dataId={self.properties.data_id!r}, group={self.properties.group!r}"
            )
        try:
            parsed = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise NacosConfigError(
                f"Nacos 配置不是合法 YAML: dataId={self.properties.data_id!r}: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise NacosConfigError("Nacos YAML 根节点必须是对象")
        with self._content_lock:
            self._last_content = str(content)
        return parsed

    def start_listener(self, on_change: Callable[[], None]) -> None:
        """启动一个可控轮询监听器；重复调用不会创建多个线程。"""
        with self._state_lock:
            if not self.properties.refresh_enabled or self._client is None:
                return
            if self._listener_thread is not None and self._listener_thread.is_alive():
                return
            self._listener_generation += 1
            generation = self._listener_generation
            self._change_callback = on_change
            self._stop_event.clear()
            interval = max(1, self.properties.refresh_interval_seconds)

        def is_current() -> bool:
            with self._state_lock:
                return generation == self._listener_generation and not self._stop_event.is_set()

        def poll() -> None:
            wait_seconds = interval
            try:
                while is_current():
                    if self._stop_event.wait(wait_seconds) or not is_current():
                        break
                    callback_failed = False
                    try:
                        content = self._get_content()
                        with self._content_lock:
                            previous_content = self._last_content
                        if content is None or str(content) == previous_content:
                            self._listener_failures = 0
                            continue
                        parsed = yaml.safe_load(content) or {}
                        if not isinstance(parsed, dict):
                            raise NacosConfigError("Nacos YAML 根节点必须是对象")
                        logger.info("Nacos config changed: dataId=%s", self.properties.data_id)
                        if not is_current():
                            break
                        try:
                            callback_failed = True
                            on_change()
                        except Exception:
                            with self._content_lock:
                                self._last_content = previous_content
                            raise
                        with self._content_lock:
                            self._last_content = str(content)
                        self._listener_failures = 0
                        wait_seconds = interval
                    except Exception as exc:
                        if callback_failed:
                            # Bean/Web 刷新失败通常是瞬态依赖问题；保持基础周期，
                            # 让下一轮尽快重试，且保留旧版本标记。
                            self._listener_failures = 0
                            wait_seconds = interval
                        else:
                            # Nacos 网络/解析故障采用有限指数退避，避免在服务
                            # 不可用时刷满日志；上限仍会定期探测恢复。
                            self._listener_failures = min(self._listener_failures + 1, 6)
                            wait_seconds = min(
                                interval * (2 ** self._listener_failures),
                                interval * 32,
                            )
                        if self._listener_failures in {1, 2, 4, 6} or callback_failed:
                            logger.error(
                                "Ignoring Nacos config refresh failure "
                                "error_type=%s", type(exc).__name__)
                        else:
                            logger.debug(
                                "Ignoring Nacos config refresh failure "
                                "error_type=%s", type(exc).__name__)
            finally:
                with self._state_lock:
                    if self._listener_generation == generation:
                        self._listener_thread = None

        thread = threading.Thread(
            target=poll, name=f"nacos-config-{self.properties.data_id}", daemon=True,
        )
        with self._state_lock:
            self._listener_thread = thread
        thread.start()
        logger.info(
            "Nacos config refresh listener started: %s (interval=%ss)",
            self.properties.data_id, interval,
        )

    def close(self) -> None:
        """停止监听并释放 SDK 客户端；可从监听回调线程安全调用。"""
        with self._state_lock:
            self._listener_generation += 1
            self._stop_event.set()
            thread = self._listener_thread
            self._listener_thread = None
            self._change_callback = None
            timeout = min(max(self.properties.timeout_ms / 1000 + 1, 1), 10)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._state_lock:
            self._client = None
            self._clients.clear()


def bootstrap_nacos_config(
    local_config: Dict[str, Any],
    existing_client: Optional[NacosConfigClient] = None,
    *,
    raise_on_unavailable: bool = False,
) -> tuple[Optional[NacosConfigClient], Dict[str, Any]]:
    """加载启动期或刷新期远程配置。

    启动阶段默认遵循 ``fail_fast``：可选的 Nacos 不可用时继续使用本地
    配置。刷新阶段则应把瞬时读取失败交给监听器重试，因此调用方可以通过
    ``raise_on_unavailable=True`` 强制向上抛出本次读取错误，而不会把一次
    未完成的刷新误记录成成功。
    """
    properties = NacosConfigProperties.from_sources(local_config)
    if not properties.enabled:
        return None, {}

    client = existing_client or NacosConfigClient(properties)
    client.configure(properties)
    try:
        remote_config = client.fetch()
    except NacosConfigError:
        if properties.fail_fast or raise_on_unavailable:
            raise
        logger.warning("Nacos Config unavailable; continuing with local/framework defaults", exc_info=True)
        return client, {}
    logger.info(
        "Loaded Nacos config: dataId=%s, group=%s", properties.data_id, properties.group
    )
    return client, remote_config
