"""``LocaleResolverMiddleware`` Starlette 中间件（对齐 Spring ``LocaleChangeInterceptor`` +
``DispatcherServlet`` 的 locale 解析逻辑）。

中间件在每个请求开始时：
1. 用配置的 ``LocaleResolver`` 从请求解析 ``LocaleContext``；
2. 写入 ``LocaleContextHolder``（``ContextVar``，协程安全）；
3. 把 ``LocaleContext`` 挂到 ``request.state.locale_context`` 供后续路由读取；
4. 请求结束 ``reset_locale_context()``，避免泄漏。

中间件不依赖 FastAPI，仅依赖 Starlette ``BaseHTTPMiddleware`` / ``Request``。
"""
from __future__ import annotations

from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .holder import LocaleContextHolder
from .locale import Locale
from .locale_resolver import (
    AcceptHeaderLocaleResolver,
    LocaleContext,
    LocaleResolver,
    SimpleLocaleContext,
)


class LocaleResolverMiddleware(BaseHTTPMiddleware):
    """HTTP 中间件：解析 locale 并写入 ``LocaleContextHolder``。

    Args:
        app:             ASGI 应用。
        locale_resolver: 区域解析器；默认 ``AcceptHeaderLocaleResolver``。
    """

    def __init__(self, app, locale_resolver: Optional[LocaleResolver] = None):
        super().__init__(app)
        self._resolver: LocaleResolver = locale_resolver or AcceptHeaderLocaleResolver()

    @property
    def locale_resolver(self) -> LocaleResolver:
        return self._resolver

    async def dispatch(self, request: Request, call_next):
        # 1. 解析 locale
        try:
            context = self._resolver.resolve_locale(request)
        except Exception:
            # 解析失败兜底：空 locale，避免中间件把请求 500
            context = SimpleLocaleContext(Locale(""))
        # 2. 写入 ContextVar（协程安全），返回 token 用于精确复位（支持嵌套）
        token = LocaleContextHolder.set_locale_context(context)
        # 3. 挂到 request.state 供路由读取
        try:
            request.state.locale_context = context
        except Exception:
            pass
        try:
            response = await call_next(request)
        finally:
            # 4. 请求结束用 token 复位（即使异常也复位，支持嵌套调用）
            LocaleContextHolder.reset_locale_context(token)
        return response


def get_request_locale(request: Optional[Request]) -> Locale:
    """从请求 ``state.locale_context`` 或 ``LocaleContextHolder`` 取当前 locale。

    优先级：``request.state.locale_context`` > ``LocaleContextHolder`` > 空 ``Locale``。
    """
    if request is not None:
        ctx = getattr(getattr(request, "state", None), "locale_context", None)
        if isinstance(ctx, LocaleContext):
            return ctx.get_locale()
    return LocaleContextHolder.get_locale()


__all__ = ["LocaleResolverMiddleware", "get_request_locale"]
