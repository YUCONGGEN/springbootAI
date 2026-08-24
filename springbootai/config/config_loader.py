"""
配置加载器
支持从YAML文件和环境变量加载配置
"""
import os
import sys
import yaml
import logging
import re
import threading
import time
from urllib.parse import quote_plus
from copy import deepcopy
from typing import Callable, Dict, Any, Optional

from .config_monitor import ConfigMonitor, resolve_config_monitor_config

logger = logging.getLogger("Spring.Config")


class ConfigurationError(ValueError):
    """应用配置缺失、格式错误或不满足生产安全要求。"""


# 匹配非字母数字字符（kebab/camel/snake 分隔符）用于松散匹配规范化
_NON_ALNUM = re.compile(r'[^0-9a-zA-Z]+')


def _normalize_name(name: str) -> str:
    """规范化命名：去除分隔符并小写，用于 ``get()`` 的松散匹配。

    ``log_dir`` / ``log-dir`` / ``LOG_DIR`` / ``log.dir`` → ``logdir``。
    与 ``springbootai.config.binding._normalize`` 保持一致，避免循环导入在此独立定义。
    """
    if not isinstance(name, str):
        return str(name).lower()
    return _NON_ALNUM.sub('', name).lower()


def _to_bool(value: Any, default: bool = False) -> bool:
    """统一布尔转换：接受 ``true/1/yes/on``（大小写不敏感），其余为 False。

    与 ``springbootai.config.binding._coerce`` 的布尔规则保持一致，避免
    ``REDIS_ENABLED=1`` 在 ``@ConfigurationProperties`` 绑定为 True 而在
    ``_override_with_env`` 中被识别为 False 的行为不一致。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')


class ConfigLoader:
    """配置加载器"""

    # ApplicationContext updates this after startup so later ``ConfigLoader()``
    # calls resolve the same application.yml instead of depending on CWD.
    _default_base_path: Optional[str] = None

    # 环境变量替换模式：${ENV_VAR} 或 ${ENV_VAR:default}（单层，用于 fullmatch 判定）
    _ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')
    # 最内层占位符：内容不含 ${，用于迭代解析嵌套占位符 ${A:${B:default}}
    _INNER_ENV_VAR_PATTERN = re.compile(r'\$\{([^${}]*)\}')
    _VALUE_EXPRESSION_PATTERN = re.compile(r'^\$\{([^}:]+)(?::(.*))?\}$')
    _MISSING = object()

    # Only these process variables are configuration inputs.  Looking at the
    # entire process environment would incorrectly label every reload as an
    # environment-sourced change on CI/Windows, where many unrelated variables
    # are always present.
    _CONFIG_ENV_NAMES = frozenset({
        'SPRING_PROFILES_ACTIVE', 'SPRING_APPLICATION_NAME', 'STARTUP_FAIL_FAST',
        'REDIS_HOST', 'REDIS_PORT', 'REDIS_DB', 'REDIS_PASSWORD', 'REDIS_ENABLED',
        'JWT_SECRET_KEY', 'JWT_ALGORITHM',
        'DB_URL', 'DB_ECHO', 'DB_ENABLED', 'DB_DRIVER', 'DB_HOST', 'DB_PORT',
        'DB_NAME', 'DB_USERNAME', 'DB_PASSWORD',
        'NACOS_SERVER', 'NACOS_NAMESPACE', 'NACOS_GROUP', 'NACOS_USERNAME',
        'NACOS_PASSWORD', 'DISCOVERY_SERVER_ADDR', 'DISCOVERY_NAMESPACE',
        'DISCOVERY_GROUP', 'DISCOVERY_ENABLED', 'NACOS_TIMEOUT',
        'NACOS_TIMEOUT_SECONDS', 'NACOS_CONNECT_TIMEOUT', 'NACOS_REQUEST_TIMEOUT',
        'DISCOVERY_TIMEOUT', 'DISCOVERY_TIMEOUT_SECONDS', 'DISCOVERY_CONNECT_TIMEOUT',
        'SEATA_SERVER', 'SEATA_SERVER_ADDR', 'SEATA_APP_ID',
        'SEATA_APPLICATION_ID', 'SEATA_TX_GROUP', 'SEATA_TRANSACTION_GROUP',
        'SEATA_MODE', 'SEATA_BRIDGE_URL', 'SEATA_BRIDGE_TOKEN',
        'SEATA_BRIDGE_TIMEOUT_S', 'SEATA_ENABLED',
        'RABBITMQ_HOST', 'RABBITMQ_PORT', 'RABBITMQ_USERNAME', 'RABBITMQ_PASSWORD',
        'RABBITMQ_VHOST', 'RABBITMQ_VIRTUAL_HOST', 'RABBITMQ_ENABLED',
        'RABBITMQ_TIMEOUT', 'RABBITMQ_TIMEOUT_SECONDS', 'RABBITMQ_CONNECTION_TIMEOUT',
        'RABBITMQ_SOCKET_TIMEOUT', 'RABBITMQ_STACK_TIMEOUT',
        'RABBITMQ_CONNECTION_ATTEMPTS', 'RABBITMQ_RETRY_DELAY', 'RABBITMQ_BLOCKED_CONNECTION_TIMEOUT',
        'PROMETHEUS_NAMESPACE', 'PROMETHEUS_SUBSYSTEM', 'PROMETHEUS_PORT',
        'PROMETHEUS_ENABLED', 'LOG_LEVEL', 'LOG_DIR', 'LOG_RETENTION', 'LOG_ROTATION',
        'SERVER_PORT', 'SERVER_HOST', 'CORS_ALLOW_ORIGINS', 'CORS_ALLOW_CREDENTIALS',
        'MANAGEMENT_CONFIG_MONITOR_ENABLED', 'MANAGEMENT_CONFIG_MONITOR_INCLUDE_VALUES',
        'MANAGEMENT_CONFIG_MONITOR_HISTORY_SIZE', 'MANAGEMENT_CONFIG_MONITOR_REFRESH_EVENTS',
        'MANAGEMENT_ADMIN_TITLE', 'MANAGEMENT_ADMIN_SUBTITLE',
        'MANAGEMENT_ADMIN_REFRESH_INTERVAL_SECONDS', 'MANAGEMENT_ADMIN_PAGE_SIZE',
        'MANAGEMENT_ADMIN_REQUEST_METRICS_ENABLED', 'MANAGEMENT_ADMIN_REQUEST_METRICS_TITLE',
        'MANAGEMENT_ADMIN_REQUEST_METRICS_TABLE', 'MANAGEMENT_ADMIN_REQUEST_METRICS_INCLUDE_PATHS',
        'MANAGEMENT_ADMIN_REQUEST_METRICS_EXCLUDE_PATHS',
        'MANAGEMENT_ENDPOINTS_WEB_SECURITY_ENABLED', 'MANAGEMENT_ENDPOINTS_WEB_SECURITY_ROLES',
        'NACOS_CONFIG_ENABLED', 'NACOS_CONFIG_SERVER_ADDR', 'NACOS_CONFIG_DATA_ID',
        'NACOS_CONFIG_GROUP', 'NACOS_CONFIG_NAMESPACE', 'NACOS_CONFIG_USERNAME',
        'NACOS_CONFIG_PASSWORD', 'NACOS_CONFIG_TIMEOUT_MS', 'NACOS_CONFIG_FAIL_FAST',
        'NACOS_CONFIG_REFRESH_ENABLED', 'NACOS_CONFIG_REFRESH_INTERVAL_SECONDS',
        'AI_ALLOW_FAKE',
    })

    # Framework-owned sections are consumed as mappings during startup.  A
    # minimal YAML file may leave one as ``null`` (``database:``), while a
    # typo can make it a scalar/list.  Normalize those values once so callers
    # consistently fall back to defaults instead of raising AttributeError.
    _MAPPING_SECTIONS = (
        'spring', 'startup', 'redis', 'jwt', 'database', 'discovery',
        'seata', 'rabbitmq', 'prometheus', 'logging', 'server', 'retry',
        'skywalking', 'ai',
    )

    # Nested sections read directly by startup/auto-configuration code.  Keep
    # malformed values from leaking into ``section.get(...)`` calls.
    _NESTED_MAPPING_PATHS = (
        ('spring', 'profiles'), ('spring', 'ai'), ('spring', 'cloud'),
        ('spring', 'cloud', 'nacos'), ('spring', 'cloud', 'nacos', 'config'),
        ('spring', 'security'), ('spring', 'kafka'), ('spring', 'devtools'),
        ('spring', 'data'), ('spring', 'batch'), ('spring', 'messages'),
        ('spring', 'swagger'), ('spring', 'mcp'), ('spring', 'langchain'),
        ('spring', 'cloud', 'config'), ('spring', 'cloud', 'bus'),
        ('spring', 'security', 'oauth2'), ('spring', 'devtools', 'restart'),
        ('spring', 'data', 'rest'), ('spring', 'mcp', 'server'),
        ('spring', 'mcp', 'clients'), ('spring', 'ai', 'openai'),
        ('spring', 'ai', 'ollama'), ('spring', 'ai', 'vector-store'),
        ('spring', 'ai', 'memory'), ('spring', 'ai', 'circuit-breaker'),
        ('spring', 'langchain', 'vector-store'),
        ('spring', 'langchain', 'retriever'),
        ('spring', 'langchain', 'memory'), ('spring', 'langchain', 'agents'),
        ('spring', 'langchain', 'chains'), ('spring', 'langchain', 'partners'),
        ('server', 'cors'), ('server', 'csrf'), ('server', 'thread_pool'),
        ('database', 'security'), ('database', 'cache'), ('database', 'pool'),
        ('database', 'batch'), ('database', 'ddl-auto'),
    )

    @staticmethod
    def _mapping(value: Any) -> Dict[str, Any]:
        """Return a configuration section as a mutable mapping.

        YAML permits an empty section (``server:``) to deserialize as ``None``
        and users occasionally provide a scalar/list by mistake.  Treat those
        values as an empty section so environment defaults can still be
        applied and the eventual validation can report only meaningful errors.
        """
        return value if isinstance(value, dict) else {}

    def _ensure_section(self, name: str) -> Dict[str, Any]:
        """Normalize a top-level section and return the mutable mapping."""
        if not isinstance(self._config, dict):
            self._config = {}
        section = self._mapping(self._config.get(name))
        if self._config.get(name) is not section:
            if name in self._config and self._config.get(name) is not None:
                self._log("warning", "Ignoring invalid configuration section %s (expected an object)", name)
            self._config[name] = section
        return section
    
    def __init__(self, config_path: str = "application.yml", base_path: str = None,
                 _test_mode: bool = False, log_events: bool = True):
        if base_path is None and config_path == "application.yml":
            base_path = self.__class__._default_base_path
        # 如果提供了base_path，则在该路径下查找配置文件
        if base_path and config_path == "application.yml":
            direct_path = os.path.join(base_path, config_path)
            config_dir_path = os.path.join(base_path, "config", config_path)
            self.config_path = direct_path if os.path.exists(direct_path) else config_dir_path
        else:
            self.config_path = config_path
        self._config: Dict[str, Any] = {}
        # 配置刷新在 Nacos 后台线程中执行；读操作必须看到完整快照，不能读到
        # ``_load_config`` 过程中的半成品。所有公开读取和 reload 都使用同一把锁。
        self._config_lock = threading.RLock()
        self._reload_in_progress = False
        self._last_remote_config: Dict[str, Any] = {}
        self._last_remote_identity = None
        self._config_sources: list[str] = []
        self._config_monitor = ConfigMonitor()
        self._has_loaded = False
        self._nacos_config_client = None
        # Bootstrap 阶段可静默读取配置，先应用 logging.level，再输出框架日志。
        self._log_events = log_events
        self._load_config()

    def _log(self, level: str, message: str, *args) -> None:
        """在需要静默预加载配置时抑制配置加载过程的普通日志。"""
        if self._log_events:
            getattr(logger, level)(message, *args)

    def _normalize_section_mappings(self) -> None:
        """Coerce known configuration sections to dictionaries in-place.

        Unknown application keys are left untouched; only sections owned by
        the framework are normalized because startup code relies on their
        mapping contract.
        """
        if not isinstance(self._config, dict):
            self._config = {}

        for section in self._MAPPING_SECTIONS:
            if not isinstance(self._config.get(section), dict):
                self._config[section] = {}

        for path in self._NESTED_MAPPING_PATHS:
            node = self._config
            for key in path[:-1]:
                child = node.get(key)
                if not isinstance(child, dict):
                    child = {}
                    node[key] = child
                node = child
            leaf = path[-1]
            if not isinstance(node.get(leaf), dict):
                node[leaf] = {}
    
    @staticmethod
    def _is_single_placeholder(value: str) -> bool:
        """判断字符串是否为单个完整的占位符（支持嵌套 ``${A:${B:default}}``）。

        用于决定解析后是否做类型推断（``yaml.safe_load``）。
        用括号深度计数识别单个平衡占位符，避免正则 ``[^}]+`` 无法处理嵌套 ``}``。
        """
        value = value.strip()
        if not (value.startswith('${') and value.endswith('}')):
            return False
        depth = 0
        for i, c in enumerate(value):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and i != len(value) - 1:
                    return False  # 在结束前就已闭合 → 非单个占位符
        return depth == 0

    def _resolve_env_var(self, value: str) -> Any:
        """
        解析环境变量引用

        支持格式：
        - ${ENV_VAR} - 直接读取环境变量
        - ${ENV_VAR:default} - 读取环境变量，不存在使用默认值
        - ${A:${B:default}} - 嵌套占位符（迭代解析最内层）

        Args:
            value: 包含环境变量引用的字符串

        Returns:
            解析后的值（单个占位符时做类型推断）
        """
        if not isinstance(value, str):
            return value

        # 判断整个值是否为单个占位符（支持嵌套），用于类型推断
        exact_placeholder = self._is_single_placeholder(value)

        def replace_env(match):
            env_spec = match.group(1)

            # 检查是否有默认值
            if ':' in env_spec:
                env_name, default_value = env_spec.split(':', 1)
            else:
                env_name = env_spec
                default_value = None

            # 从环境变量获取值
            env_value = os.environ.get(env_name.strip())

            # 如果环境变量不存在，使用默认值
            if env_value is None:
                if default_value is None:
                    raise ConfigurationError(f"必需的环境变量 {env_name.strip()} 未设置")
                return default_value

            self._environment_placeholder_used = True
            return env_value

        # 迭代解析最内层占位符，支持嵌套 ${A:${B:default}}
        # 每轮用 _INNER_ENV_VAR_PATTERN 替换所有不含 ${ 的最内层占位符，
        # 直到没有变化或达到最大迭代次数（防止无限循环）
        resolved = value
        prev = None
        iterations = 0
        while prev != resolved and iterations < 10:
            prev = resolved
            resolved = self._INNER_ENV_VAR_PATTERN.sub(replace_env, resolved)
            iterations += 1

        # 整个值是单个占位符时，做类型推断（如 "8080" → 8080, "true" → True）
        if exact_placeholder:
            parsed = yaml.safe_load(resolved)
            if not isinstance(parsed, (dict, list)):
                return parsed
        return resolved
    
    def _resolve_config_recursive(self, config: Any) -> Any:
        """
        递归解析配置中的环境变量
        
        Args:
            config: 配置值（可能是字典、列表或字符串）
        
        Returns:
            解析后的配置值
        """
        if isinstance(config, str):
            return self._resolve_env_var(config)
        elif isinstance(config, dict):
            return {key: self._resolve_config_recursive(value) for key, value in config.items()}
        elif isinstance(config, list):
            return [self._resolve_config_recursive(item) for item in config]
        else:
            return config
    
    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并两个配置字典：``override`` 覆盖 ``base``，子字典递归合并。

        对齐 Spring Boot 的 profile 合并语义：profile 特定配置覆盖主配置，
        但主配置中未涉及的键保留。返回新字典，不修改入参。
        """
        if not isinstance(base, dict):
            base = {}
        if not isinstance(override, dict):
            return deepcopy(base)
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    def _resolve_profile_path(self, profile: str) -> Optional[str]:
        """解析 ``application-{profile}.yml`` 路径，与主配置同目录。"""
        # ``default`` 也是一个有效 profile。若项目提供
        # ``application-default.yml``，它应像 Spring Boot 一样参与默认
        # 配置合并；没有该文件时自然回退到主 application.yml。
        if not profile:
            return None
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        profile_file = f"application-{profile}.yml"
        candidate = os.path.join(config_dir, profile_file)
        return candidate if os.path.exists(candidate) else None

    def _load_project_dotenv(self) -> None:
        """Load the generated project's optional ``.env`` without overriding OS values.

        The scaffold documents ``.env.example`` as the local configuration
        entry point.  Loading it here makes that promise true for both
        ``Application.py`` and ASGI factory startup.  Process environment
        variables remain higher priority, which is important for Docker and
        production deployment platforms.
        """
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        project_dir = (
            os.path.dirname(config_dir)
            if os.path.basename(config_dir).lower() == 'config'
            else config_dir
        )
        dotenv_path = os.path.join(project_dir, '.env')
        if not os.path.isfile(dotenv_path):
            return

        try:
            from dotenv import load_dotenv
        except ImportError:
            self._log("warning",
                "Found .env at %s but python-dotenv is not installed; ignoring it",
                dotenv_path,
            )
            return

        load_dotenv(dotenv_path=dotenv_path, override=False)
        self._log("debug", "Loaded project environment from %s", dotenv_path)

    def _load_config(self):
        """加载配置"""
        started = time.perf_counter()
        initial_load = not self._has_loaded
        self._config_sources = []
        self._environment_placeholder_used = False
        # Read .env before resolving YAML placeholders.  This keeps the
        # generated project's documented local setup working while preserving
        # explicitly supplied process environment variables.
        self._load_project_dotenv()

        # 1. 尝试从YAML文件加载主配置
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
                if not isinstance(self._config, dict):
                    raise ConfigurationError("配置文件根节点必须是对象")
                self._config_sources.append("yaml")
                self._log("info", f"Loaded config from {self.config_path}")
            except Exception as e:
                self._log("error", f"Failed to load config from {self.config_path}: {e}")
                raise ConfigurationError(f"无法加载配置文件 {self.config_path}") from e

        # Profile discovery below reads nested sections before environment
        # binding.  Normalize immediately after loading the main YAML so a
        # null/list section cannot break profile lookup.
        self._normalize_section_mappings()

        # 1.5 加载 profile 特定配置文件并深度合并（application-{profile}.yml 覆盖主配置）
        #     profile 来自主配置的 springbootai.profiles.active 或 SPRING_PROFILES_ACTIVE 环境变量。
        #     在占位符解析之前合并，使 profile 文件中的占位符也能被解析。
        spring_config = self._mapping(self._config.get('spring'))
        profiles_config = self._mapping(spring_config.get('profiles'))
        profile = os.getenv('SPRING_PROFILES_ACTIVE') or profiles_config.get('active', 'default')
        # 兼容 dict 格式的 profile.active（如 springbootai.profiles.active: {name: prod}）
        if isinstance(profile, dict):
            profile = profile.get('name') or profile.get('active') or 'default'
        # Profile 文件必须在完整配置占位符解析前决定，但 active 本身也
        # 经常写成 ``${SPRING_PROFILES_ACTIVE:default}``。先解析这一项，
        # 否则框架会去查找字面文件名
        # ``application-${SPRING_PROFILES_ACTIVE:default}.yml``，导致默认
        # profile 文件静默不生效。
        if isinstance(profile, str) and '${' in profile:
            profile = self._resolve_env_var(profile)
        if profile:
            profile = str(profile).strip()
        profile_path = self._resolve_profile_path(profile) if profile else None
        if profile_path:
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_config = yaml.safe_load(f) or {}
                if isinstance(profile_config, dict):
                    self._config = self._deep_merge(self._config, profile_config)
                    self._config_sources.append(f"profile:{profile}")
                    self._log("info", f"Loaded profile config from {profile_path} (profile={profile})")
            except Exception as e:
                self._log("warning", f"Failed to load profile config {profile_path}: {e}")
                active_profile = str(profile or '').strip().lower()
                fail_fast_profile = active_profile in {'prod', 'production'} or _to_bool(os.getenv('STARTUP_FAIL_FAST'), False)
                if fail_fast_profile:
                    raise ConfigurationError(f"无法加载 profile 配置 {profile_path}") from e

        # A profile may replace a whole section with null/list/scalar.  Restore
        # the mapping contract before resolving placeholders and overrides.
        self._normalize_section_mappings()

        # Nacos Config is a startup-time configuration source.  It has to be
        # merged before placeholders and environment overrides so remote YAML
        # can configure server, database, JWT and all other components.
        self._load_nacos_bootstrap_config()

        # 2. 解析配置中的环境变量占位符
        self._config = self._resolve_config_recursive(self._config)

        # 3. 从环境变量覆盖配置
        self._override_with_env()
        if self._environment_placeholder_used or any(name in os.environ for name in self._CONFIG_ENV_NAMES):
            # 不记录环境变量名/值，监控只展示配置来源类别。
            self._config_sources.append("environment")
        # 4. 从命令行参数覆盖配置（优先级最高）
        if self._override_with_cli_args():
            self._config_sources.append("cli")
        # CLI may replace a complete section (for example ``--server=[]``).
        # Re-apply the mapping contract before validation and application use.
        self._normalize_section_mappings()
        self._validate_config()
        monitor_options = resolve_config_monitor_config(self._config)
        self._config_monitor.configure(monitor_options)
        if initial_load:
            try:
                self._config_monitor.record(
                    "load", previous=None, current=self._config,
                    source="+".join(dict.fromkeys(self._config_sources)) or "defaults",
                    success=True, duration_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception:
                logger.debug("配置初始加载监控记录失败", exc_info=True)
        self._has_loaded = True

    def _load_nacos_bootstrap_config(self) -> None:
        """从 Nacos 拉取远程 YAML 并作为本地配置的覆盖层合并。"""
        try:
            from springbootai.cloud.nacos_config import (
                NacosConfigProperties,
                bootstrap_nacos_config,
            )
        except ImportError:
            # ``nacos-sdk-python`` 是可选依赖。即使本地 YAML 开启了 Nacos，
            # 也要根据实际解析出的 enabled/fail-fast 判断行为，不能只看
            # NACOS_CONFIG_ENABLED 环境变量（否则会错误地静默跳过 fail-fast）。
            try:
                from springbootai.cloud.nacos_config import NacosConfigProperties
                properties = NacosConfigProperties.from_sources(self._config)
            except Exception:
                properties = None
            if properties is not None and properties.enabled and properties.fail_fast:
                raise
            if properties is not None and properties.enabled:
                self._log(
                    "warning",
                    "Nacos Config enabled but optional nacos-sdk-python is unavailable; using local/default configuration",
                )
            return

        # 配置源被关闭时及时停止旧监听器，避免热刷新线程继续使用上一份远程配置。
        remote_identity = None
        try:
            bootstrap_properties = NacosConfigProperties.from_sources(self._config)
            remote_identity = (
                bootstrap_properties.server_addr, bootstrap_properties.data_id,
                bootstrap_properties.group, bootstrap_properties.namespace,
                bootstrap_properties.username,
            )
            if (
                not bootstrap_properties.enabled
                and self._nacos_config_client is not None
                and not self._reload_in_progress
            ):
                self._nacos_config_client.close()
                self._nacos_config_client = None
                self._last_remote_config = {}
                self._last_remote_identity = None
        except Exception:
            # 具体 fail-fast 语义由 bootstrap_nacos_config 处理；这里不让探测逻辑
            # 覆盖真正的加载错误。
            pass

        # reload() 会在监听回调内部执行。保留回调前的内容版本，避免本次
        # fetch() 在 Bean/Web 刷新尚未成功时提前提交版本，导致失败后不再重试。
        previous_client = self._nacos_config_client
        previous_content = getattr(previous_client, '_last_content', None)
        try:
            # 启动时 fail_fast=false 允许可选 Nacos 暂时离线；热刷新时则
            # 必须把读取失败抛给监听器，保留旧版本标记并在下一轮重试，
            # 不能让“使用 last-good 配置”伪装成新配置刷新成功。
            bootstrap_kwargs = {}
            if self._reload_in_progress:
                bootstrap_kwargs['raise_on_unavailable'] = True
            client, remote_config = bootstrap_nacos_config(
                self._config,
                existing_client=self._nacos_config_client,
                **bootstrap_kwargs,
            )
            self._nacos_config_client = client
            if client is previous_client and previous_client is not None:
                try:
                    previous_client._last_content = previous_content
                except Exception:
                    # 第三方/测试客户端可能没有可写的版本字段；不影响配置加载。
                    pass
            if remote_config:
                self._config = self._deep_merge(self._config, remote_config)
                self._last_remote_config = deepcopy(remote_config)
                self._last_remote_identity = remote_identity
                self._config_sources.append("nacos")
                self._normalize_section_mappings()
                self._log("info", "Merged remote Nacos configuration")
            elif (
                client is not None and self._last_remote_config
                and remote_identity == self._last_remote_identity
            ):
                # 网络抖动且 fail_fast=false 时保留最后一份成功远程配置，避免
                # 数据库/JWT/端口等关键配置瞬间回退到本地默认值。
                self._config = self._deep_merge(self._config, self._last_remote_config)
                self._config_sources.append("nacos(last-good)")
        except ImportError:
            # 兼容极少数安装损坏/依赖导入失败场景；这里同样按配置决定
            # 是否 fail-fast，而不是无条件吞掉异常。
            properties = NacosConfigProperties.from_sources(self._config)
            if properties.enabled and properties.fail_fast:
                raise
            if properties.enabled:
                self._log(
                    "warning",
                    "Nacos Config unavailable because its optional dependency could not be imported; using local/default configuration",
                )

    def start_nacos_config_refresh(self, callback: Callable[[], None]) -> None:
        """应用上下文刷新完成后启动 Nacos 的配置变更监听。"""
        if self._nacos_config_client is not None:
            self._nacos_config_client.start_listener(callback)

    def close_nacos_config(self) -> None:
        """关闭 Nacos 配置监听线程。"""
        if self._nacos_config_client is not None:
            self._nacos_config_client.close()
    
    @staticmethod
    def _get_env_any(*names: str, default: Any = None) -> Any:
        """返回第一个已设置的环境变量值；都未设置则返回 default。

        用于兼容占位符风格与显式 override 风格两套环境变量命名。
        例如 ``discovery.server_addr`` 同时支持 ``NACOS_SERVER``（占位符风格）
        和 ``DISCOVERY_SERVER_ADDR``（显式覆盖风格）。
        """
        for name in names:
            value = os.getenv(name)
            if value is not None:
                return value
        return default

    @staticmethod
    def _get_env_int(name: str, default: Any, fallback: int = 0) -> int:
        """读取整型环境变量。

        An invalid *environment* override remains a configuration error, but
        a malformed value from an optional YAML field falls back to the
        caller-provided safe default so startup is not taken down by a typo.
        """
        raw = os.getenv(name)
        if raw is None:
            # 兼容 default 为 dict 的情况（YAML 嵌套写法如 port: {value: 6379}）
            if isinstance(default, dict):
                default = default.get('value') or default.get('port') or fallback
            try:
                return int(default)
            except (ValueError, TypeError):
                logger.warning(
                    "Ignoring invalid default for %s (%r); using %s",
                    name, default, fallback,
                )
                return fallback
        try:
            return int(raw)
        except (ValueError, TypeError):
            raise ConfigurationError(f"环境变量 {name} 必须是整数，实际值: {raw!r}")

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """安全转换浮点数，兼容 dict 格式的配置值。"""
        if isinstance(value, dict):
            value = value.get('value') or value.get('timeout') or value.get('seconds') or default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _override_with_env(self):
        """使用环境变量覆盖配置"""
        spring_config = self._ensure_section('spring')
        profiles_config = self._mapping(spring_config.get('profiles'))
        spring_config['profiles'] = profiles_config
        profiles_config['active'] = os.getenv(
            'SPRING_PROFILES_ACTIVE',
            profiles_config.get('active') or 'default',
        )

        startup_config = self._ensure_section('startup')
        fail_fast_env = os.getenv('STARTUP_FAIL_FAST')
        configured_fail_fast = startup_config.get('fail_fast')
        if fail_fast_env is not None:
            startup_config['fail_fast'] = _to_bool(fail_fast_env)
        elif configured_fail_fast is None:
            startup_config.pop('fail_fast', None)
        else:
            startup_config['fail_fast'] = _to_bool(configured_fail_fast)

        # Redis配置
        redis_config = self._ensure_section('redis')
        redis_config['host'] = os.getenv('REDIS_HOST', redis_config.get('host', 'localhost'))
        redis_config['port'] = self._get_env_int(
            'REDIS_PORT', redis_config.get('port', 6379), 6379
        )
        redis_config['db'] = self._get_env_int(
            'REDIS_DB', redis_config.get('db', 0), 0
        )
        raw_redis_password = os.getenv('REDIS_PASSWORD', redis_config.get('password'))
        redis_config['password'] = (
            raw_redis_password if raw_redis_password is None or isinstance(raw_redis_password, str)
            else str(raw_redis_password)
        )
        redis_config['enabled'] = _to_bool(os.getenv('REDIS_ENABLED', redis_config.get('enabled', False)), False)

        # JWT配置
        jwt_config = self._ensure_section('jwt')
        raw_jwt_secret = os.getenv('JWT_SECRET_KEY', jwt_config.get('secret_key', ''))
        # Keep an absent development secret empty.  JwtUtils then generates a
        # per-process random key and reports the accurate "not configured"
        # warning instead of pretending the removed legacy default was used.
        jwt_config['secret_key'] = raw_jwt_secret if isinstance(raw_jwt_secret, str) else ''
        raw_algorithm = os.getenv('JWT_ALGORITHM', jwt_config.get('algorithm', 'HS256'))
        jwt_config['algorithm'] = raw_algorithm if isinstance(raw_algorithm, str) else 'HS256'

        # 数据库配置。先应用所有环境变量，再按最终 driver/database 计算 URL，
        # 否则 DB_DRIVER/DB_NAME 会被旧 URL 覆盖，导致监控和业务连接到不同数据库。
        database_config = self._ensure_section('database')
        # ``database.database`` 是 PyMyBatis/SQLite 项目常用的文件路径，
        # ``database.url`` 是 SQLAlchemy 风格连接串。没有显式 URL 时不要
        # 强行写入 test.db，否则框架扩展（请求监控等）会与业务库分离。
        explicit_url = os.getenv('DB_URL')
        database_config['echo'] = _to_bool(os.getenv('DB_ECHO', database_config.get('echo', False)), False)
        # database.enabled 默认 True（对齐 application.yml 占位符 ${DB_ENABLED:true}）
        database_config['enabled'] = _to_bool(os.getenv('DB_ENABLED', database_config.get('enabled', True)), True)
        # PyMyBatis原生数据源配置（host/port/driver等）
        database_config['driver'] = os.getenv('DB_DRIVER', database_config.get('driver', 'sqlite'))
        database_config['host'] = os.getenv('DB_HOST', database_config.get('host', 'localhost'))
        database_config['port'] = self._get_env_int(
            'DB_PORT', database_config.get('port', 3306), 3306
        )
        raw_database = os.getenv('DB_NAME', database_config.get('database', 'test'))
        database_config['database'] = raw_database if isinstance(raw_database, str) else 'test'
        raw_username = os.getenv('DB_USERNAME', database_config.get('username', ''))
        database_config['username'] = raw_username if isinstance(raw_username, str) else ''
        raw_password = os.getenv('DB_PASSWORD', database_config.get('password', ''))
        database_config['password'] = raw_password if isinstance(raw_password, str) else ''
        if explicit_url is not None and str(explicit_url).strip():
            database_config['url'] = str(explicit_url).strip()
        else:
            configured_url = database_config.get('url')
            driver = str(database_config.get('driver', 'sqlite')).lower()
            database_path = database_config.get('database')
            driver_or_name_overridden = (
                os.getenv('DB_DRIVER') is not None or os.getenv('DB_NAME') is not None
            )
            if (
                configured_url is None
                or (isinstance(configured_url, str) and not configured_url.strip())
                or driver_or_name_overridden
            ):
                if driver == 'sqlite' and database_path:
                    configured_url = 'sqlite:///' + str(database_path).replace('\\', '/')
                elif driver in {'mysql', 'mariadb'}:
                    user = quote_plus(str(database_config.get('username', '')))
                    password = quote_plus(str(database_config.get('password', '')))
                    auth = f'{user}:{password}@' if user or password else ''
                    configured_url = (
                        f"mysql+pymysql://{auth}{database_config.get('host', 'localhost')}:"
                        f"{database_config.get('port', 3306)}/{database_path or 'app'}"
                    )
                elif driver in {'postgres', 'postgresql', 'psycopg2'}:
                    user = quote_plus(str(database_config.get('username', '')))
                    password = quote_plus(str(database_config.get('password', '')))
                    auth = f'{user}:{password}@' if user or password else ''
                    configured_url = (
                        f"postgresql+psycopg2://{auth}{database_config.get('host', 'localhost')}:"
                        f"{database_config.get('port', 5432)}/{database_path or 'app'}"
                    )
                else:
                    configured_url = 'sqlite:///./runtime/springbootai.db'
            database_config['url'] = configured_url

        # 服务发现配置
        # 兼容占位符风格（NACOS_*）与显式覆盖风格（DISCOVERY_*）两套环境变量命名
        discovery_config = self._ensure_section('discovery')
        discovery_config['server_addr'] = self._get_env_any(
            'NACOS_SERVER', 'DISCOVERY_SERVER_ADDR',
            default=discovery_config.get('server_addr', 'localhost:8848'))
        discovery_config['namespace'] = self._get_env_any(
            'NACOS_NAMESPACE', 'DISCOVERY_NAMESPACE',
            default=discovery_config.get('namespace', ''))
        discovery_config['group'] = self._get_env_any(
            'NACOS_GROUP', 'DISCOVERY_GROUP',
            default=discovery_config.get('group', 'DEFAULT_GROUP'))
        discovery_config['username'] = os.getenv('NACOS_USERNAME', discovery_config.get('username', ''))
        discovery_config['password'] = os.getenv('NACOS_PASSWORD', discovery_config.get('password', ''))
        # Nacos SDK 的请求超时必须是有限正数。支持旧/新环境变量别名，
        # 以便在容器环境直接缩短可选服务不可用时的启动等待。
        discovery_config['timeout'] = self._safe_float(
            self._get_env_any(
                'NACOS_TIMEOUT', 'NACOS_TIMEOUT_SECONDS',
                'NACOS_CONNECT_TIMEOUT', 'NACOS_REQUEST_TIMEOUT',
                'DISCOVERY_TIMEOUT', 'DISCOVERY_TIMEOUT_SECONDS',
                'DISCOVERY_CONNECT_TIMEOUT',
                default=discovery_config.get(
                    'timeout', discovery_config.get(
                        'timeout_seconds', discovery_config.get('connect_timeout', 3.0)
                    )
                ),
            ),
            3.0,
        )
        discovery_config['enabled'] = _to_bool(os.getenv('DISCOVERY_ENABLED', discovery_config.get('enabled', False)), False)

        # Seata配置
        # 兼容占位符风格（SEATA_SERVER/SEATA_APP_ID/SEATA_TX_GROUP）与显式覆盖风格
        seata_config = self._ensure_section('seata')
        seata_config['server_addr'] = self._get_env_any(
            'SEATA_SERVER', 'SEATA_SERVER_ADDR',
            default=seata_config.get('server_addr', 'localhost:8091'))
        seata_config['application_id'] = self._get_env_any(
            'SEATA_APP_ID', 'SEATA_APPLICATION_ID',
            default=seata_config.get('application_id', ''))
        seata_config['transaction_group'] = self._get_env_any(
            'SEATA_TX_GROUP', 'SEATA_TRANSACTION_GROUP',
            default=seata_config.get('transaction_group', 'my_tx_group'))
        seata_config['mode'] = os.getenv('SEATA_MODE', seata_config.get('mode', 'local'))
        seata_config['bridge_url'] = os.getenv(
            'SEATA_BRIDGE_URL',
            seata_config.get('bridge_url', 'http://localhost:18091'))
        seata_config['bridge_token'] = os.getenv('SEATA_BRIDGE_TOKEN', seata_config.get('bridge_token', ''))
        seata_config['bridge_timeout_s'] = self._safe_float(
            os.getenv('SEATA_BRIDGE_TIMEOUT_S')
            or seata_config.get('bridge_timeout_s', 5.0), 5.0)
        seata_config['enabled'] = _to_bool(os.getenv('SEATA_ENABLED', seata_config.get('enabled', False)), False)

        # RabbitMQ配置
        # 兼容占位符风格（RABBITMQ_VHOST）与显式覆盖风格（RABBITMQ_VIRTUAL_HOST）
        rabbitmq_config = self._ensure_section('rabbitmq')
        rabbitmq_config['host'] = os.getenv('RABBITMQ_HOST', rabbitmq_config.get('host', 'localhost'))
        rabbitmq_config['port'] = self._get_env_int(
            'RABBITMQ_PORT', rabbitmq_config.get('port', 5672), 5672
        )
        rabbitmq_config['username'] = os.getenv('RABBITMQ_USERNAME', rabbitmq_config.get('username', 'guest'))
        rabbitmq_config['password'] = os.getenv('RABBITMQ_PASSWORD', rabbitmq_config.get('password', 'guest'))
        rabbitmq_config['virtual_host'] = self._get_env_any(
            'RABBITMQ_VHOST', 'RABBITMQ_VIRTUAL_HOST',
            default=rabbitmq_config.get('virtual_host', '/'))
        # pika 的 socket/handshake 超时与连接重试次数分开配置；默认值均为
        # 有限的小值，避免 RabbitMQ 未启动时阻塞应用数十秒。实际安全上限
        # 在 RabbitMQClient 中再次校验，Nacos/环境/Nacos 热更新均适用。
        rabbitmq_config['connection_timeout'] = self._safe_float(
            self._get_env_any(
                'RABBITMQ_CONNECTION_TIMEOUT', 'RABBITMQ_TIMEOUT',
                'RABBITMQ_TIMEOUT_SECONDS',
                default=rabbitmq_config.get(
                    'connection_timeout', rabbitmq_config.get('timeout', 5.0)
                ),
            ),
            5.0,
        )
        rabbitmq_config['socket_timeout'] = self._safe_float(
            os.getenv('RABBITMQ_SOCKET_TIMEOUT', rabbitmq_config.get('socket_timeout', 5.0)),
            5.0,
        )
        rabbitmq_config['stack_timeout'] = self._safe_float(
            os.getenv('RABBITMQ_STACK_TIMEOUT', rabbitmq_config.get('stack_timeout', 5.0)),
            5.0,
        )
        rabbitmq_config['connection_attempts'] = self._get_env_int(
            'RABBITMQ_CONNECTION_ATTEMPTS',
            rabbitmq_config.get('connection_attempts', 1),
            1,
        )
        rabbitmq_config['blocked_connection_timeout'] = self._safe_float(
            os.getenv('RABBITMQ_BLOCKED_CONNECTION_TIMEOUT',
                      rabbitmq_config.get('blocked_connection_timeout', 300.0)),
            300.0,
        )
        rabbitmq_config['retry_delay'] = self._safe_float(
            os.getenv('RABBITMQ_RETRY_DELAY', rabbitmq_config.get('retry_delay', 0.0)),
            0.0,
        )
        rabbitmq_config['enabled'] = _to_bool(os.getenv('RABBITMQ_ENABLED', rabbitmq_config.get('enabled', False)), False)

        # Prometheus配置
        prometheus_config = self._ensure_section('prometheus')
        prometheus_config['namespace'] = os.getenv('PROMETHEUS_NAMESPACE', prometheus_config.get('namespace', 'spring'))
        prometheus_config['subsystem'] = os.getenv('PROMETHEUS_SUBSYSTEM', prometheus_config.get('subsystem', 'python'))
        prometheus_config['port'] = self._get_env_int(
            'PROMETHEUS_PORT', prometheus_config.get('port', 8000), 8000
        )
        prometheus_config['enabled'] = _to_bool(os.getenv('PROMETHEUS_ENABLED', prometheus_config.get('enabled', False)), False)

        # 日志配置
        logging_config = self._ensure_section('logging')
        # 兼容 logging.level 为 dict 的情况（Spring Boot 风格）：
        # logging.level: {root: INFO, spring: DEBUG} → 提取 root 级别或第一个字符串值
        raw_level = logging_config.get('level', 'INFO')
        if isinstance(raw_level, dict):
            raw_level = raw_level.get('root') or next(
                (v for v in raw_level.values() if isinstance(v, str)), 'INFO')
        raw_level = os.getenv('LOG_LEVEL', raw_level)
        logging_config['level'] = raw_level if isinstance(raw_level, str) and raw_level else 'INFO'
        # 兼容 logging.log_dir 为 dict 的情况
        raw_log_dir = logging_config.get('log_dir')
        if isinstance(raw_log_dir, dict):
            raw_log_dir = None
        raw_log_dir = os.getenv('LOG_DIR', raw_log_dir)
        logging_config['log_dir'] = raw_log_dir if isinstance(raw_log_dir, str) and raw_log_dir else None
        raw_retention = os.getenv('LOG_RETENTION', logging_config.get('retention', '30 days'))
        logging_config['retention'] = raw_retention if isinstance(raw_retention, str) else '30 days'
        raw_rotation = os.getenv('LOG_ROTATION', logging_config.get('rotation', '100 MB'))
        logging_config['rotation'] = raw_rotation if isinstance(raw_rotation, str) else '100 MB'

        # 服务器配置
        server_config = self._ensure_section('server')
        server_config['port'] = self._get_env_int(
            'SERVER_PORT', server_config.get('port', 8080), 8080
        )
        default_server_host = '0.0.0.0'  # nosec B104 - framework server default
        raw_server_host = os.getenv(
            'SERVER_HOST', server_config.get('host', default_server_host)
        )
        server_config['host'] = raw_server_host if isinstance(raw_server_host, str) and raw_server_host else default_server_host

        cors_config = self._mapping(server_config.get('cors'))
        server_config['cors'] = cors_config
        origins_env = os.getenv('CORS_ALLOW_ORIGINS')
        if origins_env is not None:
            cors_config['allow_origins'] = [
                origin.strip() for origin in origins_env.split(',') if origin.strip()
            ]
        else:
            origins = cors_config.get('allow_origins', [])
            if isinstance(origins, str):
                origins = [item.strip() for item in origins.split(',') if item.strip()]
            cors_config['allow_origins'] = origins if isinstance(origins, list) else []
        for key, default in (
            ('allow_methods', ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']),
            ('allow_headers', ['Content-Type', 'Authorization']),
        ):
            value = cors_config.get(key, default)
            if isinstance(value, str):
                value = [item.strip() for item in value.split(',') if item.strip()]
            cors_config[key] = value if isinstance(value, list) else list(default)
        cors_config['allow_credentials'] = _to_bool(
            os.getenv('CORS_ALLOW_CREDENTIALS', cors_config.get('allow_credentials', False)), False)

        # Actuator / Admin 面板配置。所有字段都写回最终配置对象，后续 Web 与监控模块
        # 只读取 ApplicationContext.get_config()，因此无论值来自 YAML、Nacos 还是环境变量，
        # 运行期语义和优先级完全一致（环境变量最高）。
        management_config = self._ensure_section('management')
        config_monitor_config = self._mapping(
            management_config.get('config-monitor', management_config.get('config_monitor'))
        )
        management_config['config-monitor'] = config_monitor_config
        for env_name, config_key in (
            ('MANAGEMENT_CONFIG_MONITOR_ENABLED', 'enabled'),
            ('MANAGEMENT_CONFIG_MONITOR_INCLUDE_VALUES', 'include-values'),
            ('MANAGEMENT_CONFIG_MONITOR_HISTORY_SIZE', 'history-size'),
            ('MANAGEMENT_CONFIG_MONITOR_REFRESH_EVENTS', 'refresh-events'),
        ):
            value = os.getenv(env_name)
            if value is not None:
                if config_key in {'enabled', 'include-values', 'refresh-events'}:
                    value = _to_bool(value)
                elif config_key == 'history-size':
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        self._log('warning', 'Ignoring invalid %s=%r', env_name, value)
                        continue
                config_monitor_config[config_key] = value
        admin_config = self._mapping(management_config.get('admin'))
        management_config['admin'] = admin_config
        for env_name, config_key in (
            ('MANAGEMENT_ADMIN_TITLE', 'title'),
            ('MANAGEMENT_ADMIN_SUBTITLE', 'subtitle'),
            ('MANAGEMENT_ADMIN_REFRESH_INTERVAL_SECONDS', 'refresh-interval-seconds'),
            ('MANAGEMENT_ADMIN_PAGE_SIZE', 'page-size'),
        ):
            value = os.getenv(env_name)
            if value is not None:
                admin_config[config_key] = value

        request_metrics_config = self._mapping(
            admin_config.get('request-metrics', admin_config.get('request_metrics'))
        )
        admin_config['request-metrics'] = request_metrics_config
        metrics_enabled = os.getenv('MANAGEMENT_ADMIN_REQUEST_METRICS_ENABLED')
        if metrics_enabled is not None:
            request_metrics_config['enabled'] = _to_bool(metrics_enabled, False)
        for env_name, config_key in (
            ('MANAGEMENT_ADMIN_REQUEST_METRICS_TITLE', 'title'),
            ('MANAGEMENT_ADMIN_REQUEST_METRICS_TABLE', 'table'),
        ):
            value = os.getenv(env_name)
            if value is not None:
                request_metrics_config[config_key] = value
        for env_name, config_key in (
            ('MANAGEMENT_ADMIN_REQUEST_METRICS_INCLUDE_PATHS', 'include-paths'),
            ('MANAGEMENT_ADMIN_REQUEST_METRICS_EXCLUDE_PATHS', 'exclude-paths'),
        ):
            value = os.getenv(env_name)
            if value is not None:
                request_metrics_config[config_key] = [
                    item.strip() for item in value.split(',') if item.strip()
                ]

        endpoints_config = self._mapping(management_config.get('endpoints'))
        management_config['endpoints'] = endpoints_config
        web_config = self._mapping(endpoints_config.get('web'))
        endpoints_config['web'] = web_config
        actuator_security = self._mapping(web_config.get('security'))
        web_config['security'] = actuator_security
        security_enabled = os.getenv('MANAGEMENT_ENDPOINTS_WEB_SECURITY_ENABLED')
        if security_enabled is not None:
            actuator_security['enabled'] = _to_bool(security_enabled, True)
        security_roles = os.getenv('MANAGEMENT_ENDPOINTS_WEB_SECURITY_ROLES')
        if security_roles is not None:
            actuator_security['roles'] = [
                item.strip() for item in security_roles.split(',') if item.strip()
            ]

    def _override_with_cli_args(self) -> bool:
        """从命令行参数覆盖配置（优先级最高，对齐 Spring Boot ``--key=value``）。

        支持两种形式：
        - ``--server.port=9000``
        - ``--server.port 9000``

        点分隔键递归写入 ``self._config``，值经 ``yaml.safe_load`` 做类型推断
        （``9000`` → int，``true`` → bool）。在 ``_override_with_env`` 之后调用。
        """
        args = sys.argv[1:]
        i = 0
        applied = False
        while i < len(args):
            arg = args[i]
            if not arg.startswith('--'):
                i += 1
                continue
            body = arg[2:]
            if '=' in body:
                key, value = body.split('=', 1)
                applied = self._set_cli_override(key, value) or applied
                i += 1
            else:
                # --key value 形式：仅当下一个 token 非参数时才取值
                if i + 1 < len(args) and not args[i + 1].startswith('--'):
                    applied = self._set_cli_override(body, args[i + 1]) or applied
                    i += 2
                else:
                    i += 1
        return applied
    def _set_cli_override(self, dotted_key: str, raw_value: str) -> bool:
        """将点分隔键写入 ``self._config``，值做 yaml 类型推断。"""
        keys = [part.strip() for part in dotted_key.split('.') if part.strip()]
        if not keys:
            return False
        node = self._config
        for k in keys[:-1]:
            child = node.get(k)
            if not isinstance(child, dict):
                child = {}
                node[k] = child
            node = child
        parsed = yaml.safe_load(raw_value)
        node[keys[-1]] = parsed
        lowered = dotted_key.replace('_', '-').lower()
        sensitive = any(token in lowered for token in (
            'password', 'secret', 'token', 'credential', 'api-key',
            'private-key', 'access-key', 'authorization',
        ))
        shown = '******' if sensitive else repr(parsed)
        self._log("debug", "CLI override: %s=%s", dotted_key, shown)
        return True

    def _validate_config(self) -> None:
        jwt_config = self._mapping(self._config.get('jwt'))
        raw_algorithm = jwt_config.get('algorithm', 'HS256')
        # 兼容 dict 格式的 algorithm
        if isinstance(raw_algorithm, dict):
            raw_algorithm = raw_algorithm.get('value') or raw_algorithm.get('name') or 'HS256'
        algorithm = str(raw_algorithm).upper()
        if algorithm not in {'HS256', 'HS384', 'HS512'}:
            raise ConfigurationError(f"不允许的 JWT 算法: {algorithm}")

        server_config = self._mapping(self._config.get('server'))
        cors = self._mapping(server_config.get('cors'))
        if cors.get('allow_credentials') and '*' in cors.get('allow_origins', []):
            raise ConfigurationError("CORS 开启凭证时不能使用通配来源 *")

        profile = str(
            os.getenv('SPRING_PROFILES_ACTIVE')
            or os.getenv('APP_ENV')
            or self.get_active_profile()
        ).lower()
        if profile not in {'prod', 'production'}:
            return

        secret = jwt_config.get('secret_key')
        insecure_secret = 'spring-python-secret-key-change-in-production'
        if not secret or secret == insecure_secret or len(str(secret)) < 32:
            raise ConfigurationError("生产环境 JWT_SECRET_KEY 必须设置为至少 32 个字符的随机密钥")

        seata_config = self._mapping(self._config.get('seata'))
        if seata_config.get('enabled'):
            seata_mode = str(seata_config.get('mode', 'local')).lower()
            if seata_mode != 'distributed':
                raise ConfigurationError(
                    "生产环境启用 Seata 时只允许 mode=distributed；"
                    "实验性 HTTP/local 模式不能提供跨服务一致性"
                )
            if len(str(seata_config.get('bridge_token', ''))) < 16:
                raise ConfigurationError(
                    "生产环境 Seata distributed 模式要求 SEATA_BRIDGE_TOKEN 至少 16 个字符"
                )

        # 生产环境 AI 服务加固：禁止静默使用 FakeChatModel，强制校验 API Key
        # 旧版本默认 AI_ALLOW_FAKE=true，缺失 api-key 时无声返回 FakeChatModel，
        # 业务可能启动成功并持续返回测试数据，而非明确失败。
        # 双重加固：
        # (1) 将未显式设置的 AI_ALLOW_FAKE 固定为 false，使后续 AI 自动配置
        #     无论导入时序如何都不会静默降级为 FakeChatModel；
        # (2) 在此显式校验默认 provider 的 api-key 已配置，给出清晰错误。
        # 显式设置为 true 仍然立即报错。这里使用 setdefault 而不是无条件覆盖，
        # 既保留调用方对开发/测试环境的显式选择，也保证生产配置的安全默认值。
        if _to_bool(os.getenv('AI_ALLOW_FAKE'), False):
            raise ConfigurationError(
                "生产环境不允许 AI_ALLOW_FAKE=true；请配置真实 AI provider 的 api-key"
            )
        os.environ.setdefault('AI_ALLOW_FAKE', 'false')
        ai_config = self._mapping(self._config.get('ai'))
        spring_config = self._mapping(self._config.get('spring'))
        spring_ai = self._mapping(spring_config.get('ai'))
        # AI 模块默认启用（未显式 enabled=false 即视为启用）
        ai_enabled = ai_config.get('enabled', spring_ai.get('enabled', True))
        if _to_bool(ai_enabled, True):
            provider = str(
                spring_ai.get('default-provider')
                or ai_config.get('default_provider')
                or ai_config.get('default-provider')
                or 'openai'
            ).lower()
            # ollama 本地部署无需 api-key；其余 provider 必须配置 api-key
            if provider != 'ollama':
                # 兼容 springbootai.ai.<provider>.api-key（kebab）与 ai.<provider>.api_key（snake）
                # Provider sections are user supplied and may be null/list or
                # scalar.  Pick the first valid mapping and ignore malformed
                # values so production validation reports the missing key
                # instead of leaking ``AttributeError``.
                provider_cfg = self._mapping(spring_ai.get(provider))
                if not provider_cfg:
                    provider_cfg = self._mapping(ai_config.get(provider))
                api_key = (
                    provider_cfg.get('api-key')
                    or provider_cfg.get('api_key')
                    or ''
                )
                if not api_key:
                    env_hint = {
                        'openai': 'OPENAI_API_KEY',
                        'deepseek': 'DEEPSEEK_API_KEY',
                        'moonshot': 'MOONSHOT_API_KEY',
                        'zhipu': 'ZHIPUAI_API_KEY',
                    }.get(provider, f'{provider.upper()}_API_KEY')
                    raise ConfigurationError(
                        f"生产环境 AI 服务 (provider={provider}) 必须配置 api-key；"
                        f"请设置 {env_hint} 环境变量或 application.yml 的 "
                        f"springbootai.ai.{provider}.api-key。生产环境不允许静默使用 FakeChatModel。"
                    )
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        lock = getattr(self, "_config_lock", None)
        if lock is None:
            return deepcopy(getattr(self, "_config", {}))

        with lock:
            return deepcopy(self._config)
    
    def get_prefix_config(self, prefix: str) -> Dict[str, Any]:
        """
        获取指定前缀的配置
        
        Args:
            prefix: 配置前缀（如 'server', 'jwt'）
            
        Returns:
            前缀对应的配置字典
        """
        value = self.get(prefix, {})
        return deepcopy(value) if isinstance(value, dict) else {}

    def resolve_value_expression(self, expression: Any, default: Any = None) -> Any:
        """Resolve an ``@Value`` / ``@NacosValue`` expression.

        Both the concise Python form (``"server.port"``) and the familiar
        Spring form (``"${server.port:8080}"``) are accepted.  Property
        Environment variables use the same high-priority rule as normal binding,
        followed by the resolved configuration property and expression default.  A missing value returns the
        caller-provided *default* instead of leaking an annotation object into
        a constructor argument.
        """
        if not isinstance(expression, str):
            return expression

        match = self._VALUE_EXPRESSION_PATTERN.fullmatch(expression.strip())
        if match:
            key = match.group(1).strip()
            expression_default = match.group(2)
        else:
            key = expression.strip()
            expression_default = None

        # Support dotted/kebab property names and their conventional uppercase
        # underscore environment aliases (e.g. feature.timeout -> FEATURE_TIMEOUT).
        env_names = [key, key.replace('.', '_').replace('-', '_').upper()]
        env_value = next(
            (os.getenv(name) for name in dict.fromkeys(env_names)
             if os.getenv(name) is not None),
            None,
        )
        if env_value is not None:
            parsed = yaml.safe_load(env_value)
            return parsed if not isinstance(parsed, (dict, list)) else env_value

        value = self.get(key, self._MISSING)
        if value is not self._MISSING:
            return value

        if expression_default is not None:
            parsed = yaml.safe_load(expression_default)
            return parsed if not isinstance(parsed, (dict, list)) else expression_default
        return default
    
    def get_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持点分隔路径）
        
        Args:
            key: 配置键，支持点分隔（如 'server.port'）
            default: 默认值
            
        Returns:
            配置值
        """
        return self.get(key, default)
    
    def get_active_profile(self) -> str:
        """
        获取当前激活的配置文件
        
        Returns:
            激活的配置文件名（不含.yml后缀）
        """
        lock = getattr(self, "_config_lock", None)
        if lock is None:
            spring_config = self._mapping(self._config.get('spring'))
            profiles_config = self._mapping(spring_config.get('profiles'))
            active = profiles_config.get('active') or 'default'
        else:
            with lock:
                spring_config = self._mapping(self._config.get('spring'))
                profiles_config = self._mapping(spring_config.get('profiles'))
                active = profiles_config.get('active') or 'default'
        # 兼容 dict 格式（如 springbootai.profiles.active: {name: prod}）
        if isinstance(active, dict):
            active = active.get('name') or active.get('active') or 'default'
        return str(active)
    
    @staticmethod
    def _lookup_key(mapping: Any, key: str):
        """在字典中查找 ``key``：先精确匹配，再松散匹配（大小写/分隔符不敏感）。

        与 ``@ConfigurationProperties`` 松散绑定语义一致，使 ``get('logging.log-dir')``
        也能命中 YAML 中的 ``log_dir``。返回 ``(value, found)``。
        """
        if not isinstance(mapping, dict):
            return None, False
        if key in mapping:
            return mapping[key], True
        # 松散匹配：规范化（去分隔符+小写）后比较
        norm = _normalize_name(key)
        for k, v in mapping.items():
            if _normalize_name(k) == norm:
                return v, True
        return None, False

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值

        支持点分隔路径与松散绑定（kebab-case / snake_case / 大小写不敏感）。
        先精确匹配，未命中再松散匹配，避免 ``log-dir`` 找不到 ``log_dir`` 的问题。

        Args:
            key: 配置键，支持点分隔（如 redis.host / logging.log-dir / Logging.Level）
            default: 默认值

        Returns:
            配置值
        """
        lock = getattr(self, "_config_lock", None)
        if lock is None:
            value = getattr(self, "_config", {})
            for k in key.split('.'):
                value, found = self._lookup_key(value, k)
                if not found:
                    return default
            return deepcopy(value)

        with lock:
            keys = key.split('.')
            value = self._config

            for k in keys:
                value, found = self._lookup_key(value, k)
                if not found:
                    return default

            return deepcopy(value)
    
    def load_config(self):
        """加载配置（公共方法，供外部调用）"""
        with self._config_lock:
            self._load_config()

    def get_config_monitor(self) -> ConfigMonitor:
        """返回配置监控实例；实例本身线程安全，可供 Actuator 查询。"""
        return self._config_monitor
    
    def reload(self):
        """原子重新加载配置。

        新快照完整加载并校验成功后才替换当前配置；Nacos 暂时不可用或 Bean
        刷新失败时由上层回调抛出，下一轮监听仍会重试，业务继续使用旧快照。
        """
        with self._config_lock:
            previous = deepcopy(self._config)
            previous_remote = deepcopy(self._last_remote_config)
            previous_remote_identity = self._last_remote_identity
            previous_sources = list(self._config_sources)
            previous_client = self._nacos_config_client
            previous_content = getattr(previous_client, '_last_content', None)
            started = time.perf_counter()
            self._reload_in_progress = True
            try:
                self._config = {}
                self._load_config()
                current = deepcopy(self._config)
            except Exception as exc:
                # 恢复远程快照、配置来源和客户端版本，失败候选不能污染下一次重试。
                candidate_client = self._nacos_config_client
                self._config = previous
                self._last_remote_config = previous_remote
                self._last_remote_identity = previous_remote_identity
                self._config_sources = previous_sources
                self._nacos_config_client = previous_client
                if candidate_client is not None and candidate_client is not previous_client:
                    try:
                        candidate_client.close()
                    except Exception:
                        logger.debug("关闭失败的 Nacos 配置客户端失败", exc_info=True)
                if previous_client is not None:
                    try:
                        previous_client._last_content = previous_content
                    except Exception:
                        pass
                duration_ms = (time.perf_counter() - started) * 1000
                try:
                    self._config_monitor.record_refresh(
                        previous=previous, current=previous,
                        source="reload", success=False,
                        duration_ms=duration_ms, error=exc,
                    )
                except Exception:
                    logger.debug("配置监控记录失败", exc_info=True)
                self._reload_in_progress = False
                raise
            try:
                duration_ms = (time.perf_counter() - started) * 1000
                try:
                    self._config_monitor.record_refresh(
                        previous=previous, current=current,
                        source="+".join(dict.fromkeys(self._config_sources)) or "reload",
                        success=True, duration_ms=duration_ms,
                    )
                except Exception:
                    logger.debug("配置监控记录失败", exc_info=True)
                self._log("info", "Config reloaded")
                if previous_client is not None and self._nacos_config_client is None:
                    try:
                        previous_client.close()
                    except Exception:
                        # 释放旧 Nacos 客户端属于清理动作，不能把已经成功提交的
                        # 新配置变成一次失败刷新；客户端自身仍会在下一次重载时
                        # 被替换，记录日志供运维排查。
                        logger.warning("关闭旧 Nacos 配置客户端失败", exc_info=True)
            finally:
                # 无论成功后的日志/清理钩子是否抛出异常，都必须恢复状态，
                # 否则后续启动期加载会永久误判为刷新期并改变 Nacos 失败语义。
                self._reload_in_progress = False


# 创建全局配置加载器实例
config_loader = ConfigLoader()


def set_global_config_loader(loader: ConfigLoader) -> ConfigLoader:
    """Bind global configuration access to an application context loader."""
    if not isinstance(loader, ConfigLoader):
        raise TypeError("loader must be a ConfigLoader instance")

    if loader is not config_loader:
        shared_state = config_loader.__dict__
        loader_state = dict(loader.__dict__)
        shared_state.clear()
        shared_state.update(loader_state)
        loader.__dict__ = shared_state

    ConfigLoader._default_base_path = os.path.dirname(
        os.path.abspath(config_loader.config_path)
    )

    config_package = sys.modules.get('springbootai.config')
    if config_package is not None:
        setattr(config_package, 'config_loader', config_loader)
    return config_loader


def get_config() -> Dict[str, Any]:
    """获取全局配置"""
    return config_loader.get_config()


def get_config_value(key: str, default: Any = None) -> Any:
    """获取配置值"""
    return config_loader.get(key, default)
