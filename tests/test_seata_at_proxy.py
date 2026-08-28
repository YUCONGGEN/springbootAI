"""
Seata AT 数据源代理测试

验证：
1. SQL 解析（parse_sql）
2. undo_log 表创建和 CRUD
3. undo 回滚（INSERT→DELETE, UPDATE→UPDATE before, DELETE→INSERT before）
4. AT 拦截器记录 before/after image
5. 提交时删除 undo_log
"""
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock

from springbootai.cloud.seata_at_proxy import (
    SeataATProxy,
    SeataATInterceptor,
    UndoLogManager,
    UndoExecutor,
    parse_sql,
    _SQL_TYPE_UPDATE,
    _SQL_TYPE_DELETE,
    _SQL_TYPE_INSERT,
    SeataATUnsupportedSQLError,
)


class _MockSeataManager:
    """模拟 SeataTransactionManager，仅提供 AT 拦截器需要的接口。"""

    def __init__(self, xid: str = "test-xid-001"):
        self._xid = xid
        self._in_tx = False
        self._branches = []
        self._lock = threading.Lock()

    def is_in_transaction(self) -> bool:
        return self._in_tx

    def get_current_tx_id(self) -> str:
        return self._xid

    def begin(self):
        self._in_tx = True

    def end(self):
        self._in_tx = False

    def register_branch(self, xid, branch_id="", resource_id="",
                        callback_url="", commit_cb=None, rollback_cb=None,
                        service_name="", metadata=None):
        with self._lock:
            self._branches.append({
                "xid": xid,
                "branch_id": branch_id,
                "commit_cb": commit_cb,
                "rollback_cb": rollback_cb,
            })
        return branch_id

    def commit_all(self):
        """模拟全局事务提交：调用所有分支的 commit 回调。"""
        with self._lock:
            for b in self._branches:
                if b["commit_cb"]:
                    b["commit_cb"](b["xid"], b["branch_id"])
            self._branches.clear()
            self._in_tx = False

    def rollback_all(self):
        """模拟全局事务回滚：调用所有分支的 rollback 回调。"""
        with self._lock:
            for b in self._branches:
                if b["rollback_cb"]:
                    b["rollback_cb"](b["xid"], b["branch_id"])
            self._branches.clear()
            self._in_tx = False


class _MockSqlSession:
    """模拟 SqlSession，持有 sqlite3 连接和拦截器链。"""

    def __init__(self, conn: sqlite3.Connection):
        self.connection = conn
        self._in_transaction = False
        self.interceptor_chain = MagicMock()
        self.interceptor_chain.add_interceptor = MagicMock()

    @property
    def in_transaction(self):
        return self._in_transaction

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN")
        self._in_transaction = True
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            self._in_transaction = False


def _create_test_db() -> sqlite3.Connection:
    """创建测试数据库（SQLite，模拟业务表）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # SQLite 用 ? 而非 %s 作为占位符
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS `account` (
            id INTEGER PRIMARY KEY,
            name TEXT,
            balance REAL
        );
        INSERT INTO `account` (id, name, balance) VALUES (1, 'Alice', 100.0);
        INSERT INTO `account` (id, name, balance) VALUES (2, 'Bob', 200.0);
        INSERT INTO `account` (id, name, balance) VALUES (3, 'Carol', 300.0);
    """)
    conn.commit()
    return conn


class TestParseSql(unittest.TestCase):
    """测试 SQL 解析。"""

    def test_parse_update_with_where(self):
        sql_type, table, where = parse_sql(
            "UPDATE `account` SET balance = 50 WHERE id = 1"
        )
        self.assertEqual(sql_type, _SQL_TYPE_UPDATE)
        self.assertEqual(table, "account")
        self.assertEqual(where, "id = 1")

    def test_parse_update_no_where(self):
        sql_type, table, where = parse_sql(
            "UPDATE account SET balance = 0"
        )
        self.assertEqual(sql_type, _SQL_TYPE_UPDATE)
        self.assertEqual(table, "account")
        self.assertEqual(where, "")

    def test_parse_delete_with_where(self):
        sql_type, table, where = parse_sql(
            "DELETE FROM account WHERE id = 2"
        )
        self.assertEqual(sql_type, _SQL_TYPE_DELETE)
        self.assertEqual(table, "account")
        self.assertEqual(where, "id = 2")

    def test_parse_insert(self):
        sql_type, table, where = parse_sql(
            "INSERT INTO account (id, name, balance) VALUES (4, 'Dave', 400)"
        )
        self.assertEqual(sql_type, _SQL_TYPE_INSERT)
        self.assertEqual(table, "account")
        self.assertEqual(where, "")

    def test_parse_select_returns_empty(self):
        sql_type, table, where = parse_sql("SELECT * FROM account")
        self.assertEqual(sql_type, "")
        self.assertEqual(table, "")

    def test_parse_with_trailing_semicolon(self):
        sql_type, table, where = parse_sql(
            "DELETE FROM account WHERE id = 1;"
        )
        self.assertEqual(sql_type, _SQL_TYPE_DELETE)
        self.assertEqual(table, "account")


class TestUndoLogManager(unittest.TestCase):
    """测试 undo_log 表管理。"""

    def setUp(self):
        self.conn = _create_test_db()
        self.manager = UndoLogManager(None)

    def tearDown(self):
        self.conn.close()

    def test_ensure_table_creates_undo_log(self):
        self.manager.ensure_table(self.conn)
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='undo_log'"
        )
        self.assertIsNotNone(cursor.fetchone())

    def test_insert_and_select(self):
        self.manager.ensure_table(self.conn)
        self.manager.insert(
            self.conn, "b1", "x1", "account", "UPDATE",
            [{"id": 1, "balance": 100}], [{"id": 1, "balance": 50}],
        )
        record = self.manager.select(self.conn, "b1")
        self.assertIsNotNone(record)
        self.assertEqual(record["table_name"], "account")
        self.assertEqual(record["sql_type"], "UPDATE")
        self.assertEqual(record["before_image"][0]["balance"], 100)

    def test_delete(self):
        self.manager.ensure_table(self.conn)
        self.manager.insert(
            self.conn, "b2", "x2", "account", "DELETE", [{"id": 1}], []
        )
        self.manager.delete(self.conn, "b2")
        self.assertIsNone(self.manager.select(self.conn, "b2"))


class TestUndoExecutor(unittest.TestCase):
    """测试 undo 反向恢复。"""

    def setUp(self):
        self.conn = _create_test_db()

    def tearDown(self):
        self.conn.close()

    def test_undo_insert_deletes_row(self):
        """INSERT 的 undo = DELETE after image"""
        self.conn.execute(
            "INSERT INTO account (id, name, balance) VALUES (5, 'Eve', 500)"
        )
        self.conn.commit()
        after = [{"id": 5, "name": "Eve", "balance": 500.0}]
        UndoExecutor.undo(self.conn, "account", _SQL_TYPE_INSERT, None, after)
        row = self.conn.execute("SELECT * FROM account WHERE id = 5").fetchone()
        self.assertIsNone(row)

    def test_undo_update_restores_before(self):
        """UPDATE 的 undo = 用 before image 覆盖"""
        self.conn.execute("UPDATE account SET balance = 50 WHERE id = 1")
        self.conn.commit()
        before = [{"id": 1, "name": "Alice", "balance": 100.0}]
        after = [{"id": 1, "name": "Alice", "balance": 50.0}]
        UndoExecutor.undo(self.conn, "account", _SQL_TYPE_UPDATE, before, after)
        row = self.conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        self.assertEqual(row["balance"], 100.0)

    def test_undo_delete_reinserts_before(self):
        """DELETE 的 undo = INSERT before image"""
        self.conn.execute("DELETE FROM account WHERE id = 2")
        self.conn.commit()
        before = [{"id": 2, "name": "Bob", "balance": 200.0}]
        UndoExecutor.undo(self.conn, "account", _SQL_TYPE_DELETE, before, None)
        row = self.conn.execute("SELECT * FROM account WHERE id = 2").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Bob")
        self.assertEqual(row["balance"], 200.0)


class TestSeataATProxy(unittest.TestCase):
    """测试 AT 代理集成。"""

    def test_install_registers_interceptor(self):
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager()
        proxy = SeataATProxy(session, seata)
        proxy.install()
        session.interceptor_chain.add_interceptor.assert_called_once()
        self.assertTrue(proxy.is_installed())
        conn.close()

    def test_manual_undo_restores_data(self):
        """手动 undo 能恢复数据。"""
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager()
        proxy = SeataATProxy(session, seata)
        proxy.install()

        # 手动插入 undo_log 记录
        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        undo.insert(
            conn, "manual-1", "x1", "account", _SQL_TYPE_UPDATE,
            [{"id": 1, "name": "Alice", "balance": 100.0}],
            [{"id": 1, "name": "Alice", "balance": 50.0}],
        )
        # 修改数据
        conn.execute("UPDATE account SET balance = 50 WHERE id = 1")
        conn.commit()

        # 手动 undo
        self.assertTrue(proxy.manual_undo("manual-1"))
        row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        self.assertEqual(row["balance"], 100.0)
        conn.close()


class TestSeataATInterceptor(unittest.TestCase):
    """测试 AT 拦截器的记录逻辑。"""

    def test_non_transaction_passthrough(self):
        """非事务中直接透传，不记录 undo。"""
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager()
        # 不 begin，不在事务中
        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)

        # 模拟 Invocation
        invocation = MagicMock()
        invocation.get_method.return_value = "update"
        invocation.get_args.return_value = (
            "UPDATE account SET balance = 50 WHERE id = 1", {}
        )
        invocation.proceed.return_value = 1

        result = interceptor.intercept(invocation)

        # 应该透传，不记录 undo
        invocation.proceed.assert_called_once()
        # undo_log 表不应该有记录
        undo.ensure_table(conn)
        record = undo.select(conn, "at-")
        self.assertIsNone(record)
        conn.close()

    def test_records_before_image_on_update(self):
        """事务中 UPDATE 记录 before image。"""
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager("xid-test")
        seata.begin()

        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)

        # 模拟 Invocation：UPDATE account SET balance = 50 WHERE id = 1
        def proceed():
            conn.execute("UPDATE account SET balance = 50 WHERE id = 1")
            return 1

        invocation = MagicMock()
        invocation.get_method.return_value = "update"
        invocation.get_args.return_value = (
            "UPDATE account SET balance = 50 WHERE id = 1", {}
        )
        invocation.proceed.side_effect = proceed

        interceptor.intercept(invocation)

        # 验证 undo_log 有记录
        records = conn.execute("SELECT * FROM undo_log").fetchall()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["table_name"], "account")
        self.assertEqual(record["sql_type"], "UPDATE")
        before = json.loads(record["before_image"])
        self.assertEqual(before[0]["balance"], 100.0)  # 原始值
        after = json.loads(record["after_image"])
        self.assertEqual(after[0]["balance"], 50.0)  # 修改后值

        # 验证注册了分支
        self.assertEqual(len(seata._branches), 1)

        # 模拟全局回滚
        seata.rollback_all()

        # 数据应该恢复
        row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        self.assertEqual(row["balance"], 100.0)

        # undo_log 应该被删除
        records = conn.execute("SELECT * FROM undo_log").fetchall()
        self.assertEqual(len(records), 0)
        conn.close()

    def test_records_before_image_on_delete(self):
        """事务中 DELETE 记录 before image，回滚恢复。"""
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager("xid-del")
        seata.begin()

        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)

        def proceed():
            conn.execute("DELETE FROM account WHERE id = 3")
            return 1

        invocation = MagicMock()
        invocation.get_method.return_value = "delete"
        invocation.get_args.return_value = (
            "DELETE FROM account WHERE id = 3", {}
        )
        invocation.proceed.side_effect = proceed

        interceptor.intercept(invocation)

        # 验证 before image 记录了 Carol
        records = conn.execute("SELECT * FROM undo_log").fetchall()
        self.assertEqual(len(records), 1)
        before = json.loads(records[0]["before_image"])
        self.assertEqual(before[0]["name"], "Carol")
        self.assertEqual(before[0]["balance"], 300.0)

        # 全局回滚
        seata.rollback_all()

        # Carol 应该恢复
        row = conn.execute("SELECT * FROM account WHERE id = 3").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Carol")
        conn.close()

    def test_commit_deletes_undo_log(self):
        """全局提交时删除 undo_log。"""
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager("xid-commit")
        seata.begin()

        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)

        def proceed():
            conn.execute("UPDATE account SET balance = 999 WHERE id = 1")
            return 1

        invocation = MagicMock()
        invocation.get_method.return_value = "update"
        invocation.get_args.return_value = (
            "UPDATE account SET balance = 999 WHERE id = 1", {}
        )
        invocation.proceed.side_effect = proceed

        interceptor.intercept(invocation)

        # 有 undo_log
        self.assertEqual(len(conn.execute("SELECT * FROM undo_log").fetchall()), 1)

        # 全局提交
        seata.commit_all()

        # undo_log 被删除
        self.assertEqual(len(conn.execute("SELECT * FROM undo_log").fetchall()), 0)
        # 数据保持修改后的值
        row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        self.assertEqual(row["balance"], 999.0)
        conn.close()

    def test_parameterized_update_uses_only_where_parameters_for_image(self):
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager("xid-params")
        seata.begin()
        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)

        invocation = MagicMock()
        invocation.get_method.return_value = "update"
        invocation.get_args.return_value = (
            "UPDATE account SET balance = ? WHERE id = ?", (25, 2)
        )
        invocation.proceed.side_effect = lambda: conn.execute(
            "UPDATE account SET balance = ? WHERE id = ?", (25, 2)
        ).rowcount

        self.assertEqual(interceptor.intercept(invocation), 1)
        record = conn.execute("SELECT * FROM undo_log").fetchone()
        before = json.loads(record["before_image"])
        self.assertEqual(before, [{"id": 2, "name": "Bob", "balance": 200.0}])
        seata.rollback_all()
        self.assertEqual(
            conn.execute("SELECT balance FROM account WHERE id = 2").fetchone()[0],
            200.0,
        )
        conn.close()

    def test_unsafe_write_fails_closed_without_executing_business_sql(self):
        conn = _create_test_db()
        session = _MockSqlSession(conn)
        seata = _MockSeataManager("xid-unsafe")
        seata.begin()
        undo = UndoLogManager(None)
        undo.ensure_table(conn)
        interceptor = SeataATInterceptor(seata, session, undo)
        invocation = MagicMock()
        invocation.get_method.return_value = "update"
        invocation.get_args.return_value = ("UPDATE account SET balance = 0", {})

        with self.assertRaises(SeataATUnsupportedSQLError):
            interceptor.intercept(invocation)
        invocation.proceed.assert_not_called()
        conn.close()


if __name__ == "__main__":
    unittest.main()
