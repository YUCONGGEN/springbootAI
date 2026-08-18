#!/usr/bin/env python3
"""
@CreateTime / @UpdateTime 自动时间填充功能测试

覆盖：
- 注解/装饰器元数据标记
- DDL 建表：各干言下日期时间类型 + 数据库默认值
- AuditTimeExecutor.fill_on_insert / fill_on_update 运行时填充
- 与 DDL 自动建表 + 真实 SQLite 插入/更新的端到端验证
"""
import os
import sys
import sqlite3

import pytest

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tests._test_helpers  # noqa: F401  安装模块mock

from springbootai.orm import (
    DdlAutoManager, entity, Id, CreateTime, UpdateTime,
    create_time_column, update_time_column, AuditTimeExecutor,
)
from springbootai.orm.pymybatis.pool import create_connection_pool


# ==================== 测试实体 ====================

@entity("t_user_audit")
class UserAudit:
    id = Id()
    created_at = CreateTime()
    updated_at = UpdateTime()

    def __init__(self, id=None, name="", created_at=None, updated_at=None):
        self.id = id
        self.name = name
        self.created_at = created_at
        self.updated_at = updated_at


@entity("t_custom_audit")
class CustomAudit:
    id = Id()
    @create_time_column(name="create_time")
    def ctime(self):
        pass
    @update_time_column(name="update_time")
    def utime(self):
        pass

    def __init__(self, id=None, ctime=None, utime=None):
        self.id = id
        self.ctime = ctime
        self.utime = utime


@pytest.fixture
def sqlite_pool(tmp_path):
    """每个用例独立的 SQLite 连接池"""
    db_path = str(tmp_path / "audit.db")
    pool = create_connection_pool('sqlite', {
        'driver': 'sqlite',
        'database': db_path,
    })
    yield pool
    try:
        pool.close()
    except Exception:
        pass


# ==================== 注解/DDL 元数据 ====================

class TestAnnotations:
    def test_descriptor_flags(self):
        """CreateTime / UpdateTime 描述符标记"""
        assert CreateTime().create_time is True
        assert UpdateTime().update_time is True
        assert CreateTime().nullable is False
        assert UpdateTime().nullable is False

    def test_decorator_flags(self):
        """create_time_column / update_time_column 装饰器"""
        @create_time_column()
        def f():
            pass
        assert f.__column__.create_time is True

        @update_time_column()
        def g():
            pass
        assert g.__column__.update_time is True

    def test_parse_flags(self):
        """实体解析出 create_time / update_time 标记"""
        ddl = DdlAutoManager(None, dialect='sqlite', mode='none')
        et = ddl._parse_entity(UserAudit)
        cols = {c['name']: c for c in et.columns}
        assert cols['created_at']['create_time'] is True
        assert cols['updated_at']['update_time'] is True
        # 未标注的字段两个标记都为 False
        assert cols['name']['create_time'] is False
        assert cols['name']['update_time'] is False

    def test_custom_column_name_decorator(self):
        """装饰器形式 + 自定义列名"""
        ddl = DdlAutoManager(None, dialect='sqlite', mode='none')
        et = ddl._parse_entity(CustomAudit)
        cols = {c['name']: c for c in et.columns}
        assert cols['create_time']['create_time'] is True
        assert cols['update_time']['update_time'] is True
        assert cols['create_time']['py_name'] == 'ctime'
        assert cols['update_time']['py_name'] == 'utime'


# ==================== DDL 生成 ====================

class TestDdl:
    def test_mysql_default_timestamp(self):
        """MySQL：DATETIME + DEFAULT CURRENT_TIMESTAMP"""
        ddl = DdlAutoManager(None, dialect='mysql', mode='none')
        et = ddl._parse_entity(UserAudit)
        sql = ddl._build_create_table_sql(et)
        assert 'DATETIME' in sql
        assert 'DEFAULT CURRENT_TIMESTAMP' in sql

    def test_postgresql_default_timestamp(self):
        """PostgreSQL：TIMESTAMP + DEFAULT CURRENT_TIMESTAMP"""
        ddl = DdlAutoManager(None, dialect='postgresql', mode='none')
        et = ddl._parse_entity(UserAudit)
        sql = ddl._build_create_table_sql(et)
        assert 'TIMESTAMP' in sql
        assert 'DEFAULT CURRENT_TIMESTAMP' in sql

    def test_sqlite_default_datetime_now(self):
        """SQLite：TEXT + DEFAULT (datetime('now','localtime'))"""
        ddl = DdlAutoManager(None, dialect='sqlite', mode='none')
        et = ddl._parse_entity(UserAudit)
        sql = ddl._build_create_table_sql(et)
        assert "DEFAULT (datetime('now', 'localtime'))" in sql

    def test_create_table_end_to_end(self, sqlite_pool):
        """实际建表：created_at/updated_at 列存在且带默认值"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl.register_entity(UserAudit)
        ddl.execute()
        assert ddl._table_exists('t_user_audit')
        cols = ddl._get_existing_columns('t_user_audit')
        assert 'created_at' in cols
        assert 'updated_at' in cols

        # 数据库默认值兜底：不填时间也能插入
        conn = sqlite3.connect(str(sqlite_pool.config['database']))
        conn.execute("INSERT INTO t_user_audit (name) VALUES ('no-time')")
        conn.commit()
        row = conn.execute(
            "SELECT created_at, updated_at FROM t_user_audit "
            "WHERE name='no-time'").fetchone()
        conn.close()
        assert row[0] is not None
        assert row[1] is not None


# ==================== 运行时填充 ====================

class TestAuditTimeExecutor:
    def test_fill_on_insert_both_fields(self):
        """fill_on_insert 同时填充 created_at 与 updated_at"""
        ex = AuditTimeExecutor(now='2026-08-12 10:00:00')
        user = UserAudit(name="John")
        ex.fill_on_insert(UserAudit, user)
        assert user.created_at == '2026-08-12 10:00:00'
        assert user.updated_at == '2026-08-12 10:00:00'

    def test_fill_on_insert_keeps_existing(self):
        """fill_on_insert 保留已存在的时间值"""
        ex = AuditTimeExecutor(now='2026-08-12 10:00:00')
        user = UserAudit(name="John", created_at='2020-01-01 00:00:00')
        ex.fill_on_insert(UserAudit, user)
        assert user.created_at == '2020-01-01 00:00:00'  # 已有值保留
        assert user.updated_at == '2026-08-12 10:00:00'  # 空值被填充

    def test_fill_on_update_only_update_time(self):
        """fill_on_update 仅刷新 updated_at，不改 created_at"""
        ex = AuditTimeExecutor(now='2026-08-12 10:00:00')
        user = UserAudit(name="John", created_at='2026-08-12 09:00:00',
                         updated_at='2026-08-12 09:00:00')
        ex = AuditTimeExecutor(now='2026-08-12 11:00:00')
        ex.fill_on_update(UserAudit, user)
        assert user.created_at == '2026-08-12 09:00:00'  # 不变
        assert user.updated_at == '2026-08-12 11:00:00'  # 刷新

    def test_fill_with_custom_column_names(self):
        """自定义列名（装饰器形式）也能正确填充"""
        ex = AuditTimeExecutor(now='2026-08-12 10:00:00')
        obj = CustomAudit()
        ex.fill_on_insert(CustomAudit, obj)
        assert obj.ctime == '2026-08-12 10:00:00'
        assert obj.utime == '2026-08-12 10:00:00'

    def test_end_to_end_insert_update(self, sqlite_pool):
        """端到端：DDL 建表 + 填充 + 真实插入/更新"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl.register_entity(UserAudit)
        ddl.execute()

        ex = AuditTimeExecutor(now='2026-08-12 10:00:00')
        user = UserAudit(name="Alice")
        ex.fill_on_insert(UserAudit, user)

        conn = sqlite3.connect(str(sqlite_pool.config['database']))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO t_user_audit (name, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            (user.name, user.created_at, user.updated_at))
        conn.commit()
        rid = cur.lastrowid

        # 更新：刷新 updated_at
        ex = AuditTimeExecutor(now='2026-08-12 12:00:00')
        user.id = rid
        ex.fill_on_update(UserAudit, user)
        cur.execute(
            "UPDATE t_user_audit SET name=?, updated_at=? WHERE id=?",
            (user.name, user.updated_at, user.id))
        conn.commit()

        row = cur.execute(
            "SELECT created_at, updated_at FROM t_user_audit WHERE id=?",
            (rid,)).fetchone()
        conn.close()
        assert row[0] == '2026-08-12 10:00:00'
        assert row[1] == '2026-08-12 12:00:00'


if __name__ == '__main__':
    import pytest as _pytest
    _pytest.main([__file__, "-v", "--tb=short"])