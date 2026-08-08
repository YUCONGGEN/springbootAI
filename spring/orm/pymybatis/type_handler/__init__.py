"""
PyMyBatis类型处理器模块

支持自定义类型转换，适配不同数据库类型
"""

from .type_handler import (
    TypeHandler,
    IntegerTypeHandler,
    LongTypeHandler,
    StringTypeHandler,
    BooleanTypeHandler,
    FloatTypeHandler,
    DoubleTypeHandler,
    DateTypeHandler,
    DateTimeTypeHandler,
    DecimalTypeHandler,
    UUIDTypeHandler,
    TypeHandlerRegistry,
    DEFAULT_REGISTRY
)

__all__ = [
    'TypeHandler',
    'IntegerTypeHandler',
    'LongTypeHandler',
    'StringTypeHandler',
    'BooleanTypeHandler',
    'FloatTypeHandler',
    'DoubleTypeHandler',
    'DateTypeHandler',
    'DateTimeTypeHandler',
    'DecimalTypeHandler',
    'UUIDTypeHandler',
    'TypeHandlerRegistry',
    'DEFAULT_REGISTRY'
]
