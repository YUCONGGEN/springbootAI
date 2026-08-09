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

    def __init__(self, websocket, user: Optional[str] = None):
        # 延迟导入以避免顶层依赖 FastAPI/Starlette（仅类型注解需要）
        self._ws = websocket
        self._id: str = uuid.uuid4().hex
        self._attributes: Dict[str, Any] = {}
        self._user: Optional[str] = user
        self._closed: bool = False
        self._lock = threading.Lock()

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
        if self._closed:
            logger.debug("send_text on closed session %s, ignored", self._id)
            return
        await self._ws.send_text(message)

    async def send_bytes(self, data: bytes) -> None:
        if self._closed:
            return
        await self._ws.send_bytes(data)

    async def send_json(self, data: Any) -> None:
        """发送 JSON 消息。Starlette ``send_json`` 内部用 ``json.dumps``。"""
        if self._closed:
            return
        await self._ws.send_json(data)

    # ==================== 关闭 ====================

    async def close(self, code: int = 1000, reason: str = "") -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            await self._ws.close(code=code, reason=reason)
        except Exception as exc:
            logger.debug("close session %s failed: %s", self._id, exc)

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

    def __init__(self):
        self._sessions: Dict[str, WebSocketSession] = {}
        self._lock = threading.RLock()

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
        sent = 0
        for session in self.all():
            if session.user != user or not session.is_open:
                continue
            try:
                if as_json:
                    await session.send_json(message)
                else:
                    await session.send_text(message if isinstance(message, str) else str(message))
                sent += 1
            except Exception as exc:
                logger.warning("send_to_user failed for session %s: %s", session.id, exc)
        return sent

    async def broadcast(self, message: Any, as_json: bool = True,
                        exclude: Optional[Iterable[str]] = None) -> int:
        """向所有会话广播；``exclude`` 是要排除的 session_id 列表。返回推送数。"""
        excluded = set(exclude or [])
        sent = 0
        for session in self.all():
            if session.id in excluded or not session.is_open:
                continue
            try:
                if as_json:
                    await session.send_json(message)
                else:
                    await session.send_text(message if isinstance(message, str) else str(message))
                sent += 1
            except Exception as exc:
                logger.warning("broadcast failed for session %s: %s", session.id, exc)
        return sent

    async def close_all(self, code: int = 1001, reason: str = "server shutdown") -> None:
        """关闭所有会话（优雅退出）。"""
        for session in self.all():
            try:
                await session.close(code=code, reason=reason)
            except Exception as exc:
                logger.debug("close_all session %s failed: %s", session.id, exc)
        self.clear()


# 全局单例（对齐 Spring ``WebSocketHandlerRegistry`` 默认实现）
global_session_registry = WebSocketSessionRegistry()


__all__ = [
    "WebSocketSession",
    "WebSocketSessionRegistry",
    "global_session_registry",
]
