"""
PyMyBatis注解模块

提供SQL注解定义：@Select、@Insert、@Update、@Delete、@ResultMap、@Result
"""

from .annotations import (
    CacheNamespace,
    DataSource,
    Delete,
    DeleteProvider,
    Insert,
    InsertProvider,
    Options,
    Param,
    Result,
    ResultMap,
    Select,
    SelectPage,
    SelectProvider,
    Transactional,
    Update,
    UpdateProvider,
)

__all__ = [
    'Select', 'SelectPage', 'Insert', 'Update', 'Delete',
    'SelectProvider', 'InsertProvider', 'UpdateProvider', 'DeleteProvider',
    'ResultMap', 'Result',
    'Options', 'Param', 'CacheNamespace', 'DataSource', 'Transactional',
]
