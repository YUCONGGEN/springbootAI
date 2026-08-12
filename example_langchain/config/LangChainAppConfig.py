"""
LangChain 应用配置类 - 在 Spring refresh 阶段触发 AI 与 LangChain 模块自动装配。

装配时机（关键）：
@Configuration 类在 ApplicationContext.refresh 的 _register_configuration_beans 阶段
被实例化（早于 @Service 的 _autowire_value_annotations 阶段）。因此把 configure_ai +
configure_langchain 放在 __init__ 中执行，可保证 lc* Bean 在 @Service 实例化前已注册到
BeanFactory，使构造器 @Autowired 注入生效。

configure_langchain 内部会双重注册（BeanRegistry + 活跃 ApplicationContext.bean_factory），
让 lc* Bean 既能 registry.get(name) 直取，又能按类型 @Autowired。
"""
import logging

from spring.annotations.core import Configuration, Slf4j

logger = logging.getLogger("Spring.LangChain")


@Configuration
@Slf4j
class LangChainAppConfig:
    """LangChain 集成配置 - 启动时装配 AI + LangChain 双模块。"""

    def __init__(self):
        """实例化时立即装配 AI 与 LangChain 模块（在 @Service 实例化前完成）。"""
        from spring.context.registry import BeanRegistry
        from spring.config.config_loader import config_loader
        from spring.ai.autoconfig import configure_ai
        from spring.langchain.autoconfig import configure_langchain
        from spring.langgraph.autoconfig import configure_langgraph

        registry = BeanRegistry()
        # 1. 先装配 spring.ai（提供 aiChatModel / aiEmbeddingModel）
        try:
            ai_beans = configure_ai(registry=registry, config=config_loader)
        except Exception as exc:
            logger.warning("spring.ai 装配失败（LangChain 将无底层模型）: %s", exc)
            ai_beans = {}
        # 2. 再装配 spring.langchain（default-llm=auto 复用 aiChatModel）
        try:
            lc_beans = configure_langchain(registry=registry, config=config_loader)
        except Exception as exc:
            logger.error("spring.langchain 装配失败: %s", exc)
            lc_beans = {}

        try:
            lg_beans = configure_langgraph(registry=registry, config=config_loader)
        except Exception as exc:
            logger.error("spring.langgraph auto-configuration failed: %s", exc)
            lg_config = config_loader.get_prefix_config("spring.langgraph") or {}
            enabled = str(lg_config.get("enabled", False)).strip().lower() in {
                "true", "1", "yes", "on"
            }
            if enabled:
                # Explicitly enabled optional infrastructure must fail startup
                # instead of leaving a partially configured application alive.
                raise
            lg_beans = {}

        self._ai_beans_count = len(ai_beans)
        self._lc_beans_count = len(lc_beans)
        self._lg_beans_count = len(lg_beans)
        logger.info(
            "LangChainAppConfig 装配完成: ai beans=%d, langchain beans=%d",
            self._ai_beans_count, self._lc_beans_count)

    @property
    def status(self) -> dict:
        return {"ai_beans": self._ai_beans_count,
                "lc_beans": self._lc_beans_count,
                "langgraph_beans": self._lg_beans_count}
