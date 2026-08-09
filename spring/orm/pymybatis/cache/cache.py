"""
PyMyBatis缓存模块

实现多层次缓存机制：
1. XML解析缓存：项目启动仅解析一次XML，后续直接读取内存缓存
2. 预编译SQL缓存：相同SQL语句缓存prepare对象，避免重复编译
3. 二级缓存：单表查询结果内存缓存，支持过期时间、刷新机制
"""

import time
import hashlib
import logging
from typing import Dict, Any, Optional, List
from enum import Enum
from abc import abstractmethod

logger = logging.getLogger(__name__)


class CacheType(Enum):
    """缓存类型"""
    LRU = 'lru'      # 最近最少使用
    FIFO = 'fifo'    # 先进先出
    LFU = 'lfu'      # 最不经常使用


class CacheEntry:
    """缓存条目"""

    def __init__(self, key: str, value: Any, ttl: int, access_counter: int = 0):
        self.key = key
        self.value = value
        self.ttl = ttl
        self.created_at = time.time()
        self.access_count = 0
        self.last_accessed = time.time()
        self.access_counter = access_counter  # 单调递增的访问计数器

    def is_expired(self) -> bool:
        """检查缓存是否过期"""
        if self.ttl <= 0:
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self, counter: int = 0):
        """更新访问时间和计数"""
        self.access_count += 1
        self.last_accessed = time.time()
        if counter > 0:
            self.access_counter = counter


class BaseCache:
    """缓存抽象基类"""

    def __init__(self, max_size: int = 1024, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = __import__('threading').RLock()
        self._access_counter = 0  # 单调递增的访问计数器

    def _increment_counter(self) -> int:
        """递增访问计数器"""
        self._access_counter += 1
        return self._access_counter

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]

            # 检查过期
            if entry.is_expired():
                del self._cache[key]
                return None

            # 更新访问信息（使用计数器）
            entry.touch(self._increment_counter())
            return entry.value

    def put(self, key: str, value: Any) -> None:
        """设置缓存"""
        with self._lock:
            # 最大容量小于等于0时不存储
            if self.max_size <= 0:
                return

            # 如果键已存在，更新值并标记为最近访问
            if key in self._cache:
                self._cache[key].value = value
                self._cache[key].last_accessed = time.time()
                self._cache[key].access_count += 1
                self._cache[key].access_counter = self._increment_counter()
                return

            # 检查容量，需要腾出空间
            while len(self._cache) >= self.max_size:
                self._evict()

            # 创建新条目（使用当前计数器值）
            self._cache[key] = CacheEntry(key, value, self.ttl, self._increment_counter())

    def delete(self, key: str) -> None:
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def remove(self, key: str) -> None:
        """删除缓存（delete的别名）"""
        self.delete(key)

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """获取缓存大小"""
        with self._lock:
            return len(self._cache)

    @abstractmethod
    def _evict(self) -> None:
        """驱逐策略（由子类实现）"""
        pass


class LRUCache(BaseCache):
    """LRU缓存（最近最少使用）"""

    def _evict(self) -> None:
        """驱逐最久未使用的缓存（使用计数器判断）"""
        oldest_key = None
        oldest_counter = float('inf')

        for key, entry in self._cache.items():
            if entry.access_counter < oldest_counter:
                oldest_counter = entry.access_counter
                oldest_key = key

        if oldest_key:
            del self._cache[oldest_key]
            logger.debug(f"LRU缓存驱逐: {oldest_key}")


class FIFOCache(BaseCache):
    """FIFO缓存（先进先出）"""

    def _evict(self) -> None:
        """驱逐最早创建的缓存"""
        oldest_key = None
        oldest_time = float('inf')

        for key, entry in self._cache.items():
            if entry.created_at < oldest_time:
                oldest_time = entry.created_at
                oldest_key = key

        if oldest_key:
            del self._cache[oldest_key]
            logger.debug(f"FIFO缓存驱逐: {oldest_key}")


class LFUCache(BaseCache):
    """LFU缓存（最不经常使用）"""

    def _evict(self) -> None:
        """驱逐访问次数最少的缓存"""
        least_key = None
        least_count = float('inf')

        for key, entry in self._cache.items():
            if entry.access_count < least_count:
                least_count = entry.access_count
                least_key = key

        if least_key:
            del self._cache[least_key]
            logger.debug(f"LFU缓存驱逐: {least_key}")


class SqlCache:
    """SQL查询缓存"""

    def __init__(self, cache_type: str = 'lru', max_size: int = 1024, ttl: int = 3600):
        cache_classes = {
            'lru': LRUCache,
            'fifo': FIFOCache,
            'lfu': LFUCache
        }
        self.cache = cache_classes.get(cache_type, LRUCache)(max_size, ttl)

    def _generate_key(self, sql: str, params: Optional[Dict[str, Any]]) -> str:
        """生成缓存key"""
        key = f"{sql}"
        if params:
            # 对参数进行排序后拼接，确保相同参数生成相同key
            sorted_params = sorted(params.items())
            key += str(sorted_params)
        return hashlib.sha256(key.encode()).hexdigest()

    def get(self, sql: str, params: Optional[Dict[str, Any]]) -> Optional[Any]:
        """获取SQL查询缓存"""
        key = self._generate_key(sql, params)
        return self.cache.get(key)

    def put(self, sql: str, params: Optional[Dict[str, Any]], value: Any) -> None:
        """设置SQL查询缓存"""
        key = self._generate_key(sql, params)
        self.cache.put(key, value)

    def delete(self, sql: str, params: Optional[Dict[str, Any]]) -> None:
        """删除SQL查询缓存"""
        key = self._generate_key(sql, params)
        self.cache.delete(key)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()

    def size(self) -> int:
        """获取缓存大小"""
        return self.cache.size()


class ResultMapCache:
    """结果映射缓存"""

    def __init__(self, max_size: int = 100, ttl: int = 86400):
        self.cache = LRUCache(max_size, ttl)

    def get(self, key: str) -> Optional[Any]:
        """获取结果映射缓存"""
        return self.cache.get(key)

    def put(self, key: str, value: Any) -> None:
        """设置结果映射缓存"""
        self.cache.put(key, value)

    def delete(self, key: str) -> None:
        """删除结果映射缓存"""
        self.cache.delete(key)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()


class XMLParserCache:
    """XML解析缓存"""

    def __init__(self, max_size: int = 50, ttl: int = 86400):
        self.cache = LRUCache(max_size, ttl)
        self._parsed_files: Dict[str, float] = {}  # 文件路径 -> 解析时间

    def get(self, file_path: str) -> Optional[Any]:
        """获取XML解析缓存"""
        return self.cache.get(file_path)

    def put(self, file_path: str, value: Any) -> None:
        """设置XML解析缓存"""
        self.cache.put(file_path, value)
        self._parsed_files[file_path] = time.time()

    def delete(self, file_path: str) -> None:
        """删除XML解析缓存"""
        self.cache.delete(file_path)
        self._parsed_files.pop(file_path, None)

    def is_cached(self, file_path: str) -> bool:
        """检查文件是否已缓存"""
        return file_path in self._parsed_files

    def get_parse_time(self, file_path: str) -> Optional[float]:
        """获取文件解析时间"""
        return self._parsed_files.get(file_path)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()
        self._parsed_files.clear()


class PrecompiledSqlCache:
    """预编译SQL缓存"""

    def __init__(self, max_size: int = 500, ttl: int = 3600):
        self.cache = LRUCache(max_size, ttl)

    def _generate_key(self, sql: str) -> str:
        """生成预编译SQL缓存key"""
        return hashlib.sha256(sql.encode()).hexdigest()

    def get(self, sql: str) -> Optional[Any]:
        """获取预编译SQL缓存"""
        key = self._generate_key(sql)
        return self.cache.get(key)

    def put(self, sql: str, prepared_stmt: Any) -> None:
        """设置预编译SQL缓存"""
        key = self._generate_key(sql)
        self.cache.put(key, prepared_stmt)

    def delete(self, sql: str) -> None:
        """删除预编译SQL缓存"""
        key = self._generate_key(sql)
        self.cache.delete(key)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()


class SecondLevelCache:
    """二级缓存（跨会话缓存）"""

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self.cache = LRUCache(max_size, ttl)
        self._table_cache_map: Dict[str, List[str]] = {}  # 表名 -> 缓存key列表

    def _generate_key(self, table_name: str, params: Dict[str, Any]) -> str:
        """生成缓存key"""
        key = f"{table_name}_"
        if params:
            sorted_params = sorted(params.items())
            key += str(sorted_params)
        return hashlib.sha256(key.encode()).hexdigest()

    def get(self, table_name: str, params: Dict[str, Any]) -> Optional[Any]:
        """获取二级缓存"""
        key = self._generate_key(table_name, params)
        return self.cache.get(key)

    def put(self, table_name: str, params: Dict[str, Any], value: Any) -> None:
        """设置二级缓存"""
        key = self._generate_key(table_name, params)
        self.cache.put(key, value)

        # 记录表名对应的缓存key
        if table_name not in self._table_cache_map:
            self._table_cache_map[table_name] = []
        self._table_cache_map[table_name].append(key)

    def invalidate_table(self, table_name: str) -> None:
        """使指定表的所有缓存失效"""
        if table_name in self._table_cache_map:
            for key in self._table_cache_map[table_name]:
                self.cache.delete(key)
            del self._table_cache_map[table_name]
            logger.debug(f"二级缓存失效: 表 {table_name}")

    def invalidate_all(self) -> None:
        """使所有缓存失效"""
        self.cache.clear()
        self._table_cache_map.clear()

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()
        self._table_cache_map.clear()


# 全局缓存实例
GLOBAL_XML_CACHE = XMLParserCache()
GLOBAL_PRECOMPILED_CACHE = PrecompiledSqlCache()
GLOBAL_SECOND_LEVEL_CACHE = SecondLevelCache()
