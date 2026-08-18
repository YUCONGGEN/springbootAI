#!/usr/bin/env python3
"""
DDL Auto 完整功能测试（pytest 套件）
覆盖 create / update / validate / none / create-drop 模式以及 @entity 注解、
类型映射、索引生成、多方言 SQL 生成等。每个用例自包含，不依赖执行顺序。
"""
import os
import sys

import pytest
from types import SimpleNamespace
from unittest.mock import patch

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tests._test_helpers  # noqa: F401  安装模块mock

from springbootai.orm.ddl_auto import (
    DdlAutoManager, DdlAutoMode, entity, table, Index, Column, Id,
    column, id_column, init_ddl_auto, _camel_to_snake, _get_sql_type,
)
from springbootai.orm.pymybatis.pool import create_connection_pool


def test_mybatis_configurer_uses_session_factory_connection_pool():
    from springbootai.orm.mybatis_integration import MyBatisConfigurer

    pool = object()
    configurer = MyBatisConfigurer(config_loader=None)
    configurer.sql_session_factory = SimpleNamespace(
        connection_pool=pool,
        configuration=SimpleNamespace(),
    )
    db_config = {"ddl-auto": {"mode": "update"}}

    with patch("springbootai.orm.ddl_auto.init_ddl_auto") as init_ddl_auto:
        configurer._init_ddl_auto(db_config)

    init_ddl_auto.assert_called_once_with(pool, db_config)


# ==================== 实体定义 ====================

@entity("sys_user", indexes=[
    Index("idx_user_username", ["username"], unique=True),
    Index("idx_user_email", ["email"]),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = "",
                 age: int = 0, status: int = 1):
        self.id = id
        self.username = username
        self.email = email
        self.age = age
        self.status = status


@entity("sys_role")
class Role:
    def __init__(self, id: int = None, role_name: str = "", role_code: str = ""):
        self.id = id
        self.role_name = role_name
        self.role_code = role_code


# ==================== 工具夹具 ====================

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


# ==================== 模式测试 ====================

class TestDdlAutoModes:
    def test_create_mode_creates_tables(self, sqlite_pool):
        """create 模式：应删除并创建表"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl.register_entities([User, Role])
        sqls = ddl.execute()

        assert len(sqls) >= 2
        assert ddl._table_exists('sys_user')
        assert ddl._table_exists('sys_role')

    def test_create_mode_drops_existing_table(self, sqlite_pool):
        """create 模式：表已存在时应先删除再创建"""
        ddl1 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl1.register_entity(User)
        ddl1.execute()
        assert ddl1._table_exists('sys_user')

        # 再次 create 应包含 DROP TABLE 语句
        ddl2 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl2.register_entity(User)
        sqls = ddl2.execute()
        assert any('DROP TABLE' in s for s in sqls)
        assert ddl2._table_exists('sys_user')

    def test_none_mode_does_nothing(self, sqlite_pool):
        """none 模式：不执行任何 SQL"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='none')
        ddl.register_entity(User)
        sqls = ddl.execute()
        assert sqls == []
        assert not ddl._table_exists('sys_user')

    def test_unknown_mode_falls_back_to_none(self, sqlite_pool):
        """未知模式：回退到 none"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='weird-mode')
        assert ddl.mode == DdlAutoMode.NONE
        ddl.register_entity(User)
        assert ddl.execute() == []

    def test_update_mode_adds_new_columns(self, sqlite_pool):
        """update 模式：为已存在的表添加新列"""
        @entity("sys_user")
        class UserV1:
            def __init__(self, id: int = None, username: str = ""):
                self.id = id
                self.username = username

        ddl1 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl1.register_entity(UserV1)
        ddl1.execute()

        cols = ddl1._get_existing_columns('sys_user')
        assert 'id' in cols and 'username' in cols
        assert 'email' not in cols

        ddl2 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='update')
        ddl2.register_entity(User)
        sqls = ddl2.execute()

        cols2 = ddl2._get_existing_columns('sys_user')
        assert 'email' in cols2
        assert 'age' in cols2
        assert any('ALTER TABLE' in s and 'ADD COLUMN' in s for s in sqls)

    def test_update_mode_creates_missing_indexes(self, sqlite_pool):
        """update 模式：为已存在的表创建缺失的索引"""
        # 先用无索引的实体建表
        @entity("sys_user")
        class UserPlain:
            def __init__(self, id: int = None, username: str = "",
                         email: str = "", age: int = 0, status: int = 1):
                self.id = id
                self.username = username
                self.email = email
                self.age = age
                self.status = status

        ddl1 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl1.register_entity(UserPlain)
        ddl1.execute()

        # 用带索引的 User 执行 update
        ddl2 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='update')
        ddl2.register_entity(User)
        ddl2.execute()

        indexes = ddl2._get_existing_indexes('sys_user')
        assert 'idx_user_username' in indexes
        assert 'idx_user_email' in indexes

    def test_update_mode_creates_table_when_missing(self, sqlite_pool):
        """update 模式：表不存在时直接创建"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='update')
        ddl.register_entity(Role)
        sqls = ddl.execute()

        assert any('CREATE TABLE' in s for s in sqls)
        assert ddl._table_exists('sys_role')

    def test_validate_mode_passes_for_matching_schema(self, sqlite_pool):
        """validate 模式：结构匹配时通过"""
        ddl1 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl1.register_entity(User)
        ddl1.execute()

        ddl2 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='validate')
        ddl2.register_entity(User)
        # 不抛异常即通过
        ddl2.execute()

    def test_validate_mode_raises_for_missing_column(self, sqlite_pool):
        """validate 模式：缺失列时抛异常"""
        ddl1 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl1.register_entity(User)
        ddl1.execute()

        @entity("sys_user")
        class UserBad:
            def __init__(self, id: int = None, nonexistent_column: str = ""):
                self.id = id
                self.nonexistent_column = nonexistent_column

        ddl2 = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='validate')
        ddl2.register_entity(UserBad)
        with pytest.raises(Exception):
            ddl2.execute()

    def test_validate_mode_raises_for_missing_table(self, sqlite_pool):
        """validate 模式：表不存在时抛异常"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='validate')
        ddl.register_entity(User)
        with pytest.raises(Exception):
            ddl.execute()

    def test_create_drop_mode_drops_on_shutdown(self, sqlite_pool):
        """create-drop 模式：drop_all 关闭时删除所有表"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create-drop')
        ddl.register_entities([User, Role])
        ddl.execute()
        assert ddl._table_exists('sys_user')

        ddl.drop_all()
        assert not ddl._table_exists('sys_user')
        assert not ddl._table_exists('sys_role')


# ==================== 实体/类型/SQL 生成测试 ====================

class TestEntityParsingAndSql:
    def test_dataclass_entity_support(self, sqlite_pool):
        """支持 dataclass 风格实体"""
        from dataclasses import dataclass

        @dataclass
        @entity("product")
        class Product:
            id: int = None
            name: str = ""
            price: float = 0.0
            in_stock: bool = True

        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='create')
        ddl.register_entity(Product)
        ddl.execute()

        cols = ddl._get_existing_columns('product')
        assert 'name' in cols
        assert 'price' in cols
        assert 'in_stock' in cols

    def test_mysql_dialect_sql_generation(self, sqlite_pool):
        """MySQL 方言 SQL：含 AUTO_INCREMENT / ENGINE=InnoDB / COMMENT"""
        ddl = DdlAutoManager(sqlite_pool, dialect='mysql', mode='none')
        ddl.register_entity(User)
        ddl._parsed = [ddl._parse_entity(User)]
        sql = ddl._build_create_table_sql(ddl._parsed[0])

        assert 'CREATE TABLE' in sql
        assert 'AUTO_INCREMENT' in sql
        assert 'ENGINE=InnoDB' in sql
        assert 'COMMENT' in sql

    def test_postgresql_dialect_sql_generation(self, sqlite_pool):
        """PostgreSQL 方言 SQL：主键使用 SERIAL 系列 + COMMENT ON TABLE"""
        ddl = DdlAutoManager(sqlite_pool, dialect='postgresql', mode='none')
        ddl.register_entity(User)
        ddl._parsed = [ddl._parse_entity(User)]
        sql = ddl._build_create_table_sql(ddl._parsed[0])

        assert 'CREATE TABLE' in sql
        # 主键自增列使用 SERIAL / BIGSERIAL
        assert 'SERIAL' in sql
        # id 列标记为 NOT NULL 主键
        assert 'NOT NULL' in sql
        # 表注释通过 COMMENT ON TABLE 单独声明
        assert 'COMMENT ON TABLE' in sql

    def test_camel_to_snake_conversion(self):
        """驼峰转下划线"""
        assert _camel_to_snake('UserRole') == 'user_role'
        assert _camel_to_snake('sysUser') == 'sys_user'
        assert _camel_to_snake('simple') == 'simple'

    def test_type_mapping_for_dialects(self):
        """Python 类型映射到各方言 SQL 类型"""
        assert _get_sql_type(int, 'mysql') == 'BIGINT'
        assert _get_sql_type(str, 'mysql') == 'VARCHAR(255)'
        assert _get_sql_type(bool, 'mysql') == 'TINYINT(1)'
        assert _get_sql_type(float, 'postgresql') == 'DOUBLE PRECISION'
        assert _get_sql_type(int, 'sqlite') == 'INTEGER'
        assert _get_sql_type(str, 'sqlite') == 'TEXT'
        # 自定义长度
        assert _get_sql_type(str, 'mysql', {'length': 64}) == 'VARCHAR(64)'
        # column_definition 覆盖
        assert _get_sql_type(str, 'mysql',
                             {'column_definition': 'TEXT'}) == 'TEXT'

    def test_entity_decorator_sets_metadata(self):
        """@entity 装饰器标记类元数据"""
        @entity("custom_tab", comment="c")
        class Custom:
            def __init__(self, id: int = None):
                self.id = id

        assert getattr(Custom, '__entity__') is True
        assert Custom.__table__.name == 'custom_tab'
        assert Custom.__table__.comment == 'c'

    def test_entity_is_exported_with_spring_style_name(self):
        from springbootai.orm import Entity, entity as legacy_entity

        assert Entity is entity
        assert legacy_entity is Entity

        @Entity("uppercase_entity")
        class UppercaseEntity:
            id = Id()

        assert UppercaseEntity.__table__.name == "uppercase_entity"

    def test_entity_class_descriptors_survive_dynamic_init(self, sqlite_pool):
        from springbootai.orm import Entity

        @Entity("descriptor_entity")
        class DescriptorEntity:
            id = Id()
            welder_no = Column(nullable=False, length=40)
            score = Column(nullable=True)

            def __init__(self, id: int = None, welder_no: str = "", score: float = None):
                for name, value in locals().copy().items():
                    if name != "self":
                        setattr(self, name, value)

        ddl = DdlAutoManager(sqlite_pool, dialect="sqlite", mode="create")
        ddl.register_entity(DescriptorEntity)
        ddl.execute()

        columns = ddl._get_existing_columns("descriptor_entity")
        assert set(columns) == {"id", "welder_no", "score"}
        parsed = ddl._parse_entity(DescriptorEntity)
        metadata = {column["name"]: column for column in parsed.columns}
        assert metadata["id"]["sql_type"] == "INTEGER"
        assert metadata["score"]["sql_type"] == "REAL"

    def test_entity_generates_keyword_constructor(self):
        from springbootai.orm import Entity

        @Entity("simple_entity")
        class SimpleEntity:
            id: int = Id()
            name: str = Column(nullable=False)
            enabled: bool = Column(nullable=False, default=True)

        row = SimpleEntity(name="welder")

        assert row.id is None
        assert row.name == "welder"
        assert row.enabled is True
        with pytest.raises(TypeError, match="unknown"):
            SimpleEntity(unknown="value")


def test_init_ddl_auto_does_not_mutate_pool_connection_config(sqlite_pool):
    before = dict(sqlite_pool.config)

    manager = init_ddl_auto(sqlite_pool, {"driver": "sqlite", "ddl-auto": {"mode": "update"}})

    assert manager is not None
    assert sqlite_pool.config == before

    def test_table_alias_works_like_entity(self):
        """@table 是 @entity 的别名"""
        @table("alias_tab")
        class Alias:
            def __init__(self, id: int = None):
                self.id = id

        assert getattr(Alias, '__entity__') is True
        assert Alias.__table__.name == 'alias_tab'

    def test_id_and_column_descriptors(self):
        """Id / Column / column / id_column 描述符"""
        pk = Id(name="uid", auto_increment=True)
        assert pk.primary_key is True
        assert pk.auto_increment is True
        assert pk.nullable is False

        col = Column(name="email", nullable=False, unique=True, length=128)
        assert col.name == 'email'
        assert col.nullable is False
        assert col.unique is True
        assert col.length == 128

        # column 装饰器
        @column(name="renamed")
        def field():
            pass
        assert hasattr(field, '__column__')
        assert field.__column__.name == 'renamed'

        # id_column 装饰器
        @id_column()
        def pk_field():
            pass
        assert hasattr(pk_field, '__column__')
        assert pk_field.__column__.primary_key is True


# ==================== 注册/集成测试 ====================

class TestRegistrationAndIntegration:
    def test_register_entity_dedup(self, sqlite_pool):
        """register_entity / register_entities 去重"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='none')
        ddl.register_entity(User)
        ddl.register_entity(User)
        ddl.register_entities([User, Role])
        assert ddl._entities == [User, Role]

    def test_get_generated_and_executed_sql(self, sqlite_pool):
        """get_generated_sql / get_executed_sql"""
        ddl = DdlAutoManager(sqlite_pool, dialect='sqlite', mode='none')
        ddl.register_entity(User)

        generated = ddl.get_generated_sql()
        assert len(generated) == 1
        assert 'CREATE TABLE' in generated[0]

        # none 模式执行后 executed_sql 为空
        ddl.execute()
        assert ddl.get_executed_sql() == []

    def test_init_ddl_auto_from_config(self, tmp_path):
        """init_ddl_auto 配置驱动初始化"""
        db_path = str(tmp_path / "cfg.db")
        pool = create_connection_pool('sqlite', {
            'driver': 'sqlite',
            'database': db_path,
        })
        try:
            from springbootai.orm import ddl_auto
            ddl_auto._global_ddl_manager = None

            manager = DdlAutoManager(pool, dialect='sqlite', mode='create')
            manager.register_entity(User)
            manager.execute()
            assert manager._table_exists('sys_user')

            # init_ddl_auto 在 none 模式下返回 None
            result = init_ddl_auto(pool, {
                'driver': 'sqlite',
                'ddl-auto': {'mode': 'none'},
            })
            assert result is None
        finally:
            try:
                pool.close()
            except Exception:
                pass


if __name__ == '__main__':
    import pytest as _pytest
    _pytest.main([__file__, "-v", "--tb=short"])
