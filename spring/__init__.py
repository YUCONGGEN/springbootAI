from .annotations import *
from .context import *
from .web import *
from .config import *
from .utils import *
from .main import create_app, run, SpringApplication, run_cli

__version__ = "1.5.0"
__author__ = "SpringPy Team"
__license__ = "MIT"

# ORM迁移
from .orm.migration import MigrationManager, MigrationError

# 核心模块（优雅退出）
from .core.graceful_shutdown import GracefulShutdown, shutdown_handler

# 安全模块
from .security.secret_manager import SecretManager, is_sensitive_key, mask_secret, resolve_secret_config
from .security.replay_protection import ReplayProtection, NonceCache, create_replay_protection

__all__ = [
    # 框架入口
    "run",
    "create_app",
    "SpringApplication",
    "run_cli",
    # 配置
    "ConfigLoader",
    "ConfigurationError",
    "config_loader",
    "set_global_config_loader",
    "get_config",
    "get_config_value",
    # 上下文
    "ApplicationContext",
    "BeanDefinition",
    "BeanFactory",
    "ComponentScanner",
    "BeanRegistry",
    # Web
    "WebApplicationContext",
    "Result",
    "HandlerInterceptor",
    "InterceptorRegistry",
    "GlobalExceptionHandler",
    # 工具
    "SpringLogger",
    "BannerPrinter",
    # ORM迁移
    "MigrationManager",
    "MigrationError",
    # 安全
    "SecretManager",
    "ReplayProtection",
    "NonceCache",
    "create_replay_protection",
    "mask_secret",
    "is_sensitive_key",
    "resolve_secret_config",
    # 优雅退出
    "GracefulShutdown",
    "shutdown_handler",
    # 版本
    "__version__",
]
