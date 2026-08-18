"""不依赖 HTTP 对象的请求级上下文。

它只保存当前执行链的关联 ID，不负责保存监控计数。HTTP 请求由全局监控拦截器
自动建立和清理；后台任务可以显式使用：

    with request_scope("job-42"):
        service_call()  # 服务层可通过 get_request_id() 读取 ``job-42``

退出 ``with`` 后上下文会恢复，不会污染后续请求。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from .utils import new_request_id


_request_id: ContextVar[str | None] = ContextVar("example_all_request_id", default=None)


def get_request_id() -> str | None:
    """返回当前执行上下文中的关联 ID；未设置时返回 ``None``。"""
    return _request_id.get()


def set_request_id(value: str | None = None) -> Token[str | None]:
    """为当前上下文设置 ID，并返回用于恢复上下文的令牌。"""
    return _request_id.set(value.strip() if value and value.strip() else new_request_id())


def reset_request_id(token: Token[str | None]) -> None:
    """Controller 操作完成后恢复原请求上下文。"""
    _request_id.reset(token)


@contextmanager
def request_scope(value: str | None = None) -> Iterator[str]:
    """在临时作用域内向服务和日志工具暴露一个请求 ID。"""
    token = set_request_id(value)
    try:
        yield _request_id.get() or ""
    finally:
        reset_request_id(token)


__all__ = ["get_request_id", "request_scope", "reset_request_id", "set_request_id"]
