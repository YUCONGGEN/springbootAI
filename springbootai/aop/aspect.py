"""Spring-style declarative aspect support for managed Beans."""

from __future__ import annotations

import fnmatch
import functools
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from springbootai.annotations.core import (
    After,
    AfterReturning,
    AfterThrowing,
    Around,
    Aspect,
    Before,
    Pointcut,
    get_spring_annotations,
)


_ADVICE_TYPES = (Before, After, Around, AfterReturning, AfterThrowing)
_POINTCUT_REFERENCE = re.compile(r"^(?:(?P<owner>[A-Za-z_]\w*)\.)?(?P<name>[A-Za-z_]\w*)\(\)$")


class JoinPoint:
    """Read-only context exposed to advice methods."""

    def __init__(
        self,
        target: Any,
        method: Callable,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        bean_name: str = "",
    ):
        self.target = target
        self.method = method
        self.args = tuple(args)
        self.kwargs = dict(kwargs)
        self.bean_name = bean_name

    @property
    def method_name(self) -> str:
        return self.method.__name__

    @property
    def signature(self) -> str:
        owner = self.target.__class__
        return f"{owner.__module__}.{owner.__qualname__}.{self.method_name}"


class ProceedingJoinPoint(JoinPoint):
    """Join point that lets ``@Around`` advice continue the invocation."""

    def __init__(self, *args, proceed: Callable, **kwargs):
        super().__init__(*args, **kwargs)
        self._proceed = proceed

    def proceed(self, *args, **kwargs):
        if not args and not kwargs:
            return self._proceed()
        return self._proceed(*args, **kwargs)


@dataclass(frozen=True)
class _AdviceDefinition:
    bean_name: str
    aspect_class: type
    method_name: str
    annotation: Any
    expression: str
    pointcuts: Dict[str, str]


def is_aspect_class(bean_class: type) -> bool:
    return any(isinstance(annotation, Aspect) for annotation in get_spring_annotations(bean_class))


def _iter_declared_methods(bean_class: type) -> Iterable[tuple[str, Callable]]:
    """Yield methods in source declaration order, including inherited advice."""
    seen = set()
    for owner in bean_class.__mro__[:-1]:
        for name, descriptor in vars(owner).items():
            if name in seen:
                continue
            method = descriptor.__func__ if isinstance(descriptor, (staticmethod, classmethod)) else descriptor
            if inspect.isfunction(method):
                seen.add(name)
                yield name, method


def collect_advice_definitions(bean_factory: Any) -> List[_AdviceDefinition]:
    definitions: List[_AdviceDefinition] = []
    for bean_name in bean_factory.get_bean_names():
        definition = bean_factory.get_bean_definition(bean_name)
        aspect_class = getattr(definition, "bean_class", None)
        if not isinstance(aspect_class, type) or not is_aspect_class(aspect_class):
            continue

        pointcuts: Dict[str, str] = {}
        methods = list(_iter_declared_methods(aspect_class))
        for method_name, method in methods:
            for annotation in get_spring_annotations(method):
                if isinstance(annotation, Pointcut):
                    pointcuts[method_name] = annotation.value

        for method_name, method in methods:
            for annotation in get_spring_annotations(method):
                if isinstance(annotation, _ADVICE_TYPES):
                    definitions.append(
                        _AdviceDefinition(
                            bean_name=bean_name,
                            aspect_class=aspect_class,
                            method_name=method_name,
                            annotation=annotation,
                            expression=annotation.value,
                            pointcuts=pointcuts,
                        )
                    )
    return definitions


def _strip_outer_parentheses(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(expression):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(expression) - 1:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        expression = expression[1:-1].strip()
    return expression


def _split_top_level(expression: str, operator: str) -> Optional[List[str]]:
    depth = 0
    parts: List[str] = []
    start = 0
    index = 0
    while index < len(expression):
        char = expression[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and expression.startswith(operator, index):
            parts.append(expression[start:index].strip())
            start = index + len(operator)
            index += len(operator) - 1
        index += 1
    if not parts:
        return None
    parts.append(expression[start:].strip())
    return parts


def _matches_pattern(value: str, pattern: str) -> bool:
    normalized = pattern.strip().replace("..", "*")
    return fnmatch.fnmatchcase(value, normalized)


def _execution_pattern(expression: str) -> str:
    inner = expression[len("execution("):-1].strip()
    if not inner:
        raise ValueError("execution pointcut must include a method pattern")
    signature_start = inner.find("(")
    method_part = inner[:signature_start] if signature_start >= 0 else inner
    parts = method_part.split()
    if not parts or not parts[-1]:
        raise ValueError("execution pointcut must include a method pattern")
    return parts[-1]


def _matches_atom(
    expression: str,
    *,
    bean_name: str,
    target_class: type,
    method: Callable,
    pointcuts: Dict[str, str],
    resolving: Optional[set[str]] = None,
) -> bool:
    reference = _POINTCUT_REFERENCE.match(expression)
    if reference:
        name = reference.group("name")
        if name not in pointcuts:
            raise ValueError(f"Unknown pointcut reference: {expression}")
        resolving = set(resolving or ())
        if name in resolving:
            raise ValueError(f"Circular pointcut reference: {name}")
        resolving.add(name)
        return _matches_expression(
            pointcuts[name],
            bean_name=bean_name,
            target_class=target_class,
            method=method,
            pointcuts=pointcuts,
            resolving=resolving,
        )

    method_path = f"{target_class.__module__}.{target_class.__qualname__}.{method.__name__}"
    class_path = f"{target_class.__module__}.{target_class.__qualname__}"
    if expression.startswith("execution(") and expression.endswith(")"):
        return _matches_pattern(method_path, _execution_pattern(expression))
    if expression.startswith("within(") and expression.endswith(")"):
        pattern = expression[len("within("):-1].strip()
        if not pattern:
            raise ValueError("within pointcut must include a class pattern")
        return _matches_pattern(class_path, pattern)
    if expression.startswith("bean(") and expression.endswith(")"):
        pattern = expression[len("bean("):-1].strip()
        if not pattern:
            raise ValueError("bean pointcut must include a Bean name pattern")
        return _matches_pattern(bean_name, pattern)
    if expression.startswith("@annotation(") and expression.endswith(")"):
        expected = expression[len("@annotation("):-1].strip()
        if not expected:
            raise ValueError("@annotation pointcut must include an annotation name")
        return any(
            type(annotation).__name__ == expected
            or f"{type(annotation).__module__}.{type(annotation).__name__}" == expected
            for annotation in get_spring_annotations(method)
        )
    raise ValueError(f"Unsupported pointcut expression: {expression}")


def _matches_expression(
    expression: str,
    *,
    bean_name: str,
    target_class: type,
    method: Callable,
    pointcuts: Dict[str, str],
    resolving: Optional[set[str]] = None,
) -> bool:
    expression = _strip_outer_parentheses(expression)
    for operators, predicate in ((('||', ' or '), any), (('&&', ' and '), all)):
        for operator in operators:
            parts = _split_top_level(expression, operator)
            if parts:
                # Evaluate every branch so malformed pointcuts fail during Bean
                # proxy creation instead of being hidden by boolean short-circuiting.
                matches = [
                    _matches_expression(
                        part,
                        bean_name=bean_name,
                        target_class=target_class,
                        method=method,
                        pointcuts=pointcuts,
                        resolving=resolving,
                    )
                    for part in parts
                ]
                return predicate(matches)
    if expression.startswith("!"):
        return not _matches_expression(
            expression[1:],
            bean_name=bean_name,
            target_class=target_class,
            method=method,
            pointcuts=pointcuts,
            resolving=resolving,
        )
    if expression.startswith("not "):
        return not _matches_expression(
            expression[4:],
            bean_name=bean_name,
            target_class=target_class,
            method=method,
            pointcuts=pointcuts,
            resolving=resolving,
        )
    return _matches_atom(
        expression,
        bean_name=bean_name,
        target_class=target_class,
        method=method,
        pointcuts=pointcuts,
        resolving=resolving,
    )


def find_matching_advice(
    bean_factory: Any,
    bean_name: str,
    target_class: type,
    method: Callable,
) -> List[_AdviceDefinition]:
    if is_aspect_class(target_class):
        return []
    matches = []
    for advice in collect_advice_definitions(bean_factory):
        if _matches_expression(
            advice.expression,
            bean_name=bean_name,
            target_class=target_class,
            method=method,
            pointcuts=advice.pointcuts,
        ):
            matches.append(advice)
    return matches


def _invoke_advice(
    bean_factory: Any,
    advice: _AdviceDefinition,
    join_point: JoinPoint,
    *,
    result: Any = inspect.Signature.empty,
    exception: Any = inspect.Signature.empty,
):
    aspect = bean_factory.get_bean(advice.bean_name)
    method = getattr(aspect, advice.method_name)
    available = {
        "join_point": join_point,
        "joinpoint": join_point,
        "jp": join_point,
        "pjp": join_point,
        "proceeding_join_point": join_point,
        "proceedingjoinpoint": join_point,
    }
    if result is not inspect.Signature.empty:
        available.update({"result": result, "return_value": result})
        available[getattr(advice.annotation, "returning", "result")] = result
    if exception is not inspect.Signature.empty:
        available.update({"exception": exception, "error": exception, "throwable": exception})
        available[getattr(advice.annotation, "throwing", "exception")] = exception

    positional = []
    keyword = {}
    bound_names = set()
    for parameter in inspect.signature(method).parameters.values():
        normalized = parameter.name.lower()
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            keyword.update(
                (name, value)
                for name, value in available.items()
                if name not in bound_names
            )
            continue
        if parameter.name in available:
            value = available[parameter.name]
        elif normalized in available:
            value = available[normalized]
        elif parameter.annotation in (JoinPoint, ProceedingJoinPoint):
            value = join_point
        elif parameter.default is not inspect.Signature.empty:
            continue
        else:
            raise TypeError(
                f"Cannot bind advice parameter '{parameter.name}' on "
                f"{advice.aspect_class.__name__}.{advice.method_name}"
            )
        if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            keyword[parameter.name] = value
        else:
            positional.append(value)
        bound_names.add(parameter.name)
    return method(*positional, **keyword)


def apply_aspects(
    bean_factory: Any,
    target: Any,
    declared_method: Callable,
    wrapped_method: Callable,
    bean_name: str,
) -> Callable:
    """Apply all matching aspect advice to one unbound managed-Bean method."""
    advice = find_matching_advice(
        bean_factory, bean_name, target.__class__, declared_method
    )
    if not advice:
        return wrapped_method

    before = [item for item in advice if type(item.annotation) is Before]
    after = [item for item in advice if type(item.annotation) is After]
    around = [item for item in advice if type(item.annotation) is Around]
    after_returning = [
        item for item in advice if type(item.annotation) is AfterReturning
    ]
    after_throwing = [
        item for item in advice if type(item.annotation) is AfterThrowing
    ]

    def business_args(call_args):
        if call_args and call_args[0] is target:
            return call_args[1:]
        return call_args

    def invoke_target(call_args, call_kwargs):
        return wrapped_method(*call_args, **call_kwargs)

    def around_chain(call_args, call_kwargs, index=0):
        if index >= len(around):
            return invoke_target(call_args, call_kwargs)

        def proceed(*replacement_args, **replacement_kwargs):
            if replacement_args or replacement_kwargs:
                next_args = tuple(replacement_args)
                if not next_args or next_args[0] is not target:
                    next_args = (target,) + next_args
                return around_chain(next_args, replacement_kwargs, index + 1)
            return around_chain(call_args, call_kwargs, index + 1)

        join_point = ProceedingJoinPoint(
            target,
            declared_method,
            business_args(call_args),
            call_kwargs,
            bean_name,
            proceed=proceed,
        )
        return _invoke_advice(bean_factory, around[index], join_point)

    if inspect.iscoroutinefunction(wrapped_method) or any(
        inspect.iscoroutinefunction(getattr(item.aspect_class, item.method_name)) for item in advice
    ):
        @functools.wraps(wrapped_method)
        async def async_wrapper(*args, **kwargs):
            join_point = JoinPoint(
                target, declared_method, business_args(args), kwargs, bean_name
            )
            for item in before:
                advice_result = _invoke_advice(bean_factory, item, join_point)
                if inspect.isawaitable(advice_result):
                    await advice_result
            try:
                result = around_chain(args, kwargs)
                if inspect.isawaitable(result):
                    result = await result
                for item in after_returning:
                    advice_result = _invoke_advice(
                        bean_factory, item, join_point, result=result
                    )
                    if inspect.isawaitable(advice_result):
                        await advice_result
                return result
            except Exception as exc:
                for item in after_throwing:
                    advice_result = _invoke_advice(
                        bean_factory, item, join_point, exception=exc
                    )
                    if inspect.isawaitable(advice_result):
                        await advice_result
                raise
            finally:
                for item in after:
                    advice_result = _invoke_advice(bean_factory, item, join_point)
                    if inspect.isawaitable(advice_result):
                        await advice_result

        return async_wrapper

    @functools.wraps(wrapped_method)
    def wrapper(*args, **kwargs):
        join_point = JoinPoint(
            target, declared_method, business_args(args), kwargs, bean_name
        )
        for item in before:
            advice_result = _invoke_advice(bean_factory, item, join_point)
            if inspect.isawaitable(advice_result):
                raise TypeError("Synchronous advice returned an awaitable")
        try:
            result = around_chain(args, kwargs)
            if inspect.isawaitable(result):
                raise TypeError("Synchronous advice returned an awaitable")
            for item in after_returning:
                advice_result = _invoke_advice(
                    bean_factory, item, join_point, result=result
                )
                if inspect.isawaitable(advice_result):
                    raise TypeError("Synchronous advice returned an awaitable")
            return result
        except Exception as exc:
            for item in after_throwing:
                advice_result = _invoke_advice(
                    bean_factory, item, join_point, exception=exc
                )
                if inspect.isawaitable(advice_result):
                    raise TypeError("Synchronous advice returned an awaitable")
            raise
        finally:
            for item in after:
                advice_result = _invoke_advice(bean_factory, item, join_point)
                if inspect.isawaitable(advice_result):
                    raise TypeError("Synchronous advice returned an awaitable")

    return wrapper


__all__ = [
    'JoinPoint',
    'ProceedingJoinPoint',
    'apply_aspects',
    'collect_advice_definitions',
    'find_matching_advice',
    'is_aspect_class',
]
