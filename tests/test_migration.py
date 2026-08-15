#!/usr/bin/env python3
"""
数据库迁移管理器完整功能测试（pytest 套件）

覆盖 MigrationManager / MigrationRecord / MigrationError 的核心逻辑：
- 初始化与配置
- SQL 语句分割
- 变量替换
- 正向迁移执行
- Undo 回滚
- 校验一致性
- 迁移锁
"""
import os
import sys
import sqlite3
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tests._test_helpers  # noqa: F401  安装模块mock

from spring.orm.migration import MigrationManager, MigrationRecord, MigrationError
from spring.orm.pymybatis.pool import create_connection_pool


# ==================== 辅助夹具 ====================

@pytest.fixture
def sqlite_pool(tmp_path):
    """每个用例独立的 SQLite 连接池"""
    db_path = str(tmp_path / "test.db")
    pool = create_connection_pool('sqlite', {
        'driver': 'sqlite',
        'database': db_path,
    })
    yield pool
    try:
        pool.close()
    except Exception:
        pass


@pytest.fixture
def migration_dir(tmp_path):
    """创建临时迁移文件目录"""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    return mig_dir


def _write_migration(migration_dir, filename, content):
    """在迁移目录中写入迁移文件"""
    filepath = migration_dir / filename
    filepath.write_text(content, encoding='utf-8')
    return filepath


# ==================== 初始化测试 ====================

class TestMigrationManagerInit:
    """MigrationManager 初始化测试"""

    def test_init_with_sqlite_pool(self, sqlite_pool, migration_dir):
        """使用 SQLite 连接池初始化，应自动创建 schema_version 表"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        # 验证 schema_version 表已创建
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        assert cursor.fetchone() is not None
        cursor.close()
        sqlite_pool.return_connection(pooled)

    def test_init_custom_table_name(self, sqlite_pool, migration_dir):
        """使用自定义表名初始化"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            table_name='my_migrations',
        )
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='my_migrations'")
        assert cursor.fetchone() is not None
        cursor.close()
        sqlite_pool.return_connection(pooled)

    def test_init_invalid_table_name_raises(self, sqlite_pool, migration_dir):
        """无效的表名应抛出 ValueError"""
        with pytest.raises(ValueError, match="simple SQL identifier"):
            MigrationManager(
                sqlite_pool,
                migrations_dir=str(migration_dir),
                dialect='sqlite',
                table_name='drop table foo;--',
            )

    def test_init_with_variables(self, sqlite_pool, migration_dir):
        """使用变量字典初始化"""
        variables = {'app_schema': 'myapp', 'table_prefix': 't_'}
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            variables=variables,
        )
        assert manager.variables == variables

    def test_init_nonexistent_migration_dir(self, sqlite_pool, tmp_path):
        """迁移目录不存在时应正常初始化（不报错）"""
        missing_dir = tmp_path / "not_exist"
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(missing_dir),
            dialect='sqlite',
        )
        # 目录不存在，discover 应返回空列表
        assert manager._discover_migrations() == []


# ==================== SQL 分割测试 ====================

class TestSplitSqlStatements:
    """_split_sql_statements 方法测试"""

    @pytest.fixture
    def manager(self, sqlite_pool, migration_dir):
        return MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )

    def test_split_single_statement(self, manager):
        """分割单条 SQL 语句"""
        sql = "CREATE TABLE users (id INTEGER PRIMARY KEY);"
        result = manager._split_sql_statements(sql)
        assert len(result) == 1
        assert "CREATE TABLE users" in result[0]

    def test_split_multiple_statements(self, manager):
        """分割多条 SQL 语句"""
        sql = "CREATE TABLE t1 (id INT);\nCREATE TABLE t2 (id INT);"
        result = manager._split_sql_statements(sql)
        assert len(result) == 2
        assert "CREATE TABLE t1" in result[0]
        assert "CREATE TABLE t2" in result[1]

    def test_split_with_trailing_semicolon(self, manager):
        """末尾有多余分号时的分割"""
        sql = "SELECT 1;;\nSELECT 2;"
        result = manager._split_sql_statements(sql)
        # 每行以分号结尾时各成一条语句，空语句被过滤
        assert len(result) >= 2

    def test_split_empty_content(self, manager):
        """空内容应返回空列表"""
        assert manager._split_sql_statements("") == []
        assert manager._split_sql_statements("\n\n") == []

    def test_split_with_comments(self, manager):
        """注释行应被跳过"""
        sql = "-- 这是注释\nCREATE TABLE t (id INT);\n# 这也是注释\nINSERT INTO t VALUES (1);"
        result = manager._split_sql_statements(sql)
        assert len(result) == 2
        assert "CREATE TABLE t" in result[0]
        assert "INSERT INTO t" in result[1]
        # 确保注释内容不在结果中
        for stmt in result:
            assert "这是注释" not in stmt
            assert "这也是注释" not in stmt

    def test_split_statement_without_semicolon(self, manager):
        """没有分号的 SQL 应作为最后一条保留"""
        sql = "CREATE TABLE t1 (id INT);\nCREATE TABLE t2 (id INT)"
        result = manager._split_sql_statements(sql)
        assert len(result) == 2
        assert "CREATE TABLE t2" in result[1]


# ==================== 变量替换测试 ====================

class TestSubstituteVariables:
    """_substitute_variables 方法测试"""

    def test_substitute_simple_var(self, sqlite_pool, migration_dir):
        """替换单个变量"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            variables={'app_schema': 'myapp'},
        )
        result = manager._substitute_variables("SELECT * FROM ${app_schema}.users")
        assert result == "SELECT * FROM myapp.users"

    def test_substitute_multiple_vars(self, sqlite_pool, migration_dir):
        """替换多个变量"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            variables={'prefix': 't_', 'schema': 'app'},
        )
        result = manager._substitute_variables("CREATE TABLE ${schema}.${prefix}users (id INT)")
        assert result == "CREATE TABLE app.t_users (id INT)"

    def test_substitute_no_vars(self, sqlite_pool, migration_dir):
        """无变量配置时不替换"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        sql = "SELECT * FROM users"
        result = manager._substitute_variables(sql)
        assert result == sql

    def test_substitute_unknown_var_raises(self, sqlite_pool, migration_dir):
        """未知变量应抛出 MigrationError"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            variables={'known': 'value'},
        )
        with pytest.raises(MigrationError, match="Undefined migration variable"):
            manager._substitute_variables("SELECT * FROM ${unknown_var}")

    def test_substitute_var_with_semicolon_raises(self, sqlite_pool, migration_dir):
        """变量值包含分号应抛出 MigrationError（防 SQL 注入）"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
            variables={'dangerous': "val; DROP TABLE users"},
        )
        with pytest.raises(MigrationError, match="semicolon"):
            manager._substitute_variables("SELECT * FROM ${dangerous}")


# ==================== 迁移执行测试 ====================

class TestMigrate:
    """正向迁移执行测试"""

    def test_migrate_creates_table(self, sqlite_pool, migration_dir):
        """migrate 执行后应创建迁移记录表"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        pooled = sqlite_pool.get_connection()
        conn = pooled.connection
        cursor = conn.cursor()
        # 迁移记录表应存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        assert cursor.fetchone() is not None
        # 业务表也应存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert cursor.fetchone() is not None
        cursor.close()
        sqlite_pool.return_connection(pooled)

    def test_migrate_executes_sql(self, sqlite_pool, migration_dir):
        """migrate 应执行 SQL 并创建业务表"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        records = manager.migrate()
        assert len(records) == 1
        assert records[0].version == '1'
        assert records[0].success is True

    def test_migrate_records_version(self, sqlite_pool, migration_dir):
        """migrate 应在 schema_version 表中记录版本信息"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        applied = manager._get_applied_versions()
        assert '1' in applied
        rec = applied['1']
        assert rec.description == 'create users'
        assert rec.script == 'V1__create_users.sql'
        assert rec.success is True

    def test_migrate_skips_already_applied(self, sqlite_pool, migration_dir):
        """已应用的迁移应被跳过"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        # 第一次迁移
        records1 = manager.migrate()
        assert len(records1) == 1

        # 第二次迁移——应跳过
        records2 = manager.migrate()
        assert len(records2) == 0

    def test_migrate_multiple_files_order(self, sqlite_pool, migration_dir):
        """多个迁移文件应按版本号顺序执行"""
        _write_migration(migration_dir, "V2__add_index.sql",
                         "CREATE INDEX idx_users_name ON users (name);")
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        _write_migration(migration_dir, "V3__add_email.sql",
                         "ALTER TABLE users ADD COLUMN email TEXT;")

        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        records = manager.migrate()
        assert len(records) == 3
        # 验证执行顺序按版本号排列
        assert records[0].version == '1'
        assert records[1].version == '2'
        assert records[2].version == '3'

    def test_migrate_checksum_mismatch_raises(self, sqlite_pool, migration_dir):
        """已应用迁移的 checksum 变更应抛出 MigrationError"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        # 篡改迁移文件内容
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);")

        with pytest.raises(MigrationError, match="Checksum mismatch"):
            manager.migrate()

    def test_migrate_baseline(self, sqlite_pool, migration_dir):
        """baseline 模式：标记已有数据库为已完成初始迁移，不执行 SQL"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        records = manager.migrate(baseline=True)
        # baseline 模式下不执行 SQL，只是标记
        assert len(records) == 0
        # 但版本已被记录
        applied = manager._get_applied_versions()
        assert '1' in applied


# ==================== 回滚测试 ====================

class TestRollback:
    """Undo 回滚测试"""

    def test_rollback_executes_undo(self, sqlite_pool, migration_dir):
        """rollback 应执行 Undo 脚本"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        _write_migration(migration_dir, "U1__drop_users.sql",
                         "DROP TABLE IF EXISTS users;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()
        records = manager.rollback()
        assert len(records) == 1
        assert 'UNDO' in records[0].description

        # 确认表已被删除
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert cursor.fetchone() is None
        cursor.close()
        sqlite_pool.return_connection(pooled)

    def test_rollback_removes_record(self, sqlite_pool, migration_dir):
        """rollback 后应从 schema_version 中删除迁移记录"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        _write_migration(migration_dir, "U1__drop_users.sql",
                         "DROP TABLE IF EXISTS users;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()
        assert '1' in manager._get_applied_versions()

        manager.rollback()
        applied = manager._get_applied_versions()
        assert '1' not in applied

    def test_rollback_to_target_version(self, sqlite_pool, migration_dir):
        """rollback 到指定版本：应回滚所有大于目标版本的迁移"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        _write_migration(migration_dir, "V2__add_index.sql",
                         "CREATE INDEX idx_users_name ON users (name);")
        _write_migration(migration_dir, "V3__add_email.sql",
                         "ALTER TABLE users ADD COLUMN email TEXT;")
        _write_migration(migration_dir, "U3__drop_email.sql",
                         "-- SQLite 不支持 DROP COLUMN，使用替代方案\nSELECT 1;")
        _write_migration(migration_dir, "U2__drop_index.sql",
                         "DROP INDEX IF EXISTS idx_users_name;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        # 回滚到 V1（回滚 V3、V2）
        records = manager.rollback(target_version='1')
        assert len(records) == 2
        # V1 应保留
        applied = manager._get_applied_versions()
        assert '1' in applied
        assert '2' not in applied
        assert '3' not in applied

    def test_rollback_without_undo_raises(self, sqlite_pool, migration_dir):
        """没有 Undo 脚本时 rollback 应抛出 MigrationError"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        # 注意：没有 U1 脚本
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        with pytest.raises(MigrationError, match="Undo script.*not found"):
            manager.rollback()

    def test_rollback_no_applied_migrations(self, sqlite_pool, migration_dir):
        """没有已应用的迁移时 rollback 应返回空列表"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        records = manager.rollback()
        assert records == []


# ==================== 校验测试 ====================

class TestValidate:
    """校验一致性测试"""

    def test_validate_all_match(self, sqlite_pool, migration_dir):
        """所有迁移 checksum 一致时应返回 True"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()
        assert manager.validate() is True

    def test_validate_checksum_mismatch(self, sqlite_pool, migration_dir):
        """checksum 不匹配时应返回 False"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        # 篡改迁移文件
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);")
        assert manager.validate() is False

    def test_validate_applied_not_in_directory(self, sqlite_pool, migration_dir):
        """已应用迁移在目录中找不到时应返回 False"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        manager.migrate()

        # 删除迁移文件
        (migration_dir / "V1__create_users.sql").unlink()
        assert manager.validate() is False

    def test_validate_no_applied_returns_true(self, sqlite_pool, migration_dir):
        """没有已应用的迁移时 validate 返回 True"""
        _write_migration(migration_dir, "V1__create_users.sql",
                         "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        assert manager.validate() is True


# ==================== 迁移锁测试 ====================

class TestDbLock:
    """迁移锁测试"""

    def test_acquire_and_release_sqlite_lock(self, sqlite_pool, migration_dir):
        """SQLite 模式下获取和释放迁移锁"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection

        # SQLite 使用进程级 threading.Lock
        acquired = manager._acquire_db_lock(conn)
        assert acquired is True

        manager._release_db_lock(conn)
        # 释放后应能再次获取
        acquired2 = manager._acquire_db_lock(conn)
        assert acquired2 is True
        manager._release_db_lock(conn)

        sqlite_pool.return_connection(pooled)

    def test_sqlite_lock_blocks_concurrent(self, sqlite_pool, migration_dir):
        """SQLite 迁移锁应阻塞并发获取（带超时）"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection

        # 先获取锁
        manager._acquire_db_lock(conn)

        # 另一个线程尝试获取锁，应超时失败
        result = []
        def try_acquire():
            # 使用短超时
            acquired = manager._lock.acquire(timeout=0.5)
            result.append(acquired)
            if acquired:
                manager._lock.release()

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join(timeout=2)
        assert False in result  # 获取失败

        # 释放锁
        manager._release_db_lock(conn)
        sqlite_pool.return_connection(pooled)

    def test_release_lock_without_acquire_no_error(self, sqlite_pool, migration_dir):
        """未获取锁时释放不应抛出异常"""
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        pooled = sqlite_pool.get_connection()
        conn = pooled.connection
        # 直接释放（锁未被持有），应不报错
        manager._release_db_lock(conn)
        sqlite_pool.return_connection(pooled)


# ==================== MigrationRecord 测试 ====================

class TestMigrationRecord:
    """MigrationRecord 数据类测试"""

    def test_record_attributes(self):
        """验证 MigrationRecord 属性正确赋值"""
        rec = MigrationRecord(
            version='1',
            description='create users',
            script='V1__create_users.sql',
            checksum='abc123',
            execution_time=0.05,
            success=True,
        )
        assert rec.version == '1'
        assert rec.description == 'create users'
        assert rec.script == 'V1__create_users.sql'
        assert rec.checksum == 'abc123'
        assert rec.execution_time == 0.05
        assert rec.success is True

    def test_record_defaults(self):
        """验证 MigrationRecord 默认值"""
        rec = MigrationRecord(
            version='2',
            description='add index',
            script='V2__add_index.sql',
            checksum='def456',
        )
        assert rec.execution_time == 0.0
        assert rec.success is True
        assert rec.installed_on > 0


# ==================== MigrationError 测试 ====================

class TestMigrationError:
    """MigrationError 异常测试"""

    def test_migration_error_is_exception(self):
        """MigrationError 应是 Exception 的子类"""
        assert issubclass(MigrationError, Exception)

    def test_migration_error_message(self):
        """MigrationError 应正确传递错误消息"""
        err = MigrationError("something went wrong")
        assert str(err) == "something went wrong"

    def test_migration_error_from_cause(self):
        """MigrationError 应能通过 from 链接原始异常"""
        original = ValueError("bad value")
        err = MigrationError("migration failed")
        err.__cause__ = original
        assert err.__cause__ is original


# ==================== 发现迁移文件测试 ====================

class TestDiscoverMigrations:
    """迁移文件发现测试"""

    def test_discover_finds_v_files(self, sqlite_pool, migration_dir):
        """应发现 V{version}__{desc}.sql 格式的迁移文件"""
        _write_migration(migration_dir, "V1__create_users.sql", "SELECT 1;")
        _write_migration(migration_dir, "V2__add_index.sql", "SELECT 2;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        discovered = manager._discover_migrations()
        versions = [m[0] for m in discovered]
        assert '1' in versions
        assert '2' in versions

    def test_discover_ignores_non_migration_files(self, sqlite_pool, migration_dir):
        """非迁移文件应被忽略"""
        _write_migration(migration_dir, "V1__create_users.sql", "SELECT 1;")
        _write_migration(migration_dir, "README.md", "documentation")
        _write_migration(migration_dir, "U1__undo.sql", "SELECT 1;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        discovered = manager._discover_migrations()
        assert len(discovered) == 1
        assert discovered[0][0] == '1'

    def test_discover_undo_migrations(self, sqlite_pool, migration_dir):
        """应发现 U{version}__{desc}.sql 格式的回滚文件"""
        _write_migration(migration_dir, "V1__create_users.sql", "SELECT 1;")
        _write_migration(migration_dir, "U1__drop_users.sql", "DROP TABLE users;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        undos = manager._discover_undo_migrations()
        assert '1' in undos
        desc, filename, content = undos['1']
        assert desc == 'drop users'
        assert filename == 'U1__drop_users.sql'

    def test_discover_sorted_by_version(self, sqlite_pool, migration_dir):
        """迁移文件应按版本号排序"""
        _write_migration(migration_dir, "V10__late.sql", "SELECT 10;")
        _write_migration(migration_dir, "V2__second.sql", "SELECT 2;")
        _write_migration(migration_dir, "V1__first.sql", "SELECT 1;")
        manager = MigrationManager(
            sqlite_pool,
            migrations_dir=str(migration_dir),
            dialect='sqlite',
        )
        discovered = manager._discover_migrations()
        versions = [m[0] for m in discovered]
        assert versions == ['1', '2', '10']
