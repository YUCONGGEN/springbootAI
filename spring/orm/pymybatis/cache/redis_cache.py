"""
PyMyBatis Redis二级缓存模块

实现基于Redis的分布式二级缓存，支持多实例部署时的数据一致性

核心特性：
- Redis作为缓存后端
- 支持缓存过期时间
- 支持缓存失效通知（Redis Pub/Sub）
- 支持表级别的缓存失效
- 可配置的序列化方式
"""

import json
import hashlib
import logging
import time
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class SerializationType(Enum):
    """序列化类型"""
    JSON = 'json'
    PICKLE = 'pickle'


class RedisSecondLevelCache:
    """
    Redis二级缓存实现

    基于Redis实现的分布式缓存，支持多实例部署时的数据一致性。
    通过Redis Pub/Sub机制实现缓存失效通知。

    配置参数：
    - host: Redis主机地址
    - port: Redis端口
    - db: Redis数据库编号
    - password: Redis密码
    - timeout: 连接超时时间
    - ttl: 默认缓存过期时间（秒）
    - serialization: 序列化方式（json/pickle）
    - channel_prefix: Pub/Sub频道前缀
    """

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 6379,
                 db: int = 0,
                 password: Optional[str] = None,
                 timeout: int = 10,
                 ttl: int = 300,
                 serialization: str = 'json',
                 channel_prefix: str = 'pymybatis:cache:'):
        """
        初始化Redis二级缓存

        Args:
            host: Redis主机地址
            port: Redis端口
            db: Redis数据库编号
            password: Redis密码
            timeout: 连接超时时间（秒）
            ttl: 默认缓存过期时间（秒）
            serialization: 序列化方式（json/pickle）
            channel_prefix: Pub/Sub频道前缀
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.timeout = timeout
        self.ttl = ttl
        self.serialization = SerializationType(serialization.lower())
        self.channel_prefix = channel_prefix

        # Redis连接
        self._redis = None
        self._pubsub = None
        self._pubsub_thread = None

        # 本地缓存（用于减少Redis访问）
        # 修复：存储 (value, expire_ts) 元组，本地缓存有自己的 TTL，
        # 避免 Redis 键过期后本地缓存永久返回旧数据
        self._local_cache: Dict[str, tuple] = {}  # {key: (value, expire_timestamp)}
        self._local_cache_ttl = min(self.ttl, 60) if self.ttl > 0 else 60  # 本地缓存 TTL ≤ Redis TTL

        # 修复：维护 table_name → 本地缓存 key 集合的映射，
        # 用于收到表级失效通知时正确清除相关本地缓存（旧版本用 key.startswith(table_name)
        # 匹配 SHA256 哈希键，条件永远无法成立）
        self._table_key_map: Dict[str, set] = {}  # {table_name: {key1, key2, ...}}

        # 启动缓存失效通知监听器
        self._start_pubsub_listener()

    def _connect(self):
        """建立Redis连接"""
        if self._redis is None:
            try:
                import redis
                self._redis = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    socket_timeout=self.timeout,
                    decode_responses=False  # 使用字节模式
                )
                logger.info(f"Redis连接成功: {self.host}:{self.port}/{self.db}")
            except ImportError:
                raise ImportError("请安装redis: pip install redis")
            except Exception as e:
                logger.error(f"Redis连接失败: {e}")
                raise

        return self._redis

    def _serialize(self, value: Any) -> bytes:
        """序列化值"""
        if self.serialization == SerializationType.JSON:
            return json.dumps(value, ensure_ascii=False).encode('utf-8')
        else:
            import pickle
            return pickle.dumps(value)

    def _deserialize(self, value: bytes) -> Any:
        """反序列化值。

        安全加固：当 ``serialization=JSON`` 时，JSON 解码失败**不再回退 pickle**。
        旧版本在 JSON 解码失败时自动调用 ``pickle.loads()``，即使明确配置 JSON 模式，
        构造的 pickle 数据仍会被接受——攻击者/受侵入的 Redis 可借此触发 RCE。
        现在改为记录错误并返回 None，拒绝执行任何 pickle 数据。
        """
        if value is None:
            return None

        if self.serialization == SerializationType.JSON:
            try:
                return json.loads(value.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                # 安全加固：JSON 模式下禁止 pickle 回退（防止 RCE）
                # 旧版本此处调用 pickle.loads(value)，可被攻击者利用执行任意代码
                logger.error(
                    f"JSON反序列化失败，已拒绝pickle回退（安全加固）。"
                    f"数据可能被篡改或序列化配置不一致: {exc}"
                )
                return None
        else:
            import pickle
            return pickle.loads(value)

    def _generate_key(self, table_name: str, params: Dict[str, Any]) -> str:
        """
        生成缓存key

        Args:
            table_name: 表名
            params: 参数

        Returns:
            缓存key
        """
        key = f"{table_name}_"
        if params:
            sorted_params = sorted(params.items())
            key += str(sorted_params)
        return hashlib.sha256(key.encode()).hexdigest()

    def get(self, table_name: str, params: Dict[str, Any]) -> Optional[Any]:
        """
        获取缓存

        Args:
            table_name: 表名
            params: 查询参数

        Returns:
            缓存值，不存在返回None
        """
        key = self._generate_key(table_name, params)
        full_key = f"{self.channel_prefix}{key}"

        # 先从本地缓存查找（修复：检查 TTL 过期）
        if key in self._local_cache:
            value, expire_ts = self._local_cache[key]
            if time.time() < expire_ts:
                logger.debug(f"本地缓存命中: {full_key}")
                return value
            else:
                # 本地缓存已过期，删除并继续查 Redis
                del self._local_cache[key]
                # 同时从 table_key_map 中清理
                self._table_key_map.get(table_name, set()).discard(key)

        try:
            redis = self._connect()
            # 修复：检查 Redis TTL，避免返回已过期的数据
            remaining_ttl = redis.ttl(full_key)
            if remaining_ttl is not None and remaining_ttl <= 0:
                # 键已过期或不存在
                return None
            value = redis.get(full_key)
            if value is not None:
                result = self._deserialize(value)
                # 更新本地缓存（带 TTL）
                expire_ts = time.time() + self._local_cache_ttl
                self._local_cache[key] = (result, expire_ts)
                # 更新 table → key 映射
                self._table_key_map.setdefault(table_name, set()).add(key)
                logger.debug(f"Redis缓存命中: {full_key}")
                return result
        except Exception as e:
            logger.error(f"Redis缓存读取失败: {e}")

        return None

    def put(self, table_name: str, params: Dict[str, Any], value: Any) -> None:
        """
        设置缓存

        Args:
            table_name: 表名
            params: 查询参数
            value: 缓存值
        """
        key = self._generate_key(table_name, params)
        full_key = f"{self.channel_prefix}{key}"

        # 更新本地缓存（带 TTL）
        expire_ts = time.time() + self._local_cache_ttl
        self._local_cache[key] = (value, expire_ts)
        # 更新 table → key 映射
        self._table_key_map.setdefault(table_name, set()).add(key)

        try:
            redis = self._connect()
            serialized_value = self._serialize(value)

            if self.ttl > 0:
                redis.setex(full_key, self.ttl, serialized_value)
            else:
                redis.set(full_key, serialized_value)

            # 记录table_name到key的映射（用于缓存失效）
            table_key = f"{self.channel_prefix}table:{table_name}"
            redis.sadd(table_key, key)

            logger.debug(f"Redis缓存设置成功: {full_key}")
        except Exception as e:
            logger.error(f"Redis缓存写入失败: {e}")

    def invalidate_table(self, table_name: str) -> None:
        """
        使指定表的所有缓存失效（广播通知）

        Args:
            table_name: 表名
        """
        try:
            redis = self._connect()

            # 获取该表所有缓存key
            table_key = f"{self.channel_prefix}table:{table_name}"
            keys = redis.smembers(table_key)

            # 删除所有相关缓存
            for key in keys:
                full_key = f"{self.channel_prefix}{key.decode()}"
                redis.delete(full_key)
                # 更新本地缓存
                self._local_cache.pop(key.decode(), None)

            # 修复：清理 table_key_map 中的映射
            self._table_key_map.pop(table_name, None)

            # 删除表映射
            redis.delete(table_key)

            # 发布缓存失效通知
            channel = f"{self.channel_prefix}invalidate"
            message = json.dumps({'table_name': table_name})
            redis.publish(channel, message)

            logger.info(f"Redis缓存失效: 表 {table_name}，共 {len(keys)} 个缓存项")
        except Exception as e:
            logger.error(f"Redis缓存失效失败: {e}")

    def invalidate_key(self, table_name: str, params: Dict[str, Any]) -> None:
        """
        使指定缓存项失效

        Args:
            table_name: 表名
            params: 查询参数
        """
        key = self._generate_key(table_name, params)
        full_key = f"{self.channel_prefix}{key}"

        # 更新本地缓存
        self._local_cache.pop(key, None)
        self._table_key_map.get(table_name, set()).discard(key)

        try:
            redis = self._connect()
            redis.delete(full_key)

            # 从表映射中移除
            table_key = f"{self.channel_prefix}table:{table_name}"
            redis.srem(table_key, key)

            logger.debug(f"Redis缓存项失效: {full_key}")
        except Exception as e:
            logger.error(f"Redis缓存项失效失败: {e}")

    def invalidate_all(self) -> None:
        """使所有缓存失效"""
        try:
            redis = self._connect()

            # 获取所有缓存key
            pattern = f"{self.channel_prefix}*"
            keys = redis.keys(pattern)

            # 删除所有缓存
            if keys:
                redis.delete(*keys)

            # 清空本地缓存
            self._local_cache.clear()
            self._table_key_map.clear()

            # 发布缓存失效通知
            channel = f"{self.channel_prefix}invalidate"
            message = json.dumps({'table_name': '__ALL__'})
            redis.publish(channel, message)

            logger.info(f"Redis缓存全部失效，共 {len(keys)} 个缓存项")
        except Exception as e:
            logger.error(f"Redis缓存全部失效失败: {e}")

    def clear(self) -> None:
        """清空缓存（同invalidate_all）"""
        self.invalidate_all()

    def size(self) -> int:
        """获取缓存大小"""
        try:
            redis = self._connect()
            pattern = f"{self.channel_prefix}[0-9a-f]*"
            keys = redis.keys(pattern)
            return len(keys)
        except Exception as e:
            logger.error(f"Redis缓存大小获取失败: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        try:
            redis = self._connect()
            info = redis.info()

            return {
                'type': 'redis',
                'host': self.host,
                'port': self.port,
                'db': self.db,
                'ttl': self.ttl,
                'serialization': self.serialization.value,
                'local_cache_size': len(self._local_cache),
                'redis_keys_count': self.size(),
                'redis_info': {
                    'used_memory': info.get('used_memory_human', 'N/A'),
                    'used_cpu_sys': info.get('used_cpu_sys', 'N/A'),
                    'connected_clients': info.get('connected_clients', 'N/A'),
                    'keyspace_hits': info.get('keyspace_hits', 'N/A'),
                    'keyspace_misses': info.get('keyspace_misses', 'N/A')
                }
            }
        except Exception as e:
            logger.error(f"Redis缓存统计获取失败: {e}")
            return {
                'type': 'redis',
                'host': self.host,
                'port': self.port,
                'db': self.db,
                'ttl': self.ttl,
                'serialization': self.serialization.value,
                'local_cache_size': len(self._local_cache),
                'error': str(e)
            }

    def _start_pubsub_listener(self):
        """启动缓存失效通知监听器（含自动重连）"""
        if self._pubsub_thread is not None:
            return

        try:
            import threading

            def listener():
                channel = f"{self.channel_prefix}invalidate"
                # 修复：添加重连机制，Redis 断线时自动重连
                while True:
                    try:
                        redis = self._connect()
                        self._pubsub = redis.pubsub()
                        self._pubsub.subscribe(channel)
                        logger.info(f"Redis缓存失效通知监听器已启动: {channel}")

                        for message in self._pubsub.listen():
                            if message['type'] == 'message':
                                try:
                                    data = json.loads(message['data'].decode('utf-8'))
                                    table_name = data.get('table_name')

                                    if table_name == '__ALL__':
                                        # 全部失效
                                        self._local_cache.clear()
                                        self._table_key_map.clear()
                                        logger.info("收到缓存全部失效通知")
                                    else:
                                        # 修复：用 table_key_map 查找相关本地缓存 key
                                        # 旧版本用 key.startswith(table_name) 匹配 SHA256 哈希键，
                                        # 条件永远无法成立，导致跨实例失效不工作
                                        keys_to_remove = list(
                                            self._table_key_map.get(table_name, set())
                                        )
                                        for key in keys_to_remove:
                                            self._local_cache.pop(key, None)
                                        self._table_key_map.pop(table_name, None)
                                        logger.info(f"收到缓存失效通知: 表 {table_name}，"
                                                    f"清除 {len(keys_to_remove)} 个本地缓存项")
                                except Exception as e:
                                    logger.error(f"处理缓存失效通知失败: {e}")
                    except Exception as e:
                        logger.error(f"Redis pubsub 监听器异常，5秒后重连: {e}")
                        import time as _time
                        _time.sleep(5)  # 等待后重连

            self._pubsub_thread = threading.Thread(target=listener, daemon=True)
            self._pubsub_thread.start()
        except Exception as e:
            logger.error(f"启动缓存失效通知监听器失败: {e}")

    def close(self):
        """关闭Redis连接"""
        if self._pubsub:
            self._pubsub.close()

        if self._redis:
            self._redis.close()
            logger.info("Redis连接已关闭")

    def __del__(self):
        """析构函数，确保连接被关闭"""
        self.close()


def create_redis_cache(config: Dict[str, Any]) -> RedisSecondLevelCache:
    """
    根据配置创建Redis缓存实例

    Args:
        config: Redis配置字典

    Returns:
        Redis缓存实例
    """
    return RedisSecondLevelCache(
        host=config.get('host', 'localhost'),
        port=config.get('port', 6379),
        db=config.get('db', 0),
        password=config.get('password'),
        timeout=config.get('timeout', 10),
        ttl=config.get('ttl', 300),
        serialization=config.get('serialization', 'json'),
        channel_prefix=config.get('channel_prefix', 'pymybatis:cache:')
    )
