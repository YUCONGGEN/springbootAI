"""``MessageSource`` 接口与抽象基类（对齐 Spring ``org.springframework.context.MessageSource``）。

核心抽象：
- ``MessageSource``：策略接口，按 ``code`` + ``Locale`` 解析消息。
- ``AbstractMessageSource``：实现公共逻辑——参数格式化、默认消息回退、父级委派、
  ``MessageSourceResolvable`` 多 code 解析。子类只需实现 ``resolve_code``。
- ``NoSuchMessageException``：找不到消息时抛出（对齐 Spring 同名异常）。
- ``MessageSourceResolvable`` / ``DefaultMessageSourceResolvable``：多 code + 参数 + 默认消息
  的可解析对象，用于 ``ObjectError``/``FieldError`` 等校验场景。

消息格式（对齐 ``java.text.MessageFormat`` 的常见用法）：
- 位置占位符 ``{0}``/``{1}``：用 ``args`` 列表按序替换。
- 类型子模式 ``{0,number,#.##}``：忽略类型符，等价于 ``{0}``（Python 无等价格式化）。
- 关键字占位符 ``{name}``：当 ``args`` 为字典时使用。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence, Union

from .locale import Locale


class NoSuchMessageException(Exception):
    """找不到消息时抛出（对齐 Spring ``NoSuchMessageException``）。"""

    def __init__(self, code: str, locale: Optional[Locale] = None):
        self.code = code
        self.locale = locale
        loc_str = locale.to_string() if locale else "default"
        super().__init__(f"No message found under code '{code}' for locale '{loc_str}'.")


# ==================== 消息参数类型 ====================
# args 可以是：列表/元组（位置参数 {0}{1}），或字典（关键字参数 {name}）
MessageArgs = Optional[Union[Sequence[Any], dict]]


# ==================== MessageFormat 兼容格式化 ====================

# 匹配 {0}、{1,number}、{0,date,yyyy-MM-dd} 等 Java MessageFormat 占位符
_JAVA_MSGFMT = re.compile(r"\{(\d+)(?:,[a-zA-Z]+(?:,[^}]+)?)?\}")


def _format_message(template: str, args: MessageArgs, locale: Optional[Locale]) -> str:
    """按 Java ``MessageFormat`` 兼容方式格式化模板。

    - ``args`` 为列表/元组：用 ``{0}``/``{1}`` 位置替换；同时剥离 Java 类型子模式
      （``{0,number}`` → ``{0}``），使其兼容 ``str.format``。
    - ``args`` 为字典：用 ``{name}`` 关键字替换（不支持 Java 类型子模式）。
    - ``args`` 为 None：原样返回。
    - 格式化失败（参数不足/类型不匹配）原样返回模板，避免抛异常（对齐 Spring 容错）。
    """
    if args is None:
        return template
    try:
        if isinstance(args, dict):
            return template.format(**args)
        # 序列：先剥离 Java 类型子模式，再 str.format
        seq = list(args)
        stripped = _JAVA_MSGFMT.sub(r"{\1}", template)
        return stripped.format(*seq)
    except (IndexError, KeyError, ValueError, TypeError):
        return template


# ==================== MessageSourceResolvable ====================

class MessageSourceResolvable:
    """可解析消息对象（对齐 Spring ``MessageSourceResolvable``）。

    持有多个候选 ``codes``（按优先级降序）、可选 ``arguments``、可选默认消息。
    ``MessageSource.getMessage(resolvable, locale)`` 会按顺序尝试每个 code，第一个命中即返回。
    """

    def __init__(
        self,
        codes: Optional[Sequence[str]],
        arguments: MessageArgs = None,
        default_message: Optional[str] = None,
    ):
        self.codes: List[str] = list(codes) if codes else []
        self.arguments = arguments
        self.default_message = default_message

    def get_codes(self) -> List[str]:
        return self.codes

    def get_arguments(self) -> MessageArgs:
        return self.arguments

    def get_default_message(self) -> Optional[str]:
        return self.default_message


class DefaultMessageSourceResolvable(MessageSourceResolvable):
    """``MessageSourceResolvable`` 的默认实现（对齐 Spring 同名类）。"""

    def __init__(
        self,
        codes: Optional[Sequence[str]],
        arguments: MessageArgs = None,
        default_message: Optional[str] = None,
    ):
        super().__init__(codes, arguments, default_message)


# ==================== MessageSource 接口 ====================

class MessageSource:
    """消息源策略接口（对齐 Spring ``MessageSource``）。

    子类必须实现 ``resolve_code``；本类提供 ``getMessage`` 的公共入口与默认消息回退逻辑。
    """

    def getMessage(  # noqa: N802 - 保留 Java 驼峰命名以对齐 Spring API
        self,
        code: str,
        args: MessageArgs = None,
        locale: Optional[Locale] = None,
    ) -> str:
        """按 ``code`` + ``locale`` 解析消息，找不到抛 ``NoSuchMessageException``。"""
        msg = self._resolve_with_fallback(code, args, locale, default=None)
        if msg is None:
            raise NoSuchMessageException(code, locale)
        return msg

    def getMessageOrDefault(  # 便利方法，Python 风格命名
        self,
        code: str,
        args: MessageArgs = None,
        default_message: Optional[str] = None,
        locale: Optional[Locale] = None,
    ) -> Optional[str]:
        """按 ``code`` + ``locale`` 解析消息，找不到返回 ``default_message``（None 表示无默认）。"""
        return self._resolve_with_fallback(code, args, locale, default=default_message)

    def getMessageFromResolvable(  # 对齐 Spring ``getMessage(resolvable, locale)``
        self,
        resolvable: MessageSourceResolvable,
        locale: Optional[Locale] = None,
    ) -> str:
        """按 ``resolvable.codes`` 顺序解析；全部未命中时返回 ``default_message``，
        若默认消息为 None 则抛 ``NoSuchMessageException``。"""
        loc = locale or Locale("")
        for code in resolvable.get_codes():
            msg = self._resolve_with_fallback(code, resolvable.get_arguments(), loc, default=None)
            if msg is not None:
                return msg
        default = resolvable.get_default_message()
        if default is not None:
            return _format_message(default, resolvable.get_arguments(), loc)
        raise NoSuchMessageException(resolvable.get_codes()[0] if resolvable.get_codes() else "",
                                     loc)

    # ==================== 子类实现点 ====================

    def resolve_code(self, code: str, locale: Locale) -> Optional[str]:
        """子类实现：返回原始（未格式化）消息模板，找不到返回 None。

        默认实现总是返回 None（等价于空消息源）。
        """
        return None

    # ==================== 内部 ====================

    def _resolve_with_fallback(
        self,
        code: str,
        args: MessageArgs,
        locale: Optional[Locale],
        default: Optional[str],
    ) -> Optional[str]:
        loc = locale or Locale("")
        msg = self.resolve_code(code, loc)
        if msg is None:
            return default
        return _format_message(msg, args, loc)


# ==================== AbstractMessageSource ====================

class AbstractMessageSource(MessageSource):
    """``MessageSource`` 抽象基类（对齐 Spring ``AbstractMessageSource``）。

    扩展点：
    - ``resolve_code``：子类必须覆盖，返回原始消息模板。
    - ``resolve_code_without_args``：可选覆盖，返回无参数消息模板（默认走 ``resolve_code``）。

    特性：
    - ``parent_message_source``：父消息源；当前未命中时委派父级。
    - ``use_code_as_default_message``：找不到时把 ``code`` 作为默认消息（不抛异常）。
      对齐 Spring ``AbstractMessageSource.setUseCodeAsDefaultMessage``。
    """

    def __init__(self, parent: Optional[MessageSource] = None):
        self._parent: Optional[MessageSource] = parent
        self._use_code_as_default_message: bool = False

    @property
    def parent_message_source(self) -> Optional[MessageSource]:
        return self._parent

    @parent_message_source.setter
    def parent_message_source(self, value: Optional[MessageSource]) -> None:
        self._parent = value

    def set_use_code_as_default_message(self, flag: bool) -> None:
        self._use_code_as_default_message = flag

    def resolve_code_without_args(self, code: str, locale: Locale) -> Optional[str]:
        """无参数解析（子类可覆盖以优化性能）。默认走 ``resolve_code``。"""
        return self.resolve_code(code, locale)

    def resolve_code(self, code: str, locale: Locale) -> Optional[str]:  # 子类覆盖
        return None

    # ==================== 重写公共入口，加入父级委派 ====================

    def _resolve_with_fallback(
        self,
        code: str,
        args: MessageArgs,
        locale: Optional[Locale],
        default: Optional[str],
    ) -> Optional[str]:
        loc = locale or Locale("")
        # 1. 当前消息源
        if args is None:
            msg = self.resolve_code_without_args(code, loc)
        else:
            msg = self.resolve_code(code, loc)
        # 2. 父级委派
        if msg is None and self._parent is not None:
            return self._parent.getMessageOrDefault(code, args, default, loc)
        if msg is None:
            if self._use_code_as_default_message:
                return code
            return default
        return _format_message(msg, args, loc)


__all__ = [
    "NoSuchMessageException",
    "MessageArgs",
    "MessageSourceResolvable",
    "DefaultMessageSourceResolvable",
    "MessageSource",
    "AbstractMessageSource",
]
