"""
重放攻击防护 (Replay Attack Protection)

防护机制:
- Nonce + Timestamp 双重校验
- 时间戳窗口 (默认5分钟)
- Nonce 去重缓存 (Redis或内存)
- 请求签名验证
"""

import time
import hashlib
import hmac
import logging
import threading
from typing import Optional, Dict, Tuple
from collections import OrderedDict

logger = logging.getLogger("Spring.Security.Replay")

# 默认时间戳窗口（秒）
DEFAULT_TIMESTAMP_WINDOW = 300
# Nonce缓存最大容量（LRU）
DEFAULT_NONCE_CACHE_SIZE = 100000
# Nonce过期清理间隔（秒）
NONCE_CLEANUP_INTERVAL = 60


class NonceCache:
    """线程安全的LRU Nonce缓存"""

    def __init__(self, max_size: int = DEFAULT_NONCE_CACHE_SIZE, ttl: int = DEFAULT_TIMESTAMP_WINDOW):
        self._cache: "OrderedDict[str, float]" = OrderedDict()
        # Zero/negative values make the eviction loop call ``popitem`` on an
        # empty cache.  Normalize malformed configuration to a minimal usable
        # cache so replay validation fails closed without an internal crash.
        try:
            self._max_size = max(1, int(max_size))
        except (TypeError, ValueError):
            self._max_size = DEFAULT_NONCE_CACHE_SIZE
        try:
            self._ttl = max(1, int(ttl))
        except (TypeError, ValueError):
            self._ttl = DEFAULT_TIMESTAMP_WINDOW
        self._lock = threading.RLock()
        self._last_cleanup = time.monotonic()

    def _cleanup_expired(self):
        """清理过期的nonce"""
        now = time.time()
        if time.monotonic() - self._last_cleanup < NONCE_CLEANUP_INTERVAL:
            # 即使到了清理间隔，也只清理部分避免阻塞
            expired_keys = []
            for k, ts in list(self._cache.items()):
                if now - ts > self._ttl:
                    expired_keys.append(k)
                else:
                    break  # OrderedDict按插入顺序，前面过期后面也应该过期
            for k in expired_keys:
                self._cache.pop(k, None)
        self._last_cleanup = time.monotonic()

    def check_and_add(self, nonce: str) -> bool:
        """
        检查nonce是否已存在，不存在则添加

        Returns:
            True 如果nonce有效（未重复），False 如果重复
        """
        with self._lock:
            self._cleanup_expired()

            if nonce in self._cache:
                return False

            # 容量控制
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

            self._cache[nonce] = time.time()
            return True


class RedisNonceCache:
    """基于Redis的分布式Nonce缓存"""

    def __init__(self, redis_client, key_prefix: str = "springpy:nonce:", ttl: int = DEFAULT_TIMESTAMP_WINDOW):
        self._redis = redis_client
        self._prefix = key_prefix
        try:
            self._ttl = max(1, int(ttl))
        except (TypeError, ValueError):
            self._ttl = DEFAULT_TIMESTAMP_WINDOW

    def check_and_add(self, nonce: str) -> bool:
        key = f"{self._prefix}{nonce}"
        try:
            # SET NX: 仅在key不存在时设置，成功返回True（nonce有效）
            return bool(self._redis.set(key, '1', ex=self._ttl, nx=True))
        except Exception as e:
            logger.warning(f"Redis nonce check failed, falling back to allow: {e}")
            return True  # Redis故障时降级为允许（由timestamp校验兜底）


class ReplayProtection:
    """
    重放攻击保护器

    Usage:
        protector = ReplayProtection(secret_key="your-secret")
        is_valid, reason = protector.validate_request(
            timestamp=request.headers.get("X-Timestamp"),
            nonce=request.headers.get("X-Nonce"),
            signature=request.headers.get("X-Signature"),
            body=request.body,
        )
    """

    def __init__(self, secret_key: str,
                 timestamp_window: int = DEFAULT_TIMESTAMP_WINDOW,
                 nonce_cache=None,
                 redis_client=None):
        if not isinstance(secret_key, str) or not secret_key:
            raise ValueError("secret_key must be a non-empty string")
        self.secret_key = secret_key.encode('utf-8')
        try:
            self.timestamp_window = max(1, int(timestamp_window))
        except (TypeError, ValueError):
            self.timestamp_window = DEFAULT_TIMESTAMP_WINDOW

        if nonce_cache:
            self.nonce_cache = nonce_cache
        elif redis_client:
            self.nonce_cache = RedisNonceCache(redis_client, ttl=timestamp_window)
        else:
            self.nonce_cache = NonceCache(ttl=timestamp_window)

    def generate_signature(self, timestamp: str, nonce: str, body: str = "",
                           method: str = "", path: str = "") -> str:
        """
        生成请求签名

        签名字符串: METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
        """
        body_hash = hashlib.sha256(body.encode('utf-8') if isinstance(body, str) else body).hexdigest()
        message = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"
        return hmac.new(self.secret_key, message.encode('utf-8'), hashlib.sha256).hexdigest()

    def validate_request(self, timestamp: str, nonce: str,
                         signature: str = "", body: str = "",
                         method: str = "", path: str = "") -> Tuple[bool, str]:
        """
        验证请求是否为重放攻击

        Args:
            timestamp: 请求时间戳（毫秒或秒，自动检测）
            nonce: 唯一请求标识
            signature: 请求签名（可选）
            body: 请求体（用于签名验证）
            method: HTTP方法
            path: 请求路径

        Returns:
            (is_valid, reason)
        """
        # 1. 验证时间戳
        try:
            ts = int(timestamp)
            # 自动检测毫秒/秒
            if ts > 1e12:
                ts = ts / 1000
            now = time.time()
            if abs(now - ts) > self.timestamp_window:
                return False, f"Timestamp expired: window={self.timestamp_window}s, diff={abs(now - ts):.1f}s"
        except (ValueError, TypeError):
            return False, "Invalid timestamp format"

        # 2. 验证Nonce
        if not isinstance(nonce, str) or len(nonce) < 8:
            return False, "Invalid or missing nonce (minimum 8 characters)"

        if not self.nonce_cache.check_and_add(nonce):
            logger.warning(f"Replay attack detected: duplicate nonce {nonce[:8]}***")
            return False, "Duplicate nonce detected (possible replay attack)"

        # 3. 验证签名（如果提供）
        if signature:
            expected_sig = self.generate_signature(str(timestamp), nonce, body, method, path)
            if not hmac.compare_digest(expected_sig, signature):
                return False, "Invalid signature"

        return True, "OK"

    def validate_headers(self, headers: Dict[str, str], body: str = "",
                         method: str = "", path: str = "") -> Tuple[bool, str]:
        """从HTTP头验证请求"""
        return self.validate_request(
            timestamp=headers.get("x-timestamp", headers.get("X-Timestamp", "")),
            nonce=headers.get("x-nonce", headers.get("X-Nonce", "")),
            signature=headers.get("x-signature", headers.get("X-Signature", "")),
            body=body,
            method=method,
            path=path,
        )


def create_replay_protection(secret_key: str = None, redis_client=None,
                             **kwargs) -> Optional[ReplayProtection]:
    """
    工厂方法创建重放保护器

    如果没有secret_key则返回None（不启用重放防护）
    """
    if not secret_key:
        # 尝试从配置获取
        try:
            from springbootai.security.secret_manager import SecretManager
            secret_key = SecretManager().get_jwt_secret()
        except Exception:
            return None
    if not secret_key:
        return None
    return ReplayProtection(secret_key, redis_client=redis_client, **kwargs)
