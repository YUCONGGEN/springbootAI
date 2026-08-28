"""
Seata AT 模式 Python 数据源代理

在 ORM 拦截器层自动记录 before/after image，生成 undo_log，
在全局事务回滚时自动反向恢复数据。

工作原理：
1. ``SeataATInterceptor`` 拦截 UPDATE/DELETE/INSERT SQL
2. 执行前使用原 SQL 的绑定参数查询 before image
3. 执行原 SQL
4. 执行后查询 after image（仅 UPDATE/DELETE）
5. 把 before/after image 序列化为 JSON 存入 ``undo_log`` 表
6. 全局事务回滚时，根据 undo_log 反向恢复数据
7. 全局事务提交时，删除 undo_log

与 Java Seata AT 的差异：
- Java 用 ``DataSourceProxy`` 和 TC 全局锁；Python 在 ORM 拦截器层做进程内补偿
- Java 解析 SQL 用 Druid；Python 只接受可安全识别的单表 SQL 子集
- Python 不支持数据库自增列回填的 undo（INSERT 必须显式绑定主键）

限制：
1. 仅支持单表 SQL，不支持 JOIN、子查询、注释、多语句和 RETURNING
2. UPDATE/DELETE 必须有 WHERE，表必须恰好有一个主键列
3. INSERT 必须是单行显式列/VALUES，并以绑定参数提供主键
4. 需要 undo_log 表（代理安装时创建，业务事务中不会执行 DDL/隐式提交）
5. 仅在 Seata 全局事务激活时工作；跨服务强一致请使用官方 TC + TCC
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from contextlib import nullcontext
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("Spring.Cloud.SeataAT")


class SeataATError(RuntimeError):
    """Seata AT 无法保证本地分支可补偿。"""


class SeataATUnsupportedSQLError(SeataATError):
    """SQL 超出当前 AT 代理能够安全补偿的子集。"""


class SeataATUndoConflictError(SeataATError):
    """回滚时检测到数据已被另一事务修改。"""


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
_RE_INSERT_VALUES = re.compile(
    r"^\s*INSERT\s+INTO\s+`?(\w+)`?\s*\(([^)]+)\)\s*"
    r"VALUES\s*\(([^)]+)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_RE_PLACEHOLDER = re.compile(r"%s|\?")
_UNSUPPORTED_SQL = re.compile(
    r"(?:;|--|/\*|\*/|\bJOIN\b|\bSELECT\b|\bRETURNING\b|\bON\s+DUPLICATE\b)",
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
        """在代理安装阶段创建 undo_log 表，不得在业务事务中调用。"""
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
                try:
                    conn.rollback()
                except Exception:
                    logger.exception("[Seata-AT] failed to roll back undo_log DDL")
                raise SeataATError("Unable to initialize Seata AT undo_log table") from exc
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

    def delete(self, conn: Any, branch_id: str, commit: bool = True) -> None:
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(_adapt_sql(_DELETE_UNDO_LOG_SQL, ph), (branch_id,))
            if commit:
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
        commit: bool = True,
    ) -> None:
        """执行反向恢复。"""
        ph = _param_placeholder(conn)
        cursor = conn.cursor()
        try:
            if sql_type == _SQL_TYPE_INSERT:
                UndoExecutor._undo_insert(cursor, ph, table_name, after_image)
            elif sql_type == _SQL_TYPE_UPDATE:
                UndoExecutor._undo_update(
                    cursor, ph, table_name, before_image, after_image
                )
            elif sql_type == _SQL_TYPE_DELETE:
                UndoExecutor._undo_delete(cursor, ph, table_name, before_image)
            if commit:
                conn.commit()
        finally:
            cursor.close()

    @staticmethod
    def _undo_insert(cursor: Any, ph: str, table_name: str, after_image: Optional[List[Dict]]) -> None:
        if not after_image:
            raise SeataATUndoConflictError(
                f"Missing INSERT after image for {table_name}"
            )
        for row in after_image:
            if not row:
                raise SeataATUndoConflictError(f"Empty INSERT after image for {table_name}")
            primary_key = next(iter(row))
            primary_value = row[primary_key]
            cursor.execute(
                f"SELECT * FROM `{table_name}` WHERE `{primary_key}` = {ph}",  # nosec B608
                (primary_value,),
            )
            current = cursor.fetchone()
            cols = [desc[0] for desc in (cursor.description or [])]
            current_row = dict(zip(cols, tuple(current))) if current is not None else None
            if current_row != row:
                raise SeataATUndoConflictError(
                    f"Undo conflict detected for {table_name}.{primary_key}={primary_value!r}"
                )
            cursor.execute(
                f"DELETE FROM `{table_name}` WHERE `{primary_key}` = {ph}",  # nosec B608
                (primary_value,),
            )

    @staticmethod
    def _undo_update(
        cursor: Any,
        ph: str,
        table_name: str,
        before_image: Optional[List[Dict]],
        after_image: Optional[List[Dict]],
    ) -> None:
        if not before_image:
            return
        after_by_pk = {
            next(iter(row.values())): row for row in (after_image or []) if row
        }
        for row in before_image:
            cols = list(row.keys())
            if len(cols) < 2:
                raise SeataATUndoConflictError(
                    f"Incomplete before image for {table_name}"
                )
            pk = cols[0]
            pk_value = row[pk]
            expected_after = after_by_pk.get(pk_value)
            if expected_after is None:
                raise SeataATUndoConflictError(
                    f"Missing after image for {table_name}.{pk}={pk_value!r}"
                )
            cursor.execute(
                f"SELECT * FROM `{table_name}` WHERE `{pk}` = {ph}",  # nosec B608
                (pk_value,),
            )
            current = cursor.fetchone()
            current_cols = [desc[0] for desc in (cursor.description or [])]
            current_row = dict(zip(current_cols, tuple(current))) if current is not None else None
            if current_row != expected_after:
                raise SeataATUndoConflictError(
                    f"Undo conflict detected for {table_name}.{pk}={pk_value!r}"
                )
            set_clause = ", ".join(f"`{c}` = {ph}" for c in cols[1:])
            cursor.execute(
                f"UPDATE `{table_name}` SET {set_clause} WHERE `{pk}` = {ph}",  # nosec B608
                tuple(row[c] for c in cols[1:]) + (pk_value,),
            )

    @staticmethod
    def _undo_delete(cursor: Any, ph: str, table_name: str, before_image: Optional[List[Dict]]) -> None:
        if not before_image:
            return
        for row in before_image:
            cols = list(row.keys())
            if not cols:
                raise SeataATUndoConflictError(f"Empty DELETE before image for {table_name}")
            primary_key = cols[0]
            cursor.execute(
                f"SELECT 1 FROM `{table_name}` WHERE `{primary_key}` = {ph}",  # nosec B608
                (row[primary_key],),
            )
            if cursor.fetchone() is not None:
                raise SeataATUndoConflictError(
                    f"Undo conflict detected for {table_name}.{primary_key}={row[primary_key]!r}"
                )
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

        method = str(invocation.get_method()).lower()
        args = invocation.get_args()

        # 只拦截写操作（update/delete/insert）
        if method not in ("update", "delete", "insert"):
            return invocation.proceed()

        session = self._session
        if session is None and hasattr(invocation, "get_target"):
            session = invocation.get_target()
        if session is None:
            raise SeataATError("Seata AT interceptor cannot resolve SqlSession")

        sql, bound_params = self._prepare_sql(session, args)
        sql_type, table_name, where_clause = parse_sql(sql)
        expected_type = method.upper()
        if not sql_type or sql_type != expected_type:
            raise SeataATUnsupportedSQLError(
                f"Unsupported {expected_type} statement in Seata AT transaction"
            )
        if _UNSUPPORTED_SQL.search(sql):
            raise SeataATUnsupportedSQLError(
                "Seata AT supports only single-table statements without subqueries/comments"
            )
        if sql_type in {_SQL_TYPE_UPDATE, _SQL_TYPE_DELETE} and not where_clause:
            raise SeataATUnsupportedSQLError(
                "Seata AT rejects UPDATE/DELETE without a WHERE clause"
            )

        xid = self._seata.get_current_tx_id()
        branch_id = self._next_branch_id()

        # 获取底层连接
        conn = self._get_connection(session)
        if conn is None:
            raise SeataATError("Seata AT cannot obtain the business database connection")

        primary_key = self._get_primary_key(conn, table_name)
        transaction_factory = getattr(session, "transaction", None)
        if not callable(transaction_factory):
            raise SeataATError(
                "Seata AT requires a SqlSession with local transaction support"
            )
        transaction_scope = (
            nullcontext()
            if bool(getattr(session, "in_transaction", False))
            else transaction_factory()
        )

        with transaction_scope:
            before_image: Optional[List[Dict]] = None
            after_image: Optional[List[Dict]] = None

            if sql_type in {_SQL_TYPE_UPDATE, _SQL_TYPE_DELETE}:
                image_params = self._where_params(sql, bound_params)
                before_image = self._query_image(
                    conn, table_name, where_clause, image_params, primary_key
                )

            # 原 SQL、镜像和 undo_log 处于同一个本地事务；任一后置步骤失败都会回滚。
            result = invocation.proceed()

            if sql_type == _SQL_TYPE_UPDATE:
                after_image = self._query_rows_by_primary_key(
                    conn, table_name, primary_key, before_image or []
                )
            elif sql_type == _SQL_TYPE_DELETE:
                after_image = []
            else:
                after_image = self._query_insert_after_image(
                    conn, table_name, sql, bound_params, primary_key
                )

            self._undo.insert(
                conn, branch_id, xid, table_name, sql_type, before_image, after_image
            )

            # 注册失败也必须让本地事务回滚，否则会产生无全局分支的数据修改。
            self._seata.register_branch(
                xid=xid,
                branch_id=branch_id,
                resource_id=table_name,
                commit_cb=lambda _xid, _bid: self._on_commit(_bid, session),
                rollback_cb=lambda _xid, _bid: self._on_rollback(_bid, session),
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

    def _prepare_sql(self, session: Any, args: tuple) -> Tuple[str, List[Any]]:
        """解析 statement id/MyBatis 参数，得到 DBAPI 实际执行的 SQL 和参数顺序。"""
        if not args or not isinstance(args[0], str):
            raise SeataATUnsupportedSQLError("Seata AT requires a SQL string or statement id")
        sql_or_id = args[0]
        params = args[1] if len(args) > 1 else {}
        resolve = getattr(session, "_resolve_sql", None)
        process = getattr(session, "_process_sql", None)
        try:
            resolved_sql = resolve(sql_or_id)[0] if callable(resolve) else sql_or_id
            if callable(process) and isinstance(params, Mapping):
                processed_sql, bound_params = process(resolved_sql, dict(params))
                return processed_sql.strip().rstrip(";"), list(bound_params)
        except Exception as exc:
            raise SeataATUnsupportedSQLError(
                "Unable to resolve SQL and bound parameters for Seata AT"
            ) from exc
        if isinstance(params, Mapping):
            if _RE_PLACEHOLDER.search(resolved_sql) and params:
                raise SeataATUnsupportedSQLError(
                    "Raw placeholder SQL must use an ordered parameter sequence"
                )
            bound_params: Sequence[Any] = ()
        elif isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
            bound_params = params
        else:
            raise SeataATUnsupportedSQLError("Unsupported SQL parameter container")
        return resolved_sql.strip().rstrip(";"), list(bound_params)

    @staticmethod
    def _where_params(sql: str, bound_params: Sequence[Any]) -> List[Any]:
        where_match = re.search(r"\bWHERE\b", sql, re.IGNORECASE)
        if where_match is None:
            return []
        prefix_count = len(_RE_PLACEHOLDER.findall(sql[:where_match.start()]))
        where_count = len(_RE_PLACEHOLDER.findall(sql[where_match.end():]))
        values = list(bound_params[prefix_count:])
        if where_count != len(values):
            raise SeataATUnsupportedSQLError(
                "Unable to map SQL parameters to the WHERE clause"
            )
        return values

    def _get_connection(self, session: Any = None) -> Any:
        """从 SqlSession 获取底层 DBAPI 连接。"""
        session = session or self._session
        if session is None:
            return None
        # PyMyBatis SqlSession 持有 connection
        conn = getattr(session, "connection", None)
        if conn is not None:
            return conn
        # 尝试从 executor 获取
        executor = getattr(session, "executor", None)
        if executor is not None:
            conn = getattr(executor, "connection", None)
            if conn is not None:
                return conn
        getter = getattr(session, "get_connection", None)
        if callable(getter):
            return getter()
        return None

    @staticmethod
    def _get_primary_key(conn: Any, table_name: str) -> str:
        cursor = conn.cursor()
        try:
            if type(conn).__module__ == "sqlite3":
                cursor.execute(f"PRAGMA table_info(`{table_name}`)")  # nosec B608
                keys = sorted(
                    ((int(row[5]), str(row[1])) for row in cursor.fetchall() if int(row[5] or 0) > 0),
                    key=lambda item: item[0],
                )
                if len(keys) == 1:
                    return keys[0][1]
            else:
                cursor.execute(
                    f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'"  # nosec B608
                )
                rows = cursor.fetchall()
                keys = []
                for row in rows:
                    if isinstance(row, Mapping):
                        keys.append((int(row.get("Seq_in_index", 0)), row.get("Column_name")))
                    else:
                        keys.append((int(row[3]), row[4]))
                keys.sort(key=lambda item: item[0])
                if len(keys) == 1 and keys[0][1]:
                    return str(keys[0][1])
        except Exception as exc:
            raise SeataATUnsupportedSQLError(
                f"Unable to inspect primary key for table {table_name}"
            ) from exc
        finally:
            cursor.close()
        raise SeataATUnsupportedSQLError(
            f"Seata AT requires exactly one primary key column on table {table_name}"
        )

    def _query_image(
        self,
        conn: Any,
        table_name: str,
        where_clause: str,
        params: Sequence[Any],
        primary_key: str,
    ) -> List[Dict]:
        if not where_clause:
            raise SeataATUnsupportedSQLError("A WHERE clause is required for AT images")
        sql = f"SELECT * FROM `{table_name}` WHERE {where_clause}"  # nosec B608
        cursor = conn.cursor()
        try:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description] if cursor.description else []
            ordered_cols = [primary_key] + [col for col in cols if col != primary_key]
            result = []
            for row in rows:
                values = dict(zip(cols, tuple(row)))
                result.append({col: values[col] for col in ordered_cols})
            return result
        except Exception as exc:
            raise SeataATError(
                f"Unable to query AT image for table {table_name}"
            ) from exc
        finally:
            cursor.close()

    def _query_rows_by_primary_key(
        self,
        conn: Any,
        table_name: str,
        primary_key: str,
        rows: Sequence[Dict[str, Any]],
    ) -> List[Dict]:
        if not rows:
            return []
        ph = _param_placeholder(conn)
        values = [row[primary_key] for row in rows]
        where = " OR ".join(f"`{primary_key}` = {ph}" for _ in values)
        return self._query_image(conn, table_name, where, values, primary_key)

    def _query_insert_after_image(
        self,
        conn: Any,
        table_name: str,
        sql: str,
        bound_params: Sequence[Any],
        primary_key: str,
    ) -> List[Dict]:
        match = _RE_INSERT_VALUES.match(sql)
        if match is None:
            raise SeataATUnsupportedSQLError(
                "Seata AT INSERT requires one explicit column/value row"
            )
        columns = [part.strip().strip("`") for part in match.group(2).split(",")]
        values = [part.strip() for part in match.group(3).split(",")]
        if len(columns) != len(values) or primary_key not in columns:
            raise SeataATUnsupportedSQLError(
                "Seata AT INSERT must explicitly bind the primary key"
            )
        parameter_index = 0
        primary_value = None
        for column, token in zip(columns, values):
            if _RE_PLACEHOLDER.fullmatch(token):
                if parameter_index >= len(bound_params):
                    raise SeataATUnsupportedSQLError("INSERT parameter count mismatch")
                if column == primary_key:
                    primary_value = bound_params[parameter_index]
                parameter_index += 1
            elif column == primary_key:
                raise SeataATUnsupportedSQLError(
                    "Seata AT INSERT primary key must use a bound parameter"
                )
        if parameter_index != len(bound_params) or primary_value is None:
            raise SeataATUnsupportedSQLError("Unable to resolve INSERT primary key")
        ph = _param_placeholder(conn)
        return self._query_image(
            conn,
            table_name,
            f"`{primary_key}` = {ph}",
            [primary_value],
            primary_key,
        )

    def _callback_connection(self, session: Any) -> Tuple[Any, Any, bool]:
        current = getattr(session, "_current_connection", None)
        if bool(getattr(session, "in_transaction", False)) and current is not None:
            return current, None, True
        pool = getattr(session, "connection_pool", None)
        if pool is not None:
            pooled = pool.get_connection()
            return pooled.get_connection(), lambda: pool.return_connection(pooled), False
        conn = self._get_connection(session)
        return conn, None, False

    def _on_commit(self, branch_id: str, session: Any = None) -> None:
        conn, release, ambient = self._callback_connection(session or self._session)
        try:
            if conn is None:
                raise SeataATError("Cannot obtain connection for AT commit cleanup")
            self._undo.delete(conn, branch_id, commit=not ambient)
        finally:
            if release:
                release()

    def _on_rollback(self, branch_id: str, session: Any = None) -> None:
        target_session = session or self._session
        conn, release, ambient = self._callback_connection(target_session)
        if conn is None:
            raise SeataATError("Cannot obtain connection for AT rollback")
        try:
            record = self._undo.select(conn, branch_id)
            if record is None:
                raise SeataATError(f"undo_log not found for branch {branch_id}")
            UndoExecutor.undo(
                conn,
                record["table_name"],
                record["sql_type"],
                record["before_image"],
                record["after_image"],
                commit=False,
            )
            self._undo.delete(conn, branch_id, commit=False)
            if not ambient:
                conn.commit()
            logger.info(
                "[Seata-AT] undo applied: branch=%s table=%s",
                branch_id,
                record["table_name"],
            )
        except Exception:
            if ambient:
                if hasattr(target_session, "_transaction_rollback_only"):
                    target_session._transaction_rollback_only = True
            else:
                try:
                    conn.rollback()
                except Exception:
                    logger.exception("[Seata-AT] failed to roll back undo transaction")
            raise
        finally:
            if release:
                release()


# ---------------------------------------------------------------------------
# AT 代理总入口
# ---------------------------------------------------------------------------

class SeataATProxy:
    """Seata AT 数据源代理。

    用法：
        from springbootai.cloud.seata import seata_manager
        from springbootai.cloud.seata_at_proxy import SeataATProxy

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
        if chain is None:
            raise SeataATError("SqlSession has no interceptor_chain")
        if bool(getattr(self._session, "in_transaction", False)):
            raise SeataATError("Seata AT proxy must be installed before a transaction starts")
        conn = self._interceptor._get_connection(self._session)
        if conn is None:
            raise SeataATError("Cannot initialize Seata AT without a database connection")
        self._undo.ensure_table(conn)
        chain.add_interceptor(self._interceptor)
        self._installed = True
        logger.info("[Seata-AT] AT interceptor installed on SqlSession")

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


def install_seata_at_factory(sql_session_factory: Any, seata_manager: Any) -> SeataATInterceptor:
    """在 SqlSessionFactory 上安装 AT 拦截器，使之后创建的每个 Session 自动生效。"""
    existing = getattr(sql_session_factory, "_seata_at_interceptor", None)
    if existing is not None:
        return existing
    configuration = getattr(sql_session_factory, "configuration", None)
    if configuration is None or not hasattr(configuration, "interceptors"):
        raise SeataATError("Seata AT requires a PyMyBatis SqlSessionFactory")

    undo = UndoLogManager(sql_session_factory)
    with sql_session_factory.open_session() as bootstrap_session:
        conn = bootstrap_session.get_connection()
        undo.ensure_table(conn)

    interceptor = SeataATInterceptor(seata_manager, None, undo)
    configuration.interceptors.append(interceptor)
    sql_session_factory._seata_at_interceptor = interceptor
    logger.info("[Seata-AT] AT interceptor installed on SqlSessionFactory")
    return interceptor
