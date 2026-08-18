"""
PyMyBatis SqlSession模块

SqlSession是PyMyBatis的核心执行引擎，负责执行SQL语句、管理事务和连接
"""

import logging
import contextlib
import os
import re
import importlib
import copy
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Type, Tuple

from ..configuration import Configuration
from ..dialect import Dialect, get_dialect
from ..pool import ConnectionPool, create_connection_pool
from ..xml_parser import XmlParser, MappedStatement, ResultMap
from ..dynamic_sql import DynamicSQLProcessor, SecurityError
from ..cache import SqlCache, ResultMapCache, GLOBAL_PRECOMPILED_CACHE
from ..mapper import MapperProxy, MapperRegistry
from ..transaction import TransactionManager, TransactionIsolationLevel
from ..security import SQLInjectionDetector, SensitiveDataMasker, PasswordEncoder
from ..security.access_control import RoleBasedAccessControl
from ..type_handler import TypeHandlerRegistry
from ..interceptor import InterceptorChain

logger = logging.getLogger(__name__)


def create_pool_from_configuration(configuration: Configuration) -> ConnectionPool:
    """Create one connection pool from a validated ORM configuration."""
    datasource = configuration.get_datasource()
    pool_config = {
        **datasource,
        'min_size': configuration.pool_min_size,
        'max_size': configuration.pool_max_size,
        'max_idle': configuration.pool_max_idle,
        'wait_timeout': configuration.pool_wait_timeout,
        'validation_interval': configuration.pool_validation_interval,
        'leak_detection_enabled': configuration.leak_detection_enabled,
        'leak_timeout': configuration.leak_timeout,
        'circuit_breaker_enabled': configuration.circuit_breaker_enabled,
        'circuit_breaker_failure_threshold': configuration.circuit_breaker_failure_threshold,
        'circuit_breaker_recovery_timeout': configuration.circuit_breaker_recovery_timeout,
        'circuit_breaker_success_threshold': configuration.circuit_breaker_success_threshold,
    }
    return create_connection_pool(configuration.dialect, pool_config)


class SqlSession:
    """
    SqlSession是PyMyBatis的核心执行引擎

    核心功能：
    1. 执行SQL语句（SELECT/INSERT/UPDATE/DELETE）
    2. 获取Mapper代理对象
    3. 管理事务
    4. 管理数据库连接
    5. 缓存管理
    6. 安全防护（SQL注入、DDL阻止、访问控制）
    """

    def __init__(
        self,
        configuration: Configuration,
        connection_pool: Optional[ConnectionPool] = None,
    ):
        """
        初始化SqlSession

        Args:
            configuration: 配置对象
        """
        self.configuration = configuration

        # 获取方言
        self.dialect: Dialect = get_dialect(configuration.dialect)

        # Factory创建的Session共享连接池；直接创建Session时由Session拥有连接池。
        self._owns_connection_pool = connection_pool is None
        self.connection_pool = connection_pool or create_pool_from_configuration(configuration)

        # 初始化XML解析器和映射语句缓存
        self.mapped_statements: Dict[str, MappedStatement] = {}
        self.result_maps: Dict[str, ResultMap] = {}
        self._mapper_locations_loaded = False
        self.type_handler_registry: TypeHandlerRegistry = TypeHandlerRegistry()
        for java_type, handler in configuration.type_handlers.items():
            if isinstance(java_type, type):
                self.type_handler_registry.register(java_type, handler)

        # 动态SQL处理器（传递配置）
        # 根据方言选择参数占位符：SQLite/Oracle使用'?'，MySQL/PostgreSQL使用'%s'
        placeholder = '?' if configuration.dialect.lower() in ['sqlite', 'oracle'] else '%s'
        self.dynamic_sql_processor = DynamicSQLProcessor(placeholder=placeholder)
        self.dynamic_sql_processor.enable_raw_params(configuration.allow_raw_params)

        # 缓存
        self.sql_cache = SqlCache(
            cache_type=configuration.cache_type,
            max_size=configuration.cache_size,
            ttl=configuration.cache_ttl
        )
        self.result_map_cache = ResultMapCache()

        # Mapper注册中心
        self.mapper_registry = MapperRegistry()

        # 事务管理器
        self.transaction_manager = TransactionManager(
            isolation_level=TransactionIsolationLevel(configuration.default_transaction_isolation)
        )

        # 安全组件
        self.sql_injection_detector = SQLInjectionDetector(
            enabled=configuration.sql_injection_detection,
            block_ddl=configuration.block_ddl,
            allow_raw_params=configuration.allow_raw_params
        )
        self.sensitive_data_masker = SensitiveDataMasker(
            enabled=configuration.sensitive_data_masking
        )
        self.password_encoder = PasswordEncoder()

        # 访问控制
        self.access_control = RoleBasedAccessControl(
            enabled=configuration.access_control_enabled
        )

        # 当前连接
        self._current_connection = None
        self._current_pooled_conn = None

        # 当前用户上下文（用于访问控制）
        self._user_context: Dict[str, Any] = {}

        self._transaction_depth = 0
        self._transaction_rollback_only = False
        self._transaction_dirty = False
        self._transaction_flush_cache = False
        self._transaction_isolation: Optional[TransactionIsolationLevel] = None
        self._closed = False
        self._batch_operations: List[Tuple[str, Optional[Dict[str, Any]]]] = []
        self.interceptor_chain = InterceptorChain()
        for interceptor in configuration.interceptors:
            self.interceptor_chain.add_interceptor(interceptor)

    def set_user_context(self, user_context: Dict[str, Any]) -> None:
        """
        设置用户上下文（用于访问控制）

        Args:
            user_context: 用户上下文（包含user_id、role等）
        """
        self._user_context = user_context

    def get_user_context(self) -> Dict[str, Any]:
        """获取当前用户上下文"""
        return self._user_context

    def _load_mapper_locations(self) -> None:
        """加载XML映射文件（支持懒加载）"""
        import glob

        if self._mapper_locations_loaded:
            return
        self._mapper_locations_loaded = True

        for location in self.configuration.mapper_locations:
            # 如果是目录，递归查找所有XML文件
            if os.path.isdir(location):
                xml_files = glob.glob(os.path.join(location, '**', '*.xml'), recursive=True)
            elif location.endswith('.xml'):
                xml_files = [location]
            else:
                # 尝试通配符匹配
                xml_files = glob.glob(location)

            for xml_file in sorted(set(xml_files)):
                parser = XmlParser()
                parser.parse_file(xml_file)

                # 收集映射语句
                for statement in parser.get_all_mapped_statements():
                    key = f"{parser.get_namespace()}.{statement.id}" if parser.get_namespace() else statement.id
                    if not self._statement_matches_database(statement):
                        continue
                    current = self.mapped_statements.get(key)
                    # A database-specific statement wins over the generic
                    # variant; a later generic statement never hides a
                    # matching vendor-specific one.
                    if current is None or (
                        current.database_id is None and statement.database_id is not None
                    ):
                        self.mapped_statements[key] = statement

                # 收集结果映射
                for result_map in parser.get_all_result_maps():
                    key = f"{parser.get_namespace()}.{result_map.id}" if parser.get_namespace() else result_map.id
                    self.result_maps[key] = result_map

    def _resolve_sql(self, sql_or_id: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        解析SQL或statement_id

        Args:
            sql_or_id: SQL语句或statement_id

        Returns:
            (sql, result_map_id, statement_type)
        """
        # 如果包含空格，可能是SQL语句
        if ' ' in sql_or_id or '\n' in sql_or_id:
            return sql_or_id, None, None

        # 尝试从映射语句中查找
        statement = self._get_mapped_statement(sql_or_id)
        if statement is not None:
            # 从sql_or_id中提取namespace
            namespace = sql_or_id.rsplit('.', 1)[0] if '.' in sql_or_id else None
            # 构建完整的result_map key（带namespace）
            result_map_key = f"{namespace}.{statement.result_map}" if namespace and statement.result_map else statement.result_map
            return statement.sql, result_map_key, statement.sql_type

        # 默认当作SQL处理
        return sql_or_id, None, None

    def _get_mapped_statement(self, statement_id: str) -> Optional[MappedStatement]:
        if not self._mapper_locations_loaded:
            self._load_mapper_locations()
        return self.mapped_statements.get(statement_id)

    def _statement_matches_database(self, statement: MappedStatement) -> bool:
        """Check a MyBatis ``databaseId`` against the configured dialect."""
        database_id = statement.database_id
        if not database_id:
            return True
        dialect = self.configuration.dialect.lower()
        aliases = {
            'postgres': 'postgresql',
            'psycopg': 'postgresql',
            'sqlite3': 'sqlite',
        }
        return str(database_id).lower() in {dialect, aliases.get(dialect, dialect)}

    def get_mapped_statement(self, statement_id: str) -> Optional[MappedStatement]:
        """Return XML metadata for an id without exposing the internal registry."""
        return self._get_mapped_statement(statement_id)

    def _process_sql(self, sql: str, params: Dict[str, Any]) -> Tuple[str, List[Any]]:
        processed_sql, param_order = self.dynamic_sql_processor.process(sql, params)
        return processed_sql, [self.type_handler_registry.to_database(value) for value in param_order]

    @staticmethod
    def _copy_cached_result(value: Any) -> Any:
        """Do not let callers mutate a cache entry owned by the Session."""
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    @staticmethod
    def _get_statement_for_id(sql_or_id: str, statement_lookup) -> Optional[MappedStatement]:
        if ' ' in sql_or_id or '\n' in sql_or_id:
            return None
        return statement_lookup(sql_or_id)

    def get_connection(self):
        """
        获取数据库连接

        Returns:
            数据库连接对象
        """
        if self._closed:
            raise RuntimeError("SqlSession 已关闭")

        if self._current_pooled_conn is not None:
            if self._current_pooled_conn.is_valid():
                return self._current_connection
            self.connection_pool.return_connection(self._current_pooled_conn)
            self._current_pooled_conn = None
            self._current_connection = None

        pooled_conn = self.connection_pool.get_connection()
        self._current_connection = pooled_conn.get_connection()
        # 保存PooledConnection引用以便正确归还
        self._current_pooled_conn = pooled_conn
        return self._current_connection

    def return_connection(self) -> None:
        """归还数据库连接到连接池"""
        if self._current_pooled_conn is not None:
            self.connection_pool.return_connection(self._current_pooled_conn)
            self._current_pooled_conn = None
        self._current_connection = None

    @property
    def _in_transaction(self) -> bool:
        return self._transaction_depth > 0

    @property
    def in_transaction(self) -> bool:
        """Public transaction-state query used by Spring integrations."""
        return self._in_transaction

    @contextlib.contextmanager
    def _suspended_transaction(self):
        """Temporarily detach the current physical transaction.

        The pooled connection is deliberately kept out of the pool while the
        suspended branch runs.  Returning it would expose an uncommitted
        transaction to another request.  A second connection is therefore
        required for ``REQUIRES_NEW``/``NOT_SUPPORTED``.
        """
        state = (
            self._current_connection,
            self._current_pooled_conn,
            self._transaction_depth,
            self._transaction_rollback_only,
            self._transaction_dirty,
            self._transaction_flush_cache,
            self._transaction_isolation,
        )
        self._current_connection = None
        self._current_pooled_conn = None
        self._transaction_depth = 0
        self._transaction_rollback_only = False
        self._transaction_dirty = False
        self._transaction_flush_cache = False
        self._transaction_isolation = None
        try:
            yield
        finally:
            # Release only the temporary branch connection; the outer one is
            # restored without touching its transaction state.
            self.return_connection()
            (
                self._current_connection,
                self._current_pooled_conn,
                self._transaction_depth,
                self._transaction_rollback_only,
                self._transaction_dirty,
                self._transaction_flush_cache,
                self._transaction_isolation,
            ) = state

    def _handle_write_success(self, connection: Any, flush_cache: bool = True) -> None:
        if self._in_transaction:
            self._transaction_dirty = True
            self._transaction_flush_cache = self._transaction_flush_cache or flush_cache
            return
        connection.commit()
        if flush_cache:
            self.sql_cache.clear()

    def _handle_write_error(self, connection: Any) -> None:
        if self._in_transaction:
            self._transaction_rollback_only = True
            return
        try:
            connection.rollback()
        except Exception:
            logger.exception("SQL执行失败后回滚连接失败")

    def _validate_sql(self, sql: str) -> None:
        """
        验证SQL语句安全性

        Args:
            sql: SQL语句

        Raises:
            SecurityError: SQL语句不安全
        """
        # 检查DDL（只阻止DROP/TRUNCATE/ALTER等危险DDL，不阻止CREATE TABLE等）
        if self.sql_injection_detector.is_ddl_blocked(sql):
            raise SecurityError(f"DDL语句被阻止: {sql}")

    def _apply_access_control(self, sql: str, params: Dict[str, Any]) -> str:
        """
        应用访问控制条件

        Args:
            sql: SQL语句
            params: 参数

        Returns:
            添加访问控制条件后的SQL语句
        """
        if not self.configuration.access_control_enabled:
            return sql

        # 提取表名（简化实现）
        table_name = self._extract_table_name(sql)

        # 获取行级访问条件
        condition = self.access_control.get_access_condition(table_name, 'SELECT', self._user_context)
        if condition:
            # 检查SQL是否已有WHERE子句
            if 'WHERE' in sql.upper():
                sql = f"{sql} AND {condition}"
            else:
                sql = f"{sql} WHERE {condition}"

        return sql

    def _extract_table_name(self, sql: str) -> str:
        """
        从SQL语句中提取表名（简化实现）

        Args:
            sql: SQL语句

        Returns:
            表名
        """
        import re
        # 匹配FROM后面的表名
        match = re.search(r'FROM\s+(\w+)', sql, re.IGNORECASE)
        if match:
            return match.group(1)
        return ''

    def execute(self, sql_or_id: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """按映射声明或SQL首关键字分派到对应的执行方法。"""
        resolved_sql, _, statement_type = self._resolve_sql(sql_or_id)
        operation = (statement_type or resolved_sql.lstrip().split(None, 1)[0]).lower()
        dispatch = {
            'select': self.select,
            'insert': self.insert,
            'update': self.update,
            'delete': self.delete,
        }
        executor = dispatch.get(operation)
        if executor is None:
            raise ValueError(f"不支持的SQL操作: {operation or '<empty>'}")
        return executor(sql_or_id, params)

    def select(self, sql: str, params: Optional[Dict[str, Any]] = None,
               result_map: Optional[str] = None,
               use_cache: Optional[bool] = None,
               fetch_size: Optional[int] = None,
               timeout: Optional[int] = None,
               _intercepted: bool = False) -> List[Dict[str, Any]]:
        """
        执行SELECT查询

        Args:
            sql: SQL语句或statement_id
            params: 参数字典
            result_map: 结果映射ID

        Returns:
            查询结果列表
        """
        params = params or {}
        if not _intercepted and self.interceptor_chain.interceptors:
            return self.interceptor_chain.invoke(
                self, 'select', (sql, params),
                {
                    'result_map': result_map, 'use_cache': use_cache,
                    'fetch_size': fetch_size, 'timeout': timeout,
                },
                lambda: self.select(
                    sql, params, result_map, use_cache, fetch_size, timeout,
                    _intercepted=True,
                ),
            )

        statement = self._get_statement_for_id(sql, self._get_mapped_statement)

        # 解析SQL或statement_id
        processed_sql, stmt_result_map, _ = self._resolve_sql(sql)
        result_map = result_map or stmt_result_map
        if statement is not None:
            fetch_size = fetch_size if fetch_size is not None else statement.fetch_size
            timeout = timeout if timeout is not None else statement.timeout
            if use_cache is None:
                use_cache = statement.use_cache
            if statement.flush_cache:
                self.sql_cache.clear()
        cache_enabled = self.configuration.cache_enabled if use_cache is None else use_cache
        cache_params = dict(params)
        if result_map:
            cache_params['__pymybatis_result_map__'] = result_map

        # 检查SQL注入
        if self.configuration.sql_injection_detection:
            for value in params.values():
                if not self.sql_injection_detector.is_safe(value):
                    raise SecurityError(f"SQL注入检测失败: {value}")

        # 处理动态SQL
        processed_sql, param_order = self._process_sql(processed_sql, params)

        # 验证SQL安全性
        self._validate_sql(processed_sql)

        # 应用访问控制
        processed_sql = self._apply_access_control(processed_sql, params)

        # 检查缓存
        if cache_enabled:
            cached_result = self.sql_cache.get(processed_sql, cache_params)
            if cached_result is not None:
                logger.debug(f"缓存命中: {processed_sql}")
                return self._copy_cached_result(cached_result)

        # 获取连接
        connection = self.get_connection()

        # 使用预编译缓存
        cursor = None
        try:
            cursor = connection.cursor()
            self._configure_cursor(cursor, fetch_size=fetch_size, timeout=timeout)

            # 尝试从预编译缓存获取
            cached_stmt = None
            if self.configuration.sql_precompile_cache:
                cached_stmt = GLOBAL_PRECOMPILED_CACHE.get(processed_sql)

            if cached_stmt:
                cursor.execute(cached_stmt, tuple(param_order))
            else:
                cursor.execute(processed_sql, tuple(param_order))
                # 缓存预编译语句
                if self.configuration.sql_precompile_cache:
                    GLOBAL_PRECOMPILED_CACHE.put(processed_sql, processed_sql)

            # 获取结果
            results = cursor.fetchall()

            # 将结果转换为字典
            if results:
                if hasattr(cursor, 'description') and cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    results = [
                        dict(row) if isinstance(row, Mapping) or hasattr(row, 'keys')
                        else dict(zip(columns, row))
                        for row in results
                    ]

            # 应用结果映射
            result_map_obj = self.result_maps.get(result_map) if result_map else None
            if result_map_obj is not None:
                results = self._apply_result_map(results, result_map_obj)
                if result_map_obj.type:
                    results = self._apply_statement_result_type(
                        results, result_map_obj.type
                    )

            # 脱敏处理
            if self.configuration.sensitive_data_masking:
                results = self.sensitive_data_masker.mask_list(results)

            if statement is not None and statement.result_type:
                results = self._apply_statement_result_type(
                    results, statement.result_type
                )

            # 缓存结果
            if cache_enabled:
                self.sql_cache.put(
                    processed_sql, cache_params, self._copy_cached_result(results)
                )

            return results

        finally:
            if cursor:
                cursor.close()

    def select_one(self, sql: str, params: Optional[Dict[str, Any]] = None,
                   result_map: Optional[str] = None,
                   use_cache: Optional[bool] = None,
                   fetch_size: Optional[int] = None,
                   timeout: Optional[int] = None) -> Optional[Any]:
        """
        执行SELECT查询，返回单条记录

        Args:
            sql: SQL语句或statement_id
            params: 参数字典
            result_map: 结果映射ID

        Returns:
            查询结果，未找到返回None。如果只有一个字段，返回标量值。
        """
        results = self.select(
            sql, params, result_map, use_cache, fetch_size, timeout
        )
        if not results:
            return None
        
        result = results[0]
        # 如果结果只有一个字段，返回标量值（如COUNT查询）
        if isinstance(result, dict) and len(result) == 1:
            return list(result.values())[0]
        return result

    def select_pagination(self, sql: str, params: Optional[Dict[str, Any]] = None,
                          page_num: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """
        执行分页查询

        Args:
            sql: SQL语句或statement_id
            params: 参数字典
            page_num: 页码（从1开始）
            page_size: 每页条数

        Returns:
            分页结果，包含total和data
        """
        if page_num < 1:
            raise ValueError("page_num 必须大于等于 1")
        if page_size < 1 or page_size > self.configuration.max_batch_size:
            raise ValueError(
                f"page_size 必须在 1 到 {self.configuration.max_batch_size} 之间"
            )

        # 计算偏移量
        offset = (page_num - 1) * page_size

        # 检查偏移量限制
        if offset > self.configuration.max_pagination_offset:
            raise SecurityError(
                f"分页偏移量({offset})超过最大限制({self.configuration.max_pagination_offset})，"
                "请使用游标分页"
            )

        # 解析SQL
        resolved_sql, _, _ = self._resolve_sql(sql)

        # 构建分页SQL
        pagination_sql = self.dialect.get_pagination_sql(resolved_sql, offset, page_size)

        # 执行分页查询
        data = self.select(pagination_sql, params)

        # 计算总数（如果需要）
        count_sql = f"SELECT COUNT(*) as total FROM ({resolved_sql}) t"  # nosec B608 - wraps already-resolved mapper SQL
        count_result = self.select_one(count_sql, params)
        if isinstance(count_result, dict):
            total = count_result.get('total', 0)
        else:
            total = count_result or 0

        return {
            'total': total,
            'page_num': page_num,
            'page_size': page_size,
            'data': data
        }

    def select_cursor(self, sql: str, params: Optional[Dict[str, Any]] = None,
                      cursor_key: str = 'id', cursor_value: Optional[int] = None,
                      page_size: int = 100) -> Dict[str, Any]:
        """
        执行游标分页查询（避免大偏移量分页）

        Args:
            sql: SQL语句或statement_id
            params: 参数字典
            cursor_key: 游标字段（通常为主键）
            cursor_value: 游标值（上一页最后一条记录的cursor_key值）
            page_size: 每页条数

        Returns:
            分页结果，包含data和next_cursor
        """
        params = params or {}
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?', cursor_key):
            raise ValueError("cursor_key 不是合法的字段标识符")
        if page_size < 1 or page_size > self.configuration.max_batch_size:
            raise ValueError(
                f"page_size 必须在 1 到 {self.configuration.max_batch_size} 之间"
            )

        # 解析SQL
        resolved_sql, _, _ = self._resolve_sql(sql)

        # 提取ORDER BY和LIMIT子句（如果存在）
        order_by_clause = ''
        remaining_sql = resolved_sql.rstrip().rstrip(';')

        # 调用方传入的LIMIT会被统一替换，防止重复LIMIT或绕过页大小限制。
        remaining_sql = re.sub(
            r'\s+LIMIT\s+\d+(?:\s+OFFSET\s+\d+)?\s*$',
            '',
            remaining_sql,
            flags=re.IGNORECASE,
        )
        
        # 处理ORDER BY
        order_by_match = re.search(r'\s+ORDER\s+BY\s+.+$', remaining_sql, re.IGNORECASE)
        if order_by_match:
            order_by_clause = order_by_match.group(0)
            remaining_sql = remaining_sql[:order_by_match.start()]

        # 构建游标分页SQL
        if cursor_value is not None:
            # 检查SQL是否已有WHERE子句
            if 'WHERE' in remaining_sql.upper():
                cursor_sql = f"{remaining_sql} AND {cursor_key} > #{{_cursor_value}}"
            else:
                cursor_sql = f"{remaining_sql} WHERE {cursor_key} > #{{_cursor_value}}"

            # 添加排序和限制
            if not order_by_clause:
                order_by_clause = f" ORDER BY {cursor_key}"
            cursor_sql = f"{cursor_sql}{order_by_clause} LIMIT {page_size}"

            # 添加游标参数
            params = {**params, '_cursor_value': cursor_value}
        else:
            # 第一页
            if not order_by_clause:
                order_by_clause = f" ORDER BY {cursor_key}"
            cursor_sql = f"{remaining_sql}{order_by_clause} LIMIT {page_size}"

        # 执行查询
        data = self.select(cursor_sql, params)

        # 计算下一页游标
        next_cursor = None
        if len(data) == page_size:
            next_cursor = data[-1].get(cursor_key.split('.')[-1])

        return {
            'data': data,
            'next_cursor': next_cursor,
            'page_size': page_size
        }

    def cursor_page(self, sql: str, cursor_key: str = 'id',
                    cursor_value: Optional[int] = None, page_size: int = 100) -> Dict[str, Any]:
        """
        执行游标分页查询（简化接口）

        Args:
            sql: SQL语句
            cursor_key: 游标字段（通常为主键）
            cursor_value: 游标值（上一页最后一条记录的cursor_key值）
            page_size: 每页条数

        Returns:
            分页结果，包含data和next_cursor
        """
        return self.select_cursor(sql, {}, cursor_key, cursor_value, page_size)

    def insert(self, sql: str, params: Optional[Dict[str, Any]] = None,
               use_generated_keys: bool = False,
               timeout: Optional[int] = None,
               _intercepted: bool = False) -> int:
        """
        执行INSERT操作

        Args:
            sql: SQL语句或statement_id
            params: 参数字典

        Returns:
            影响的行数或自增主键
        """
        params = params or {}
        if not _intercepted and self.interceptor_chain.interceptors:
            return self.interceptor_chain.invoke(
                self, 'insert', (sql, params),
                {'use_generated_keys': use_generated_keys, 'timeout': timeout},
                lambda: self.insert(
                    sql, params, use_generated_keys, timeout, _intercepted=True
                ),
            )

        statement = self._get_statement_for_id(sql, self._get_mapped_statement)

        # 解析SQL或statement_id
        processed_sql, _, _ = self._resolve_sql(sql)
        flush_cache = statement.flush_cache if statement is not None else True
        if statement is not None:
            timeout = timeout if timeout is not None else statement.timeout
            use_generated_keys = use_generated_keys or statement.use_generated_keys

            if statement.select_key_sql and statement.select_key_order == 'BEFORE':
                key_value = self._execute_select_key(statement, params)
                self._assign_key_to_params(
                    params,
                    statement.select_key_key_property or statement.key_property,
                    key_value,
                )

        # 检查SQL注入
        if self.configuration.sql_injection_detection:
            for value in params.values():
                if not self.sql_injection_detector.is_safe(value):
                    raise SecurityError(f"SQL注入检测失败: {value}")

        # 处理动态SQL
        processed_sql, param_order = self._process_sql(processed_sql, params)

        # 验证SQL安全性
        self._validate_sql(processed_sql)

        # 获取连接
        connection = self.get_connection()
        cursor = None

        try:
            # 执行SQL
            cursor = connection.cursor()
            self._configure_cursor(cursor, timeout=timeout)
            cursor.execute(processed_sql, tuple(param_order))
            affected_rows = cursor.rowcount
            result_value = affected_rows

            # 获取自增主键
            if use_generated_keys and getattr(cursor, 'lastrowid', None) is not None:
                result_value = cursor.lastrowid
            elif use_generated_keys and self.dialect.get_dialect_name() == 'mysql':
                cursor.execute("SELECT LAST_INSERT_ID()")
                result = cursor.fetchone()
                if result:
                    result_value = list(result.values())[0] if isinstance(result, dict) else result[0]

            if use_generated_keys and statement and statement.key_property:
                self._assign_key_to_params(params, statement.key_property, result_value)

            self._handle_write_success(connection, flush_cache=flush_cache)

            if statement is not None and statement.select_key_sql \
                    and statement.select_key_order == 'AFTER':
                key_value = self._execute_select_key(statement, params)
                self._assign_key_to_params(
                    params,
                    statement.select_key_key_property or statement.key_property,
                    key_value,
                )
            return result_value

        except Exception:
            self._handle_write_error(connection)
            raise

        finally:
            if cursor:
                cursor.close()

    def _execute_select_key(
        self, statement: MappedStatement, params: Dict[str, Any]
    ) -> Any:
        """Execute an XML ``selectKey`` and return its key value."""
        rows = self.select(
            statement.select_key_sql or '',
            params,
            use_cache=False,
            timeout=statement.timeout,
        )
        if not rows:
            return None
        value = rows[0]
        if isinstance(value, Mapping):
            key_column = statement.select_key_key_column or statement.key_column
            if key_column and key_column in value:
                value = value[key_column]
            elif len(value) == 1:
                value = next(iter(value.values()))
        result_type = statement.select_key_result_type
        if result_type:
            converted = self._apply_statement_result_type([value], result_type)
            value = converted[0]
        return value

    def update(self, sql: str, params: Optional[Dict[str, Any]] = None,
               timeout: Optional[int] = None,
               _intercepted: bool = False) -> int:
        """
        执行UPDATE操作

        Args:
            sql: SQL语句或statement_id
            params: 参数字典

        Returns:
            影响的行数
        """
        params = params or {}
        if not _intercepted and self.interceptor_chain.interceptors:
            return self.interceptor_chain.invoke(
                self, 'update', (sql, params), {'timeout': timeout},
                lambda: self.update(sql, params, timeout, _intercepted=True),
            )

        statement = self._get_statement_for_id(sql, self._get_mapped_statement)

        # 解析SQL或statement_id
        processed_sql, _, _ = self._resolve_sql(sql)
        flush_cache = statement.flush_cache if statement is not None else True
        if statement is not None:
            timeout = timeout if timeout is not None else statement.timeout

        # 检查SQL注入
        if self.configuration.sql_injection_detection:
            for value in params.values():
                if not self.sql_injection_detector.is_safe(value):
                    raise SecurityError(f"SQL注入检测失败: {value}")

        # 处理动态SQL
        processed_sql, param_order = self._process_sql(processed_sql, params)

        # 验证SQL安全性
        self._validate_sql(processed_sql)

        # 获取连接
        connection = self.get_connection()
        cursor = None

        try:
            cursor = connection.cursor()
            self._configure_cursor(cursor, timeout=timeout)
            cursor.execute(processed_sql, tuple(param_order))

            self._handle_write_success(connection, flush_cache=flush_cache)

            return cursor.rowcount

        except Exception:
            self._handle_write_error(connection)
            raise

        finally:
            if cursor:
                cursor.close()

    def delete(self, sql: str, params: Optional[Dict[str, Any]] = None,
               timeout: Optional[int] = None,
               _intercepted: bool = False) -> int:
        """
        执行DELETE操作

        Args:
            sql: SQL语句或statement_id
            params: 参数字典

        Returns:
            影响的行数
        """
        params = params or {}
        if not _intercepted and self.interceptor_chain.interceptors:
            return self.interceptor_chain.invoke(
                self, 'delete', (sql, params), {'timeout': timeout},
                lambda: self.delete(sql, params, timeout, _intercepted=True),
            )

        statement = self._get_statement_for_id(sql, self._get_mapped_statement)

        # 解析SQL或statement_id
        processed_sql, _, _ = self._resolve_sql(sql)
        flush_cache = statement.flush_cache if statement is not None else True
        if statement is not None:
            timeout = timeout if timeout is not None else statement.timeout

        # 检查SQL注入
        if self.configuration.sql_injection_detection:
            for value in params.values():
                if not self.sql_injection_detector.is_safe(value):
                    raise SecurityError(f"SQL注入检测失败: {value}")

        # 处理动态SQL
        processed_sql, param_order = self._process_sql(processed_sql, params)

        # 验证SQL安全性
        self._validate_sql(processed_sql)

        # 获取连接
        connection = self.get_connection()
        cursor = None

        try:
            cursor = connection.cursor()
            self._configure_cursor(cursor, timeout=timeout)
            cursor.execute(processed_sql, tuple(param_order))

            self._handle_write_success(connection, flush_cache=flush_cache)

            return cursor.rowcount

        except Exception:
            self._handle_write_error(connection)
            raise

        finally:
            if cursor:
                cursor.close()

    @staticmethod
    def _configure_cursor(cursor: Any, fetch_size: Optional[int] = None,
                          timeout: Optional[int] = None) -> None:
        if fetch_size is not None:
            if fetch_size <= 0:
                raise ValueError("fetch_size 必须大于0")
            cursor.arraysize = fetch_size
        if timeout is not None:
            if timeout <= 0:
                raise ValueError("timeout 必须大于0")
            if hasattr(cursor, 'timeout'):
                cursor.timeout = timeout

    def _apply_result_map(self, results: List[Dict[str, Any]], result_map: ResultMap) -> List[Dict[str, Any]]:
        """
        应用结果映射，将数据库列名转换为对象属性名

        Args:
            results: 查询结果列表
            result_map: 结果映射

        Returns:
            映射后的结果列表
        """
        if not results:
            return results
        
        mapped_results = []
        for row in results:
            mapped_results.append(self._map_result_row(row, result_map))
        return mapped_results

    def _map_result_row(self, row: Mapping, result_map: ResultMap) -> Dict[str, Any]:
        """Map one joined row, including nested MyBatis result mappings."""
        selected_map = result_map
        if result_map.discriminator is not None:
            discriminator_value = row.get(result_map.discriminator.column)
            case_id = result_map.discriminator.cases.get(str(discriminator_value))
            if case_id:
                selected_map = self._lookup_result_map(case_id) or result_map

        mapped_row: Dict[str, Any] = {}
        for column, value in row.items():
            property_name = selected_map.get_property(column)
            mapped_row[property_name or column] = value

        for nested in selected_map.associations:
            value = self._load_nested_result(row, nested, collection=False)
            if value is not None:
                mapped_row[nested.property] = value
        for nested in selected_map.collections:
            value = self._load_nested_result(row, nested, collection=True)
            mapped_row[nested.property] = value
        return mapped_row

    def _lookup_result_map(self, result_map_id: Optional[str]) -> Optional[ResultMap]:
        if not result_map_id:
            return None
        direct = self.result_maps.get(result_map_id)
        if direct is not None:
            return direct
        namespace = result_map_id.rsplit('.', 1)[0] if '.' in result_map_id else None
        if namespace:
            return self.result_maps.get(result_map_id)
        # Inline nested maps are registered under their generic id and under
        # the mapper namespace during XML loading.
        matches = [value for key, value in self.result_maps.items()
                   if key.endswith('.' + result_map_id)]
        return matches[0] if matches else None

    @staticmethod
    def _nested_parameters(row: Mapping, column: Optional[str]) -> Dict[str, Any]:
        if not column:
            return dict(row)
        # MyBatis supports composite columns: {id=author_id,type=kind}.
        if column.startswith('{') and column.endswith('}'):
            parameters: Dict[str, Any] = {}
            for item in column[1:-1].split(','):
                name, _, source = item.partition('=')
                if name and source:
                    parameters[name.strip()] = row.get(source.strip())
            return parameters
        value = row.get(column)
        return {column: value, '_parameter': value}

    def _load_nested_result(
        self, row: Mapping, nested: Any, collection: bool
    ) -> Any:
        params = self._nested_parameters(row, nested.column)
        if nested.select:
            nested_statement = nested.select
            if '.' not in nested_statement:
                # Resolve a relative statement id when XML used a namespace.
                candidates = [key for key in self.mapped_statements
                              if key.endswith('.' + nested_statement)]
                nested_statement = candidates[0] if candidates else nested_statement
            if collection:
                return self.select(nested_statement, params)
            return self.select_one(nested_statement, params)

        child_map = self._lookup_result_map(nested.result_map)
        if child_map is None:
            return None
        # Joined nested objects with no non-null mapped column represent SQL
        # NULL on the outer join and should remain None.
        mapped_columns = child_map.mappings.keys()
        if not any(row.get(column) is not None for column in mapped_columns):
            return [] if collection else None
        child = self._map_result_row(row, child_map)
        target_type = nested.result_type or nested.java_type or nested.of_type or child_map.type
        if target_type:
            child = self._apply_statement_result_type([child], target_type)[0]
        return [child] if collection else child

    @staticmethod
    def _resolve_statement_result_type(result_type: str) -> Optional[Type]:
        builtins = {
            'int': int,
            'float': float,
            'str': str,
            'bool': bool,
            'dict': dict,
            'builtins.int': int,
            'builtins.float': float,
            'builtins.str': str,
            'builtins.bool': bool,
            'builtins.dict': dict,
        }
        if result_type in builtins:
            return builtins[result_type]
        if '.' not in result_type:
            return None
        module_name, type_name = result_type.rsplit('.', 1)
        return getattr(importlib.import_module(module_name), type_name)

    def _apply_statement_result_type(self, results: List[Any], result_type: str) -> List[Any]:
        """Apply XML ``resultType`` when it can be resolved unambiguously.

        Simple aliases match MyBatis' scalar behavior. Custom classes must be
        fully qualified; an unqualified name is intentionally left as a dict so
        mapper XML does not depend on process-wide import heuristics.
        """
        target_type = self._resolve_statement_result_type(result_type)
        if target_type is None:
            return results

        def convert(value: Any) -> Any:
            if isinstance(value, target_type):
                return value
            if isinstance(value, Mapping):
                if target_type is dict:
                    return dict(value)
                if len(value) == 1 and target_type in {int, float, str, bool}:
                    return target_type(next(iter(value.values())))
                return target_type(**value)
            return target_type(value)

        return [convert(value) for value in results]

    @staticmethod
    def _assign_key_to_params(params: Dict[str, Any], property_name: str, value: Any) -> None:
        """Update a parameter mapping for XML ``keyProperty`` when possible."""
        if not property_name:
            return
        if '.' not in property_name:
            params[property_name] = value
            return

        root, path = property_name.split('.', 1)
        target = params.get(root)
        if target is None:
            return
        parts = path.split('.')
        for part in parts[:-1]:
            if isinstance(target, Mapping):
                target = target.get(part)
            else:
                target = getattr(target, part, None)
            if target is None:
                return
        if isinstance(target, dict):
            target[parts[-1]] = value
        elif target is not None:
            setattr(target, parts[-1], value)

    @contextlib.contextmanager
    def transaction(
        self,
        isolation_level: Optional[Any] = None,
        propagation: str = 'REQUIRED',
    ):
        """
        事务上下文管理器

        Usage:
            with session.transaction():
                session.insert(...)
                session.update(...)
        """
        normalized_propagation = str(propagation or 'REQUIRED').upper()
        supported = {
            'REQUIRED', 'REQUIRES_NEW', 'NESTED', 'SUPPORTS',
            'MANDATORY', 'NOT_SUPPORTED', 'NEVER',
        }
        if normalized_propagation not in supported:
            raise ValueError(
                f"不支持的事务传播级别: {propagation}; 可选: {', '.join(sorted(supported))}"
            )

        # Non-transactional propagation modes do not alter transaction state.
        if normalized_propagation == 'NEVER':
            if self._in_transaction:
                raise RuntimeError("事务传播 NEVER 要求当前不存在活动事务")
            yield
            return
        if normalized_propagation == 'MANDATORY' and not self._in_transaction:
            raise RuntimeError("事务传播 MANDATORY 要求当前已存在活动事务")
        if normalized_propagation == 'SUPPORTS' and not self._in_transaction:
            yield
            return
        if normalized_propagation == 'SUPPORTS':
            # Join the ambient transaction without creating a new logical
            # boundary.  An exception is intentionally propagated to the
            # caller, which owns the rollback decision.
            yield
            return
        if normalized_propagation == 'NOT_SUPPORTED' and self._in_transaction:
            with self._suspended_transaction():
                yield
            return
        if normalized_propagation == 'NOT_SUPPORTED':
            yield
            return
        if normalized_propagation == 'REQUIRES_NEW' and self._in_transaction:
            with self._suspended_transaction():
                with self.transaction(
                    isolation_level=isolation_level,
                    propagation='REQUIRED',
                ):
                    yield
            return

        connection = self.get_connection()
        is_outermost = self._transaction_depth == 0

        # ``NESTED`` uses a savepoint inside an existing physical transaction.
        # Unlike REQUIRED's rollback-only behavior, a handled nested failure can
        # leave the outer transaction usable.
        if normalized_propagation == 'NESTED' and not is_outermost:
            savepoint = f"pymybatis_nested_{self._transaction_depth}"
            cursor = connection.cursor()
            try:
                cursor.execute(f"SAVEPOINT {savepoint}")
            finally:
                cursor.close()
            self._transaction_depth += 1
            try:
                yield
            except Exception:
                cursor = connection.cursor()
                try:
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    cursor.close()
                raise
            else:
                cursor = connection.cursor()
                try:
                    cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    cursor.close()
            finally:
                self._transaction_depth -= 1
            return

        requested_isolation = (
            self._transaction_isolation
            if not is_outermost and isolation_level is None
            else self._resolve_transaction_isolation(isolation_level)
        )

        if is_outermost:
            self._set_transaction_isolation(connection, requested_isolation)
            if hasattr(connection, 'begin'):
                connection.begin()
            else:
                connection.execute('BEGIN')
            self._transaction_rollback_only = False
            self._transaction_dirty = False
            self._transaction_flush_cache = False
            self._transaction_isolation = requested_isolation
        elif requested_isolation != self._transaction_isolation:
            raise RuntimeError("嵌套事务不能更改隔离级别")

        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_rollback_only = True
            if is_outermost:
                connection.rollback()
            raise
        else:
            if is_outermost:
                if self._transaction_rollback_only:
                    connection.rollback()
                    raise RuntimeError("事务已标记为仅回滚，不能提交")
                connection.commit()
                if self._transaction_dirty and self._transaction_flush_cache:
                    self.sql_cache.clear()
        finally:
            self._transaction_depth -= 1
            if is_outermost:
                self._transaction_rollback_only = False
                self._transaction_dirty = False
                self._transaction_flush_cache = False
                self._transaction_isolation = None

    def _resolve_transaction_isolation(
        self, isolation_level: Optional[Any]
    ) -> TransactionIsolationLevel:
        if isolation_level is None:
            return self.transaction_manager.default_isolation_level
        if isinstance(isolation_level, TransactionIsolationLevel):
            return isolation_level
        try:
            return TransactionIsolationLevel(str(isolation_level).upper())
        except ValueError as exc:
            supported = ', '.join(level.value for level in TransactionIsolationLevel)
            raise ValueError(f"不支持的事务隔离级别: {isolation_level}; 可选: {supported}") from exc

    def _set_transaction_isolation(
        self, connection: Any, isolation_level: TransactionIsolationLevel
    ) -> None:
        if connection.__class__.__module__.startswith('sqlite3'):
            return

        normalized = isolation_level.value.replace('_', ' ')
        set_session = getattr(connection, 'set_session', None)
        if callable(set_session):
            set_session(isolation_level=normalized)
            return

        cursor = connection.cursor()
        try:
            cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {normalized}")
        finally:
            cursor.close()

    def get_mapper(self, mapper_class: Type) -> Any:
        """
        获取Mapper代理对象

        Args:
            mapper_class: Mapper类

        Returns:
            Mapper代理对象
        """
        return MapperProxy(mapper_class, self)

    def close(self) -> None:
        """关闭SqlSession"""
        if self._closed:
            return
        if self._in_transaction and self._current_connection is not None:
            self._current_connection.rollback()
            self._transaction_depth = 0
        self.return_connection()
        if self._owns_connection_pool:
            self.connection_pool.close()
        self._closed = True

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False
