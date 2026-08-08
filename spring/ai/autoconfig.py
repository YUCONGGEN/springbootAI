"""
SpringPy AI 自动配置 - 读取 application.yml 的 spring.ai.* 配置，
按 provider 创建 ChatModel/EmbeddingModel/ChatClient/VectorStore/Memory Bean，
注册到 BeanRegistry，实现 Spring 风格的统一配置与依赖注入。

配置读取采用"混合方式"：
- 类型化 AIProperties dataclass 绑定 spring.ai.* 子树（替换裸 dict.get + 手动 int/float 转换）
- 复用 config_loader 的 ${ENV:default} 占位符解析（env 一致覆盖由 config_loader 保证）
- 额外一层 metadata env 覆盖作为安全网：yml 写死字面值时，声明的 env 名仍可覆盖
- 优先级：环境变量 > application.yml > dataclass 默认值（对齐框架约定）

配置示例（application.yml）：
    spring:
      ai:
        default-provider: ${AI_PROVIDER:openai}        # openai | ollama
        max-retries: ${AI_MAX_RETRIES:3}
        retry-delay-ms: ${AI_RETRY_DELAY_MS:500}
        openai:
          api-key: ${OPENAI_API_KEY:}
          base-url: ${OPENAI_BASE_URL:https://api.openai.com/v1}
          chat:
            model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
            temperature: ${OPENAI_TEMPERATURE:0.7}
          embedding:
            model: ${OPENAI_EMBEDDING_MODEL:text-embedding-3-small}
        ollama:
          base-url: ${OLLAMA_BASE_URL:http://localhost:11434}
          chat:
            model: ${OLLAMA_CHAT_MODEL:llama3}
        vector-store:
          type: ${AI_VECTOR_STORE:inmemory}            # inmemory | redis
          collection: ${AI_VECTOR_COLLECTION:default}
        memory:
          store: ${AI_MEMORY_STORE:inmemory}           # inmemory | redis
          max-messages: ${AI_MEMORY_MAX:20}
        circuit-breaker:
          enabled: ${AI_CB_ENABLED:true}
          failure-threshold: ${AI_CB_FAILURE_THRESHOLD:5}
          recovery-timeout: ${AI_CB_RECOVERY_TIMEOUT:30}
"""
import dataclasses
import logging
import os
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional

from spring.ai.advisors import MessageChatMemoryAdvisor
from spring.ai.core import ChatClient, ChatClientBuilder, ChatModel
from spring.ai.memory import ChatMemory, InMemoryChatMemory, RedisChatMemory
from spring.ai.providers import (
    FakeChatModel, FakeEmbeddingModel, OllamaChatModel, OllamaEmbeddingModel,
    OpenAIChatModel, OpenAIEmbeddingModel,
)
from spring.ai.resilience import AICircuitBreaker
from spring.ai.vectorstore import (
    RedisVectorStore, SimpleInMemoryVectorStore, VectorStore,
)
from spring.config.config_loader import config_loader
from spring.context.registry import BeanRegistry

logger = logging.getLogger("Spring.AI")


# ==================== 类型化配置 dataclass ====================
# 字段名用 snake_case，绑定器自动匹配 yml 的 kebab-case 键。
# metadata["env"] 声明对应环境变量名（绝对名），作为 env 覆盖安全网。

@dataclass
class OpenAIChatProps:
    model: str = field(default="gpt-4o-mini", metadata={"env": "OPENAI_CHAT_MODEL"})
    temperature: float = field(default=0.7, metadata={"env": "OPENAI_TEMPERATURE"})


@dataclass
class OpenAIEmbeddingProps:
    model: str = field(default="text-embedding-3-small",
                       metadata={"env": "OPENAI_EMBEDDING_MODEL"})


@dataclass
class OpenAIProps:
    api_key: str = field(default="", metadata={"env": "OPENAI_API_KEY"})
    base_url: str = field(default="https://api.openai.com/v1",
                          metadata={"env": "OPENAI_BASE_URL"})
    chat: OpenAIChatProps = field(default_factory=OpenAIChatProps)
    embedding: OpenAIEmbeddingProps = field(default_factory=OpenAIEmbeddingProps)


@dataclass
class OllamaChatProps:
    model: str = field(default="llama3", metadata={"env": "OLLAMA_CHAT_MODEL"})
    temperature: float = field(default=0.7, metadata={"env": "OLLAMA_TEMPERATURE"})


@dataclass
class OllamaEmbeddingProps:
    model: str = field(default="llama3", metadata={"env": "OLLAMA_EMBEDDING_MODEL"})


@dataclass
class OllamaProps:
    base_url: str = field(default="http://localhost:11434",
                          metadata={"env": "OLLAMA_BASE_URL"})
    chat: OllamaChatProps = field(default_factory=OllamaChatProps)
    embedding: OllamaEmbeddingProps = field(default_factory=OllamaEmbeddingProps)


@dataclass
class VectorStoreProps:
    type: str = field(default="inmemory", metadata={"env": "AI_VECTOR_STORE"})
    collection: str = field(default="default", metadata={"env": "AI_VECTOR_COLLECTION"})


@dataclass
class MemoryProps:
    store: str = field(default="inmemory", metadata={"env": "AI_MEMORY_STORE"})
    max_messages: int = field(default=20, metadata={"env": "AI_MEMORY_MAX"})


@dataclass
class CircuitBreakerProps:
    enabled: bool = field(default=True, metadata={"env": "AI_CB_ENABLED"})
    failure_threshold: int = field(default=5, metadata={"env": "AI_CB_FAILURE_THRESHOLD"})
    recovery_timeout: float = field(default=30.0, metadata={"env": "AI_CB_RECOVERY_TIMEOUT"})


@dataclass
class AIProperties:
    """spring.ai.* 的类型化配置根。"""
    default_provider: str = field(default="openai", metadata={"env": "AI_PROVIDER"})
    max_retries: int = field(default=3, metadata={"env": "AI_MAX_RETRIES"})
    retry_delay_ms: int = field(default=500, metadata={"env": "AI_RETRY_DELAY_MS"})
    openai: OpenAIProps = field(default_factory=OpenAIProps)
    ollama: OllamaProps = field(default_factory=OllamaProps)
    vector_store: VectorStoreProps = field(default_factory=VectorStoreProps)
    memory: MemoryProps = field(default_factory=MemoryProps)
    circuit_breaker: CircuitBreakerProps = field(default_factory=CircuitBreakerProps)


# ==================== 绑定器 ====================

_MISSING = object()


def _coerce(value: Any, type_hint: type) -> Any:
    """按类型注解把字符串/字面值转换为对应类型。"""
    if value is None or type_hint is Any:
        return value
    if type_hint is str:
        return str(value)
    if type_hint is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    if type_hint is int:
        if isinstance(value, bool):
            return int(value)
        return int(value)
    if type_hint is float:
        return float(value)
    return value


def _bind(cls: type, data: Dict[str, Any]) -> Any:
    """递归绑定 dataclass：yml 子树 + env 覆盖 + 类型转换。

    优先级：metadata env（若存在于 os.environ）> yml 值 > dataclass 默认值。
    嵌套 dataclass 字段总是递归（即使 yml 未提供该段），保证叶子 env 覆盖可达。
    """
    if not isinstance(data, dict):
        data = {}
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        yml_key = f.name.replace("_", "-")
        raw = data.get(yml_key, _MISSING)
        if raw is _MISSING:
            raw = data.get(f.name, _MISSING)
        # env 覆盖安全网（绝对 env 名）
        env_name = f.metadata.get("env")
        if env_name and env_name in os.environ:
            raw = os.environ[env_name]

        # 嵌套 dataclass：总是递归，让叶子 env 覆盖生效
        if dataclasses.is_dataclass(f.type):
            sub = raw if isinstance(raw, dict) else {}
            kwargs[f.name] = _bind(f.type, sub)
            continue

        if raw is _MISSING:
            continue  # 落到 dataclass default / default_factory
        kwargs[f.name] = _coerce(raw, f.type)
    return cls(**kwargs)


def bind_ai_config(ai_config: Dict[str, Any]) -> AIProperties:
    """从 spring.ai 子树（dict）绑定出类型化的 AIProperties。"""
    return _bind(AIProperties, ai_config or {})


# ==================== Bean 构建 ====================

def _build_circuit_breaker(props: AIProperties) -> Optional[AICircuitBreaker]:
    """根据配置构建熔断器"""
    cb = props.circuit_breaker
    if not cb.enabled:
        return None
    return AICircuitBreaker(
        failure_threshold=cb.failure_threshold,
        recovery_timeout=cb.recovery_timeout,
    )


def _build_chat_model(props: AIProperties) -> ChatModel:
    """根据配置构建 ChatModel（含熔断器）"""
    cb = _build_circuit_breaker(props)
    provider = props.default_provider

    if provider == "openai":
        if not props.openai.api_key:
            logger.warning("spring.ai.openai.api-key 未配置，降级 FakeChatModel")
            return FakeChatModel(prefix="[AI]")
        return OpenAIChatModel(
            api_key=props.openai.api_key,
            base_url=props.openai.base_url,
            model=props.openai.chat.model,
            temperature=props.openai.chat.temperature,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    if provider == "ollama":
        return OllamaChatModel(
            base_url=props.ollama.base_url,
            model=props.ollama.chat.model,
            temperature=props.ollama.chat.temperature,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    logger.warning("未知 AI provider: %s，降级 FakeChatModel", provider)
    return FakeChatModel()


def _build_embedding_model(props: AIProperties):
    """根据配置构建 EmbeddingModel（含熔断器）"""
    cb = _build_circuit_breaker(props)
    provider = props.default_provider

    if provider == "openai":
        if not props.openai.api_key:
            logger.warning("Embedding 未配置 api-key，降级 FakeEmbeddingModel")
            return FakeEmbeddingModel(dim=16)
        return OpenAIEmbeddingModel(
            api_key=props.openai.api_key,
            base_url=props.openai.base_url,
            model=props.openai.embedding.model,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    if provider == "ollama":
        return OllamaEmbeddingModel(
            base_url=props.ollama.base_url,
            model=props.ollama.embedding.model,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    return FakeEmbeddingModel(dim=16)


def _build_memory(props: AIProperties, redis_client=None) -> ChatMemory:
    """根据配置构建会话记忆"""
    if props.memory.store == "redis" and redis_client is not None:
        return RedisChatMemory(redis_client=redis_client,
                               max_messages=props.memory.max_messages)
    return InMemoryChatMemory(max_messages=props.memory.max_messages)


def _build_vector_store(props: AIProperties,
                        embedding_model=None,
                        redis_client=None) -> VectorStore:
    """根据配置构建向量存储"""
    if props.vector_store.type == "redis" and redis_client is not None:
        return RedisVectorStore(
            redis_client=redis_client,
            collection=props.vector_store.collection,
            embedding_model=embedding_model,
        )
    if props.vector_store.type == "redis":
        logger.warning("vector-store=redis 但无可用 redis_client，降级 inmemory")
    return SimpleInMemoryVectorStore(embedding_model=embedding_model)


def _resolve_redis_client(props: AIProperties,
                          redis_client=None):
    """解析 Redis 客户端：优先用传入的 client，否则在需要 redis 时自动复用
    框架全局 spring.utils.redis_client.redis_client 单例。

    这样用户只需在 application.yml 配 vector-store.type=redis / memory.store=redis，
    即可自动启用 Redis 持久化，无需手动传 redis_client 参数。
    """
    if redis_client is not None:
        return redis_client
    needs_redis = (props.vector_store.type == "redis"
                   or props.memory.store == "redis")
    if not needs_redis:
        return None
    try:
        from spring.utils.redis_client import redis_client as global_redis
        return global_redis
    except ImportError:
        logger.warning("框架 RedisClient 不可用，redis 模式将降级 inmemory")
        return None


def configure_ai(registry: Optional[BeanRegistry] = None,
                 config: Optional[Any] = None,
                 redis_client=None) -> Dict[str, Any]:
    """
    AI 模块自动配置入口 - 读取配置、绑定 AIProperties、构建并注册 Bean。

    Args:
        registry: BeanRegistry（默认全局单例）
        config: 配置加载器（默认全局 config_loader）
        redis_client: 可选 Redis 客户端（启用 redis 记忆/向量存储时传入）

    Returns:
        已注册的 Bean 名称 -> Bean 映射
    """
    if registry is None:
        registry = BeanRegistry()
    if config is None:
        config = config_loader

    ai_config = config.get_prefix_config("spring.ai") or config.get("ai", {}) or {}
    if not ai_config:
        ai_config = {}

    # 类型化绑定：env 覆盖 + 类型转换 + 默认值
    props = bind_ai_config(ai_config)

    # 自动复用框架全局 RedisClient 单例（当配置了 redis 模式且未显式传 client）
    redis_client = _resolve_redis_client(props, redis_client)

    beans: Dict[str, Any] = {}

    # 1. ChatModel（含熔断器）
    chat_model = _build_chat_model(props)
    registry.register("aiChatModel", chat_model)
    beans["aiChatModel"] = chat_model

    # 2. EmbeddingModel（含熔断器）- RAG 自动可用
    embedding_model = _build_embedding_model(props)
    registry.register("aiEmbeddingModel", embedding_model)
    beans["aiEmbeddingModel"] = embedding_model

    # 3. VectorStore（注入 EmbeddingModel，RAG 检索自动嵌入）
    vector_store = _build_vector_store(props, embedding_model, redis_client)
    registry.register("aiVectorStore", vector_store)
    beans["aiVectorStore"] = vector_store

    # 4. ChatClient（注入默认 Memory Advisor）
    memory = _build_memory(props, redis_client)
    registry.register("aiChatMemory", memory)
    beans["aiChatMemory"] = memory

    memory_advisor = MessageChatMemoryAdvisor(memory)
    chat_client = (ChatClientBuilder(chat_model)
                   .default_advisors(memory_advisor).build())
    registry.register("aiChatClient", chat_client)
    beans["aiChatClient"] = chat_client

    logger.info("AI 模块自动配置完成: provider=%s, beans=%d",
                props.default_provider, len(beans))
    return beans
