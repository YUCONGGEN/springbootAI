"""
PyMyBatis数据库方言模块

支持MySQL、PostgreSQL、SQLite、Oracle等数据库的SQL方言适配
"""

from .dialect import Dialect, MySQLDialect, PostgreSQLDialect, SQLiteDialect, OracleDialect, get_dialect

__all__ = ['Dialect', 'MySQLDialect', 'PostgreSQLDialect', 'SQLiteDialect', 'OracleDialect', 'get_dialect']
