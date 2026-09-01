"""
工具/函数调用注册表 - 从 Python 函数签名自动生成 tool schema，执行模型发起的工具调用。

不依赖 OpenAI function-calling 协议细节，生成通用 schema，由 Provider 适配层转换为
各模型要求的格式。
"""
import inspect
import json
import logging
import math
import re
import threading
import types
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import (
    Annotated, Any, Callable, Dict, List, Literal, Optional, Set, Union,
    get_args, get_origin, get_type_hints,
)


logger = logging.getLogger("Spring.AI.Tools")

try:  # Python 3.10-3.12 expose the parser under ``re``.
    from re import _constants as _re_constants  # type: ignore[attr-defined]
    from re import _parser as _re_parser  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - compatibility fallback
    import sre_constants as _re_constants
    import sre_parse as _re_parser
_CANCELLATION_PARAMETER = "cancellation_token"


_PY_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _type_to_schema(type_hint: Any) -> Dict[str, Any]:
    """Convert common Python typing forms into an honest JSON Schema."""
    if type_hint in (Any, inspect.Parameter.empty):
        return {}
    if type_hint is None or type_hint is type(None):
        return {"type": "null"}
    if isinstance(type_hint, type) and issubclass(type_hint, Enum):
        values = [item.value for item in type_hint]
        schema: Dict[str, Any] = {"enum": values}
        if values and all(type(item) is type(values[0]) for item in values):
            schema.update(_type_to_schema(type(values[0])))
        return schema

    origin = get_origin(type_hint)
    args = get_args(type_hint)
    if origin is Annotated:
        return _type_to_schema(args[0]) if args else {}
    if origin is Literal:
        values = list(args)
        schema = {"enum": values}
        if values and all(type(item) is type(values[0]) for item in values):
            schema.update(_type_to_schema(type(values[0])))
        return schema
    if origin in (Union, types.UnionType):
        return {"anyOf": [_type_to_schema(item) for item in args]}
    if origin in (list, List, set, Set, tuple):
        item_schema = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin in (dict, Dict, Mapping):
        value_schema = _type_to_schema(args[1]) if len(args) > 1 else {}
        return {"type": "object", "additionalProperties": value_schema}
    json_type = _PY_TO_JSON_TYPE.get(type_hint)
    return {"type": json_type} if json_type else {"type": "string"}


def _schema_error(path: str, detail: str) -> "ToolExecutionError":
    return ToolExecutionError(f"tool arguments failed schema validation at {path}: {detail}")


def _compile_safe_pattern(pattern: Any) -> re.Pattern:
    text = str(pattern)
    if len(text) > 256:
        raise ValueError("pattern exceeds 256 characters")
    parsed = _re_parser.parse(text)
    repeat_ops = {
        _re_constants.MAX_REPEAT,
        _re_constants.MIN_REPEAT,
    }
    possessive = getattr(_re_constants, "POSSESSIVE_REPEAT", None)
    if possessive is not None:
        repeat_ops.add(possessive)
    forbidden_ops = {
        _re_constants.ASSERT,
        _re_constants.ASSERT_NOT,
        _re_constants.GROUPREF,
        _re_constants.GROUPREF_EXISTS,
    }

    def walk(node: Any, *, repeated: bool = False, depth: int = 0) -> None:
        if depth > 32:
            raise ValueError("pattern nesting exceeds 32 levels")
        for operation, argument in node:
            if operation in forbidden_ops:
                raise ValueError("lookarounds and backreferences are not allowed")
            if operation in repeat_ops:
                if repeated:
                    raise ValueError("nested quantifiers are not allowed")
                walk(argument[2], repeated=True, depth=depth + 1)
            elif operation is _re_constants.BRANCH:
                if repeated:
                    raise ValueError("alternation inside a quantified group is not allowed")
                for branch in argument[1]:
                    walk(branch, repeated=False, depth=depth + 1)
            elif operation is _re_constants.SUBPATTERN:
                walk(argument[-1], repeated=repeated, depth=depth + 1)

    walk(parsed)
    return re.compile(text)


def _validate_json_schema(
    value: Any,
    schema: Any,
    path: str = "$",
    _depth: int = 0,
) -> None:
    """Validate the bounded JSON Schema subset accepted by tool registries.

    Model-generated arguments are untrusted input. Provider-side schema hints
    are therefore never treated as an execution-time validation boundary.
    """
    if not isinstance(schema, Mapping):
        raise _schema_error(path, "schema must be an object")
    if _depth > 32:
        raise _schema_error(path, "schema nesting exceeds 32 levels")

    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if alternatives is not None:
        if (not isinstance(alternatives, list) or not alternatives
                or len(alternatives) > 32):
            raise _schema_error(path, "schema alternatives must be a non-empty list")
        matches = 0
        for candidate in alternatives:
            try:
                _validate_json_schema(value, candidate, path, _depth + 1)
                matches += 1
            except ToolExecutionError:
                continue
        if matches == 0 or ("oneOf" in schema and matches != 1):
            raise _schema_error(path, "value does not match the allowed alternatives")
        return

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_matches_json_type(value, item) for item in expected):
            raise _schema_error(path, f"expected one of {expected!r}")
    elif expected and not _matches_json_type(value, expected):
        raise _schema_error(path, f"expected {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise _schema_error(path, "value is not in enum")
    if "const" in schema and value != schema["const"]:
        raise _schema_error(path, "value does not match const")

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if properties is None:
            properties = {}
        elif not isinstance(properties, Mapping):
            raise _schema_error(path, "properties must be an object")
        if len(properties) > 256:
            raise _schema_error(path, "schema has too many properties")
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise _schema_error(path, "required must be a list")
        for name in required:
            if name not in value:
                raise _schema_error(path, f"missing required property {name!r}")
        for name, item in value.items():
            child_path = f"{path}.{name}"
            if name in properties:
                _validate_json_schema(
                    item, properties[name], child_path, _depth + 1)
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                raise _schema_error(child_path, "additional property is not allowed")
            if isinstance(additional, Mapping):
                _validate_json_schema(item, additional, child_path, _depth + 1)
        _check_size(value, schema, path, "minProperties", "maxProperties")

    if isinstance(value, list):
        _check_size(value, schema, path, "minItems", "maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_json_schema(
                    item, item_schema, f"{path}[{index}]", _depth + 1)

    if isinstance(value, str):
        _check_size(value, schema, path, "minLength", "maxLength")
        pattern = schema.get("pattern")
        if pattern is not None:
            try:
                if _compile_safe_pattern(pattern).search(value) is None:
                    raise _schema_error(path, "string does not match pattern")
            except (re.error, ValueError) as exc:
                raise _schema_error(
                    path, "schema contains an unsafe or invalid pattern") from exc

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise _schema_error(path, "number must be finite")
        for key, predicate in (
            ("minimum", lambda current, bound: current >= bound),
            ("maximum", lambda current, bound: current <= bound),
            ("exclusiveMinimum", lambda current, bound: current > bound),
            ("exclusiveMaximum", lambda current, bound: current < bound),
        ):
            if key in schema and not predicate(value, schema[key]):
                raise _schema_error(path, f"number violates {key}")


def _matches_json_type(value: Any, expected: Any) -> bool:
    return {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, Mapping),
    }.get(str(expected), False)


def _check_size(value: Any, schema: Mapping, path: str,
                minimum_key: str, maximum_key: str) -> None:
    size = len(value)
    if minimum_key in schema and size < int(schema[minimum_key]):
        raise _schema_error(path, f"value violates {minimum_key}")
    if maximum_key in schema and size > int(schema[maximum_key]):
        raise _schema_error(path, f"value violates {maximum_key}")


class ToolExecutionError(RuntimeError):
    """Raised when a tool call violates the execution policy."""


class ToolCancellationToken:
    """Cooperative cancellation signal for bounded in-process tools.

    Python cannot safely kill an arbitrary running thread. A tool that opts
    into a timeout accepts ``cancellation_token`` and checks ``cancelled`` or
    calls ``raise_if_cancelled()`` around side-effect steps. The registry never
    returns a timeout while that worker is still running.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ToolExecutionError("tool execution cancelled")


@dataclass(frozen=True)
class ToolExecutionPolicy:
    """Fail-closed policy for model initiated tool calls.

    ``authorizer`` and ``approver`` receive ``(tool_name, arguments, context)``.
    A policy is intentionally attached to each registry so a request cannot
    silently inherit permissions from another ChatClient.
    """

    allowed_tools: Optional[Set[str]] = None
    allow_dangerous: bool = False
    max_argument_bytes: int = 16_384
    max_result_chars: int = 10_000
    # Zero means synchronous execution without a framework timeout. A positive
    # timeout is accepted only for cooperatively cancellable tools; this avoids
    # returning a timeout while a daemon thread continues mutating state.
    timeout_seconds: float = 0.0
    cancellation_grace_seconds: float = 1.0
    require_approval: bool = False
    authorizer: Optional[Callable[[str, Dict[str, Any], Any], bool]] = None
    approver: Optional[Callable[[str, Dict[str, Any], Any], bool]] = None

    def validate(self, tool: "ToolDefinition", arguments: Dict[str, Any], context: Any) -> None:
        if self.allowed_tools is not None and tool.name not in self.allowed_tools:
            raise PermissionError(f"tool is not allowed: {tool.name}")
        if tool.dangerous and not self.allow_dangerous:
            raise PermissionError(f"dangerous tool is disabled: {tool.name}")
        if self.max_argument_bytes <= 0 or self.max_result_chars <= 0:
            raise ValueError("tool execution limits must be greater than zero")
        if self.timeout_seconds < 0 or self.cancellation_grace_seconds < 0:
            raise ValueError("tool timeout limits cannot be negative")
        try:
            encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("tool arguments must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > self.max_argument_bytes:
            raise ToolExecutionError("tool arguments exceed the configured size limit")
        if self.authorizer and not self.authorizer(tool.name, arguments, context):
            raise PermissionError(f"tool authorization denied: {tool.name}")
        if self.require_approval:
            if not self.approver or not self.approver(tool.name, arguments, context):
                raise PermissionError(f"tool approval required: {tool.name}")


class ToolDefinition:
    """工具定义"""

    def __init__(self, name: str, description: str, func: Callable,
                 parameters: Dict[str, Any], return_type: str = "string",
                 dangerous: bool = False,
                 input_schema: Optional[Dict[str, Any]] = None,
                 accepts_cancellation: bool = False,
                 managed_timeout: bool = False):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters
        self.return_type = return_type
        self.dangerous = dangerous
        self.input_schema = deepcopy(input_schema) if input_schema is not None else None
        self.accepts_cancellation = accepts_cancellation
        self.managed_timeout = managed_timeout

    def to_schema(self) -> Dict[str, Any]:
        """生成 OpenAI 风格的 function schema"""
        if self.input_schema is not None:
            parameters = deepcopy(self.input_schema)
        else:
            properties = {
                name: {key: value for key, value in schema.items() if key != "__required"}
                for name, schema in self.parameters.items()
            }
            parameters = {
                "type": "object",
                "properties": properties,
                "required": [
                    p for p, m in self.parameters.items()
                    if m.get("__required", True)
                ],
            }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class ToolRegistry:
    """工具注册表 - 管理所有可被 LLM 调用的工具"""

    def __init__(self, policy: Optional[ToolExecutionPolicy] = None):
        self._tools: Dict[str, ToolDefinition] = {}
        self.policy = policy or ToolExecutionPolicy()
        self._quarantined_tools: Set[str] = set()
        self._state_lock = threading.RLock()

    def register(self, name: str, func: Callable,
                 description: str = "", return_description: str = "",
                 dangerous: bool = False) -> ToolDefinition:
        """注册工具，从签名自动推断参数 schema"""
        if name in self._tools:
            raise ValueError(f"duplicate tool registration: {name}")
        sig = inspect.signature(func)
        try:
            type_hints = get_type_hints(func)
        except (NameError, TypeError):
            type_hints = {}
        properties: Dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls", _CANCELLATION_PARAMETER):
                continue
            py_type = type_hints.get(
                pname,
                param.annotation if param.annotation is not inspect.Parameter.empty else str,
            )
            required = param.default is inspect.Parameter.empty
            prop = _type_to_schema(py_type)
            prop["__required"] = required
            properties[pname] = prop

        # 返回类型
        ret_type = "string"
        if sig.return_annotation is not inspect.Signature.empty:
            ret_type = _type_to_schema(
                type_hints.get("return", sig.return_annotation)
            ).get("type", "string")

        desc = description or (func.__doc__ or "").strip().split("\n")[0]
        tool = ToolDefinition(name=name, description=desc, func=func,
                              parameters=properties, return_type=ret_type,
                              dangerous=dangerous or bool(
                                  getattr(func, "__spring_tool_dangerous__", False)),
                              accepts_cancellation=(
                                  _CANCELLATION_PARAMETER in sig.parameters),
                              managed_timeout=bool(getattr(
                                  func, "__spring_tool_managed_timeout__", False)))
        self._tools[name] = tool
        return tool

    def register_schema(self, name: str, func: Callable,
                        input_schema: Dict[str, Any], description: str = "",
                        return_type: str = "string",
                        dangerous: bool = False) -> ToolDefinition:
        """Register a tool while preserving its externally supplied schema."""
        if name in self._tools:
            raise ValueError(f"duplicate tool registration: {name}")
        if not callable(func):
            raise TypeError("tool func must be callable")
        if not isinstance(input_schema, dict) or input_schema.get("type", "object") != "object":
            raise ValueError("tool input_schema must be an object JSON Schema")
        properties = input_schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("tool input_schema.properties must be an object")
        required = input_schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ValueError("tool input_schema.required must be a list of strings")

        parameter_metadata: Dict[str, Any] = {}
        required_names = set(required)
        for parameter_name, schema in properties.items():
            if not isinstance(parameter_name, str) or not isinstance(schema, dict):
                raise ValueError("tool input_schema properties must map strings to schemas")
            metadata = deepcopy(schema)
            metadata["__required"] = parameter_name in required_names
            parameter_metadata[parameter_name] = metadata

        tool = ToolDefinition(
            name=name,
            description=description,
            func=func,
            parameters=parameter_metadata,
            return_type=return_type,
            dangerous=dangerous,
            input_schema=input_schema,
            accepts_cancellation=(
                _CANCELLATION_PARAMETER in inspect.signature(func).parameters),
            managed_timeout=bool(getattr(
                func, "__spring_tool_managed_timeout__", False)),
        )
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def schemas(self) -> List[Dict[str, Any]]:
        """返回所有工具的 schema（供 Provider 注入模型）"""
        return [t.to_schema() for t in self._tools.values()
                if self.policy.allow_dangerous or not t.dangerous]

    def execute(self, name: str, arguments: Dict[str, Any], context: Any = None) -> Any:
        """按名称执行工具"""
        with self._state_lock:
            if name in self._quarantined_tools:
                raise ToolExecutionError(
                    f"tool is quarantined after an uncertain timeout: {name}")
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"工具未注册: {name}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ToolExecutionError("tool arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ToolExecutionError("tool arguments must be an object")
        self.policy.validate(tool, arguments, context)
        _validate_json_schema(arguments, tool.to_schema()["function"]["parameters"])

        call_arguments = dict(arguments)
        if tool.accepts_cancellation:
            call_arguments[_CANCELLATION_PARAMETER] = ToolCancellationToken()
        try:
            inspect.signature(tool.func).bind(**call_arguments)
        except TypeError as exc:
            raise ToolExecutionError(
                f"tool arguments do not match the registered signature: {name}"
            ) from exc

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}
        cancellation_token = call_arguments.pop(
            _CANCELLATION_PARAMETER, ToolCancellationToken())

        def invoke() -> None:
            try:
                call_arguments = dict(arguments)
                if tool.accepts_cancellation:
                    call_arguments[_CANCELLATION_PARAMETER] = cancellation_token
                result = tool.func(**call_arguments)
                if inspect.isawaitable(result):
                    import asyncio
                    async def await_result(awaitable):
                        return await awaitable
                    result = asyncio.run(await_result(result))
                # Rendering and JSON validation are part of the bounded tool
                # operation.  A hostile ``__str__``/``__repr__`` must not run
                # later on the request thread after the timeout has ended.
                if isinstance(result, str):
                    rendered = result
                    normalized = result
                else:
                    try:
                        rendered = json.dumps(
                            result, ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        normalized = result
                    except (TypeError, ValueError):
                        rendered = str(result)
                        normalized = rendered
                if len(rendered) > self.policy.max_result_chars:
                    raise ToolExecutionError(
                        "tool result exceeds the configured size limit")
                result_holder["value"] = normalized
            except BaseException as exc:  # propagate the original tool error
                error_holder["error"] = exc

        timeout = self.policy.timeout_seconds
        if timeout <= 0 or tool.managed_timeout:
            invoke()
        else:
            if not tool.accepts_cancellation:
                raise ToolExecutionError(
                    f"tool {name} configures a timeout but does not accept "
                    f"the reserved '{_CANCELLATION_PARAMETER}' parameter"
                )
            worker = threading.Thread(
                target=invoke, name=f"spring-ai-tool-{name}", daemon=True)
            worker.start()
            worker.join(timeout)
            if worker.is_alive():
                cancellation_token.cancel()
                worker.join(self.policy.cancellation_grace_seconds)
                if worker.is_alive():
                    # Python cannot safely terminate an arbitrary thread. Keep
                    # the request timeout truthful, quarantine this tool to
                    # prevent automatic retries, and report the outcome as
                    # uncertain while the daemon worker winds down.
                    with self._state_lock:
                        self._quarantined_tools.add(name)
                    logger.error(
                        "Tool %s ignored cancellation; quarantined with uncertain outcome",
                        name,
                    )
                    raise ToolExecutionError(
                        f"tool execution timed out with uncertain outcome: {name}")
                raise ToolExecutionError(f"tool execution timed out: {name}")
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value")

    def clear(self) -> None:
        self._tools.clear()
        with self._state_lock:
            self._quarantined_tools.clear()

    def __len__(self) -> int:
        return len(self._tools)


class CompositeToolRegistry:
    """Route tool operations to multiple registries without weakening policy.

    Each child registry remains responsible for its own authorization, approval,
    timeout and result-size checks. Duplicate names are rejected because silent
    shadowing could redirect a model call to a less restrictive implementation.
    """

    def __init__(self, *registries: Any):
        self._registries = [registry for registry in registries if registry is not None]
        owners: Dict[str, Any] = {}
        for registry in self._registries:
            if not all(hasattr(registry, attr) for attr in ("names", "get", "schemas", "execute")):
                raise TypeError("child registry does not implement the tool registry contract")
            for name in registry.names():
                if name in owners:
                    raise ValueError(f"duplicate tool name across registries: {name}")
                owners[name] = registry
        self._owners = owners

    def names(self) -> List[str]:
        return list(self._owners)

    def get(self, name: str) -> Optional[ToolDefinition]:
        owner = self._owners.get(name)
        return owner.get(name) if owner is not None else None

    def schemas(self) -> List[Dict[str, Any]]:
        schemas: List[Dict[str, Any]] = []
        for registry in self._registries:
            schemas.extend(registry.schemas())
        return schemas

    def execute(self, name: str, arguments: Dict[str, Any], context: Any = None) -> Any:
        owner = self._owners.get(name)
        if owner is None:
            raise KeyError(f"tool is not registered: {name}")
        return owner.execute(name, arguments, context)

    def __len__(self) -> int:
        return len(self._owners)
