"""
LangChain Agent 服务 - 演示用 AgentService + ToolFactory 构建可调用工具的智能体。
"""
import ast
import operator
from typing import Any

from spring.annotations.core import Autowired, Service, Slf4j
from spring.langchain.agents.services import AgentService
from spring.langchain.tools.tools import ToolFactory


# ==================== 安全算术求值器 ====================
# 用 AST 遍历替代 eval()，只允许数字和算术运算符，杜绝沙箱逃逸
# （eval 即使清空 __builtins__ 仍可通过 (1).__class__.__bases__ 访问任意类）

_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval_arithmetic(expression: str) -> Any:
    """安全求值算术表达式（仅允许数字和 + - * / // % ** 运算符）。

    不使用 eval()，而是用 ast.walk 遍历语法树，遇到非算术节点
    （属性访问、函数调用、名字解析等）立即拒绝，杜绝沙箱逃逸。
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"表达式语法错误: {exc}") from exc

    def _eval(node):
        # 数字字面量（Python 3.8+ 用 ast.Constant，旧版用 ast.Num）
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        # 二元运算
        if isinstance(node, ast.BinOp):
            op_func = _ALLOWED_BIN_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            return op_func(_eval(node.left), _eval(node.right))
        # 一元运算（正负号）
        if isinstance(node, ast.UnaryOp):
            op_func = _ALLOWED_UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
            return op_func(_eval(node.operand))
        # 括号表达式
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        # 其他节点（属性访问、调用、名字等）一律拒绝
        raise ValueError(f"不允许的表达式类型: {type(node).__name__}")

    return _eval(tree)


@Slf4j
@Service
class LangChainAgentService:
    """Agent 服务 - 基于 ReAct Agent + 自定义工具。"""

    @Autowired
    def __init__(self, agent_service: AgentService):
        self.agent_service = agent_service

    def _build_tools(self):
        """构造两个示例工具：当前时间、计算器。"""

        def current_time(query: str = "") -> str:
            """返回当前时间（示例工具）。"""
            from datetime import datetime
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def calculator(expression: str) -> str:
            """计算数学表达式，如 2+3*4。"""
            try:
                # 安全求值：用 AST 遍历，不使用 eval（防沙箱逃逸）
                result = safe_eval_arithmetic(expression)
                return str(result)
            except Exception as exc:
                return f"计算失败: {exc}"

        return [
            ToolFactory.from_function(current_time, name="current_time",
                                      description="获取当前时间"),
            ToolFactory.from_function(calculator, name="calculator",
                                      description="计算数学表达式"),
        ]

    def run(self, question: str, agent_type: str = "react") -> str:
        """执行 Agent。"""
        tools = self._build_tools()
        executor = self.agent_service.create_agent(
            tools, agent_type=agent_type, max_iterations=5)
        return self.agent_service.run_agent(executor, question)
