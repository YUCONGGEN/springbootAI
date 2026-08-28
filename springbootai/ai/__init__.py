"""
SpringBootAI AI 模块 - 对齐 Spring AI 的 ChatClient/Advisor/ETL 抽象，
底层复用 LangChain 生态做模型适配，上层保留 Spring 风格的统一配置与依赖注入。

模块组成：
- core:         ChatClient / ChatModel / EmbeddingModel / Advisor / Message 抽象
- annotations:  @AiClient / @Tool / @AiAdvisor / @AiMemory 注解
- providers:    OpenAI兼容 / Ollama Provider（LangChain 优先，原生HTTP降级）+ Fake测试模型
- advisors:     QuestionAnswerAdvisor(RAG) / MessageChatMemoryAdvisor / SimpleLoggerAdvisor
- memory:       ChatMemory (InMemory / Redis)
- vectorstore:  VectorStore 抽象 + SimpleInMemoryVectorStore
- etl:          DocumentReader / TextSplitter（TokenTextSplitter / CharacterTextSplitter）
- tools:        ToolRegistry 函数调用注册表
- autoconfig:   从 application.yml 的 spring.ai.* 自动装配 Bean
"""
from springbootai.ai.core import (
    Advisor, AdvisorRequest, ChatClient, ChatClientBuilder, ChatModel,
    ChatResponse, EmbeddingModel, Generation, Message, MessageType,
    PromptSpec, TokenBudgetExceededError, ToolLoopLimitExceededError,
)
from springbootai.ai.annotations import (
    Agent, AiAdvisor, AiCache, AiClient, AiMemory, AiRetry, ContentModeration,
    Embedding, Prompt, RAG, StructuredOutput, TokenUsage, Tool, VectorStore,
)
# ``VectorStore`` 在本模块历史上表示向量库接口；保留该公开名称，注解通过
# ``springbootai.ai.annotations.VectorStore`` 或这个别名使用。
VectorStoreAnnotation = VectorStore
from springbootai.ai.advisors import (
    MessageChatMemoryAdvisor, QuestionAnswerAdvisor, SimpleLoggerAdvisor,
)
from springbootai.ai.memory import ChatMemory, InMemoryChatMemory, RedisChatMemory
from springbootai.ai.vectorstore import (
    Document as VectorDocument, LangChainVectorStore, RedisVectorStore,
    SearchRequest, SimpleInMemoryVectorStore, VectorStore, cosine_similarity,
)
from springbootai.ai.etl import (
    CharacterTextSplitter, DocumentReader, DocumentTooLargeError,
    TextDocument, TextReader,
    TextSplitter, TokenTextSplitter,
)
from springbootai.ai.tools import (
    CompositeToolRegistry,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolRegistry,
    ToolCancellationToken,
)
from springbootai.ai.providers import (
    FakeChatModel, FakeEmbeddingModel, OllamaChatModel, OllamaEmbeddingModel,
    OpenAICompatChatModel, OpenAIChatModel, OpenAIEmbeddingModel,
    ProviderProtocolError, ProviderResponseTooLargeError, ProviderStreamError,
)
from springbootai.ai.resilience import (
    AICircuitBreaker, CircuitOpenError, TransientError, resilient_call,
)
from springbootai.ai.observability import AIMetrics, ai_metrics
from springbootai.ai.autoconfig import AIProperties, bind_ai_config, configure_ai
from springbootai.ai.annotation_runtime import ContentModerationError

__version__ = "2.3.10"

__all__ = [
    # core
    "Advisor", "AdvisorRequest", "ChatClient", "ChatClientBuilder",
    "ChatModel", "ChatResponse", "EmbeddingModel", "Generation", "Message",
    "MessageType", "PromptSpec", "TokenBudgetExceededError",
    "ToolLoopLimitExceededError",
    # annotations
    "AiAdvisor", "AiClient", "AiMemory", "Tool", "Prompt", "RAG",
    "StructuredOutput", "Agent", "Embedding", "VectorStore", "AiRetry",
    "AiCache", "TokenUsage", "ContentModeration",
    "VectorStoreAnnotation",
    "ContentModerationError",
    # advisors
    "MessageChatMemoryAdvisor", "QuestionAnswerAdvisor", "SimpleLoggerAdvisor",
    # memory
    "ChatMemory", "InMemoryChatMemory", "RedisChatMemory",
    # vectorstore
    "VectorDocument", "LangChainVectorStore", "RedisVectorStore",
    "SearchRequest", "SimpleInMemoryVectorStore", "VectorStore",
    "cosine_similarity",
    # etl
    "CharacterTextSplitter", "DocumentReader", "DocumentTooLargeError",
    "TextDocument", "TextReader",
    "TextSplitter", "TokenTextSplitter",
    # tools
    "CompositeToolRegistry", "ToolCancellationToken", "ToolDefinition",
    "ToolExecutionPolicy", "ToolRegistry",
    # providers
    "FakeChatModel", "FakeEmbeddingModel", "OllamaChatModel",
    "OllamaEmbeddingModel", "OpenAICompatChatModel", "OpenAIChatModel",
    "OpenAIEmbeddingModel", "ProviderProtocolError",
    "ProviderResponseTooLargeError",
    "ProviderStreamError",
    # resilience
    "AICircuitBreaker", "CircuitOpenError", "TransientError", "resilient_call",
    # observability
    "AIMetrics", "ai_metrics",
    # autoconfig
    "AIProperties", "bind_ai_config", "configure_ai",
    "__version__",
]
