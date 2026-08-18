"""``MessageSourceAutoConfiguration`` 默认装配（对齐 Spring Boot
``MessageSourceAutoConfiguration``）。

从 ``application.yml`` 读取 ``springbootai.messages.basename`` / ``springbootai.messages.encoding``
等配置，构造默认 ``ResourceBundleMessageSource`` 并注册为容器单例 Bean。

配置示例（``application.yml``）::

    spring:
      messages:
        basename: messages,errors     # 资源基名列表（逗号分隔），默认 messages
        encoding: UTF-8                # 资源文件编码，默认 UTF-8
        base-dir: classpath:i18n       # 资源根目录，默认 classpath:i18n
        fallback-to-system-locale: true
        use-code-as-default-message: false

``base-dir`` 取值：
- ``classpath:xxx`` → 相对当前工作目录的 ``xxx`` 子目录（对齐 Spring ``classpath:`` 前缀语义）
- 绝对/相对路径 → 直接使用
- 未配置 → 默认 ``i18n``（即 ``./i18n/messages_*.properties``）

集成方式：
1. ``configure_message_source(config_loader)`` 工厂函数：从配置构造消息源。
2. ``ApplicationContext`` 启动时调用本模块注册 ``messageSource`` Bean（见下方钩子）。
3. 应用层通过 ``context.get_bean("messageSource")`` 或 ``get_bean_by_type(MessageSource)`` 获取。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from .locale import Locale
from .message_source import MessageSource
from .sources import ResourceBundleMessageSource


# Bean 名称（对齐 Spring ``messageSource``）
MESSAGE_SOURCE_BEAN_NAME = "messageSource"


def _split_basenames(raw: str) -> List[str]:
    """逗号分隔的 basename 列表解析；去除空白与空项。"""
    if not raw:
        return ["messages"]
    return [b.strip() for b in raw.split(",") if b.strip()]


def _resolve_base_dir(raw: str) -> str:
    """解析 ``base-dir`` 配置。

    - ``classpath:xxx`` → ``xxx``（相对工作目录；Spring ``classpath:`` 在此实现为文件系统等价）
    - 其他 → 原样返回
    - 未提供 → ``i18n``
    """
    if not raw:
        return "i18n"
    if raw.startswith("classpath:"):
        return raw[len("classpath:"):]
    return raw


def configure_message_source(
    config_loader: Optional[Any] = None,
    basenames: Optional[Iterable[str]] = None,
    base_dir: Optional[str] = None,
    encoding: Optional[str] = None,
    fallback_to_system_locale: Optional[bool] = None,
    use_code_as_default_message: Optional[bool] = None,
    default_locale: Optional[Locale] = None,
) -> ResourceBundleMessageSource:
    """从 ``config_loader`` 与显式参数构造 ``ResourceBundleMessageSource``。

    优先级：显式参数 > ``config_loader`` 读取的 ``springbootai.messages.*`` > 默认值。

    Args:
        config_loader:                ``springbootai.config.ConfigLoader`` 实例（可为 None）。
        basenames:                    资源基名列表。
        base_dir:                     资源根目录。
        encoding:                     资源编码。
        fallback_to_system_locale:    locale 未命中是否回退到系统 locale。
        use_code_as_default_message:  找不到消息时是否把 code 作为默认消息。
        default_locale:               默认 locale。

    Returns:
        配置好的 ``ResourceBundleMessageSource`` 单例（每次调用返回新实例）。
    """
    # 从 config_loader 读取默认值
    cfg_basenames = ["messages"]
    cfg_base_dir = "i18n"
    cfg_encoding = "utf-8"
    cfg_fallback = True
    cfg_use_code = False

    if config_loader is not None:
        try:
            msgs_cfg = config_loader.get_prefix_config("springbootai.messages") or {}
            if msgs_cfg.get("basename"):
                cfg_basenames = _split_basenames(msgs_cfg["basename"])
            if msgs_cfg.get("base-dir") or msgs_cfg.get("base_dir"):
                cfg_base_dir = _resolve_base_dir(
                    msgs_cfg.get("base-dir") or msgs_cfg.get("base_dir")
                )
            if msgs_cfg.get("encoding"):
                cfg_encoding = msgs_cfg["encoding"]
            if msgs_cfg.get("fallback-to-system-locale") is not None:
                cfg_fallback = bool(msgs_cfg.get("fallback-to-system-locale"))
            if msgs_cfg.get("use-code-as-default-message") is not None:
                cfg_use_code = bool(msgs_cfg.get("use-code-as-default-message"))
        except Exception:
            # 配置缺失或异常：用默认值
            pass

    final_basenames = list(basenames) if basenames is not None else cfg_basenames
    final_base_dir = base_dir if base_dir is not None else cfg_base_dir
    final_encoding = encoding if encoding is not None else cfg_encoding
    final_fallback = fallback_to_system_locale if fallback_to_system_locale is not None else cfg_fallback
    final_use_code = use_code_as_default_message if use_code_as_default_message is not None else cfg_use_code
    final_default_locale = default_locale if default_locale is not None else Locale("")

    source = ResourceBundleMessageSource(
        basenames=final_basenames,
        base_dir=final_base_dir,
        default_encoding=final_encoding,
        fallback_to_system_locale=final_fallback,
        default_locale=final_default_locale,
    )
    if final_use_code:
        source.set_use_code_as_default_message(True)
    return source


class MessageSourceAutoConfiguration:
    """消息源自动配置（对齐 Spring Boot ``MessageSourceAutoConfiguration``）。

    静态方法 ``register(context)``：从 ``context.config_loader`` 读取配置，构造
    ``ResourceBundleMessageSource`` 并注册为 ``messageSource`` Bean。若已存在同名 Bean 则跳过。
    """

    @staticmethod
    def register(context: Any) -> Optional[MessageSource]:
        """向 ``ApplicationContext`` 注册 ``messageSource`` Bean。

        Returns:
            注册的消息源实例；若已存在同名 Bean 则返回该实例。
        """
        bean_factory = getattr(context, "bean_factory", None) or getattr(context, "_bean_factory", None)
        if bean_factory is None:
            return None
        # 已存在同名 Bean：跳过（对齐 Spring ``@ConditionalOnMissingBean``）
        existing = bean_factory._bean_definitions.get(MESSAGE_SOURCE_BEAN_NAME) \
            if hasattr(bean_factory, "_bean_definitions") else None
        if existing is not None:
            try:
                return bean_factory.get_bean(MESSAGE_SOURCE_BEAN_NAME)
            except Exception:
                return None

        config_loader = getattr(context, "config_loader", None)
        source = configure_message_source(config_loader)

        # 注册为实例（BeanFactory.register_instance 直接放 _bean_instances）
        try:
            bean_factory.register_instance(MESSAGE_SOURCE_BEAN_NAME, source)
            # 同步 type_to_name 索引（register_instance 已做，保险起见）
            from .message_source import MessageSource as _MS
            bean_factory._type_to_name.setdefault(_MS, MESSAGE_SOURCE_BEAN_NAME)
            bean_factory._type_to_name.setdefault(ResourceBundleMessageSource, MESSAGE_SOURCE_BEAN_NAME)
        except Exception:
            pass
        return source


__all__ = [
    "MESSAGE_SOURCE_BEAN_NAME",
    "configure_message_source",
    "MessageSourceAutoConfiguration",
]
