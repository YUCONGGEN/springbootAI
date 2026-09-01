"""``WebSocketRouter`` 把注解端点转换为 Starlette/FastAPI WebSocket 路由。

支持的端点类型：
1. ``@ServerEndpoint("/ws/path")`` 标注的类 → ``AnnotatedEndpointHandler`` → WS 路由
2. ``WebSocketHandler`` 子类实例 → 直接 WS 路由
3. ``@MessageEndpoint`` + ``@MessageMapping`` 类 → ``MessageEndpointDispatcher`` → WS 路由

``WebSocketRouter`` 维护 ``{path: (handler, options)}``；``install(app)`` 把所有路由
注册到 Starlette/FastAPI 应用。

消息帧格式（简化 STOMP，JSON）::

    客户端 → 服务端：
        {"action": "subscribe",   "destination": "/topic/greetings"}
        {"action": "unsubscribe", "destination": "/topic/greetings"}
        {"action": "message",     "destination": "/app/greet", "payload": {"name": "Tom"}}

    服务端 → 客户端（broker 广播）：
        {"destination": "/topic/greetings", "payload": {"content": "Hello, Tom!"}}
"""
from __future__ import annotations

import inspect
import asyncio
import json
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Type
from urllib.parse import urlsplit

from .annotations import (
    MessageEndpoint,
    MessageMappingModel,
    collect_message_mappings,
)
from .broker import MessageBrokerConfigurer, broker_registry
from .exceptions import (
    WebSocketConnectionException,
    WebSocketHandlerException,
    MessageBrokerException,
)
from .handler import (
    AnnotatedEndpointHandler,
    WebSocketHandler,
    discover_server_endpoints,
)
from .session import (
    WebSocketSession,
    WebSocketSessionRegistry,
    global_session_registry,
)

logger = logging.getLogger("Spring.WebSocket.Router")


# ==================== MessageEndpointDispatcher ====================

class MessageEndpointDispatcher(WebSocketHandler):
    """``@MessageEndpoint`` 类的消息分发处理器。

    - 维护 ``{destination: MessageMappingModel}`` 路由表
    - 收到消息帧 ``{"destination": "/app/x", "payload": ...}`` 时：
      1. 用 ``MessageBrokerConfigurer.strip_app_prefix`` 剥离 ``/app`` 前缀
      2. 查找 ``@MessageMapping`` 方法并调用
      3. 按方法上的 ``@SendTo`` / ``@SendToUser`` 决定返回值去向
    - 收到 ``subscribe`` 帧时：调用 broker 订阅 + 触发 ``@SubscribeMapping``
    """

    def __init__(
        self,
        endpoint_cls: Type,
        instance: Optional[Any] = None,
        configurer: Optional[MessageBrokerConfigurer] = None,
        session_registry: Optional[WebSocketSessionRegistry] = None,
        destination_authorizer: Optional[Callable] = None,
    ):
        self._endpoint_cls = endpoint_cls
        self._instance = instance
        self._configurer = configurer or broker_registry
        self._session_registry = session_registry or global_session_registry
        self._destination_authorizer = destination_authorizer
        self._models: List[MessageMappingModel] = collect_message_mappings(endpoint_cls)
        # @MessageMapping 路由表（destination -> model）
        self._message_routes: Dict[str, MessageMappingModel] = {
            m.destination: m for m in self._models if not m.is_subscribe and m.destination
        }
        # @SubscribeMapping 路由表
        self._subscribe_routes: Dict[str, MessageMappingModel] = {
            m.subscribe_destination: m for m in self._models if m.is_subscribe and m.subscribe_destination
        }

    @property
    def message_routes(self) -> Dict[str, MessageMappingModel]:
        return dict(self._message_routes)

    @property
    def subscribe_routes(self) -> Dict[str, MessageMappingModel]:
        return dict(self._subscribe_routes)

    def _get_instance(self) -> Any:
        if self._instance is None:
            self._instance = self._endpoint_cls()
        return self._instance

    async def after_connection_established(self, session: WebSocketSession) -> None:
        # 默认无 lifecycle；@MessageEndpoint 通常不需要 on_open
        pass

    async def handle_text_message(self, session: WebSocketSession, message: str) -> None:
        try:
            frame = json.loads(message)
        except json.JSONDecodeError as exc:
            raise WebSocketHandlerException(f"非法 JSON 帧: {exc}") from exc
        if not isinstance(frame, dict):
            raise WebSocketHandlerException("消息帧必须是 JSON 对象")
        action = frame.get("action", "message")
        destination = frame.get("destination", "")
        payload = frame.get("payload")

        if self._destination_authorizer is not None:
            try:
                allowed = self._destination_authorizer(
                    session, action, destination, payload)
                if inspect.isawaitable(allowed):
                    allowed = await allowed
            except Exception as exc:
                logger.warning(
                    "WebSocket destination authorization failed error_type=%s",
                    type(exc).__name__,
                )
                allowed = False
            if not allowed:
                raise MessageBrokerException("destination access denied")

        if action == "subscribe":
            await self._handle_subscribe(session, destination)
        elif action == "unsubscribe":
            await self._handle_unsubscribe(session, destination)
        elif action == "message":
            await self._handle_message(session, destination, payload)
        else:
            raise WebSocketHandlerException(f"未知 action: {action!r}")

    async def handle_binary_message(self, session: WebSocketSession, data: bytes) -> None:
        raise WebSocketHandlerException(
            "MessageEndpointDispatcher 仅支持文本（JSON）消息"
        )

    async def after_connection_closed(self, session: WebSocketSession, reason: str) -> None:
        # 会话退出时清理其所有订阅
        self._configurer.broker.unsubscribe_all(session.id)

    async def _handle_subscribe(self, session: WebSocketSession, destination: str) -> None:
        if not destination:
            raise MessageBrokerException("subscribe 帧缺少 destination")
        # 1. 如果有 @SubscribeMapping，触发并回发初始数据
        model = self._subscribe_routes.get(destination)
        if model is not None:
            await self._invoke_and_dispatch(model, session, destination, None)
            return
        # 2. 否则注册到 broker
        if self._configurer.is_broker_destination(destination):
            self._configurer.broker.subscribe(destination, session)

    async def _handle_unsubscribe(self, session: WebSocketSession, destination: str) -> None:
        if not destination:
            return
        self._configurer.broker.unsubscribe(destination, session.id)

    async def _handle_message(self, session: WebSocketSession, destination: str,
                              payload: Any) -> None:
        if not destination:
            raise MessageBrokerException("message 帧缺少 destination")
        # 1. broker destination（/topic /queue）：直接发布
        if self._configurer.is_broker_destination(destination):
            await self._configurer.broker.publish(destination, payload, exclude=[session.id])
            return
        # 2. app destination（/app）：剥离前缀，路由到 @MessageMapping
        mapping_path = self._configurer.strip_app_prefix(destination)
        if mapping_path is None:
            raise MessageBrokerException(
                f"destination {destination!r} 不在任何已配置前缀下（app/broker）"
            )
        model = self._message_routes.get(mapping_path)
        if model is None:
            raise MessageBrokerException(
                f"未找到 @MessageMapping({mapping_path!r}) 处理方法"
            )
        await self._invoke_and_dispatch(model, session, destination, payload)

    async def _invoke_and_dispatch(
        self,
        model: MessageMappingModel,
        session: WebSocketSession,
        original_destination: str,
        payload: Any,
    ) -> None:
        """调用映射方法并把返回值按 ``@SendTo`` / ``@SendToUser`` 派发。"""
        instance = self._get_instance()
        method = getattr(instance, model.method_name, None)
        if not callable(method):
            raise WebSocketHandlerException(
                f"方法 {model.method_name!r} 不存在于 {self._endpoint_cls.__name__}"
            )
        try:
            result = method(payload, session) if _accepts_session(method) else method(payload)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            logger.warning(
                "@MessageMapping %s.%s failed error_type=%s",
                self._endpoint_cls.__name__, model.method_name,
                type(exc).__name__,
            )
            raise WebSocketHandlerException(
                "message handler failed") from exc

        if result is None:
            return  # 无返回值：不发送

        # @SendTo：广播到指定 destination
        if model.send_to:
            for dest in model.send_to:
                await self._configurer.broker.publish(dest, result)
            return

        # @SendToUser / 默认：定向回发给发送者
        if model.send_to_user_broadcast and session.user:
            # 广播给该用户所有会话
            await self._session_registry.send_to_user(
                session.user, {"destination": original_destination, "payload": result}
            )
        else:
            # 仅回发当前会话
            await session.send_json({"destination": original_destination, "payload": result})


def _accepts_session(method: Callable) -> bool:
    """检测方法签名是否接受第二个 session 参数（``def handle(payload, session)``）。"""
    try:
        sig = inspect.signature(method)
        params = [p for p in sig.parameters.values()
                  if p.name != "self" and p.kind not in (
                      inspect.Parameter.VAR_POSITIONAL,
                      inspect.Parameter.VAR_KEYWORD,
                  )]
        return len(params) >= 2
    except (TypeError, ValueError):
        return False


# ==================== WebSocketRouter ====================

class _RouteEntry:
    """路由表项：``{path: (handler_factory, options)}``。"""

    __slots__ = ("path", "handler_factory", "name", "subprotocols")

    def __init__(
        self,
        path: str,
        handler_factory: Callable[[], WebSocketHandler],
        name: Optional[str] = None,
        subprotocols: Optional[List[str]] = None,
    ):
        self.path = path
        self.handler_factory = handler_factory
        self.name = name
        self.subprotocols = subprotocols


class WebSocketRouter:
    """WebSocket 路由注册表（对齐 Spring ``WebSocketHandlerRegistry``）。

    用法::

        router = WebSocketRouter()
        router.add_endpoint("/ws/echo", EchoHandler())
        router.add_endpoint("/ws/chat", ChatHandlerClass, annotated=True)
        router.add_message_endpoint("/ws/app", AppController)
        router.install(app)  # 挂载到 FastAPI/Starlette 应用
    """

    def __init__(
        self,
        session_registry: Optional[WebSocketSessionRegistry] = None,
        configurer: Optional[MessageBrokerConfigurer] = None,
        handshake_authorizer: Optional[Callable] = None,
        destination_authorizer: Optional[Callable] = None,
        allowed_origins: Optional[Iterable[str]] = None,
        allow_anonymous: bool = False,
        allow_query_token: bool = False,
        max_message_size: int = 1024 * 1024,
        send_timeout: float = 10.0,
    ):
        inherited_registry = getattr(configurer, "session_registry", None)
        self._session_registry = (
            session_registry or inherited_registry or WebSocketSessionRegistry())
        self._configurer = configurer or MessageBrokerConfigurer(
            session_registry=self._session_registry)
        self._routes: Dict[str, _RouteEntry] = {}
        self._handshake_authorizer = handshake_authorizer
        self._destination_authorizer = destination_authorizer
        self._allowed_origins = set(allowed_origins or ())
        self._allow_anonymous = bool(allow_anonymous)
        self._allow_query_token = bool(allow_query_token)
        self._max_message_size = max(1, int(max_message_size))
        self._send_timeout = max(0.001, float(send_timeout))

    @property
    def session_registry(self) -> WebSocketSessionRegistry:
        return self._session_registry

    @property
    def configurer(self) -> MessageBrokerConfigurer:
        return self._configurer

    @property
    def routes(self) -> Dict[str, _RouteEntry]:
        return dict(self._routes)

    # ==================== 注册 ====================

    def add_handler(
        self,
        path: str,
        handler: WebSocketHandler,
        name: Optional[str] = None,
    ) -> None:
        """注册一个 ``WebSocketHandler`` 实例到指定路径。"""
        if path in self._routes:
            raise WebSocketConnectionException(f"路径 {path!r} 已注册 WebSocket 端点")
        self._routes[path] = _RouteEntry(path, lambda: handler, name=name)

    def add_endpoint(
        self,
        path: str,
        endpoint_cls: Type,
        instance: Optional[Any] = None,
        name: Optional[str] = None,
    ) -> None:
        """注册一个 ``@ServerEndpoint`` 标注的类，或一个 ``WebSocketHandler`` 子类。

        - ``@ServerEndpoint`` 类：用 ``AnnotatedEndpointHandler`` 包装。
        - ``WebSocketHandler`` 子类：直接实例化。
        """
        if path in self._routes:
            raise WebSocketConnectionException(f"路径 {path!r} 已注册 WebSocket 端点")

        # @MessageEndpoint 类：用 MessageEndpointDispatcher
        if _is_message_endpoint(endpoint_cls):
            dispatcher = MessageEndpointDispatcher(
                endpoint_cls, instance=instance, configurer=self._configurer,
                session_registry=self._session_registry,
                destination_authorizer=self._destination_authorizer,
            )
            self._routes[path] = _RouteEntry(path, lambda: dispatcher, name=name)
            return

        # @ServerEndpoint 类：用 AnnotatedEndpointHandler
        if _is_server_endpoint(endpoint_cls):
            def annotated_handler_factory(
                    cls=endpoint_cls, shared=instance) -> WebSocketHandler:
                return AnnotatedEndpointHandler(cls, instance=shared)
            self._routes[path] = _RouteEntry(
                path, annotated_handler_factory, name=name,
            )
            return

        # WebSocketHandler 子类
        if isinstance(endpoint_cls, type) and issubclass(endpoint_cls, WebSocketHandler):
            handler = instance if isinstance(instance, endpoint_cls) else endpoint_cls()
            self._routes[path] = _RouteEntry(path, lambda: handler, name=name)
            return

        raise WebSocketHandlerException(
            f"不支持的端点类型: {endpoint_cls!r}（需为 @ServerEndpoint/@MessageEndpoint/"
            f"WebSocketHandler 子类）"
        )

    def add_message_endpoint(
        self,
        path: str,
        endpoint_cls: Type,
        instance: Optional[Any] = None,
        name: Optional[str] = None,
    ) -> None:
        """显式注册 ``@MessageEndpoint`` 类到指定路径。"""
        if not _is_message_endpoint(endpoint_cls):
            raise WebSocketHandlerException(
                f"{endpoint_cls!r} 未标注 @MessageEndpoint"
            )
        if path in self._routes:
            raise WebSocketConnectionException(f"路径 {path!r} 已注册 WebSocket 端点")
        dispatcher = MessageEndpointDispatcher(
            endpoint_cls, instance=instance, configurer=self._configurer,
            session_registry=self._session_registry,
            destination_authorizer=self._destination_authorizer,
        )
        self._routes[path] = _RouteEntry(path, lambda: dispatcher, name=name)

    # ==================== 挂载到 ASGI 应用 ====================

    def install(self, app: Any) -> None:
        """把所有路由挂载到 Starlette/FastAPI 应用。"""
        for entry in self._routes.values():
            self._install_route(app, entry)

    def _install_route(self, app: Any, entry: _RouteEntry) -> None:
        """挂载单个 WebSocket 路由到应用。"""
        # 延迟导入 Starlette WebSocket
        from starlette.websockets import WebSocket

        async def endpoint(websocket: WebSocket) -> None:
            auth = await self._authorize_handshake(websocket)
            if auth is None:
                try:
                    await websocket.close(code=1008, reason="policy violation")
                except Exception:
                    pass
                return

            # 握手授权通过后才接受连接。
            try:
                await websocket.accept()
            except Exception as exc:
                raise WebSocketConnectionException(
                    "WebSocket handshake failed") from exc

            session = WebSocketSession(
                websocket, user=auth.get("user"),
                send_timeout=self._send_timeout)
            session.attributes.update(auth.get("attributes", {}))
            self._session_registry.register(session)
            handler = entry.handler_factory()
            close_notified = False

            # 调用 after_connection_established
            try:
                await handler.after_connection_established(session)
            except Exception as exc:
                logger.warning(
                    "after_connection_established failed error_type=%s",
                    type(exc).__name__,
                )
                await _safe_close(session, code=1011, reason="server error")
                await _safe_call(
                    handler.after_connection_closed, session,
                    "connection establishment failed")
                self._session_registry.unregister(session.id)
                return

            # 消息循环
            try:
                while True:
                    # 检查会话状态
                    if session.is_closed:
                        break
                    # 兼容 Starlette：state 可能是 WebSocketState.CONNECTED 或 CONNECTING
                    try:
                        state = websocket.state
                    except RuntimeError:
                        state = None
                    if state is not None:
                        # Starlette 0.30+: state 在 disconnect 后为 DISCONNECTED
                        from starlette.websockets import WebSocketState as _State
                        if state == getattr(_State, "DISCONNECTED", None):
                            break

                    message = await websocket.receive()
                    msg_type = message.get("type", "")
                    if msg_type == "websocket.disconnect":
                        # 客户端断开
                        code = message.get("code", 1000)
                        session.mark_closed()
                        await _safe_call(
                            handler.after_connection_closed, session,
                            f"client closed (code={code})")
                        close_notified = True
                        break
                    text_message = message.get("text")
                    byte_message = message.get("bytes")
                    if text_message is not None:
                        if len(text_message.encode("utf-8")) > self._max_message_size:
                            await _safe_close(
                                session, code=1009, reason="message too large")
                            break
                        await handler.handle_text_message(session, text_message)
                    elif byte_message is not None:
                        if len(byte_message) > self._max_message_size:
                            await _safe_close(
                                session, code=1009, reason="message too large")
                            break
                        await handler.handle_binary_message(session, byte_message)
            except Exception as exc:
                # 区分：连接关闭 vs 处理器异常
                if _is_disconnect(exc):
                    await _safe_call(handler.after_connection_closed, session, "client disconnected")
                    close_notified = True
                else:
                    logger.warning(
                        "WebSocket message loop failed error_type=%s",
                        type(exc).__name__,
                    )
                    await _safe_call(handler.handle_transport_error, session, exc)
                    await _safe_call(
                        handler.after_connection_closed, session,
                        "message handling failed")
                    close_notified = True
                    await _safe_close(session, code=1011, reason="server error")
            finally:
                session.mark_closed()
                if not close_notified:
                    await _safe_call(
                        handler.after_connection_closed, session,
                        "server closed")
                self._session_registry.unregister(session.id)
                # 清理该会话的所有 broker 订阅
                self._configurer.broker.unsubscribe_all(session.id)

        # 注册到应用。Starlette 把 WebSocket 路由 API 挂在 ``app.router`` 上，
        # FastAPI 既暴露 ``app.websocket`` 装饰器又有 ``app.router.add_websocket_route``。
        # 此处按优先级兼容多版本。
        add_websocket_route = (
            getattr(app, "add_websocket_route", None)
            or getattr(getattr(app, "router", None), "add_websocket_route", None)
        )
        app_websocket_decorator = getattr(app, "websocket", None)

        if callable(add_websocket_route):
            # 标准注册：add_websocket_route(path, endpoint)
            add_websocket_route(entry.path, endpoint)
        elif callable(app_websocket_decorator):
            # FastAPI 风格：app.websocket(path) 是装饰器工厂
            app_websocket_decorator(entry.path)(endpoint)
        else:
            raise WebSocketConnectionException(
                f"应用 {app!r} 不支持 WebSocket 路由（无 websocket/add_websocket_route）"
            )

    async def _authorize_handshake(self, websocket) -> Optional[Dict[str, Any]]:
        origin = ""
        host = ""
        try:
            origin = websocket.headers.get("origin", "")
            host = websocket.headers.get("host", "")
        except Exception:
            pass
        if (self._allowed_origins and "*" not in self._allowed_origins
                and origin not in self._allowed_origins):
            return None
        if not self._allowed_origins and origin:
            try:
                parsed_origin = urlsplit(origin)
                origin_host = parsed_origin.netloc.lower()
            except ValueError:
                return None
            if (parsed_origin.scheme not in {"http", "https"}
                    or not origin_host
                    or origin_host != str(host).lower()):
                return None
        if self._handshake_authorizer is None:
            if self._allow_anonymous:
                return {"user": None, "attributes": {}}
            authorization = ""
            try:
                authorization = websocket.headers.get("authorization", "")
            except Exception:
                pass
            token = ""
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            if not token and self._allow_query_token:
                try:
                    token = websocket.query_params.get("access_token", "")
                except Exception:
                    token = ""
            if not token:
                return None
            try:
                from springbootai.security.oauth2 import oauth2_resource_server
                if oauth2_resource_server.is_configured:
                    claims = await asyncio.to_thread(
                        oauth2_resource_server.validate_token, token)
                else:
                    from springbootai.security.jwt_utils import jwt_utils
                    claims = await asyncio.to_thread(
                        jwt_utils.decode_token, token)
            except Exception as exc:
                logger.info(
                    "WebSocket bearer token rejected error_type=%s",
                    type(exc).__name__,
                )
                return None
            user = claims.get("sub") or claims.get("username")
            return {
                "user": str(user) if user is not None else None,
                "attributes": {"principal": claims},
            }
        try:
            if inspect.iscoroutinefunction(self._handshake_authorizer):
                result = await self._handshake_authorizer(websocket)
            else:
                result = await asyncio.to_thread(
                    self._handshake_authorizer, websocket)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            logger.warning(
                "WebSocket handshake authorization failed error_type=%s",
                type(exc).__name__,
            )
            return None
        if result is True:
            return {"user": None, "attributes": {}}
        if isinstance(result, str) and result:
            return {"user": result, "attributes": {}}
        if isinstance(result, dict) and result.get("allowed", True):
            attributes = result.get("attributes", {})
            if not isinstance(attributes, dict):
                attributes = {}
            user = result.get("user")
            return {
                "user": str(user) if user is not None else None,
                "attributes": dict(attributes),
            }
        return None


def _is_server_endpoint(cls: Any) -> bool:
    """类是否标注 ``@ServerEndpoint``。"""
    if not isinstance(cls, type):
        return False
    from .handler import ServerEndpoint
    return any(isinstance(a, ServerEndpoint)
               for a in getattr(cls, "__spring_annotations__", []) or [])


def _is_message_endpoint(cls: Any) -> bool:
    """类是否标注 ``@MessageEndpoint``。"""
    if not isinstance(cls, type):
        return False
    return any(isinstance(a, MessageEndpoint)
               for a in getattr(cls, "__spring_annotations__", []) or [])


async def _safe_close(session: WebSocketSession, code: int, reason: str) -> None:
    try:
        await session.close(code=code, reason=reason)
    except Exception:
        pass


async def _safe_call(method: Callable, *args) -> None:
    try:
        result = method(*args)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.debug(
            "safe_call %s failed error_type=%s",
            getattr(method, "__name__", type(method).__name__),
            type(exc).__name__,
        )


def _is_disconnect(exc: Exception) -> bool:
    """判断异常是否是 WebSocket 断开（Starlette 抛 WebSocketDisconnect）。"""
    try:
        from starlette.websockets import WebSocketDisconnect
        if isinstance(exc, WebSocketDisconnect):
            return True
    except ImportError:
        pass
    # 兜底：按异常名/消息判断
    name = type(exc).__name__.lower()
    return "disconnect" in name or "closed" in str(exc).lower()


def install_websocket_routes(
    app: Any,
    classes: Optional[Iterable[Type]] = None,
    modules: Optional[Iterable[Any]] = None,
    router: Optional[WebSocketRouter] = None,
    **router_options,
) -> WebSocketRouter:
    """便捷函数：扫描 ``@ServerEndpoint`` 类并挂载到应用。

    Args:
        app:     Starlette/FastAPI 应用。
        classes: 显式传入的端点类列表。
        modules: 模块列表（扫描其中的 ``@ServerEndpoint`` 类）。
        router:  可选的预构造路由器；为 None 时新建。

    Returns:
        挂载完成的 ``WebSocketRouter``。
    """
    if router is not None and router_options:
        raise ValueError(
            "router_options cannot be used with an existing WebSocketRouter")
    r = router or WebSocketRouter(**router_options)
    endpoints = discover_server_endpoints(classes=classes, modules=modules)
    for path, cls in endpoints.items():
        if path not in r.routes:
            r.add_endpoint(path, cls)
    r.install(app)
    return r


__all__ = [
    "WebSocketRouter",
    "MessageEndpointDispatcher",
    "install_websocket_routes",
]
