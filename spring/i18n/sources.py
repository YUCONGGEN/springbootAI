"""具体 ``MessageSource`` 实现：``StaticMessageSource`` / ``ResourceBundleMessageSource`` /
``DelegatingMessageSource``（对齐 Spring 同名类）。

- ``StaticMessageSource``：编程式注册消息，用于测试或动态消息。
- ``ResourceBundleMessageSource``：从 ``basenames`` 加载资源文件（``messages`` →
  ``messages.properties`` / ``messages_en.properties`` / ``messages_zh_CN.properties``），
  支持 ``.properties``（Java 风格）与 ``.yml``/``.yaml``（复用项目 ``pyyaml`` 依赖）。
- ``DelegatingMessageSource``：未配置父级时的占位实现，所有调用委派父级或返回默认消息。
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

from .locale import Locale
from .message_source import (
    AbstractMessageSource,
    MessageArgs,
    MessageSource,
    NoSuchMessageException,
    _format_message,
)
from .properties import load_properties, parse_properties


# ==================== StaticMessageSource ====================

class StaticMessageSource(AbstractMessageSource):
    """编程式消息源（对齐 Spring ``StaticMessageSource``）。

    内部存储 ``{(code, locale_str): template}``，``locale_str`` 为空表示默认（无 locale）。
    解析时按 ``locale`` → ``locale_country`` → ``language`` → 默认 顺序回退。
    """

    def __init__(self, parent: Optional[MessageSource] = None):
        super().__init__(parent=parent)
        # key: (code, locale_string) -> template
        self._messages: Dict[Tuple[str, str], str] = {}

    def add_message(self, code: str, locale: Locale, template: str) -> None:
        """注册单条消息。"""
        self._messages[(code, locale.to_string())] = template

    def add_messages(self, messages: Dict[str, str], locale: Locale) -> None:
        """批量注册消息。"""
        loc_str = locale.to_string()
        for code, template in messages.items():
            self._messages[(code, loc_str)] = template

    def resolve_code(self, code: str, locale: Locale) -> Optional[str]:
        loc_str = locale.to_string()
        # 1. 精确匹配
        if (code, loc_str) in self._messages:
            return self._messages[(code, loc_str)]
        # 2. language_COUNTRY → language 回退
        if locale.country:
            lang_key = (code, locale.language)
            if lang_key in self._messages:
                return self._messages[lang_key]
        # 3. 默认（无 locale）
        default_key = (code, "")
        if default_key in self._messages:
            return self._messages[default_key]
        return None


# ==================== ResourceBundleMessageSource ====================


def _load_yaml(path: str, encoding: str) -> Dict[str, str]:
    """加载 YAML 资源文件；顶层必须是扁平 ``{key: value}`` 映射。"""
    import yaml  # 项目核心依赖（pyyaml）
    with open(path, "r", encoding=encoding, newline="") as f:
        data = yaml.safe_load(f.read()) or {}
    if not isinstance(data, dict):
        return {}
    # 值统一转字符串（消息模板必须是字符串）
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


# 支持的文件扩展名及加载器
_EXT_LOADERS = (
    (".properties", lambda path, enc: load_properties(path, enc)),
    (".yml", _load_yaml),
    (".yaml", _load_yaml),
)


class ResourceBundleMessageSource(AbstractMessageSource):
    """资源包消息源（对齐 Spring ``ResourceBundleMessageSource``）。

    Args:
        basenames:        资源基名列表，如 ``["messages", "errors"]``。
                          解析时按 basename + locale 后缀搜索文件。
        base_dir:         资源根目录，默认 ``"."``。搜索文件时拼接 ``base_dir/basename_locale.ext``。
        default_encoding: 文件编码，默认 UTF-8（对齐 Spring ``defaultEncoding``）。
        fallback_to_system_locale: 当请求 locale 找不到时，是否回退到系统 locale。
                          默认 True（对齐 Spring 同名开关）。
        default_locale:   默认 locale（``None`` 时用 ``Locale("")``）。

    文件命名约定（与 Java ``ResourceBundle`` 一致）：
        ``messages.properties``          — 默认
        ``messages_en.properties``       — 英语
        ``messages_en_US.properties``    — 英语(美国)
        ``messages_zh_CN.properties``    — 中文(中国)

    YML 等价：
        ``messages.yml`` / ``messages_en.yml`` / ``messages_zh_CN.yml``

    解析顺序：``locale`` → ``locale_country`` → ``language`` → 默认。
    多 ``basename`` 时，前者优先（后者作为补充，不覆盖前者已命中的 code）。
    """

    def __init__(
        self,
        basenames: Optional[Iterable[str]] = None,
        base_dir: str = ".",
        default_encoding: str = "utf-8",
        fallback_to_system_locale: bool = True,
        default_locale: Optional[Locale] = None,
        parent: Optional[MessageSource] = None,
    ):
        super().__init__(parent=parent)
        self._basenames: List[str] = list(basenames) if basenames else ["messages"]
        self._base_dir = base_dir
        self._default_encoding = default_encoding
        self._fallback_to_system_locale = fallback_to_system_locale
        self._default_locale = default_locale or Locale("")
        # 缓存：{(basename, locale_str): {code: template}}
        self._cached_bundles: Dict[Tuple[str, str], Dict[str, str]] = {}

    # ---- 配置 ----

    def add_basename(self, basename: str) -> None:
        self._basenames.append(basename)
        self._cached_bundles.clear()

    def set_default_encoding(self, encoding: str) -> None:
        self._default_encoding = encoding
        self._cached_bundles.clear()

    def set_base_dir(self, base_dir: str) -> None:
        self._base_dir = base_dir
        self._cached_bundles.clear()

    def set_default_locale(self, locale: Locale) -> None:
        self._default_locale = locale
        self._cached_bundles.clear()

    # ---- 解析 ----

    def resolve_code(self, code: str, locale: Locale) -> Optional[str]:
        # 优先精确 locale，再 country 回退到 language，再默认
        for loc in self._locale_fallback_chain(locale):
            for basename in self._basenames:
                bundle = self._get_bundle(basename, loc)
                if bundle and code in bundle:
                    return bundle[code]
        return None

    def resolve_code_without_args(self, code: str, locale: Locale) -> Optional[str]:
        # 复用同一解析路径（无参数优化空间不大，保持一致性）
        return self.resolve_code(code, locale)

    # ---- 内部 ----

    def _locale_fallback_chain(self, locale: Locale) -> List[Locale]:
        """构造 locale 回退链：locale → locale(country 去掉) → language → 默认。"""
        chain: List[Locale] = []
        if not locale.is_empty:
            chain.append(locale)
            if locale.country:
                chain.append(Locale(locale.language))
            elif locale.variant:
                chain.append(Locale(locale.language))
        if self._fallback_to_system_locale and not self._default_locale.is_empty:
            if self._default_locale not in chain:
                chain.append(self._default_locale)
        # 默认（空 locale）
        if Locale("") not in chain:
            chain.append(Locale(""))
        return chain

    def _get_bundle(self, basename: str, locale: Locale) -> Dict[str, str]:
        """获取指定 basename + locale 的消息字典（带缓存）。"""
        cache_key = (basename, locale.to_string())
        if cache_key in self._cached_bundles:
            return self._cached_bundles[cache_key]
        bundle = self._load_bundle(basename, locale)
        self._cached_bundles[cache_key] = bundle
        return bundle

    def _load_bundle(self, basename: str, locale: Locale) -> Dict[str, str]:
        """在 ``base_dir`` 下查找 basename + locale 后缀的资源文件。"""
        # locale 后缀：locale.to_string() 为空则无后缀
        loc_str = locale.to_string()
        suffix = f"_{loc_str}" if loc_str else ""
        # 依次尝试 .properties / .yml / .yaml
        for ext, loader in _EXT_LOADERS:
            path = os.path.join(self._base_dir, f"{basename}{suffix}{ext}")
            if os.path.isfile(path):
                try:
                    return loader(path, self._default_encoding)
                except Exception:
                    # 加载失败：跳过，回退到下一个扩展名
                    continue
        return {}


# ==================== DelegatingMessageSource ====================

class DelegatingMessageSource(MessageSource):
    """委派消息源（对齐 Spring ``DelegatingMessageSource``）。

    ApplicationContext 初始化前用作占位 ``MessageSource``：所有调用委派给父级；
    父级为 None 时返回 ``default_message`` 或抛 ``NoSuchMessageException``。
    """

    def __init__(self, parent: Optional[MessageSource] = None):
        self._parent: Optional[MessageSource] = parent

    @property
    def parent_message_source(self) -> Optional[MessageSource]:
        return self._parent

    @parent_message_source.setter
    def parent_message_source(self, value: Optional[MessageSource]) -> None:
        self._parent = value

    def getMessage(self, code, args=None, locale=None):  # noqa: N802
        if self._parent is not None:
            return self._parent.getMessage(code, args, locale)
        raise NoSuchMessageException(code, locale)

    def getMessageOrDefault(self, code, args=None, default_message=None, locale=None):
        if self._parent is not None:
            return self._parent.getMessageOrDefault(code, args, default_message, locale)
        return default_message

    def getMessageFromResolvable(self, resolvable, locale=None):
        if self._parent is not None:
            return self._parent.getMessageFromResolvable(resolvable, locale)
        default = resolvable.get_default_message()
        if default is not None:
            return _format_message(default, resolvable.get_arguments(), locale)
        raise NoSuchMessageException(
            resolvable.get_codes()[0] if resolvable.get_codes() else "", locale
        )


__all__ = [
    "StaticMessageSource",
    "ResourceBundleMessageSource",
    "DelegatingMessageSource",
]
