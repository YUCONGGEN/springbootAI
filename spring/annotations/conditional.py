"""SpringPy 条件装配注解 —— 对齐 Spring Boot 的条件化 Bean 注册。

本模块在既有 ``@Profile``（``spring.annotations.core.Profile``）基础上补齐 Spring Boot
条件装配家族，复用同一 ``SpringAnnotation`` 元数据范式：

- ``@Conditional``：自定义条件（传入 ``Condition`` 子类实例或 ``callable(context)->bool``）。
- ``@ConditionalOnProperty``：配置属性匹配时装配。
- ``@ConditionalOnBean``：容器中已存在指定 Bean 时装配。
- ``@ConditionalOnMissingBean``：容器中不存在指定 Bean 时装配。
- ``@ConditionalOnClass``：类路径中存在指定类时装配。

每个注解实现 ``matches(application_context) -> bool``，由
``ApplicationContext._matches_conditions`` 在 ``_register_component`` 阶段统一求值
（与既有 ``_matches_active_profile`` 并列）。

与 Spring 的一致点：
- 条件求值时机：组件扫描注册阶段（BeanDefinition 注册前）。
- ``@ConditionalOnProperty`` 的 ``having_value`` / ``match_if_missing`` 语义对齐 Spring。
- ``@Conditional`` 支持传入 ``Condition`` 类（实现 ``matches(context)``）。

与 Spring 的差异（已标注）：
- Spring 条件求值访问 ``ConditionContext`` + ``AnnotatedTypeMetadata``；本框架传入
  ``ApplicationContext`` 本身（含 ``config_loader`` / ``bean_factory``），简化但等价。
- ``@ConditionalOnBean`` / ``@ConditionalOnMissingBean`` 检查的是**已注册的
  BeanDefinition 名字/类型**，而非已实例化的 Bean（与 Spring 一致），但受扫描顺序影响：
  若依赖的 Bean 在当前组件之后扫描，则条件求值为假。生产中应把被依赖 Bean 放在更早的包
  或用 ``@Configuration`` + ``@Bean`` 显式声明（这是已知限制，对齐 Spring 的注册顺序敏感性）。
- 不支持 SpEL；``having_value`` 为字符串等值匹配。
"""
from __future__ import annotations

import importlib
from typing import Any, Optional, Type, Union

from spring.annotations.core import SpringAnnotation


# 条件注解类型标识，便于 _matches_conditions 用 _annotation_type 批量识别
_CONDITIONAL_TYPE = "conditional"


class Conditional(SpringAnnotation):
    """``@Conditional``：自定义条件装配（对齐 Spring ``@Conditional``）。

    Args:
        condition: 条件。可为：
            - ``Condition`` 子类**类型**（会实例化后调用 ``matches(context)``）；
            - ``Condition`` 子类**实例**（直接调用 ``matches(context)``）；
            - ``callable(context) -> bool``（直接调用）。
    """

    _annotation_type = _CONDITIONAL_TYPE

    def __new__(cls, *args, **kwargs):
        # ``Conditional`` 的第一个位置参数是 condition（类或可调用），并非被装饰目标。
        # 跳过 ``SpringAnnotation.__new__`` 的"无括号装饰器"优化，避免把 condition 误判
        # 为装饰目标（否则 ``Conditional(MyCond)`` 会被当成 ``@Conditional`` 作用于 MyCond）。
        return super().__new__(cls)

    def __init__(self, condition: Union[Type, Any, callable]):
        super().__init__(condition=condition)

    def matches(self, ctx: Any) -> bool:
        cond = self.condition
        # 传入的是类 -> 实例化
        if isinstance(cond, type):
            try:
                inst = cond()
            except Exception:
                return False
        else:
            inst = cond
        if hasattr(inst, "matches") and callable(inst.matches):
            try:
                return bool(inst.matches(ctx))
            except Exception:
                return False
        if callable(inst):
            try:
                return bool(inst(ctx))
            except Exception:
                return False
        return True


class ConditionalOnProperty(SpringAnnotation):
    """``@ConditionalOnProperty``：配置属性匹配时装配（对齐 Spring Boot）。

    Args:
        name:             配置键（如 ``"redis.enabled"``）。
        having_value:     期望值（字符串等值匹配）。为 None 时只要键存在（非 None）即匹配。
        match_if_missing: 配置键缺失时是否视为匹配。默认 False。
    """

    _annotation_type = _CONDITIONAL_TYPE

    def __init__(
        self,
        name: str,
        having_value: Optional[str] = None,
        match_if_missing: bool = False,
    ):
        super().__init__(name=name, having_value=having_value, match_if_missing=match_if_missing)

    def matches(self, ctx: Any) -> bool:
        loader = getattr(ctx, "config_loader", None)
        try:
            value = loader.get(self.name) if loader is not None else None
        except Exception:
            value = None
        if value is None:
            return bool(self.match_if_missing)
        if self.having_value is None:
            return True
        return str(value) == str(self.having_value)


class ConditionalOnBean(SpringAnnotation):
    """``@ConditionalOnBean``：容器中已存在指定 Bean 时装配（对齐 Spring Boot）。

    Args:
        bean_name: Bean 名称。
        bean_type: Bean 类型（按类型匹配，会查 BeanDefinition 的 bean_class）。
        value:     bean_name 的别名（对齐 Spring 参数风格）。
    """

    _annotation_type = _CONDITIONAL_TYPE

    def __init__(
        self,
        bean_name: Optional[str] = None,
        bean_type: Optional[Type] = None,
        value: Optional[str] = None,
    ):
        if value is not None and bean_name is None:
            bean_name = value
        super().__init__(bean_name=bean_name, bean_type=bean_type, value=value)

    def matches(self, ctx: Any) -> bool:
        bf = getattr(ctx, "bean_factory", None)
        if bf is None:
            return False
        try:
            names = bf.get_bean_names()
        except Exception:
            return False
        if self.bean_name:
            if self.bean_name in names:
                return True
        if self.bean_type is not None:
            # 按类型匹配：遍历 BeanDefinition 的 bean_class
            try:
                for name in names:
                    defn = bf._bean_definitions.get(name)
                    if defn is not None and getattr(defn, "bean_class", None) is self.bean_type:
                        return True
                    if defn is not None and isinstance(getattr(defn, "bean_class", None), type):
                        if issubclass(defn.bean_class, self.bean_type):
                            return True
            except Exception:
                return False
        return False


class ConditionalOnMissingBean(SpringAnnotation):
    """``@ConditionalOnMissingBean``：容器中不存在指定 Bean 时装配（对齐 Spring Boot）。

    参数同 ``@ConditionalOnBean``。常用于提供默认实现：用户未自定义时装配默认 Bean。
    """

    _annotation_type = _CONDITIONAL_TYPE

    def __init__(
        self,
        bean_name: Optional[str] = None,
        bean_type: Optional[Type] = None,
        value: Optional[str] = None,
    ):
        if value is not None and bean_name is None:
            bean_name = value
        super().__init__(bean_name=bean_name, bean_type=bean_type, value=value)

    def matches(self, ctx: Any) -> bool:
        on_bean = ConditionalOnBean(
            bean_name=self.bean_name, bean_type=self.bean_type, value=self.value)
        return not on_bean.matches(ctx)


class ConditionalOnClass(SpringAnnotation):
    """``@ConditionalOnClass``：类路径中存在指定类时装配（对齐 Spring Boot）。

    Args:
        name:  类的全限定名（``"module.Class"``）或模块名（``"module"``）。
        value: 类类型本身（直接判断，等价于 ``isinstance`` 可导入）。
    """

    _annotation_type = _CONDITIONAL_TYPE

    def __init__(
        self,
        name: Optional[str] = None,
        value: Optional[Type] = None,
    ):
        super().__init__(name=name, value=value)

    def matches(self, ctx: Any) -> bool:
        # 直接传类类型
        if self.value is not None:
            return isinstance(self.value, type)
        if not self.name:
            return False
        target = self.name
        # 支持 "module.Sub.Class" 形式：从左到右尝试 import
        parts = target.split(".")
        # 先尝试整体作为模块
        try:
            importlib.import_module(target)
            return True
        except ImportError:
            pass
        # 尝试 module + attr
        for i in range(len(parts) - 1, 0, -1):
            mod_path = ".".join(parts[:i])
            attr_path = parts[i:]
            try:
                mod = importlib.import_module(mod_path)
            except ImportError:
                continue
            obj = mod
            ok = True
            for attr in attr_path:
                if not hasattr(obj, attr):
                    ok = False
                    break
                obj = getattr(obj, attr)
            if ok:
                return True
        return False


# 供 _matches_conditions 识别的全部条件注解类型
CONDITION_ANNOTATIONS = (
    Conditional, ConditionalOnProperty, ConditionalOnBean,
    ConditionalOnMissingBean, ConditionalOnClass,
)


def all_conditions_match(component_class: type, ctx: Any) -> bool:
    """求类上所有条件注解的合取（AND）。任一条件为假则返回 False。

    供 ``ApplicationContext._matches_conditions`` 调用，集中条件求值逻辑。
    """
    from spring.annotations.core import get_spring_annotations
    for ann in get_spring_annotations(component_class):
        if isinstance(ann, CONDITION_ANNOTATIONS):
            try:
                if not ann.matches(ctx):
                    return False
            except Exception:
                return False
    return True


__all__ = [
    "Conditional",
    "ConditionalOnProperty",
    "ConditionalOnBean",
    "ConditionalOnMissingBean",
    "ConditionalOnClass",
    "CONDITION_ANNOTATIONS",
    "all_conditions_match",
]
