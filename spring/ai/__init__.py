"""
SpringPy AI 模块 - 对齐 Spring AI 的 ChatClient/Advisor/ETL 抽象，
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
from spring.ai.core import (
    Advisor, AdvisorRequest, ChatClient, ChatClientBuilder, ChatModel,
    ChatResponse, EmbeddingModel, Generation, Message, MessageType,
    PromptSpec,
)
from spring.ai.annotations import AiAdvisor, AiClient, AiMemory, Tool
from spring.ai.advisors import (
    MessageChatMemoryAdvisor, QuestionAnswerAdvisor, SimpleLoggerAdvisor,
)
from spring.ai.memory import ChatMemory, InMemoryChatMemory, RedisChatMemory
from spring.ai.vectorstore import (
    Document as VectorDocument, RedisVectorStore, SearchRequest,
    SimpleInMemoryVectorStore, VectorStore, cosine_similarity,
)
from spring.ai.etl import (
    CharacterTextSplitter, DocumentReader, TextDocument, TextReader,
    TextSplitter, TokenTextSplitter,
)
from spring.ai.tools import ToolDefinition, ToolRegistry
from spring.ai.providers import (
    FakeChatModel, FakeEmbeddingModel, OllamaChatModel, OllamaEmbeddingModel,
    OpenAIChatModel, OpenAIEmbeddingModel,
)
from spring.ai.resilience import (
    AICircuitBreaker, CircuitOpenError, TransientError, resilient_call,
)
from spring.ai.observability import AIMetrics, ai_metrics
from spring.ai.autoconfig import AIProperties, bind_ai_config, configure_ai

__version__ = "1.2.0"

__all__ = [
    # core
    "Advisor", "AdvisorRequest", "ChatClient", "ChatClientBuilder",
    "ChatModel", "ChatResponse", "EmbeddingModel", "Generation", "Message",
    "MessageType", "PromptSpec",
    # annotations
    "AiAdvisor", "AiClient", "AiMemory", "Tool",
    # advisors
    "MessageChatMemoryAdvisor", "QuestionAnswerAdvisor", "SimpleLoggerAdvisor",
    # memory
    "ChatMemory", "InMemoryChatMemory", "RedisChatMemory",
    # vectorstore
    "VectorDocument", "RedisVectorStore", "SearchRequest",
    "SimpleInMemoryVectorStore", "VectorStore", "cosine_similarity",
    # etl
    "CharacterTextSplitter", "DocumentReader", "TextDocument", "TextReader",
    "TextSplitter", "TokenTextSplitter",
    # tools
    "ToolDefinition", "ToolRegistry",
    # providers
    "FakeChatModel", "FakeEmbeddingModel", "OllamaChatModel",
    "OllamaEmbeddingModel", "OpenAIChatModel", "OpenAIEmbeddingModel",
    # resilience
    "AICircuitBreaker", "CircuitOpenError", "TransientError", "resilient_call",
    # observability
    "AIMetrics", "ai_metrics",
    # autoconfig
    "AIProperties", "bind_ai_config", "configure_ai",
    "__version__",
]
