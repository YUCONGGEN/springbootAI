"""
Spring与MyBatis集成模块
提供@MapperScan、@Mapper等注解，实现Mapper自动注册到Spring容器
"""
from typing import Optional, List, Dict, Type
import os
import sys
import inspect
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from springbootai.annotations.core import SpringAnnotation
from springbootai.context.bean_factory import BeanFactory
from springbootai.context.bean_definition import BeanDefinition
from springbootai.config.config_loader import ConfigLoader
from springbootai.orm.pymybatis import build_session_factory, SqlSessionFactory, SqlSession

logger = logging.getLogger("Spring.MyBatis")
_transaction_session: ContextVar[Optional[SqlSession]] = ContextVar(
    'spring_mybatis_transaction_session', default=None
)


def get_transaction_session() -> Optional[SqlSession]:
    return _transaction_session.get()


@contextmanager
def mybatis_transaction(session_factory: SqlSessionFactory, propagation: str = 'REQUIRED'):
    """Bind one ``SqlSession`` to the current execution context.

    The propagation names intentionally follow Spring's transaction contract.
    ``REQUIRES_NEW`` gets a separate session/connection while the outer
    context is suspended.  ``NOT_SUPPORTED`` runs without a bound session so
    mapper calls use their normal short-lived, auto-commit session.
    """
    normalized = str(propagation or 'REQUIRED').upper()
    supported = {
        'REQUIRED', 'REQUIRES_NEW', 'NESTED', 'SUPPORTS',
        'MANDATORY', 'NOT_SUPPORTED', 'NEVER',
    }
    if normalized not in supported:
        raise ValueError(
            f"不支持的事务传播级别: {propagation}; 可选: {', '.join(sorted(supported))}"
        )

    existing_session = get_transaction_session()
    if normalized == 'NEVER':
        if existing_session is not None and existing_session.in_transaction:
            raise RuntimeError("事务传播 NEVER 要求当前不存在活动事务")
        yield None
        return

    if normalized == 'MANDATORY' and (
        existing_session is None or not existing_session.in_transaction
    ):
        raise RuntimeError("事务传播 MANDATORY 要求当前已存在活动事务")

    if normalized in {'SUPPORTS', 'NOT_SUPPORTED'}:
        if normalized == 'SUPPORTS' and existing_session is not None:
            yield existing_session
            return
        # Suspend the outer connection while mapper calls create their normal
        # short-lived auto-commit sessions.  This avoids accidentally running
        # NOT_SUPPORTED work on the outer transaction.
        if existing_session is not None and normalized == 'NOT_SUPPORTED':
            with existing_session._suspended_transaction():
                token = _transaction_session.set(None)
                try:
                    yield None
                finally:
                    _transaction_session.reset(token)
            return
        yield None
        return

    if normalized == 'REQUIRED' and existing_session is not None:
        with existing_session.transaction(propagation='REQUIRED'):
            yield existing_session
        return

    if normalized == 'NESTED' and existing_session is not None:
        with existing_session.transaction(propagation='NESTED'):
            yield existing_session
        return

    # REQUIRES_NEW always creates a new physical session.  The outer session
    # remains open and is restored after the inner boundary completes.
    if normalized == 'REQUIRES_NEW':
        with session_factory.open_session() as session:
            token = _transaction_session.set(session)
            try:
                with session.transaction(propagation='REQUIRED'):
                    yield session
            finally:
                _transaction_session.reset(token)
        return

    # REQUIRED with no existing session starts the physical transaction.
    if existing_session is not None:
        raise RuntimeError(f"无法建立事务传播上下文: {normalized}")

    with session_factory.open_session() as session:
        token = _transaction_session.set(session)
        try:
            with session.transaction(propagation='REQUIRED'):
                yield session
        finally:
            _transaction_session.reset(token)


class ManagedMapperProxy:
    """为每次Mapper调用创建并关闭Session，避免跨请求共享会话状态。"""

    def __init__(self, session_factory: SqlSessionFactory, mapper_class: Type):
        self._session_factory = session_factory
        self._mapper_class = mapper_class

    def __getattr__(self, name: str):
        mapper_method = getattr(self._mapper_class, name, None)
        if mapper_method is None or not callable(mapper_method):
            raise AttributeError(f"Mapper {self._mapper_class.__name__} 没有方法: {name}")

        def invoke(*args, **kwargs):
            transaction_session = get_transaction_session()
            if transaction_session is not None:
                mapper = transaction_session.get_mapper(self._mapper_class)
                return getattr(mapper, name)(*args, **kwargs)
            with self._session_factory.open_session() as session:
                mapper = session.get_mapper(self._mapper_class)
                return getattr(mapper, name)(*args, **kwargs)

        return invoke


class Mapper(SpringAnnotation):
    """
    Mapper接口注解
    标识一个类为MyBatis Mapper接口
    
    使用示例：
    @Mapper
    class UserMapper:
        @Select("SELECT * FROM users WHERE id = #{id}")
        def find_by_id(self, id):
            pass
    """
    _annotation_type = "mapper"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class MapperScan(SpringAnnotation):
    """
    Mapper扫描注解
    指定要扫描的Mapper包路径
    
    使用示例：
    @SpringBootApplication
    @MapperScan(base_packages=["example.mappers"])
    class Application:
        pass
    """
    _annotation_type = "mapper_scan"

    def __init__(self, base_packages: Optional[List[str]] = None):
        super().__init__(base_packages=base_packages or [])


class MyBatisConfigurer:
    """
    MyBatis配置器
    负责初始化SqlSessionFactory和注册Mapper Bean
    """
    
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.sql_session_factory: Optional[SqlSessionFactory] = None
        self._mapper_registry: Dict[str, Type] = {}
    
    def init(self, application_context) -> None:
        """
        初始化MyBatis
        """
        # 1. 获取数据库配置
        db_config = self.config_loader.get_config().get('database', {})
        orm_mode = str(db_config.get('orm', 'mybatis')).lower()
        if not db_config.get('enabled', False) or orm_mode not in {'mybatis', 'both'}:
            return
        
        # 2. 构建配置字典，传递给build_session_factory
        datasource_config = {
            'driver': db_config.get('driver', 'sqlite'),
            'host': db_config.get('host', 'localhost'),
            'port': db_config.get('port', 3306),
            'database': db_config.get('database', 'test'),
            'username': db_config.get('username', ''),
            'password': db_config.get('password', ''),
        }
        
        # 设置安全配置
        security_config = dict(db_config.get('security', {}))
        if 'ddl_block_enabled' in security_config and 'block_ddl' not in security_config:
            security_config['block_ddl'] = security_config.pop('ddl_block_enabled')
        
        # 设置缓存配置
        cache_config = db_config.get('cache', {})
        
        # 3. 构建SqlSessionFactory（内部会调用Configuration.load_config）
        pool_config = {
            'min_size': db_config.get('min_size', 5),
            'max_size': db_config.get('max_size', 20),
            'max_idle': db_config.get('max_idle', 3600),
            'wait_timeout': db_config.get('wait_timeout', 30),
            'validation_interval': db_config.get('validation_interval', 300),
            'leak_detection_enabled': db_config.get('leak_detection_enabled', True),
            'leak_timeout': db_config.get('leak_timeout', 300),
            'circuit_breaker': db_config.get('circuit_breaker', {}),
        }

        mybatis_config = {
            'datasource': datasource_config,
            'pool': pool_config,
            'security': security_config,
            'cache': cache_config,
            'transaction': db_config.get('transaction', {}),
            'batch': db_config.get('batch', {}),
        }
        mapper_locations = db_config.get('mapper_locations') or db_config.get('mapper_paths')
        if mapper_locations:
            mybatis_config['mapper_locations'] = mapper_locations

        self.sql_session_factory = build_session_factory(mybatis_config)
        
        # 4. 初始化DDL自动建表（JPA hibernate.ddl-auto风格）
        self._init_ddl_auto(db_config)
        
        # 5. 扫描并注册Mapper
        self._scan_mappers(application_context)
        
        # 6. 注册SqlSessionFactory和SqlSession为Bean
        self._register_beans(application_context.bean_factory)
    
    def _init_ddl_auto(self, db_config: dict) -> None:
        """初始化DDL自动建表"""
        try:
            from springbootai.orm.ddl_auto import init_ddl_auto
            # 获取连接池
            pool = getattr(self.sql_session_factory, 'connection_pool', None)
            if hasattr(self.sql_session_factory, 'configuration'):
                pool = pool or getattr(self.sql_session_factory.configuration, 'pool', None)
            if pool is None and hasattr(self.sql_session_factory, '_pool'):
                pool = self.sql_session_factory._pool
            if pool is not None:
                init_ddl_auto(pool, db_config)
        except Exception as e:
            logger.warning(f"DDL auto initialization skipped: {e}")
    
    def _scan_mappers(self, application_context) -> None:
        """
        扫描Mapper类
        """
        # 获取MapperScan注解配置
        main_class = application_context.main_class
        annotations = getattr(main_class, '__spring_annotations__', [])
        
        base_packages = []
        for annotation in annotations:
            if isinstance(annotation, MapperScan):
                base_packages.extend(annotation.base_packages)
        
        if not base_packages:
            # 默认扫描主类所在包下的mappers目录
            base_packages.append(self._get_default_mapper_package(main_class))
        
        # 扫描每个包
        for package in base_packages:
            self._scan_package(package)
    
    def _get_default_mapper_package(self, main_class) -> str:
        """
        获取默认的Mapper包路径
        """
        module_name = main_class.__module__
        if module_name == '__main__':
            return 'mappers'
        return f"{module_name.split('.')[0]}.mappers"
    
    def _scan_package(self, package_name: str) -> None:
        """
        扫描指定包下的Mapper类
        """
        try:
            # 将包名转换为路径
            package_path = package_name.replace('.', os.sep)
            
            # 查找包路径
            for path in sys.path:
                full_path = os.path.join(path, package_path)
                if os.path.exists(full_path) and os.path.isdir(full_path):
                    # 遍历包下所有文件
                    for filename in os.listdir(full_path):
                        if filename.endswith('.py') and not filename.startswith('_'):
                            module_name = f"{package_name}.{filename[:-3]}"
                            self._import_module(module_name)
                    break
        except Exception as e:
            logger.warning(f"Failed to scan package {package_name}: {e}")
    
    def _import_module(self, module_name: str) -> None:
        """
        导入模块并查找Mapper类
        """
        try:
            module = __import__(module_name, fromlist=['*'])
            for name in dir(module):
                obj = getattr(module, name)
                if inspect.isclass(obj) and hasattr(obj, '__spring_annotations__'):
                    for annotation in obj.__spring_annotations__:
                        if isinstance(annotation, Mapper):
                            self._mapper_registry[name] = obj
                            break
        except Exception as exc:
            logger.warning("Failed to import mapper module %s: %s", module_name, exc)
    
    def _generate_bean_name(self, cls_name: str) -> str:
        """
        生成Bean名称，与Spring的命名规则保持一致
        将驼峰式转换为下划线式，如 UserMapper -> user_mapper
        """
        base_name = cls_name[:-6] if cls_name.endswith('Mapper') else cls_name
        
        # 将驼峰式转换为下划线式
        result = []
        for i, char in enumerate(base_name):
            if i > 0 and char.isupper():
                result.append('_')
            result.append(char.lower())
        
        suffix = '_mapper' if cls_name.endswith('Mapper') else ''
        
        return ''.join(result) + suffix
    
    def _register_beans(self, bean_factory: BeanFactory) -> None:
        """
        注册MyBatis相关Bean到Spring容器
        """
        # 注册SqlSessionFactory
        bean_factory.register_bean_definition(
            'sqlSessionFactory',
            BeanDefinition(
                bean_class=SqlSessionFactory,
                bean_name='sqlSessionFactory',
                scope='singleton',
                # The factory owns the connection pool.  Register its close
                # method with the container so ApplicationContext.destroy()
                # releases SQLite/MySQL connections even when no ASGI
                # shutdown event is involved (tests, reloaders, embedding).
                destroy_method='close',
            )
        )
        bean_factory.register_instance('sqlSessionFactory', self.sql_session_factory)
        
        # 注册SqlSession（每次获取都创建新实例）
        def create_sql_session():
            return self.sql_session_factory.open_session()
        
        bean_factory.register_bean_definition(
            'sqlSession',
            BeanDefinition(
                bean_class=SqlSession,
                bean_name='sqlSession',
                scope='prototype',
                factory_method=create_sql_session,
            )
        )
        
        # 注册所有Mapper（使用与Spring一致的命名规则）
        for mapper_name, mapper_class in self._mapper_registry.items():
            # 生成符合Spring命名规则的bean名称
            bean_name = self._generate_bean_name(mapper_name)
            
            # 创建Mapper代理工厂方法
            def create_mapper_proxy(mapper_cls=mapper_class):
                return ManagedMapperProxy(self.sql_session_factory, mapper_cls)
            
            bean_factory.register_bean_definition(
                bean_name,
                BeanDefinition(
                    bean_class=mapper_class,
                    bean_name=bean_name,
                    scope='prototype',
                    factory_method=create_mapper_proxy,
                )
            )


def init_mybatis(application_context) -> None:
    """
    初始化MyBatis集成
    在Spring应用启动时调用
    """
    configurer = MyBatisConfigurer(application_context.config_loader)
    configurer.init(application_context)
