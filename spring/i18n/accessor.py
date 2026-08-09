"""``MessageSourceAccessor`` 便捷访问器（对齐 Spring ``MessageSourceAccessor``）。

包装一个 ``MessageSource`` + 默认 ``Locale``，提供更简洁的 API：

- ``getMessage(code, args, locale)``           — 抛异常变体
- ``getMessage(code, args, default, locale)``  — 默认消息变体
- ``getMessage(resolvable, locale)``           — resolvable 变体

所有 ``locale`` 参数可选，缺省用构造时传入的默认 locale（对齐 Spring 同名行为）。
"""
from __future__ import annotations

from typing import Optional

from .locale import Locale
from .message_source import (
    MessageArgs,
    MessageSource,
    MessageSourceResolvable,
    NoSuchMessageException,
)


class MessageSourceAccessor:
    """``MessageSource`` 便捷访问器。

    Args:
        message_source: 被包装的消息源。
        default_locale: 默认 locale（请求未指定时使用）。
    """

    def __init__(self, message_source: MessageSource, default_locale: Optional[Locale] = None):
        self._source = message_source
        self._default_locale = default_locale if default_locale is not None else Locale("")

    @property
    def message_source(self) -> MessageSource:
        return self._source

    @property
    def default_locale(self) -> Locale:
        return self._default_locale

    def set_default_locale(self, locale: Locale) -> None:
        self._default_locale = locale

    # ==================== 便捷方法 ====================

    def getMessage(  # noqa: N802 - 保留 Java 驼峰命名以对齐 Spring API
        self,
        code: str,
        args: MessageArgs = None,
        locale: Optional[Locale] = None,
    ) -> str:
        """按 code 解析消息，找不到抛 ``NoSuchMessageException``。"""
        return self._source.getMessage(code, args, self._locale(locale))

    def getMessageOrDefault(
        self,
        code: str,
        args: MessageArgs = None,
        default_message: Optional[str] = None,
        locale: Optional[Locale] = None,
    ) -> Optional[str]:
        """按 code 解析消息，找不到返回 ``default_message``。"""
        return self._source.getMessageOrDefault(code, args, default_message, self._locale(locale))

    def getMessageFromResolvable(
        self,
        resolvable: MessageSourceResolvable,
        locale: Optional[Locale] = None,
    ) -> str:
        return self._source.getMessageFromResolvable(resolvable, self._locale(locale))

    # 别名（Python 风格）
    def get_message(self, code: str, args: MessageArgs = None, locale: Optional[Locale] = None) -> str:
        return self.getMessage(code, args, locale)

    def get_message_or_default(
        self,
        code: str,
        args: MessageArgs = None,
        default_message: Optional[str] = None,
        locale: Optional[Locale] = None,
    ) -> Optional[str]:
        return self.getMessageOrDefault(code, args, default_message, locale)

    # ==================== 内部 ====================

    def _locale(self, locale: Optional[Locale]) -> Locale:
        return locale if locale is not None else self._default_locale


__all__ = ["MessageSourceAccessor"]
