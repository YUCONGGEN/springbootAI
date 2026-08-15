"""
配置加载器
支持从YAML文件和环境变量加载配置
"""
import os
import sys
import yaml
import logging
import re
from copy import deepcopy
from typing import Dict, Any, Optional

logger = logging.getLogger("Spring.Config")


class ConfigurationError(ValueError):
    """应用配置缺失、格式错误或不满足生产安全要求。"""


# 匹配非字母数字字符（kebab/camel/snake 分隔符）用于松散匹配规范化
_NON_ALNUM = re.compile(r'[^0-9a-zA-Z]+')


def _normalize_name(name: str) -> str:
    """规范化命名：去除分隔符并小写，用于 ``get()`` 的松散匹配。

    ``log_dir`` / ``log-dir`` / ``LOG_DIR`` / ``log.dir`` → ``logdir``。
    与 ``spring.config.binding._normalize`` 保持一致，避免循环导入在此独立定义。
    """
    if not isinstance(name, str):
        return str(name).lower()
    return _NON_ALNUM.sub('', name).lower()


def _to_bool(value: Any, default: bool = False) -> bool:
    """统一布尔转换：接受 ``true/1/yes/on``（大小写不敏感），其余为 False。

    与 ``spring.config.binding._coerce`` 的布尔规则保持一致，避免
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
                logger.warning("Ignoring invalid configuration section %s (expected an object)", name)
            self._config[name] = section
        return section
    
    def __init__(self, config_path: str = "application.yml", base_path: str = None, _test_mode: bool = False):
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
        self._load_config()

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
        if not profile or profile == 'default':
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
            logger.warning(
                "Found .env at %s but python-dotenv is not installed; ignoring it",
                dotenv_path,
            )
            return

        load_dotenv(dotenv_path=dotenv_path, override=False)
        logger.debug("Loaded project environment from %s", dotenv_path)

    def _load_config(self):
        """加载配置"""
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
                logger.info(f"Loaded config from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config from {self.config_path}: {e}")
                raise ConfigurationError(f"无法加载配置文件 {self.config_path}") from e

        # Profile discovery below reads nested sections before environment
        # binding.  Normalize immediately after loading the main YAML so a
        # null/list section cannot break profile lookup.
        self._normalize_section_mappings()

        # 1.5 加载 profile 特定配置文件并深度合并（application-{profile}.yml 覆盖主配置）
        #     profile 来自主配置的 spring.profiles.active 或 SPRING_PROFILES_ACTIVE 环境变量。
        #     在占位符解析之前合并，使 profile 文件中的占位符也能被解析。
        spring_config = self._mapping(self._config.get('spring'))
        profiles_config = self._mapping(spring_config.get('profiles'))
        profile = os.getenv('SPRING_PROFILES_ACTIVE') or profiles_config.get('active', 'default')
        # 兼容 dict 格式的 profile.active（如 spring.profiles.active: {name: prod}）
        if isinstance(profile, dict):
            profile = profile.get('name') or profile.get('active') or 'default'
        if profile:
            profile = str(profile).strip()
        profile_path = self._resolve_profile_path(profile) if profile else None
        if profile_path:
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_config = yaml.safe_load(f) or {}
                if isinstance(profile_config, dict):
                    self._config = self._deep_merge(self._config, profile_config)
                    logger.info(f"Loaded profile config from {profile_path} (profile={profile})")
            except Exception as e:
                logger.warning(f"Failed to load profile config {profile_path}: {e}")

        # A profile may replace a whole section with null/list/scalar.  Restore
        # the mapping contract before resolving placeholders and overrides.
        self._normalize_section_mappings()

        # 2. 解析配置中的环境变量占位符
        self._config = self._resolve_config_recursive(self._config)

        # 3. 从环境变量覆盖配置
        self._override_with_env()
        # 4. 从命令行参数覆盖配置（优先级最高）
        self._override_with_cli_args()
        # CLI may replace a complete section (for example ``--server=[]``).
        # Re-apply the mapping contract before validation and application use.
        self._normalize_section_mappings()
        self._validate_config()
    
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
            value = value.get('value') or value.get('timeout') or default
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

        # 数据库配置
        database_config = self._ensure_section('database')
        database_config['url'] = os.getenv('DB_URL', database_config.get('url', 'sqlite:///./test.db'))
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

    def _override_with_cli_args(self) -> None:
        """从命令行参数覆盖配置（优先级最高，对齐 Spring Boot ``--key=value``）。

        支持两种形式：
        - ``--server.port=9000``
        - ``--server.port 9000``

        点分隔键递归写入 ``self._config``，值经 ``yaml.safe_load`` 做类型推断
        （``9000`` → int，``true`` → bool）。在 ``_override_with_env`` 之后调用。
        """
        args = sys.argv[1:]
        i = 0
        while i < len(args):
            arg = args[i]
            if not arg.startswith('--'):
                i += 1
                continue
            body = arg[2:]
            if '=' in body:
                key, value = body.split('=', 1)
                self._set_cli_override(key, value)
                i += 1
            else:
                # --key value 形式：仅当下一个 token 非参数时才取值
                if i + 1 < len(args) and not args[i + 1].startswith('--'):
                    self._set_cli_override(body, args[i + 1])
                    i += 2
                else:
                    i += 1

    def _set_cli_override(self, dotted_key: str, raw_value: str) -> None:
        """将点分隔键写入 ``self._config``，值做 yaml 类型推断。"""
        keys = dotted_key.split('.')
        node = self._config
        for k in keys[:-1]:
            child = node.get(k)
            if not isinstance(child, dict):
                child = {}
                node[k] = child
            node = child
        parsed = yaml.safe_load(raw_value)
        node[keys[-1]] = parsed
        logger.debug(f"CLI override: {dotted_key}={parsed!r}")

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
        # (1) 强制 AI_ALLOW_FAKE=false，使 autoconfig 缺 key 时抛 ValueError；
        # (2) 在此显式校验默认 provider 的 api-key 已配置，给出清晰错误。
        os.environ['AI_ALLOW_FAKE'] = 'false'
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
                # 兼容 spring.ai.<provider>.api-key（kebab）与 ai.<provider>.api_key（snake）
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
                        f"spring.ai.{provider}.api-key。生产环境不允许静默使用 FakeChatModel。"
                    )
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
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
        lookup happens first, then an environment variable with the same name,
        followed by the expression default.  A missing value returns the
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

        value = self.get(key, self._MISSING)
        if value is not self._MISSING:
            return value

        env_value = os.getenv(key)
        if env_value is not None:
            parsed = yaml.safe_load(env_value)
            return parsed if not isinstance(parsed, (dict, list)) else env_value

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
        spring_config = self._mapping(self._config.get('spring'))
        profiles_config = self._mapping(spring_config.get('profiles'))
        active = profiles_config.get('active') or 'default'
        # 兼容 dict 格式（如 spring.profiles.active: {name: prod}）
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
        keys = key.split('.')
        value = self._config

        for k in keys:
            value, found = self._lookup_key(value, k)
            if not found:
                return default

        return value
    
    def load_config(self):
        """加载配置（公共方法，供外部调用）"""
        self._load_config()
    
    def reload(self):
        """重新加载配置"""
        self._config = {}
        self._load_config()
        logger.info("Config reloaded")


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

    config_package = sys.modules.get('spring.config')
    if config_package is not None:
        setattr(config_package, 'config_loader', config_loader)
    return config_loader


def get_config() -> Dict[str, Any]:
    """获取全局配置"""
    return config_loader.get_config()


def get_config_value(key: str, default: Any = None) -> Any:
    """获取配置值"""
    return config_loader.get(key, default)
