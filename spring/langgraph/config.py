"""Typed configuration for the optional SpringBootAI LangGraph module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping


class LangGraphConfigurationError(ValueError):
    """Raised when a LangGraph setting is unsafe or invalid."""


@dataclass(frozen=True)
class LangGraphProperties:
    """Configuration bound from ``spring.langgraph``.

    The module is disabled by default.  An in-memory checkpointer is explicitly
    opt-in because it is suitable for tests only and is lost on process restart.
    """

    enabled: bool = False
    name: str = "springbootai"
    timeout_seconds: float = 60.0
    max_steps: int = 25
    checkpointer: str = "none"  # none | memory | injected
    allow_in_memory: bool = False
    require_thread_id: bool = True
    max_input_bytes: int = 65_536
    stream_mode: str = "updates"

    def validate(self) -> "LangGraphProperties":
        if not self.name or len(self.name) > 128:
            raise LangGraphConfigurationError("spring.langgraph.name must be 1-128 characters")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 600:
            raise LangGraphConfigurationError("timeout_seconds must be in (0, 600]")
        if self.max_steps < 1 or self.max_steps > 1000:
            raise LangGraphConfigurationError("max_steps must be in [1, 1000]")
        if self.checkpointer not in {"none", "memory", "injected"}:
            raise LangGraphConfigurationError("checkpointer must be none, memory, or injected")
        if self.checkpointer == "memory" and not self.allow_in_memory:
            raise LangGraphConfigurationError(
                "in-memory checkpointer is disabled; set allow-in-memory=true only for tests"
            )
        if self.max_input_bytes < 1024 or self.max_input_bytes > 10 * 1024 * 1024:
            raise LangGraphConfigurationError("max_input_bytes must be in [1024, 10485760]")
        if self.stream_mode not in {"values", "updates", "messages", "debug", "custom"}:
            raise LangGraphConfigurationError("unsupported stream_mode")
        return self


def _value(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data:
            return data[name]
        kebab = name.replace("_", "-")
        if kebab in data:
            return data[kebab]
    return default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bind_langgraph_config(data: Mapping[str, Any] | None = None) -> LangGraphProperties:
    """Bind a ``spring.langgraph`` mapping and environment overrides."""

    data = data or {}
    def env_or(key: str, env_name: str, default: Any) -> Any:
        return os.environ[env_name] if env_name in os.environ else _value(data, key, default=default)

    values: Dict[str, Any] = {
        "enabled": _bool(env_or("enabled", "LG_ENABLED", False), False),
        "name": env_or("name", "LG_NAME", "springbootai"),
        "timeout_seconds": _float(
            env_or("timeout_seconds", "LG_TIMEOUT_SECONDS", 60.0), 60.0
        ),
        "max_steps": _int(
            env_or("max_steps", "LG_MAX_STEPS", 25), 25
        ),
        "checkpointer": str(
            env_or("checkpointer", "LG_CHECKPOINTER", "none")
        ).lower(),
        "allow_in_memory": _bool(
            env_or("allow_in_memory", "LG_ALLOW_IN_MEMORY", False), False
        ),
        "require_thread_id": _bool(
            env_or("require_thread_id", "LG_REQUIRE_THREAD_ID", True), True
        ),
        "max_input_bytes": _int(
            env_or("max_input_bytes", "LG_MAX_INPUT_BYTES", 65_536), 65_536
        ),
        "stream_mode": str(
            env_or("stream_mode", "LG_STREAM_MODE", "updates")
        ).lower(),
    }
    return LangGraphProperties(**values).validate()
