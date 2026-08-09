"""WebSocket 模块异常族（对齐 Spring ``WebSocketException`` 体系）。"""
from __future__ import annotations


class WebSocketException(Exception):
    """WebSocket 模块根异常（对齐 Spring ``WebSocketException``）。"""


class WebSocketConnectionException(WebSocketException):
    """连接级异常（握手失败、连接断开等）。"""


class WebSocketHandlerException(WebSocketException):
    """处理器执行异常（``on_message`` 抛错、消息路由失败等）。"""


class MessageBrokerException(WebSocketException):
    """消息代理异常（订阅失败、destination 解析失败等）。"""


__all__ = [
    "WebSocketException",
    "WebSocketConnectionException",
    "WebSocketHandlerException",
    "MessageBrokerException",
]
