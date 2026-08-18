"""SpringBootAI Bean Validation 方法级 AOP 注解 ``@BeanValidate``。

把字段约束校验（``springbootai.validation.validator.BeanValidator``）接入既有 AOP 分发链路：
``@BeanValidate`` 作为方法级 ``SpringAnnotation``，在 ``comprehensive_aop.ANNOTATION_DECORATORS``
中注册装饰器，受管 Bean 方法被调用前自动校验指定参数对象。

对齐 Jakarta Bean Validation 的方法级校验（``@Validated`` + 约束注解），但本模块只校验
**参数对象整体**（即对参数值调用 ``BeanValidator.validate_or_raise``），不校验单个标量参数。
单个标量参数校验仍由既有 ``@Validate`` 切面承担（``comprehensive_aop.validate_decorator``）。

用法::

    from springbootai.validation import BeanValidate, NotBlank, BeanValidator
    from springbootai.annotations import Service

    class UserDto:
        name = NotBlank()
        def __init__(self, name=None): self.name = name

    @Service
    class UserService:
        @BeanValidate("user")          # 校验名为 user 的参数
        def create(self, user: UserDto):
            ...

        @BeanValidate                   # 不传参：自动校验所有"类型含约束"的参数
        def update(self, user: UserDto, flag: bool):
            ...

与 Java 的差异：Java 方法级校验需配合 ``MethodValidationPostProcessor`` 代理，且支持
``@NotNull`` 直接标注在方法参数上；本模块不解析参数上的约束，仅对参数对象做整体校验。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, List, Optional, Union

from springbootai.annotations.core import SpringAnnotation

from .validator import BeanValidator
from .exceptions import ValidationError


class BeanValidate(SpringAnnotation):
    """方法级校验注解：调用前自动用 ``BeanValidator`` 校验指定参数对象。

    Args:
        value: 指定要校验的参数名（str）或参数名列表（List[str]）。
               不传时校验**所有**类型声明含字段约束的参数（自动探测）。
        groups: 校验分组列表（透传给 ``BeanValidator.validate``）。
    """

    _annotation_type = "aop"

    def __init__(
        self,
        value: Union[str, List[str], None] = None,
        groups: Optional[List[type]] = None,
    ):
        if isinstance(value, str):
            params: List[str] = [value]
        elif value is None:
            params = []
        else:
            params = list(value)
        super().__init__(value=params, groups=groups or [])


def _param_has_constraints(cls: Any) -> bool:
    """参数类型是否声明了字段约束（用于 ``@BeanValidate()`` 自动探测）。"""
    if not isinstance(cls, type):
        return False
    try:
        return bool(BeanValidator.get_constraints(cls))
    except Exception:
        return False


def bean_validate_decorator(annotation: BeanValidate):
    """``@BeanValidate`` 的 AOP 装饰器工厂（注册到 ``comprehensive_aop.ANNOTATION_DECORATORS``）。

    在方法调用前，对指定参数对象执行 ``BeanValidator.validate_or_raise``；
    违反约束时抛出 ``ValidationError``，阻止方法执行。
    """
    target_params: List[str] = list(annotation.value)
    groups = list(annotation.groups)

    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)

        def _resolve_targets(args, kwargs) -> List[str]:
            """决定本次调用要校验的参数名列表。"""
            if target_params:
                # 显式指定的参数名
                return [p for p in target_params]
            # 自动探测：所有类型声明含约束的参数
            targets: List[str] = []
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                annotation_cls = param.annotation
                if annotation_cls is inspect.Parameter.empty:
                    continue
                if _param_has_constraints(annotation_cls):
                    targets.append(pname)
            return targets

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                bound = sig.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                for pname in _resolve_targets(args, kwargs):
                    if pname not in bound.arguments:
                        continue
                    val = bound.arguments[pname]
                    if val is None:
                        continue
                    BeanValidator.validate_or_raise(val, groups=groups)
                return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            for pname in _resolve_targets(args, kwargs):
                if pname not in bound.arguments:
                    continue
                val = bound.arguments[pname]
                if val is None:
                    continue
                BeanValidator.validate_or_raise(val, groups=groups)
            return func(*args, **kwargs)
        return wrapper

    return decorator


__all__ = ["BeanValidate", "bean_validate_decorator", "ValidationError"]
