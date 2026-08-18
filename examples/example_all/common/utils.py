"""全局基础设施使用的无副作用工具。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4


def new_request_id(prefix: str = "req") -> str:
    """生成用于日志和请求头的短关联 ID。"""
    normalized = prefix.strip().replace(" ", "-") or "req"
    return f"{normalized}-{uuid4().hex[:12]}"


def mask_sensitive(values: Mapping[str, Any], *, keys: frozenset[str] = frozenset({"password", "token", "secret", "authorization"})) -> dict[str, Any]:
    """复制元数据，并遮蔽不应写入请求日志的敏感值。"""
    return {
        key: "***" if key.lower() in keys else value
        for key, value in values.items()
    }


__all__ = ["mask_sensitive", "new_request_id"]
