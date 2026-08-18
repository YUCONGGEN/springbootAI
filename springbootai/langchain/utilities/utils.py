"""
Utility 注册表 - 封装 langchain classic 的实用工具类，作为 @Component Bean。

封装的工具：
- serpapi: SerpAPIWrapper（搜索引擎，需 serpapi + google-search-results）
- duckduckgo: DuckDuckGoSearchRun（免费搜索，需 duckduckgo-search）
- wikipedia: WikipediaAPIWrapper（维基百科，需 wikipedia）
- python-repl: PythonREPL（执行 Python 代码，需 langchain_experimental）
- sql-database: SQLDatabase（SQL 数据库，需 sqlalchemy）
- arxiv: ArxivAPIWrapper（arXiv 论文，需 arxiv）
- pubmed: PubMedAPIWrapper（PubMed，需 pymed）
- wolfram-alpha: WolframAlphaAPIWrapper（数学/知识，需 wolframalpha）

所有工具懒加载，缺失时抛带安装提示的 ImportError。
可作为 langchain Tool 直接交给 Agent。
"""
import logging
from typing import Any, List


logger = logging.getLogger("Spring.LangChain")


class UtilityRegistry:
    """Utility 注册表 Bean - 创建与管理各类实用工具。

    安全警告：``python-repl`` 与 ``sql-database`` 具备代码执行/数据库读写能力，
    默认禁用（``_DANGEROUS_UTILS``）。必须显式设置环境变量
    ``AI_ALLOW_DANGEROUS_TOOLS=true`` 或构造时传入 ``allow_dangerous=True``
    才可启用，对应 OWASP Excessive Agency。
    """

    # 工具名 -> (模块, 类名)
    _UTIL_MAP = {
        "serpapi":        ("langchain_community.utilities", "SerpAPIWrapper"),
        "duckduckgo":     ("langchain_community.utilities", "DuckDuckGoSearchAPIWrapper"),
        "wikipedia":      ("langchain_community.utilities", "WikipediaAPIWrapper"),
        "python-repl":    ("langchain_experimental.utilities", "PythonREPL"),
        "sql-database":   ("langchain_community.utilities", "SQLDatabase"),
        "arxiv":          ("langchain_community.utilities", "ArxivAPIWrapper"),
        "pubmed":         ("langchain_community.utilities", "PubMedAPIWrapper"),
        "wolfram-alpha":  ("langchain_community.utilities", "WolframAlphaAPIWrapper"),
        "golden-query":   ("langchain_community.utilities", "GoldenQueryAPIWrapper"),
        "openweathermap": ("langchain_community.utilities", "OpenWeatherMapAPIWrapper"),
        "stack-overflow": ("langchain_community.utilities", "StackExchangeAPIWrapper"),
    }

    # ==================== 危险工具安全管控 ====================
    # OWASP Excessive Agency：python-repl 可执行任意 Python 代码，
    # sql-database 可读写数据库；默认禁用，防止提示注入升级为 RCE/数据破坏。
    _DANGEROUS_UTILS = frozenset({"python-repl", "sql-database"})

    def __init__(self, allow_dangerous: bool = False):
        import os
        self._allow_dangerous = allow_dangerous or os.environ.get(
            "AI_ALLOW_DANGEROUS_TOOLS", "false").strip().lower() in (
                "true", "1", "yes", "on")

    @classmethod
    def create(cls, util_type: str, **kwargs) -> Any:
        """
        创建工具实例。

        Args:
            util_type: 见 _UTIL_MAP 的 key
            kwargs: 透传给工具构造器（如 serpapi 需 serpapi_api_key）

        Raises:
            PermissionError: 尝试创建危险工具但未设置 AI_ALLOW_DANGEROUS_TOOLS=true
        """
        if util_type in cls._DANGEROUS_UTILS:
            import os as _os
            allowed = _os.environ.get("AI_ALLOW_DANGEROUS_TOOLS", "false").strip().lower() in (
                "true", "1", "yes", "on")
            if not allowed:
                raise PermissionError(
                    f"危险工具 '{util_type}' 默认禁用（OWASP Excessive Agency）。"
                    " 设置 AI_ALLOW_DANGEROUS_TOOLS=true 可启用，"
                    " 但请确保已实现沙箱、审计日志和最小权限原则。"
                )
        spec = cls._UTIL_MAP.get(util_type)
        if not spec:
            raise ValueError(
                f"未知 util_type: {util_type}。支持: {list(cls._UTIL_MAP.keys())}"
            )
        module_name, class_name = spec
        try:
            import importlib
            module = importlib.import_module(module_name)
            util_cls = getattr(module, class_name)
        except ImportError as exc:
            raise ImportError(
                f"工具 {util_type} 依赖未安装（{exc}）。"
                f"请 pip install {module_name.replace('_', '-')}"
            ) from exc
        return util_cls(**kwargs)

    @classmethod
    def as_tools(cls, util_types: List[str], **kwargs) -> List[Any]:
        """
        批量创建工具并转为 langchain Tool 列表（供 Agent 直接用）。

        Args:
            util_types: 工具类型名列表
        """
        from langchain_core.tools import Tool
        tools = []
        for ut in util_types:
            util = cls.create(ut, **kwargs.get(ut, {}))
            # 多数 utility 有 run 方法
            if hasattr(util, "run"):
                tools.append(Tool(name=ut, func=util.run,
                                  description=(util.__doc__ or ut).strip().split("\n")[0]))
            elif hasattr(util, "invoke"):
                tools.append(Tool(name=ut, func=util.invoke,
                                  description=(util.__doc__ or ut).strip().split("\n")[0]))
        return tools

    @classmethod
    def supported_types(cls) -> list:
        """返回支持的工具类型。"""
        return list(cls._UTIL_MAP.keys())


# ==================== 安全算术求值器 ====================

def safe_eval_arithmetic(expression: str) -> float:
    """
    基于 ``ast.parse`` 的安全算术表达式求值器。

    仅支持白名单运算符（+、-、*、/、//、%、**、正负号）和数字字面值，
    拒绝函数调用、属性访问、变量名等任何可能执行代码的构造。

    对比 ``eval()``：``eval`` 会执行任意 Python 代码，``safe_eval_arithmetic``
    只做纯算术求值。测试用 ``FakeChatModel`` 的工具模拟与原 demo 示例。

    Args:
        expression: 算术表达式字符串（如 "2 + 3 * 4"）
    Returns:
        计算结果（int 或 float）
    Raises:
        ValueError: 表达式包含不允许的操作或语法错误
    """
    import ast
    import operator as _op

    _ALLOWED_OPS = {
        ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
        ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv,
        ast.Mod: _op.mod, ast.Pow: _op.pow, ast.USub: _op.neg,
        ast.UAdd: _op.pos,
    }

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](_eval(node.left),
                                                _eval(node.right))
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    try:
        tree = ast.parse(str(expression).strip(), mode='eval')
        return _eval(tree)
    except (SyntaxError, TypeError, ZeroDivisionError) as exc:
        raise ValueError(f"invalid arithmetic expression: {exc}") from exc
