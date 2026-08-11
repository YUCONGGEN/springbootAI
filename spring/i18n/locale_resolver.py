"""``LocaleResolver`` 区域解析器（对齐 Spring ``org.springframework.web.servlet.i18n``）。

核心抽象：
- ``LocaleResolver``：策略接口，从 HTTP 请求解析 ``LocaleContext`` / 写回响应。
- ``LocaleContext``：携带当前 locale（可选时区）的上下文对象。
- ``AcceptHeaderLocaleResolver``：从请求 ``Accept-Language`` 头解析（默认推荐）。
- ``FixedLocaleResolver``：永远返回固定 locale（对齐 Spring 同名类）。
- ``SessionLocaleResolver``：从会话读写 locale（Starlette SessionMiddleware 风格）。
- ``CookieLocaleResolver``：从 Cookie 读写 locale。

设计要点：
- 复用 Starlette ``Request``/``Response`` 抽象，不直接依赖 FastAPI。
- ``AcceptHeaderLocaleResolver`` 实现 RFC 7231 简化版：解析 q 值排序 + locale 前缀回退。
- ``SessionLocaleResolver`` 需要应用先注册 ``SessionMiddleware``（Starlette 标准做法）。
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from .locale import Locale


# ==================== LocaleContext ====================

class LocaleContext:
    """区域上下文（对齐 Spring ``LocaleContext``）。"""

    def get_locale(self) -> Locale:
        raise NotImplementedError

    def is_fallback(self) -> bool:
        """是否为回退 locale（部分实现标记）。默认 False。"""
        return False


class SimpleLocaleContext(LocaleContext):
    """简单 ``LocaleContext`` 实现（对齐 Spring ``SimpleLocaleContext``）。"""

    def __init__(self, locale: Optional[Locale]):
        self._locale = locale if locale is not None else Locale()

    def get_locale(self) -> Locale:
        return self._locale

    def __repr__(self) -> str:
        return f"SimpleLocaleContext({self._locale!r})"


class SimpleTimeZoneAwareLocaleContext(LocaleContext):
    """带时区的 ``LocaleContext``（对齐 Spring ``SimpleTimeZoneAwareLocaleContext``）。

    本实现保留 ``time_zone`` 字段但不参与解析逻辑（仅元数据语义）。
    """

    def __init__(self, locale: Optional[Locale], time_zone: Optional[str] = None):
        self._locale = locale if locale is not None else Locale()
        self._time_zone = time_zone

    def get_locale(self) -> Locale:
        return self._locale

    def get_time_zone(self) -> Optional[str]:
        return self._time_zone

    def __repr__(self) -> str:
        return f"SimpleTimeZoneAwareLocaleContext({self._locale!r}, tz={self._time_zone!r})"


# ==================== LocaleResolver 接口 ====================

class LocaleResolver:
    """区域解析器策略接口（对齐 Spring ``LocaleResolver``）。

    子类需实现 ``resolve_locale(request)`` 返回 ``LocaleContext``。
    ``set_locale_context(request, response, context)`` 用于写回（部分实现支持）。
    """

    def resolve_locale(self, request) -> LocaleContext:  # noqa: D401 - 接口方法
        raise NotImplementedError

    def set_locale_context(self, request, response, context: LocaleContext) -> None:
        """写回 locale 到响应（``FixedLocaleResolver`` 不支持，抛 ``UnsupportedOperation``）。"""
        raise NotImplementedError(f"{type(self).__name__} does not support set_locale_context")


# ==================== AcceptHeaderLocaleResolver ====================

# Accept-Language 头解析：zh-CN,zh;q=0.9,en;q=0.8
_ACCEPT_LANG_RE = re.compile(
    r"\s*([a-zA-Z]{1,8}(?:-[a-zA-Z0-9]{1,8})*)\s*(?:;\s*q\s*=\s*([0-9.]+))?\s*,?",
    re.IGNORECASE,
)


def parse_accept_language(header: str) -> List[Tuple[Locale, float]]:
    """解析 ``Accept-Language`` 头，返回 ``[(Locale, q), ...]`` 按 q 降序。

    q 默认 1.0；q=0 表示不可接受（仍保留在列表中，调用方可过滤）。
    """
    if not header:
        return []
    result: List[Tuple[Locale, float]] = []
    for match in _ACCEPT_LANG_RE.finditer(header):
        tag = match.group(1)
        q_str = match.group(2)
        try:
            q = float(q_str) if q_str else 1.0
        except ValueError:
            q = 1.0
        result.append((Locale.parse(tag), q))
    # q 降序，稳定排序（保留声明顺序）
    result.sort(key=lambda x: -x[1])
    return result


class AcceptHeaderLocaleResolver(LocaleResolver):
    """从 ``Accept-Language`` 头解析 locale（对齐 Spring ``AcceptHeaderLocaleResolver``）。

    Args:
        supported_locales: 支持的 locale 列表；为空时返回请求 locale 原样。
        default_locale:    无匹配时返回的默认 locale；``None`` 时返回 ``Locale("")``。

    匹配算法（简化 RFC 4647 过滤）：
        1. 按 q 降序遍历 Accept-Language；
        2. 精确匹配 supported（language + country）；
        3. language 前缀匹配 supported；
        4. 全部不匹配返回 ``default_locale``。
    """

    def __init__(
        self,
        supported_locales: Optional[Sequence[Locale]] = None,
        default_locale: Optional[Locale] = None,
    ):
        self._supported: List[Locale] = list(supported_locales) if supported_locales else []
        self._default: Locale = default_locale if default_locale is not None else Locale("")

    @property
    def supported_locales(self) -> List[Locale]:
        return list(self._supported)

    def set_supported_locales(self, locales: Sequence[Locale]) -> None:
        self._supported = list(locales)

    def set_default_locale(self, locale: Locale) -> None:
        self._default = locale

    def resolve_locale(self, request) -> LocaleContext:
        header = _get_header(request, "accept-language", "")
        candidates = parse_accept_language(header)
        if not candidates:
            return SimpleLocaleContext(self._default)
        if not self._supported:
            # 无 supported 列表：直接返回最高 q 的 locale
            best = candidates[0][0]
            return SimpleLocaleContext(best if best.is_empty is False else self._default)

        for cand, q in candidates:
            if q <= 0:
                continue
            # 精确匹配
            for sup in self._supported:
                if cand == sup:
                    return SimpleLocaleContext(sup)
            # language 前缀匹配
            for sup in self._supported:
                if cand.language and cand.language == sup.language:
                    return SimpleLocaleContext(sup)
        return SimpleLocaleContext(self._default)

    def set_locale_context(self, request, response, context: LocaleContext) -> None:
        # Accept-Header 解析器不支持写回（对齐 Spring 同名行为）
        raise NotImplementedError(
            "AcceptHeaderLocaleResolver 不支持 set_locale_context；"
            "如需写回请使用 SessionLocaleResolver 或 CookieLocaleResolver"
        )


# ==================== FixedLocaleResolver ====================

class FixedLocaleResolver(LocaleResolver):
    """固定 locale 解析器（对齐 Spring ``FixedLocaleResolver``）。

    所有请求返回同一 ``LocaleContext``，``set_locale_context`` 抛 ``UnsupportedOperation``。
    """

    def __init__(
        self,
        locale: Optional[Locale] = None,
        time_zone: Optional[str] = None,
    ):
        self._locale = locale if locale is not None else Locale("")
        self._time_zone = time_zone

    def resolve_locale(self, request) -> LocaleContext:
        return SimpleTimeZoneAwareLocaleContext(self._locale, self._time_zone)

    def set_locale_context(self, request, response, context: LocaleContext) -> None:
        raise NotImplementedError(
            "FixedLocaleResolver 不支持 set_locale_context（locale 固定不可变）"
        )


# ==================== SessionLocaleResolver ====================

class SessionLocaleResolver(LocaleResolver):
    """会话级 locale 解析器（对齐 Spring ``SessionLocaleResolver``）。

    依赖 Starlette ``SessionMiddleware``；通过 ``request.session`` 读写 locale 字符串。
    """

    def __init__(
        self,
        session_attribute_name: str = "spring_locale",
        default_locale: Optional[Locale] = None,
    ):
        self._session_attr = session_attribute_name
        self._default = default_locale if default_locale is not None else Locale("")

    def resolve_locale(self, request) -> LocaleContext:
        session = _get_session(request)
        loc_str = session.get(self._session_attr) if session else None
        if loc_str:
            return SimpleLocaleContext(Locale.parse(loc_str))
        return SimpleLocaleContext(self._default)

    def set_locale_context(self, request, response, context: LocaleContext) -> None:
        session = _get_session(request)
        if session is None:
            raise RuntimeError(
                "SessionLocaleResolver 需要 SessionMiddleware；请先注册 starlette SessionMiddleware"
            )
        session[self._session_attr] = context.get_locale().to_string()


# ==================== CookieLocaleResolver ====================

class CookieLocaleResolver(LocaleResolver):
    """Cookie 级 locale 解析器（对齐 Spring ``CookieLocaleResolver``）。

    Args:
        cookie_name:     Cookie 名称，默认 ``spring_locale``。
        cookie_max_age:  Cookie Max-Age（秒），默认 1 年。
        cookie_path:     Cookie Path，默认 ``/``。
        cookie_domain:   Cookie Domain，默认 None。
        cookie_secure:   是否 Secure，默认 False。
        cookie_httponly: 是否 HttpOnly，默认 True。
        default_locale:  Cookie 不存在时的默认 locale。
    """

    def __init__(
        self,
        cookie_name: str = "spring_locale",
        cookie_max_age: int = 365 * 24 * 3600,
        cookie_path: str = "/",
        cookie_domain: Optional[str] = None,
        cookie_secure: bool = False,
        cookie_httponly: bool = True,
        default_locale: Optional[Locale] = None,
    ):
        self._cookie_name = cookie_name
        self._max_age = cookie_max_age
        self._path = cookie_path
        self._domain = cookie_domain
        self._secure = cookie_secure
        self._httponly = cookie_httponly
        self._default = default_locale if default_locale is not None else Locale("")

    def resolve_locale(self, request) -> LocaleContext:
        cookies = _get_cookies(request)
        loc_str = cookies.get(self._cookie_name) if cookies else None
        if loc_str:
            return SimpleLocaleContext(Locale.parse(loc_str))
        return SimpleLocaleContext(self._default)

    def set_locale_context(self, request, response, context: LocaleContext) -> None:
        _set_cookie(
            response,
            name=self._cookie_name,
            value=context.get_locale().to_language_tag(),
            max_age=self._max_age,
            path=self._path,
            domain=self._domain,
            secure=self._secure,
            httponly=self._httponly,
        )


# ==================== Starlette Request/Response 兼容工具 ====================

def _get_header(request, name: str, default: str) -> str:
    """从请求对象取头；兼容 Starlette ``Request`` 与 dict-like。"""
    if request is None:
        return default
    headers = getattr(request, "headers", None)
    if headers is None:
        return default
    try:
        # Starlette Headers 对象支持 .get 大小写不敏感
        return headers.get(name, default)
    except AttributeError:
        try:
            return dict(headers).get(name, default)
        except Exception:
            return default


def _get_session(request):
    """获取 Starlette ``request.session``；不存在返回 None。"""
    if request is None:
        return None
    return getattr(request, "session", None)


def _get_cookies(request):
    """获取 Starlette ``request.cookies``；不存在返回 None。"""
    if request is None:
        return None
    cookies = getattr(request, "cookies", None)
    if cookies is None:
        return None
    try:
        return dict(cookies)
    except Exception:
        return cookies


def _set_cookie(response, name: str, value: str, max_age: int, path: str,
                domain: Optional[str], secure: bool, httponly: bool) -> None:
    """写回 Cookie；兼容 Starlette ``Response`` 与自定义响应对象。"""
    if response is None:
        return
    set_cookie = getattr(response, "set_cookie", None)
    if callable(set_cookie):
        set_cookie(
            key=name, value=value, max_age=max_age, path=path,
            domain=domain, secure=secure, httponly=httponly,
        )
        return
    # 兜底：手动拼 Set-Cookie 头
    parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}"]
    if domain:
        parts.append(f"Domain={domain}")
    if secure:
        parts.append("Secure")
    if httponly:
        parts.append("HttpOnly")
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            headers.append("set-cookie", "; ".join(parts))
        except AttributeError:
            pass


__all__ = [
    "LocaleContext",
    "SimpleLocaleContext",
    "SimpleTimeZoneAwareLocaleContext",
    "LocaleResolver",
    "AcceptHeaderLocaleResolver",
    "FixedLocaleResolver",
    "SessionLocaleResolver",
    "CookieLocaleResolver",
    "parse_accept_language",
]
