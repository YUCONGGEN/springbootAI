"""Spring-style optional LangGraph auto-configuration."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from spring.config.config_loader import config_loader
from spring.context.registry import BeanRegistry
from spring.langgraph.config import bind_langgraph_config
from spring.langgraph.runtime import LangGraphRuntime

logger = logging.getLogger("Spring.LangGraph")


def _config_prefix(config: Any) -> Dict[str, Any]:
    if config is None:
        return {}
    getter = getattr(config, "get_prefix_config", None)
    if getter:
        return getter("spring.langgraph") or {}
    if isinstance(config, dict):
        spring = config.get("spring", {}) or {}
        return dict((spring.get("langgraph", {}) or {}))
    return {}


def _register(registry: BeanRegistry, name: str, bean: Any) -> None:
    registry.register(name, bean)
    try:
        from spring.context.application_context import ApplicationContext
        ctx = ApplicationContext.get_instance()
        bf = getattr(ctx, "bean_factory", None) if ctx else None
        if bf:
            from spring.context.bean_definition import BeanDefinition
            bf.register_bean_definition(name, BeanDefinition(bean_class=type(bean), bean_name=name))
            bf.register_instance(name, bean)
    except Exception as exc:
        logger.debug("LangGraph bean factory sync skipped: %s", exc)


def configure_langgraph(
    registry: Optional[BeanRegistry] = None,
    config: Optional[Any] = None,
    *,
    model: Any = None,
    tool_registry: Any = None,
    checkpointer: Any = None,
) -> Dict[str, Any]:
    """Create LangGraph beans only when ``spring.langgraph.enabled`` is true.

    ``model`` and ``tool_registry`` are normally resolved from ``spring.ai``
    by name, so applications keep one model, retry and tool policy.
    """
    registry = registry or BeanRegistry()
    props = bind_langgraph_config(
        _config_prefix(config if config is not None else config_loader)
    )
    if not props.enabled:
        logger.info("spring.langgraph.enabled=false; skipping LangGraph auto-configuration")
        return {}

    selected_model = model or registry.get("aiChatModel") or registry.get("lcLangChainModel")
    selected_tools = tool_registry or registry.get("aiToolRegistry")
    runtime = LangGraphRuntime(
        props, model=selected_model, tool_registry=selected_tools, checkpointer=checkpointer
    )
    beans = {
        "langGraphProperties": props,
        "langGraphRuntime": runtime,
    }
    _register(registry, "langGraphProperties", props)
    _register(registry, "langGraphRuntime", runtime)
    if selected_model is not None:
        _register(registry, "langGraphModel", selected_model)
        beans["langGraphModel"] = selected_model
    logger.info("LangGraph auto-configuration completed: name=%s", props.name)
    return beans
