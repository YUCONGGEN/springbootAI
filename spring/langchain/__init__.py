"""
SpringBootAI LangChain 模块 - 把 langchain classic 全套能力封装为 Spring 风格 Bean。

模块组成：
- adapters:    springbootAI ChatModel/EmbeddingModel <-> langchain 模型/嵌入/向量库 双向桥接
- partners:    30+ Partner 提供商工厂（OpenAI/Anthropic/Ollama/DeepSeek/ZhipuAI/Tongyi...）
- autoconfig:  从 application.yml 的 spring.langchain.* 自动装配 Bean
- prompts:     PromptTemplate / ChatPromptTemplate / FewShotPromptTemplate 工厂
- chains:      LLMChain / ConversationChain / SequentialChain / RetrievalQA / 摘要 / LLMMath
- agents:      ReAct / OpenAI-tools / structured-chat Agent
- memory:      buffer / summary / buffer-window / token-buffer 会话记忆
- parsers:     comma-list / datetime / json / pydantic / enum 输出解析
- loaders:     text / csv / pdf / web / directory / json 文档加载
- retrievers:  similarity / multi-query / contextual-compression / self-query / time-weighted / ensemble
- vectorstores:FAISS / Chroma / Pinecone / Weaviate / PGVector / Redis / inmemory
- indexes:     VectorStoreIndexCreator 一键 RAG
- tools:       langchain Tool 与 springbootAI @Tool 互转
- utilities:   SerpAPI / DuckDuckGo / Wikipedia / PythonREPL / SQLDatabase / Arxiv ...
- callbacks:   StdOut / StreamingStdOut / File 回调
"""
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
from spring.langchain.utilities.utils import UtilityRegistry
from spring.langchain.callbacks.handlers import CallbackRegistry

__version__ = "1.0.0"

__all__ = [
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
    "__version__",
]
