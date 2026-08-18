"""SpringBootAI i18n 国际化模块 —— 注解驱动的消息源与区域解析（对齐 Spring ``MessageSource`` +
``LocaleResolver`` 体系）。

模块组成（镜像 ``org.springframework.context.*`` / ``org.springframework.web.servlet.i18n.*``）：

- **locale**:          ``Locale`` 区域对象（``language``/``country``/``variant``），对齐
                        ``java.util.Locale`` 的字符串表示（``en``/``en_US``/``zh_CN``）
- **message_source**:  ``MessageSource`` 接口 + ``AbstractMessageSource`` 抽象基类 +
                        ``NoSuchMessageException`` + ``MessageSourceResolvable``
- **sources**:         ``StaticMessageSource``（编程式）/ ``ResourceBundleMessageSource``
                        （资源包加载，支持 ``.properties`` 与 ``.yml``）/ ``DelegatingMessageSource``
                        （父级回退，对齐 ``AbstractApplicationContext`` 的内嵌实现）
- **locale_resolver**: ``LocaleResolver`` 接口 + ``LocaleContext`` + ``AcceptHeaderLocaleResolver``
                        / ``FixedLocaleResolver`` / ``SessionLocaleResolver`` / ``CookieLocaleResolver``
- **holder**:          ``LocaleContextHolder`` 线程/协程安全上下文持有器（``ContextVar``）
- **accessor**:        ``MessageSourceAccessor`` 便捷访问器（提供无异常 ``getMessage`` 变体）
- **properties**:      Java 风格 ``.properties`` 文件解析器（UTF-8，支持转义/续行）
- **middleware**:      ``LocaleResolverMiddleware`` Starlette 中间件，从请求解析并设置 ``LocaleContext``
- **auto_config**:     ``MessageSourceAutoConfiguration`` 默认装配（``springbootai.messages.basename``）

设计原则：**复用项目既有范式，不重复造轮子**。本模块：
- 不依赖任何第三方库（``.properties`` 解析自实现，``.yml`` 复用项目核心依赖 ``pyyaml``）。
- 注解描述符范式与 ``springbootai.excel`` / ``springbootai.csv`` 一致。
- ``LocaleContextHolder`` 复用 ``ContextVar`` 模式，与 ``springbootai.datasource`` 动态路由一致。

与 Java 的差异：
- Spring 用 ``ResourceBundle`` 加载类路径资源；本实现用文件系统路径 + ``basenames`` 列表。
- ``MessageFormat`` 类型子模式（``{0,number,#.##}``）降级为 ``str.format``，类型符忽略；
  位置占位符 ``{0}``/``{1}`` 与 Java 行为一致。
- 不支持 ``ResourceBundle.Control`` 自定义加载策略（可按需扩展）。
"""
from .locale import (
    Locale,
    LOCALE_EN, LOCALE_US, LOCALE_UK,
    LOCALE_CHINA, LOCALE_TAIWAN, LOCALE_JAPAN, LOCALE_KOREA,
    LOCALE_GERMANY, LOCALE_FRANCE,
    parse_locale,
)
from .message_source import (
    MessageSource,
    AbstractMessageSource,
    NoSuchMessageException,
    MessageSourceResolvable,
    DefaultMessageSourceResolvable,
)
from .sources import (
    StaticMessageSource,
    ResourceBundleMessageSource,
    DelegatingMessageSource,
)
from .locale_resolver import (
    LocaleResolver,
    LocaleContext,
    SimpleLocaleContext,
    SimpleTimeZoneAwareLocaleContext,
    AcceptHeaderLocaleResolver,
    FixedLocaleResolver,
    SessionLocaleResolver,
    CookieLocaleResolver,
    parse_accept_language,
)
from .holder import LocaleContextHolder
from .accessor import MessageSourceAccessor
from .properties import load_properties, parse_properties
from .middleware import LocaleResolverMiddleware, get_request_locale
from .auto_config import MessageSourceAutoConfiguration, configure_message_source

__version__ = "2.3.3"

__all__ = [
    # Locale
    "Locale",
    "LOCALE_EN", "LOCALE_US", "LOCALE_UK",
    "LOCALE_CHINA", "LOCALE_TAIWAN", "LOCALE_JAPAN", "LOCALE_KOREA",
    "LOCALE_GERMANY", "LOCALE_FRANCE",
    "parse_locale",
    # MessageSource
    "MessageSource", "AbstractMessageSource",
    "NoSuchMessageException", "MessageSourceResolvable", "DefaultMessageSourceResolvable",
    # Sources
    "StaticMessageSource", "ResourceBundleMessageSource", "DelegatingMessageSource",
    # LocaleResolver
    "LocaleResolver", "LocaleContext", "SimpleLocaleContext",
    "SimpleTimeZoneAwareLocaleContext",
    "AcceptHeaderLocaleResolver", "FixedLocaleResolver",
    "SessionLocaleResolver", "CookieLocaleResolver",
    "parse_accept_language",
    # Holder / Accessor
    "LocaleContextHolder", "MessageSourceAccessor",
    # Properties
    "load_properties", "parse_properties",
    # Middleware
    "LocaleResolverMiddleware", "get_request_locale",
    # Auto config
    "MessageSourceAutoConfiguration", "configure_message_source",
    "__version__",
]
