"""
工具/函数调用注册表 - 从 Python 函数签名自动生成 tool schema，执行模型发起的工具调用。

不依赖 OpenAI function-calling 协议细节，生成通用 schema，由 Provider 适配层转换为
各模型要求的格式。
"""
import inspect
import json
from typing import Any, Callable, Dict, List, Optional


_PY_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


class ToolDefinition:
    """工具定义"""

    def __init__(self, name: str, description: str, func: Callable,
                 parameters: Dict[str, Any], return_type: str = "string"):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters
        self.return_type = return_type

    def to_schema(self) -> Dict[str, Any]:
        """生成 OpenAI 风格的 function schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [
                        p for p, m in self.parameters.items()
                        if m.get("__required", True)
                    ],
                },
            },
        }


class ToolRegistry:
    """工具注册表 - 管理所有可被 LLM 调用的工具"""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, name: str, func: Callable,
                 description: str = "", return_description: str = "") -> ToolDefinition:
        """注册工具，从签名自动推断参数 schema"""
        sig = inspect.signature(func)
        properties: Dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            py_type = param.annotation if param.annotation is not inspect.Parameter.empty else str
            json_type = _PY_TO_JSON_TYPE.get(py_type, "string")
            required = param.default is inspect.Parameter.empty
            prop = {"type": json_type, "__required": required}
            properties[pname] = prop

        # 返回类型
        ret_type = "string"
        if sig.return_annotation is not inspect.Signature.empty:
            ret_type = _PY_TO_JSON_TYPE.get(sig.return_annotation, "string")

        desc = description or (func.__doc__ or "").strip().split("\n")[0]
        tool = ToolDefinition(name=name, description=desc, func=func,
                              parameters=properties, return_type=ret_type)
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def schemas(self) -> List[Dict[str, Any]]:
        """返回所有工具的 schema（供 Provider 注入模型）"""
        return [t.to_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """按名称执行工具"""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"工具未注册: {name}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return tool.func(**arguments)

    def clear(self) -> None:
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)
