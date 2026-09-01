"""
会话记忆 - 支持 InMemory 与 Redis 两种存储，为多轮对话提供历史消息管理。
"""
import json
import hashlib
import logging
import threading
from collections import OrderedDict
from abc import ABC, abstractmethod
from typing import List
from urllib.parse import quote

from springbootai.ai.core import Message


logger = logging.getLogger("Spring.AI.Memory")


def _positive_limit(value: int, name: str, *, maximum: int = 100_000) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if not 1 <= parsed <= maximum:
        raise ValueError(f"{name} must be in [1, {maximum}]")
    return parsed


def _key_part(value: str, *, max_length: int = 256) -> str:
    """Encode untrusted IDs into bounded, delimiter-safe storage key parts."""
    raw = str(value)
    if len(raw) > max_length:
        raw = f"sha256-{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    return quote(raw, safe="-_.~")


class ChatMemory(ABC):
    """会话记忆抽象"""

    @abstractmethod
    def add(self, conversation_id: str, message: Message, *,
            namespace: str = "") -> None:
        """追加一条消息到会话"""

    @abstractmethod
    def get(self, conversation_id: str,
            last_n: int = 20, *, namespace: str = "") -> List[Message]:
        """获取会话历史（最近 last_n 条）"""

    @abstractmethod
    def clear(self, conversation_id: str, *, namespace: str = "") -> None:
        """清空指定会话"""


class InMemoryChatMemory(ChatMemory):
    """内存会话记忆 - 开发/测试用"""

    def __init__(self, max_messages: int = 20,
                 max_conversations: int = 10_000):
        self._store: OrderedDict[tuple[str, str], list[Message]] = OrderedDict()
        self._max = _positive_limit(max_messages, "max_messages")
        self._max_conversations = _positive_limit(
            max_conversations, "max_conversations")
        self._lock = threading.RLock()

    @staticmethod
    def _key(conversation_id: str, namespace: str = "") -> tuple[str, str]:
        return (_key_part(namespace or "global"), _key_part(conversation_id))

    def add(self, conversation_id: str, message: Message, *,
            namespace: str = "") -> None:
        key = self._key(conversation_id, namespace)
        with self._lock:
            if key not in self._store:
                while len(self._store) >= self._max_conversations:
                    self._store.popitem(last=False)
            bucket = self._store.setdefault(key, [])
            bucket.append(message)
            # 滑动窗口：保留最近 max_messages 条
            if len(bucket) > self._max:
                self._store[key] = bucket[-self._max:]
            self._store.move_to_end(key)

    def get(self, conversation_id: str,
            last_n: int = 20, *, namespace: str = "") -> List[Message]:
        last_n = _positive_limit(last_n, "last_n")
        with self._lock:
            key = self._key(conversation_id, namespace)
            bucket = self._store.get(key, [])
            if key in self._store:
                self._store.move_to_end(key)
            return list(bucket[-last_n:])

    def clear(self, conversation_id: str, *, namespace: str = "") -> None:
        with self._lock:
            self._store.pop(self._key(conversation_id, namespace), None)


class RedisChatMemory(ChatMemory):
    """Redis 会话记忆 - 生产用，复用 SpringBootAI RedisClient。

    安全设计：
    - 记忆键以 ``namespace`` 分隔，防止不同用户/租户串读历史对话。
    - ``namespace`` 默认从 ``request.context['user_id']`` 与 ``tenant_id``
      派生，业务方应在 Advisor 层注入已验证的身份信息。
    - 生产环境 ``conversation_id`` 不应使用 "default"（已在 Advisor 层降级）。
    """

    KEY_PREFIX = "springpy:ai:memory:"

    def __init__(self, redis_client=None, max_messages: int = 20,
                 ttl: int = 86400, namespace: str = ""):
        self._client = redis_client
        self._max = _positive_limit(max_messages, "max_messages")
        self._ttl = _positive_limit(ttl, "ttl", maximum=365 * 24 * 3600)
        self._namespace = namespace

    def _key(self, conversation_id: str, namespace: str = "") -> str:
        ns = _key_part(namespace or self._namespace or "global")
        return f"{self.KEY_PREFIX}{ns}:{_key_part(conversation_id)}"

    def add(self, conversation_id: str, message: Message, *,
            namespace: str = "") -> None:
        if self._client is None:
            return
        key = self._key(conversation_id, namespace)
        record_data = message.to_dict()
        if message.metadata:
            record_data["metadata"] = message.metadata
        record = json.dumps(record_data, ensure_ascii=False)
        raw = (self._client.get_client()
               if hasattr(self._client, "get_client") else self._client)
        if raw is not None and hasattr(raw, "pipeline"):
            try:
                pipeline = raw.pipeline(transaction=True)
                pipeline.rpush(key, record)
                pipeline.ltrim(key, -self._max, -1)
                pipeline.expire(key, self._ttl)
                pipeline.execute()
                return
            except Exception as exc:
                logger.warning(
                    "Redis chat memory atomic write failed error_type=%s",
                    type(exc).__name__,
                )
                raise RuntimeError("Redis chat memory write failed") from exc

        pushed = self._client.list_push(key, record)
        if not pushed:
            logger.warning("Redis chat memory write failed")
            raise RuntimeError("Redis chat memory write failed")
        # 维护窗口与 TTL
        total = self._client.list_length(key) or 0
        if total > self._max:
            self._client.list_remove_range(
                key, 0, total - self._max - 1
            )
        # 给真正的 list 键刷新 TTL（之前只给 :ttl 标记键设过期，list 键会无限增长）
        # 注意：不能用 set_value（会覆盖 list 键），改用原生 client.expire
        if not self._refresh_expire(key):
            raise RuntimeError("Redis chat memory TTL refresh failed")

    def _refresh_expire(self, key: str) -> bool:
        """刷新 list 键的 TTL（框架封装无 expire 接口，降级原生 client）"""
        try:
            raw = (self._client.get_client()
                   if hasattr(self._client, "get_client") else None)
            if raw is not None and hasattr(raw, "expire"):
                return raw.expire(key, self._ttl) is not False
        except Exception as exc:
            logger.warning(
                "Redis chat memory TTL refresh failed error_type=%s",
                type(exc).__name__,
            )
            return False
        return False

    def get(self, conversation_id: str,
            last_n: int = 20, *, namespace: str = "") -> List[Message]:
        last_n = _positive_limit(last_n, "last_n")
        if self._client is None:
            return []
        records = self._client.list_range(
            self._key(conversation_id, namespace), -last_n, -1)
        messages: List[Message] = []
        for rec in records or []:
            try:
                d = json.loads(rec) if isinstance(rec, str) else rec
                messages.append(Message(
                    content=d.get("content", ""),
                    type=d.get("role", "user"),
                    name=d.get("name"),
                    metadata=(d.get("metadata", {})
                              if isinstance(d.get("metadata", {}), dict)
                              else {}),
                ))
            except (json.JSONDecodeError, TypeError):
                continue
        return messages

    def clear(self, conversation_id: str, *, namespace: str = "") -> None:
        if self._client is None:
            return
        self._client.delete_key(self._key(conversation_id, namespace))
