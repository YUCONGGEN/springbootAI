"""内存消息代理 + 发送操作 API（对齐 Spring ``SimpleBrokerMessageHandler`` +
``SimpMessageSendingOperations``）。

``InMemoryBroker`` 主题式发布订阅代理：
- ``subscribe(destination, session)``        会话订阅 destination
- ``unsubscribe(destination, session_id)``   会话取消订阅（按 session_id）
- ``unsubscribe_all(session_id)``            会话退出时取消其所有订阅
- ``publish(destination, message, exclude)`` 向 destination 的所有订阅者推送 JSON 消息
- ``subscribers(destination)``               返回 destination 的订阅会话列表

destination 命名约定（对齐 Spring STOMP）：
- ``/topic/*``   主题广播（多客户端可订阅）
- ``/queue/*``   队列（点对点，通常与 ``@SendToUser`` 配合）
- ``/app/*``     应用消息（``@MessageMapping`` 入口，前缀由 ``MessageBrokerConfigurer`` 剥离）

``SimpMessageSendingOperations`` 提供高阶 API：
- ``convert_and_send(destination, payload)``  转换 payload 为 JSON 并发布到 destination
- ``convert_and_send_to_user(user, payload)`` 定向推送给用户

``MessageBrokerConfigurer`` 配置入口：
- ``application_destination_prefixes``：``@MessageMapping`` 入口前缀（默认 ``["/app"]``）
- ``broker_prefixes``：broker 处理的前缀（默认 ``["/topic", "/queue"]``）
- ``user_destination_prefix``：用户私有目的地前缀（默认 ``/user``）

``broker_registry`` 全局单例（``InMemoryBroker`` + ``SimpMessageSendingOperations``）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Dict, Iterable, List, Optional, Set

from .exceptions import MessageBrokerException
from .session import (
    WebSocketSession, WebSocketSessionRegistry, global_session_registry,
)

logger = logging.getLogger("Spring.WebSocket.Broker")


class InMemoryBroker:
    """内存主题式消息代理（对齐 Spring ``SimpleBrokerMessageHandler``）。

    线程安全：所有订阅/发布操作加锁；推送是 ``async``，需事件循环驱动。
    """

    def __init__(self, send_timeout: float = 10.0,
                 publish_concurrency: int = 100,
                 max_destinations: int = 10000,
                 max_subscriptions_per_session: int = 100,
                 max_destination_length: int = 512,
                 max_message_size: int = 1024 * 1024):
        # destination -> {session_id: WebSocketSession}
        self._subscriptions: Dict[str, Dict[str, WebSocketSession]] = {}
        self._session_destinations: Dict[str, Set[str]] = {}
        self._lock = threading.RLock()
        self.send_timeout = max(0.001, float(send_timeout))
        self.publish_concurrency = max(1, int(publish_concurrency))
        self.max_destinations = max(1, int(max_destinations))
        self.max_subscriptions_per_session = max(
            1, int(max_subscriptions_per_session))
        self.max_destination_length = max(1, int(max_destination_length))
        self.max_message_size = max(1, int(max_message_size))

    def _validate_destination(self, destination: str) -> str:
        if not isinstance(destination, str) or not destination:
            raise MessageBrokerException("destination 不能为空")
        if len(destination.encode("utf-8")) > self.max_destination_length:
            raise MessageBrokerException("destination 超过长度限制")
        if any(char in destination for char in "\r\n\x00"):
            raise MessageBrokerException("destination 包含非法字符")
        return destination

    def subscribe(self, destination: str, session: WebSocketSession) -> int:
        """会话订阅 destination；返回该 destination 当前订阅数。"""
        destination = self._validate_destination(destination)
        with self._lock:
            destinations = self._session_destinations.setdefault(
                session.id, set())
            if destination not in destinations:
                if len(destinations) >= self.max_subscriptions_per_session:
                    raise MessageBrokerException("会话订阅数超过限制")
                if (destination not in self._subscriptions
                        and len(self._subscriptions) >= self.max_destinations):
                    raise MessageBrokerException("broker destination 数超过限制")
            bucket = self._subscriptions.setdefault(destination, {})
            bucket[session.id] = session
            destinations.add(destination)
            return len(bucket)

    def unsubscribe(self, destination: str, session_id: str) -> bool:
        """会话取消订阅指定 destination；返回是否成功取消。"""
        with self._lock:
            bucket = self._subscriptions.get(destination)
            if bucket is None:
                return False
            removed = bucket.pop(session_id, None) is not None
            if removed:
                destinations = self._session_destinations.get(session_id)
                if destinations is not None:
                    destinations.discard(destination)
                    if not destinations:
                        self._session_destinations.pop(session_id, None)
            if not bucket:
                self._subscriptions.pop(destination, None)
            return removed

    def unsubscribe_all(self, session_id: str) -> int:
        """会话退出时取消其所有订阅；返回取消的订阅数。"""
        n = 0
        with self._lock:
            destinations = self._session_destinations.pop(session_id, set())
            for destination in destinations:
                bucket = self._subscriptions.get(destination)
                if bucket is None:
                    continue
                if bucket.pop(session_id, None) is not None:
                    n += 1
                if not bucket:
                    self._subscriptions.pop(destination, None)
        return n

    def subscribers(self, destination: str) -> List[WebSocketSession]:
        """返回 destination 的订阅会话列表（拷贝）。"""
        with self._lock:
            bucket = self._subscriptions.get(destination, {})
            return list(bucket.values())

    def subscriber_count(self, destination: str) -> int:
        with self._lock:
            return len(self._subscriptions.get(destination, {}))

    def destinations(self) -> List[str]:
        with self._lock:
            return list(self._subscriptions.keys())

    def clear(self) -> None:
        with self._lock:
            self._subscriptions.clear()
            self._session_destinations.clear()

    async def publish(self, destination: str, message: Any,
                      exclude: Optional[Iterable[str]] = None) -> int:
        """向 destination 的所有订阅者推送 JSON 消息；返回成功推送数。

        - ``exclude``：要排除的 session_id 列表。
        - 已关闭的会话自动跳过，并在推送后清理其订阅。
        """
        destination = self._validate_destination(destination)
        frame = _wrap_message(destination, message)
        try:
            encoded_size = len(json.dumps(
                frame, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise MessageBrokerException(
                "WebSocket message is not JSON serializable") from exc
        if encoded_size > self.max_message_size:
            raise MessageBrokerException("WebSocket message exceeds size limit")
        excluded: Set[str] = set(exclude or [])
        stale: List[str] = []
        with self._lock:
            bucket = self._subscriptions.get(destination, {})
            targets = [s for sid, s in bucket.items() if sid not in excluded]
        async def send_one(session: WebSocketSession) -> bool:
            if not session.is_open:
                stale.append(session.id)
                return False
            try:
                await asyncio.wait_for(
                    session.send_json(frame), timeout=self.send_timeout)
                return session.is_open
            except Exception as exc:
                session.mark_closed()
                logger.warning(
                    "publish to session %s failed error_type=%s",
                    session.id, type(exc).__name__)
                stale.append(session.id)
                return False

        sent = 0
        if targets:
            iterator = iter(targets)

            async def worker() -> int:
                count = 0
                while True:
                    try:
                        target = next(iterator)
                    except StopIteration:
                        return count
                    count += int(await send_one(target))

            worker_count = min(self.publish_concurrency, len(targets))
            sent = sum(await asyncio.gather(*(
                worker() for _ in range(worker_count))))
        # 清理失效会话的订阅
        if stale:
            with self._lock:
                bucket = self._subscriptions.get(destination)
                if bucket is not None:
                    for sid in stale:
                        bucket.pop(sid, None)
                        destinations = self._session_destinations.get(sid)
                        if destinations is not None:
                            destinations.discard(destination)
                            if not destinations:
                                self._session_destinations.pop(sid, None)
                    if not bucket:
                        self._subscriptions.pop(destination, None)
        return sent


def _wrap_message(destination: str, payload: Any) -> Dict[str, Any]:
    """构造标准消息帧：``{"destination": ..., "payload": ...}``。"""
    return {"destination": destination, "payload": payload}


# ==================== SimpMessageSendingOperations ====================

class SimpMessageSendingOperations:
    """高阶消息发送 API（对齐 Spring ``SimpMessageSendingOperations``）。"""

    def __init__(self, broker: InMemoryBroker,
                 session_registry=global_session_registry):
        self._broker = broker
        self._session_registry = session_registry

    @property
    def broker(self) -> InMemoryBroker:
        return self._broker

    async def convert_and_send(self, destination: str, payload: Any,
                               exclude: Optional[Iterable[str]] = None) -> int:
        """转换 payload 为 JSON 并发布到 destination。"""
        return await self._broker.publish(destination, payload, exclude=exclude)

    async def convert_and_send_to_user(self, user: str, destination: str, payload: Any) -> int:
        """定向推送给用户：消息发到该用户的所有会话，destination 作为元数据。

        实现：直接通过 ``session_registry.send_to_user`` 推送，不走 broker 订阅。
        """
        message = _wrap_message(destination, payload)
        return await self._session_registry.send_to_user(user, message, as_json=True)


# ==================== MessageBrokerConfigurer ====================

class MessageBrokerConfigurer:
    """消息代理配置器（对齐 Spring ``@EnableWebSocketMessageBroker`` +
    ``WebSocketMessageBrokerConfigurer``）。

    配置项：
    - ``application_destination_prefixes``：``@MessageMapping`` 入口前缀（默认 ``["/app"]``）。
      客户端发往 ``/app/greet`` 的消息被路由到 ``@MessageMapping("/greet")``。
    - ``broker_prefixes``：broker 处理的前缀（默认 ``["/topic", "/queue"]``）。
      ``@SendTo("/topic/x")`` 的消息直接由 broker 广播。
    - ``user_destination_prefix``：用户私有目的地前缀（默认 ``/user``）。
    """

    def __init__(
        self,
        application_destination_prefixes: Optional[List[str]] = None,
        broker_prefixes: Optional[List[str]] = None,
        user_destination_prefix: str = "/user",
        session_registry=None,
    ):
        self._app_prefixes: List[str] = list(application_destination_prefixes or ["/app"])
        self._broker_prefixes: List[str] = list(broker_prefixes or ["/topic", "/queue"])
        self._user_prefix: str = user_destination_prefix
        self._session_registry = (
            session_registry or WebSocketSessionRegistry())
        self._broker = InMemoryBroker()
        self._sending_ops = SimpMessageSendingOperations(
            self._broker, self._session_registry)

    @property
    def broker(self) -> InMemoryBroker:
        return self._broker

    @property
    def sending_operations(self) -> SimpMessageSendingOperations:
        return self._sending_ops

    @property
    def session_registry(self):
        return self._session_registry

    @property
    def application_destination_prefixes(self) -> List[str]:
        return list(self._app_prefixes)

    @property
    def broker_prefixes(self) -> List[str]:
        return list(self._broker_prefixes)

    @property
    def user_destination_prefix(self) -> str:
        return self._user_prefix

    def strip_app_prefix(self, destination: str) -> Optional[str]:
        """剥离 ``/app`` 前缀，返回 ``@MessageMapping`` 匹配路径；非入口返回 None。"""
        for prefix in self._app_prefixes:
            if destination == prefix:
                return ""
            if destination.startswith(prefix + "/"):
                return destination[len(prefix):]
        return None

    def is_broker_destination(self, destination: str) -> bool:
        """destination 是否由 broker 直接处理（``/topic`` / ``/queue`` 等）。"""
        for prefix in self._broker_prefixes:
            if destination == prefix or destination.startswith(prefix + "/"):
                return True
        return False


# 全局单例（默认配置）
broker_registry = MessageBrokerConfigurer(
    session_registry=global_session_registry)


__all__ = [
    "InMemoryBroker",
    "SimpMessageSendingOperations",
    "MessageBrokerConfigurer",
    "broker_registry",
]
