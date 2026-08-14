"""SpringBootAI Bean Validation 验证器。

``BeanValidator`` 反射实体类的字段约束（``Constraint`` 描述符或 ``__bean_constraint__``
函数装饰器），对一个对象实例执行全部约束校验，收集 ``ConstraintViolation``。

镜像 ORM ``DdlAutoManager._parse_entity`` 与 Excel ``parse_excel_columns`` 的反射范式：
遍历 ``cls.__mro__`` 的 ``__dict__``，自底向上收集每个字段的约束列表，子类覆盖父类。

用法::

    from spring.validation import BeanValidator, NotBlank, Min

    class User:
        name = NotBlank(message="姓名不能为空")
        age = Min(0)
        def __init__(self, name=None, age=None):
            self.name = name; self.age = age

    violations = BeanValidator.validate(User(name="", age=-1))
    if violations:
        ...  # 处理违规
    BeanValidator.validate_or_raise(User(name="Tom", age=18))  # 通过则不抛错

方法级校验由 ``@BeanValidate`` AOP 切面驱动（注册到 ``comprehensive_aop``），见模块 ``__init__``。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from .constraints import Constraint
from .exceptions import ConstraintViolation, ValidationError


def _collect_constraints(cls: Type) -> Dict[str, List[Constraint]]:
    """反射收集类（含 MRO 父类）每个字段的约束列表。

    镜像 ORM ``_parse_entity`` 与 Excel ``parse_excel_columns`` 的 MRO 遍历：
    自底向上（``reversed(cls.__mro__)``），子类约束覆盖父类同名字段。
    支持四种声明形式：
      1. 类属性 ``Constraint`` 描述符（如 ``name = NotBlank()``）。
      2. 函数上的 ``__bean_constraint__`` 列表（``@NotBlank() def name(self): ...``）。
      3. 描述符内联 ``constraints`` 属性（组合式）：如 ``Column(constraints=[NotBlank()])``、
         ``ExcelProperty(constraints=[NotBlank()])``、``CsvProperty(constraints=[NotBlank()])``。
      4. 函数上通过 ``@column`` / ``@ExcelProperty`` / ``@CsvProperty`` 装饰器挂载的描述符
         本身所带的 ``constraints`` 列表（形式 2 + 形式 3 叠加）。
    """
    collected: Dict[str, List[Constraint]] = {}

    for base in reversed(cls.__mro__):
        if base is object:
            continue
        for attr_name, value in vars(base).items():
            if attr_name.startswith("__"):
                continue
            constraints: List[Constraint] = []
            # 形式1：类属性 Constraint 描述符实例
            if isinstance(value, Constraint):
                if not value.attr_name:
                    value.attr_name = attr_name
                constraints.append(value)
            # 形式3：类属性是外模块描述符（Column/ExcelProperty/CsvProperty/Id/...），
            #        通过 constraints=[] 参数内联约束
            elif hasattr(value, "constraints") and isinstance(getattr(value, "constraints", None), list):
                for c in value.constraints:
                    if isinstance(c, Constraint):
                        if not c.attr_name:
                            c.attr_name = attr_name
                        constraints.append(c)
            # 形式2+4：函数装饰器
            if hasattr(value, "__bean_constraint__"):
                clist = getattr(value, "__bean_constraint__")
                if isinstance(clist, list):
                    for c in clist:
                        if isinstance(c, Constraint) and not c.attr_name:
                            c.attr_name = attr_name
                        constraints.append(c)
            # 形式4补充：函数装饰器形式的 @column/@ExcelProperty/@CsvProperty
            # 把描述符挂在 __column__/__excel_property__/__csv_property__ 上
            for tag in ("__column__", "__excel_property__", "__csv_property__"):
                if hasattr(value, tag):
                    desc = getattr(value, tag)
                    desc_constraints = getattr(desc, "constraints", None)
                    if isinstance(desc_constraints, list):
                        for c in desc_constraints:
                            if isinstance(c, Constraint):
                                if not c.attr_name:
                                    c.attr_name = attr_name
                                constraints.append(c)
            if constraints:
                # 子类覆盖父类同名字段（与 ORM/Excel 解析一致）
                collected[attr_name] = constraints
    return collected


def _get_field_value(obj: Any, attr_name: str) -> Any:
    """从对象实例取字段值：优先 ``getattr``，失败则 None。"""
    try:
        return getattr(obj, attr_name)
    except AttributeError:
        return None


class BeanValidator:
    """Bean Validation 校验器（静态方法风格，无状态，可直接调用）。

    设计为无状态工具类，对齐 Jakarta ``Validator`` 接口的 ``validate`` 语义，
    但简化为静态方法，避免在未接入 IoC 容器的场景下还需手动构造实例。
    """

    @staticmethod
    def get_constraints(cls: Type) -> Dict[str, List[Constraint]]:
        """返回类上声明的字段约束映射（公开 API，便于调试/报告）。"""
        return _collect_constraints(cls)

    @staticmethod
    def validate(obj: Any, groups: Optional[List[type]] = None) -> List[ConstraintViolation]:
        """校验对象实例，返回全部约束违反列表（通过则返回空列表）。

        Args:
            obj:    待校验对象。若是类，则按无实例处理（仅字段无值，仅 NotNull 类会触发）。
            groups: 校验分组（对齐 Jakarta Validation groups）。当前实现：约束未声明 groups
                    时始终执行；声明了 groups 时仅当传入 groups 命中才执行。
                    （分组功能为兼容预留，约束默认不限定分组。）
        """
        if obj is None:
            return []
        cls = obj if isinstance(obj, type) else type(obj)
        constraints_map = _collect_constraints(cls)

        violations: List[ConstraintViolation] = []
        for attr_name, constraints in constraints_map.items():
            value = None if isinstance(obj, type) else _get_field_value(obj, attr_name)
            for constraint in constraints:
                # 分组过滤：约束可选声明 groups
                cgroups = getattr(constraint, "groups", None) or []
                if cgroups:
                    if not groups or not any(g in cgroups for g in groups):
                        continue
                msg = constraint.validate(value)
                if msg is not None:
                    violations.append(ConstraintViolation(
                        attr_name=attr_name,
                        value=value,
                        constraint=constraint,
                        message=msg,
                    ))
        return violations

    @staticmethod
    def validate_or_raise(obj: Any, groups: Optional[List[type]] = None) -> None:
        """校验对象实例，存在违反则抛出 ``ValidationError``；通过则无返回。"""
        violations = BeanValidator.validate(obj, groups=groups)
        if violations:
            raise ValidationError(violations)

    @staticmethod
    def is_valid(obj: Any, groups: Optional[List[type]] = None) -> bool:
        """便捷判断：是否通过全部约束。"""
        return not BeanValidator.validate(obj, groups=groups)


__all__ = ["BeanValidator", "_collect_constraints"]
