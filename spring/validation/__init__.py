"""SpringBootAI Bean Validation 模块 —— 字段约束注解 + 验证器 + 方法级 AOP。

对齐 Jakarta Bean Validation（Hibernate Validator）的核心能力：
- 字段级约束（``@NotNull``/``@NotBlank``/``@Size``/``@Min``/``@Max``/``@Pattern``/``@Email`` 等）
  作为字段描述符，复用 ORM ``Column`` / Excel ``ExcelProperty`` 元数据范式。
- ``BeanValidator`` 反射收集约束并校验对象实例，返回 ``ConstraintViolation`` 列表。
- ``@BeanValidate`` 方法级 AOP 注解，接入既有 ``comprehensive_aop`` 分发链路，
  受管 Bean 方法调用前自动校验参数对象。

模块组成：
- constraints: 字段约束注解（``Constraint`` 基类 + 14 个内置约束）
- validator:   ``BeanValidator`` 反射校验器
- aop:         ``@BeanValidate`` 方法级注解 + AOP 装饰器
- exceptions:  ``ValidationError`` / ``ConstraintViolation``

设计原则：**复用项目既有范式，不重复造轮子**。约束描述符、反射收集、AOP 注册全部对齐
既有 ORM/Excel/综合 AOP 实现，未引入任何 Spring 风格第三方库。

与 Java 的差异（已标注）：
- 仅支持字段级约束（Java 还支持方法参数级/返回值级标量约束）；方法级通过 ``@BeanValidate``
  对参数对象整体校验实现。
- 校验器为无状态静态方法风格，不依赖 IoC 容器即可独立使用。
"""
from .exceptions import ConstraintViolation, ValidationError
from .constraints import (
    Constraint,
    NotNull, NotBlank, NotEmpty,
    Size,
    Min, Max,
    Positive, PositiveOrZero, Negative, NegativeOrZero,
    Pattern, Email,
    AssertTrue, AssertFalse,
)
from .validator import BeanValidator
from .aop import BeanValidate, bean_validate_decorator

__version__ = "1.0.0"

__all__ = [
    # 异常
    "ConstraintViolation", "ValidationError",
    # 约束
    "Constraint",
    "NotNull", "NotBlank", "NotEmpty",
    "Size",
    "Min", "Max",
    "Positive", "PositiveOrZero", "Negative", "NegativeOrZero",
    "Pattern", "Email",
    "AssertTrue", "AssertFalse",
    # 验证器
    "BeanValidator",
    # 方法级 AOP
    "BeanValidate", "bean_validate_decorator",
    "__version__",
]
