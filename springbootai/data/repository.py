"""Spring Data 仓库抽象（对齐 ``org.springframework.data.repository.PagingAndSortingRepository``）。

提供基于实体元数据的 CRUD + 分页 + 排序 + ``Specification`` 动态查询统一抽象。
**复用现有范式不重复造轮子**：
- 实体解析复用 ``DdlAutoManager._parse_entity``（与 ``OptimisticLockExecutor`` 同一 ``__new__`` 技巧），
  无需 pool 即可解析表名/列/主键。
- SQL 执行复用 ``OptimisticLockExecutor`` 的轻量范式（pool + cursor + ``_quote``），
  不强依赖 PyMyBatis ``SqlSession``，降低使用门槛。
- 列名翻译 ``_col_resolver`` 把 Python 属性名映射为真实列名（对齐 ``Column(name=...)``），
  供 ``Sort`` / ``Specification`` 复用。

与 Java 差异：
- Java 的 Spring Data Repository 是接口 + 方法名解析（运行时动态代理生成实现）；
  Python 无等价元编程惯例，故采用**基类继承** + 显式方法，更符合 Python 习惯。
- ``@DataRepository`` 为标记注解（声明管理的实体类型），实际能力由继承基类获得。
"""
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from springbootai.data.page import Page, Pageable, Sort
from springbootai.data.specification import Specification

T = TypeVar("T")


def _parse_entity_table(entity_class: Type):
    """复用 ``DdlAutoManager._parse_entity`` 解析实体元数据（不依赖 pool）。

    与 ``OptimisticLockExecutor._parse_columns`` 同一技巧：``__new__`` 绕过 ``__init__``
    （后者需要 pool），直接调用纯解析方法。
    """
    from springbootai.orm.ddl_auto import DdlAutoManager
    tmp = DdlAutoManager.__new__(DdlAutoManager)
    tmp.dialect = "sqlite"
    tmp.mode = None  # type: ignore
    return tmp._parse_entity(entity_class)


class PagingAndSortingRepository(Generic[T]):
    """分页排序仓库基类。

    Args:
        pool:          数据库连接池（需支持 ``connection()`` 返回带 ``cursor()``/``commit()``/``close()`` 的连接）。
        entity_class:  管理的实体类（带 ``@entity``/``Column`` 元数据）。
        dialect:       SQL 方言（mysql/postgresql/sqlite），影响标识符引用。
    """

    def __init__(self, pool: Any, entity_class: Type[T], dialect: str = "sqlite"):
        self.pool = pool
        self.entity_class = entity_class
        self.dialect = dialect.lower()
        if self.dialect not in {"sqlite", "mysql", "postgresql"}:
            raise ValueError(
                "repository dialect must be sqlite, mysql, or postgresql")
        self._table = _parse_entity_table(entity_class)
        self._columns: List[dict] = [c for c in self._table.columns if not c.get("transient")]
        primary_key = next(
            (c for c in self._columns if c.get("primary_key")), None)
        if primary_key is None:
            raise ValueError(
                f"实体 {entity_class.__name__} 未声明主键（@Id），无法构建 Repository"
            )
        self._pk: Dict[str, Any] = primary_key
        # py_name -> sql 列名 映射，供 Sort/Specification 翻译
        self._col_map: Dict[str, str] = {}
        for column in self._columns:
            python_name = column.get("py_name") or column.get("name")
            sql_name = column.get("name") or column.get("py_name")
            if python_name is not None and sql_name is not None:
                self._col_map[str(python_name)] = str(sql_name)

    # ==================== 内部工具 ====================

    def _quote(self, identifier: str) -> str:
        if self.dialect == "mysql":
            return f"`{str(identifier).replace('`', '``')}`"
        return f'"{str(identifier).replace(chr(34), chr(34) * 2)}"'

    def _placeholder(self) -> str:
        return "%s" if self.dialect in {"mysql", "postgresql"} else "?"

    def _col_resolver(self, prop: str) -> str:
        if prop not in self._col_map:
            raise ValueError(f"unknown repository property: {prop}")
        return self._quote(self._col_map[prop])

    def _column_list(self) -> str:
        return ", ".join(self._quote(c["name"]) for c in self._columns)

    def _row_to_entity(self, row: tuple) -> T:
        """按列顺序把行元组转为实体实例。"""
        obj = self.entity_class.__new__(self.entity_class)
        for col, val in zip(self._columns, row):
            setattr(obj, col["py_name"], val)
        return obj  # type: ignore

    def _get_field(self, entity: T, py_name: str) -> Any:
        return getattr(entity, py_name, None)

    def _execute(self, sql: str, params: list, fetch: bool = False):
        """执行 SQL。fetch=True 返回行列表，否则返回影响行数。"""
        conn = None
        cursor = None
        pooled = hasattr(self.pool, "connection")
        try:
            if pooled:
                conn = self.pool.connection()
            else:
                conn = self.pool
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if fetch:
                rows = cursor.fetchall()
                conn.commit()
                return rows
            # DML：rowcount 为影响行数（sqlite3/MySQLdb/psycopg2 一致）
            affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception:
            if conn is not None and hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if cursor is not None and hasattr(cursor, "close"):
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None and pooled:
                try:
                    conn.close()
                except Exception:
                    pass

    def _fetchone(self, sql: str, params: list):
        conn = None
        cursor = None
        pooled = hasattr(self.pool, "connection")
        try:
            if pooled:
                conn = self.pool.connection()
            else:
                conn = self.pool
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            conn.commit()
            return row
        except Exception:
            if conn is not None and hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if cursor is not None and hasattr(cursor, "close"):
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None and pooled:
                try:
                    conn.close()
                except Exception:
                    pass

    def _execute_insert(self, sql: str, params: list,
                        return_generated_id: bool = False) -> Any:
        """Execute an INSERT and capture its generated key on the same cursor."""
        conn = None
        cursor = None
        pooled = hasattr(self.pool, "connection")
        try:
            conn = self.pool.connection() if pooled else self.pool
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if return_generated_id and self.dialect == "postgresql":
                row = cursor.fetchone()
                generated_id = row[0] if row else None
            elif return_generated_id:
                generated_id = getattr(cursor, "lastrowid", None)
            else:
                generated_id = None
            conn.commit()
            return generated_id
        except Exception:
            if conn is not None and hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if cursor is not None and hasattr(cursor, "close"):
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None and pooled:
                try:
                    conn.close()
                except Exception:
                    pass

    # ==================== CRUD ====================

    def save(self, entity: T) -> T:
        """保存实体：主键已存在则 UPDATE，否则 INSERT。"""
        pk_val = self._get_field(entity, self._pk["py_name"])
        if pk_val is not None and self.exists_by_id(pk_val):
            return self._update(entity)
        return self._insert(entity)

    def _insert(self, entity: T) -> T:
        non_auto = [c for c in self._columns if not c.get("auto_increment")]
        params = [self._get_field(entity, c["py_name"]) for c in non_auto]
        if non_auto:
            cols = ", ".join(self._quote(c["name"]) for c in non_auto)
            placeholders = ", ".join(
                self._placeholder() for _ in non_auto)
            sql = f"INSERT INTO {self._quote(self._table.table_name)} ({cols}) VALUES ({placeholders})"  # nosec B608
        elif self.dialect == "mysql":
            sql = f"INSERT INTO {self._quote(self._table.table_name)} () VALUES ()"  # nosec B608
        else:
            sql = f"INSERT INTO {self._quote(self._table.table_name)} DEFAULT VALUES"  # nosec B608
        returns_generated_id = bool(self._pk.get("auto_increment"))
        if self.dialect == "postgresql" and returns_generated_id:
            sql += f" RETURNING {self._quote(self._pk['name'])}"
        generated_id = self._execute_insert(
            sql, params, return_generated_id=returns_generated_id)
        # 自增主键回填
        if self._pk.get("auto_increment") and self._get_field(entity, self._pk["py_name"]) is None:
            if generated_id is not None:
                setattr(entity, self._pk["py_name"], generated_id)
        return entity

    def _update(self, entity: T) -> T:
        non_pk = [c for c in self._columns if not c.get("primary_key")]
        marker = self._placeholder()
        set_parts = ", ".join(
            f"{self._quote(c['name'])} = {marker}" for c in non_pk)
        params = [self._get_field(entity, c["py_name"]) for c in non_pk]
        pk_val = self._get_field(entity, self._pk["py_name"])
        params.append(pk_val)
        sql = (f"UPDATE {self._quote(self._table.table_name)} SET {set_parts} "  # nosec B608
               f"WHERE {self._quote(self._pk['name'])} = {marker}")
        self._execute(sql, params)
        return entity

    def find_by_id(self, id_: Any) -> Optional[T]:
        sql = (f"SELECT {self._column_list()} FROM {self._quote(self._table.table_name)} "  # nosec B608
               f"WHERE {self._quote(self._pk['name'])} = {self._placeholder()}")
        row = self._fetchone(sql, [id_])
        return self._row_to_entity(row) if row else None

    def exists_by_id(self, id_: Any) -> bool:
        sql = (f"SELECT 1 FROM {self._quote(self._table.table_name)} "  # nosec B608
               f"WHERE {self._quote(self._pk['name'])} = {self._placeholder()} LIMIT 1")
        return self._fetchone(sql, [id_]) is not None

    def count(self, specification: Optional[Specification] = None) -> int:
        where, params = self._spec_where(specification)
        sql = f"SELECT COUNT(*) FROM {self._quote(self._table.table_name)}{where}"  # nosec B608
        row = self._fetchone(sql, params)
        return int(row[0]) if row else 0

    def delete_by_id(self, id_: Any) -> int:
        sql = (f"DELETE FROM {self._quote(self._table.table_name)} "  # nosec B608
               f"WHERE {self._quote(self._pk['name'])} = {self._placeholder()}")
        return self._execute(sql, [id_])

    def delete(self, entity: T) -> int:
        return self.delete_by_id(self._get_field(entity, self._pk["py_name"]))

    def delete_all(self, specification: Optional[Specification] = None) -> int:
        where, params = self._spec_where(specification)
        sql = f"DELETE FROM {self._quote(self._table.table_name)}{where}"  # nosec B608
        return self._execute(sql, params)

    # ==================== 查询（排序/分页/动态） ====================

    def find_all(self,
                 sort: Optional[Sort] = None,
                 specification: Optional[Specification] = None,
                 pageable: Optional[Pageable] = None) -> Any:
        """统一查询入口。

        - 仅传 ``sort``：返回 ``List[T]``。
        - 仅传 ``specification``：返回 ``List[T]``。
        - 传 ``pageable``：返回 ``Page[T]``（可同时带 ``specification``）。
        """
        where, params = self._spec_where(specification)
        if pageable is not None:
            return self._find_page(pageable, where, params, specification)
        order = self._sort_sql(sort or Sort.unsorted())
        sql = (f"SELECT {self._column_list()} FROM {self._quote(self._table.table_name)}"  # nosec B608
               f"{where}{order}")
        rows = self._execute(sql, params, fetch=True)
        return [self._row_to_entity(r) for r in rows]

    def find_one(self, specification: Specification) -> Optional[T]:
        where, params = self._spec_where(specification)
        sql = (f"SELECT {self._column_list()} FROM {self._quote(self._table.table_name)}"  # nosec B608
               f"{where} LIMIT 1")
        row = self._fetchone(sql, params)
        return self._row_to_entity(row) if row else None

    def _find_page(self, pageable: Pageable, where: str, params: list,
                   specification: Optional[Specification] = None) -> Page:
        order = self._sort_sql(pageable.sort)
        # SQLite/MySQL/PostgreSQL 均支持 LIMIT/OFFSET
        page_sql = (f"SELECT {self._column_list()} FROM {self._quote(self._table.table_name)}"  # nosec B608
                    f"{where}{order} LIMIT {self._placeholder()} "
                    f"OFFSET {self._placeholder()}")
        rows = self._execute(page_sql, params + [pageable.limit, pageable.offset], fetch=True)
        content = [self._row_to_entity(r) for r in rows]
        # total 必须带同一 specification，否则分页总数与筛选条件不一致
        total = self.count(specification)
        return Page(content, pageable, total)

    def _spec_where(self, specification: Optional[Specification]) -> tuple:
        if specification is None:
            return "", []
        sql, params = specification.to_predicate(self._col_resolver)
        if self._placeholder() != "?":
            sql = sql.replace("?", self._placeholder())
        return (f" WHERE {sql}" if sql else ""), params

    def _sort_sql(self, sort: Sort) -> str:
        if not sort.is_sorted:
            return ""
        return " ORDER BY " + sort.to_sql(self._col_resolver)


# ==================== 注解（标记） ====================

class DataRepository:
    """``@DataRepository(EntityClass)`` 标记注解：声明仓库管理的实体类型。

    标记后可通过 ``get_data_repository_entity(cls)`` 读取实体类型，便于 IoC 集成
    （如 ``@Bean`` 工厂方法根据实体类型构造 ``PagingAndSortingRepository``）。

    注意：本注解仅声明元数据，**不**自动生成仓库实现——仓库能力由继承
    ``PagingAndSortingRepository`` 获得（对齐 Python 习惯，与 Java 接口代理方式不同）。
    """

    def __init__(self, entity_class: Type):
        self.entity_class = entity_class

    def __call__(self, target: Type) -> Type:
        setattr(target, "__data_repository__", self)
        return target


def get_data_repository_entity(cls: Type) -> Optional[Type]:
    ann = getattr(cls, "__data_repository__", None)
    return ann.entity_class if ann is not None else None
