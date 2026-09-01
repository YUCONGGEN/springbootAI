"""
SpringBootAI AI 自动配置 - 读取 application.yml 的 spring.ai.* 配置，
按 provider 创建 ChatModel/EmbeddingModel/ChatClient/VectorStore/Memory Bean，
注册到 BeanRegistry，实现 Spring 风格的统一配置与依赖注入。

配置读取采用"混合方式"：
- 类型化 AIProperties dataclass 绑定 spring.ai.* 子树（兼容旧版 springbootai.ai.*）
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

from springbootai.ai.advisors import MessageChatMemoryAdvisor
from springbootai.ai.core import ChatClient, ChatClientBuilder, ChatModel
from springbootai.ai.memory import ChatMemory, InMemoryChatMemory, RedisChatMemory
from springbootai.ai.providers import (
    FakeChatModel, FakeEmbeddingModel, OllamaChatModel, OllamaEmbeddingModel,
    OpenAIChatModel, OpenAICompatChatModel, OpenAIEmbeddingModel,
)
from springbootai.ai.resilience import AICircuitBreaker
from springbootai.ai.vectorstore import (
    RedisVectorStore, SimpleInMemoryVectorStore, VectorStore,
)
from springbootai.config.config_loader import config_loader
from springbootai.context.registry import BeanRegistry

logger = logging.getLogger("Spring.AI")


def _ai_allow_fake() -> bool:
    """读取 ``AI_ALLOW_FAKE`` 环境变量，决定 api_key 缺失时是否降级 ``FakeChatModel``。

    安全默认：``false``。开发/测试环境需**显式**设置 ``AI_ALLOW_FAKE=true``
    才允许降级，防止生产环境配错时无声返回测试数据。

    设计要点：
    - 每次调用实时读取环境变量（非模块导入时一次性读取），便于 ``config_loader``
      在生产 profile 下运行时强制 ``AI_ALLOW_FAKE=false``，避免导入时序导致的绕过。
    - 接受 ``true/1/yes/on``（大小写不敏感）为 True，其余为 False，与框架
      ``_to_bool`` 规则一致。
    - 生产环境由 ``config_loader._validate_config`` 双重加固：
      (1) 强制 ``AI_ALLOW_FAKE=false``；
      (2) 校验默认 provider 的 api-key 已配置，缺失直接抛 ``ConfigurationError``。
    """
    return os.environ.get("AI_ALLOW_FAKE", "false").strip().lower() in (
        "true", "1", "yes", "on")


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


# ---- OpenAI 兼容多厂商（DeepSeek / Moonshot / ZhipuAI）----
# 由 OpenAICompatChatModel 接入，底层优先 LangChain 专用包，降级 OpenAI 兼容 HTTP。

@dataclass
class DeepSeekProps:
    api_key: str = field(default="", metadata={"env": "DEEPSEEK_API_KEY"})
    base_url: str = field(default="https://api.deepseek.com",
                          metadata={"env": "DEEPSEEK_BASE_URL"})
    model: str = field(default="deepseek-chat", metadata={"env": "DEEPSEEK_MODEL"})
    temperature: float = field(default=0.7, metadata={"env": "DEEPSEEK_TEMPERATURE"})


@dataclass
class MoonshotProps:
    api_key: str = field(default="", metadata={"env": "MOONSHOT_API_KEY"})
    base_url: str = field(default="https://api.moonshot.cn/v1",
                          metadata={"env": "MOONSHOT_BASE_URL"})
    model: str = field(default="moonshot-v1-8k", metadata={"env": "MOONSHOT_MODEL"})
    temperature: float = field(default=0.7, metadata={"env": "MOONSHOT_TEMPERATURE"})


@dataclass
class ZhipuProps:
    api_key: str = field(default="", metadata={"env": "ZHIPUAI_API_KEY"})
    base_url: str = field(default="https://open.bigmodel.cn/api/paas/v4",
                          metadata={"env": "ZHIPUAI_BASE_URL"})
    model: str = field(default="glm-4-flash", metadata={"env": "ZHIPUAI_MODEL"})
    temperature: float = field(default=0.7, metadata={"env": "ZHIPUAI_TEMPERATURE"})


@dataclass
class VectorStoreProps:
    type: str = field(default="inmemory", metadata={"env": "AI_VECTOR_STORE"})
    collection: str = field(default="default", metadata={"env": "AI_VECTOR_COLLECTION"})
    max_documents: int = field(
        default=10_000, metadata={"env": "AI_VECTOR_MAX_DOCUMENTS"})
    max_scan: int = field(
        default=10_000, metadata={"env": "AI_VECTOR_MAX_SCAN"})
    max_content_length: int = field(
        default=1_000_000, metadata={"env": "AI_VECTOR_MAX_CONTENT_LENGTH"})
    max_embedding_dimensions: int = field(
        default=65_536, metadata={"env": "AI_VECTOR_MAX_DIMENSIONS"})
    max_metadata_size: int = field(
        default=256 * 1024, metadata={"env": "AI_VECTOR_MAX_METADATA_SIZE"})
    max_scan_bytes: int = field(
        default=100 * 1024 * 1024,
        metadata={"env": "AI_VECTOR_MAX_SCAN_BYTES"})


@dataclass
class MemoryProps:
    store: str = field(default="inmemory", metadata={"env": "AI_MEMORY_STORE"})
    max_messages: int = field(default=20, metadata={"env": "AI_MEMORY_MAX"})
    max_conversations: int = field(
        default=10000, metadata={"env": "AI_MEMORY_MAX_CONVERSATIONS"})
    ttl: int = field(default=86_400, metadata={"env": "AI_MEMORY_TTL"})
    allow_global_namespace: bool = field(
        default=False, metadata={"env": "AI_MEMORY_ALLOW_GLOBAL_NAMESPACE"})


@dataclass
class CircuitBreakerProps:
    enabled: bool = field(default=True, metadata={"env": "AI_CB_ENABLED"})
    failure_threshold: int = field(default=5, metadata={"env": "AI_CB_FAILURE_THRESHOLD"})
    recovery_timeout: float = field(default=30.0, metadata={"env": "AI_CB_RECOVERY_TIMEOUT"})


@dataclass
class AIProperties:
    """spring.ai.* 的类型化配置根（兼容旧版 springbootai.ai.*）。"""
    default_provider: str = field(default="openai", metadata={"env": "AI_PROVIDER"})
    max_retries: int = field(default=3, metadata={"env": "AI_MAX_RETRIES"})
    retry_delay_ms: int = field(default=500, metadata={"env": "AI_RETRY_DELAY_MS"})
    request_timeout_seconds: int = field(
        default=60, metadata={"env": "AI_REQUEST_TIMEOUT_SECONDS"})
    max_output_tokens: int = field(
        default=4096, metadata={"env": "AI_MAX_OUTPUT_TOKENS"})
    max_total_tokens: int = field(
        default=100000, metadata={"env": "AI_MAX_TOTAL_TOKENS"})
    max_tool_iterations: int = field(
        default=5, metadata={"env": "AI_MAX_TOOL_ITERATIONS"})
    max_input_bytes: int = field(
        default=2 * 1024 * 1024, metadata={"env": "AI_MAX_INPUT_BYTES"})
    max_concurrent_requests: int = field(
        default=32, metadata={"env": "AI_MAX_CONCURRENT_REQUESTS"})
    concurrency_acquire_timeout: float = field(
        default=30.0, metadata={"env": "AI_CONCURRENCY_ACQUIRE_TIMEOUT"})
    openai: OpenAIProps = field(default_factory=OpenAIProps)
    ollama: OllamaProps = field(default_factory=OllamaProps)
    deepseek: DeepSeekProps = field(default_factory=DeepSeekProps)
    moonshot: MoonshotProps = field(default_factory=MoonshotProps)
    zhipu: ZhipuProps = field(default_factory=ZhipuProps)
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
    """从 springbootai.ai 子树（dict）绑定出类型化的 AIProperties。"""
    props = _bind(AIProperties, ai_config or {})
    if not 0 <= props.max_retries <= 20:
        raise ValueError("AI max_retries must be in [0, 20]")
    if not 0 <= props.retry_delay_ms <= 60_000:
        raise ValueError("AI retry_delay_ms must be in [0, 60000]")
    if not 1 <= props.request_timeout_seconds <= 600:
        raise ValueError("AI request_timeout_seconds must be in [1, 600]")
    if not 1 <= props.max_output_tokens <= 1_000_000:
        raise ValueError("AI max_output_tokens must be in [1, 1000000]")
    if not 1 <= props.max_total_tokens <= 10_000_000:
        raise ValueError("AI max_total_tokens must be in [1, 10000000]")
    if props.max_total_tokens < props.max_output_tokens:
        raise ValueError(
            "AI max_total_tokens must be greater than or equal to max_output_tokens")
    if not 0 <= props.max_tool_iterations <= 100:
        raise ValueError("AI max_tool_iterations must be in [0, 100]")
    if not 1024 <= props.max_input_bytes <= 100 * 1024 * 1024:
        raise ValueError("AI max_input_bytes must be in [1024, 104857600]")
    if not 1 <= props.max_concurrent_requests <= 10000:
        raise ValueError("AI max_concurrent_requests must be in [1, 10000]")
    if not 0.1 <= props.concurrency_acquire_timeout <= 600:
        raise ValueError("AI concurrency_acquire_timeout must be in [0.1, 600]")
    if not 1 <= props.memory.max_messages <= 100_000:
        raise ValueError("AI memory.max_messages must be in [1, 100000]")
    if not 1 <= props.memory.max_conversations <= 1_000_000:
        raise ValueError(
            "AI memory.max_conversations must be in [1, 1000000]")
    if props.memory.store not in {"inmemory", "redis"}:
        raise ValueError("AI memory.store must be 'inmemory' or 'redis'")
    if not 1 <= props.memory.ttl <= 365 * 24 * 3600:
        raise ValueError("AI memory.ttl must be in [1, 31536000]")
    if props.vector_store.type not in {"inmemory", "redis"}:
        raise ValueError("AI vector_store.type must be 'inmemory' or 'redis'")
    vector_limits = {
        "max_documents": (props.vector_store.max_documents, 1_000_000),
        "max_scan": (props.vector_store.max_scan, 1_000_000),
        "max_content_length": (
            props.vector_store.max_content_length, 100_000_000),
        "max_embedding_dimensions": (
            props.vector_store.max_embedding_dimensions, 1_000_000),
        "max_metadata_size": (
            props.vector_store.max_metadata_size, 10_000_000),
        "max_scan_bytes": (
            props.vector_store.max_scan_bytes, 1_000_000_000),
    }
    for name, (value, maximum) in vector_limits.items():
        if not 1 <= value <= maximum:
            raise ValueError(
                f"AI vector_store.{name} must be in [1, {maximum}]")
    return props


# ==================== Bean 构建 ====================

def _build_circuit_breaker(props: AIProperties, name: str = "default",
                           redis_client=None):
    """根据配置构建熔断器（复用框架 Redis 持久化电路状态）"""
    cb = props.circuit_breaker
    if not cb.enabled:
        return None
    return AICircuitBreaker(
        failure_threshold=cb.failure_threshold,
        recovery_timeout=cb.recovery_timeout,
        name=name,
        redis_client=redis_client,
    )


def _apply_runtime_limits(model: ChatModel, props: AIProperties) -> ChatModel:
    model.max_output_tokens = props.max_output_tokens
    model.max_total_tokens = props.max_total_tokens
    model.max_tool_iterations = props.max_tool_iterations
    model.max_input_bytes = props.max_input_bytes
    model.max_concurrent_requests = props.max_concurrent_requests
    model.concurrency_acquire_timeout = props.concurrency_acquire_timeout
    return model


def _build_fake_chat_model(props: AIProperties,
                           prefix: str = "[AI]") -> FakeChatModel:
    """Apply the same request budgets to the explicit development fake."""
    return _apply_runtime_limits(FakeChatModel(prefix=prefix), props)


def _build_chat_model(props: AIProperties, redis_client=None) -> ChatModel:
    """根据配置构建 ChatModel（含熔断器）"""
    cb = _build_circuit_breaker(props, name="chat", redis_client=redis_client)
    provider = props.default_provider

    if provider == "openai":
        if not props.openai.api_key:
            if not _ai_allow_fake():
                raise ValueError(
                    "AI_ALLOW_FAKE=false 但 spring.ai.openai.api-key 未配置。"
                    " 请设置 OPENAI_API_KEY 环境变量或 application.yml 的 api-key。")
            logger.warning("spring.ai.openai.api-key 未配置，降级 FakeChatModel")
            return _build_fake_chat_model(props)
        return _apply_runtime_limits(OpenAIChatModel(
            api_key=props.openai.api_key,
            base_url=props.openai.base_url,
            model=props.openai.chat.model,
            temperature=props.openai.chat.temperature,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
            max_output_tokens=props.max_output_tokens,
            max_total_tokens=props.max_total_tokens,
            max_tool_iterations=props.max_tool_iterations,
        ), props)

    if provider == "ollama":
        return _apply_runtime_limits(OllamaChatModel(
            base_url=props.ollama.base_url,
            model=props.ollama.chat.model,
            temperature=props.ollama.chat.temperature,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
            max_output_tokens=props.max_output_tokens,
            max_total_tokens=props.max_total_tokens,
            max_tool_iterations=props.max_tool_iterations,
        ), props)

    # OpenAI 兼容多厂商（DeepSeek / Moonshot / ZhipuAI）— 底层优先 LangChain 专用包
    _COMPAT_SPECS = {
        "deepseek": ("deepseek", "langchain_deepseek", "ChatDeepSeek",
                     props.deepseek),
        "moonshot": ("moonshot", "langchain_moonshot", "ChatMoonshot",
                     props.moonshot),
        "zhipu": ("zhipu", "langchain_zhipuai", "ChatZhipuAI", props.zhipu),
    }
    if provider in _COMPAT_SPECS:
        pname, lc_mod, lc_cls, cfg = _COMPAT_SPECS[provider]
        if not cfg.api_key:
            if not _ai_allow_fake():
                raise ValueError(
                    f"AI_ALLOW_FAKE=false 但 spring.ai.{provider}.api-key 未配置。"
                    f" 请设置 {provider.upper()}_API_KEY 环境变量。")
            logger.warning("spring.ai.%s.api-key 未配置，降级 FakeChatModel", provider)
            return _build_fake_chat_model(props)
        return _apply_runtime_limits(OpenAICompatChatModel(
            provider=pname, api_key=cfg.api_key, base_url=cfg.base_url,
            model=cfg.model, temperature=cfg.temperature,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries, retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb, langchain_module=lc_mod, langchain_class=lc_cls,
            max_output_tokens=props.max_output_tokens,
            max_total_tokens=props.max_total_tokens,
            max_tool_iterations=props.max_tool_iterations,
        ), props)

    logger.warning("未知 AI provider: %s", provider)
    if not _ai_allow_fake():
        raise ValueError(
            f"AI_ALLOW_FAKE=false 但未知 provider: {provider}。"
            " 请检查 application.yml 的 spring.ai.default-provider 配置。")
    return _build_fake_chat_model(props, prefix="AI:")


def _build_embedding_model(props: AIProperties, redis_client=None):
    """根据配置构建 EmbeddingModel（含熔断器）"""
    cb = _build_circuit_breaker(props, name="embedding", redis_client=redis_client)
    provider = props.default_provider

    if provider == "openai":
        if not props.openai.api_key:
            if not _ai_allow_fake():
                raise ValueError(
                    "AI_ALLOW_FAKE=false 但 Embedding 未配置 api-key。"
                    " 请设置 OPENAI_API_KEY 环境变量。")
            logger.warning("Embedding 未配置 api-key，降级 FakeEmbeddingModel")
            return FakeEmbeddingModel(dim=16)
        return OpenAIEmbeddingModel(
            api_key=props.openai.api_key,
            base_url=props.openai.base_url,
            model=props.openai.embedding.model,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    if provider == "ollama":
        return OllamaEmbeddingModel(
            base_url=props.ollama.base_url,
            model=props.ollama.embedding.model,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    # OpenAI 兼容多厂商（DeepSeek / Moonshot / ZhipuAI）— 复用 OpenAI 兼容嵌入
    if provider in ("deepseek", "moonshot", "zhipu"):
        cfg = getattr(props, provider)
        if not cfg.api_key:
            if not _ai_allow_fake():
                raise ValueError(
                    f"AI_ALLOW_FAKE=false 但 Embedding 未配置 {provider} api-key。")
            logger.warning("Embedding 未配置 %s api-key，降级 FakeEmbeddingModel",
                           provider)
            return FakeEmbeddingModel(dim=16)
        return OpenAIEmbeddingModel(
            api_key=cfg.api_key, base_url=cfg.base_url,
            timeout=props.request_timeout_seconds,
            max_retries=props.max_retries,
            retry_delay_ms=props.retry_delay_ms,
            circuit_breaker=cb,
        )

    if not _ai_allow_fake():
        raise ValueError(
            "AI_ALLOW_FAKE=false 但未知 Embedding provider。"
            " 请检查 application.yml 的 spring.ai.default-provider 配置。")
    return FakeEmbeddingModel(dim=16)


def _build_memory(props: AIProperties, redis_client=None) -> ChatMemory:
    """根据配置构建会话记忆"""
    if props.memory.store == "redis" and redis_client is not None:
        return RedisChatMemory(redis_client=redis_client,
                               max_messages=props.memory.max_messages,
                               ttl=props.memory.ttl)
    return InMemoryChatMemory(
        max_messages=props.memory.max_messages,
        max_conversations=props.memory.max_conversations,
    )


def _build_vector_store(props: AIProperties,
                        embedding_model=None,
                        redis_client=None) -> VectorStore:
    """根据配置构建向量存储"""
    if props.vector_store.type == "redis" and redis_client is not None:
        return RedisVectorStore(
            redis_client=redis_client,
            collection=props.vector_store.collection,
            embedding_model=embedding_model,
            max_scan=props.vector_store.max_scan,
            max_content_length=props.vector_store.max_content_length,
            max_embedding_dimensions=(
                props.vector_store.max_embedding_dimensions),
            max_metadata_size=props.vector_store.max_metadata_size,
            max_scan_bytes=props.vector_store.max_scan_bytes,
        )
    if props.vector_store.type == "redis":
        logger.warning("vector-store=redis 但无可用 redis_client，降级 inmemory")
    return SimpleInMemoryVectorStore(
        embedding_model=embedding_model,
        max_documents=props.vector_store.max_documents,
        max_content_length=props.vector_store.max_content_length,
        max_embedding_dimensions=props.vector_store.max_embedding_dimensions,
        max_metadata_size=props.vector_store.max_metadata_size,
    )


def _resolve_redis_client(props: AIProperties,
                          redis_client=None):
    """解析 Redis 客户端：优先用传入的 client，否则在需要 redis 时自动复用
    框架全局 springbootai.utils.redis_client.redis_client 单例。

    这样用户只需在 application.yml 配 vector-store.type=redis / memory.store=redis，
    即可自动启用 Redis 持久化，无需手动传 redis_client 参数。
    熔断器也在需要 Redis 时自动复用。
    """
    if redis_client is not None:
        return redis_client
    needs_redis = (props.vector_store.type == "redis"
                   or props.memory.store == "redis"
                   or props.circuit_breaker.enabled)
    if not needs_redis:
        return None
    try:
        from springbootai.utils.redis_client import redis_client as global_redis
        return global_redis
    except ImportError:
        if props.vector_store.type == "redis" or props.memory.store == "redis":
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

    # 同时兼容 Spring 风格的 ``spring.ai`` 配置（旧项目和测试常用）以及
    # 框架原生 ``springbootai.ai``，避免把已配置的 api-key 误判为空。
    ai_config = (
        config.get_prefix_config("springbootai.ai")
        or config.get_prefix_config("spring.ai")
        or config.get("ai", {})
        or {}
    )
    if not ai_config:
        ai_config = {}

    # 类型化绑定：env 覆盖 + 类型转换 + 默认值
    props = bind_ai_config(ai_config)

    # 自动复用框架全局 RedisClient 单例（当配置了 redis 模式且未显式传 client）
    redis_client = _resolve_redis_client(props, redis_client)

    beans: Dict[str, Any] = {}

    # 1. ChatModel（含熔断器）
    chat_model = _build_chat_model(props, redis_client=redis_client)
    registry.register("aiChatModel", chat_model)
    beans["aiChatModel"] = chat_model

    # 2. EmbeddingModel（含熔断器）- RAG 自动可用
    embedding_model = _build_embedding_model(props, redis_client=redis_client)
    registry.register("aiEmbeddingModel", embedding_model)
    beans["aiEmbeddingModel"] = embedding_model

    # 3. VectorStore（注入 EmbeddingModel，RAG 检索自动嵌入）
    vector_store = _build_vector_store(props, embedding_model, redis_client)
    registry.register("aiVectorStore", vector_store)
    beans["aiVectorStore"] = vector_store

    # 4. ChatClient（注入默认 Memory Advisor — 可通过 spring.ai.memory.auto-advisor=false 禁用）
    memory = _build_memory(props, redis_client)
    registry.register("aiChatMemory", memory)
    beans["aiChatMemory"] = memory

    auto_advisor = str(
        os.environ.get("SPRING_AI_MEMORY_AUTO_ADVISOR",
                       os.environ.get("springbootai.ai.memory.auto-advisor", "true"))
    ).strip().lower() in ("true", "1", "yes", "on")
    if auto_advisor:
        memory_advisor = MessageChatMemoryAdvisor(
            memory, max_messages=props.memory.max_messages,
            allow_global_namespace=props.memory.allow_global_namespace)
        chat_client = (ChatClientBuilder(chat_model)
                       .default_advisors(memory_advisor).build())
    else:
        chat_client = ChatClient(chat_model)
    registry.register("aiChatClient", chat_client)
    beans["aiChatClient"] = chat_client

    logger.info("AI 模块自动配置完成: provider=%s, beans=%d",
                props.default_provider, len(beans))
    return beans
