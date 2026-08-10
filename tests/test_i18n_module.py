"""SpringBootAI i18n 国际化模块测试 —— 覆盖 Locale / MessageSource / LocaleResolver /
LocaleContextHolder / MessageSourceAccessor / properties 解析 / 中间件 / 自动配置。

对齐 tests/test_csv_module.py 的 pytest + 临时文件风格；不依赖第三方 i18n 库。
"""
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.i18n import (
    Locale, LOCALE_EN, LOCALE_CHINA, LOCALE_US, LOCALE_UK, parse_locale,
    MessageSource, AbstractMessageSource, NoSuchMessageException,
    MessageSourceResolvable, DefaultMessageSourceResolvable,
    StaticMessageSource, ResourceBundleMessageSource, DelegatingMessageSource,
    LocaleResolver, LocaleContext, SimpleLocaleContext, SimpleTimeZoneAwareLocaleContext,
    AcceptHeaderLocaleResolver, FixedLocaleResolver,
    SessionLocaleResolver, CookieLocaleResolver,
    LocaleContextHolder, MessageSourceAccessor,
    load_properties, parse_properties,
    LocaleResolverMiddleware, get_request_locale,
    MessageSourceAutoConfiguration, configure_message_source,
    parse_accept_language,
)


# ==================== Locale ====================

class TestLocale:
    def test_constructor_normalizes_case(self):
        loc = Locale("EN", "us", "Posix")
        assert loc.language == "en"
        assert loc.country == "US"
        assert loc.variant == "Posix"

    def test_parse_underscore_variants(self):
        assert Locale.parse("en") == Locale("en")
        assert Locale.parse("en_US") == Locale("en", "US")
        assert Locale.parse("en_US_POSIX") == Locale("en", "US", "POSIX")

    def test_parse_bcp47_dash_variants(self):
        assert Locale.parse("en-US") == Locale("en", "US")
        assert Locale.parse("zh-CN") == Locale("zh", "CN")
        # BCP 47 扩展私用子段：x-private 拼到 variant
        loc = Locale.parse("en-US-x-posix")
        assert loc.language == "en" and loc.country == "US"
        assert "posix" in loc.variant.lower()

    def test_parse_empty_returns_empty(self):
        loc = Locale.parse("")
        assert loc.is_empty

    def test_to_string_java_style(self):
        assert Locale("en").to_string() == "en"
        assert Locale("en", "US").to_string() == "en_US"
        assert Locale("en", "US", "POSIX").to_string() == "en_US_POSIX"

    def test_to_language_tag_bcp47(self):
        assert Locale("en").to_language_tag() == "en"
        assert Locale("en", "US").to_language_tag() == "en-US"
        assert Locale("zh", "CN").to_language_tag() == "zh-CN"

    def test_equality_and_hash(self):
        assert Locale("en", "US") == Locale("EN", "us")
        assert hash(Locale("en", "US")) == hash(Locale("EN", "us"))
        assert Locale("en") != Locale("en", "US")

    def test_matches_prefix(self):
        # 宽泛 locale matches 具体 locale
        assert Locale("en").matches(Locale("en", "US"))
        # 具体 locale 不 matches 宽泛 locale
        assert not Locale("en", "US").matches(Locale("en"))
        # 不同语言不 match
        assert not Locale("en").matches(Locale("zh"))

    def test_predefined_constants(self):
        assert LOCALE_EN == Locale("en")
        assert LOCALE_US == Locale("en", "US")
        assert LOCALE_CHINA == Locale("zh", "CN")
        assert LOCALE_UK == Locale("en", "GB")

    def test_str_repr(self):
        assert str(Locale("zh", "CN")) == "zh_CN"
        assert "zh_CN" in repr(Locale("zh", "CN"))


# ==================== properties 解析 ====================

class TestProperties:
    def test_basic_kv(self):
        result = parse_properties("greeting=Hello\nname=World")
        assert result == {"greeting": "Hello", "name": "World"}

    def test_separator_variants(self):
        # = : 与空白均作分隔符
        result = parse_properties("a=1\nb:2\nc 3")
        assert result == {"a": "1", "b": "2", "c": "3"}

    def test_comments_and_blanks(self):
        content = textwrap.dedent("""\
            # this is a comment
            ! also a comment

            key=value
        """)
        result = parse_properties(content)
        assert result == {"key": "value"}

    def test_line_continuation(self):
        content = "greeting=Hello, \\\n         World!"
        result = parse_properties(content)
        assert result["greeting"] == "Hello, World!"

    def test_escapes(self):
        content = r"line=first\nsecond\ttab"
        result = parse_properties(content)
        assert result["line"] == "first\nsecond\ttab"

    def test_escaped_separators_in_key(self):
        # 转义的 = 应保留在 key 中
        content = r"a\=b=value"
        result = parse_properties(content)
        assert "a=b" in result
        assert result["a=b"] == "value"

    def test_unicode_escape(self):
        content = "zh=\\u4f60\\u597d"
        result = parse_properties(content)
        assert result["zh"] == "你好"

    def test_load_from_file(self, tmp_path):
        f = tmp_path / "test.properties"
        f.write_text("greeting=Hi\nname=There", encoding="utf-8")
        result = load_properties(str(f))
        assert result == {"greeting": "Hi", "name": "There"}

    def test_utf8_chinese(self, tmp_path):
        f = tmp_path / "zh.properties"
        f.write_text("greeting=你好，世界\n", encoding="utf-8")
        result = load_properties(str(f), encoding="utf-8")
        assert result["greeting"] == "你好，世界"


# ==================== MessageSource（StaticMessageSource）====================

class TestStaticMessageSource:
    def test_add_and_get_message(self):
        src = StaticMessageSource()
        src.add_message("greeting", LOCALE_EN, "Hello, {0}!")
        assert src.getMessage("greeting", ["Tom"], LOCALE_EN) == "Hello, Tom!"

    def test_get_message_or_default_returns_default(self):
        src = StaticMessageSource()
        assert src.getMessageOrDefault("missing", None, "fallback", LOCALE_EN) == "fallback"

    def test_get_message_raises_when_missing(self):
        src = StaticMessageSource()
        with pytest.raises(NoSuchMessageException):
            src.getMessage("missing", None, LOCALE_EN)

    def test_locale_fallback_to_language(self):
        src = StaticMessageSource()
        src.add_message("greeting", Locale("en"), "Hi")
        # 请求 en_US 应回退到 en
        assert src.getMessage("greeting", None, Locale("en", "US")) == "Hi"

    def test_locale_fallback_to_default_when_no_language(self):
        src = StaticMessageSource()
        src.add_message("greeting", Locale(""), "Default Hi")
        # 请求 zh_CN 但只有默认消息
        assert src.getMessage("greeting", None, Locale("zh", "CN")) == "Default Hi"

    def test_exact_locale_overrides_language(self):
        src = StaticMessageSource()
        src.add_message("greeting", Locale("en"), "Hi")
        src.add_message("greeting", Locale("en", "US"), "Howdy")
        assert src.getMessage("greeting", None, Locale("en", "US")) == "Howdy"
        assert src.getMessage("greeting", None, Locale("en", "GB")) == "Hi"

    def test_dict_args_keyword_substitution(self):
        src = StaticMessageSource()
        src.add_message("welcome", LOCALE_EN, "Welcome, {name}!")
        assert src.getMessage("welcome", {"name": "Alice"}, LOCALE_EN) == "Welcome, Alice!"

    def test_java_messageformat_type_subpattern_stripped(self):
        src = StaticMessageSource()
        # Java MessageFormat 类型子模式 {0,number,#.##} 应被剥离为 {0}
        src.add_message("price", LOCALE_US, "Price: {0,number,#.##}")
        assert src.getMessage("price", [12.5], LOCALE_US) == "Price: 12.5"

    def test_format_failure_returns_template_verbatim(self):
        src = StaticMessageSource()
        # 参数不足：原样返回模板（对齐 Spring 容错）
        src.add_message("greeting", LOCALE_EN, "Hello, {0} and {1}!")
        assert src.getMessage("greeting", ["Tom"], LOCALE_EN) == "Hello, {0} and {1}!"

    def test_add_messages_batch(self):
        src = StaticMessageSource()
        src.add_messages({"a": "A", "b": "B"}, LOCALE_EN)
        assert src.getMessage("a", None, LOCALE_EN) == "A"
        assert src.getMessage("b", None, LOCALE_EN) == "B"

    def test_use_code_as_default_message(self):
        src = StaticMessageSource()
        src.set_use_code_as_default_message(True)
        # 找不到消息时返回 code 自身
        assert src.getMessageOrDefault("missing.code", None, None, LOCALE_EN) == "missing.code"


# ==================== MessageSource 父级委派 ====================

class TestParentDelegation:
    def test_parent_fallback(self):
        parent = StaticMessageSource()
        parent.add_message("parent.only", LOCALE_EN, "from parent")
        child = StaticMessageSource(parent=parent)
        # 子级未命中 -> 委派父级
        assert child.getMessage("parent.only", None, LOCALE_EN) == "from parent"

    def test_child_overrides_parent(self):
        parent = StaticMessageSource()
        parent.add_message("shared", LOCALE_EN, "parent value")
        child = StaticMessageSource(parent=parent)
        child.add_message("shared", LOCALE_EN, "child value")
        assert child.getMessage("shared", None, LOCALE_EN) == "child value"

    def test_delegating_message_source_with_parent(self):
        parent = StaticMessageSource()
        parent.add_message("hi", LOCALE_EN, "Hi")
        delegating = DelegatingMessageSource(parent=parent)
        assert delegating.getMessage("hi", None, LOCALE_EN) == "Hi"

    def test_delegating_message_source_no_parent_returns_default(self):
        delegating = DelegatingMessageSource()
        assert delegating.getMessageOrDefault("missing", None, "default", LOCALE_EN) == "default"

    def test_delegating_message_source_no_parent_raises(self):
        delegating = DelegatingMessageSource()
        with pytest.raises(NoSuchMessageException):
            delegating.getMessage("missing", None, LOCALE_EN)


# ==================== MessageSourceResolvable ====================

class TestMessageSourceResolvable:
    def test_resolvable_first_matching_code_wins(self):
        src = StaticMessageSource()
        src.add_message("code1", LOCALE_EN, "First")
        src.add_message("code2", LOCALE_EN, "Second")
        resolvable = DefaultMessageSourceResolvable(["code2", "code1"], None, None)
        assert src.getMessageFromResolvable(resolvable, LOCALE_EN) == "Second"

    def test_resolvable_default_message_when_no_match(self):
        src = StaticMessageSource()
        resolvable = DefaultMessageSourceResolvable(
            ["missing"], ["arg"], "default {0}"
        )
        assert src.getMessageFromResolvable(resolvable, LOCALE_EN) == "default arg"

    def test_resolvable_raises_when_no_match_no_default(self):
        src = StaticMessageSource()
        resolvable = DefaultMessageSourceResolvable(["missing"], None, None)
        with pytest.raises(NoSuchMessageException):
            src.getMessageFromResolvable(resolvable, LOCALE_EN)

    def test_resolvable_with_dict_args(self):
        src = StaticMessageSource()
        src.add_message("welcome", LOCALE_EN, "Welcome, {name}!")
        resolvable = DefaultMessageSourceResolvable(["welcome"], {"name": "Bob"})
        assert src.getMessageFromResolvable(resolvable, LOCALE_EN) == "Welcome, Bob!"


# ==================== ResourceBundleMessageSource ====================

class TestResourceBundleMessageSource:
    @pytest.fixture(autouse=True)
    def _restore_yaml(self):
        """YAML bundle 测试依赖真实 ``yaml.safe_load``（``_test_helpers`` 全局 mock 会覆盖）。"""
        _restore_real_modules()
        yield

    @pytest.fixture
    def i18n_dir(self, tmp_path):
        """构造临时 i18n 资源目录，含多 locale 文件。"""
        d = tmp_path / "i18n"
        d.mkdir()
        (d / "messages.properties").write_text(
            "greeting=Hello\nfarewell=Goodbye", encoding="utf-8"
        )
        (d / "messages_en.properties").write_text(
            "greeting=Hello\nfarewell=Goodbye", encoding="utf-8"
        )
        (d / "messages_en_US.properties").write_text(
            "greeting=Howdy", encoding="utf-8"
        )
        (d / "messages_zh_CN.properties").write_text(
            "greeting=你好\nfarewell=再见", encoding="utf-8"
        )
        return str(d)

    def test_default_bundle_when_no_locale(self, i18n_dir):
        src = ResourceBundleMessageSource(
            basenames=["messages"], base_dir=i18n_dir, default_locale=Locale("")
        )
        assert src.getMessage("greeting", None, Locale("")) == "Hello"

    def test_exact_locale_match(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        assert src.getMessage("greeting", None, Locale("zh", "CN")) == "你好"
        assert src.getMessage("greeting", None, Locale("en", "US")) == "Howdy"

    def test_fallback_to_language(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        # 请求 en_GB：无精确，回退到 en
        assert src.getMessage("greeting", None, Locale("en", "GB")) == "Hello"

    def test_fallback_to_default_bundle(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        # 请求 ja_JP：无对应资源，回退到默认 messages.properties
        assert src.getMessage("greeting", None, Locale("ja", "JP")) == "Hello"

    def test_yaml_bundle(self, tmp_path):
        d = tmp_path / "i18n"
        d.mkdir()
        (d / "messages.yml").write_text("greeting: Hello from YAML\n", encoding="utf-8")
        (d / "messages_zh_CN.yml").write_text("greeting: 来自 YAML 的你好\n", encoding="utf-8")
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=str(d))
        assert src.getMessage("greeting", None, Locale("")) == "Hello from YAML"
        assert src.getMessage("greeting", None, Locale("zh", "CN")) == "来自 YAML 的你好"

    def test_multiple_basenames(self, tmp_path):
        d = tmp_path / "i18n"
        d.mkdir()
        (d / "messages.properties").write_text("greeting=Hi", encoding="utf-8")
        (d / "errors.properties").write_text("not.found=Not Found", encoding="utf-8")
        src = ResourceBundleMessageSource(
            basenames=["messages", "errors"], base_dir=str(d)
        )
        assert src.getMessage("greeting", None, Locale("")) == "Hi"
        assert src.getMessage("not.found", None, Locale("")) == "Not Found"

    def test_args_formatting(self, i18n_dir):
        # 在临时目录追加带占位符的消息
        with open(os.path.join(i18n_dir, "messages_en.properties"), "a", encoding="utf-8") as f:
            f.write("\nwelcome=Welcome, {0}!\n")
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        # ResourceBundleMessageSource 缓存机制：之前已缓存可能不刷新，重新构造
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        assert src.getMessage("welcome", ["Alice"], Locale("en")) == "Welcome, Alice!"

    def test_bundle_cache_hit(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        # 多次调用应命中缓存（不重新读文件）
        src.getMessage("greeting", None, Locale("zh", "CN"))
        cached = src._cached_bundles.get(("messages", "zh_CN"))
        assert cached is not None
        assert cached["greeting"] == "你好"
        # 再次调用应复用缓存
        src.getMessage("greeting", None, Locale("zh", "CN"))
        assert ("messages", "zh_CN") in src._cached_bundles

    def test_missing_code_raises(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        with pytest.raises(NoSuchMessageException):
            src.getMessage("missing.code", None, Locale("en"))

    def test_use_code_as_default(self, i18n_dir):
        src = ResourceBundleMessageSource(basenames=["messages"], base_dir=i18n_dir)
        src.set_use_code_as_default_message(True)
        assert src.getMessageOrDefault("missing", None, None, Locale("en")) == "missing"


# ==================== AcceptHeaderLocaleResolver ====================

class TestAcceptHeaderLocaleResolver:
    def test_parse_accept_language_simple(self):
        result = parse_accept_language("en-US,en;q=0.9,zh-CN;q=0.8")
        assert len(result) == 3
        # q 降序
        assert result[0][0] == Locale("en", "US")
        assert result[0][1] == 1.0
        assert result[1][0] == Locale("en")
        assert result[1][1] == 0.9

    def test_parse_empty_header(self):
        assert parse_accept_language("") == []

    def test_exact_match(self):
        resolver = AcceptHeaderLocaleResolver(
            supported_locales=[Locale("en", "US"), Locale("zh", "CN")],
            default_locale=Locale("en"),
        )
        req = _FakeRequest(headers={"accept-language": "zh-CN,zh;q=0.9"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("zh", "CN")

    def test_language_prefix_match(self):
        resolver = AcceptHeaderLocaleResolver(
            supported_locales=[Locale("en", "US")], default_locale=Locale("en")
        )
        # en-GB 在 supported 中无精确，但语言前缀 en 匹配 en_US
        req = _FakeRequest(headers={"accept-language": "en-GB"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en", "US")

    def test_no_match_returns_default(self):
        resolver = AcceptHeaderLocaleResolver(
            supported_locales=[Locale("en", "US")], default_locale=Locale("en")
        )
        req = _FakeRequest(headers={"accept-language": "fr-FR"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en")

    def test_empty_header_returns_default(self):
        resolver = AcceptHeaderLocaleResolver(
            supported_locales=[Locale("en", "US")], default_locale=Locale("en")
        )
        req = _FakeRequest(headers={})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en")

    def test_no_supported_returns_best_effort(self):
        # supported_locales 为空：直接返回最高 q 的 locale
        resolver = AcceptHeaderLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(headers={"accept-language": "zh-CN,en;q=0.9"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("zh", "CN")

    def test_q0_rejected(self):
        resolver = AcceptHeaderLocaleResolver(
            supported_locales=[Locale("en", "US"), Locale("fr", "FR")],
            default_locale=Locale("en"),
        )
        # fr;q=0 应被跳过
        req = _FakeRequest(headers={"accept-language": "fr-FR;q=0,en-US;q=0.9"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en", "US")

    def test_set_locale_context_not_supported(self):
        resolver = AcceptHeaderLocaleResolver()
        with pytest.raises(NotImplementedError):
            resolver.set_locale_context(_FakeRequest(), _FakeResponse(), SimpleLocaleContext(Locale("en")))


# ==================== FixedLocaleResolver ====================

class TestFixedLocaleResolver:
    def test_always_returns_fixed_locale(self):
        resolver = FixedLocaleResolver(locale=Locale("zh", "CN"))
        for header in [None, "en-US", "fr-FR"]:
            req = _FakeRequest(headers={"accept-language": header} if header else {})
            ctx = resolver.resolve_locale(req)
            assert ctx.get_locale() == Locale("zh", "CN")

    def test_with_time_zone(self):
        resolver = FixedLocaleResolver(locale=Locale("en"), time_zone="UTC")
        ctx = resolver.resolve_locale(_FakeRequest())
        assert isinstance(ctx, SimpleTimeZoneAwareLocaleContext)
        assert ctx.get_time_zone() == "UTC"

    def test_set_locale_context_not_supported(self):
        resolver = FixedLocaleResolver(locale=Locale("en"))
        with pytest.raises(NotImplementedError):
            resolver.set_locale_context(_FakeRequest(), _FakeResponse(), SimpleLocaleContext(Locale("en")))


# ==================== CookieLocaleResolver ====================

class TestCookieLocaleResolver:
    def test_resolve_from_cookie(self):
        resolver = CookieLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(cookies={"spring_locale": "zh-CN"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("zh", "CN")

    def test_default_when_no_cookie(self):
        resolver = CookieLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(cookies={})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en")

    def test_set_locale_writes_cookie(self):
        resolver = CookieLocaleResolver(default_locale=Locale("en"))
        resp = _FakeResponse()
        resolver.set_locale_context(
            _FakeRequest(), resp, SimpleLocaleContext(Locale("zh", "CN"))
        )
        assert resp.cookies["spring_locale"]["value"] == "zh-CN"
        assert resp.cookies["spring_locale"]["path"] == "/"

    def test_custom_cookie_name(self):
        resolver = CookieLocaleResolver(cookie_name="lang", default_locale=Locale("en"))
        req = _FakeRequest(cookies={"lang": "fr-FR"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("fr", "FR")


# ==================== SessionLocaleResolver ====================

class TestSessionLocaleResolver:
    def test_resolve_from_session(self):
        resolver = SessionLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(session={"spring_locale": "zh_CN"})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("zh", "CN")

    def test_default_when_no_session_value(self):
        resolver = SessionLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(session={})
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en")

    def test_default_when_no_session_at_all(self):
        resolver = SessionLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(session=None)
        ctx = resolver.resolve_locale(req)
        assert ctx.get_locale() == Locale("en")

    def test_set_locale_writes_session(self):
        resolver = SessionLocaleResolver(default_locale=Locale("en"))
        session = {}
        req = _FakeRequest(session=session)
        resolver.set_locale_context(req, _FakeResponse(), SimpleLocaleContext(Locale("zh", "CN")))
        assert session["spring_locale"] == "zh_CN"

    def test_set_locale_without_session_raises(self):
        resolver = SessionLocaleResolver(default_locale=Locale("en"))
        req = _FakeRequest(session=None)
        with pytest.raises(RuntimeError):
            resolver.set_locale_context(req, _FakeResponse(), SimpleLocaleContext(Locale("zh")))


# ==================== LocaleContextHolder ====================

class TestLocaleContextHolder:
    def test_set_and_get(self):
        token = LocaleContextHolder.set_locale(Locale("zh", "CN"))
        try:
            assert LocaleContextHolder.get_locale() == Locale("zh", "CN")
        finally:
            LocaleContextHolder.reset_locale_context(token)

    def test_get_returns_default_when_unset(self):
        # 暂存并清除当前上下文
        token = LocaleContextHolder.set_locale_context(None)
        try:
            LocaleContextHolder.set_default_locale(Locale("en"))
            assert LocaleContextHolder.get_locale() == Locale("en")
        finally:
            LocaleContextHolder.reset_locale_context(token)

    def test_nested_context_token_reset(self):
        # 外层 en
        outer_token = LocaleContextHolder.set_locale(Locale("en"))
        try:
            # 内层 zh_CN
            inner_token = LocaleContextHolder.set_locale(Locale("zh", "CN"))
            assert LocaleContextHolder.get_locale() == Locale("zh", "CN")
            # 退出内层，恢复外层
            LocaleContextHolder.reset_locale_context(inner_token)
            assert LocaleContextHolder.get_locale() == Locale("en")
        finally:
            LocaleContextHolder.reset_locale_context(outer_token)

    def test_default_locale_setter(self):
        LocaleContextHolder.set_default_locale(Locale("fr", "FR"))
        assert LocaleContextHolder.get_default_locale() == Locale("fr", "FR")
        # 还原
        LocaleContextHolder.set_default_locale(None)
        assert LocaleContextHolder.get_default_locale() == Locale("")

    def test_reset_without_token(self):
        LocaleContextHolder.set_locale(Locale("zh", "CN"))
        LocaleContextHolder.reset_locale_context()  # 不传 token
        # 上下文已被清空（reset to None）
        LocaleContextHolder.set_default_locale(Locale("en"))
        assert LocaleContextHolder.get_locale() == Locale("en")


# ==================== MessageSourceAccessor ====================

class TestMessageSourceAccessor:
    def test_get_message_uses_default_locale(self):
        src = StaticMessageSource()
        src.add_message("hi", Locale("en"), "Hi")
        src.add_message("hi", Locale("zh", "CN"), "你好")
        accessor = MessageSourceAccessor(src, default_locale=Locale("zh", "CN"))
        # 不传 locale，使用 accessor 默认 zh_CN
        assert accessor.getMessage("hi") == "你好"

    def test_get_message_with_explicit_locale(self):
        src = StaticMessageSource()
        src.add_message("hi", Locale("en"), "Hi")
        accessor = MessageSourceAccessor(src, default_locale=Locale("zh", "CN"))
        assert accessor.getMessage("hi", locale=Locale("en")) == "Hi"

    def test_get_message_or_default(self):
        src = StaticMessageSource()
        accessor = MessageSourceAccessor(src, default_locale=Locale("en"))
        assert accessor.getMessageOrDefault("missing", default_message="fallback") == "fallback"

    def test_python_style_aliases(self):
        src = StaticMessageSource()
        src.add_message("hi", Locale("en"), "Hi")
        accessor = MessageSourceAccessor(src, default_locale=Locale("en"))
        assert accessor.get_message("hi") == "Hi"
        assert accessor.get_message_or_default("missing", default_message="fb") == "fb"


# ==================== 中间件 / 集成测试 ====================

def _restore_real_modules():
    """恢复真实 ``yaml`` 与 ``starlette`` 模块属性。

    ``tests/_test_helpers.py`` 在导入时会全局覆盖 ``yaml.safe_load`` 与
    ``starlette.responses.JSONResponse`` 等为 ``MagicMock``，破坏需要真实
    Starlette 路由的集成测试。本函数用 ``importlib.reload`` 恢复真实实现。
    """
    import importlib
    try:
        import yaml as _yaml
        importlib.reload(_yaml)
    except Exception:
        pass
    for mod_name in (
        "starlette.responses",
        "starlette.requests",
        "starlette.middleware.base",
        "starlette.testclient",
    ):
        try:
            mod = __import__(mod_name, fromlist=["*"])
            importlib.reload(mod)
        except Exception:
            pass


class TestMiddleware:
    @pytest.fixture(autouse=True)
    def _restore_starlette(self):
        _restore_real_modules()
        yield

    def test_middleware_sets_locale_context(self):
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        captured = {}

        async def endpoint(request):
            # 中间件应已把 locale 写入 LocaleContextHolder
            captured["locale"] = LocaleContextHolder.get_locale().to_string()
            captured["state_locale"] = get_request_locale(request).to_string()
            return JSONResponse({"ok": True})

        app = Starlette()
        app.add_middleware(
            LocaleResolverMiddleware,
            locale_resolver=AcceptHeaderLocaleResolver(
                supported_locales=[Locale("zh", "CN"), Locale("en", "US")],
                default_locale=Locale("en"),
            ),
        )
        app.router.add_route("/", endpoint, methods=["GET"])

        with TestClient(app) as client:
            resp = client.get("/", headers={"Accept-Language": "zh-CN"})
            assert resp.status_code == 200
            assert captured["locale"] == "zh_CN"
            assert captured["state_locale"] == "zh_CN"

    def test_middleware_resets_after_request(self):
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        async def endpoint(request):
            return JSONResponse({"ok": True})

        app = Starlette()
        app.add_middleware(LocaleResolverMiddleware)
        app.router.add_route("/", endpoint, methods=["GET"])

        with TestClient(app) as client:
            client.get("/", headers={"Accept-Language": "zh-CN"})
            # 请求结束后 ContextVar 应被复位
            LocaleContextHolder.set_default_locale(Locale("en"))
            assert LocaleContextHolder.get_locale() == Locale("en")


# ==================== 自动配置 ====================

class TestAutoConfiguration:
    def test_configure_with_explicit_params(self):
        src = configure_message_source(
            basenames=["msgs"], base_dir="i18n", encoding="utf-8"
        )
        assert src._basenames == ["msgs"]
        assert src._base_dir == "i18n"
        assert src._default_encoding == "utf-8"

    def test_configure_with_config_loader(self, tmp_path):
        # 构造一个最小 ConfigLoader 风格对象
        class FakeLoader:
            def get_prefix_config(self, prefix):
                if prefix == "spring.messages":
                    return {
                        "basename": "messages,errors",
                        "encoding": "UTF-8",
                        "base-dir": "classpath:i18n",
                        "fallback-to-system-locale": False,
                        "use-code-as-default-message": True,
                    }
                return {}

        src = configure_message_source(FakeLoader())
        assert src._basenames == ["messages", "errors"]
        assert src._base_dir == "i18n"  # classpath: 已剥离
        assert src._default_encoding == "UTF-8"
        assert src._fallback_to_system_locale is False
        assert src._use_code_as_default_message is True

    def test_configure_defaults_without_config(self):
        src = configure_message_source(None)
        assert src._basenames == ["messages"]
        assert src._base_dir == "i18n"
        assert src._default_encoding == "utf-8"
        assert src._fallback_to_system_locale is True

    def test_auto_config_register_to_context(self):
        # 构造一个最小 ApplicationContext 风格对象
        class FakeBeanFactory:
            def __init__(self):
                self._bean_definitions = {}
                self._bean_instances = {}
                self._type_to_name = {}

            def register_instance(self, name, instance):
                self._bean_instances[name] = instance
                cls = instance.__class__
                if cls not in self._type_to_name:
                    self._type_to_name[cls] = name

            def get_bean(self, name):
                return self._bean_instances.get(name)

        class FakeContext:
            def __init__(self):
                self.bean_factory = FakeBeanFactory()
                self.config_loader = None

        ctx = FakeContext()
        source = MessageSourceAutoConfiguration.register(ctx)
        assert source is not None
        assert ctx.bean_factory.get_bean("messageSource") is source

    def test_auto_config_skip_when_bean_exists(self):
        class FakeBeanFactory:
            def __init__(self):
                existing = StaticMessageSource()
                self._bean_definitions = {"messageSource": object()}
                self._bean_instances = {"messageSource": existing}
                self._type_to_name = {}

            def get_bean(self, name):
                return self._bean_instances.get(name)

        class FakeContext:
            def __init__(self):
                self.bean_factory = FakeBeanFactory()
                self.config_loader = None

        ctx = FakeContext()
        existing = ctx.bean_factory.get_bean("messageSource")
        returned = MessageSourceAutoConfiguration.register(ctx)
        # 应返回已存在的 Bean，不覆盖
        assert returned is existing


# ==================== 端到端集成测试 ====================

class TestEndToEnd:
    @pytest.fixture(autouse=True)
    def _restore_starlette(self):
        _restore_real_modules()
        yield

    def test_full_flow_with_resource_bundle(self, tmp_path):
        """端到端：资源文件 → MessageSource → Accessor → 多 locale 解析。"""
        d = tmp_path / "i18n"
        d.mkdir()
        (d / "messages.properties").write_text(
            "app.title=My App\napp.welcome=Welcome, {0}!",
            encoding="utf-8",
        )
        (d / "messages_zh_CN.properties").write_text(
            "app.title=我的应用\napp.welcome=欢迎，{0}！",
            encoding="utf-8",
        )
        src = ResourceBundleMessageSource(
            basenames=["messages"], base_dir=str(d), default_locale=Locale("en")
        )
        accessor = MessageSourceAccessor(src, default_locale=Locale("en"))

        # 默认 locale（en）
        assert accessor.getMessage("app.title") == "My App"
        assert accessor.getMessage("app.welcome", ["Tom"]) == "Welcome, Tom!"
        # 切换 zh_CN
        assert accessor.getMessage("app.title", locale=Locale("zh", "CN")) == "我的应用"
        assert accessor.getMessage("app.welcome", ["汤姆"], locale=Locale("zh", "CN")) == "欢迎，汤姆！"

    def test_full_flow_with_middleware_and_messages(self, tmp_path):
        """端到端：中间件 + 资源文件 + 路由内调用 MessageSource。"""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        d = tmp_path / "i18n"
        d.mkdir()
        (d / "messages.properties").write_text("greeting=Hello", encoding="utf-8")
        (d / "messages_zh_CN.properties").write_text("greeting=你好", encoding="utf-8")

        src = ResourceBundleMessageSource(
            basenames=["messages"], base_dir=str(d), default_locale=Locale("en")
        )

        async def greet(request):
            locale = get_request_locale(request)
            msg = src.getMessage("greeting", None, locale)
            return JSONResponse({"greeting": msg, "locale": locale.to_string()})

        app = Starlette()
        app.add_middleware(
            LocaleResolverMiddleware,
            locale_resolver=AcceptHeaderLocaleResolver(
                supported_locales=[Locale("en"), Locale("zh", "CN")],
                default_locale=Locale("en"),
            ),
        )
        app.router.add_route("/greet", greet, methods=["GET"])

        with TestClient(app) as client:
            # 中文请求
            resp = client.get("/greet", headers={"Accept-Language": "zh-CN"})
            assert resp.json()["greeting"] == "你好"
            # 英文请求
            resp = client.get("/greet", headers={"Accept-Language": "en-US"})
            assert resp.json()["greeting"] == "Hello"


# ==================== 辅助：Fake Request/Response ====================

class _FakeRequest:
    """Starlette ``Request`` 的最小子集，用于 LocaleResolver 单测。"""

    def __init__(self, headers=None, cookies=None, session=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.session = session  # None 表示无 session
        # request.state 用于中间件挂载
        from starlette.datastructures import State
        self.state = State()


class _FakeResponse:
    """Starlette ``Response`` 的最小子集，用于 CookieLocaleResolver 单测。"""

    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, max_age=None, path="/", domain=None,
                   secure=False, httponly=False, **kwargs):
        self.cookies[key] = {
            "value": value, "max_age": max_age, "path": path,
            "domain": domain, "secure": secure, "httponly": httponly,
        }
