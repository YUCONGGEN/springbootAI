"""配置变更监控。

配置监控是一个轻量、可选的框架能力。它只保存在进程内的有限历史记录，默认
关闭，不会读取或输出配置值，也不会改变配置加载/刷新流程。应用可以通过 YAML、
Nacos 或环境变量开启：

.. code-block:: yaml

    management:
      config-monitor:
        enabled: true
        include-values: false       # 生产环境建议保持 false
        history-size: 100
        refresh-events: true

设计目标是“监控失败不影响配置”：记录失败、脱敏和序列化都在独立的保护边界内，
任何异常只会丢弃本次监控事件。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("Spring.Config.Monitor")


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(value: Any, default: int, maximum: int = 10_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if 1 <= parsed <= maximum else default


def resolve_config_monitor_config(config: Any) -> Dict[str, Any]:
    """从最终配置解析配置监控选项。

    同时兼容 ``config-monitor``、``config_monitor`` 和根级
    ``springbootai.config-monitor``，方便历史项目逐步迁移。环境变量在
    :class:`ConfigLoader` 中完成覆盖，这里只负责安全解析，避免依赖具体配置源。
    """
    root = _mapping(config)
    management = _mapping(root.get("management"))
    section = management.get("config-monitor", management.get("config_monitor", {}))
    if not isinstance(section, Mapping):
        springbootai = _mapping(root.get("springbootai"))
        section = springbootai.get("config-monitor", springbootai.get("config_monitor", {}))
    section = _mapping(section)
    return {
        "enabled": _bool(section.get("enabled", False), False),
        "include_values": _bool(
            section.get("include-values", section.get("include_values", False)), False
        ),
        "history_size": _positive_int(
            section.get("history-size", section.get("history_size", 100)), 100, 10_000
        ),
        "refresh_events": _bool(
            section.get("refresh-events", section.get("refresh_events", True)), True
        ),
    }


_SENSITIVE_PARTS = (
    "password", "passwd", "secret", "token", "credential", "api-key", "api_key",
    "apikey", "private-key", "private_key", "access-key", "access_key", "authorization",
)


def _is_sensitive(key: str) -> bool:
    normalized = str(key).replace("_", "-").lower()
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _safe_value(value: Any, key: str, include_values: bool) -> Any:
    """返回可 JSON 序列化且脱敏的值摘要。"""
    if not include_values or _is_sensitive(key):
        return "******" if _is_sensitive(key) else None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, f"{key}.{k}", include_values) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v, key, include_values) for v in value]
    return repr(value)[:500]


def _flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(child, path))
    elif isinstance(value, (list, tuple)):
        # Lists are compared as one property. This avoids a large event for every index.
        result[prefix] = list(value)
    else:
        result[prefix] = value
    return result


def diff_config_keys(previous: Any, current: Any) -> list[str]:
    """返回两个配置快照之间发生变化的点分隔键。"""
    old = _flatten(previous)
    new = _flatten(current)
    keys = set(old) | set(new)
    changed: list[str] = []
    for key in keys:
        try:
            equal = old.get(key) == new.get(key) and key in old and key in new
        except Exception:
            equal = False
        if not equal:
            changed.append(key)
    return sorted(changed)


class ConfigMonitor:
    """线程安全的有限配置刷新历史。

    ``record`` 不持有配置加载锁，也不调用外部回调，避免监控反向阻塞业务。读取
    ``snapshot`` 返回深拷贝，调用方可以自由修改返回值。
    """

    def __init__(self, options: Optional[Mapping[str, Any]] = None):
        self._lock = threading.RLock()
        self._events: deque[Dict[str, Any]] = deque(maxlen=100)
        self._enabled = False
        self._include_values = False
        self._history_size = 100
        self._refresh_events = True
        self._last_config: Any = None
        self._configured_at: Optional[str] = None
        self.configure(options or {})

    def configure(self, options: Any = None, *, config: Any = None) -> Dict[str, Any]:
        """更新监控开关；关闭时清空历史，避免旧敏感数据残留。"""
        resolved = (
            resolve_config_monitor_config(config)
            if config is not None
            else (dict(options) if isinstance(options, Mapping) else resolve_config_monitor_config(options))
        )
        # 调用方可以只传一个字段（例如运行期只切换 enabled），其余字段
        # 必须回退到安全默认值，而不是因缺少字典键导致应用启动失败。
        defaults = resolve_config_monitor_config({})
        defaults.update({k: v for k, v in resolved.items() if k in defaults})
        resolved = defaults
        with self._lock:
            self._enabled = bool(resolved["enabled"])
            self._include_values = bool(resolved["include_values"])
            self._history_size = int(resolved["history_size"])
            self._refresh_events = bool(resolved["refresh_events"])
            self._events = deque(self._events, maxlen=self._history_size)
            self._configured_at = datetime.now(timezone.utc).isoformat()
            if not self._enabled:
                self._events.clear()
                self._last_config = None
        return dict(resolved)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def record(
        self,
        event_type: str,
        *,
        previous: Any = None,
        current: Any = None,
        source: str = "unknown",
        success: bool = True,
        duration_ms: Optional[float] = None,
        error: Optional[Any] = None,
    ) -> None:
        with self._lock:
            if not self._enabled or (event_type == "refresh" and not self._refresh_events):
                return
            changed = diff_config_keys(previous, current) if previous is not None else []
            event: Dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": str(event_type),
                "source": str(source or "unknown"),
                "success": bool(success),
                "changed_keys": changed,
            }
            if duration_ms is not None:
                try:
                    event["duration_ms"] = round(max(0.0, float(duration_ms)), 3)
                except (TypeError, ValueError):
                    pass
            if error:
                event["error"] = str(error)[:500]
            if self._include_values and current is not None:
                # Include only changed keys and always apply key based masking.
                flat = _flatten(current)
                event["values"] = {
                    key: _safe_value(flat.get(key), key, self._include_values)
                    for key in changed if key in flat
                }
            self._events.append(event)
            self._last_config = deepcopy(current)

    def record_refresh(self, *, previous: Any, current: Any, source: str,
                       success: bool, duration_ms: Optional[float] = None,
                       error: Optional[Any] = None) -> None:
        self.record(
            "refresh", previous=previous, current=current, source=source,
            success=success, duration_ms=duration_ms, error=error,
        )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "include_values": self._include_values,
                "history_size": self._history_size,
                "refresh_events": self._refresh_events,
                "configured_at": self._configured_at,
                "events": deepcopy(list(self._events)),
            }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


__all__ = [
    "ConfigMonitor", "resolve_config_monitor_config", "diff_config_keys",
]
