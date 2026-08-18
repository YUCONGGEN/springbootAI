"""ORM PyMyBatis 完整测试 - 覆盖 SQL 注解、结果映射、DDL 自动建表等。"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from springbootai.orm.pymybatis.annotations.annotations import (
    Select, Insert, Update, Delete, SelectAnnotation, InsertAnnotation,
    UpdateAnnotation, DeleteAnnotation, Param, Result, ResultMap, Options,
)
from springbootai.orm.ddl_auto import (
    DdlAutoManager, DdlAutoMode, Column, Id, Table, Index, entity,
    _camel_to_snake, _get_sql_type,
)
from springbootai.orm.pymybatis.pool import create_connection_pool


# ==================== SQL 注解测试 ====================

class TestSelectAnnotation:
    def test_select_attaches_annotation(self):
        @Select("SELECT * FROM items", result_map="itemMap", result_type="dict", timeout=2)
        def find():
            pass

        assert hasattr(find, "select")
        assert isinstance(find.select, SelectAnnotation)

    def test_select_attributes(self):
        @Select("SELECT * FROM items", result_map="itemMap", result_type="dict", timeout=2)
        def find():
            pass

        ann = find.select
        assert ann.value == "SELECT * FROM items"
        assert ann.result_map == "itemMap"
        assert ann.result_type == "dict"
        assert ann.timeout == 2

    def test_select_default_cache_true(self):
        @Select("SELECT 1")
        def find():
            pass

        assert find.select.cache is True

    def test_select_annotation_direct_construction(self):
        ann = SelectAnnotation("SELECT 1", result_type="int", timeout=5)
        assert ann.value == "SELECT 1"
        assert ann.result_type == "int"
        assert ann.timeout == 5


class TestInsertAnnotation:
    def test_insert_attaches_annotation(self):
        @Insert("INSERT INTO items(name) VALUES (#{name})", key_property="id", use_generated_keys=True)
        def insert(name):
            pass

        assert hasattr(insert, "insert")
        assert isinstance(insert.insert, InsertAnnotation)

    def test_insert_attributes(self):
        @Insert("INSERT INTO items(name) VALUES (#{name})", key_property="id", use_generated_keys=True)
        def insert(name):
            pass

        ann = insert.insert
        assert ann.value == "INSERT INTO items(name) VALUES (#{name})"
        assert ann.key_property == "id"
        assert ann.use_generated_keys is True

    def test_insert_annotation_direct(self):
        ann = InsertAnnotation("INSERT INTO t VALUES (1)")
        assert ann.use_generated_keys is False


class TestUpdateAnnotation:
    def test_update_attaches_annotation(self):
        @Update("UPDATE items SET name = #{name}", timeout=3)
        def update(name):
            pass

        assert hasattr(update, "update")
        assert isinstance(update.update, UpdateAnnotation)

    def test_update_attributes(self):
        @Update("UPDATE items SET name = #{name}", timeout=3)
        def update(name):
            pass

        ann = update.update
        assert ann.value == "UPDATE items SET name = #{name}"
        assert ann.timeout == 3


class TestDeleteAnnotation:
    def test_delete_attaches_annotation(self):
        @Delete("DELETE FROM items WHERE id = #{id}")
        def delete(id):
            pass

        assert hasattr(delete, "delete")
        assert isinstance(delete.delete, DeleteAnnotation)

    def test_delete_attributes(self):
        @Delete("DELETE FROM items WHERE id = #{id}", timeout=4)
        def delete(id):
            pass

        ann = delete.delete
        assert ann.value == "DELETE FROM items WHERE id = #{id}"
        assert ann.timeout == 4


class TestParam:
    def test_value(self):
        p = Param("id")
        assert p.value == "id"


class TestResult:
    def test_with_column_and_property(self):
        r = Result(column="item_id", property="id")
        assert r.column == "item_id"
        assert r.property == "id"

    def test_with_types(self):
        r = Result(column="id", property="id", java_type="int", jdbc_type="INTEGER")
        assert r.java_type == "int"
        assert r.jdbc_type == "INTEGER"


class TestResultMap:
    def test_requires_id_and_type(self):
        rm = ResultMap("itemMap", "dict")
        assert rm.id == "itemMap"
        assert rm.type == "dict"

    def test_with_results(self):
        rm = ResultMap(
            "itemMap", "dict",
            [Result(column="item_id", property="id")],
        )
        assert len(rm.results) == 1
        assert rm.get_property("item_id") == "id"

    def test_get_property_returns_none_for_missing(self):
        rm = ResultMap("m", "dict")
        assert rm.get_property("missing") is None

    def test_call_decorator_attaches(self):
        rm = ResultMap("itemMap", "dict")

        @rm
        class Mapper:
            pass

        assert hasattr(Mapper, "__result_maps__")
        assert rm in Mapper.__result_maps__

    def test_decorator_appends_not_replaces(self):
        rm1 = ResultMap("m1", "dict")
        rm2 = ResultMap("m2", "dict")

        @rm1
        @rm2
        class Mapper:
            pass

        assert len(Mapper.__result_maps__) == 2


class TestOptions:
    def test_defaults(self):
        opt = Options()
        assert opt.use_cache is True
        assert opt.flush_cache is False

    def test_custom(self):
        opt = Options(fetch_size=20, timeout=5, use_cache=False, flush_cache=True)
        assert opt.fetch_size == 20
        assert opt.timeout == 5
        assert opt.use_cache is False
        assert opt.flush_cache is True

    def test_call_attaches_options(self):
        opt = Options(fetch_size=20)

        @opt
        def fn():
            pass

        assert hasattr(fn, "options")
        assert fn.options.fetch_size == 20


# ==================== DDL Auto 测试 ====================

class TestCamelToSnake:
    def test_simple_camel(self):
        assert _camel_to_snake("CamelCase") == "camel_case"

    def test_already_snake(self):
        assert _camel_to_snake("snake_case") == "snake_case"

    def test_single_word(self):
        assert _camel_to_snake("User") == "user"

    def test_complex(self):
        assert _camel_to_snake("UserOrderItem") == "user_order_item"

    def test_with_numbers(self):
        assert _camel_to_snake("User2Order") == "user2_order"


class TestGetSqlType:
    def test_int_mysql_returns_bigint(self):
        assert _get_sql_type(int, "mysql") == "BIGINT"

    def test_float_mysql_returns_double(self):
        assert _get_sql_type(float, "mysql") == "DOUBLE"

    def test_str_mysql_returns_varchar(self):
        assert _get_sql_type(str, "mysql") == "VARCHAR(255)"

    def test_str_with_length(self):
        assert _get_sql_type(str, "mysql", {"length": 100}) == "VARCHAR(100)"

    def test_bool_mysql(self):
        assert _get_sql_type(bool, "mysql") == "TINYINT(1)"

    def test_bytes_mysql(self):
        assert _get_sql_type(bytes, "mysql") == "BLOB"

    def test_int_sqlite(self):
        assert _get_sql_type(int, "sqlite") == "INTEGER"

    def test_float_sqlite(self):
        assert _get_sql_type(float, "sqlite") == "REAL"

    def test_str_sqlite(self):
        assert _get_sql_type(str, "sqlite") == "TEXT"

    def test_column_definition_override(self):
        assert _get_sql_type(int, "mysql", {"column_definition": "MEDIUMINT"}) == "MEDIUMINT"


# ==================== Column / Id / Table / Index 测试 ====================

class TestColumn:
    def test_defaults(self):
        c = Column()
        assert c.nullable is True
        assert c.unique is False
        assert c.primary_key is False

    def test_custom(self):
        c = Column(name="user_id", nullable=False, unique=True, length=50, comment="user id")
        assert c.name == "user_id"
        assert c.nullable is False
        assert c.unique is True
        assert c.length == 50
        assert c.comment == "user id"


class TestId:
    def test_id_is_column_with_primary_key(self):
        i = Id()
        assert i.primary_key is True
        assert i.nullable is False

    def test_id_auto_increment_default(self):
        i = Id()
        assert i.auto_increment is True

    def test_id_custom_name(self):
        i = Id(name="user_id")
        assert i.name == "user_id"


class TestTable:
    def test_defaults(self):
        t = Table()
        assert t.name == ""
        assert t.indexes == []

    def test_with_name_and_indexes(self):
        idx = Index("idx_name", ["name"])
        t = Table(name="users", indexes=[idx], comment="users table")
        assert t.name == "users"
        assert len(t.indexes) == 1
        assert t.comment == "users table"


class TestIndex:
    def test_basic(self):
        idx = Index("idx_name", ["name"])
        assert idx.name == "idx_name"
        assert idx.columns == ["name"]
        assert idx.unique is False

    def test_unique(self):
        idx = Index("uk_email", ["email"], unique=True)
        assert idx.unique is True


# ==================== @entity 装饰器测试 ====================

class TestEntityDecorator:
    def test_sets_entity_and_table(self):
        @entity("sys_user")
        class User:
            pass

        assert User.__entity__ is True
        assert hasattr(User, "__table__")
        assert User.__table__.name == "sys_user"

    def test_no_table_name_uses_camel_to_snake(self):
        @entity()
        class UserOrder:
            pass

        assert UserOrder.__table__.name == "user_order"

    def test_preserves_class_identity(self):
        @entity("t")
        class T:
            pass

        assert T.__name__ == "T"


# ==================== DdlAutoManager 测试 ====================

class TestDdlAutoMode:
    def test_values(self):
        assert DdlAutoMode.NONE.value == "none"
        assert DdlAutoMode.VALIDATE.value == "validate"
        assert DdlAutoMode.UPDATE.value == "update"
        assert DdlAutoMode.CREATE.value == "create"
        assert DdlAutoMode.CREATE_DROP.value == "create-drop"


class TestDdlAutoManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_orm.db")
        self.pool = create_connection_pool(
            "sqlite",
            {"database": self.db_path, "min_size": 1, "max_size": 3},
        )

    def teardown_method(self):
        try:
            self.pool.close()
        finally:
            os.remove(self.db_path)
            os.rmdir(self.tmpdir)

    def test_create_manager(self):
        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        assert mgr.dialect == "sqlite"
        assert mgr.mode == DdlAutoMode.NONE

    def test_register_entity(self):
        @entity("users")
        class User:
            def __init__(self, id: int = None, name: str = ""):
                self.id = id
                self.name = name

        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        mgr.register_entity(User)
        assert len(mgr._entities) == 1

    def test_invalid_mode_falls_back_to_none(self):
        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="invalid_mode")
        assert mgr.mode == DdlAutoMode.NONE

    def test_get_generated_sql(self):
        @entity("users")
        class User:
            def __init__(self, id: int = None, name: str = ""):
                self.id = id
                self.name = name

        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        mgr.register_entity(User)
        sqls = mgr.get_generated_sql()
        assert len(sqls) == 1
        assert "CREATE TABLE" in sqls[0]
        assert "users" in sqls[0]

    def test_execute_create(self):
        @entity("users_test")
        class User:
            def __init__(self, id: int = None, name: str = ""):
                self.id = id
                self.name = name

        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="create")
        mgr.register_entity(User)
        executed = mgr.execute()
        assert len(executed) >= 1
        # Verify table actually exists by querying sqlite_master
        pooled = self.pool.get_connection()
        conn = pooled.connection
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", ("users_test",))
        rows = cursor.fetchall()
        cursor.close()
        self.pool.return_connection(pooled)
        assert len(rows) == 1

    def test_execute_none_mode_returns_empty(self):
        @entity("t_none")
        class T:
            def __init__(self, id: int = None):
                self.id = id

        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        mgr.register_entity(T)
        assert mgr.execute() == []

    def test_register_entities_batch(self):
        @entity("t1")
        class T1:
            def __init__(self, id: int = None):
                self.id = id

        @entity("t2")
        class T2:
            def __init__(self, id: int = None):
                self.id = id

        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        mgr.register_entities([T1, T2])
        assert len(mgr._entities) == 2

    def test_get_executed_sql_empty_initially(self):
        mgr = DdlAutoManager(self.pool, dialect="sqlite", mode="none")
        assert mgr.get_executed_sql() == []


# ==================== create_connection_pool 测试 ====================

class TestCreateConnectionPool:
    def test_creates_sqlite_pool(self):
        pool = create_connection_pool(
            "sqlite",
            {"database": ":memory:", "min_size": 1, "max_size": 1},
        )
        try:
            assert pool.max_size == 1
        finally:
            pool.close()

    def test_unsupported_dialect_raises(self):
        # "oracle" is a known dialect but cx_Oracle is not installed; use a
        # clearly unknown dialect to verify ValueError is raised by the
        # pool_map lookup.
        with pytest.raises(ValueError):
            create_connection_pool("unsupported_db", {"database": ":memory:"})


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
