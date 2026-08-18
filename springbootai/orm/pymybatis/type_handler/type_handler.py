"""
PyMyBatis类型处理器模块

支持自定义类型转换，适配不同数据库类型
"""

import datetime
import decimal
import enum
import uuid
from typing import Any, Optional, Dict
from abc import ABC, abstractmethod


class TypeHandler(ABC):
    """
    类型处理器抽象基类

    定义类型转换的核心接口：
    - java_type: Java类型
    - jdbc_type: JDBC类型
    - set_parameter: 设置参数
    - get_result: 获取结果
    """

    @property
    @abstractmethod
    def java_type(self) -> type:
        """Java类型"""
        pass

    @property
    @abstractmethod
    def jdbc_type(self) -> str:
        """JDBC类型"""
        pass

    @abstractmethod
    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        """
        设置参数

        Args:
            statement: SQL语句对象
            parameter_index: 参数索引
            value: 参数值
        """
        pass

    @abstractmethod
    def get_result(self, result_set: Any, column_name: str) -> Any:
        """
        获取结果

        Args:
            result_set: 结果集
            column_name: 列名

        Returns:
            转换后的结果
        """
        pass

    def to_database(self, value: Any) -> Any:
        """Convert a Python value before passing it to a DB-API driver."""
        return value

    def from_database(self, value: Any) -> Any:
        """Convert a DB-API value back to the declared Python type."""
        return value


class IntegerTypeHandler(TypeHandler):
    """Integer类型处理器"""

    @property
    def java_type(self) -> type:
        return int

    @property
    def jdbc_type(self) -> str:
        return 'INTEGER'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), int(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return int(value) if value is not None else None


class LongTypeHandler(TypeHandler):
    """Long类型处理器"""

    @property
    def java_type(self) -> type:
        return int

    @property
    def jdbc_type(self) -> str:
        return 'BIGINT'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), int(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return int(value) if value is not None else None


class StringTypeHandler(TypeHandler):
    """String类型处理器"""

    @property
    def java_type(self) -> type:
        return str

    @property
    def jdbc_type(self) -> str:
        return 'VARCHAR'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), str(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return str(value) if value is not None else None


class BooleanTypeHandler(TypeHandler):
    """Boolean类型处理器"""

    @property
    def java_type(self) -> type:
        return bool

    @property
    def jdbc_type(self) -> str:
        return 'BOOLEAN'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), bool(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return bool(value) if value is not None else None


class FloatTypeHandler(TypeHandler):
    """Float类型处理器"""

    @property
    def java_type(self) -> type:
        return float

    @property
    def jdbc_type(self) -> str:
        return 'FLOAT'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), float(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return float(value) if value is not None else None


class DoubleTypeHandler(TypeHandler):
    """Double类型处理器"""

    @property
    def java_type(self) -> type:
        return float

    @property
    def jdbc_type(self) -> str:
        return 'DOUBLE'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), float(value) if value is not None else None)

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return float(value) if value is not None else None


class DateTypeHandler(TypeHandler):
    """Date类型处理器"""

    @property
    def java_type(self) -> type:
        return datetime.date

    @property
    def jdbc_type(self) -> str:
        return 'DATE'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        if value is None:
            statement.setdefault(str(parameter_index), None)
        elif isinstance(value, datetime.datetime):
            statement.setdefault(str(parameter_index), value.date())
        elif isinstance(value, datetime.date):
            statement.setdefault(str(parameter_index), value)
        else:
            statement.setdefault(str(parameter_index), datetime.datetime.strptime(value, '%Y-%m-%d').date())

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return datetime.datetime.strptime(str(value), '%Y-%m-%d').date()

    def to_database(self, value: Any) -> Any:
        if isinstance(value, datetime.datetime):
            return value.date().isoformat()
        if isinstance(value, datetime.date):
            return value.isoformat()
        return value

    def from_database(self, value: Any) -> Any:
        if value is None or isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(str(value))


class DateTimeTypeHandler(TypeHandler):
    """DateTime类型处理器"""

    @property
    def java_type(self) -> type:
        return datetime.datetime

    @property
    def jdbc_type(self) -> str:
        return 'TIMESTAMP'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        if value is None:
            statement.setdefault(str(parameter_index), None)
        elif isinstance(value, datetime.datetime):
            statement.setdefault(str(parameter_index), value)
        else:
            statement.setdefault(str(parameter_index), datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S'))

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime(value.year, value.month, value.day)
        return datetime.datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')

    def to_database(self, value: Any) -> Any:
        return value.isoformat(sep=' ') if isinstance(value, datetime.datetime) else value

    def from_database(self, value: Any) -> Any:
        if value is None or isinstance(value, datetime.datetime):
            return value
        return datetime.datetime.fromisoformat(str(value))


class DecimalTypeHandler(TypeHandler):
    """Portable DECIMAL/NUMERIC handler for DB-API drivers."""

    @property
    def java_type(self) -> type:
        return decimal.Decimal

    @property
    def jdbc_type(self) -> str:
        return 'DECIMAL'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), self.to_database(value))

    def get_result(self, result_set: Any, column_name: str) -> Any:
        value = result_set.get(column_name)
        return self.from_database(value)

    def to_database(self, value: Any) -> Any:
        return None if value is None else str(value)

    def from_database(self, value: Any) -> Any:
        return None if value is None else decimal.Decimal(str(value))


class UUIDTypeHandler(TypeHandler):
    """Store UUID values as portable text while retaining UUID on reads."""

    @property
    def java_type(self) -> type:
        return uuid.UUID

    @property
    def jdbc_type(self) -> str:
        return 'VARCHAR'

    def set_parameter(self, statement: Any, parameter_index: int, value: Any) -> None:
        statement.setdefault(str(parameter_index), self.to_database(value))

    def get_result(self, result_set: Any, column_name: str) -> Any:
        return self.from_database(result_set.get(column_name))

    def to_database(self, value: Any) -> Any:
        return None if value is None else str(value)

    def from_database(self, value: Any) -> Any:
        return None if value is None or isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class TypeHandlerRegistry:
    """
    类型处理器注册中心

    管理所有类型处理器，支持自动选择和自定义注册
    """

    def __init__(self):
        """初始化类型处理器注册中心"""
        self.type_handlers: Dict[type, TypeHandler] = {}
        self.jdbc_type_handlers: Dict[str, TypeHandler] = {}

        # 注册默认类型处理器
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """注册默认类型处理器"""
        self.register(int, IntegerTypeHandler())
        self.register(bool, BooleanTypeHandler())
        self.register(float, DoubleTypeHandler())
        self.register(str, StringTypeHandler())
        self.register(datetime.date, DateTypeHandler())
        self.register(datetime.datetime, DateTimeTypeHandler())
        self.register(decimal.Decimal, DecimalTypeHandler())
        self.register(uuid.UUID, UUIDTypeHandler())

    def register(self, java_type: type, handler: TypeHandler, jdbc_type: Optional[str] = None) -> None:
        """
        注册类型处理器

        Args:
            java_type: Java类型
            handler: 类型处理器
        """
        # Also accept MyBatis' ``register(java_type, jdbc_type, handler)``
        # ordering for easier Java-to-Python migration.
        if isinstance(handler, str) and isinstance(jdbc_type, TypeHandler):
            handler, jdbc_type = jdbc_type, handler
        self.type_handlers[java_type] = handler
        if jdbc_type:
            self.jdbc_type_handlers[str(jdbc_type).upper()] = handler

    def get_handler(self, java_type: type, jdbc_type: Optional[str] = None) -> Optional[TypeHandler]:
        """
        获取类型处理器

        Args:
            java_type: Java类型

        Returns:
            类型处理器，未找到返回None
        """
        if jdbc_type is not None:
            handler = self.jdbc_type_handlers.get(str(jdbc_type).upper())
            if handler is not None:
                return handler
        handler = self.type_handlers.get(java_type)
        if handler is not None:
            return handler
        for registered_type, registered_handler in self.type_handlers.items():
            try:
                if isinstance(java_type, type) and isinstance(registered_type, type) and issubclass(java_type, registered_type):
                    return registered_handler
            except TypeError:
                continue
        return None

    def get_handler_by_jdbc_type(self, jdbc_type: str) -> Optional[TypeHandler]:
        """
        根据JDBC类型获取类型处理器

        Args:
            jdbc_type: JDBC类型

        Returns:
            类型处理器，未找到返回None
        """
        for handler in self.type_handlers.values():
            if handler.jdbc_type == jdbc_type:
                return handler
        return None

    def get_or_default(self, java_type: type) -> TypeHandler:
        """
        获取类型处理器，如果未找到则返回String类型处理器

        Args:
            java_type: Java类型

        Returns:
            类型处理器
        """
        handler = self.get_handler(java_type)
        if handler is None:
            handler = StringTypeHandler()
        return handler

    def to_database(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, enum.Enum):
            value = value.value
        handler = self.get_handler(type(value))
        return handler.to_database(value) if handler else value

    def from_database(self, value: Any, java_type: Optional[type] = None) -> Any:
        if value is None or java_type is None:
            return value
        handler = self.get_handler(java_type)
        return handler.from_database(value) if handler else value

    def set_parameter(self, statement: Any, parameter_index: int, value: Any, java_type: Optional[type] = None) -> None:
        """
        设置参数

        Args:
            statement: SQL语句对象
            parameter_index: 参数索引
            value: 参数值
            java_type: Java类型，不指定则自动推断
        """
        if java_type is None:
            java_type = type(value) if value is not None else str

        handler = self.get_or_default(java_type)
        handler.set_parameter(statement, parameter_index, value)

    def get_result(self, result_set: Any, column_name: str, java_type: Optional[type] = None) -> Any:
        """
        获取结果

        Args:
            result_set: 结果集
            column_name: 列名
            java_type: Java类型，不指定则自动推断

        Returns:
            转换后的结果
        """
        value = result_set.get(column_name)

        if java_type is None:
            if value is None:
                return None
            java_type = type(value)

        handler = self.get_or_default(java_type)
        return handler.get_result(result_set, column_name)

    def get_all_handlers(self) -> Dict[type, TypeHandler]:
        """获取所有类型处理器"""
        return self.type_handlers


# 全局默认类型处理器注册中心
DEFAULT_REGISTRY = TypeHandlerRegistry()
