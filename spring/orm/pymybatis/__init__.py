"""
PyMyBatis - Python版MyBatis ORM框架

对标Java MyBatis，实现SQL与代码分离，支持XML映射文件、注解两种SQL编写方式。

核心特性：
- SQL注入防御（参数化查询 + AST验证）
- 敏感数据脱敏
- 连接池管理（带熔断降级机制）
- 多数据源支持
- 动态SQL（if/where/foreach标签）
- 事务管理
- 自定义类型处理器
- 拦截器插件
- 查询缓存（支持Redis分布式缓存）
- 监控指标（Prometheus兼容）

支持数据库：MySQL、PostgreSQL、SQLite、Oracle
"""

from .core import SqlSession, SqlSessionFactory
from .configuration import Configuration
from .mapper import Mapper
from .annotations import (
    CacheNamespace, DataSource, Delete, Insert, Options, Param, Result,
    ResultMap, Select, Transactional, Update,
    SelectProvider, InsertProvider, UpdateProvider, DeleteProvider,
)
from .transaction import Transaction, TransactionIsolationLevel
from .pool import ConnectionPool
from .cache import SqlCache, LRUCache, GLOBAL_SECOND_LEVEL_CACHE
from .dialect import Dialect, MySQLDialect, PostgreSQLDialect, SQLiteDialect, OracleDialect
from .security import SensitiveDataMasker, SQLInjectionDetector
from .interceptor import Interceptor
from .type_handler import TypeHandler

__version__ = "1.3.0"
__author__ = "PyMyBatis Team"

# 基础导出列表
__all__ = [
    'SqlSession', 'SqlSessionFactory', 'Configuration', 'Mapper',
    'Select', 'Insert', 'Update', 'Delete',
    'SelectProvider', 'InsertProvider', 'UpdateProvider', 'DeleteProvider',
    'ResultMap', 'Result',
    'Options', 'Param', 'CacheNamespace', 'DataSource', 'Transactional',
    'Transaction', 'TransactionIsolationLevel', 'ConnectionPool',
    'SqlCache', 'LRUCache', 'GLOBAL_SECOND_LEVEL_CACHE', 'Dialect',
    'MySQLDialect', 'PostgreSQLDialect', 'SQLiteDialect', 'OracleDialect',
    'SensitiveDataMasker', 'SQLInjectionDetector', 'Interceptor', 'TypeHandler',
    'build_session_factory',
]

# 可选模块（按需导入）
try:
    from .circuit_breaker import CircuitBreaker, DatabaseCircuitBreaker, CircuitBreakerState, CircuitBreakerError
    __all__.extend(['CircuitBreaker', 'DatabaseCircuitBreaker', 'CircuitBreakerState', 'CircuitBreakerError'])
except ImportError:
    pass

try:
    from .cache.redis_cache import RedisSecondLevelCache, create_redis_cache
    __all__.extend(['RedisSecondLevelCache', 'create_redis_cache'])
except ImportError:
    pass

try:
    from .metrics import MetricsCollector, Counter, Gauge, Histogram, Timer, get_default_collector
    __all__.extend(['MetricsCollector', 'Counter', 'Gauge', 'Histogram', 'Timer', 'get_default_collector'])
except ImportError:
    pass


def build_session_factory(config: dict) -> SqlSessionFactory:
    """
    快速构建SqlSessionFactory

    Args:
        config: 配置字典，包含数据源、映射文件等配置

    Returns:
        SqlSessionFactory实例
    """
    configuration = Configuration()
    configuration.load_config(config)
    return SqlSessionFactory(configuration)
