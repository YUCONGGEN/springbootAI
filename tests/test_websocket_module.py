"""SpringBootAI WebSocket 实时通信模块测试 —— 覆盖 WebSocketSession / WebSocketHandler /
@ServerEndpoint / @MessageMapping / @SendTo / broker / router 全链路。

对齐 tests/test_i18n_module.py 的 pytest + Starlette TestClient 风格。
异步测试统一用 ``asyncio.run()``（对齐项目既有 ``test_datasource_routing.py`` /
``test_transactional_events.py`` 风格，不依赖 pytest-asyncio）。
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from springbootai.websocket import (
    WebSocketSession, WebSocketSessionRegistry,
    WebSocketHandler, TextWebSocketHandler, BinaryWebSocketHandler,
    ServerEndpoint, AnnotatedEndpointHandler, discover_server_endpoints,
    MessageMapping, SendTo, SubscribeMapping, MessageEndpoint,
    collect_message_mappings,
    InMemoryBroker, SimpMessageSendingOperations,
    MessageBrokerConfigurer, WebSocketRouter, MessageEndpointDispatcher, install_websocket_routes,
    WebSocketException, WebSocketHandlerException, MessageBrokerException,
)


def run(coro):
    """运行协程并返回结果（统一入口，便于将来切换 event loop 策略）。"""
    return asyncio.run(coro)


# ==================== WebSocketSession ====================

class _FakeWebSocket:
    """最小 WebSocket 桩，支持 send_text/send_json/receive_text/close。"""

    def __init__(self):
        self.sent = []          # 已发送消息列表
        self.received = []      # 待接收消息队列
        self.closed = False
        self.close_code = None
        self.close_reason = None

    async def send_text(self, msg):
        self.sent.append(("text", msg))

    async def send_bytes(self, data):
        self.sent.append(("bytes", data))

    async def send_json(self, data):
        self.sent.append(("json", data))

    async def receive_text(self):
        return self.received.pop(0)

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_code = code
        self.close_reason = reason


class TestWebSocketSession:
    def test_unique_id(self):
        s1 = WebSocketSession(_FakeWebSocket())
        s2 = WebSocketSession(_FakeWebSocket())
        assert s1.id != s2.id

    def test_attributes_dict(self):
        s = WebSocketSession(_FakeWebSocket())
        s.attributes["user_id"] = 42
        assert s.attributes["user_id"] == 42

    def test_is_open_initially(self):
        s = WebSocketSession(_FakeWebSocket())
        assert s.is_open is True
        assert s.is_closed is False

    def test_send_text(self):
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        run(s.send_text("hello"))
        assert ws.sent == [("text", "hello")]

    def test_send_json(self):
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        run(s.send_json({"k": "v"}))
        assert ws.sent == [("json", {"k": "v"})]

    def test_close_marks_closed(self):
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        run(s.close(code=1001, reason="bye"))
        assert s.is_closed is True
        assert s.is_open is False
        assert ws.closed is True
        assert ws.close_code == 1001

    def test_send_after_closed_noop(self):
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        run(s.close())
        run(s.send_text("after close"))  # 应静默跳过
        assert ws.sent == []

    def test_user_property(self):
        s = WebSocketSession(_FakeWebSocket(), user="alice")
        assert s.user == "alice"
        s.user = "bob"
        assert s.user == "bob"


# ==================== WebSocketSessionRegistry ====================

class TestSessionRegistry:
    def test_register_and_get(self):
        reg = WebSocketSessionRegistry()
        s = WebSocketSession(_FakeWebSocket())
        reg.register(s)
        assert reg.get(s.id) is s
        assert reg.count() == 1

    def test_unregister(self):
        reg = WebSocketSessionRegistry()
        s = WebSocketSession(_FakeWebSocket())
        reg.register(s)
        reg.unregister(s.id)
        assert reg.get(s.id) is None
        assert reg.count() == 0

    def test_send_to_user(self):
        reg = WebSocketSessionRegistry()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1, user="alice")
        s2 = WebSocketSession(ws2, user="bob")
        reg.register(s1)
        reg.register(s2)
        sent = run(reg.send_to_user("alice", {"msg": "hi"}))
        assert sent == 1
        assert ws1.sent == [("json", {"msg": "hi"})]
        assert ws2.sent == []

    def test_broadcast(self):
        reg = WebSocketSessionRegistry()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        reg.register(s1)
        reg.register(s2)
        sent = run(reg.broadcast("hello", as_json=False))
        assert sent == 2
        assert ws1.sent == [("text", "hello")]
        assert ws2.sent == [("text", "hello")]

    def test_broadcast_exclude(self):
        reg = WebSocketSessionRegistry()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        reg.register(s1)
        reg.register(s2)
        sent = run(reg.broadcast("hello", as_json=False, exclude=[s1.id]))
        assert sent == 1
        assert ws1.sent == []
        assert ws2.sent == [("text", "hello")]

    def test_broadcast_skips_closed(self):
        reg = WebSocketSessionRegistry()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        run(s1.close())
        reg.register(s1)
        reg.register(s2)
        sent = run(reg.broadcast("hi", as_json=False))
        assert sent == 1
        assert ws2.sent == [("text", "hi")]

    def test_close_all(self):
        reg = WebSocketSessionRegistry()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        reg.register(s1)
        reg.register(s2)
        run(reg.close_all(code=1001, reason="shutdown"))
        assert s1.is_closed and s2.is_closed
        assert reg.count() == 0


# ==================== @ServerEndpoint + Handler ====================

@ServerEndpoint("/ws/echo")
class EchoEndpoint:
    """测试用 echo 端点：把收到的文本原样回发。"""

    async def on_open(self, session):
        await session.send_text("welcome")

    async def on_message(self, session, message):
        await session.send_text("echo: " + message)

    async def on_close(self, session, reason):
        await session.send_text(f"bye: {reason}")


@ServerEndpoint("/ws/lifecycle")
class FullLifecycleEndpoint:
    """完整生命周期端点，记录每次钩子调用。"""

    def __init__(self):
        self.events = []

    async def on_open(self, session):
        self.events.append(("open", session.id))

    async def on_message(self, session, message):
        self.events.append(("message", message))

    async def on_close(self, session, reason):
        self.events.append(("close", reason))

    async def on_error(self, session, error):
        self.events.append(("error", str(error)))


class TestServerEndpointAnnotation:
    def test_annotation_metadata(self):
        annotations = EchoEndpoint.__spring_annotations__
        se = next(a for a in annotations if isinstance(a, ServerEndpoint))
        assert se.value == "/ws/echo"

    def test_discover_endpoints(self):
        result = discover_server_endpoints(classes=[EchoEndpoint, FullLifecycleEndpoint])
        assert result["/ws/echo"] is EchoEndpoint
        assert result["/ws/lifecycle"] is FullLifecycleEndpoint

    def test_discover_ignores_non_annotated(self):
        class NoAnnotation:
            pass
        result = discover_server_endpoints(classes=[NoAnnotation])
        assert result == {}


class TestAnnotatedEndpointHandler:
    def test_lifecycle_calls(self):
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        handler = AnnotatedEndpointHandler(EchoEndpoint)
        run(handler.after_connection_established(session))
        assert ws.sent == [("text", "welcome")]
        run(handler.handle_text_message(session, "hi"))
        assert ws.sent[-1] == ("text", "echo: hi")
        run(handler.after_connection_closed(session, "test"))
        assert ws.sent[-1] == ("text", "bye: test")

    def test_missing_hooks_noop(self):
        @ServerEndpoint("/ws/min")
        class MinimalEndpoint:
            pass
        handler = AnnotatedEndpointHandler(MinimalEndpoint)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        # 不抛异常即可
        run(handler.after_connection_established(session))
        run(handler.handle_text_message(session, "msg"))
        run(handler.after_connection_closed(session, "r"))
        assert ws.sent == []

    def test_on_error_caught(self):
        @ServerEndpoint("/ws/err")
        class ErrorEndpoint:
            async def on_message(self, session, message):
                raise ValueError("boom")

        handler = AnnotatedEndpointHandler(ErrorEndpoint)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        # 异常应包装为 WebSocketHandlerException
        with pytest.raises(WebSocketHandlerException):
            run(handler.handle_text_message(session, "x"))


# ==================== Handler 接口 ====================

class TestHandlerInterfaces:
    def test_text_handler_rejects_binary(self):
        class EchoText(TextWebSocketHandler):
            async def handle_text_message(self, session, message):
                await session.send_text(message)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        handler = EchoText()
        with pytest.raises(WebSocketHandlerException):
            run(handler.handle_binary_message(session, b"bytes"))

    def test_binary_handler_rejects_text(self):
        class EchoBinary(BinaryWebSocketHandler):
            async def handle_binary_message(self, session, data):
                await session.send_bytes(data)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        handler = EchoBinary()
        with pytest.raises(WebSocketHandlerException):
            run(handler.handle_text_message(session, "text"))

    def test_handler_default_noops(self):
        handler = WebSocketHandler()
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        # 默认实现不应抛异常
        run(handler.after_connection_established(session))
        run(handler.handle_message(session, "msg"))
        run(handler.after_connection_closed(session, "r"))
        assert handler.supports_partial_messages() is False


# ==================== InMemoryBroker ====================

class TestInMemoryBroker:
    def test_subscribe_and_publish(self):
        broker = InMemoryBroker()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        broker.subscribe("/topic/news", s1)
        broker.subscribe("/topic/news", s2)
        assert broker.subscriber_count("/topic/news") == 2
        sent = run(broker.publish("/topic/news", {"title": "hello"}))
        assert sent == 2
        # 两个订阅者都收到
        assert ws1.sent[0] == ("json", {"destination": "/topic/news", "payload": {"title": "hello"}})
        assert ws2.sent[0] == ("json", {"destination": "/topic/news", "payload": {"title": "hello"}})

    def test_unsubscribe(self):
        broker = InMemoryBroker()
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        broker.subscribe("/topic/x", s)
        assert broker.unsubscribe("/topic/x", s.id) is True
        assert broker.subscriber_count("/topic/x") == 0

    def test_publish_excludes_session(self):
        broker = InMemoryBroker()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        broker.subscribe("/topic/x", s1)
        broker.subscribe("/topic/x", s2)
        sent = run(broker.publish("/topic/x", "hi", exclude=[s1.id]))
        assert sent == 1
        assert ws1.sent == []
        assert ws2.sent[0] == ("json", {"destination": "/topic/x", "payload": "hi"})

    def test_publish_skips_closed_and_cleans_subscription(self):
        broker = InMemoryBroker()
        ws1 = _FakeWebSocket()
        ws2 = _FakeWebSocket()
        s1 = WebSocketSession(ws1)
        s2 = WebSocketSession(ws2)
        run(s1.close())
        broker.subscribe("/topic/x", s1)
        broker.subscribe("/topic/x", s2)
        sent = run(broker.publish("/topic/x", "hi"))
        assert sent == 1
        # 失效会话应被清理
        assert broker.subscriber_count("/topic/x") == 1

    def test_unsubscribe_all(self):
        broker = InMemoryBroker()
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        broker.subscribe("/topic/a", s)
        broker.subscribe("/topic/b", s)
        n = broker.unsubscribe_all(s.id)
        assert n == 2
        assert broker.subscriber_count("/topic/a") == 0
        assert broker.subscriber_count("/topic/b") == 0

    def test_publish_empty_destination_raises(self):
        broker = InMemoryBroker()
        with pytest.raises(MessageBrokerException):
            run(broker.publish("", "x"))

    def test_subscribe_empty_destination_raises(self):
        broker = InMemoryBroker()
        with pytest.raises(MessageBrokerException):
            broker.subscribe("", WebSocketSession(_FakeWebSocket()))

    def test_subscription_and_message_limits_are_enforced(self):
        broker = InMemoryBroker(
            max_destinations=1,
            max_subscriptions_per_session=1,
            max_message_size=32,
        )
        session = WebSocketSession(_FakeWebSocket())
        broker.subscribe("/topic/a", session)
        with pytest.raises(MessageBrokerException, match="订阅数"):
            broker.subscribe("/topic/b", session)
        with pytest.raises(MessageBrokerException, match="size limit"):
            run(broker.publish("/topic/a", "x" * 100))


# ==================== SimpMessageSendingOperations ====================

class TestSimpMessageSendingOperations:
    def test_convert_and_send(self):
        broker = InMemoryBroker()
        ops = SimpMessageSendingOperations(broker)
        ws = _FakeWebSocket()
        s = WebSocketSession(ws)
        broker.subscribe("/topic/x", s)
        sent = run(ops.convert_and_send("/topic/x", {"hello": "world"}))
        assert sent == 1
        assert ws.sent[0] == ("json", {"destination": "/topic/x", "payload": {"hello": "world"}})

    def test_convert_and_send_to_user(self):
        # 用一个简单的 session registry
        reg = WebSocketSessionRegistry()
        broker = InMemoryBroker()
        ops = SimpMessageSendingOperations(broker, session_registry=reg)
        ws = _FakeWebSocket()
        s = WebSocketSession(ws, user="alice")
        reg.register(s)
        sent = run(ops.convert_and_send_to_user("alice", "/queue/private", "hi"))
        assert sent == 1
        assert ws.sent[0] == ("json", {"destination": "/queue/private", "payload": "hi"})


# ==================== MessageBrokerConfigurer ====================

class TestMessageBrokerConfigurer:
    def test_default_prefixes(self):
        cfg = MessageBrokerConfigurer()
        assert cfg.application_destination_prefixes == ["/app"]
        assert cfg.broker_prefixes == ["/topic", "/queue"]
        assert cfg.user_destination_prefix == "/user"

    def test_strip_app_prefix(self):
        cfg = MessageBrokerConfigurer()
        assert cfg.strip_app_prefix("/app/greet") == "/greet"
        assert cfg.strip_app_prefix("/app") == ""
        assert cfg.strip_app_prefix("/topic/x") is None

    def test_is_broker_destination(self):
        cfg = MessageBrokerConfigurer()
        assert cfg.is_broker_destination("/topic/x") is True
        assert cfg.is_broker_destination("/queue/y") is True
        assert cfg.is_broker_destination("/app/greet") is False
        assert cfg.is_broker_destination("/unknown") is False

    def test_custom_prefixes(self):
        cfg = MessageBrokerConfigurer(
            application_destination_prefixes=["/msg"],
            broker_prefixes=["/chan"],
            user_destination_prefix="/u",
        )
        assert cfg.application_destination_prefixes == ["/msg"]
        assert cfg.broker_prefixes == ["/chan"]
        assert cfg.user_destination_prefix == "/u"
        assert cfg.strip_app_prefix("/msg/x") == "/x"
        assert cfg.is_broker_destination("/chan/x") is True


# ==================== @MessageMapping + @SendTo ====================

@MessageEndpoint
class GreetingController:
    """测试用消息端点：``/app/greet`` → 广播到 ``/topic/greetings``。"""

    @MessageMapping("/greet")
    @SendTo("/topic/greetings")
    async def greet(self, payload):
        return {"content": "Hello, " + payload["name"] + "!"}

    @MessageMapping("/echo")
    def echo(self, payload):
        # 无 @SendTo，默认回发给发送者
        return {"echo": payload}


@MessageEndpoint
class SubscribeController:
    """``@SubscribeMapping`` 端点：订阅时回发初始数据。"""

    @SubscribeMapping("/topic/init")
    def on_subscribe(self, payload):
        return {"init": "welcome"}


class TestMessageMappingAnnotations:
    def test_collect_message_mappings(self):
        models = collect_message_mappings(GreetingController)
        # 两个 @MessageMapping 方法
        assert len(models) == 2
        greet = next(m for m in models if m.destination == "/greet")
        assert greet.send_to == ["/topic/greetings"]
        assert greet.is_subscribe is False
        echo = next(m for m in models if m.destination == "/echo")
        assert echo.send_to == []
        # 无 @SendTo 的 @MessageMapping：默认 send_to_user=True
        assert echo.send_to_user is True

    def test_subscribe_mapping_collected(self):
        models = collect_message_mappings(SubscribeController)
        assert len(models) == 1
        m = models[0]
        assert m.is_subscribe is True
        assert m.subscribe_destination == "/topic/init"


class TestMessageEndpointDispatcher:
    def test_message_mapping_with_send_to_broadcasts(self):
        # 准备：一个订阅了 /topic/greetings 的会话
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws_subscriber = _FakeWebSocket()
        subscriber_session = WebSocketSession(ws_subscriber)
        cfg.broker.subscribe("/topic/greetings", subscriber_session)

        # 调用 dispatch：模拟发送者发 /app/greet
        ws_sender = _FakeWebSocket()
        sender_session = WebSocketSession(ws_sender)
        frame = {"action": "message", "destination": "/app/greet", "payload": {"name": "Tom"}}
        run(dispatcher.handle_text_message(sender_session, json.dumps(frame)))

        # 订阅者应收到广播
        assert len(ws_subscriber.sent) == 1
        broadcast = ws_subscriber.sent[0][1]
        assert broadcast["destination"] == "/topic/greetings"
        assert broadcast["payload"] == {"content": "Hello, Tom!"}

    def test_message_mapping_without_send_to_replies_to_sender(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        frame = {"action": "message", "destination": "/app/echo", "payload": "ping"}
        run(dispatcher.handle_text_message(session, json.dumps(frame)))
        # 发送者应直接收到回发
        assert len(ws.sent) == 1
        reply = ws.sent[0][1]
        assert reply["destination"] == "/app/echo"
        assert reply["payload"] == {"echo": "ping"}

    def test_subscribe_action_with_subscribe_mapping(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(SubscribeController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        # 订阅 /topic/init：触发 @SubscribeMapping，回发初始数据
        frame = {"action": "subscribe", "destination": "/topic/init"}
        run(dispatcher.handle_text_message(session, json.dumps(frame)))
        assert len(ws.sent) == 1
        assert ws.sent[0][1]["payload"] == {"init": "welcome"}

    def test_subscribe_action_registers_to_broker(self):
        cfg = MessageBrokerConfigurer()
        # 用一个有 @MessageMapping 但无 @SubscribeMapping 的端点
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        frame = {"action": "subscribe", "destination": "/topic/greetings"}
        run(dispatcher.handle_text_message(session, json.dumps(frame)))
        assert cfg.broker.subscriber_count("/topic/greetings") == 1

    def test_unsubscribe_action(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        cfg.broker.subscribe("/topic/x", session)
        frame = {"action": "unsubscribe", "destination": "/topic/x"}
        run(dispatcher.handle_text_message(session, json.dumps(frame)))
        assert cfg.broker.subscriber_count("/topic/x") == 0

    def test_message_to_broker_destination_publishes(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws_sub = _FakeWebSocket()
        sub_session = WebSocketSession(ws_sub)
        cfg.broker.subscribe("/topic/news", sub_session)

        ws_sender = _FakeWebSocket()
        sender_session = WebSocketSession(ws_sender)
        # 直接发到 /topic/news：broker 转发（排除发送者）
        frame = {"action": "message", "destination": "/topic/news", "payload": "news"}
        run(dispatcher.handle_text_message(sender_session, json.dumps(frame)))
        assert ws_sub.sent[0][1]["payload"] == "news"

    def test_invalid_json_raises(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        with pytest.raises(WebSocketHandlerException):
            run(dispatcher.handle_text_message(session, "not-json"))

    def test_unknown_action_raises(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        frame = {"action": "bogus", "destination": "/x"}
        with pytest.raises(WebSocketHandlerException):
            run(dispatcher.handle_text_message(session, json.dumps(frame)))

    def test_no_handler_for_destination_raises(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        frame = {"action": "message", "destination": "/app/unknown", "payload": "x"}
        with pytest.raises(MessageBrokerException):
            run(dispatcher.handle_text_message(session, json.dumps(frame)))

    def test_connection_closed_unsubscribes(self):
        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(GreetingController, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        cfg.broker.subscribe("/topic/x", session)
        run(dispatcher.after_connection_closed(session, "test"))
        assert cfg.broker.subscriber_count("/topic/x") == 0

    def test_method_accepts_session_param(self):
        @MessageEndpoint
        class C:
            @MessageMapping("/with-session")
            def handle(self, payload, session):
                return {"sid": session.id}

        cfg = MessageBrokerConfigurer()
        dispatcher = MessageEndpointDispatcher(C, configurer=cfg)
        ws = _FakeWebSocket()
        session = WebSocketSession(ws)
        frame = {"action": "message", "destination": "/app/with-session", "payload": "x"}
        run(dispatcher.handle_text_message(session, json.dumps(frame)))
        assert ws.sent[0][1]["payload"] == {"sid": session.id}


# ==================== WebSocketRouter + 集成测试 ====================

class TestWebSocketRouter:
    def test_add_handler(self):
        router = WebSocketRouter()
        handler = TextWebSocketHandler()
        router.add_handler("/ws/x", handler)
        assert "/ws/x" in router.routes

    def test_add_endpoint_server_endpoint(self):
        router = WebSocketRouter()
        router.add_endpoint("/ws/echo", EchoEndpoint)
        assert "/ws/echo" in router.routes

    def test_add_endpoint_handler_subclass(self):
        class MyHandler(TextWebSocketHandler):
            pass
        router = WebSocketRouter()
        router.add_endpoint("/ws/h", MyHandler)
        assert "/ws/h" in router.routes

    def test_add_endpoint_unsupported_raises(self):
        class NotAnEndpoint:
            pass
        router = WebSocketRouter()
        with pytest.raises(WebSocketHandlerException):
            router.add_endpoint("/ws/x", NotAnEndpoint)

    def test_duplicate_path_raises(self):
        router = WebSocketRouter()
        router.add_handler("/ws/x", TextWebSocketHandler())
        with pytest.raises(WebSocketException):
            router.add_handler("/ws/x", TextWebSocketHandler())

    def test_add_message_endpoint(self):
        router = WebSocketRouter()
        router.add_message_endpoint("/ws/app", GreetingController)
        assert "/ws/app" in router.routes

    def test_add_message_endpoint_requires_annotation(self):
        class NotAnnotated:
            pass
        router = WebSocketRouter()
        with pytest.raises(WebSocketHandlerException):
            router.add_message_endpoint("/ws/x", NotAnnotated)

    def test_default_routers_do_not_share_sessions_or_broker(self):
        first = WebSocketRouter()
        second = WebSocketRouter()
        assert first.session_registry is not second.session_registry
        assert first.configurer.broker is not second.configurer.broker
        assert first.configurer.session_registry is first.session_registry

    def test_query_token_is_disabled_and_non_http_origin_is_rejected(self):
        websocket = SimpleNamespace(
            headers={"host": "app.test", "origin": "https://app.test"},
            query_params={"access_token": "token"},
        )
        assert run(WebSocketRouter()._authorize_handshake(websocket)) is None

        bad_origin = SimpleNamespace(
            headers={"host": "app.test", "origin": "javascript://app.test"},
            query_params={},
        )
        assert run(WebSocketRouter(
            allow_anonymous=True)._authorize_handshake(bad_origin)) is None


class TestIntegrationWithStarlette:
    """端到端：通过 Starlette TestClient 连接真实 WebSocket。"""

    @pytest.fixture
    def app_and_router(self):
        from starlette.applications import Starlette
        # 独立 router + configurer 避免污染全局
        cfg = MessageBrokerConfigurer()
        # Anonymous access is an explicit test/demo choice; production router
        # defaults now require a validated bearer token.
        router = WebSocketRouter(configurer=cfg, allow_anonymous=True)
        app = Starlette()
        return app, router, cfg

    def test_server_endpoint_echo(self, app_and_router):
        app, router, _ = app_and_router
        router.add_endpoint("/ws/echo", EchoEndpoint)
        router.install(app)

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            with client.websocket_connect("/ws/echo") as ws:
                # on_open 发的 welcome
                welcome = ws.receive_text()
                assert welcome == "welcome"
                ws.send_text("hello")
                reply = ws.receive_text()
                assert reply == "echo: hello"

    def test_message_endpoint_send_to(self, app_and_router):
        app, router, cfg = app_and_router
        router.add_message_endpoint("/ws/app", GreetingController)
        router.install(app)

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            # 1. 订阅者连接并订阅 /topic/greetings
            with client.websocket_connect("/ws/app") as sub_ws:
                sub_ws.send_text(json.dumps({
                    "action": "subscribe", "destination": "/topic/greetings"
                }))
                # 2. 发送者连接并发 /app/greet
                with client.websocket_connect("/ws/app") as sender_ws:
                    sender_ws.send_text(json.dumps({
                        "action": "message",
                        "destination": "/app/greet",
                        "payload": {"name": "Tom"},
                    }))
                # 3. 订阅者应收到广播
                msg = sub_ws.receive_json()
                assert msg["destination"] == "/topic/greetings"
                assert msg["payload"] == {"content": "Hello, Tom!"}

    def test_message_endpoint_echo_replies_to_sender(self, app_and_router):
        app, router, _ = app_and_router
        router.add_message_endpoint("/ws/app", GreetingController)
        router.install(app)

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            with client.websocket_connect("/ws/app") as ws:
                ws.send_text(json.dumps({
                    "action": "message",
                    "destination": "/app/echo",
                    "payload": "ping",
                }))
                reply = ws.receive_json()
                assert reply["destination"] == "/app/echo"
                assert reply["payload"] == {"echo": "ping"}

    def test_handler_subclass_integration(self, app_and_router):
        class CounterHandler(TextWebSocketHandler):
            async def after_connection_established(self, session):
                await session.send_text("connected")

            async def handle_text_message(self, session, message):
                await session.send_text(f"got: {message}")

        app, router, _ = app_and_router
        router.add_handler("/ws/counter", CounterHandler())
        router.install(app)

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            with client.websocket_connect("/ws/counter") as ws:
                assert ws.receive_text() == "connected"
                ws.send_text("hi")
                assert ws.receive_text() == "got: hi"

    def test_install_websocket_routes_helper(self):
        from starlette.applications import Starlette
        app = Starlette()
        # 扫描当前测试模块的 @ServerEndpoint 类
        router = install_websocket_routes(
            app, classes=[EchoEndpoint], allow_anonymous=True)
        assert "/ws/echo" in router.routes

        from starlette.testclient import TestClient
        with TestClient(app) as client:
            with client.websocket_connect("/ws/echo") as ws:
                assert ws.receive_text() == "welcome"
                ws.send_text("xyz")
                assert ws.receive_text() == "echo: xyz"

    def test_session_registry_tracks_sessions(self, app_and_router):
        app, router, cfg = app_and_router
        router.add_endpoint("/ws/echo", EchoEndpoint)
        router.install(app)

        from starlette.testclient import TestClient
        reg = router.session_registry
        assert reg.count() == 0
        with TestClient(app) as client:
            with client.websocket_connect("/ws/echo") as ws:
                ws.receive_text()  # welcome
                assert reg.count() == 1
            # 断开后注册表应清理
            # 给一点时间让 finally 执行
            import time
            time.sleep(0.1)
            assert reg.count() == 0
