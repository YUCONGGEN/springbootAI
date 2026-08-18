"""WebSocket Handler 接口与 ``@ServerEndpoint`` 类级注解（对齐 Spring
``WebSocketHandler`` + JSR-356 ``@ServerEndpoint``）。

两种使用范式：

1. **接口风格**（对齐 Spring ``WebSocketHandler``）::

       class EchoHandler(WebSocketHandler):
           async def after_connection_established(self, session):
               await session.send_text("welcome")
           async def handle_message(self, session, message):
               await session.send_text("echo: " + message)

   或更便捷的 ``TextWebSocketHandler`` / ``BinaryWebSocketHandler``。

2. **JSR-356 注解风格**（``@ServerEndpoint``）::

       @ServerEndpoint("/ws/echo")
       class EchoEndpoint:
           async def on_open(self, session): ...
           async def on_message(self, session, message): ...
           async def on_close(self, session, reason): ...
           async def on_error(self, session, error): ...

``@ServerEndpoint`` 只注册元数据（路径 + 生命周期方法名），实际方法包装由
``AnnotatedEndpointHandler`` 完成（适配到 ``WebSocketHandler`` 接口）。
``discover_server_endpoints`` 扫描模块/类列表，返回 ``{path: endpoint_cls}`` 字典，
供 ``WebSocketRouter`` 挂载路由。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Type

from springbootai.annotations.core import SpringAnnotation

from .exceptions import WebSocketHandlerException
from .session import WebSocketSession

logger = logging.getLogger("Spring.WebSocket.Handler")


# ==================== WebSocketHandler 接口 ====================

class WebSocketHandler:
    """WebSocket 处理器接口（对齐 Spring ``WebSocketHandler``）。

    子类覆盖以下方法：
    - ``after_connection_established(session)``：连接建立后调用。
    - ``handle_text_message(session, message)``：处理文本消息（默认调用 ``handle_message``）。
    - ``handle_binary_message(session, data)``：处理二进制消息（默认调用 ``handle_message``）。
    - ``handle_message(session, message)``：通用消息处理（默认 no-op）。
    - ``handle_transport_error(session, exception)``：传输错误。
    - ``after_connection_closed(session, reason)``：连接关闭后调用。
    - ``supports_partial_messages()``：是否支持分片消息，默认 False。
    """

    async def after_connection_established(self, session: WebSocketSession) -> None:
        """连接建立后调用（默认 no-op）。"""
        pass

    async def handle_text_message(self, session: WebSocketSession, message: str) -> None:
        await self.handle_message(session, message)

    async def handle_binary_message(self, session: WebSocketSession, data: bytes) -> None:
        await self.handle_message(session, data)

    async def handle_message(self, session: WebSocketSession, message: Any) -> None:
        """通用消息处理（默认 no-op，子类覆盖）。"""
        pass

    async def handle_transport_error(self, session: WebSocketSession, exception: Exception) -> None:
        logger.warning("WebSocket transport error on session %s: %s", session.id, exception)

    async def after_connection_closed(self, session: WebSocketSession, reason: str) -> None:
        """连接关闭后调用（默认 no-op）。"""
        pass

    def supports_partial_messages(self) -> bool:
        return False


class TextWebSocketHandler(WebSocketHandler):
    """文本消息便捷基类（对齐 Spring ``TextWebSocketHandler``）。

    子类只需覆盖 ``handle_text_message`` 即可处理文本消息。
    二进制消息默认拒绝（抛 ``WebSocketHandlerException``）。
    """

    async def handle_binary_message(self, session: WebSocketSession, data: bytes) -> None:
        raise WebSocketHandlerException(
            f"{type(self).__name__} 不支持二进制消息（覆盖 handle_binary_message 以启用）"
        )


class BinaryWebSocketHandler(WebSocketHandler):
    """二进制消息便捷基类（对齐 Spring ``BinaryWebSocketHandler``）。

    子类只需覆盖 ``handle_binary_message`` 即可处理二进制消息。
    文本消息默认拒绝。
    """

    async def handle_text_message(self, session: WebSocketSession, message: str) -> None:
        raise WebSocketHandlerException(
            f"{type(self).__name__} 不支持文本消息（覆盖 handle_text_message 以启用）"
        )


# ==================== @ServerEndpoint 注解 ====================

class ServerEndpoint(SpringAnnotation):
    """``@ServerEndpoint("/ws/echo")`` 类级注解（JSR-356 风格）。

    标注的类作为 WebSocket 端点，可定义以下生命周期方法（均为 ``async``）：
    - ``on_open(session)``：连接建立后调用。
    - ``on_message(session, message)``：收到消息时调用（文本/二进制备用同名方法）。
    - ``on_close(session, reason)``：连接关闭后调用。
    - ``on_error(session, error)``：异常时调用。

    用法::

        @ServerEndpoint("/ws/echo")
        class EchoEndpoint:
            async def on_open(self, session):
                await session.send_text("welcome")
            async def on_message(self, session, message):
                await session.send_text("echo: " + message)
    """

    _annotation_type = "server_endpoint"

    def __init__(self, value: str = "", subprotocols: Optional[List[str]] = None):
        super().__init__(value=value, subprotocols=subprotocols or [])


# ==================== AnnotatedEndpointHandler ====================

class AnnotatedEndpointHandler(WebSocketHandler):
    """把 ``@ServerEndpoint`` 标注的类适配到 ``WebSocketHandler`` 接口。

    Args:
        endpoint_cls: ``@ServerEndpoint`` 标注的类。
        instance:     可选的预构造实例（用于 IoC 注入依赖）；为 None 时用 ``endpoint_cls()``。
    """

    def __init__(self, endpoint_cls: Type, instance: Optional[Any] = None):
        self._endpoint_cls = endpoint_cls
        self._instance = instance  # 延迟构造，按需创建

    def _get_instance(self) -> Any:
        if self._instance is None:
            self._instance = self._endpoint_cls()
        return self._instance

    async def after_connection_established(self, session: WebSocketSession) -> None:
        await self._call_lifecycle("on_open", session)

    async def handle_text_message(self, session: WebSocketSession, message: str) -> None:
        await self._call_lifecycle("on_message", session, message)

    async def handle_binary_message(self, session: WebSocketSession, data: bytes) -> None:
        # 优先 on_bytes，否则复用 on_message
        instance = self._get_instance()
        on_bytes = getattr(instance, "on_bytes", None)
        if callable(on_bytes):
            await self._invoke(on_bytes, session, data)
        else:
            await self._call_lifecycle("on_message", session, data)

    async def handle_transport_error(self, session: WebSocketSession, exception: Exception) -> None:
        await self._call_lifecycle("on_error", session, exception)

    async def after_connection_closed(self, session: WebSocketSession, reason: str) -> None:
        await self._call_lifecycle("on_close", session, reason)

    async def _call_lifecycle(self, method_name: str, *args) -> None:
        instance = self._get_instance()
        method = getattr(instance, method_name, None)
        if not callable(method):
            return  # 钩子未定义，跳过
        await self._invoke(method, *args)

    async def _invoke(self, method: Callable, *args) -> None:
        try:
            result = method(*args)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "ServerEndpoint %s.%s 抛异常: %s",
                self._endpoint_cls.__name__, method.__name__, exc
            )
            raise WebSocketHandlerException(str(exc)) from exc


# ==================== 端点发现 ====================

def discover_server_endpoints(
    classes: Optional[Iterable[Type]] = None,
    modules: Optional[Iterable[Any]] = None,
) -> Dict[str, Type]:
    """扫描 ``@ServerEndpoint`` 标注的类，返回 ``{path: endpoint_cls}``。

    Args:
        classes: 显式传入的类列表。
        modules: 模块对象列表，扫描其 ``__dict__`` 中的类。

    Returns:
        ``{path: endpoint_cls}``；路径冲突时后者覆盖前者（最后声明者胜出）。
    """
    result: Dict[str, Type] = {}
    candidates: List[Type] = []
    if classes:
        candidates.extend(classes)
    if modules:
        for mod in modules:
            if mod is None:
                continue
            for attr in vars(mod).values():
                if isinstance(attr, type) and getattr(attr, "__module__", "") == mod.__name__:
                    candidates.append(attr)
    seen_ids = set()
    for cls in candidates:
        if id(cls) in seen_ids:
            continue
        seen_ids.add(id(cls))
        annotations = getattr(cls, "__spring_annotations__", []) or []
        for ann in annotations:
            if isinstance(ann, ServerEndpoint) and ann.value:
                result[ann.value] = cls
                break
    return result


__all__ = [
    "WebSocketHandler",
    "TextWebSocketHandler",
    "BinaryWebSocketHandler",
    "ServerEndpoint",
    "AnnotatedEndpointHandler",
    "discover_server_endpoints",
]
