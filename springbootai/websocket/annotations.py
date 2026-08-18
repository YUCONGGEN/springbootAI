"""WebSocket 消息映射注解（对齐 Spring ``@MessageMapping`` / ``@SendTo`` / ``@SendToUser``
/ ``@SubscribeMapping``）。

注解语义（与 Spring STOMP 一致）：
- ``@MessageMapping("/chat")``       方法处理发往 ``/chat`` 的消息（``/app`` 前缀由配置剥离）。
- ``@SendTo("/topic/greetings")``    方法返回值自动广播到 ``/topic/greetings``。
                                      不标注时默认回发给发送者（对齐 Spring ``@SendToUser`` 默认）。
- ``@SendToUser``                    方法返回值定向发给发送者（对齐 Spring ``@SendToUser``）。
- ``@SubscribeMapping("/topic/x")``  客户端订阅时触发，方法返回值作为初始数据回发给订阅者。
- ``@MessageEndpoint``               类级注解，标记一个类包含 ``@MessageMapping`` 方法
                                      （对齐 Spring ``@MessageMapping``+``@Controller`` 组合）。

注解本身只注册元数据；实际方法包装在 ``MessageEndpointDispatcher``（见 router.py）中完成。
"""
from __future__ import annotations

from typing import List, Optional, Type

from springbootai.annotations.core import SpringAnnotation


# ==================== 类级注解 ====================

class MessageEndpoint(SpringAnnotation):
    """``@MessageEndpoint`` 类级注解，标记一个类为消息端点（含 ``@MessageMapping`` 方法）。

    等价于 Spring ``@Controller`` + ``@MessageMapping`` 的组合约定。
    """

    _annotation_type = "message_endpoint"


# ==================== 方法级注解 ====================

class MessageMapping(SpringAnnotation):
    """``@MessageMapping("/chat")`` 方法级注解，声明消息处理方法。

    用法::

        @MessageEndpoint
        class GreetingController:
            @MessageMapping("/greet")
            @SendTo("/topic/greetings")
            def greet(self, message):
                return {"content": "Hello, " + message["name"]}

    客户端发送 ``{"destination": "/app/greet", "payload": {"name": "Tom"}}`` 时触发。
    """

    _annotation_type = "message_mapping"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class SendTo(SpringAnnotation):
    """``@SendTo("/topic/greetings")`` 方法级注解，把返回值广播到指定 destination。

    不标注时，方法返回值默认回发给发送者（等价于 ``@SendToUser``）。
    """

    _annotation_type = "send_to"

    def __init__(self, value: str = ""):
        # 支持单 destination 或多 destination（逗号分隔）
        dests = [v.strip() for v in value.split(",") if v.strip()] if value else []
        super().__init__(value=value, destinations=dests)


class SendToUser(SpringAnnotation):
    """``@SendToUser`` 方法级注解，把返回值定向发给发送者（不广播）。

    可指定 ``broadcast``（False 时只发给当前会话；True 时发给该用户所有会话）。
    """

    _annotation_type = "send_to_user"

    def __init__(self, broadcast: bool = False):
        super().__init__(broadcast=broadcast)


class SubscribeMapping(SpringAnnotation):
    """``@SubscribeMapping("/topic/init")`` 方法级注解，订阅时触发并返回初始数据。

    与 ``@MessageMapping`` 区别：``@SubscribeMapping`` 在客户端订阅 destination 时触发，
    返回值直接回发给订阅者（不经过 broker 广播）。
    """

    _annotation_type = "subscribe_mapping"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


# ==================== 元数据模型 ====================

class MessageMappingModel:
    """解析后的消息映射元数据，供 ``router.MessageEndpointDispatcher`` 消费。"""

    __slots__ = (
        "method_name", "destination", "send_to", "send_to_user",
        "send_to_user_broadcast", "subscribe_destination", "is_subscribe",
    )

    def __init__(
        self,
        method_name: str,
        destination: str,
        send_to: Optional[List[str]] = None,
        send_to_user: bool = False,
        send_to_user_broadcast: bool = False,
        subscribe_destination: str = "",
        is_subscribe: bool = False,
    ):
        self.method_name = method_name
        self.destination = destination
        self.send_to = send_to or []
        self.send_to_user = send_to_user
        self.send_to_user_broadcast = send_to_user_broadcast
        self.subscribe_destination = subscribe_destination
        self.is_subscribe = is_subscribe


# ==================== 元数据收集 ====================

def collect_message_mappings(cls: Type) -> List[MessageMappingModel]:
    """收集类上所有 ``@MessageMapping`` / ``@SubscribeMapping`` 方法的元数据。

    遍历 ``cls.__dict__``（仅本类，不含继承），为每个标注方法构造 ``MessageMappingModel``。
    同时读取方法上的 ``@SendTo`` / ``@SendToUser`` 决定返回值去向。
    """
    models: List[MessageMappingModel] = []
    for name, method in vars(cls).items():
        if not callable(method):
            continue
        annotations = getattr(method, "__spring_annotations__", []) or []
        # 优先 @MessageMapping
        msg_mapping = next((a for a in annotations if isinstance(a, MessageMapping)), None)
        sub_mapping = next((a for a in annotations if isinstance(a, SubscribeMapping)), None)
        if msg_mapping is None and sub_mapping is None:
            continue
        send_to = next((a for a in annotations if isinstance(a, SendTo)), None)
        send_to_user = next((a for a in annotations if isinstance(a, SendToUser)), None)

        send_to_dests = send_to.destinations if send_to else []
        is_subscribe = sub_mapping is not None
        destination = (sub_mapping.value if is_subscribe else msg_mapping.value) or ""

        models.append(MessageMappingModel(
            method_name=name,
            destination=destination,
            send_to=send_to_dests,
            send_to_user=bool(send_to_user) or (not send_to_dests and not is_subscribe),
            send_to_user_broadcast=getattr(send_to_user, "broadcast", False) if send_to_user else False,
            subscribe_destination=destination if is_subscribe else "",
            is_subscribe=is_subscribe,
        ))
    return models


__all__ = [
    "MessageEndpoint",
    "MessageMapping",
    "SendTo",
    "SendToUser",
    "SubscribeMapping",
    "MessageMappingModel",
    "collect_message_mappings",
]
