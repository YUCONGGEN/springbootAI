"""Lombok-style annotations for concise Python domain models.

The decorators in this module deliberately generate ordinary Python methods.
That keeps models easy to debug while removing repetitive ``__init__``,
``__repr__`` and accessor boilerplate from framework entities.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, get_origin, ClassVar

from .core import SpringAnnotation

__all__ = ["Data", "Get", "Set", "ToString"]


def _normalize_fields(fields: Optional[Iterable[str] | str]) -> Optional[tuple[str, ...]]:
    """Return a stable field selection, or ``None`` for all declared fields."""
    if fields is None:
        return None
    if isinstance(fields, str):
        fields = (fields,)
    try:
        normalized = tuple(dict.fromkeys(str(field) for field in fields))
    except TypeError as exc:
        raise TypeError("fields must be a field name or an iterable of field names") from exc
    if any(not field or field.startswith("_") for field in normalized):
        raise ValueError("fields must contain non-private field names")
    return normalized


def _declared_fields(cls: type) -> tuple[str, ...]:
    """Collect public instance fields from annotations and ORM descriptors.

    ORM fields such as ``Id()`` and ``Required()`` have both annotations and
    descriptor defaults in normal use.  Looking at both sources also makes the
    decorators useful for small standalone models that only declare defaults.
    """
    fields: dict[str, None] = {}
    for base in reversed(cls.__mro__):
        if base is object:
            continue
        annotations = getattr(base, "__dict__", {}).get("__annotations__", {})
        for name, annotation in annotations.items():
            if name.startswith("_") or get_origin(annotation) is ClassVar:
                continue
            fields[name] = None
        for name, value in getattr(base, "__dict__", {}).items():
            if name.startswith("_") or name in fields:
                continue
            if value.__class__.__module__ == "springbootai.orm.ddl_auto" and hasattr(value, "default"):
                fields[name] = None
    return tuple(fields)


def _selected_fields(cls: type, requested: Optional[tuple[str, ...]]) -> tuple[str, ...]:
    declared = _declared_fields(cls)
    if requested is None:
        return declared
    unknown = [name for name in requested if name not in declared]
    if unknown:
        raise AttributeError(f"{cls.__name__} has no declared field(s): {', '.join(unknown)}")
    return requested


def _method_is_custom(cls: type, name: str) -> bool:
    """Whether *name* is explicitly supplied by this class or a parent class."""
    for base in cls.__mro__:
        if name in base.__dict__:
            return base is not object and not getattr(
                base.__dict__[name], "__springbootai_generated__", False
            )
    return False


def _field_default(cls: type, name: str) -> Any:
    """Read a plain or descriptor default without evaluating framework metadata."""
    for base in cls.__mro__:
        if name not in base.__dict__:
            continue
        value = base.__dict__[name]
        if hasattr(value, "default"):
            return value.default
        return value
    return None


def _attach_annotation(target: type, annotation: SpringAnnotation) -> None:
    if "__spring_annotations__" not in target.__dict__:
        target.__spring_annotations__ = []
    target.__spring_annotations__.append(annotation)
    annotation._original_class = target


class _ModelAnnotation(SpringAnnotation):
    """Decorator base that supports both ``@Annotation`` and ``@Annotation()``.

    ``SpringAnnotation.__new__`` attaches metadata for normal annotations but
    returns the decorated class before an overriding ``__call__`` can generate
    methods.  Model annotations need that generation step, so they manage the
    two decorator forms directly and retain the same metadata contract.
    """

    def __new__(cls, *args: Any, **kwargs: Any):
        if args and isinstance(args[0], type):
            target = args[0]
            instance = object.__new__(cls)
            instance.__init__(*args[1:], **kwargs)
            return instance._decorate(target)
        return object.__new__(cls)

    def _decorate(self, target: type) -> type:
        _attach_annotation(target, self)
        self._apply(target)
        return target

    def __call__(self, target: type) -> type:
        return self._decorate(target)

    def _apply(self, target: type) -> None:
        raise NotImplementedError


class Get(_ModelAnnotation):
    """Generate ``get_<field>()`` methods for declared model fields.

    Use ``@Get`` for every field or ``@Get(["id", "name"])`` to select the
    accessors needed by a public API.  Explicit methods always take priority.
    """

    _annotation_type = "model_get"

    def __init__(self, fields: Optional[Iterable[str] | str] = None):
        super().__init__(fields=_normalize_fields(fields))

    def _apply(self, target: type) -> None:
        for field in _selected_fields(target, self.fields):
            method_name = f"get_{field}"
            if _method_is_custom(target, method_name):
                continue

            def getter(instance: Any, _field: str = field) -> Any:
                return getattr(instance, _field)

            getter.__name__ = method_name
            getter.__qualname__ = f"{target.__qualname__}.{method_name}"
            getter.__doc__ = f"Return the `{field}` field. Generated by @Get."
            getter.__springbootai_generated__ = True
            setattr(target, method_name, getter)


class Set(_ModelAnnotation):
    """Generate fluent ``set_<field>(value)`` methods for declared fields.

    A generated setter returns ``self`` so model updates can be chained.  It
    assigns values only; business validation remains the responsibility of the
    framework validation annotations and service boundary.
    """

    _annotation_type = "model_set"

    def __init__(self, fields: Optional[Iterable[str] | str] = None):
        super().__init__(fields=_normalize_fields(fields))

    def _apply(self, target: type) -> None:
        for field in _selected_fields(target, self.fields):
            method_name = f"set_{field}"
            if _method_is_custom(target, method_name):
                continue

            def setter(instance: Any, value: Any, _field: str = field) -> Any:
                setattr(instance, _field, value)
                return instance

            setter.__name__ = method_name
            setter.__qualname__ = f"{target.__qualname__}.{method_name}"
            setter.__doc__ = f"Set `{field}` and return self. Generated by @Set."
            setter.__springbootai_generated__ = True
            setattr(target, method_name, setter)


class ToString(_ModelAnnotation):
    """Generate readable ``__str__`` and ``__repr__`` methods for a model.

    The default representation is ``User(id=1, username='alice')``.  Pass
    ``exclude=["password_hash"]`` to hide sensitive or noisy fields.
    """

    _annotation_type = "model_to_string"

    def __init__(self, *, exclude: Optional[Iterable[str] | str] = None):
        super().__init__(exclude=_normalize_fields(exclude) or ())

    def _apply(self, target: type) -> None:
        excluded = set(self.exclude)
        fields = tuple(field for field in _declared_fields(target) if field not in excluded)

        def render(instance: Any) -> str:
            values = ", ".join(
                f"{field}={getattr(instance, field, None)!r}" for field in fields
            )
            return f"{type(instance).__name__}({values})"

        if not _method_is_custom(target, "__repr__"):
            def generated_repr(instance: Any) -> str:
                return render(instance)

            generated_repr.__doc__ = "Generated by @ToString."
            generated_repr.__springbootai_generated__ = True
            setattr(target, "__repr__", generated_repr)
        if not _method_is_custom(target, "__str__"):
            def generated_str(instance: Any) -> str:
                return render(instance)

            generated_str.__doc__ = "Generated by @ToString."
            generated_str.__springbootai_generated__ = True
            setattr(target, "__str__", generated_str)


class Data(_ModelAnnotation):
    """Compose ``@Get``, ``@Set`` and ``@ToString`` for a domain model.

    When no constructor exists, ``@Data`` creates a keyword-only constructor
    from declared fields.  Descriptor defaults from ``Id``, ``Required`` and
    other ORM columns are honored; undeclared keyword arguments fail fast.
    It also adds value equality unless the class already supplies ``__eq__``.
    """

    _annotation_type = "model_data"

    def __init__(
        self,
        fields: Optional[Iterable[str] | str] = None,
        *,
        exclude: Optional[Iterable[str] | str] = None,
        init: bool = True,
        eq: bool = True,
    ):
        super().__init__(
            fields=_normalize_fields(fields),
            exclude=_normalize_fields(exclude) or (),
            init=bool(init),
            eq=bool(eq),
        )

    def _apply(self, target: type) -> None:
        fields = _selected_fields(target, self.fields)
        _add_getters(target, fields)
        _add_setters(target, fields)
        _add_to_string(target, self.exclude)
        if self.init and "__init__" not in target.__dict__:
            _add_initializer(target, fields)
        if self.eq and not _method_is_custom(target, "__eq__"):
            _add_equality(target, fields)


def _add_getters(target: type, fields: tuple[str, ...]) -> None:
    annotation = object.__new__(Get)
    SpringAnnotation.__init__(annotation, fields=fields)
    annotation._apply(target)


def _add_setters(target: type, fields: tuple[str, ...]) -> None:
    annotation = object.__new__(Set)
    SpringAnnotation.__init__(annotation, fields=fields)
    annotation._apply(target)


def _add_to_string(target: type, exclude: tuple[str, ...]) -> None:
    annotation = object.__new__(ToString)
    SpringAnnotation.__init__(annotation, exclude=exclude)
    annotation._apply(target)


def _add_initializer(target: type, fields: tuple[str, ...]) -> None:
    def generated_init(instance: Any, **values: Any) -> None:
        unknown = sorted(set(values) - set(fields))
        if unknown:
            raise TypeError(f"Unexpected model field(s): {', '.join(unknown)}")
        for field in fields:
            setattr(instance, field, values.get(field, _field_default(target, field)))

    generated_init.__name__ = "__init__"
    generated_init.__qualname__ = f"{target.__qualname__}.__init__"
    generated_init.__doc__ = "Keyword-only constructor generated by @Data."
    generated_init.__springbootai_generated__ = True
    setattr(target, "__init__", generated_init)


def _add_equality(target: type, fields: tuple[str, ...]) -> None:
    def generated_eq(instance: Any, other: Any) -> bool:
        if type(other) is not type(instance):
            return NotImplemented
        return all(getattr(instance, field, None) == getattr(other, field, None) for field in fields)

    generated_eq.__name__ = "__eq__"
    generated_eq.__qualname__ = f"{target.__qualname__}.__eq__"
    generated_eq.__doc__ = "Value equality generated by @Data."
    generated_eq.__springbootai_generated__ = True
    setattr(target, "__eq__", generated_eq)
