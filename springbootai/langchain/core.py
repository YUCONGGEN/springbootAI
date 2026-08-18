"""
LangChain 模块核心入口 - 对齐 springbootai.ai.core 的 ChatClient 编程范式。

提供 ``LangChainCore`` 作为统一 API 入口，整合 chains/agents/memory/prompts/
loaders/retrievers/vectorstores/tools/utilities/callbacks 全部子模块能力。

设计原则：
- **统一入口**：一个 ``LangChainCore`` 实例即可访问所有 LangChain 子模块
- **构建器模式**：``LangChainCore.builder().with_model(...).with_config(...).build()``
- **Spring AI 对齐**：``core.chat("hello")`` 类似 ``chatClient.prompt().user("hello").call()``
- **懒加载**：子模块在首次访问时初始化，减少启动开销
- **配置驱动**：可通过 ``LangChainProperties`` 或 application.yml 集中配置

对齐 langchain-master 的官方 monorepo 架构：
- langchain_core (base abstractions) → 通过 pip 依赖使用
- langchain_classic (Chain/Agent/Memory) → 通过工厂方法封装
- langchain_v1 (create_agent + langgraph) → 后续版本支持
- partners (30+ 提供商) → 通过 PartnerProviderFactory 注册
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Sequence

logger = logging.getLogger("Spring.LangChain")


# ==================== 响应类型 ====================

@dataclass
class LangChainResponse:
    """
    LangChain 模块的统一返回类型，对齐 ChatResponse 范式。

    Attributes:
        output: 主输出文本（Chain/Agent 的最终结果）
        content: 同 output（兼容 springbootai.ai 命名）
        metadata: 额外元数据（token 用量、执行步骤等）
        intermediate_steps: Agent 的中间推理步骤（如有）
    """
    output: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    intermediate_steps: List[Any] = field(default_factory=list)

    @property
    def content(self) -> str:
        """兼容 springbootai.ai ChatResponse 命名。"""
        return self.output

    def __str__(self) -> str:
        return self.output


# ==================== 核心类 ====================

class LangChainCore:
    """
    LangChain 模块统一核心入口。

    整合 langchain classic 全套能力的 Spring 风格 API，提供：
    - 链式调用（chains）
    - Agent 执行（agents）
    - 会话记忆（memory）
    - 提示模板（prompts）
    - 输出解析（parsers）
    - 文档加载（loaders）
    - 检索器（retrievers）
    - 向量存储（vector_stores）
    - 工具执行（tools）
    - 实用工具（utilities）
    - 回调（callbacks）

    使用方式：

    .. code-block:: python

        # 方式 1：构建器
        core = (LangChainCore.builder()
                .with_model(lc_model)
                .with_retriever(retriever)
                .build())

        # 方式 2：直接构造
        core = LangChainCore(model=lc_model)
        response = core.chat("What is LangChain?")
        docs = core.loaders.load("pdf", "document.pdf")

        # 方式 3：从 application.yml 自动配置
        core = LangChainCore.from_autoconfig()

    对齐 langchain-master 官方架构：
    - langchain_core 的 Runnable 接口通过 .invoke() / .stream() 间接使用
    - langchain_classic 的 Chain/Agent 通过对应服务 Bean 封装
    - partners 通过 PartnerProviderFactory 动态注册
    """

    # ==================== 构造 ====================

    def __init__(
        self,
        *,
        model: Any = None,
        embedding_model: Any = None,
        retriever: Any = None,
        vector_store: Any = None,
        memory: Any = None,
        config: Optional[Dict[str, Any]] = None,
        properties: Any = None,
        tools: Optional[List[Any]] = None,
        agent_type: str = "react",
    ):
        """
        Args:
            model: langchain BaseChatModel 或 springbootAI ChatModel（自动桥接）
            embedding_model: langchain Embeddings 或 springbootAI EmbeddingModel（自动桥接）
            retriever: 默认检索器（langchain BaseRetriever）
            vector_store: 默认向量存储（langchain VectorStore）
            memory: 默认会话记忆（langchain BaseMemory）
            config: 配置字典（application.yml 的 springbootai.langchain.* 子树）
            properties: LangChainProperties 类型化配置
            tools: 默认工具列表
            agent_type: 默认 Agent 类型
        """
        self._model = model  # 原始引用（springbootAI 或 langchain）
        self._embedding_model = embedding_model
        self._lc_model = self._ensure_langchain_model(model)   # 内部统一使用 langchain 对象
        self._lc_embedding = self._ensure_langchain_embedding(embedding_model)
        self._retriever = retriever
        self._vector_store = vector_store
        self._memory = memory
        self._config = config or {}
        self._properties = properties
        self._tools = tools or []
        self._agent_type = agent_type

        # 懒加载子模块
        self._chains_service = None
        self._agents_service = None
        self._memory_factory = None
        self._prompt_factory = None
        self._parser_factory = None
        self._loader_registry = None
        self._retriever_factory = None
        self._vector_store_factory = None
        self._tool_factory = None
        self._utility_registry = None
        self._callback_registry = None
        self._partner_provider = None

    # ==================== 构建器 ====================

    @staticmethod
    def builder() -> "LangChainCoreBuilder":
        """返回构建器，对齐 ChatClient.builder() 范式。"""
        return LangChainCoreBuilder()

    @classmethod
    def from_autoconfig(
        cls,
        registry: Any = None,
        config: Any = None,
        chat_model: Any = None,
        embedding_model: Any = None,
    ) -> "LangChainCore":
        """
        从 application.yml 自动配置创建 LangChainCore。

        调用 autoconfig.configure_langchain 构建所有 Bean，然后封装为
        LangChainCore 统一入口。

        Args:
            registry: BeanRegistry（默认全局单例）
            config: 配置加载器
            chat_model: 已有的 springbootAI ChatModel
            embedding_model: 已有的 springbootAI EmbeddingModel
        """
        from springbootai.langchain.autoconfig import configure_langchain
        beans = configure_langchain(
            registry=registry,
            config=config,
            chat_model=chat_model,
            embedding_model=embedding_model,
        )
        return cls(
            model=beans.get("lcLangChainModel"),
            embedding_model=beans.get("lcEmbeddings"),
            properties=beans.get("_langchain_properties"),
        )

    # ==================== 自动桥接 ====================

    @staticmethod
    def _ensure_langchain_model(model: Any) -> Any:
        """若传入 springbootAI ChatModel，自动桥接为 langchain BaseChatModel；否则原样返回。"""
        if model is None:
            return None
        # 已实现 langchain 接口（有 invoke + stream）
        if hasattr(model, "invoke") and hasattr(model, "stream"):
            return model
        # springbootAI ChatModel — 自动桥接
        from springbootai.langchain.adapters import to_langchain_model
        return to_langchain_model(model)

    @staticmethod
    def _ensure_langchain_embedding(embedding: Any) -> Any:
        """若传入 springbootAI EmbeddingModel，自动桥接为 langchain Embeddings；否则原样返回。"""
        if embedding is None:
            return None
        if hasattr(embedding, "embed_query"):
            return embedding
        from springbootai.langchain.adapters import to_langchain_embeddings
        return to_langchain_embeddings(embedding)

    # ==================== 子模块属性（懒加载） ====================

    @property
    def chains(self):
        """Chain 服务 - 创建和执行各类 Chain。"""
        if self._chains_service is None:
            from springbootai.langchain.chains.services import ChainService
            self._chains_service = ChainService(lcLangChainModel=self._lc_model)
        return self._chains_service

    @property
    def agents(self):
        """Agent 服务 - 创建和执行各类 Agent。"""
        if self._agents_service is None:
            from springbootai.langchain.agents.services import AgentService
            self._agents_service = AgentService(lcLangChainModel=self._lc_model)
        return self._agents_service

    @property
    def memory(self):
        """会话记忆工厂 - 创建各类 Conversation Memory。"""
        if self._memory_factory is None:
            from springbootai.langchain.memory.memory import MemoryFactory
            self._memory_factory = MemoryFactory()  # type: ignore[call-arg]
        return self._memory_factory

    @property
    def prompts(self):
        """提示模板工厂 - 创建各类 PromptTemplate。"""
        if self._prompt_factory is None:
            from springbootai.langchain.prompts.templates import PromptTemplateFactory
            self._prompt_factory = PromptTemplateFactory()
        return self._prompt_factory

    @property
    def parsers(self):
        """输出解析器工厂 - 创建各类 OutputParser。"""
        if self._parser_factory is None:
            from springbootai.langchain.parsers.parsers import OutputParserFactory
            self._parser_factory = OutputParserFactory()
        return self._parser_factory

    @property
    def loaders(self):
        """文档加载器注册表 - 创建各类 DocumentLoader。"""
        if self._loader_registry is None:
            from springbootai.langchain.loaders.loaders import DocumentLoaderRegistry
            self._loader_registry = DocumentLoaderRegistry()  # type: ignore[call-arg]
        return self._loader_registry

    @property
    def retrievers(self):
        """检索器工厂 - 创建各类 Retriever。"""
        if self._retriever_factory is None:
            from springbootai.langchain.retrievers.retrievers import RetrieverFactory
            self._retriever_factory = RetrieverFactory()
        return self._retriever_factory

    @property
    def vector_stores(self):
        """向量存储工厂 - 创建各类 VectorStore。"""
        if self._vector_store_factory is None:
            from springbootai.langchain.vectorstores.stores import VectorStoreFactory
            self._vector_store_factory = VectorStoreFactory()
        return self._vector_store_factory

    @property
    def tools(self):
        """工具工厂 + 注册表 - 创建和注册 Tool。"""
        if self._tool_factory is None:
            from springbootai.langchain.tools.tools import ToolFactory
            self._tool_factory = ToolFactory()
        return self._tool_factory

    @property
    def utilities(self):
        """实用工具注册表 - SerpAPI / Wikipedia / SQL 等。"""
        if self._utility_registry is None:
            from springbootai.langchain.utilities.utils import UtilityRegistry
            self._utility_registry = UtilityRegistry()
        return self._utility_registry

    @property
    def callbacks(self):
        """回调处理器注册表 - StdOut / File 等。"""
        if self._callback_registry is None:
            from springbootai.langchain.callbacks.handlers import CallbackRegistry
            self._callback_registry = CallbackRegistry()
        return self._callback_registry

    # ==================== 便捷方法 ====================

    def chat(
        self,
        message: str,
        *,
        system: Optional[str] = None,
        memory: Any = None,
        chain_type: str = "llm",
        **kwargs,
    ) -> LangChainResponse:
        """
        便捷对话接口 - 对齐 ChatClient.prompt().user().call()。

        Args:
            message: 用户输入
            system: 系统提示（可选）
            memory: 会话记忆（可选，不传则无状态）
            chain_type: 链类型（llm | conversation | retrieval-qa）
            kwargs: 传递给链的其他参数

        Returns:
            LangChainResponse 包含输出和元数据
        """
        if chain_type == "conversation":
            mem = memory or self._memory
            chain = self.chains.create_conversation_chain(memory=mem)
            result = chain.invoke({"input": message})
            return LangChainResponse(
                output=result.get("response", str(result)),
                metadata={"chain_type": "conversation"},
            )
        if chain_type == "retrieval-qa":
            retriever = kwargs.pop("retriever", self._retriever)
            if retriever is None:
                raise ValueError("retrieval-qa 需要 retriever")
            chain = self.chains.create_retrieval_qa(retriever, **kwargs)
            result = chain.invoke({"query": message})
            return LangChainResponse(
                output=result.get("result", str(result)),
                metadata={"chain_type": "retrieval-qa"},
            )
        # 默认 llm_chain
        if system:
            message = f"{system}\n\nUser: {message}"
        chain = self.chains.create_llm_chain(template="{input}",
                                              input_variables=["input"])
        result = chain.invoke({"input": message})
        return LangChainResponse(
            output=result.get("text", str(result)),
            metadata={"chain_type": "llm"},
        )

    def agent_chat(
        self,
        message: str,
        *,
        tools: Optional[Sequence[Any]] = None,
        agent_type: Optional[str] = None,
        **kwargs,
    ) -> LangChainResponse:
        """
        便捷 Agent 对话接口。

        Args:
            message: 用户输入
            tools: 工具列表（默认用构造函数传入的）
            agent_type: Agent 类型（默认用构造函数传入的）
            kwargs: 传递给 Agent 的额外参数
        """
        tools = tools or self._tools
        atype = agent_type or self._agent_type
        executor = self.agents.create_agent(tools, agent_type=atype, **kwargs)
        result = executor.invoke({"input": message})
        intermediate = result.get("intermediate_steps", [])
        return LangChainResponse(
            output=result.get("output", str(result)),
            intermediate_steps=intermediate,
            metadata={"agent_type": atype, "tool_count": len(tools)},
        )

    def stream(
        self,
        message: str,
        *,
        system: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        流式对话接口 - 对齐 ChatClient.stream()。

        注意：langchain_classic 的 stream 支持有限，此方法返回普通生成器
        （按 token 逐块产出需使用 langchain_v1 + langgraph）。
        """
        response = self.chat(message, system=system, **kwargs)
        yield response.output

    # ==================== 模型管理 ====================

    def set_model(self, model: Any) -> "LangChainCore":
        """替换当前模型并刷新所有依赖它的子模块。"""
        self._model = model
        self._lc_model = self._ensure_langchain_model(model)
        self._chains_service = None
        self._agents_service = None
        return self

    @property
    def model(self) -> Any:
        """当前 langchain 模型。"""
        return self._model

    @property
    def embedding_model(self) -> Any:
        """当前 langchain Embeddings。"""
        return self._embedding_model

    @property
    def retriever(self) -> Any:
        """默认检索器。"""
        return self._retriever

    # ==================== RAG 一站式 ====================

    def rag_pipeline(
        self,
        query: str,
        *,
        documents: Optional[List[str]] = None,
        retriever: Any = None,
        chain_type: str = "stuff",
    ) -> LangChainResponse:
        """
        RAG 一站式流水线：检索 → 生成。

        Args:
            query: 用户查询
            documents: 直接传入文档文本（跳过检索），与 retriever 互斥
            retriever: 检索器（默认用构造函数注入的）
            chain_type: 链类型（stuff | map_reduce | refine）
        """
        if documents is not None:
            from langchain_core.documents import Document as LCDoc
            docs = [LCDoc(page_content=t) for t in documents]
            chain = self.chains.create_summarize_chain(chain_type=chain_type)
            chain.llm = self._lc_model
            result = chain.invoke(docs)
            return LangChainResponse(
                output=result.get("output_text", str(result)),
                metadata={"chain_type": chain_type, "doc_count": len(docs)},
            )

        ret = retriever or self._retriever
        if ret is None:
            raise ValueError("RAG pipeline 需要 retriever 或 documents")

        qa = self.chains.create_retrieval_qa(ret, chain_type=chain_type)
        result = qa.invoke({"query": query})
        return LangChainResponse(
            output=result.get("result", str(result)),
            metadata={"chain_type": chain_type},
        )

    def __repr__(self) -> str:
        model_name = type(self._model).__name__ if self._model else "None"
        return f"LangChainCore(model={model_name}, agent={self._agent_type})"


# ==================== 构建器 ====================

class LangChainCoreBuilder:
    """
    LangChainCore 构建器，对齐 ChatClient.builder() 范式。

    用法:
        core = (LangChainCore.builder()
                .with_model(lc_model)
                .with_tools([calculator, search])
                .with_agent_type("react")
                .build())
    """

    def __init__(self):
        self._model = None
        self._embedding_model = None
        self._retriever = None
        self._vector_store = None
        self._memory = None
        self._config = {}
        self._properties = None
        self._tools = []
        self._agent_type = "react"

    def with_model(self, model: Any) -> "LangChainCoreBuilder":
        """设置 langchain BaseChatModel。"""
        self._model = model
        return self

    def with_embedding_model(self, embedding_model: Any) -> "LangChainCoreBuilder":
        """设置 langchain Embeddings。"""
        self._embedding_model = embedding_model
        return self

    def with_retriever(self, retriever: Any) -> "LangChainCoreBuilder":
        """设置默认检索器。"""
        self._retriever = retriever
        return self

    def with_vector_store(self, vector_store: Any) -> "LangChainCoreBuilder":
        """设置默认向量存储。"""
        self._vector_store = vector_store
        return self

    def with_memory(self, memory: Any) -> "LangChainCoreBuilder":
        """设置默认会话记忆。"""
        self._memory = memory
        return self

    def with_config(self, config: Dict[str, Any]) -> "LangChainCoreBuilder":
        """设置配置字典（application.yml 的 springbootai.langchain.* 子树）。"""
        self._config = config
        return self

    def with_properties(self, properties: Any) -> "LangChainCoreBuilder":
        """设置 LangChainProperties 类型化配置。"""
        self._properties = properties
        return self

    def with_tools(self, tools: List[Any]) -> "LangChainCoreBuilder":
        """设置默认工具列表。"""
        self._tools = list(tools)
        return self

    def with_agent_type(self, agent_type: str) -> "LangChainCoreBuilder":
        """设置默认 Agent 类型（react | openai-tools | structured-chat 等）。"""
        self._agent_type = agent_type
        return self

    def build(self) -> LangChainCore:
        """构建 LangChainCore 实例。"""
        if self._model is None:
            logger.warning(
                "LangChainCore 未设置 model；部分功能（chains/agents）将不可用。"
                "请调用 .with_model(lc_model) 或使用 from_autoconfig()。")
        return LangChainCore(
            model=self._model,
            embedding_model=self._embedding_model,
            retriever=self._retriever,
            vector_store=self._vector_store,
            memory=self._memory,
            config=self._config,
            properties=self._properties,
            tools=self._tools,
            agent_type=self._agent_type,
        )


# ==================== 便捷函数 ====================

def create_langchain_core(
    model: Any = None,
    *,
    tools: Optional[List[Any]] = None,
    agent_type: str = "react",
    **kwargs,
) -> LangChainCore:
    """
    快速创建 LangChainCore 实例。

    用法:
        core = create_langchain_core(lc_model)
        response = core.chat("Hello!")
    """
    return LangChainCoreBuilder() \
        .with_model(model) \
        .with_tools(tools or []) \
        .with_agent_type(agent_type) \
        .build()
