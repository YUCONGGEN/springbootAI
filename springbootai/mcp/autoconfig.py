"""Spring-style optional auto-configuration for MCP clients and server."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from springbootai.ai.tools import CompositeToolRegistry, ToolExecutionPolicy
from springbootai.config.config_loader import config_loader
from springbootai.context.registry import BeanRegistry
from springbootai.mcp.client import build_client_manager, require_mcp_sdk
from springbootai.mcp.config import MCPProperties, bind_mcp_config
from springbootai.mcp.server import MCPServerAdapter

logger = logging.getLogger("Spring.MCP")


def _config_prefix(config: Any) -> Dict[str, Any]:
    if config is None:
        return {}
    getter = getattr(config, "get_prefix_config", None)
    if getter:
        return getter("springbootai.mcp") or {}
    if isinstance(config, dict):
        spring = config.get("spring", {}) or {}
        return dict(spring.get("mcp", {}) or {})
    return {}


def _register(registry: BeanRegistry, name: str, bean: Any) -> None:
    registry.register(name, bean)
    try:
        from springbootai.context.application_context import ApplicationContext
        from springbootai.context.bean_definition import BeanDefinition

        context = ApplicationContext.get_instance()
        factory = getattr(context, "bean_factory", None) if context else None
        if factory:
            factory.register_bean_definition(
                name, BeanDefinition(bean_class=type(bean), bean_name=name)
            )
            factory.register_instance(name, bean)
    except Exception as exc:
        logger.debug("MCP bean factory synchronization skipped: %s", exc)


def configure_mcp(
    registry: Optional[BeanRegistry] = None,
    config: Optional[Any] = None,
    *,
    ai_tool_registry: Any = None,
    remote_tool_policy: Optional[ToolExecutionPolicy] = None,
    token_verifier: Any = None,
    in_process_servers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Configure MCP clients, their AI tool bridge and an optional server.

    No network connection or SDK import occurs while ``springbootai.mcp.enabled`` is
    false.  Auto-connect is intended for an explicit bootstrap call; applications
    that want lifecycle-managed startup may set ``auto-connect=false`` and call
    the manager from their ASGI startup hook.
    """
    registry = registry or BeanRegistry()
    props: MCPProperties = bind_mcp_config(
        _config_prefix(config if config is not None else config_loader)
    )
    if not props.enabled:
        logger.info("springbootai.mcp.enabled=false; skipping MCP auto-configuration")
        return {}

    require_mcp_sdk()
    beans: Dict[str, Any] = {"mcpProperties": props}
    _register(registry, "mcpProperties", props)

    manager = build_client_manager(props.clients, in_process_servers=in_process_servers)
    _register(registry, "mcpClientManager", manager)
    beans["mcpClientManager"] = manager

    if props.clients:
        if props.auto_connect:
            manager.connect_all_sync()
            remote_registry = manager.create_tool_registry_sync(remote_tool_policy)
            _register(registry, "mcpToolRegistry", remote_registry)
            beans["mcpToolRegistry"] = remote_registry
            local_registry = ai_tool_registry or registry.get("aiToolRegistry")
            effective_registry = (
                CompositeToolRegistry(local_registry, remote_registry)
                if local_registry is not None
                else remote_registry
            )
            _register(registry, "aiEffectiveToolRegistry", effective_registry)
            beans["aiEffectiveToolRegistry"] = effective_registry
            chat_client = registry.get("aiChatClient")
            if chat_client is not None and hasattr(chat_client, "default_tools_set"):
                chat_client.default_tools_set(effective_registry)
        else:
            logger.info(
                "MCP auto-connect is disabled; call create_tool_registry after application startup"
            )

    if props.server.enabled:
        selected_registry = ai_tool_registry or registry.get("aiToolRegistry")
        server = MCPServerAdapter(
            props.server,
            selected_registry,
            token_verifier=token_verifier,
        )
        _register(registry, "mcpServer", server)
        beans["mcpServer"] = server

    logger.info(
        "MCP auto-configuration completed: clients=%d server=%s",
        len(props.clients),
        props.server.enabled,
    )
    return beans


__all__ = ["configure_mcp"]
