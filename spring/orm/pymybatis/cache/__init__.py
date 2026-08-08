"""
PyMyBatis缓存模块

包含查询缓存、结果集映射缓存、Redis二级缓存等组件
"""

from .cache import (
    CacheType,
    CacheEntry,
    BaseCache,
    LRUCache,
    FIFOCache,
    LFUCache,
    SqlCache,
    ResultMapCache,
    XMLParserCache,
    PrecompiledSqlCache,
    SecondLevelCache,
    GLOBAL_XML_CACHE,
    GLOBAL_PRECOMPILED_CACHE,
    GLOBAL_SECOND_LEVEL_CACHE
)

# 基础导出列表
__all__ = [
    'CacheType',
    'CacheEntry',
    'BaseCache',
    'LRUCache',
    'FIFOCache',
    'LFUCache',
    'SqlCache',
    'ResultMapCache',
    'XMLParserCache',
    'PrecompiledSqlCache',
    'SecondLevelCache',
    'GLOBAL_XML_CACHE',
    'GLOBAL_PRECOMPILED_CACHE',
    'GLOBAL_SECOND_LEVEL_CACHE'
]

# Redis缓存（可选）
try:
    from .redis_cache import RedisSecondLevelCache, create_redis_cache, SerializationType
    __all__.extend(['RedisSecondLevelCache', 'create_redis_cache', 'SerializationType'])
except ImportError:
    pass