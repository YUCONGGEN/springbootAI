"""
PyMyBatis配置管理模块

负责加载和管理框架的所有配置项，包括：
- 数据源配置（支持环境变量读取）
- 映射文件配置
- 缓存配置
- 事务配置
- 安全配置
- 连接池配置
"""

import os
import json
import yaml
import re
from typing import Dict, List, Optional, Any


class ConfigurationError(ValueError):
    """Raised when ORM configuration is missing or internally inconsistent."""


class Configuration:
    """
    配置管理类

    核心职责：
    1. 加载配置文件（JSON/YAML）
    2. 管理多数据源配置
    3. 管理映射器配置
    4. 管理缓存配置
    5. 管理事务和安全配置
    6. 支持环境变量读取（${ENV_VAR}格式）
    """

    # 环境变量替换模式：${ENV_VAR} 或 ${ENV_VAR:default}
    ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def __init__(self):
        # 数据源配置
        self.datasources: Dict[str, Dict[str, Any]] = {}

        # 默认数据源名称
        self.default_datasource: str = 'default'

        # 映射器配置
        self.mappers: List[str] = []

        # XML映射文件路径
        self.mapper_locations: List[str] = []

        # 缓存配置
        self.cache_enabled: bool = True
        self.cache_type: str = 'lru'
        self.cache_size: int = 1024
        self.cache_ttl: int = 3600

        # Redis缓存配置（可选）
        self.redis_cache_enabled: bool = False
        self.redis_cache_config: Dict[str, Any] = {}

        # 事务配置
        self.default_transaction_isolation: str = 'READ_COMMITTED'
        self.default_fetch_size: int = 100
        self.default_timeout: int = 30

        # 连接池配置
        self.pool_min_size: int = 5
        self.pool_max_size: int = 20
        self.pool_max_idle: int = 10
        self.pool_wait_timeout: int = 30
        self.pool_validation_interval: int = 300
        self.leak_detection_enabled: bool = True
        self.leak_timeout: int = 300

        # 熔断器配置
        self.circuit_breaker_enabled: bool = False
        self.circuit_breaker_failure_threshold: int = 3
        self.circuit_breaker_recovery_timeout: int = 60
        self.circuit_breaker_success_threshold: int = 3

        # 安全配置
        self.sql_injection_detection: bool = True
        self.ast_validation_enabled: bool = False  # AST验证（需要sqlglot）
        self.sensitive_data_masking: bool = True
        self.access_control_enabled: bool = False
        self.log_masking_enabled: bool = True
        self.block_ddl: bool = True
        self.allow_raw_params: bool = False
        self.allowed_tables: List[str] = []  # 允许的表名白名单
        self.allowed_columns: List[str] = []  # 允许的字段名白名单

        # 性能配置
        self.sql_precompile_cache: bool = True
        self.result_map_cache: bool = True
        self.lazy_load_mappers: bool = True

        # 批量操作配置
        self.max_batch_size: int = 1000
        self.batch_split_size: int = 100

        # 类型处理器注册
        self.type_handlers: Dict[str, Any] = {}

        # 拦截器列表
        self.interceptors: List[Any] = []

        # 方言配置
        self.dialect: str = 'mysql'

        # 日志配置
        self.log_level: str = 'INFO'
        self.log_file: Optional[str] = None

        # 分页配置
        self.max_pagination_offset: int = 10000

        # 监控指标配置
        self.metrics_enabled: bool = False
        self.metrics_endpoint: str = '/metrics'
        self.metrics_port: int = 9090

    def _resolve_env_var(self, value: str) -> Any:
        """
        解析环境变量引用

        支持格式：
        - ${ENV_VAR} - 直接读取环境变量
        - ${ENV_VAR:default} - 读取环境变量，不存在使用默认值

        Args:
            value: 包含环境变量引用的字符串

        Returns:
            解析后的字符串
        """
        if not isinstance(value, str):
            return value

        exact_placeholder = self.ENV_VAR_PATTERN.fullmatch(value)

        def replace_env(match):
            env_spec = match.group(1)

            # 检查是否有默认值
            if ':' in env_spec:
                env_name, default_value = env_spec.split(':', 1)
            else:
                env_name = env_spec
                default_value = None  # 使用None表示没有默认值

            # 从环境变量获取值
            env_value = os.environ.get(env_name.strip())

            # 如果环境变量不存在，使用默认值
            if env_value is None:
                if default_value is None:
                    raise ConfigurationError(f"必需的环境变量 {env_name.strip()} 未设置")
                return default_value

            return env_value

        resolved = self.ENV_VAR_PATTERN.sub(replace_env, value)
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

        if isinstance(config, dict):
            resolved = {}
            for key, value in config.items():
                resolved[key] = self._resolve_config_recursive(value)
            return resolved

        if isinstance(config, list):
            resolved = []
            for item in config:
                resolved.append(self._resolve_config_recursive(item))
            return resolved

        return config

    def load_config(self, config: Dict[str, Any]) -> None:
        """
        加载配置字典（支持环境变量解析）

        Args:
            config: 配置字典
        """
        # 递归解析环境变量
        config = self._resolve_config_recursive(config)
        if not isinstance(config, dict):
            raise ConfigurationError("ORM配置根节点必须是对象")

        # 加载数据源配置（支持单数据源和多数据源两种格式）
        if 'datasource' in config:
            # 单数据源格式
            self.datasources = {'default': config['datasource']}
            self.default_datasource = 'default'
            
            # 根据驱动自动设置方言
            driver = config['datasource'].get('driver', 'mysql').lower()
            if driver == 'sqlite':
                self.dialect = 'sqlite'
            elif driver == 'postgresql':
                self.dialect = 'postgresql'
            elif driver == 'oracle':
                self.dialect = 'oracle'
            else:
                self.dialect = 'mysql'

        elif 'datasources' in config:
            # 多数据源格式
            self.datasources = config['datasources']
            if 'default' in self.datasources:
                self.default_datasource = 'default'

        # 加载默认数据源
        if 'default_datasource' in config:
            self.default_datasource = config['default_datasource']

        # 加载映射器配置
        if 'mappers' in config:
            self.mappers = config['mappers']

        # 加载XML映射文件路径（支持mapper_paths和mapper_locations两种格式）
        if 'mapper_paths' in config:
            self.mapper_locations = config['mapper_paths']
        elif 'mapper_locations' in config:
            self.mapper_locations = config['mapper_locations']

        # 加载缓存配置
        if 'cache' in config:
            cache_config = config['cache']
            self.cache_enabled = cache_config.get('enabled', True)
            self.cache_type = cache_config.get('type', 'lru')
            self.cache_size = cache_config.get('size', 1024)
            self.cache_ttl = cache_config.get('ttl', 3600)

            # Redis缓存配置
            if 'redis' in cache_config:
                redis_config = cache_config['redis']
                self.redis_cache_enabled = redis_config.get('enabled', False)
                self.redis_cache_config = redis_config

        # 加载事务配置
        if 'transaction' in config:
            tx_config = config['transaction']
            self.default_transaction_isolation = tx_config.get('isolation', 'READ_COMMITTED')
            self.default_fetch_size = tx_config.get('fetch_size', 100)
            self.default_timeout = tx_config.get('timeout', 30)

        # 加载连接池配置
        if 'pool' in config:
            pool_config = config['pool']
            self.pool_min_size = int(pool_config.get('min_size', 5))
            self.pool_max_size = int(pool_config.get('max_size', 20))
            self.pool_max_idle = float(pool_config.get('max_idle', 10))
            self.pool_wait_timeout = float(pool_config.get('wait_timeout', 30))
            self.pool_validation_interval = float(pool_config.get('validation_interval', 300))
            self.leak_detection_enabled = pool_config.get('leak_detection_enabled', True)
            self.leak_timeout = float(pool_config.get('leak_timeout', 300))

            # 熔断器配置
            if 'circuit_breaker' in pool_config:
                cb_config = pool_config['circuit_breaker']
                self.circuit_breaker_enabled = cb_config.get('enabled', False)
                self.circuit_breaker_failure_threshold = int(cb_config.get('failure_threshold', 3))
                self.circuit_breaker_recovery_timeout = float(cb_config.get('recovery_timeout', 60))
                self.circuit_breaker_success_threshold = int(cb_config.get('success_threshold', 3))

        # 加载安全配置
        if 'security' in config:
            security_config = config['security']
            self.sql_injection_detection = security_config.get('sql_injection_detection', True)
            self.ast_validation_enabled = security_config.get('ast_validation_enabled', False)
            self.sensitive_data_masking = security_config.get('sensitive_data_masking', True)
            self.access_control_enabled = security_config.get('access_control_enabled', False)
            self.log_masking_enabled = security_config.get('log_masking_enabled', True)
            self.block_ddl = security_config.get('block_ddl', True)
            self.allow_raw_params = security_config.get('allow_raw_params', False)
            self.allowed_tables = security_config.get('allowed_tables', [])
            self.allowed_columns = security_config.get('allowed_columns', [])

        # 加载性能配置
        if 'performance' in config:
            perf_config = config['performance']
            self.sql_precompile_cache = perf_config.get('sql_precompile_cache', True)
            self.result_map_cache = perf_config.get('result_map_cache', True)
            self.lazy_load_mappers = perf_config.get('lazy_load_mappers', True)

        # 加载批量操作配置
        if 'batch' in config:
            batch_config = config['batch']
            self.max_batch_size = batch_config.get('max_size', 1000)
            self.batch_split_size = batch_config.get('split_size', 100)

        # 加载方言配置
        if 'dialect' in config:
            self.dialect = config['dialect']

        # 加载日志配置
        if 'logging' in config:
            logging_config = config['logging']
            self.log_level = logging_config.get('level', 'INFO')
            self.log_file = logging_config.get('file')

        # 加载分页配置
        if 'pagination' in config:
            pagination_config = config['pagination']
            self.max_pagination_offset = pagination_config.get('max_offset', 10000)

        # 加载监控指标配置
        if 'metrics' in config:
            metrics_config = config['metrics']
            self.metrics_enabled = metrics_config.get('enabled', False)
            self.metrics_endpoint = metrics_config.get('endpoint', '/metrics')
            self.metrics_port = metrics_config.get('port', 9090)

        self._validate()

    def _validate(self) -> None:
        if self.datasources and self.default_datasource not in self.datasources:
            raise ConfigurationError(f"默认数据源不存在: {self.default_datasource}")
        if self.pool_min_size < 0 or self.pool_max_size < 1:
            raise ConfigurationError("连接池大小必须为非负数，且 max_size 必须大于 0")
        if self.pool_min_size > self.pool_max_size:
            raise ConfigurationError("连接池 min_size 不能大于 max_size")
        if self.pool_wait_timeout <= 0 or self.pool_validation_interval <= 0 or self.leak_timeout <= 0:
            raise ConfigurationError("连接池超时配置必须大于 0")
        valid_isolation_levels = {
            'READ_UNCOMMITTED', 'READ_COMMITTED', 'REPEATABLE_READ', 'SERIALIZABLE'
        }
        if self.default_transaction_isolation not in valid_isolation_levels:
            raise ConfigurationError(
                f"不支持的事务隔离级别: {self.default_transaction_isolation}"
            )

    def load_config_file(self, file_path: str) -> None:
        """
        从配置文件加载配置（支持环境变量解析）

        Args:
            file_path: 配置文件路径，支持JSON和YAML格式
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"配置文件不存在: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        with open(file_path, 'r', encoding='utf-8') as f:
            if ext == '.json':
                config = json.load(f)
            elif ext in ('.yaml', '.yml'):
                config = yaml.safe_load(f)
            else:
                raise ValueError(f"不支持的配置文件格式: {ext}")

        self.load_config(config)

    def get_datasource(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取数据源配置（已解析环境变量）

        Args:
            name: 数据源名称，默认为默认数据源

        Returns:
            数据源配置字典
        """
        ds_name = name or self.default_datasource
        if ds_name not in self.datasources:
            raise ValueError(f"数据源不存在: {ds_name}")
        return self.datasources[ds_name]

    def register_type_handler(self, java_type: str, handler: Any) -> None:
        """
        注册自定义类型处理器

        Args:
            java_type: Java类型全限定名
            handler: 类型处理器实例
        """
        self.type_handlers[java_type] = handler

    def register_interceptor(self, interceptor: Any) -> None:
        """
        注册拦截器

        Args:
            interceptor: 拦截器实例
        """
        self.interceptors.append(interceptor)

    def is_cache_enabled(self) -> bool:
        """检查缓存是否启用"""
        return self.cache_enabled

    def is_sql_injection_detection_enabled(self) -> bool:
        """检查SQL注入检测是否启用"""
        return self.sql_injection_detection

    def is_sensitive_data_masking_enabled(self) -> bool:
        """检查敏感数据脱敏是否启用"""
        return self.sensitive_data_masking

    def is_access_control_enabled(self) -> bool:
        """检查访问控制是否启用"""
        return self.access_control_enabled

    def is_log_masking_enabled(self) -> bool:
        """检查日志脱敏是否启用"""
        return self.log_masking_enabled

    def is_sql_precompile_cache_enabled(self) -> bool:
        """检查SQL预编译缓存是否启用"""
        return self.sql_precompile_cache

    def is_result_map_cache_enabled(self) -> bool:
        """检查结果集映射缓存是否启用"""
        return self.result_map_cache

    def is_lazy_load_mappers_enabled(self) -> bool:
        """检查映射器懒加载是否启用"""
        return self.lazy_load_mappers

    def is_ddl_blocked(self) -> bool:
        """检查DDL语句是否被阻止"""
        return self.block_ddl

    def is_raw_params_allowed(self) -> bool:
        """检查${}参数是否允许使用"""
        return self.allow_raw_params

    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典（不包含敏感信息）"""
        return {
            'datasources': {name: {k: '******' if k.lower() in ('password', 'pwd') else v
                                   for k, v in ds.items()}
                            for name, ds in self.datasources.items()},
            'default_datasource': self.default_datasource,
            'mappers': self.mappers,
            'mapper_locations': self.mapper_locations,
            'cache': {
                'enabled': self.cache_enabled,
                'type': self.cache_type,
                'size': self.cache_size,
                'ttl': self.cache_ttl,
                'redis': {
                    'enabled': self.redis_cache_enabled,
                    **{k: '******' if k.lower() == 'password' else v
                       for k, v in self.redis_cache_config.items()}
                }
            },
            'transaction': {
                'isolation': self.default_transaction_isolation,
                'fetch_size': self.default_fetch_size,
                'timeout': self.default_timeout
            },
            'pool': {
                'min_size': self.pool_min_size,
                'max_size': self.pool_max_size,
                'max_idle': self.pool_max_idle,
                'wait_timeout': self.pool_wait_timeout,
                'validation_interval': self.pool_validation_interval,
                'leak_detection_enabled': self.leak_detection_enabled,
                'leak_timeout': self.leak_timeout,
                'circuit_breaker': {
                    'enabled': self.circuit_breaker_enabled,
                    'failure_threshold': self.circuit_breaker_failure_threshold,
                    'recovery_timeout': self.circuit_breaker_recovery_timeout,
                    'success_threshold': self.circuit_breaker_success_threshold
                }
            },
            'security': {
                'sql_injection_detection': self.sql_injection_detection,
                'ast_validation_enabled': self.ast_validation_enabled,
                'sensitive_data_masking': self.sensitive_data_masking,
                'access_control_enabled': self.access_control_enabled,
                'log_masking_enabled': self.log_masking_enabled,
                'block_ddl': self.block_ddl,
                'allow_raw_params': self.allow_raw_params,
                'allowed_tables': self.allowed_tables,
                'allowed_columns': self.allowed_columns
            },
            'performance': {
                'sql_precompile_cache': self.sql_precompile_cache,
                'result_map_cache': self.result_map_cache,
                'lazy_load_mappers': self.lazy_load_mappers
            },
            'batch': {
                'max_size': self.max_batch_size,
                'split_size': self.batch_split_size
            },
            'dialect': self.dialect,
            'logging': {
                'level': self.log_level,
                'file': self.log_file
            },
            'pagination': {
                'max_offset': self.max_pagination_offset
            },
            'metrics': {
                'enabled': self.metrics_enabled,
                'endpoint': self.metrics_endpoint,
                'port': self.metrics_port
            }
        }

    def __repr__(self) -> str:
        return f"<Configuration dialect={self.dialect}, datasources={list(self.datasources.keys())}>"
