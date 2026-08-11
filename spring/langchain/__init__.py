"""
SpringBootAI LangChain 模块 - 把 langchain classic 全套能力封装为 Spring 风格 Bean。

模块组成（对齐 langchain-master 官方 monorepo libs/ 架构）：
- core:        LangChainCore 统一核心入口（构建器模式 + 一站式 RAG/对话/Agent）
- adapters:    springbootAI ChatModel/EmbeddingModel <-> langchain 模型/嵌入/向量库 双向桥接
- partners:    30+ Partner 提供商工厂（OpenAI/Anthropic/Ollama/DeepSeek/ZhipuAI/Tongyi...）
- autoconfig:  从 application.yml 的 spring.langchain.* 自动装配 Bean
- prompts:     PromptTemplate / ChatPromptTemplate / FewShotPromptTemplate 工厂
- chains:      LLMChain / ConversationChain / RetrievalQA / ConversationalRetrieval /
               SequentialChain / APIChain / ConstitutionalChain / MultiPromptChain /
               FlareChain / MapReduceChain / LLMMathChain / SummarizeChain
- agents:      ReAct / chat-zero-shot-react / conversational / openai-tools /
               structured-chat / self-ask-with-search / xml Agent
- memory:      buffer / summary / buffer-window / token-buffer / entity /
               combined / read-only-shared 会话记忆
- parsers:     comma-list / datetime / json / pydantic / enum 输出解析
- loaders:     text / csv / pdf / web / directory / json / markdown / word 文档加载
- retrievers:  similarity / multi-query / contextual-compression / self-query /
               time-weighted / ensemble
- vectorstores:FAISS / Chroma / Pinecone / Weaviate / PGVector / Redis / inmemory
- indexes:     VectorStoreIndexCreator 一键 RAG
- tools:       langchain Tool 与 springbootAI @Tool 互转
- utilities:   SerpAPI / DuckDuckGo / Wikipedia / PythonREPL / SQLDatabase / Arxiv ...
- callbacks:   StdOut / StreamingStdOut / File 回调

===== 架构边界 =====
- 本模块**锁定 langchain_classic (1.x) API** 作为底层能力层。
  langchain 官方已弃用 classic API 转向 langchain_v1 + langgraph，但 v1 依赖
  重量级 langgraph 库。本项目选择稳定 classic API + pip 版本锁定，确保行为可预期。
  因此导入本模块时，langchain classic 的 DeprecationWarning 会被自动静默。
- langchain v1 `create_agent()` / `langgraph` / `LCEL Runnable` 不在此模块范围。
  需要这些能力的用户请直接用原生 langchain；spring/langchain/adapters 可做桥接。
- Partner 提供商采用懒加载，36 个 partner 中仅 9 个列入 [langchain] extra；
  其余 15+ 个按需 `pip install`，首次使用有明确 ImportError 提示。
- async 支持有限：本模块基于 langchain classic 的同步 API；`core.stream()` 返回
  普通生成器而非 async generator。完整 async 流式需等待 v1/lcEL 迁移。
"""
import warnings as _warnings

# 静默 langchain classic 弃用告警（全局忽略，不依赖模块导入顺序）。
# langchain_classic 1.x（LLMChain, ConversationChain, AgentExecutor 等）已
# 被官方标记 deprecated 并建议迁移到 langchain_v1 + langgraph。本项目有意锁定
# classic API 以保证稳定性，用户不应看到这些框架级别的弃用告警。
# 注意：simplefilter("ignore") 必须放在 filterwarnings 之前，因为后者依赖模块匹配。
try:
    from langchain_core._api import LangChainDeprecationWarning
    _warnings.simplefilter("ignore", LangChainDeprecationWarning)
except ImportError:
    pass

# 静默 langchain-community sunset 告警（community 被官方标记 sunset，但
# 30+ partner 提供商仍通过 community 懒导入；用户不应看到此架构级告警）
_warnings.filterwarnings("ignore", message=".*langchain-community.*sunset.*")
_warnings.filterwarnings("ignore", message=".*langchain-community.*no longer.*")
# 静默 langchain-openai 迁移告警
_warnings.filterwarnings("ignore", message=".*langchain-openai.*deprecated.*")
from spring.langchain.core import (
    LangChainCore, LangChainCoreBuilder, LangChainResponse,
    create_langchain_core,
)
from spring.langchain.adapters import (
    LangChainEmbeddingToSpring, LangChainModelToSpring,
    SpringChatModelToLangChain, SpringEmbeddingToLangChain,
    to_langchain_embeddings, to_langchain_model,
    to_spring_embeddings, to_spring_model,
)
from spring.langchain.partners import (
    PARTNER_REGISTRY, PartnerProviderFactory, is_partner_available,
    list_available_partners, list_partners,
)
from spring.langchain.autoconfig import (
    LangChainProperties, bind_langchain_config, configure_langchain,
)
from spring.langchain.prompts.templates import PromptTemplateFactory
from spring.langchain.chains.services import ChainService
from spring.langchain.agents.services import AgentService
from spring.langchain.memory.memory import MemoryFactory
from spring.langchain.parsers.parsers import OutputParserFactory
from spring.langchain.loaders.loaders import DocumentLoaderRegistry
from spring.langchain.retrievers.retrievers import RetrieverFactory
from spring.langchain.vectorstores.stores import VectorStoreFactory
from spring.langchain.indexes.index import IndexService
from spring.langchain.tools.tools import ToolFactory, ToolRegistry
from spring.langchain.utilities.utils import UtilityRegistry, safe_eval_arithmetic
from spring.langchain.callbacks.handlers import CallbackRegistry

__version__ = "1.0.0"

__all__ = [
    # core
    "LangChainCore", "LangChainCoreBuilder", "LangChainResponse",
    "create_langchain_core",
    # adapters
    "LangChainEmbeddingToSpring", "LangChainModelToSpring",
    "SpringChatModelToLangChain", "SpringEmbeddingToLangChain",
    "to_langchain_embeddings", "to_langchain_model",
    "to_spring_embeddings", "to_spring_model",
    # partners
    "PARTNER_REGISTRY", "PartnerProviderFactory", "is_partner_available",
    "list_available_partners", "list_partners",
    # autoconfig
    "LangChainProperties", "bind_langchain_config", "configure_langchain",
    # 能力 Bean
    "PromptTemplateFactory", "ChainService", "AgentService", "MemoryFactory",
    "OutputParserFactory", "DocumentLoaderRegistry", "RetrieverFactory",
    "VectorStoreFactory", "IndexService", "ToolFactory", "ToolRegistry",
    "UtilityRegistry", "CallbackRegistry",
    # 安全工具
    "safe_eval_arithmetic",
    "__version__",
]
