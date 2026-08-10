"""SpringBootAI Bean Validation 异常定义。

设计对齐 Jakarta Bean Validation（Hibernate Validator）的错误语义：
- ``ValidationError``：校验失败时抛出的汇总异常，包含全部约束违反。
- ``ConstraintViolation``：单条约束违反信息（字段、值、消息、约束类型）。
"""
from __future__ import annotations

from typing import Any, List


class ConstraintViolation:
    """单条约束违反记录。

    属性：
        attr_name:    违反约束的字段名。
        value:        被校验的实际值。
        constraint:   触发违反的约束注解实例（如 ``NotNull``/``Size``）。
        message:      人可读的违规描述。
    """

    __slots__ = ("attr_name", "value", "constraint", "message")

    def __init__(self, attr_name: str, value: Any, constraint: Any, message: str):
        self.attr_name = attr_name
        self.value = value
        self.constraint = constraint
        self.message = message

    def __repr__(self) -> str:
        cname = type(self.constraint).__name__
        return (f"ConstraintViolation(attr={self.attr_name!r}, "
                f"constraint={cname}, value={self.value!r}, message={self.message!r})")

    def __str__(self) -> str:
        return f"{self.attr_name}: {self.message}"


class ValidationError(Exception):
    """Bean Validation 校验失败异常。

    汇总一次校验产生的所有 ``ConstraintViolation``，便于上层统一处理或批量回显。
    """

    def __init__(self, violations: List[ConstraintViolation]):
        self.violations: List[ConstraintViolation] = list(violations)
        lines = "; ".join(str(v) for v in self.violations) if self.violations else "校验失败"
        super().__init__(lines)

    @property
    def messages(self) -> List[str]:
        return [v.message for v in self.violations]


__all__ = ["ConstraintViolation", "ValidationError"]
