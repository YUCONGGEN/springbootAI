"""Optional LangGraph orchestration for SpringBootAI.

Install ``springbootAI[langgraph]`` before importing this package in an
application.  The package delegates graph execution to the official LangGraph
runtime and reuses ``springbootai.ai`` model/tool beans.
"""

from springbootai.langgraph.config import (
    LangGraphConfigurationError,
    LangGraphProperties,
    bind_langgraph_config,
)
from springbootai.langgraph.runtime import (
    LangGraphRuntime,
    LangGraphUnavailableError,
    LangGraphWorkflow,
)
from springbootai.langgraph.checkpoint import open_sqlite_checkpointer
from springbootai.langgraph.autoconfig import configure_langgraph
from springbootai.langgraph.annotation_runtime import (
    LangGraphAnnotationRuntime,
    build_langgraph,
)
from springbootai.langgraph.annotations import (
    GraphEdge,
    GraphInvoke,
    GraphNode,
    GraphRoute,
    LangGraph,
)

__all__ = [
    "LangGraphConfigurationError",
    "LangGraphProperties",
    "bind_langgraph_config",
    "LangGraphRuntime",
    "LangGraphUnavailableError",
    "LangGraphWorkflow",
    "open_sqlite_checkpointer",
    "configure_langgraph",
    "GraphEdge",
    "GraphInvoke",
    "GraphNode",
    "GraphRoute",
    "LangGraph",
    "LangGraphAnnotationRuntime",
    "build_langgraph",
]
