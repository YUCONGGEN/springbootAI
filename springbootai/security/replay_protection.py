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
import re
from typing import Optional, Dict, Tuple
from collections import OrderedDict

logger = logging.getLogger("Spring.Security.Replay")

# 默认时间戳窗口（秒）
DEFAULT_TIMESTAMP_WINDOW = 300
# Nonce缓存最大容量（LRU）
DEFAULT_NONCE_CACHE_SIZE = 100000
# Nonce过期清理间隔（秒）
NONCE_CLEANUP_INTERVAL = 60
MIN_SECRET_BYTES = 32
MAX_NONCE_LENGTH = 256
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


class ReplayProtectionUnavailable(RuntimeError):
    """The shared replay store is unavailable, so validation cannot be safe."""


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
        # OrderedDict is oldest-first, so this stops at the first live item and
        # also permits a nonce to be reused immediately after its configured TTL.
        expired_keys = []
        for k, ts in self._cache.items():
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
        except Exception as exc:
            logger.error(
                "Redis nonce check failed; rejecting request (%s)",
                type(exc).__name__,
            )
            raise ReplayProtectionUnavailable("distributed nonce store unavailable") from exc


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
                 redis_client=None,
                 require_signature: bool = True,
                 max_nonce_length: int = MAX_NONCE_LENGTH,
                 max_body_bytes: int = DEFAULT_MAX_BODY_BYTES):
        if not isinstance(secret_key, str) or not secret_key:
            raise ValueError("secret_key must be a non-empty string")
        self.secret_key = secret_key.encode('utf-8')
        if len(self.secret_key) < MIN_SECRET_BYTES:
            raise ValueError(
                f"secret_key must contain at least {MIN_SECRET_BYTES} UTF-8 bytes"
            )
        self.require_signature = bool(require_signature)
        try:
            self.max_nonce_length = min(MAX_NONCE_LENGTH, max(8, int(max_nonce_length)))
        except (TypeError, ValueError):
            self.max_nonce_length = MAX_NONCE_LENGTH
        try:
            self.max_body_bytes = min(
                100 * 1024 * 1024, max(1, int(max_body_bytes))
            )
        except (TypeError, ValueError):
            self.max_body_bytes = DEFAULT_MAX_BODY_BYTES
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
        if not isinstance(body, (str, bytes, bytearray)):
            raise TypeError("body must be str or bytes")
        body_bytes = body.encode('utf-8') if isinstance(body, str) else bytes(body)
        body_hash = hashlib.sha256(body_bytes).hexdigest()
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
            signature: 请求签名（默认必需；require_signature=False 时可选）
            body: 请求体（用于签名验证）
            method: HTTP方法
            path: 请求路径

        Returns:
            (is_valid, reason)
        """
        # 1. 验证时间戳
        if not isinstance(timestamp, str) or len(timestamp) > 20:
            return False, "Invalid timestamp format"
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
        if (
            not isinstance(nonce, str)
            or not 8 <= len(nonce) <= self.max_nonce_length
            or not re.fullmatch(r"[A-Za-z0-9._~-]+", nonce)
        ):
            return False, (
                f"Invalid or missing nonce (8-{self.max_nonce_length} URL-safe characters)"
            )

        if not isinstance(method, str) or len(method) > 32 or "\n" in method or "\r" in method:
            return False, "Invalid HTTP method"
        if not isinstance(path, str) or len(path.encode("utf-8")) > 8192 or "\n" in path or "\r" in path:
            return False, "Invalid request path"
        if not isinstance(body, (str, bytes, bytearray)):
            return False, "Invalid request body type"
        body_bytes = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        if len(body_bytes) > self.max_body_bytes:
            return False, "Request body exceeds replay protection limit"

        # Verify authentication before consuming the nonce. Otherwise an
        # attacker can burn a victim's nonce using a deliberately bad signature.
        if not signature:
            if self.require_signature:
                return False, "Missing signature"
        else:
            if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
                return False, "Invalid signature format"
            expected_sig = self.generate_signature(
                timestamp, nonce, body_bytes, method, path
            )
            if not hmac.compare_digest(expected_sig, signature.lower()):
                return False, "Invalid signature"

        # Consume the nonce only after all stateless checks succeed.
        try:
            nonce_is_new = self.nonce_cache.check_and_add(nonce)
        except ReplayProtectionUnavailable:
            return False, "Nonce store unavailable"
        except Exception as exc:
            logger.error(
                "Nonce cache failed; rejecting request (%s)", type(exc).__name__
            )
            return False, "Nonce store unavailable"
        if not nonce_is_new:
            logger.warning("Replay attack detected: duplicate nonce %s***", nonce[:8])
            return False, "Duplicate nonce detected (possible replay attack)"

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
