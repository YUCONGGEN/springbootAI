"""``LocaleContextHolder`` 区域上下文持有器（对齐 Spring ``LocaleContextHolder``）。

使用 ``ContextVar`` 保证线程与 ``asyncio`` 协程间的隔离（与 ``spring.datasource`` 动态路由
的 ``ContextVar`` 模式一致）。

核心 API：
- ``set_locale_context(ctx)`` / ``get_locale_context()``：设置/获取 ``LocaleContext``
  - ``set_locale_context`` 返回 token，可用 ``reset_locale_context(token)`` 精确复位
- ``set_locale(locale)`` / ``get_locale()``：便捷方法，等价于包装/解包 ``SimpleLocaleContext``
- ``reset_locale_context(token=None)``：清除当前上下文（对齐 Spring ``resetLocaleContext``）
- ``set_default_locale(locale)``：设置全局默认 locale（对齐 Spring 同名静态方法）

嵌套调用：``ContextVar.reset(token)`` 天然支持嵌套——内层请求退出后自动恢复外层 locale，
与 ``spring.datasource.DataSourceContextHolder`` 完全一致。
"""
from __future__ import annotations

import contextvars
import threading
from typing import Optional

from .locale import Locale
from .locale_resolver import LocaleContext, SimpleLocaleContext


# ContextVar：协程安全 + 线程安全（Python 3.10+ 推荐）
_locale_context_var: "contextvars.ContextVar[Optional[LocaleContext]]" = contextvars.ContextVar(
    "spring_locale_context", default=None
)

# 全局默认 locale（进程级，所有线程/协程共享）
_default_locale_lock = threading.Lock()
_default_locale: Optional[Locale] = None


class LocaleContextHolder:
    """区域上下文持有器（对齐 Spring ``LocaleContextHolder``）。

    所有方法均为 ``@staticmethod``，状态保存在 ``ContextVar`` 与全局默认变量中。
    """

    @staticmethod
    def set_locale_context(context: Optional[LocaleContext]):
        """设置当前上下文的 ``LocaleContext``；``None`` 等价于清除。

        返回 ``ContextVar.set`` 的 token，可用 ``reset_locale_context(token)`` 精确复位。
        """
        return _locale_context_var.set(context)

    @staticmethod
    def get_locale_context() -> LocaleContext:
        """获取当前 ``LocaleContext``；不存在时返回 ``SimpleLocaleContext(default_locale)``。"""
        ctx = _locale_context_var.get()
        if ctx is not None:
            return ctx
        return SimpleLocaleContext(LocaleContextHolder.get_default_locale())

    @staticmethod
    def set_locale(locale: Optional[Locale]):
        """便捷方法：用 ``SimpleLocaleContext`` 包装 locale 设置到上下文。返回 token。"""
        return LocaleContextHolder.set_locale_context(
            SimpleLocaleContext(locale) if locale is not None else None
        )

    @staticmethod
    def get_locale() -> Locale:
        """获取当前 locale；上下文未设置时返回全局默认 locale（可能为空 ``Locale``）。"""
        return LocaleContextHolder.get_locale_context().get_locale()

    @staticmethod
    def reset_locale_context(token=None) -> None:
        """清除当前上下文（对齐 Spring ``resetLocaleContext``）。

        - 传入 ``token``：精确复位到 ``set_locale_context`` 之前的值（支持嵌套）。
        - 不传 ``token``：直接置为 None（慎用，会丢失嵌套层级）。
        """
        if token is not None:
            try:
                _locale_context_var.reset(token)
                return
            except (ValueError, LookupError):
                # token 不属于当前上下文（跨协程误用），兜底置 None
                pass
        _locale_context_var.set(None)

    # 兼容简短别名
    @staticmethod
    def reset(token=None) -> None:
        LocaleContextHolder.reset_locale_context(token)

    @staticmethod
    def set_default_locale(locale: Optional[Locale]) -> None:
        """设置进程级默认 locale；未设置上下文时 ``get_locale`` 返回此值。"""
        global _default_locale
        with _default_locale_lock:
            _default_locale = locale

    @staticmethod
    def get_default_locale() -> Locale:
        """获取进程级默认 locale；未设置返回空 ``Locale``。"""
        with _default_locale_lock:
            loc = _default_locale
        return loc if loc is not None else Locale()


__all__ = ["LocaleContextHolder"]
