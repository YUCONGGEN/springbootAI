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
    """Utility 注册表 Bean - 创建与管理各类实用工具。"""

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

    @classmethod
    def create(cls, util_type: str, **kwargs) -> Any:
        """
        创建工具实例。

        Args:
            util_type: 见 _UTIL_MAP 的 key
            kwargs: 透传给工具构造器（如 serpapi 需 serpapi_api_key）
        """
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
