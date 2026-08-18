"""
会话记忆 - 支持 InMemory 与 Redis 两种存储，为多轮对话提供历史消息管理。
"""
import json
from abc import ABC, abstractmethod
from typing import List

from springbootai.ai.core import Message


class ChatMemory(ABC):
    """会话记忆抽象"""

    @abstractmethod
    def add(self, conversation_id: str, message: Message) -> None:
        """追加一条消息到会话"""

    @abstractmethod
    def get(self, conversation_id: str,
            last_n: int = 20) -> List[Message]:
        """获取会话历史（最近 last_n 条）"""

    @abstractmethod
    def clear(self, conversation_id: str) -> None:
        """清空指定会话"""


class InMemoryChatMemory(ChatMemory):
    """内存会话记忆 - 开发/测试用"""

    def __init__(self, max_messages: int = 20):
        self._store: dict = {}
        self._max = max_messages

    def add(self, conversation_id: str, message: Message) -> None:
        bucket = self._store.setdefault(conversation_id, [])
        bucket.append(message)
        # 滑动窗口：保留最近 max_messages 条
        if len(bucket) > self._max:
            self._store[conversation_id] = bucket[-self._max:]

    def get(self, conversation_id: str,
            last_n: int = 20) -> List[Message]:
        bucket = self._store.get(conversation_id, [])
        return list(bucket[-last_n:])

    def clear(self, conversation_id: str) -> None:
        self._store.pop(conversation_id, None)


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
        self._max = max_messages
        self._ttl = ttl
        self._namespace = namespace

    def _key(self, conversation_id: str) -> str:
        ns = self._namespace or "global"
        return f"{self.KEY_PREFIX}{ns}:{conversation_id}"

    def add(self, conversation_id: str, message: Message) -> None:
        if self._client is None:
            return
        record = json.dumps(message.to_dict(), ensure_ascii=False)
        self._client.list_push(self._key(conversation_id), record)
        # 维护窗口与 TTL
        key = self._key(conversation_id)
        total = self._client.list_length(key) or 0
        if total > self._max:
            self._client.list_remove_range(
                key, 0, total - self._max - 1
            )
        # 给真正的 list 键刷新 TTL（之前只给 :ttl 标记键设过期，list 键会无限增长）
        # 注意：不能用 set_value（会覆盖 list 键），改用原生 client.expire
        self._refresh_expire(key)

    def _refresh_expire(self, key: str) -> None:
        """刷新 list 键的 TTL（框架封装无 expire 接口，降级原生 client）"""
        try:
            raw = (self._client.get_client()
                   if hasattr(self._client, "get_client") else None)
            if raw is not None and hasattr(raw, "expire"):
                raw.expire(key, self._ttl)
        except Exception:
            pass

    def get(self, conversation_id: str,
            last_n: int = 20) -> List[Message]:
        if self._client is None:
            return []
        records = self._client.list_range(self._key(conversation_id), -last_n, -1)
        messages: List[Message] = []
        for rec in records or []:
            try:
                d = json.loads(rec) if isinstance(rec, str) else rec
                messages.append(Message(content=d.get("content", ""),
                                        type=d.get("role", "user")))
            except (json.JSONDecodeError, TypeError):
                continue
        return messages

    def clear(self, conversation_id: str) -> None:
        if self._client is None:
            return
        self._client.delete_key(self._key(conversation_id))
