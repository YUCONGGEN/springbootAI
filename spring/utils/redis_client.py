"""
Redis客户端工具类
提供分布式锁、持久化存储等企业级功能
"""
import json
import time
import uuid
from typing import Any, Optional

try:
    from redis.exceptions import RedisError
except ImportError:
    class RedisError(Exception):
        """Fallback used when the optional Redis dependency is unavailable."""


class RedisClient:
    """Redis客户端封装"""

    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0, password: str = None):
        self._client = None
        self.configure(host=host, port=port, db=db, password=password)

    def configure(self, host: str, port: int, db: int, password: str = None) -> None:
        self.host = host
        self.port = int(port)
        self.db = int(db)
        self.password = password
        self._client = None

    def connect(self, strict: bool = False) -> None:
        """连接Redis"""
        try:
            from redis import Redis
            
            self._client = Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
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
        end_time = time.time() + wait_timeout
        
        while time.time() < end_time:
            # 使用SET NX EX命令获取锁
            result = client.set(f"lock:{key}", lock_id, nx=True, ex=timeout)
            if result:
                return lock_id
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
        result = client.eval(script, 1, f"lock:{key}", lock_id)
        return result == 1
    
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
        config: Redis配置字典，包含host, port, db, password等
    """
    redis_client.configure(
        host=config.get('host', 'localhost'),
        port=config.get('port', 6379),
        db=config.get('db', 0),
        password=config.get('password')
    )
    redis_client.connect(strict=True)
