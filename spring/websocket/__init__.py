"""SpringBootAI WebSocket 实时通信模块 —— 注解驱动的 WebSocket 端点与消息路由（对齐
JSR-356 ``@ServerEndpoint`` + Spring WebSocket ``@MessageMapping`` / ``@SendTo`` 体系）。

模块组成：
- **session**:   ``WebSocketSession`` 会话抽象 + ``WebSocketSessionRegistry`` 全局会话注册表
                  （对齐 Spring ``WebSocketSession`` / ``WebSocketHandlerRegistry``）
- **handler**:   ``WebSocketHandler`` 接口 + ``TextWebSocketHandler`` / ``BinaryWebSocketHandler``
                  便捷基类 + ``@ServerEndpoint`` 类级注解（JSR-356 风格生命周期钩子）
- **annotations**: ``@MessageMapping`` / ``@SendTo`` / ``@SendToUser`` / ``@SubscribeMapping``
                  方法级注解（Spring STOMP 风格消息路由）
- **broker**:    ``InMemoryBroker`` 主题式发布订阅代理（对齐 Spring ``SimpleBrokerMessageHandler``）
                  + ``SimpMessageSendingOperations`` 发送操作 API
- **router**:    ``WebSocketRouter`` 把注解端点转换为 Starlette/FastAPI WebSocket 路由
- **exceptions**: ``WebSocketException`` 异常族

设计原则：**复用项目既有范式，不重复造轮子**。
- ``@ServerEndpoint`` / ``@MessageMapping`` 等注解复用 ``SpringAnnotation`` 元数据描述符范式
  （与 ``spring.excel`` / ``spring.csv`` / ``spring.validation`` 一致）。
- 不依赖第三方 WebSocket 库；直接基于 Starlette ``WebSocket`` 原生能力。
- 不实现完整 STOMP 协议（复杂度过高）；采用简化 JSON 消息帧，对齐 Spring ``SimpleBroker``
  的核心语义（destination 路由 + topic 订阅）。

与 Java 的差异：
- JSR-356 在 Java EE 容器内注册端点；本实现通过 ``WebSocketRouter.install(app)`` 挂载到
  Starlette/FastAPI 应用。
- Spring STOMP 用 ``@EnableWebSocketMessageBroker`` + ``WebSocketMessageBrokerConfigurer``；
  本实现用 ``MessageBrokerConfigurer`` + ``WebSocketRouter`` 组合，更轻量。
- 不支持 STOMP ACK/NACK/事务（可按需扩展 ``InMemoryBroker``）。
"""
from .exceptions import (
    WebSocketException,
    WebSocketConnectionException,
    WebSocketHandlerException,
    MessageBrokerException,
)
from .session import (
    WebSocketSession,
    WebSocketSessionRegistry,
    global_session_registry,
)
from .handler import (
    WebSocketHandler,
    TextWebSocketHandler,
    BinaryWebSocketHandler,
    ServerEndpoint,
    AnnotatedEndpointHandler,
    discover_server_endpoints,
)
from .annotations import (
    MessageMapping,
    SendTo,
    SendToUser,
    SubscribeMapping,
    MessageEndpoint,
    collect_message_mappings,
    MessageMappingModel,
)
from .broker import (
    InMemoryBroker,
    SimpMessageSendingOperations,
    MessageBrokerConfigurer,
    broker_registry,
)
from .router import WebSocketRouter, MessageEndpointDispatcher, install_websocket_routes

__version__ = "2.1.0"

__all__ = [
    # 异常
    "WebSocketException", "WebSocketConnectionException",
    "WebSocketHandlerException", "MessageBrokerException",
    # 会话
    "WebSocketSession", "WebSocketSessionRegistry", "global_session_registry",
    # Handler / @ServerEndpoint
    "WebSocketHandler", "TextWebSocketHandler", "BinaryWebSocketHandler",
    "ServerEndpoint", "AnnotatedEndpointHandler", "discover_server_endpoints",
    # 注解
    "MessageMapping", "SendTo", "SendToUser", "SubscribeMapping", "MessageEndpoint",
    "MessageMappingModel", "collect_message_mappings",
    # Broker
    "InMemoryBroker", "SimpMessageSendingOperations",
    "MessageBrokerConfigurer", "broker_registry",
    # Router
    "WebSocketRouter", "MessageEndpointDispatcher", "install_websocket_routes",
    "__version__",
]
