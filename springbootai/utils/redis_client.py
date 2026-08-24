"""
Redis客户端工具类
提供分布式锁、持久化存储等企业级功能
"""
import json
import time
import uuid
import logging
from typing import Any

try:
    from redis.exceptions import RedisError
except ImportError:
    class RedisError(Exception):
        """Fallback used when the optional Redis dependency is unavailable."""


logger = logging.getLogger("Spring.Redis")


class RedisClient:
    """Redis客户端封装"""

    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0,
                 password: str = None, timeout: int = 5):
        self._client = None
        self.configure(host=host, port=port, db=db, password=password, timeout=timeout)

    def configure(self, host: str, port: int, db: int, password: str = None,
                  timeout: int = 5) -> None:
        """配置 Redis 连接参数。

        Args:
            host: 主机
            port: 端口
            db: 数据库序号
            password: 密码
            timeout: 套接字超时（秒），对齐 application.yml 的 redis.timeout（毫秒值会被
                init_redis 转换为秒）。默认 5 秒，保持向后兼容。
        """
        self.host = host
        self.port = int(port)
        self.db = int(db)
        self.password = password
        # timeout 统一为秒；application.yml 中 redis.timeout 为毫秒，init_redis 负责换算
        self.timeout = max(0.1, float(timeout))
        self._client = None

    def connect(self, strict: bool = False) -> None:
        """连接Redis"""
        try:
            from redis import Redis

            # redis-py 8 ships a default retry policy with ten connection
            # attempts.  A synchronous health check during application
            # startup would therefore block for tens of seconds when an
            # optional Redis service is down (and can make the HTTP server
            # appear hung).  Framework startup already decides whether this
            # dependency is fail-fast; the probe itself must be one bounded
            # attempt.  Keep the retry object version-compatible for older
            # redis-py releases that do not expose it.
            retry = None
            try:
                from redis.backoff import NoBackoff
                from redis.retry import Retry
                retry = Retry(NoBackoff(), retries=0)
            except (ImportError, TypeError):
                pass
            client_kwargs = {
                "host": self.host,
                "port": self.port,
                "db": self.db,
                "password": self.password,
                "decode_responses": True,
                "socket_timeout": self.timeout,
                "socket_connect_timeout": self.timeout,
            }
            if retry is not None:
                client_kwargs["retry"] = retry
            else:
                # redis-py 6+ prefers an explicit Retry object and emits a
                # deprecation warning for ``retry_on_timeout``.  Keep the
                # legacy switch only for older releases where Retry is not
                # available.
                client_kwargs["retry_on_timeout"] = False
            self._client = Redis(**client_kwargs)
            # 测试连接
            self._client.ping()
        except ImportError as exc:
            self._client = None
            if strict:
                raise RuntimeError("Redis已启用但redis依赖未安装") from exc
        except Exception as e:
            self._client = None
            if strict:
                raise ConnectionError(f"无法连接Redis: {e}") from e
    
    def get_client(self):
        """获取Redis客户端"""
        if self._client is None:
            self.connect()
        return self._client
    
    # ==================== 分布式锁 ====================
    
    def acquire_lock(self, key: str, timeout: int = 10, wait_timeout: int = 5):
        """
        获取分布式锁
        
        Args:
            key: 锁键
            timeout: 锁过期时间（秒）
            wait_timeout: 等待锁的超时时间（秒）
        
        Returns:
            锁标识（用于释放锁），获取失败返回None
        """
        client = self.get_client()
        if client is None:
            return None
        
        lock_id = str(uuid.uuid4())
        try:
            lock_ttl = max(1, int(timeout))
            wait_seconds = max(0.0, float(wait_timeout))
        except (TypeError, ValueError):
            return None
        end_time = time.monotonic() + wait_seconds

        while time.monotonic() < end_time:
            try:
                # 使用SET NX EX命令获取锁
                result = client.set(f"lock:{key}", lock_id, nx=True, ex=lock_ttl)
                if result:
                    return lock_id
            except (RedisError, TypeError, ValueError) as exc:
                logger.warning("Redis lock acquisition failed: %s", exc)
                return None
            time.sleep(0.01)  # 短暂等待后重试
        
        return None
    
    def release_lock(self, key: str, lock_id: str) -> bool:
        """
        释放分布式锁
        
        Args:
            key: 锁键
            lock_id: 锁标识
        
        Returns:
            是否成功释放
        """
        client = self.get_client()
        if client is None:
            return False
        
        # 使用Lua脚本保证原子性释放
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            result = client.eval(script, 1, f"lock:{key}", lock_id)
            return result == 1
        except (RedisError, TypeError, ValueError) as exc:
            # Lock cleanup runs from AOP ``finally`` blocks; a transient Redis
            # outage must not replace the business exception or crash the
            # request after the work has completed.
            logger.warning("Redis lock release failed: %s", exc)
            return False
    
    # ==================== 持久化存储 ====================
    
    def set_value(self, key: str, value: Any, expire: int = None) -> bool:
        """
        设置值
        
        Args:
            key: 键
            value: 值（支持任意可JSON序列化的类型）
            expire: 过期时间（秒）
        
        Returns:
            是否成功
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            if isinstance(value, (str, int, float, bool)):
                result = client.set(key, value, ex=expire)
            else:
                result = client.set(key, json.dumps(value), ex=expire)
            return result is not None
        except (RedisError, TypeError):
            return False
    
    def get_value(self, key: str) -> Any:
        """
        获取值
        
        Args:
            key: 键
        
        Returns:
            值（自动反序列化）
        """
        client = self.get_client()
        if client is None:
            return None
        
        try:
            value = client.get(key)
            if value is None:
                return None
            
            # 尝试解析为JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except RedisError:
            return None
    
    def delete_key(self, key: str) -> bool:
        """
        删除键
        
        Args:
            key: 键
        
        Returns:
            是否成功
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            result = client.delete(key)
            return result > 0
        except RedisError:
            return False
    
    def exists_key(self, key: str) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 键
        
        Returns:
            是否存在
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            return client.exists(key) > 0
        except RedisError:
            return False
    
    # ==================== 列表操作 ====================
    
    def list_push(self, key: str, value: Any) -> int:
        """
        向列表尾部添加元素
        
        Args:
            key: 键
            value: 值
        
        Returns:
            列表长度
        """
        client = self.get_client()
        if client is None:
            return 0
        
        try:
            if not isinstance(value, str):
                value = json.dumps(value)
            return client.rpush(key, value)
        except (RedisError, TypeError):
            return 0
    
    def list_range(self, key: str, start: int = 0, end: int = -1) -> list:
        """
        获取列表指定范围的元素
        
        Args:
            key: 键
            start: 起始索引
            end: 结束索引
        
        Returns:
            元素列表
        """
        client = self.get_client()
        if client is None:
            return []
        
        try:
            values = client.lrange(key, start, end)
            result = []
            for v in values:
                try:
                    result.append(json.loads(v))
                except (json.JSONDecodeError, TypeError):
                    result.append(v)
            return result
        except RedisError:
            return []
    
    def list_remove_range(self, key: str, start: int, end: int) -> int:
        """
        删除列表指定范围的元素
        
        Args:
            key: 键
            start: 起始索引
            end: 结束索引
        
        Returns:
            删除的元素数量
        """
        client = self.get_client()
        if client is None:
            return 0
        
        try:
            # 获取列表长度
            length = client.llen(key)
            if length == 0:
                return 0
            
            # 计算需要保留的元素
            result = 0
            # 删除从start到end的元素（通过截断实现）
            if start > 0:
                # 保留前start个元素
                client.ltrim(key, 0, start - 1)
                result = length - start
            elif end < length - 1:
                # 保留从end+1开始的元素
                client.ltrim(key, end + 1, -1)
                result = end + 1
            
            return result
        except RedisError:
            return 0
    
    def list_length(self, key: str) -> int:
        """
        获取列表长度
        
        Args:
            key: 键
        
        Returns:
            列表长度
        """
        client = self.get_client()
        if client is None:
            return 0
        
        try:
            return client.llen(key)
        except RedisError:
            return 0
    
    # ==================== 计数器操作 ====================
    
    def increment(self, key: str, amount: int = 1) -> int:
        """
        递增计数器
        
        Args:
            key: 键
            amount: 递增值
        
        Returns:
            递增后的值
        """
        client = self.get_client()
        if client is None:
            return 0
        
        try:
            return client.incrby(key, amount)
        except RedisError:
            return 0
    
    def decrement(self, key: str, amount: int = 1) -> int:
        """
        递减计数器
        
        Args:
            key: 键
            amount: 递减值
        
        Returns:
            递减后的值
        """
        client = self.get_client()
        if client is None:
            return 0
        
        try:
            return client.decrby(key, amount)
        except RedisError:
            return 0
    
    # ==================== Hash操作 ====================
    
    def hash_set(self, key: str, field: str, value: Any) -> bool:
        """
        设置Hash字段值
        
        Args:
            key: 键
            field: 字段名
            value: 值
        
        Returns:
            是否成功
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            if not isinstance(value, str):
                value = json.dumps(value)
            return client.hset(key, field, value) > 0
        except (RedisError, TypeError):
            return False
    
    def hash_get(self, key: str, field: str) -> Any:
        """
        获取Hash字段值
        
        Args:
            key: 键
            field: 字段名
        
        Returns:
            值
        """
        client = self.get_client()
        if client is None:
            return None
        
        try:
            value = client.hget(key, field)
            if value is None:
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except RedisError:
            return None
    
    def hash_get_all(self, key: str) -> dict:
        """
        获取Hash所有字段和值
        
        Args:
            key: 键
        
        Returns:
            字段-值字典
        """
        client = self.get_client()
        if client is None:
            return {}
        
        try:
            result = client.hgetall(key)
            for field, value in list(result.items()):
                try:
                    result[field] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
            return result
        except RedisError:
            return {}
    
    def hash_delete(self, key: str, field: str) -> bool:
        """
        删除Hash字段
        
        Args:
            key: 键
            field: 字段名
        
        Returns:
            是否成功
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            return client.hdel(key, field) > 0
        except RedisError:
            return False
    
    # ==================== 集合操作 ====================
    
    def set_add(self, key: str, value: Any) -> bool:
        """
        向集合添加元素
        
        Args:
            key: 键
            value: 值
        
        Returns:
            是否成功
        """
        client = self.get_client()
        if client is None:
            return False
        
        try:
            if not isinstance(value, str):
                value = json.dumps(value)
            return client.sadd(key, value) > 0
        except (RedisError, TypeError):
            return False
    
    def set_members(self, key: str) -> set:
        """
        获取集合所有元素
        
        Args:
            key: 键
        
        Returns:
            元素集合
        """
        client = self.get_client()
        if client is None:
            return set()
        
        try:
            members = client.smembers(key)
            result = set()
            for m in members:
                try:
                    result.add(json.loads(m))
                except (json.JSONDecodeError, TypeError):
                    result.add(m)
            return result
        except RedisError:
            return set()


# 创建全局Redis客户端实例
redis_client = RedisClient()


def init_redis(config: dict) -> None:
    """
    初始化Redis连接

    Args:
        config: Redis配置字典，包含host, port, db, password, timeout等。
            timeout 在 application.yml 中以毫秒表示（如 5000），此处换算为秒。
    """
    # redis.timeout 在 application.yml 中为毫秒（默认 5000），换算为秒
    timeout_ms = config.get('timeout', 5000)
    try:
        timeout_s = float(timeout_ms) / 1000.0
    except (ValueError, TypeError):
        timeout_s = 5.0
    redis_client.configure(
        host=config.get('host', 'localhost'),
        port=config.get('port', 6379),
        db=config.get('db', 0),
        password=config.get('password'),
        timeout=timeout_s,
    )
    redis_client.connect(strict=True)
