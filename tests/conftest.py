"""
Pytest 全局配置 - 警告抑制。

langchain_classic 1.x 被官方标记为 deprecated 并建议迁移到 langchain_v1 + langgraph。
本项目有意锁定 classic API 以保证稳定性，以下警告预期存在且无业务影响。
"""
import warnings as _warnings

# ========== langchain classic deprecation ==========
# simplefilter("ignore", Class) 全局生效，优先级高于 pytest 内置的 default::DeprecationWarning
try:
    from langchain_core._api import LangChainDeprecationWarning
    _warnings.simplefilter("ignore", LangChainDeprecationWarning)
except ImportError:
    pass

# 备选：消息匹配（catch 被 pytest filterwarnings 漏掉的警告）
_warnings.filterwarnings("ignore", message=".*deprecated in LangChain.*")
_warnings.filterwarnings("ignore", message=".*will be removed in.*")
_warnings.filterwarnings("ignore", message=".*Use .*create_agent.* instead.*")

# ========== langchain-community sunset ==========
_warnings.filterwarnings("ignore", message=".*langchain-community.*sunset.*")
_warnings.filterwarnings("ignore", message=".*langchain-community.*no longer.*")