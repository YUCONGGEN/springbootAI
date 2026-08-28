"""Regression tests for security-sensitive parsing and serialization paths."""

import pytest

from springbootai.orm.ddl_auto import DdlAutoManager
from springbootai.orm.pymybatis import build_session_factory
from springbootai.orm.pymybatis.cache.redis_cache import RedisSecondLevelCache
from springbootai.orm.pymybatis.dynamic_sql import DynamicSQLProcessor, SecurityError
from springbootai.orm.pymybatis.interceptor import (
    InterceptorSecurityError,
    Invocation,
    SecurityInterceptor,
)
from springbootai.orm.pymybatis.xml_parser import XmlParser
from springbootai.cloud.seata import SeataTransactionManager
from springbootai.data import Order, Sort
from springbootai.orm.migration import MigrationManager


def test_ddl_source_defaults_accept_literals_without_executing_calls():
    class LiteralEntity:
        def __init__(self):
            self.name = "safe"
            self.tags = ["a", "b"]
            self.payload = __import__("os").getcwd()

    fields = DdlAutoManager(None)._extract_init_fields(LiteralEntity)

    assert fields["name"] == "safe"
    assert fields["tags"] == ["a", "b"]
    assert fields["payload"] == ""


def test_dynamic_sql_interpreter_supports_ognl_subset():
    processor = DynamicSQLProcessor()
    params = {
        "user": {"age": 21, "name": "alice"},
        "roles": ["admin", "reader"],
    }

    assert processor._evaluate_expression(
        "user.age >= 18 and user.name != null and 'admin' in roles",
        params,
    )
    assert processor._evaluate_value_expression("'%' + user.name + '%'", params) == "%alice%"


def test_dynamic_sql_interpreter_rejects_function_and_dunder_access():
    processor = DynamicSQLProcessor()

    with pytest.raises(SecurityError):
        processor._evaluate_value_expression("__import__('os')", {})
    with pytest.raises(SecurityError):
        processor._evaluate_value_expression("value.__class__", {"value": "x"})


def test_prepared_parameters_are_data_even_when_they_look_like_sql():
    """SQL-like business text must remain safe when bound through ``#{}``."""
    factory = build_session_factory({
        "datasource": {"driver": "sqlite", "database": ":memory:"},
        "pool": {"min_size": 1, "max_size": 1},
        "security": {
            "block_ddl": False,
            "sql_injection_detection": True,
            "sensitive_data_masking": False,
        },
    })
    session = factory.open_session()
    payloads = [
        "O'Reilly -- database handbook",
        "The expression 1 OR 1=1 is always true",
        "x'); DROP TABLE notes; --",
        "UNION SELECT is a SQL concept",
    ]
    try:
        connection = session.get_connection()
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        connection.commit()

        for index, body in enumerate(payloads, start=1):
            session.insert(
                "INSERT INTO notes(id, body) VALUES (#{id}, #{body})",
                {"id": index, "body": body},
            )

        rows = session.select("SELECT body FROM notes ORDER BY id", use_cache=False)
        assert [row["body"] for row in rows] == payloads
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='notes'"
        ).fetchone()[0] == 1
    finally:
        session.close()
        factory.close()


def test_security_interceptor_does_not_scan_prepared_parameter_values():
    invocation = Invocation(
        target=None,
        method="insert",
        args=(
            "INSERT INTO notes(body) VALUES (#{body})",
            {"body": "x'); DROP TABLE notes; --"},
        ),
        proceed=lambda: "executed with a bound value",
    )

    assert SecurityInterceptor().intercept(invocation) == "executed with a bound value"


def test_security_interceptor_keeps_ddl_structure_policy():
    invocation = Invocation(
        target=None,
        method="execute",
        args=("DROP TABLE notes", {}),
        proceed=lambda: "must not execute",
    )

    with pytest.raises(InterceptorSecurityError, match="DDL"):
        SecurityInterceptor().intercept(invocation)


def test_raw_sql_parameters_require_a_full_identifier_match():
    processor = DynamicSQLProcessor(placeholder="?")
    processor.enable_raw_params(True)
    processor.set_raw_param_whitelist({"table"})
    processor.add_raw_param_pattern(r"[a-z_]+")

    sql, values = processor.process("SELECT * FROM ${table}", {"table": "notes"})
    assert sql == "SELECT * FROM notes"
    assert values == []

    with pytest.raises(SecurityError):
        processor.process(
            "SELECT * FROM ${table}",
            {"table": "notes; DROP TABLE notes; --"},
        )


def test_redis_cache_rejects_pickle_serialization_before_connecting():
    with pytest.raises(ValueError, match="pickle.*disabled"):
        RedisSecondLevelCache(serialization="pickle")


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE mapper SYSTEM "file:///etc/passwd"><mapper namespace="bad"/>',
        '<!DOCTYPE mapper [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<mapper namespace="bad"><sql id="x">&xxe;</sql></mapper>',
    ],
)
def test_xml_mapper_rejects_dtd_and_entities(xml):
    with pytest.raises(ValueError, match="XML"):
        XmlParser().parse_string(xml)


def test_xml_mapper_accepts_official_mybatis_dtd_without_resolving_it():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
      "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
    <mapper namespace="tests.SafeMapper">
      <select id="findAll">SELECT 1</select>
    </mapper>'''

    parser = XmlParser()
    parser.parse_string(xml)

    assert parser.get_mapped_statement("tests.SafeMapper.findAll") is not None


def test_seata_callback_url_is_fail_closed_and_allowlisted(tmp_path):
    manager = SeataTransactionManager()
    manager.stop_recovery_worker()
    manager._cleanup_context()
    manager.configure(
        mode="http",
        store_path=str(tmp_path / "seata.sqlite3"),
        recovery_interval_s=0,
        callback_allowed_hosts=["*.internal", "127.0.0.1"],
    )
    try:
        xid = manager.begin_transaction(name="callback-policy")
        manager.register_branch(xid, callback_url="https://orders.internal/seata/branch")
        with pytest.raises(ValueError, match=r"HTTP\(S\)"):
            manager.register_branch(xid, callback_url="file:///etc/passwd")
        with pytest.raises(ValueError, match="not allow-listed"):
            manager.register_branch(xid, callback_url="http://169.254.169.254/latest")
        with pytest.raises(ValueError, match="credentials"):
            manager.register_branch(xid, callback_url="http://user:pass@orders.internal/callback")
    finally:
        manager._cleanup_context()
        manager.set_mode("local")
        manager._transaction_store = None
        manager._transaction_store_path = ""


def test_repository_rejects_unknown_sort_property():
    from tests.test_data_repository import User, _Pool
    from springbootai.data import PagingAndSortingRepository
    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        repository = PagingAndSortingRepository(_Pool(connection), User, dialect="sqlite")
        with pytest.raises(ValueError, match="unknown repository property"):
            repository._sort_sql(Sort(Order.asc('name"; DROP TABLE users; --')))
    finally:
        connection.close()


def test_migration_table_name_must_be_a_simple_identifier():
    with pytest.raises(ValueError, match="simple SQL identifier"):
        MigrationManager(None, ".", table_name="history; DROP TABLE users")
