"""
Spring ORM模块
集成PyMyBatis作为核心ORM框架
提供SQL与代码分离、事务管理、连接池等企业级数据库能力

支持两种数据访问模式：
1. Mapper模式（推荐）：使用@Mapper注解和SQL注解定义数据访问接口
2. Repository模式：使用SQLAlchemy的ORM方式进行数据访问
"""

# 导入SQLAlchemy数据库管理器（可选）
try:
    from springbootai.orm.database import (
        DatabaseManager,
        Base,
        BaseEntity,
        User,
        AuditLog,
        init_database,
    )
except ImportError:
    # SQLAlchemy未安装，这些类不可用
    DatabaseManager = None
    Base = None
    BaseEntity = None
    User = None
    AuditLog = None
    init_database = None

# 从pymybatis导入核心类
from springbootai.orm.pymybatis import (
    Configuration,
    build_session_factory,
    SqlSessionFactory,
    SqlSession,
)

# 导入Spring与MyBatis集成注解和工具
from springbootai.orm.mybatis_integration import (
    Mapper,
    MapperScan,
    MyBatisConfigurer,
    init_mybatis,
)

# 导入注解
from springbootai.orm.pymybatis.annotations import (
    Select,
    SelectPage,
    Insert,
    Update,
    Delete,
    SelectProvider,
    InsertProvider,
    UpdateProvider,
    DeleteProvider,
    ResultMap,
    Result,
    Options,
    Param,
    CacheNamespace,
    DataSource,
    Transactional as MapperTransactional,
)

# 导入安全模块
from springbootai.orm.pymybatis.security import (
    AccessCondition,
    SensitiveDataMasker,
    PasswordEncoder,
    SQLInjectionDetector,
    RoleBasedAccessControl,
    RowLevelAccessControl,
)

# 导入缓存模块
from springbootai.orm.pymybatis.cache import (
    LRUCache,
    SecondLevelCache,
)

# 导入事务模块
from springbootai.orm.pymybatis.transaction import (
    TransactionIsolationLevel,
)

# 导入拦截器模块
from springbootai.orm.pymybatis.interceptor import (
    Interceptor,
    LogInterceptor,
    PerformanceInterceptor,
    SecurityInterceptor,
)

# 导入类型处理器
from springbootai.orm.pymybatis.type_handler import (
    TypeHandler,
)

# 导入数据库方言
from springbootai.orm.pymybatis.dialect import (
    Dialect,
    get_dialect,
)

# 导入连接池
from springbootai.orm.pymybatis.pool import (
    create_connection_pool,
)

# 导入动态SQL处理器
from springbootai.orm.pymybatis.dynamic_sql import (
    DynamicSQLProcessor,
)

# 导入XML解析器
from springbootai.orm.pymybatis.xml_parser import (
    XmlParser,
)

# 导入熔断器
from springbootai.orm.pymybatis.circuit_breaker import (
    CircuitBreaker,
)

# 导入指标监控
from springbootai.orm.pymybatis.metrics import (
    MetricsCollector,
)

# 导入数据库迁移（Flyway风格）
from springbootai.orm.migration import (
    MigrationManager,
    MigrationError,
    MigrationState,
)

# 导入DDL自动建表（JPA hibernate.ddl-auto风格）
from springbootai.orm.ddl_auto import (
    DdlAutoManager,
    DdlAutoMode,
    EntityTable,
    Table,
    Column,
    Required,
    Text,
    Id,
    Version,
    CreateTime,
    UpdateTime,
    Transient,
    Index,
    Entity,
    entity,
    table as table_decorator,
    column as column_decorator,
    id_column as id_column_decorator,
    version_column,
    version_column as version_column_decorator,
    create_time_column,
    update_time_column,
    transient_field,
    transient_field as transient_field_decorator,
    init_ddl_auto,
    get_ddl_manager,
    OptimisticLockExecutor,
    OptimisticLockError,
    AuditTimeExecutor,
)

# 版本信息
from springbootai.orm.pymybatis.version import __version__

__all__ = [
    # SQLAlchemy数据库管理器
    'DatabaseManager',
    'Base',
    'BaseEntity',
    'User',
    'AuditLog',
    'init_database',
    # PyMyBatis核心类
    'Configuration',
    'build_session_factory',
    'SqlSessionFactory',
    'SqlSession',
    # Spring集成注解
    'Mapper',
    'MapperScan',
    'MyBatisConfigurer',
    'init_mybatis',
    # 注解
    'Select',
    'SelectPage',
    'Insert',
    'Update',
    'Delete',
    'SelectProvider',
    'InsertProvider',
    'UpdateProvider',
    'DeleteProvider',
    'ResultMap',
    'Result',
    'Options',
    'Param',
    'CacheNamespace',
    'DataSource',
    'MapperTransactional',
    # 安全模块
    'AccessCondition',
    'SensitiveDataMasker',
    'PasswordEncoder',
    'SQLInjectionDetector',
    'RoleBasedAccessControl',
    'RowLevelAccessControl',
    # 缓存模块
    'LRUCache',
    'SecondLevelCache',
    # 事务模块
    'TransactionIsolationLevel',
    # 拦截器模块
    'Interceptor',
    'LogInterceptor',
    'PerformanceInterceptor',
    'SecurityInterceptor',
    # 类型处理器
    'TypeHandler',
    # 数据库方言
    'Dialect',
    'get_dialect',
    # 连接池
    'create_connection_pool',
    # 动态SQL
    'DynamicSQLProcessor',
    # XML解析器
    'XmlParser',
    # 熔断器
    'CircuitBreaker',
    # 指标监控
    'MetricsCollector',
    # 数据库迁移
    'MigrationManager',
    'MigrationError',
    'MigrationState',
    # DDL自动建表
    'DdlAutoManager',
    'DdlAutoMode',
    'EntityTable',
    'Table',
    'Column',
    'Required',
    'Text',
    'Id',
    'Version',
    'CreateTime',
    'UpdateTime',
    'Transient',
    'Index',
    'Entity',
    'entity',
    'table_decorator',
    'column_decorator',
    'id_column_decorator',
    'version_column',
    'version_column_decorator',
    'create_time_column',
    'update_time_column',
    'transient_field',
    'transient_field_decorator',
    'init_ddl_auto',
    'get_ddl_manager',
    # JPA @Version 乐观锁执行器
    'OptimisticLockExecutor',
    'OptimisticLockError',
    # JPA @CreateTime/@UpdateTime 自动时间填充执行器
    'AuditTimeExecutor',
    # 版本
    '__version__',
]
