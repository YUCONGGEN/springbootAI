"""
工具/函数调用注册表 - 从 Python 函数签名自动生成 tool schema，执行模型发起的工具调用。

不依赖 OpenAI function-calling 协议细节，生成通用 schema，由 Provider 适配层转换为
各模型要求的格式。
"""
import inspect
import json
import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, get_type_hints


_PY_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


class ToolExecutionError(RuntimeError):
    """Raised when a tool call violates the execution policy."""


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
    timeout_seconds: float = 10.0
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
                 input_schema: Optional[Dict[str, Any]] = None):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters
        self.return_type = return_type
        self.dangerous = dangerous
        self.input_schema = deepcopy(input_schema) if input_schema is not None else None

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

    def register(self, name: str, func: Callable,
                 description: str = "", return_description: str = "",
                 dangerous: bool = False) -> ToolDefinition:
        """注册工具，从签名自动推断参数 schema"""
        sig = inspect.signature(func)
        try:
            type_hints = get_type_hints(func)
        except (NameError, TypeError):
            type_hints = {}
        properties: Dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            py_type = type_hints.get(
                pname,
                param.annotation if param.annotation is not inspect.Parameter.empty else str,
            )
            json_type = _PY_TO_JSON_TYPE.get(py_type, "string")
            required = param.default is inspect.Parameter.empty
            prop = {"type": json_type, "__required": required}
            properties[pname] = prop

        # 返回类型
        ret_type = "string"
        if sig.return_annotation is not inspect.Signature.empty:
            ret_type = _PY_TO_JSON_TYPE.get(
                type_hints.get("return", sig.return_annotation), "string"
            )

        desc = description or (func.__doc__ or "").strip().split("\n")[0]
        tool = ToolDefinition(name=name, description=desc, func=func,
                              parameters=properties, return_type=ret_type,
                              dangerous=dangerous or bool(
                                  getattr(func, "__spring_tool_dangerous__", False)))
        self._tools[name] = tool
        return tool

    def register_schema(self, name: str, func: Callable,
                        input_schema: Dict[str, Any], description: str = "",
                        return_type: str = "string",
                        dangerous: bool = False) -> ToolDefinition:
        """Register a tool while preserving its externally supplied schema."""
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

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def invoke() -> None:
            try:
                result = tool.func(**arguments)
                if inspect.isawaitable(result):
                    import asyncio
                    result = asyncio.run(result)
                result_holder["value"] = result
            except BaseException as exc:  # propagate the original tool error
                error_holder["error"] = exc

        worker = threading.Thread(target=invoke, name=f"spring-ai-tool-{name}", daemon=True)
        worker.start()
        timeout = self.policy.timeout_seconds
        worker.join(timeout if timeout > 0 else None)
        if worker.is_alive():
            raise ToolExecutionError(f"tool execution timed out: {name}")
        if "error" in error_holder:
            raise error_holder["error"]
        result = result_holder.get("value")
        rendered = str(result)
        if len(rendered) > self.policy.max_result_chars:
            raise ToolExecutionError("tool result exceeds the configured size limit")
        return result

    def clear(self) -> None:
        self._tools.clear()

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
