"""SpringPy JPA @Version / @Transient 模块测试 —— 覆盖注解/DDL生成/瞬态跳过/乐观锁执行器。

对齐 tests/test_orm_pymybatis_full.py 的 pytest 风格。使用 DdlAutoManager 解析实体生成 DDL
（不依赖真实数据库，dialect=sqlite），乐观锁执行器用内存 sqlite 真实执行。
"""
import os
import sys
import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.orm import (
    entity, Id, Version, Transient, Column, Index,
    version_column, transient_field,
    DdlAutoManager, DdlAutoMode,
    OptimisticLockExecutor, OptimisticLockError,
)


# ==================== 测试实体 ====================

@entity("sys_user")
class User:
    id = Id()
    name = Column(name="user_name", nullable=False, length=50)
    version = Version()
    display_name = Transient()  # 瞬态：不落库

    def __init__(self, id=None, name=None, version=0, display_name=None):
        self.id = id
        self.name = name
        self.version = version
        self.display_name = display_name


@entity("sys_order")
class Order:
    id = Id()
    amount = Column(nullable=False)
    remark = Transient()

    @version_column()
    def version(self): ...

    @transient_field()
    def cache_key(self): ...

    # 注意：函数装饰器形式字段需在 __init__ 中赋值才参与解析回退
    def __init__(self, id=None, amount=None, version=0, remark=None, cache_key=None):
        self.id = id
        self.amount = amount
        self.version = version
        self.remark = remark
        self.cache_key = cache_key


def _parse(cls, dialect="sqlite"):
    """用临时 DdlAutoManager 仅做解析（不执行 DDL）。"""
    m = DdlAutoManager.__new__(DdlAutoManager)
    m.pool = None
    m.dialect = dialect
    m.mode = DdlAutoMode.NONE
    m._entities = [cls]
    m._parsed = []
    m._executed_sql = []
    m._lock = __import__("threading").Lock()
    return m._parse_entity(cls)


def _build_sql(cls, dialect="sqlite"):
    """生成 CREATE TABLE SQL。"""
    m = DdlAutoManager.__new__(DdlAutoManager)
    m.pool = None
    m.dialect = dialect
    m.mode = DdlAutoMode.NONE
    m._entities = [cls]
    m._parsed = []
    m._executed_sql = []
    m._lock = __import__("threading").Lock()
    et = m._parse_entity(cls)
    return m._build_create_table_sql(et), et


# ==================== 注解基础 ====================

class TestAnnotations:
    def test_version_is_column_subclass(self):
        assert issubclass(Version, Column)
        v = Version()
        assert v.version is True
        assert v.primary_key is False
        assert v.nullable is False
        assert v.default == 0

    def test_version_custom_name(self):
        v = Version(name="ver")
        assert v.name == "ver"

    def test_transient_is_marker(self):
        t = Transient()
        assert not isinstance(t, Column)  # 独立标记类
        t.__set_name__(object, "field_x")
        assert t.attr_name == "field_x"

    def test_transient_call_sets_marker(self):
        def f(self): ...
        Transient()(f)
        assert getattr(f, "__transient__", False) is True

    def test_version_column_decorator(self):
        @version_column()
        def v(self): ...
        assert hasattr(v, "__column__")
        assert v.__column__.version is True

    def test_transient_field_decorator(self):
        @transient_field()
        def t(self): ...
        assert getattr(t, "__transient__", False) is True


# ==================== DDL 解析与生成 ====================

class TestDdlParsing:
    def test_version_column_generated(self):
        et = _parse(User)
        names = [c["name"] for c in et.columns]
        assert "version" in names

    def test_version_meta_flags(self):
        et = _parse(User)
        vcol = next(c for c in et.columns if c["py_name"] == "version")
        assert vcol["version"] is True
        assert vcol["nullable"] is False
        assert vcol["sql_type"] == "INTEGER"
        assert vcol["default"] == 0

    def test_transient_field_skipped(self):
        et = _parse(User)
        names = [c["name"] for c in et.columns]
        assert "display_name" not in names
        assert "display_name" not in [c["py_name"] for c in et.columns]

    def test_create_table_sql_contains_version_not_transient(self):
        sql, _ = _build_sql(User, dialect="mysql")
        assert "version" in sql.lower()
        assert "display_name" not in sql.lower()
        assert "INTEGER" in sql  # version 类型
        # version 列 DEFAULT 0
        assert "DEFAULT 0" in sql

    def test_sqlite_dialect_version_type(self):
        sql, _ = _build_sql(User, dialect="sqlite")
        assert "version" in sql.lower()
        # sqlite 整型
        assert "INTEGER" in sql

    def test_function_decorator_version_and_transient(self):
        et = _parse(Order)
        names = [c["name"] for c in et.columns]
        assert "version" in names  # version_column 函数装饰器
        assert "remark" not in names  # transient_field 跳过
        vcol = next(c for c in et.columns if c["py_name"] == "version")
        assert vcol["version"] is True

    def test_no_version_field_returns_none(self):
        @entity("no_ver")
        class NoVer:
            id = Id()
            name = Column()
            def __init__(self, id=None, name=None): self.id = id; self.name = name
        from spring.orm.ddl_auto import _find_version_column
        assert _find_version_column(NoVer) is None


# ==================== 乐观锁执行器（真实 sqlite） ====================

class _PooledConn:
    """连接池返回的连接包装器：委托真实 sqlite3 连接，``close()`` 为 no-op。

    模拟真实连接池（如 DBUtils）语义：``pool.connection()`` 返回的连接 ``close()``
    归还池而非销毁底层连接，使 ``OptimisticLockExecutor._execute_dml`` 的 finally
    关闭逻辑不影响同一测试内的后续访问。
    """

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):  # no-op：归还池
        return None

    def __getattr__(self, item):
        return getattr(self._conn, item)


class _RawSqlitePool:
    """模拟连接池：包一个 sqlite3 连接，``connection()`` 返回池化包装器。"""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return _PooledConn(self._conn)


class TestOptimisticLockExecutor:
    def _setup_db(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute(
            "CREATE TABLE sys_user (id INTEGER PRIMARY KEY, user_name TEXT, version INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute("INSERT INTO sys_user (id, user_name, version) VALUES (1, 'old', 0)")
        conn.commit()
        return conn

    def test_try_update_success_increments_version(self):
        conn = self._setup_db()
        pool = _RawSqlitePool(conn)
        exe = OptimisticLockExecutor(pool, dialect="sqlite")
        u = User(id=1, name="old", version=0)
        ok = exe.try_update(User, u, set_fields={"name": "new"})
        assert ok is True
        # 实体回写新版本号
        assert u.version == 1
        # 数据库实际更新
        row = conn.execute("SELECT user_name, version FROM sys_user WHERE id=1").fetchone()
        assert row[0] == "new"
        assert row[1] == 1

    def test_update_returns_new_version(self):
        conn = self._setup_db()
        pool = _RawSqlitePool(conn)
        exe = OptimisticLockExecutor(pool, dialect="sqlite")
        u = User(id=1, name="old", version=0)
        new_ver = exe.update(User, u, set_fields={"name": "v2"})
        assert new_ver == 1

    def test_optimistic_lock_conflict_raises(self):
        conn = self._setup_db()
        pool = _RawSqlitePool(conn)
        exe = OptimisticLockExecutor(pool, dialect="sqlite")
        # 模拟并发：实体持有的 version 已过期（数据库已是 0，实体传 5）
        u = User(id=1, name="old", version=5)
        with pytest.raises(OptimisticLockError):
            exe.update(User, u, set_fields={"name": "x"})
        # try_update 返回 False
        ok = exe.try_update(User, User(id=1, version=99), set_fields={"name": "y"})
        assert ok is False

    def test_update_without_version_annotation_raises(self):
        @entity("no_ver_tbl")
        class NoVer:
            id = Id()
            name = Column()
            def __init__(self, id=None, name=None, version=0): self.id = id; self.name = name
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE no_ver_tbl (id INTEGER PRIMARY KEY, name TEXT)")
        exe = OptimisticLockExecutor(_RawSqlitePool(conn), dialect="sqlite")
        with pytest.raises(ValueError):
            exe.try_update(NoVer, NoVer(id=1), set_fields={"name": "x"})

    def test_missing_pk_raises(self):
        @entity("no_pk_tbl")
        class NoPk:
            name = Column()
            version = Version()
            def __init__(self, name=None, version=0): self.name = name; self.version = version
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE no_pk_tbl (name TEXT, version INTEGER)")
        exe = OptimisticLockExecutor(_RawSqlitePool(conn), dialect="sqlite")
        with pytest.raises(ValueError):
            exe.try_update(NoPk, NoPk(name="x"), set_fields={"name": "y"})

    def test_empty_pk_value_raises(self):
        conn = self._setup_db()
        exe = OptimisticLockExecutor(_RawSqlitePool(conn), dialect="sqlite")
        u = User(id=None, version=0)
        with pytest.raises(ValueError):
            exe.try_update(User, u, set_fields={"name": "x"})

    def test_quoting_mysql_dialect(self):
        exe = OptimisticLockExecutor(_RawSqlitePool(sqlite3.connect(":memory:")), dialect="mysql")
        assert exe._quote("col") == "`col`"
        exe2 = OptimisticLockExecutor(_RawSqlitePool(sqlite3.connect(":memory:")), dialect="sqlite")
        assert exe2._quote("col") == '"col"'
