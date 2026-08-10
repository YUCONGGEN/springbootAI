"""
工具注册表与工厂 - 把 springbootAI @Tool 与 langchain classic Tool 统一封装。

提供两条路径：
1. ToolFactory.from_function: 把普通 Python 函数转 langchain StructuredTool（供 Agent 用）
2. ToolFactory.from_spring_tool_registry: 把 springbootAI ToolRegistry（@Tool 注册的）
   转为 langchain BaseTool 列表，让 Agent 复用 springbootAI 已注册的工具

这样 springbootAI 的 @Tool 注解与 langchain Agent 生态完全互通。
"""
import logging
from typing import Any, Callable, List, Optional

from spring.annotations.core import Component

logger = logging.getLogger("Spring.LangChain")


@Component
class ToolFactory:
    """工具工厂 Bean - 创建 langchain BaseTool 与桥接 springbootAI @Tool。"""

    @staticmethod
    def from_function(func: Callable, name: Optional[str] = None,
                      description: Optional[str] = None) -> Any:
        """
        把 Python 函数转为 langchain StructuredTool。

        Args:
            func: 普通函数（签名 + docstring 自动生成 schema）
            name: 工具名（默认用函数名）
            description: 工具描述（默认取 docstring 首行）
        """
        from langchain_core.tools import StructuredTool
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip().split("\n")[0]
        return StructuredTool.from_function(func, name=tool_name,
                                            description=tool_desc)

    @staticmethod
    def create_tool(name: str, func: Callable,
                    description: str = "") -> Any:
        """创建 langchain Tool（简单形式）。"""
        from langchain_core.tools import Tool
        return Tool(name=name, func=func, description=description)

    @staticmethod
    def from_spring_tool_registry(spring_registry) -> List[Any]:
        """
        把 springbootAI ToolRegistry 转为 langchain BaseTool 列表。

        Args:
            spring_registry: spring.ai.tools.ToolRegistry 实例（含 schemas()/execute()/names()）
        """
        if spring_registry is None or not hasattr(spring_registry, "names"):
            return []
        tools = []
        for name in spring_registry.names():
            td = spring_registry.get(name)
            if td is None:
                continue
            func = td.func
            desc = td.description or (func.__doc__ or "").strip().split("\n")[0]
            tools.append(ToolFactory.from_function(func, name=name,
                                                   description=desc))
        return tools


class ToolRegistry:
    """
    langchain 工具注册表 - 收集多个工具供 Agent 使用。

    与 springbootAI ToolRegistry 区分：本类面向 langchain Agent，
    内部存 langchain BaseTool 列表。
    """

    def __init__(self):
        self._tools: List[Any] = []

    def add(self, tool: Any) -> "ToolRegistry":
        self._tools.append(tool)
        return self

    def add_function(self, func: Callable, name: Optional[str] = None,
                     description: Optional[str] = None) -> "ToolRegistry":
        self._tools.append(ToolFactory.from_function(func, name, description))
        return self

    def all(self) -> List[Any]:
        return list(self._tools)

    def names(self) -> List[str]:
        return [getattr(t, "name", "") for t in self._tools]

    def clear(self) -> None:
        self._tools.clear()
