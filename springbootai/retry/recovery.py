"""Recovery method discovery and invocation for exhausted retry operations."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Tuple, get_type_hints

from springbootai.annotations.core import Recover, get_spring_annotations


@dataclass(frozen=True)
class RecoveryMethod:
    method: Callable
    exception_types: Tuple[type, ...]
    receives_exception: bool


def _iter_recover_methods(instance: Any) -> Iterable[RecoveryMethod]:
    for name in dir(instance.__class__):
        descriptor = inspect.getattr_static(instance.__class__, name, None)
        method = descriptor.__func__ if isinstance(descriptor, (staticmethod, classmethod)) else descriptor
        if not inspect.isfunction(method):
            continue
        for annotation in get_spring_annotations(method):
            if not isinstance(annotation, Recover):
                continue
            exception_types = annotation.value or _exception_types_from_signature(method)
            yield RecoveryMethod(
                method=getattr(instance, name),
                exception_types=exception_types or (Exception,),
                receives_exception=True,
            )


def _exception_types_from_signature(method: Callable) -> Optional[Tuple[type, ...]]:
    parameters = list(inspect.signature(method).parameters.values())
    if parameters and parameters[0].name in ('self', 'cls'):
        parameters = parameters[1:]
    if not parameters:
        return None
    try:
        annotation = get_type_hints(method).get(parameters[0].name, parameters[0].annotation)
    except (NameError, TypeError):
        annotation = parameters[0].annotation
    if isinstance(annotation, type) and issubclass(annotation, Exception):
        return (annotation,)
    return None


def _inheritance_distance(exception_type: type, candidate: type) -> int:
    try:
        return exception_type.__mro__.index(candidate)
    except ValueError:
        return 10_000


def _can_bind(
    recovery: RecoveryMethod,
    exception: Exception,
    args: tuple,
    kwargs: dict,
) -> bool:
    call_args = (exception, *args) if recovery.receives_exception else args
    try:
        inspect.signature(recovery.method).bind(*call_args, **kwargs)
        return True
    except TypeError:
        return False


def resolve_recovery_method(
    instance: Any,
    annotation: Any,
    exception: Exception,
    args: tuple,
    kwargs: dict,
) -> Optional[RecoveryMethod]:
    """Resolve explicit legacy recovery or the most specific ``@Recover``."""
    explicit_name = getattr(annotation, 'recover', '')
    if explicit_name:
        explicit = getattr(instance, explicit_name, None)
        if not callable(explicit):
            raise AttributeError(f"Retry recover method '{explicit_name}' was not found")
        declared = inspect.getattr_static(instance.__class__, explicit_name, None)
        declared = declared.__func__ if isinstance(declared, (staticmethod, classmethod)) else declared
        recover_annotations = [
            item for item in get_spring_annotations(declared) if isinstance(item, Recover)
        ]
        exception_types = (
            recover_annotations[0].value or _exception_types_from_signature(declared) or (Exception,)
            if recover_annotations
            else (Exception,)
        )
        recovery = RecoveryMethod(
            explicit,
            exception_types,
            receives_exception=bool(recover_annotations),
        )
        if not isinstance(exception, exception_types):
            return None
        if not _can_bind(recovery, exception, args, kwargs):
            raise TypeError(
                f"Recover method '{explicit_name}' does not accept the failed call arguments"
            )
        return recovery

    candidates = []
    for recovery in _iter_recover_methods(instance):
        matching_types = [
            item for item in recovery.exception_types if isinstance(exception, item)
        ]
        if not matching_types or not _can_bind(recovery, exception, args, kwargs):
            continue
        distance = min(
            _inheritance_distance(type(exception), item) for item in matching_types
        )
        candidates.append((distance, recovery.method.__name__, recovery))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    best_distance = candidates[0][0]
    equally_specific = [
        recovery for distance, _name, recovery in candidates
        if distance == best_distance
    ]
    if len(equally_specific) > 1:
        names = ', '.join(item.method.__name__ for item in equally_specific)
        raise ValueError(
            f"Ambiguous @Recover methods for {type(exception).__name__}: {names}"
        )
    return candidates[0][2]


def invoke_recovery(
    recovery: RecoveryMethod,
    exception: Exception,
    args: tuple,
    kwargs: dict,
):
    call_args = (exception, *args) if recovery.receives_exception else args
    return recovery.method(*call_args, **kwargs)


__all__ = [
    'RecoveryMethod',
    'invoke_recovery',
    'resolve_recovery_method',
]
