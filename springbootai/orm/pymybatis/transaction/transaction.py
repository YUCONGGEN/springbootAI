"""
PyMyBatis事务管理模块

实现事务隔离级别控制和事务边界管理
"""

from enum import Enum
from typing import Optional, Any, Dict
from contextlib import contextmanager
import re
import threading


class TransactionIsolationLevel(Enum):
    """
    事务隔离级别

    定义数据库事务的隔离程度：
    - READ_UNCOMMITTED: 读未提交，允许读取未提交的数据
    - READ_COMMITTED: 读已提交，只允许读取已提交的数据
    - REPEATABLE_READ: 可重复读，保证同一事务内多次读取相同数据的一致性
    - SERIALIZABLE: 串行化，最高隔离级别，完全串行化执行
    """
    READ_UNCOMMITTED = 'READ_UNCOMMITTED'
    READ_COMMITTED = 'READ_COMMITTED'
    REPEATABLE_READ = 'REPEATABLE_READ'
    SERIALIZABLE = 'SERIALIZABLE'


class TransactionStatus(Enum):
    """
    事务状态

    - ACTIVE: 事务活跃中
    - COMMITTED: 事务已提交
    - ROLLED_BACK: 事务已回滚
    - FAILED: 事务失败
    """
    ACTIVE = 'ACTIVE'
    COMMITTED = 'COMMITTED'
    ROLLED_BACK = 'ROLLED_BACK'
    FAILED = 'FAILED'


class Transaction:
    """
    事务管理类

    核心功能：
    1. 管理事务边界（begin/commit/rollback）
    2. 控制事务隔离级别
    3. 管理事务嵌套
    4. 支持保存点
    """

    def __init__(self, connection: Any, isolation_level: Optional[TransactionIsolationLevel] = None):
        """
        初始化事务

        Args:
            connection: 数据库连接对象
            isolation_level: 事务隔离级别
        """
        self.connection = connection
        self.isolation_level = isolation_level or TransactionIsolationLevel.READ_COMMITTED
        self.status = TransactionStatus.ACTIVE
        self.nested_count = 0
        self.savepoints: Dict[str, Any] = {}

        # 设置隔离级别
        self._set_isolation_level()

    def _set_isolation_level(self) -> None:
        """设置事务隔离级别"""
        # sqlite3 的 isolation_level 表示 BEGIN 模式而非 ANSI 隔离级别。
        if self.connection.__class__.__module__.startswith('sqlite3'):
            return

        set_session = getattr(self.connection, 'set_session', None)
        if callable(set_session):
            set_session(isolation_level=self.isolation_level.value.replace('_', ' '))

    def begin(self) -> None:
        """开始事务"""
        if self.nested_count == 0:
            if hasattr(self.connection, 'begin'):
                self.connection.begin()
            else:
                self.connection.execute('BEGIN')
        self.nested_count += 1
        self.status = TransactionStatus.ACTIVE

    def commit(self) -> None:
        """提交事务"""
        if self.nested_count <= 0 or not self.is_active():
            raise RuntimeError("没有可提交的活动事务")
        if self.nested_count > 1:
            self.nested_count -= 1
            return
        try:
            self.connection.commit()
        except Exception:
            # The server-side outcome may be unknown.  Preserve nesting so a
            # caller can still roll back/clean up, but do not present the
            # transaction as active or retry-safe.
            self.status = TransactionStatus.FAILED
            raise
        self.nested_count = 0
        self.status = TransactionStatus.COMMITTED

    def rollback(self, savepoint: Optional[str] = None) -> None:
        """
        回滚事务

        Args:
            savepoint: 保存点名称，如果指定则回滚到该保存点
        """
        if savepoint is not None and savepoint in self.savepoints:
            self._execute_savepoint_sql(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
        else:
            self.connection.rollback()
            self.nested_count = 0
            self.status = TransactionStatus.ROLLED_BACK

    def create_savepoint(self, name: str) -> None:
        """
        创建保存点

        Args:
            name: 保存点名称
        """
        self._validate_savepoint_name(name)
        self._execute_savepoint_sql(f'SAVEPOINT "{name}"')
        self.savepoints[name] = name

    def release_savepoint(self, name: str) -> None:
        """
        释放保存点

        Args:
            name: 保存点名称
        """
        if name in self.savepoints:
            self._execute_savepoint_sql(f'RELEASE SAVEPOINT "{name}"')
            del self.savepoints[name]

    @staticmethod
    def _validate_savepoint_name(name: str) -> None:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError("保存点名称只能包含字母、数字和下划线，且不能以数字开头")

    def _execute_savepoint_sql(self, sql: str) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
        finally:
            cursor.close()

    def is_active(self) -> bool:
        """检查事务是否活跃"""
        return self.status == TransactionStatus.ACTIVE

    def is_committed(self) -> bool:
        """检查事务是否已提交"""
        return self.status == TransactionStatus.COMMITTED

    def is_rolled_back(self) -> bool:
        """检查事务是否已回滚"""
        return self.status == TransactionStatus.ROLLED_BACK

    def __enter__(self):
        """上下文管理器进入，自动开始事务"""
        self.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出，根据异常决定提交或回滚"""
        if exc_type is not None:
            self.rollback()
            return False
        try:
            self.commit()
        except Exception:
            try:
                self.rollback()
            except Exception:
                # Preserve the commit exception; it best describes the
                # uncertain transaction outcome.
                pass
            raise
        return False


class TransactionManager:
    """
    事务管理器

    负责管理事务的创建、提交和回滚，支持：
    - 编程式事务
    - 声明式事务
    - 嵌套事务
    """

    def __init__(self, isolation_level: Optional[TransactionIsolationLevel] = None):
        """
        初始化事务管理器

        Args:
            isolation_level: 默认事务隔离级别
        """
        self.default_isolation_level = isolation_level or TransactionIsolationLevel.READ_COMMITTED
        self._local = threading.local()

    @property
    def current_transaction(self) -> Optional[Transaction]:
        return getattr(self._local, 'current_transaction', None)

    @current_transaction.setter
    def current_transaction(self, value: Optional[Transaction]) -> None:
        self._local.current_transaction = value

    @contextmanager
    def transaction(self, isolation_level: Optional[TransactionIsolationLevel] = None):
        """
        创建事务上下文管理器

        Args:
            isolation_level: 事务隔离级别，不指定则使用默认级别

        Yields:
            事务对象
        """
        if self.current_transaction is not None:
            # 嵌套事务
            self.current_transaction.begin()
            try:
                yield self.current_transaction
            except BaseException:
                self.current_transaction.rollback()
                self.current_transaction = None
                raise
            else:
                try:
                    self.current_transaction.commit()
                except Exception:
                    try:
                        self.current_transaction.rollback()
                    except Exception:
                        pass
                    self.current_transaction = None
                    raise
        else:
            # 新事务
            raise ValueError("事务必须在SqlSession上下文中使用")

    def begin(self, connection: Any, isolation_level: Optional[TransactionIsolationLevel] = None) -> Transaction:
        """
        开始新事务

        Args:
            connection: 数据库连接对象
            isolation_level: 事务隔离级别

        Returns:
            事务对象
        """
        level = isolation_level or self.default_isolation_level
        if self.current_transaction is not None and self.current_transaction.is_active():
            self.current_transaction.begin()
            return self.current_transaction
        transaction = Transaction(connection, level)
        transaction.begin()
        self.current_transaction = transaction
        return transaction

    def commit(self) -> None:
        """提交当前事务"""
        if self.current_transaction is not None:
            try:
                self.current_transaction.commit()
            except Exception:
                try:
                    self.current_transaction.rollback()
                except Exception:
                    pass
                self.current_transaction = None
                raise
            if self.current_transaction.nested_count == 0:
                self.current_transaction = None

    def rollback(self) -> None:
        """回滚当前事务"""
        if self.current_transaction is not None:
            self.current_transaction.rollback()
            self.current_transaction = None

    def get_current_transaction(self) -> Optional[Transaction]:
        """获取当前事务"""
        return self.current_transaction

    def is_in_transaction(self) -> bool:
        """检查是否在事务中"""
        return self.current_transaction is not None and self.current_transaction.is_active()


def get_isolation_level_code(isolation_level: TransactionIsolationLevel) -> int:
    """
    获取隔离级别对应的数值代码

    Args:
        isolation_level: 事务隔离级别

    Returns:
        隔离级别代码
    """
    isolation_map = {
        TransactionIsolationLevel.READ_UNCOMMITTED: 1,
        TransactionIsolationLevel.READ_COMMITTED: 2,
        TransactionIsolationLevel.REPEATABLE_READ: 4,
        TransactionIsolationLevel.SERIALIZABLE: 8
    }
    return isolation_map.get(isolation_level, 2)
