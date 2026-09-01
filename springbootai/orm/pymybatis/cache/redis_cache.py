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
import threading
import re
from collections import OrderedDict
from typing import Dict, Any, Optional
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
                 channel_prefix: str = 'pymybatis:cache:',
                 max_local_entries: int = 10000):
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
        self.port = int(port)
        self.db = int(db)
        self.password = password
        self.timeout = min(60.0, max(0.1, float(timeout)))
        self.ttl = max(0, int(ttl))
        self.max_local_entries = max(1, min(1_000_000, int(max_local_entries)))
        self.serialization = SerializationType(serialization.lower())
        self.channel_prefix = channel_prefix

        # Redis连接
        self._redis = None
        self._pubsub = None
        self._pubsub_thread = None
        self._closed = False
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._connection_lock = threading.Lock()
        if self.serialization == SerializationType.PICKLE:
            raise ValueError(
                "serialization='pickle' is disabled because Redis values can be "
                "modified outside this process; use JSON serialization"
            )

        # 本地缓存（用于减少Redis访问）
        # 修复：存储 (value, expire_ts) 元组，本地缓存有自己的 TTL，
        # 避免 Redis 键过期后本地缓存永久返回旧数据
        self._local_cache: "OrderedDict[str, tuple]" = OrderedDict()
        self._local_cache_ttl = min(self.ttl, 60) if self.ttl > 0 else 60  # 本地缓存 TTL ≤ Redis TTL

        # 修复：维护 table_name → 本地缓存 key 集合的映射，
        # 用于收到表级失效通知时正确清除相关本地缓存（旧版本用 key.startswith(table_name)
        # 匹配 SHA256 哈希键，条件永远无法成立）
        self._table_key_map: Dict[str, set] = {}  # {table_name: {key1, key2, ...}}

        # 启动缓存失效通知监听器
        self._start_pubsub_listener()

    def _local_put(self, table_name: str, key: str, value: Any) -> None:
        with self._state_lock:
            self._local_cache[key] = (
                value, time.time() + self._local_cache_ttl
            )
            self._local_cache.move_to_end(key)
            self._table_key_map.setdefault(table_name, set()).add(key)
            while len(self._local_cache) > self.max_local_entries:
                evicted, _ = self._local_cache.popitem(last=False)
                for table, keys in list(self._table_key_map.items()):
                    keys.discard(evicted)
                    if not keys:
                        self._table_key_map.pop(table, None)

    def _local_invalidate_table(self, table_name: str) -> int:
        with self._state_lock:
            keys = self._table_key_map.pop(table_name, set())
            for key in keys:
                self._local_cache.pop(key, None)
            return len(keys)

    def _connect(self):
        """建立Redis连接"""
        if self._closed:
            raise RuntimeError("Redis cache is closed")
        if self._redis is None:
            with self._connection_lock:
                if self._redis is not None:
                    return self._redis
                if self._closed:
                    raise RuntimeError("Redis cache is closed")
                self._redis = self._create_redis_connection()
        return self._redis

    def _create_redis_connection(self):
        try:
            import redis
            client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout,
                decode_responses=False,
                health_check_interval=30,
            )
            client.ping()
            logger.info("Redis二级缓存连接成功")
            return client
        except ImportError:
            raise ImportError("请安装redis: pip install redis")
        except Exception as exc:
            logger.error("Redis二级缓存连接失败 (%s)", type(exc).__name__)
            raise

    def _serialize(self, value: Any) -> bytes:
        """序列化值"""
        if self.serialization == SerializationType.JSON:
            return json.dumps(value, ensure_ascii=False).encode('utf-8')
        raise ValueError("only JSON cache serialization is supported")

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
        raise ValueError("only JSON cache serialization is supported")

    def _generate_key(self, table_name: str, params: Dict[str, Any]) -> str:
        """
        生成缓存key

        Args:
            table_name: 表名
            params: 参数

        Returns:
            缓存key
        """
        if not isinstance(table_name, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,128}", table_name
        ):
            raise ValueError("table_name contains unsafe characters")
        try:
            encoded_params = json.dumps(
                params or {}, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("cache params must be JSON serializable") from exc
        key = f"{table_name}\n{encoded_params}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

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
        with self._state_lock:
            cached = self._local_cache.get(key)
            if cached is not None:
                value, expire_ts = cached
                if time.time() < expire_ts:
                    self._local_cache.move_to_end(key)
                    logger.debug("本地二级缓存命中")
                    return value
                self._local_cache.pop(key, None)
                self._table_key_map.get(table_name, set()).discard(key)

        try:
            redis = self._connect()
            value = redis.get(full_key)
            if value is not None:
                result = self._deserialize(value)
                if result is None:
                    return None
                self._local_put(table_name, key, result)
                logger.debug("Redis二级缓存命中")
                return result
        except Exception as exc:
            logger.error("Redis二级缓存读取失败 (%s)", type(exc).__name__)

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

        try:
            redis = self._connect()
            serialized_value = self._serialize(value)
            table_key = f"{self.channel_prefix}table:{table_name}"
            pipe = redis.pipeline(transaction=True)
            if self.ttl > 0:
                pipe.setex(full_key, self.ttl, serialized_value)
            else:
                pipe.set(full_key, serialized_value)
            pipe.sadd(table_key, key)
            if self.ttl > 0:
                # Do not retain stale table indexes forever.
                pipe.expire(table_key, self.ttl + self._local_cache_ttl)
            pipe.execute()
            # Only expose the value locally after the distributed write wins.
            self._local_put(table_name, key, value)
            logger.debug("Redis二级缓存设置成功")
        except Exception as exc:
            logger.error("Redis二级缓存写入失败 (%s)", type(exc).__name__)

    def invalidate_table(self, table_name: str) -> None:
        """
        使指定表的所有缓存失效（广播通知）

        Args:
            table_name: 表名
        """
        local_count = self._local_invalidate_table(table_name)
        try:
            redis = self._connect()

            # 获取该表所有缓存key
            table_key = f"{self.channel_prefix}table:{table_name}"
            keys = redis.smembers(table_key)

            decoded = [
                key.decode("utf-8") if isinstance(key, bytes) else str(key)
                for key in keys
            ]
            pipe = redis.pipeline(transaction=True)
            if decoded:
                pipe.delete(*[
                    f"{self.channel_prefix}{key}" for key in decoded
                ])
            pipe.delete(table_key)
            channel = f"{self.channel_prefix}invalidate"
            message = json.dumps({'table_name': table_name})
            pipe.publish(channel, message)
            pipe.execute()

            logger.info(
                "Redis表缓存失效完成，远程=%d，本地=%d", len(keys), local_count
            )
        except Exception as exc:
            logger.error("Redis表缓存失效失败 (%s)", type(exc).__name__)

    def invalidate_key(self, table_name: str, params: Dict[str, Any]) -> None:
        """
        使指定缓存项失效

        Args:
            table_name: 表名
            params: 查询参数
        """
        key = self._generate_key(table_name, params)
        full_key = f"{self.channel_prefix}{key}"

        with self._state_lock:
            self._local_cache.pop(key, None)
            self._table_key_map.get(table_name, set()).discard(key)

        try:
            redis = self._connect()
            redis.delete(full_key)

            # 从表映射中移除
            table_key = f"{self.channel_prefix}table:{table_name}"
            redis.srem(table_key, key)

            logger.debug(f"Redis缓存项失效: {full_key}")
        except Exception as exc:
            logger.error("Redis缓存项失效失败 (%s)", type(exc).__name__)

    def invalidate_all(self) -> None:
        """使所有缓存失效"""
        with self._state_lock:
            self._local_cache.clear()
            self._table_key_map.clear()
        try:
            redis = self._connect()
            pattern = f"{self.channel_prefix}*"
            deleted = 0
            batch = []
            for key in redis.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += int(redis.delete(*batch) or 0)
                    batch = []
            if batch:
                deleted += int(redis.delete(*batch) or 0)
            channel = f"{self.channel_prefix}invalidate"
            message = json.dumps({'table_name': '__ALL__'})
            redis.publish(channel, message)
            logger.info("Redis缓存全部失效，共 %d 个缓存项", deleted)
        except Exception as exc:
            logger.error("Redis缓存全部失效失败 (%s)", type(exc).__name__)

    def clear(self) -> None:
        """清空缓存（同invalidate_all）"""
        self.invalidate_all()

    def size(self) -> int:
        """获取缓存大小"""
        try:
            redis = self._connect()
            pattern = f"{self.channel_prefix}[0-9a-f]*"
            return sum(1 for _ in redis.scan_iter(match=pattern, count=500))
        except Exception as exc:
            logger.error("Redis缓存大小获取失败 (%s)", type(exc).__name__)
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
                'local_cache_size': self._local_size(),
                'redis_keys_count': self.size(),
                'redis_info': {
                    'used_memory': info.get('used_memory_human', 'N/A'),
                    'used_cpu_sys': info.get('used_cpu_sys', 'N/A'),
                    'connected_clients': info.get('connected_clients', 'N/A'),
                    'keyspace_hits': info.get('keyspace_hits', 'N/A'),
                    'keyspace_misses': info.get('keyspace_misses', 'N/A')
                }
            }
        except Exception as exc:
            logger.error("Redis缓存统计获取失败 (%s)", type(exc).__name__)
            return {
                'type': 'redis',
                'host': self.host,
                'port': self.port,
                'db': self.db,
                'ttl': self.ttl,
                'serialization': self.serialization.value,
                'local_cache_size': self._local_size(),
                'error': type(exc).__name__,
            }

    def _local_size(self) -> int:
        with self._state_lock:
            return len(self._local_cache)

    def _start_pubsub_listener(self):
        """启动缓存失效通知监听器（含自动重连）"""
        if self._pubsub_thread is not None:
            return

        try:
            def listener():
                channel = f"{self.channel_prefix}invalidate"
                reconnect_delay = 0.25
                while not self._stop_event.is_set():
                    pubsub = None
                    try:
                        redis = self._connect()
                        pubsub = redis.pubsub(ignore_subscribe_messages=True)
                        self._pubsub = pubsub
                        pubsub.subscribe(channel)
                        reconnect_delay = 0.25
                        logger.info("Redis缓存失效通知监听器已启动")
                        while not self._stop_event.is_set():
                            message = pubsub.get_message(timeout=1.0)
                            if not message or message.get('type') != 'message':
                                continue
                            try:
                                raw = message.get('data', b'')
                                if isinstance(raw, bytes):
                                    if len(raw) > 65536:
                                        raise ValueError("invalid cache message size")
                                    raw = raw.decode('utf-8')
                                data = json.loads(raw)
                                table_name = data.get('table_name')
                                if table_name == '__ALL__':
                                    with self._state_lock:
                                        self._local_cache.clear()
                                        self._table_key_map.clear()
                                elif isinstance(table_name, str) and table_name:
                                    self._local_invalidate_table(table_name)
                            except Exception as exc:
                                logger.error(
                                    "处理缓存失效通知失败 (%s)", type(exc).__name__
                                )
                    except Exception as exc:
                        if not self._stop_event.is_set():
                            logger.error(
                                "Redis pubsub 监听器异常，将重连 (%s)",
                                type(exc).__name__,
                            )
                            self._stop_event.wait(reconnect_delay)
                            reconnect_delay = min(5.0, reconnect_delay * 2)
                    finally:
                        if pubsub is not None:
                            try:
                                pubsub.close()
                            except Exception:
                                pass
                        if self._pubsub is pubsub:
                            self._pubsub = None

            self._pubsub_thread = threading.Thread(target=listener, daemon=True)
            self._pubsub_thread.start()
        except Exception as exc:
            logger.error("启动缓存失效通知监听器失败 (%s)", type(exc).__name__)

    def close(self):
        """关闭Redis连接"""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
            pubsub = self._pubsub
            redis = self._redis
        if pubsub:
            try:
                pubsub.close()
            except Exception:
                pass
        thread = self._pubsub_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=min(2.0, self.timeout + 0.1))
        if redis:
            try:
                redis.close()
            finally:
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
        channel_prefix=config.get('channel_prefix', 'pymybatis:cache:'),
        max_local_entries=config.get('max_local_entries', 10000),
    )
