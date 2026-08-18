"""
PyMyBatis数据库方言模块

定义各数据库的SQL语法差异，实现SQL方言适配
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple


class Dialect(ABC):
    """
    数据库方言抽象基类

    定义各数据库特有的SQL语法：
    - 分页查询
    - 主键自增
    - 批量插入
    - 特殊函数
    """

    @abstractmethod
    def get_dialect_name(self) -> str:
        """获取方言名称"""
        pass

    @abstractmethod
    def get_pagination_sql(self, sql: str, offset: int, limit: int) -> str:
        """
        获取分页SQL

        Args:
            sql: 原始SQL
            offset: 偏移量
            limit: 每页条数

        Returns:
            分页SQL
        """
        pass

    @abstractmethod
    def get_insert_returning_sql(self, sql: str, key_column: str) -> str:
        """
        获取插入并返回主键的SQL

        Args:
            sql: 原始INSERT SQL
            key_column: 主键列名

        Returns:
            返回主键的INSERT SQL
        """
        pass

    @abstractmethod
    def get_batch_insert_sql(self, table_name: str, columns: List[str], values: List[Tuple]) -> str:
        """
        获取批量插入SQL

        Args:
            table_name: 表名
            columns: 列名列表
            values: 值列表

        Returns:
            批量插入SQL
        """
        pass

    @abstractmethod
    def get_batch_update_sql(self, table_name: str, columns: List[str], values: List[Tuple], pk_column: str) -> str:
        """
        获取批量更新SQL

        Args:
            table_name: 表名
            columns: 列名列表（不含主键）
            values: 值列表（每条记录包含主键和更新值）
            pk_column: 主键列名

        Returns:
            批量更新SQL
        """
        pass

    @abstractmethod
    def get_identity_query(self) -> str:
        """获取获取自增主键的SQL"""
        pass

    @abstractmethod
    def get_now_function(self) -> str:
        """获取当前时间函数"""
        pass

    @abstractmethod
    def get_concat_function(self, args: List[str]) -> str:
        """获取字符串拼接函数"""
        pass

    @abstractmethod
    def get_substring_function(self, column: str, start: int, length: Optional[int] = None) -> str:
        """获取子字符串函数"""
        pass

    @abstractmethod
    def get_length_function(self, column: str) -> str:
        """获取长度函数"""
        pass

    @abstractmethod
    def supports_limit_offset(self) -> bool:
        """是否支持LIMIT OFFSET语法"""
        pass

    @abstractmethod
    def supports_batch_insert(self) -> bool:
        """是否支持批量插入"""
        pass

    @abstractmethod
    def get_quote_char(self) -> str:
        """获取标识符引用字符"""
        pass

    def quote_identifier(self, identifier: str) -> str:
        """
        引用标识符（表名、列名等）

        Args:
            identifier: 标识符

        Returns:
            带引号的标识符
        """
        quote = self.get_quote_char()
        escaped = str(identifier).replace(quote, quote * 2)
        return f"{quote}{escaped}{quote}"


class MySQLDialect(Dialect):
    """MySQL数据库方言"""

    def get_dialect_name(self) -> str:
        return 'mysql'

    def get_pagination_sql(self, sql: str, offset: int, limit: int) -> str:
        return f"{sql} LIMIT {limit} OFFSET {offset}"

    def get_insert_returning_sql(self, sql: str, key_column: str) -> str:
        return sql

    def get_batch_insert_sql(self, table_name: str, columns: List[str], values: List[Tuple]) -> str:
        columns_str = ', '.join(self.quote_identifier(c) for c in columns)
        values_str = ', '.join(
            f"({', '.join('%s' for _ in row)})" for row in values
        )
        return f"INSERT INTO {self.quote_identifier(table_name)} ({columns_str}) VALUES {values_str}"  # nosec B608

    def get_batch_update_sql(self, table_name: str, columns: List[str], values: List[Tuple], pk_column: str) -> str:
        # MySQL批量更新使用CASE WHEN
        set_parts = []
        for col in columns:
            when_parts = []
            for _ in values:
                when_parts.append(f"WHEN {pk_column} = %s THEN %s")
            set_parts.append(f"{self.quote_identifier(col)} = CASE {pk_column} {' '.join(when_parts)} END")

        set_str = ', '.join(set_parts)
        pk_values = [row[0] for row in values]
        where_str = f"{pk_column} IN ({', '.join('%s' for _ in pk_values)})"

        return f"UPDATE {self.quote_identifier(table_name)} SET {set_str} WHERE {where_str}"  # nosec B608

    def get_identity_query(self) -> str:
        return "SELECT LAST_INSERT_ID()"

    def get_now_function(self) -> str:
        return "NOW()"

    def get_concat_function(self, args: List[str]) -> str:
        return ' CONCAT(' + ', '.join(args) + ')'

    def get_substring_function(self, column: str, start: int, length: Optional[int] = None) -> str:
        if length:
            return f"SUBSTRING({column}, {start}, {length})"
        return f"SUBSTRING({column}, {start})"

    def get_length_function(self, column: str) -> str:
        return f"LENGTH({column})"

    def supports_limit_offset(self) -> bool:
        return True

    def supports_batch_insert(self) -> bool:
        return True

    def get_quote_char(self) -> str:
        return '`'


class PostgreSQLDialect(Dialect):
    """PostgreSQL数据库方言"""

    def get_dialect_name(self) -> str:
        return 'postgresql'

    def get_pagination_sql(self, sql: str, offset: int, limit: int) -> str:
        return f"{sql} LIMIT {limit} OFFSET {offset}"

    def get_insert_returning_sql(self, sql: str, key_column: str) -> str:
        return f"{sql} RETURNING {self.quote_identifier(key_column)}"

    def get_batch_insert_sql(self, table_name: str, columns: List[str], values: List[Tuple]) -> str:
        columns_str = ', '.join(self.quote_identifier(c) for c in columns)
        values_str = ', '.join(
            f"({', '.join('%s' for _ in row)})" for row in values
        )
        return f"INSERT INTO {self.quote_identifier(table_name)} ({columns_str}) VALUES {values_str}"  # nosec B608

    def get_batch_update_sql(self, table_name: str, columns: List[str], values: List[Tuple], pk_column: str) -> str:
        # PostgreSQL批量更新使用FROM子句
        set_parts = []
        for col in columns:
            set_parts.append(f"{self.quote_identifier(col)} = updates.{self.quote_identifier(col)}")

        set_str = ', '.join(set_parts)

        # 构建VALUES子句作为临时表
        columns_with_pk = [pk_column] + columns
        values_str = ', '.join(
            f"({', '.join('%s' for _ in row)})" for row in values
        )

        return (
            f"UPDATE {self.quote_identifier(table_name)} SET {set_str} "  # nosec B608
            f"FROM (VALUES {values_str}) AS updates("
            f"{', '.join(self.quote_identifier(c) for c in columns_with_pk)}) "
            f"WHERE {self.quote_identifier(table_name)}."
            f"{self.quote_identifier(pk_column)} = updates.{self.quote_identifier(pk_column)}"
        )

    def get_identity_query(self) -> str:
        return "SELECT LASTVAL()"

    def get_now_function(self) -> str:
        return "NOW()"

    def get_concat_function(self, args: List[str]) -> str:
        return ' || '.join(args)

    def get_substring_function(self, column: str, start: int, length: Optional[int] = None) -> str:
        if length:
            return f"SUBSTRING({column} FROM {start} FOR {length})"
        return f"SUBSTRING({column} FROM {start})"

    def get_length_function(self, column: str) -> str:
        return f"LENGTH({column})"

    def supports_limit_offset(self) -> bool:
        return True

    def supports_batch_insert(self) -> bool:
        return True

    def get_quote_char(self) -> str:
        return '"'


class SQLiteDialect(Dialect):
    """SQLite数据库方言"""

    def get_dialect_name(self) -> str:
        return 'sqlite'

    def get_pagination_sql(self, sql: str, offset: int, limit: int) -> str:
        return f"{sql} LIMIT {limit} OFFSET {offset}"

    def get_insert_returning_sql(self, sql: str, key_column: str) -> str:
        return sql

    def get_batch_insert_sql(self, table_name: str, columns: List[str], values: List[Tuple]) -> str:
        columns_str = ', '.join(self.quote_identifier(c) for c in columns)
        values_str = ', '.join(
            f"({', '.join('?' for _ in row)})" for row in values
        )
        return f"INSERT INTO {self.quote_identifier(table_name)} ({columns_str}) VALUES {values_str}"  # nosec B608

    def get_batch_update_sql(self, table_name: str, columns: List[str], values: List[Tuple], pk_column: str) -> str:
        # SQLite批量更新使用CASE WHEN
        set_parts = []
        for col in columns:
            when_parts = []
            for i, row in enumerate(values):
                when_parts.append(f"WHEN {pk_column} = ? THEN ?")
            set_parts.append(f"{self.quote_identifier(col)} = CASE {pk_column} {' '.join(when_parts)} END")

        set_str = ', '.join(set_parts)
        pk_values = [row[0] for row in values]
        where_str = f"{pk_column} IN ({', '.join('?' for _ in pk_values)})"

        return f"UPDATE {self.quote_identifier(table_name)} SET {set_str} WHERE {where_str}"  # nosec B608

    def get_identity_query(self) -> str:
        return "SELECT LAST_INSERT_ROWID()"

    def get_now_function(self) -> str:
        return "datetime('now')"

    def get_concat_function(self, args: List[str]) -> str:
        return ' || '.join(args)

    def get_substring_function(self, column: str, start: int, length: Optional[int] = None) -> str:
        if length:
            return f"SUBSTR({column}, {start}, {length})"
        return f"SUBSTR({column}, {start})"

    def get_length_function(self, column: str) -> str:
        return f"LENGTH({column})"

    def supports_limit_offset(self) -> bool:
        return True

    def supports_batch_insert(self) -> bool:
        return True

    def get_quote_char(self) -> str:
        return '"'


class OracleDialect(Dialect):
    """Oracle数据库方言"""

    def get_dialect_name(self) -> str:
        return 'oracle'

    def get_pagination_sql(self, sql: str, offset: int, limit: int) -> str:
        # Oracle使用ROWNUM进行分页
        offset_val = offset + 1
        return (
            f"SELECT * FROM (SELECT t.*, ROWNUM rn FROM ({sql}) t "  # nosec B608
            f"WHERE ROWNUM <= {offset + limit}) WHERE rn >= {offset_val}"
        )

    def get_insert_returning_sql(self, sql: str, key_column: str) -> str:
        return f"{sql} RETURNING {self.quote_identifier(key_column)} INTO :id"

    def get_batch_insert_sql(self, table_name: str, columns: List[str], values: List[Tuple]) -> str:
        # Oracle批量插入使用UNION ALL
        columns_str = ', '.join(self.quote_identifier(c) for c in columns)
        values_parts = []
        for i, row in enumerate(values):
            row_values = []
            for j, _ in enumerate(row):
                row_values.append(f":{i * len(row) + j + 1}")
            values_parts.append(f"SELECT {', '.join(row_values)} FROM DUAL")  # nosec B608

        values_str = ' UNION ALL '.join(values_parts)
        return f"INSERT INTO {self.quote_identifier(table_name)} ({columns_str}) {values_str}"

    def get_batch_update_sql(self, table_name: str, columns: List[str], values: List[Tuple], pk_column: str) -> str:
        # Oracle批量更新使用MERGE语句
        columns_with_pk = [pk_column] + columns

        # 构建VALUES子句
        values_parts = []
        param_index = 1
        for row in values:
            row_values = []
            for _ in row:
                row_values.append(f":{param_index}")
                param_index += 1
            values_parts.append(f"({', '.join(row_values)})")

        values_str = ' UNION ALL '.join(
            f"SELECT {', '.join(values_parts[i])} FROM DUAL"  # nosec B608
            for i in range(len(values_parts))
        )

        # 构建SET子句
        set_parts = []
        for col in columns:
            set_parts.append(f"{self.quote_identifier(col)} = source.{self.quote_identifier(col)}")
        set_str = ', '.join(set_parts)

        return (
            f"MERGE INTO {self.quote_identifier(table_name)} target "  # nosec B608
            f"USING (SELECT {', '.join(self.quote_identifier(c) for c in columns_with_pk)} "
            f"FROM ({values_str})) source ON (target.{self.quote_identifier(pk_column)} = "
            f"source.{self.quote_identifier(pk_column)}) WHEN MATCHED THEN UPDATE SET {set_str}"
        )

    def get_identity_query(self) -> str:
        return "SELECT SEQ_CURRVAL FROM DUAL"

    def get_now_function(self) -> str:
        return "SYSDATE"

    def get_concat_function(self, args: List[str]) -> str:
        return ' || '.join(args)

    def get_substring_function(self, column: str, start: int, length: Optional[int] = None) -> str:
        if length:
            return f"SUBSTR({column}, {start}, {length})"
        return f"SUBSTR({column}, {start})"

    def get_length_function(self, column: str) -> str:
        return f"LENGTH({column})"

    def supports_limit_offset(self) -> bool:
        return False

    def supports_batch_insert(self) -> bool:
        return True

    def get_quote_char(self) -> str:
        return '"'


def get_dialect(dialect_name: str) -> Dialect:
    """
    根据方言名称获取方言实例

    Args:
        dialect_name: 方言名称（mysql/postgresql/sqlite/oracle）

    Returns:
        方言实例

    Raises:
        ValueError: 不支持的方言
    """
    dialect_map = {
        'mysql': MySQLDialect(),
        'postgresql': PostgreSQLDialect(),
        'sqlite': SQLiteDialect(),
        'oracle': OracleDialect()
    }

    dialect = dialect_map.get(dialect_name.lower())
    if not dialect:
        raise ValueError(f"不支持的数据库方言: {dialect_name}")

    return dialect
