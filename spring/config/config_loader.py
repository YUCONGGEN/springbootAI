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


class ConfigLoader:
    """配置加载器"""

    # ApplicationContext updates this after startup so later ``ConfigLoader()``
    # calls resolve the same application.yml instead of depending on CWD.
    _default_base_path: Optional[str] = None
    
    # 环境变量替换模式：${ENV_VAR} 或 ${ENV_VAR:default}
    _ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')
    _VALUE_EXPRESSION_PATTERN = re.compile(r'^\$\{([^}:]+)(?::(.*))?\}$')
    _MISSING = object()
    
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
        
        exact_placeholder = self._ENV_VAR_PATTERN.fullmatch(value)

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
        
        resolved = self._ENV_VAR_PATTERN.sub(replace_env, value)
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
    
    def _load_config(self):
        """加载配置"""
        # 1. 尝试从YAML文件加载
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
        
        # 2. 解析配置中的环境变量占位符
        self._config = self._resolve_config_recursive(self._config)
        
        # 3. 从环境变量覆盖配置
        self._override_with_env()
        self._validate_config()
    
    def _override_with_env(self):
        """使用环境变量覆盖配置"""
        self._config.setdefault('spring', {})
        self._config['spring'].setdefault('profiles', {})
        self._config['spring']['profiles']['active'] = os.getenv(
            'SPRING_PROFILES_ACTIVE',
            self._config['spring']['profiles'].get('active', 'default'),
        )

        self._config.setdefault('startup', {})
        fail_fast_env = os.getenv('STARTUP_FAIL_FAST')
        configured_fail_fast = self._config['startup'].get('fail_fast')
        if fail_fast_env is not None:
            self._config['startup']['fail_fast'] = fail_fast_env.lower() == 'true'
        elif configured_fail_fast is None:
            self._config['startup'].pop('fail_fast', None)
        else:
            self._config['startup']['fail_fast'] = bool(configured_fail_fast)

        # Redis配置
        self._config.setdefault('redis', {})
        self._config['redis']['host'] = os.getenv('REDIS_HOST', self._config['redis'].get('host', 'localhost'))
        self._config['redis']['port'] = int(os.getenv('REDIS_PORT', str(self._config['redis'].get('port', 6379))))
        self._config['redis']['db'] = int(os.getenv('REDIS_DB', str(self._config['redis'].get('db', 0))))
        self._config['redis']['password'] = os.getenv('REDIS_PASSWORD', self._config['redis'].get('password'))
        self._config['redis']['enabled'] = os.getenv('REDIS_ENABLED', str(self._config['redis'].get('enabled', False))).lower() == 'true'
        
        # JWT配置
        self._config.setdefault('jwt', {})
        self._config['jwt']['secret_key'] = os.getenv('JWT_SECRET_KEY', self._config['jwt'].get('secret_key', 'spring-python-secret-key-change-in-production'))
        self._config['jwt']['algorithm'] = os.getenv('JWT_ALGORITHM', self._config['jwt'].get('algorithm', 'HS256'))
        
        # 数据库配置
        self._config.setdefault('database', {})
        self._config['database']['url'] = os.getenv('DB_URL', self._config['database'].get('url', 'sqlite:///./test.db'))
        self._config['database']['echo'] = os.getenv('DB_ECHO', str(self._config['database'].get('echo', False))).lower() == 'true'
        self._config['database']['enabled'] = os.getenv('DB_ENABLED', str(self._config['database'].get('enabled', False))).lower() == 'true'
        # PyMyBatis原生数据源配置（host/port/driver等）
        self._config['database']['driver'] = os.getenv('DB_DRIVER', self._config['database'].get('driver', 'sqlite'))
        self._config['database']['host'] = os.getenv('DB_HOST', self._config['database'].get('host', 'localhost'))
        self._config['database']['port'] = int(os.getenv('DB_PORT', str(self._config['database'].get('port', 3306))))
        self._config['database']['database'] = os.getenv('DB_NAME', self._config['database'].get('database', 'test'))
        self._config['database']['username'] = os.getenv('DB_USERNAME', self._config['database'].get('username', ''))
        self._config['database']['password'] = os.getenv('DB_PASSWORD', self._config['database'].get('password', ''))
        
        # 服务发现配置
        self._config.setdefault('discovery', {})
        self._config['discovery']['server_addr'] = os.getenv('DISCOVERY_SERVER_ADDR', self._config['discovery'].get('server_addr', 'localhost:8848'))
        self._config['discovery']['namespace'] = os.getenv('DISCOVERY_NAMESPACE', self._config['discovery'].get('namespace', ''))
        self._config['discovery']['group'] = os.getenv('DISCOVERY_GROUP', self._config['discovery'].get('group', 'DEFAULT_GROUP'))
        self._config['discovery']['username'] = os.getenv('NACOS_USERNAME', self._config['discovery'].get('username', ''))
        self._config['discovery']['password'] = os.getenv('NACOS_PASSWORD', self._config['discovery'].get('password', ''))
        self._config['discovery']['enabled'] = os.getenv('DISCOVERY_ENABLED', str(self._config['discovery'].get('enabled', False))).lower() == 'true'
        
        # Seata配置
        self._config.setdefault('seata', {})
        self._config['seata']['server_addr'] = os.getenv('SEATA_SERVER_ADDR', self._config['seata'].get('server_addr', 'localhost:8091'))
        self._config['seata']['application_id'] = os.getenv('SEATA_APPLICATION_ID', self._config['seata'].get('application_id', ''))
        self._config['seata']['transaction_group'] = os.getenv('SEATA_TRANSACTION_GROUP', self._config['seata'].get('transaction_group', 'my_tx_group'))
        self._config['seata']['enabled'] = os.getenv('SEATA_ENABLED', str(self._config['seata'].get('enabled', False))).lower() == 'true'
        
        # RabbitMQ配置
        self._config.setdefault('rabbitmq', {})
        self._config['rabbitmq']['host'] = os.getenv('RABBITMQ_HOST', self._config['rabbitmq'].get('host', 'localhost'))
        self._config['rabbitmq']['port'] = int(os.getenv('RABBITMQ_PORT', str(self._config['rabbitmq'].get('port', 5672))))
        self._config['rabbitmq']['username'] = os.getenv('RABBITMQ_USERNAME', self._config['rabbitmq'].get('username', 'guest'))
        self._config['rabbitmq']['password'] = os.getenv('RABBITMQ_PASSWORD', self._config['rabbitmq'].get('password', 'guest'))
        self._config['rabbitmq']['virtual_host'] = os.getenv('RABBITMQ_VIRTUAL_HOST', self._config['rabbitmq'].get('virtual_host', '/'))
        self._config['rabbitmq']['enabled'] = os.getenv('RABBITMQ_ENABLED', str(self._config['rabbitmq'].get('enabled', False))).lower() == 'true'
        
        # Prometheus配置
        self._config.setdefault('prometheus', {})
        self._config['prometheus']['namespace'] = os.getenv('PROMETHEUS_NAMESPACE', self._config['prometheus'].get('namespace', 'spring'))
        self._config['prometheus']['subsystem'] = os.getenv('PROMETHEUS_SUBSYSTEM', self._config['prometheus'].get('subsystem', 'python'))
        self._config['prometheus']['port'] = int(os.getenv('PROMETHEUS_PORT', str(self._config['prometheus'].get('port', 8000))))
        self._config['prometheus']['enabled'] = os.getenv('PROMETHEUS_ENABLED', str(self._config['prometheus'].get('enabled', False))).lower() == 'true'
        
        # 日志配置
        self._config.setdefault('logging', {})
        self._config['logging']['level'] = os.getenv('LOG_LEVEL', self._config['logging'].get('level', 'INFO'))
        self._config['logging']['log_dir'] = os.getenv('LOG_DIR', self._config['logging'].get('log_dir', 'logs'))
        self._config['logging']['retention'] = os.getenv('LOG_RETENTION', self._config['logging'].get('retention', '30 days'))
        self._config['logging']['rotation'] = os.getenv('LOG_ROTATION', self._config['logging'].get('rotation', '100 MB'))
        
        # 服务器配置
        self._config.setdefault('server', {})
        self._config['server']['port'] = int(os.getenv('SERVER_PORT', str(self._config['server'].get('port', 8080))))
        self._config['server']['host'] = os.getenv('SERVER_HOST', self._config['server'].get('host', '0.0.0.0'))

        self._config['server'].setdefault('cors', {})
        cors_config = self._config['server']['cors']
        origins_env = os.getenv('CORS_ALLOW_ORIGINS')
        if origins_env is not None:
            cors_config['allow_origins'] = [
                origin.strip() for origin in origins_env.split(',') if origin.strip()
            ]
        else:
            cors_config.setdefault('allow_origins', [])
        cors_config['allow_credentials'] = os.getenv(
            'CORS_ALLOW_CREDENTIALS', str(cors_config.get('allow_credentials', False))
        ).lower() == 'true'

    def _validate_config(self) -> None:
        algorithm = str(self._config.get('jwt', {}).get('algorithm', 'HS256')).upper()
        if algorithm not in {'HS256', 'HS384', 'HS512'}:
            raise ConfigurationError(f"不允许的 JWT 算法: {algorithm}")

        cors = self._config.get('server', {}).get('cors', {})
        if cors.get('allow_credentials') and '*' in cors.get('allow_origins', []):
            raise ConfigurationError("CORS 开启凭证时不能使用通配来源 *")

        profile = str(
            os.getenv('SPRING_PROFILES_ACTIVE')
            or os.getenv('APP_ENV')
            or self.get_active_profile()
        ).lower()
        if profile not in {'prod', 'production'}:
            return

        secret = self._config.get('jwt', {}).get('secret_key')
        insecure_secret = 'spring-python-secret-key-change-in-production'
        if not secret or secret == insecure_secret or len(str(secret)) < 32:
            raise ConfigurationError("生产环境 JWT_SECRET_KEY 必须设置为至少 32 个字符的随机密钥")
    
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
        return self._config.get('spring', {}).get('profiles', {}).get('active', 'default')
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点分隔（如 redis.host）
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
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
