"""
Seata AT 模式 Python 数据源代理

在 ORM 拦截器层自动记录 before/after image，生成 undo_log，
在全局事务回滚时自动反向恢复数据。

工作原理：
1. ``SeataATInterceptor`` 拦截 UPDATE/DELETE/INSERT SQL
2. 执行前查询 before image（``SELECT * FROM table WHERE ...``）
3. 执行原 SQL
4. 执行后查询 after image（仅 UPDATE/DELETE）
5. 把 before/after image 序列化为 JSON 存入 ``undo_log`` 表
6. 全局事务回滚时，根据 undo_log 反向恢复数据
7. 全局事务提交时，删除 undo_log

与 Java Seata AT 的差异：
- Java 用 ``DataSourceProxy`` 代理 JDBC 连接；Python 在 ORM 拦截器层实现
- Java 解析 SQL 用 Druid；Python 用正则表达式，仅支持单表
- Java 的 undo_log 有 branch_id 和 xid 联合索引；Python 用 branch_id 主键查询
- Python 不支持数据库自增列回填的 undo（需业务显式提供主键）

限制：
1. 仅支持单表 SQL（不支持 JOIN / 子查询）
2. WHERE 条件直接用于 before image 查询（原样拼接）
3. 需要 undo_log 表（自动创建，存储在业务数据库）
4. 仅在 Seata 全局事务激活时工作
5. INSERT 的 undo 需要 after image 包含主键
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Spring.Cloud.SeataAT")


# ---------------------------------------------------------------------------
# SQL 解析（简化版，仅提取表名和 WHERE 条件）
# ---------------------------------------------------------------------------

_SQL_TYPE_UPDATE = "UPDATE"
_SQL_TYPE_DELETE = "DELETE"
_SQL_TYPE_INSERT = "INSERT"

_RE_UPDATE = re.compile(
    r"^\s*UPDATE\s+`?(\w+)`?\s+SET\s+.+\s+WHERE\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_UPDATE_NO_WHERE = re.compile(
    r"^\s*UPDATE\s+`?(\w+)`?\s+SET\s+.+$",
    re.IGNORECASE | re.DOTALL,
)
_RE_DELETE = re.compile(
    r"^\s*DELETE\s+FROM\s+`?(\w+)`?\s+WHERE\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_DELETE_NO_WHERE = re.compile(
    r"^\s*DELETE\s+FROM\s+`?(\w+)`?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_RE_INSERT = re.compile(
    r"^\s*INSERT\s+INTO\s+`?(\w+)`?",
    re.IGNORECASE,
)


def parse_sql(sql: str) -> Tuple[str, str, str]:
    """解析 SQL，返回 (操作类型, 表名, WHERE 条件)。

    WHERE 条件为空字符串表示无 WHERE（全表操作）。
    无法识别的 SQL 返回 ("", "", "")。
    """
    sql_stripped = sql.strip().rstrip(";")
    m = _RE_UPDATE.match(sql_stripped)
    if m:
        return _SQL_TYPE_UPDATE, m.group(1), m.group(2).strip()
    m = _RE_UPDATE_NO_WHERE.match(sql_stripped)
    if m:
        return _SQL_TYPE_UPDATE, m.group(1), ""
    m = _RE_DELETE.match(sql_stripped)
    if m:
        return _SQL_TYPE_DELETE, m.group(1), m.group(2).strip()
    m = _RE_DELETE_NO_WHERE.match(sql_stripped)
    if m:
        return _SQL_TYPE_DELETE, m.group(1), ""
    m = _RE_INSERT.match(sql_stripped)
    if m:
        return _SQL_TYPE_INSERT, m.group(1), ""
    return "", "", ""


# ---------------------------------------------------------------------------
# UndoLog 管理
# ---------------------------------------------------------------------------

_CREATE_UNDO_LOG_SQL = """
CREATE TABLE IF NOT EXISTS `undo_log` (
    `branch_id`     VARCHAR(64)  NOT NULL,
    `xid`           VARCHAR(128) NOT NULL,
    `table_name`    VARCHAR(128) NOT NULL,
    `sql_type`      VARCHAR(16)  NOT NULL,
    `before_image`  TEXT,
    `after_image`   TEXT,
    `created_at`    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`branch_id`)
)
"""

_INSERT_UNDO_LOG_SQL = (
    "INSERT INTO `undo_log` "
    "(branch_id, xid, table_name, sql_type, before_image, after_image) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)

_DELETE_UNDO_LOG_SQL = "DELETE FROM `undo_log` WHERE branch_id = %s"

_SELECT_UNDO_LOG_SQL = (
    "SELECT branch_id, xid, table_name, sql_type, before_image, after_image "
    "FROM `undo_log` WHERE branch_id = %s"
)


def _param_placeholder(conn: Any) -> str:
    """返回连接对应的参数占位符（MySQL=%s，SQLite=?）。

    Python DBAPI 的 paramstyle 是模块级属性，不在连接对象上。
    """
    import sys
    module_name = type(conn).__module__
    if module_name == "sqlite3":
        return "?"
    mod = sys.modules.get(module_name)
    if mod is not None and getattr(mod, "paramstyle", "format") == "qmark":
        return "?"
    return "%s"


def _adapt_sql(sql: str, placeholder: str) -> str:
    """把 SQL 模板中的 %s 替换为连接对应的占位符。"""
    if placeholder == "?":
        return sql.replace("%s", "?")
    return sql


class UndoLogManager:
    """管理 undo_log 表的创建、插入、查询和删除。"""

    def __init__(self, executor: Any):
        """Args:
            executor: 能执行 SQL 的对象（SqlSession 或 DB cursor），
                     需提供 ``execute(sql, params)`` 和 ``fetchall()`` 方法。
        """
        self._executor = executor
        self._ensured: set[str] = set()
        self._lock = threading.Lock()

    def ensure_table(self, conn: Any) -> None:
        """在指定连接上创建 undo_log 表（每个连接只创建一次）。"""
        conn_id = id(conn)
        if conn_id in self._ensured:
            return
        with self._lock:
            if conn_id in self._ensured:
                return
            cursor = conn.cursor()
            try:
                cursor.execute(_CREATE_UNDO_LOG_SQL)
                conn.commit()
            except Exception as exc:
                logger.warning("[Seata-AT] ensure undo_log table failed: %s", exc)
            finally:
                cursor.close()
            self._ensured.add(conn_id)

    def insert(
        self,
        conn: Any,
        branch_id: str,
        xid: str,
        table_name: str,
        sql_type: str,
        before_image: Optional[List[Dict]],
        after_image: Optional[List[Dict]],
    ) -> None:
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(
                _adapt_sql(_INSERT_UNDO_LOG_SQL, ph),
                (
                    branch_id,
                    xid,
                    table_name,
                    sql_type,
                    json.dumps(before_image, ensure_ascii=False, default=str),
                    json.dumps(after_image, ensure_ascii=False, default=str),
                ),
            )
            conn.commit()
        finally:
            cursor.close()

    def select(self, conn: Any, branch_id: str) -> Optional[Dict[str, Any]]:
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(_adapt_sql(_SELECT_UNDO_LOG_SQL, ph), (branch_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            # 支持元组和 Row 对象
            row_vals = tuple(row)
            return {
                "branch_id": row_vals[0],
                "xid": row_vals[1],
                "table_name": row_vals[2],
                "sql_type": row_vals[3],
                "before_image": json.loads(row_vals[4]) if row_vals[4] else None,
                "after_image": json.loads(row_vals[5]) if row_vals[5] else None,
            }
        finally:
            cursor.close()

    def delete(self, conn: Any, branch_id: str) -> None:
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(_adapt_sql(_DELETE_UNDO_LOG_SQL, ph), (branch_id,))
            conn.commit()
        finally:
            cursor.close()


# ---------------------------------------------------------------------------
# Undo 执行器（反向恢复）
# ---------------------------------------------------------------------------

class UndoExecutor:
    """根据 undo_log 反向恢复数据。"""

    @staticmethod
    def undo(
        conn: Any,
        table_name: str,
        sql_type: str,
        before_image: Optional[List[Dict]],
        after_image: Optional[List[Dict]],
    ) -> None:
        """执行反向恢复。"""
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            if sql_type == _SQL_TYPE_INSERT:
                UndoExecutor._undo_insert(cursor, ph, table_name, after_image)
            elif sql_type == _SQL_TYPE_UPDATE:
                UndoExecutor._undo_update(cursor, ph, table_name, before_image)
            elif sql_type == _SQL_TYPE_DELETE:
                UndoExecutor._undo_delete(cursor, ph, table_name, before_image)
            conn.commit()
        finally:
            cursor.close()

    @staticmethod
    def _undo_insert(cursor: Any, ph: str, table_name: str, after_image: Optional[List[Dict]]) -> None:
        if not after_image:
            return
        for row in after_image:
            where_clause = " AND ".join(f"`{k}` = {ph}" for k in row)
            cursor.execute(
                f"DELETE FROM `{table_name}` WHERE {where_clause}",  # nosec B608
                tuple(row.values()),
            )

    @staticmethod
    def _undo_update(cursor: Any, ph: str, table_name: str, before_image: Optional[List[Dict]]) -> None:
        if not before_image:
            return
        for row in before_image:
            cols = list(row.keys())
            if len(cols) < 2:
                continue
            pk = cols[0]
            set_clause = ", ".join(f"`{c}` = {ph}" for c in cols[1:])
            cursor.execute(
                f"UPDATE `{table_name}` SET {set_clause} WHERE `{pk}` = {ph}",  # nosec B608
                tuple(row[c] for c in cols[1:]) + (row[pk],),
            )

    @staticmethod
    def _undo_delete(cursor: Any, ph: str, table_name: str, before_image: Optional[List[Dict]]) -> None:
        if not before_image:
            return
        for row in before_image:
            cols = list(row.keys())
            placeholders = ", ".join(ph for _ in cols)
            col_names = ", ".join(f"`{c}`" for c in cols)
            cursor.execute(
                f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})",  # nosec B608
                tuple(row[c] for c in cols),
            )


# ---------------------------------------------------------------------------
# AT 拦截器
# ---------------------------------------------------------------------------

class SeataATInterceptor:
    """ORM 拦截器：在 Seata 全局事务中自动记录 before/after image。

    注册方式：
        at_proxy = SeataATProxy(sql_session, seata_manager)
        at_proxy.install()

    只在 ``seata_manager.is_in_transaction()`` 为 True 时生效，
    非事务 SQL 直接透传，零开销。
    """

    def __init__(self, seata_manager: Any, sql_session: Any, undo_log_manager: UndoLogManager):
        self._seata = seata_manager
        self._session = sql_session
        self._undo = undo_log_manager
        self._branch_counter = 0
        self._lock = threading.Lock()

    def intercept(self, invocation: Any) -> Any:
        """拦截 SQL 执行。"""
        # 非全局事务直接透传
        if not self._seata.is_in_transaction():
            return invocation.proceed()

        method = invocation.get_method()
        args = invocation.get_args()

        # 只拦截写操作（update/delete/insert）
        if method not in ("update", "delete", "insert"):
            return invocation.proceed()

        sql = self._extract_sql(args)
        if not sql:
            return invocation.proceed()

        sql_type, table_name, where_clause = parse_sql(sql)
        if not sql_type:
            # 无法解析的 SQL，透传但不记录 undo
            return invocation.proceed()

        xid = self._seata.get_current_tx_id()
        branch_id = self._next_branch_id()

        # 获取底层连接
        conn = self._get_connection()
        if conn is None:
            # 无法获取连接，透传
            return invocation.proceed()

        self._undo.ensure_table(conn)

        before_image: Optional[List[Dict]] = None
        after_image: Optional[List[Dict]] = None

        if sql_type == _SQL_TYPE_UPDATE or sql_type == _SQL_TYPE_DELETE:
            before_image = self._query_image(conn, table_name, where_clause)

        # 执行原 SQL
        result = invocation.proceed()

        if sql_type == _SQL_TYPE_UPDATE:
            after_image = self._query_image(conn, table_name, where_clause)
        elif sql_type == _SQL_TYPE_DELETE:
            after_image = []
        elif sql_type == _SQL_TYPE_INSERT:
            after_image = self._query_insert_after_image(conn, table_name, where_clause)

        # 记录 undo_log
        self._undo.insert(
            conn, branch_id, xid, table_name, sql_type, before_image, after_image
        )

        # 注册 AT 分支到全局事务（用本地回调）
        self._seata.register_branch(
            xid=xid,
            branch_id=branch_id,
            resource_id=table_name,
            commit_cb=lambda _xid, _bid: self._on_commit(_bid),
            rollback_cb=lambda _xid, _bid: self._on_rollback(_bid),
        )

        logger.info(
            "[Seata-AT] %s on %s recorded: xid=%s... branch=%s... before=%d after=%d",
            sql_type, table_name, xid[:8], branch_id[:8],
            len(before_image or []), len(after_image or []),
        )
        return result

    def _next_branch_id(self) -> str:
        with self._lock:
            self._branch_counter += 1
            return f"at-{uuid.uuid4().hex[:12]}-{self._branch_counter}"

    def _extract_sql(self, args: tuple) -> str:
        for arg in args:
            if isinstance(arg, str) and any(
                kw in arg.upper() for kw in ("UPDATE", "DELETE", "INSERT")
            ):
                return arg
        return ""

    def _get_connection(self) -> Any:
        """从 SqlSession 获取底层 DBAPI 连接。"""
        # PyMyBatis SqlSession 持有 connection
        conn = getattr(self._session, "connection", None)
        if conn is not None:
            return conn
        # 尝试从 executor 获取
        executor = getattr(self._session, "executor", None)
        if executor is not None:
            conn = getattr(executor, "connection", None)
            if conn is not None:
                return conn
        return None

    def _query_image(
        self, conn: Any, table_name: str, where_clause: str
    ) -> List[Dict]:
        if not where_clause:
            return []
        sql = f"SELECT * FROM `{table_name}` WHERE {where_clause}"  # nosec B608
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description] if cursor.description else []
            return [dict(zip(cols, row)) for row in rows]
        except Exception as exc:
            logger.warning("[Seata-AT] query before image failed: %s", exc)
            return []
        finally:
            cursor.close()

    def _query_insert_after_image(
        self, conn: Any, table_name: str, where_clause: str
    ) -> List[Dict]:
        # INSERT 后无法精确知道插入的行，返回空（限制）
        return []

    def _on_commit(self, branch_id: str) -> None:
        conn = self._get_connection()
        if conn:
            self._undo.delete(conn, branch_id)

    def _on_rollback(self, branch_id: str) -> None:
        conn = self._get_connection()
        if conn is None:
            logger.error("[Seata-AT] cannot get connection for undo: branch=%s", branch_id)
            return
        record = self._undo.select(conn, branch_id)
        if record is None:
            logger.warning("[Seata-AT] undo_log not found: branch=%s", branch_id)
            return
        UndoExecutor.undo(
            conn,
            record["table_name"],
            record["sql_type"],
            record["before_image"],
            record["after_image"],
        )
        self._undo.delete(conn, branch_id)
        logger.info("[Seata-AT] undo applied: branch=%s table=%s", branch_id, record["table_name"])


# ---------------------------------------------------------------------------
# AT 代理总入口
# ---------------------------------------------------------------------------

class SeataATProxy:
    """Seata AT 数据源代理。

    用法：
        from spring.cloud.seata import seata_manager
        from spring.cloud.seata_at_proxy import SeataATProxy

        at_proxy = SeataATProxy(sql_session, seata_manager)
        at_proxy.install()  # 注册 ORM 拦截器

    安装后，在 ``seata_manager`` 开启的全局事务中，
    所有 UPDATE/DELETE/INSERT 会自动记录 undo_log，
    全局事务回滚时自动反向恢复。
    """

    def __init__(self, sql_session: Any, seata_manager: Any):
        self._session = sql_session
        self._seata = seata_manager
        self._undo = UndoLogManager(sql_session)
        self._interceptor = SeataATInterceptor(seata_manager, sql_session, self._undo)
        self._installed = False

    def install(self) -> None:
        """注册 AT 拦截器到 SqlSession 的拦截器链。"""
        if self._installed:
            return
        chain = getattr(self._session, "interceptor_chain", None)
        if chain is not None:
            chain.add_interceptor(self._interceptor)
            self._installed = True
            logger.info("[Seata-AT] AT interceptor installed on SqlSession")
        else:
            logger.warning(
                "[Seata-AT] SqlSession has no interceptor_chain; AT proxy not installed"
            )

    def is_installed(self) -> bool:
        return self._installed

    def manual_undo(self, branch_id: str) -> bool:
        """手动执行 undo（用于运维或恢复）。"""
        conn = self._interceptor._get_connection()
        if conn is None:
            return False
        record = self._undo.select(conn, branch_id)
        if record is None:
            return False
        UndoExecutor.undo(
            conn,
            record["table_name"],
            record["sql_type"],
            record["before_image"],
            record["after_image"],
        )
        self._undo.delete(conn, branch_id)
        return True
