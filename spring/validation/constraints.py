"""SpringBootAI Bean Validation 约束注解 —— 字段级描述符。

设计原则：**复用项目既有范式，不重复造轮子**。本模块的字段级约束完全镜像 ORM 层
``spring/orm/ddl_auto.py`` 的 ``Column``/``Id`` 与 Excel 层 ``spring/excel/annotations.py``
的 ``ExcelProperty`` 元数据描述符范式：

- 字段级约束以**类属性描述符**形式声明（推荐），Python 自动回填字段名；也支持**函数装饰器**
  形式（镜像 ``column()`` / ``ExcelProperty.__call__``）。
- 元数据通过 ``cls.__mro__`` 反射读取（与 ``Column``/``__column__`` 一致），由
  ``BeanValidator`` 统一收集并校验。

对齐 Jakarta Bean Validation（``javax.validation.constraints``）的核心约束：
``@NotNull`` / ``@NotBlank`` / ``@NotEmpty`` / ``@Size`` / ``@Min`` / ``@Max`` /
``@Pattern`` / ``@Email`` / ``@Positive`` / ``@PositiveOrZero`` / ``@Negative`` /
``@NegativeOrZero`` / ``@AssertTrue`` / ``@AssertFalse``。

与 Java 的差异（已标注）：
- Java Bean Validation 是 JSR-380 标准 + Hibernate Validator 实现，运行时通过反射读注解；
  本模块同样反射读字段描述符，但不依赖 JPA/Pydantic，适用于任意 Python 对象。
- 约束只支持字段级（Java 还支持方法参数级/返回值级），方法级校验由 ``@BeanValidate`` AOP
  切面对参数对象整体校验实现（见 ``validator.py``）。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional


class Constraint:
    """所有字段约束的基类（镜像 ORM ``Column`` 描述符范式）。

    子类需实现 ``_check(value) -> Optional[str]``，返回违规消息字符串；通过返回 ``None``
    表示通过。``message`` 可由用户覆盖。

    两种使用方式（与 ``Column``/``ExcelProperty`` 一致）：

    1. 类属性描述符（推荐）::

           class User:
               name = NotBlank(message="姓名不能为空")
               age = Min(0, message="年龄不能为负")
               def __init__(self, name=None, age=None): ...

    2. 函数装饰器（镜像 ``@column``）::

           @NotBlank()
           def name(self): ...
    """

    # 约束名，子类覆盖（用于校验报告归类）
    constraint_name: str = "Constraint"

    def __init__(self, message: Optional[str] = None):
        self.message = message
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """类属性描述符形式时，Python 自动回填字段名（镜像 ``ExcelProperty``）。"""
        self.attr_name = name

    def __call__(self, target: Callable) -> Callable:
        """函数装饰器形式：``@NotBlank()``，把约束挂到 ``__bean_constraint__`` 列表。

        镜像 ORM ``column()`` 的 ``setattr(f, '__column__', col)`` 与
        ``ExcelProperty.__call__`` 的 ``setattr(target, '__excel_property__', self)``。
        一个方法上可叠加多个约束（用列表累积，而非覆盖）。
        """
        existing = getattr(target, "__bean_constraint__", None)
        if isinstance(existing, list):
            existing.append(self)
        else:
            setattr(target, "__bean_constraint__", [self])
        if not self.attr_name:
            self.attr_name = getattr(target, "__name__", "")
        return target

    def _check(self, value: Any) -> Optional[str]:
        """子类实现：返回违规消息（None 表示通过）。"""
        raise NotImplementedError

    def validate(self, value: Any) -> Optional[str]:
        """对外校验入口：返回违规消息或 None。

        默认消息优先取用户自定义 ``message``，否则取 ``_check`` 返回的默认消息。
        """
        msg = self._check(value)
        if msg is None:
            return None
        return self.message if self.message else msg

    def __repr__(self) -> str:
        return f"{type(self).__name__}(attr={self.attr_name!r})"


# ==================== 非空类约束 ====================

class NotNull(Constraint):
    """``@NotNull``：值不能为 None（允许空字符串/空集合）。

    对齐 ``javax.validation.constraints.NotNull``。
    """
    constraint_name = "NotNull"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return "不能为 null"
        return None


class NotBlank(Constraint):
    """``@NotBlank``：字符串不能为 None 且去除首尾空白后长度 > 0。

    对齐 ``javax.validation.constraints.NotBlank``（仅作用于字符串）。
    """
    constraint_name = "NotBlank"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return "不能为空"
        if not isinstance(value, str):
            return None  # 非字符串交给其他约束（如 NotNull）
        if value.strip() == "":
            return "不能为空白"
        return None


class NotEmpty(Constraint):
    """``@NotEmpty``：不能为 None 且 size > 0（字符串/集合/字典/数组）。

    对齐 ``javax.validation.constraints.NotEmpty``。
    """
    constraint_name = "NotEmpty"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return "不能为空"
        try:
            if len(value) == 0:
                return "长度/大小必须大于 0"
        except TypeError:
            return None  # 无 len() 的对象，不强制
        return None


# ==================== 长度/大小约束 ====================

class Size(Constraint):
    """``@Size``：字符串/集合/数组长度在 ``[min, max]`` 区间。

    对齐 ``javax.validation.constraints.Size``。``min`` 默认 0，``max`` 默认 2^31-1。
    """
    constraint_name = "Size"

    def __init__(self, min: int = 0, max: int = 2 ** 31 - 1, message: Optional[str] = None):
        super().__init__(message=message)
        if min < 0:
            raise ValueError("@Size min 不能为负")
        if max < min:
            raise ValueError("@Size max 不能小于 min")
        self.min = min
        self.max = max

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None  # null 交给 @NotNull
        try:
            length = len(value)
        except TypeError:
            return None  # 无 len() 的对象，不强制
        if length < self.min or length > self.max:
            return f"长度必须在 {self.min} 到 {self.max} 之间（实际 {length}）"
        return None


# ==================== 数值范围约束 ====================

class Min(Constraint):
    """``@Min``：数值 >= value。对齐 ``javax.validation.constraints.Min``。"""
    constraint_name = "Min"

    def __init__(self, value: Any, message: Optional[str] = None):
        super().__init__(message=message)
        self.value = value

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) < float(self.value):
                return f"必须大于等于 {self.value}"
        except (TypeError, ValueError):
            return None  # 非数值，不强制
        return None


class Max(Constraint):
    """``@Max``：数值 <= value。对齐 ``javax.validation.constraints.Max``。"""
    constraint_name = "Max"

    def __init__(self, value: Any, message: Optional[str] = None):
        super().__init__(message=message)
        self.value = value

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) > float(self.value):
                return f"必须小于等于 {self.value}"
        except (TypeError, ValueError):
            return None
        return None


class Positive(Constraint):
    """``@Positive``：数值 > 0。对齐 ``javax.validation.constraints.Positive``。"""
    constraint_name = "Positive"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) <= 0:
                return "必须为正数"
        except (TypeError, ValueError):
            return None
        return None


class PositiveOrZero(Constraint):
    """``@PositiveOrZero``：数值 >= 0。"""
    constraint_name = "PositiveOrZero"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) < 0:
                return "必须大于等于 0"
        except (TypeError, ValueError):
            return None
        return None


class Negative(Constraint):
    """``@Negative``：数值 < 0。"""
    constraint_name = "Negative"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) >= 0:
                return "必须为负数"
        except (TypeError, ValueError):
            return None
        return None


class NegativeOrZero(Constraint):
    """``@NegativeOrZero``：数值 <= 0。"""
    constraint_name = "NegativeOrZero"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if float(value) > 0:
                return "必须小于等于 0"
        except (TypeError, ValueError):
            return None
        return None


# ==================== 字符串格式约束 ====================

class Pattern(Constraint):
    """``@Pattern``：字符串匹配正则。对齐 ``javax.validation.constraints.Pattern``。"""
    constraint_name = "Pattern"

    def __init__(self, regex: str, message: Optional[str] = None):
        super().__init__(message=message)
        try:
            self._compiled = re.compile(regex)
        except re.error as e:
            raise ValueError(f"@Pattern 正则非法: {e}") from e
        self.regex = regex

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        if not self._compiled.search(value):
            return f"不匹配模式 {self.regex!r}"
        return None


# 常见邮箱正则（与 Hibernate Validator Email 推荐一致，宽松版本）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Email(Constraint):
    """``@Email``：字符串为合法邮箱格式。对齐 ``javax.validation.constraints.Email``。

    采用宽松邮箱正则（``local@domain.tld``），不追求 RFC 5322 完整覆盖，
    生产环境如需更严格校验请配合 ``@Pattern`` 自定义。
    """
    constraint_name = "Email"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        if value == "":
            return None  # 空串交给 @NotBlank
        if not _EMAIL_RE.match(value):
            return "邮箱格式不合法"
        return None


# ==================== 布尔断言约束 ====================

class AssertTrue(Constraint):
    """``@AssertTrue``：值必须为 True（或真值）。对齐 ``javax.validation.constraints.AssertTrue``。"""
    constraint_name = "AssertTrue"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not bool(value):
            return "必须为 true"
        return None


class AssertFalse(Constraint):
    """``@AssertFalse``：值必须为 False（或假值）。对齐 ``javax.validation.constraints.AssertFalse``。"""
    constraint_name = "AssertFalse"

    def _check(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if bool(value):
            return "必须为 false"
        return None


__all__ = [
    "Constraint",
    "NotNull", "NotBlank", "NotEmpty",
    "Size",
    "Min", "Max",
    "Positive", "PositiveOrZero", "Negative", "NegativeOrZero",
    "Pattern", "Email",
    "AssertTrue", "AssertFalse",
]
