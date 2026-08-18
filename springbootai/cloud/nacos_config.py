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
            timeout_ms=_as_positive_int(value("NACOS_CONFIG_TIMEOUT_MS", "timeout-ms", "timeout_ms", default=5000), 5000),
            fail_fast=_as_bool(value("NACOS_CONFIG_FAIL_FAST", "fail-fast", "fail_fast", default=False)),
            refresh_enabled=_as_bool(value("NACOS_CONFIG_REFRESH_ENABLED", "refresh-enabled", "refresh_enabled", default=True), True),
            refresh_interval_seconds=_as_positive_int(
                value("NACOS_CONFIG_REFRESH_INTERVAL_SECONDS", "refresh-interval-seconds", "refresh_interval_seconds", default=5),
                5,
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

    def configure(self, properties: NacosConfigProperties) -> None:
        """更新引导参数；地址、Data ID 等变更时重建 SDK 客户端。"""
        if properties != self.properties:
            self.close()
            self.properties = properties
            self._client = None
            self._clients.clear()
            self._last_content = None

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
        # 先复用上一次成功的客户端；没有成功记录时先尝试匿名，再按需
        # 尝试账号密码。客户端对象只在首次使用时创建，后续刷新直接复用。
        clients = []
        if self._client is not None:
            clients.append(self._client)
        else:
            anonymous = self._clients.get(False)
            if anonymous is None:
                anonymous = self._new_client(False)
                self._clients[False] = anonymous
            clients.append(anonymous)
        if self.properties.username and self.properties.password:
            authenticated = self._clients.get(True)
            if authenticated is None:
                authenticated = self._new_client(True)
                self._clients[True] = authenticated
            if authenticated not in clients:
                clients.append(authenticated)
        for client in clients:
            try:
                content = client.get_config(
                    self.properties.data_id,
                    self.properties.group,
                    timeout=self.properties.timeout_ms / 1000,
                )
                self._client = client
                return content
            except Exception as exc:
                errors.append(exc)
        raise NacosConfigError(
            f"无法读取 Nacos 配置 dataId={self.properties.data_id!r}, "
            f"group={self.properties.group!r}, server={self.properties.server_addr!r}: {errors[-1]}"
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
        self._last_content = str(content)
        return parsed

    def start_listener(self, on_change: Callable[[], None]) -> None:
        """监听 Nacos 变更，内容合法时通知 ConfigLoader 重新加载并刷新 Bean。

        ``nacos-sdk-python`` 的 watcher 在 Windows 上会启动无法可靠关闭的子进程。
        框架因此使用受控后台轮询：启动/关闭可预测，兼容 Windows、Docker 与 SDK
        不同版本，同时仍能自动发现 Nacos 配置变化。
        """
        if not self.properties.refresh_enabled or self._client is None or self._listener_thread:
            return
        self._change_callback = on_change
        self._stop_event.clear()

        def poll() -> None:
            interval = self.properties.refresh_interval_seconds
            while not self._stop_event.wait(interval):
                try:
                    content = self._get_content()
                    if content is None or str(content) == self._last_content:
                        continue
                    parsed = yaml.safe_load(content) or {}
                    if not isinstance(parsed, dict):
                        raise NacosConfigError("Nacos YAML 根节点必须是对象")
                    self._last_content = str(content)
                    logger.info("Nacos config changed: dataId=%s", self.properties.data_id)
                    on_change()
                except Exception as exc:
                    # 暂时网络抖动或一次错误更新不应终止后续监听。
                    logger.error("Ignoring Nacos config refresh failure: %s", exc)

        self._listener_thread = threading.Thread(
            target=poll,
            name=f"nacos-config-{self.properties.data_id}",
            daemon=True,
        )
        self._listener_thread.start()
        logger.info(
            "Nacos config refresh listener started: %s (interval=%ss)",
            self.properties.data_id, self.properties.refresh_interval_seconds,
        )

    def close(self) -> None:
        self._stop_event.set()
        thread = self._listener_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._listener_thread = None
        self._change_callback = None
        self._client = None
        self._clients.clear()


def bootstrap_nacos_config(
    local_config: Dict[str, Any],
    existing_client: Optional[NacosConfigClient] = None,
) -> tuple[Optional[NacosConfigClient], Dict[str, Any]]:
    """加载启动期远程配置；调用方根据 fail-fast 决定是否中止启动。"""
    properties = NacosConfigProperties.from_sources(local_config)
    if not properties.enabled:
        return None, {}

    client = existing_client or NacosConfigClient(properties)
    client.configure(properties)
    try:
        remote_config = client.fetch()
    except NacosConfigError:
        if properties.fail_fast:
            raise
        logger.warning("Nacos Config unavailable; continuing with local/framework defaults", exc_info=True)
        return client, {}
    logger.info(
        "Loaded Nacos config: dataId=%s, group=%s", properties.data_id, properties.group
    )
    return client, remote_config
