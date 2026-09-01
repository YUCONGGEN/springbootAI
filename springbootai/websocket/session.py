"""``WebSocketSession`` 会话抽象与全局注册表（对齐 Spring ``WebSocketSession`` +
``WebSocketHandlerRegistry``）。

``WebSocketSession`` 包装 Starlette ``WebSocket``，提供：
- 唯一 ``id``（uuid4）
- ``attributes`` 字典（用户态附加数据，对齐 Spring ``attributes``）
- ``send_text`` / ``send_json`` / ``send_bytes`` / ``receive_text`` / ``receive_json`` / ``close``
- ``is_open`` / ``is_closed`` 状态
- ``user`` 属性（可选，关联鉴权用户）

``WebSocketSessionRegistry`` 线程安全注册表，支持：
- ``register`` / ``unregister`` / ``get`` / ``all``
- ``send_to_user(user, message)`` 定向推送
- ``broadcast(message)`` 广播
- ``close_all(code, reason)`` 关闭所有会话（优雅退出）
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("Spring.WebSocket.Session")


class WebSocketSession:
    """WebSocket 会话抽象，包装 Starlette ``WebSocket``。

    每个会话有唯一 ``id``；``attributes`` 用于在生命周期钩子间传递用户态数据。
    """

    def __init__(self, websocket, user: Optional[str] = None,
                 send_timeout: float = 10.0):
        # 延迟导入以避免顶层依赖 FastAPI/Starlette（仅类型注解需要）
        self._ws = websocket
        self._id: str = uuid.uuid4().hex
        self._attributes: Dict[str, Any] = {}
        self._user: Optional[str] = user
        self._closed: bool = False
        self._lock = threading.Lock()
        self._send_lock = asyncio.Lock()
        self._send_timeout = max(0.001, float(send_timeout))

    # ==================== 属性 ====================

    @property
    def id(self) -> str:
        return self._id

    @property
    def attributes(self) -> Dict[str, Any]:
        return self._attributes

    @property
    def user(self) -> Optional[str]:
        return self._user

    @user.setter
    def user(self, value: Optional[str]) -> None:
        self._user = value

    @property
    def is_open(self) -> bool:
        return not self._closed and self._ws is not None

    @property
    def is_closed(self) -> bool:
        return self._closed

    # ==================== 接收 ====================

    async def receive_text(self) -> str:
        return await self._ws.receive_text()

    async def receive_bytes(self) -> bytes:
        return await self._ws.receive_bytes()

    async def receive_json(self) -> Any:
        return await self._ws.receive_json()

    # ==================== 发送 ====================

    async def send_text(self, message: str) -> None:
        await self._send(self._ws.send_text, message)

    async def send_bytes(self, data: bytes) -> None:
        await self._send(self._ws.send_bytes, data)

    async def send_json(self, data: Any) -> None:
        """发送 JSON 消息。Starlette ``send_json`` 内部用 ``json.dumps``。"""
        await self._send(self._ws.send_json, data)

    async def _send(self, callback, value: Any) -> None:
        if self._closed:
            logger.debug("send on closed session %s, ignored", self._id)
            return
        async with self._send_lock:
            if self._closed:
                return
            try:
                await asyncio.wait_for(
                    callback(value), timeout=self._send_timeout)
            except asyncio.TimeoutError:
                self.mark_closed()
                raise TimeoutError(
                    f"WebSocket send timed out for session {self._id}") from None

    # ==================== 关闭 ====================

    async def close(self, code: int = 1000, reason: str = "") -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            async with self._send_lock:
                await asyncio.wait_for(
                    self._ws.close(code=code, reason=reason),
                    timeout=self._send_timeout,
                )
        except Exception as exc:
            logger.debug(
                "close session %s failed error_type=%s",
                self._id, type(exc).__name__,
            )

    def mark_closed(self) -> None:
        """标记会话已关闭（不主动发 close 帧，用于异常分支）。"""
        with self._lock:
            self._closed = True

    def __repr__(self) -> str:
        return f"WebSocketSession(id={self._id!r}, user={self._user!r}, open={self.is_open})"


# ==================== 全局会话注册表 ====================

class WebSocketSessionRegistry:
    """线程安全的 WebSocket 会话注册表。

    - ``register(session)``     注册会话
    - ``unregister(session_id)`` 注销会话
    - ``get(session_id)``        按 id 取会话
    - ``all()``                  返回所有会话列表（拷贝）
    - ``send_to_user(user, ...)`` 定向推送
    - ``broadcast(...)``         广播
    - ``close_all(...)``         关闭所有会话

    推送方法自动跳过已关闭的会话；推送是 ``async`` 的，需要事件循环驱动。
    """

    def __init__(self, send_timeout: float = 10.0,
                 broadcast_concurrency: int = 100):
        self._sessions: Dict[str, WebSocketSession] = {}
        self._lock = threading.RLock()
        self.send_timeout = max(0.001, float(send_timeout))
        self.broadcast_concurrency = max(1, int(broadcast_concurrency))

    def register(self, session: WebSocketSession) -> None:
        with self._lock:
            self._sessions[session.id] = session

    def unregister(self, session_id: str) -> Optional[WebSocketSession]:
        with self._lock:
            return self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Optional[WebSocketSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def all(self) -> List[WebSocketSession]:
        with self._lock:
            return list(self._sessions.values())

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    async def send_to_user(self, user: str, message: Any, as_json: bool = True) -> int:
        """向指定用户的所有会话推送消息；返回成功推送的会话数。"""
        targets = [
            session for session in self.all()
            if session.user == user and session.is_open
        ]
        return await self._dispatch(targets, message, as_json, "send_to_user")

    async def broadcast(self, message: Any, as_json: bool = True,
                        exclude: Optional[Iterable[str]] = None) -> int:
        """向所有会话广播；``exclude`` 是要排除的 session_id 列表。返回推送数。"""
        excluded = set(exclude or [])
        targets = [
            session for session in self.all()
            if session.id not in excluded and session.is_open
        ]
        return await self._dispatch(targets, message, as_json, "broadcast")

    async def _dispatch(self, targets: List[WebSocketSession], message: Any,
                        as_json: bool, operation: str) -> int:
        queue: asyncio.Queue = asyncio.Queue()
        for session in targets:
            queue.put_nowait(session)
        sent = 0
        stale: List[str] = []

        async def worker() -> None:
            nonlocal sent
            while True:
                try:
                    session = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    callback = session.send_json if as_json else session.send_text
                    payload = (message if as_json or isinstance(message, str)
                               else str(message))
                    await asyncio.wait_for(
                        callback(payload), timeout=self.send_timeout)
                    if session.is_open:
                        sent += 1
                except Exception as exc:
                    session.mark_closed()
                    stale.append(session.id)
                    logger.warning(
                        "%s failed for session %s error_type=%s",
                        operation, session.id, type(exc).__name__)

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(len(targets), self.broadcast_concurrency))
        ]
        if workers:
            await asyncio.gather(*workers)
        for session_id in stale:
            self.unregister(session_id)
        return sent

    async def close_all(self, code: int = 1001, reason: str = "server shutdown") -> None:
        """关闭所有会话（优雅退出）。"""
        async def close_one(session: WebSocketSession) -> None:
            try:
                await asyncio.wait_for(
                    session.close(code=code, reason=reason),
                    timeout=self.send_timeout,
                )
            except Exception as exc:
                logger.debug(
                    "close_all session %s failed error_type=%s",
                    session.id, type(exc).__name__)

        await asyncio.gather(*(close_one(session) for session in self.all()))
        self.clear()


# 全局单例（对齐 Spring ``WebSocketHandlerRegistry`` 默认实现）
global_session_registry = WebSocketSessionRegistry()


__all__ = [
    "WebSocketSession",
    "WebSocketSessionRegistry",
    "global_session_registry",
]
