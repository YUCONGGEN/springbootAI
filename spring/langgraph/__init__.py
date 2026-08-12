"""Optional LangGraph orchestration for SpringBootAI.

Install ``springbootAI[langgraph]`` before importing this package in an
application.  The package delegates graph execution to the official LangGraph
runtime and reuses ``spring.ai`` model/tool beans.
"""

from spring.langgraph.config import (
    LangGraphConfigurationError,
    LangGraphProperties,
    bind_langgraph_config,
)
from spring.langgraph.runtime import (
    LangGraphRuntime,
    LangGraphUnavailableError,
    LangGraphWorkflow,
)
from spring.langgraph.checkpoint import open_sqlite_checkpointer
from spring.langgraph.autoconfig import configure_langgraph
from spring.langgraph.annotation_runtime import (
    LangGraphAnnotationRuntime,
    build_langgraph,
)
from spring.langgraph.annotations import (
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
