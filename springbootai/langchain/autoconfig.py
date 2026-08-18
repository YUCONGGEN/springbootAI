"""
SpringBootAI LangChain 自动配置 - 读取 application.yml 的 springbootai.langchain.* 配置，
构建并注册 LangChain classic 全套能力 Bean 到 BeanRegistry。

完全镜像 springbootai.ai.autoconfig 的设计：
- LangChainProperties dataclass 类型化绑定 springbootai.langchain.* 子树
- _bind 递归绑定 + env 覆盖 + 类型转换
- configure_langchain(registry, config, ...) 工厂注册入口

注册的 Bean（命名风格与 aiChatModel 对齐，统一 lc 前缀）：
- lcLangChainModel:        langchain BaseChatModel（由 aiChatModel 桥接，或 partner 创建）
- lcEmbeddings:            langchain Embeddings（由 aiEmbeddingModel 桥接）
- lcPromptRegistry:        PromptTemplateFactory
- lcChainService:          ChainService
- lcAgentService:          AgentService
- lcMemoryFactory:         MemoryFactory
- lcParserRegistry:        OutputParserFactory
- lcLoaderRegistry:        DocumentLoaderRegistry
- lcRetrieverFactory:      RetrieverFactory
- lcVectorStoreFactory:    VectorStoreFactory
- lcIndexService:          IndexService
- lcToolFactory:           ToolFactory
- lcUtilityRegistry:       UtilityRegistry
- lcCallbackRegistry:      CallbackRegistry
- lcPartnerChatModel_<name>:   各启用 partner 的聊天模型（springbootAI ChatModel）
- lcPartnerEmbeddingModel_<name>: 各启用 partner 的嵌入模型（可选）
"""
import dataclasses
import logging
import os
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional

from springbootai.config.config_loader import config_loader
from springbootai.context.registry import BeanRegistry

logger = logging.getLogger("Spring.LangChain")


def _get_active_bean_factory():
    """获取当前活跃 ApplicationContext 的 BeanFactory（若存在）。

    BeanRegistry（configure_* 注册目标）与 ApplicationContext.bean_factory
    （@Autowired 解析目标）是两套存储。为让 lc* Bean 既能被 registry.get(name)
    直接取用，又能被 @Autowired 按类型/名称注入，这里在 ApplicationContext 存在时
    同步注册到其 bean_factory。测试场景下无活跃 ctx 时返回 None，仅注册到 registry。
    """
    try:
        from springbootai.context.application_context import ApplicationContext
        ctx = ApplicationContext.get_instance()
        return getattr(ctx, "bean_factory", None) if ctx else None
    except Exception:
        return None


def _register_bean(registry: BeanRegistry, name: str, bean: Any) -> None:
    """双重注册：BeanRegistry + 活跃 ApplicationContext.bean_factory。

    BeanFactory.get_bean 要求先有 BeanDefinition 才会查 _bean_instances（仅
    register_instance 不够）。因此这里同时注册 definition + instance，让
    @Autowired 按名称或类型都能解析到。
    """
    registry.register(name, bean)
    bf = _get_active_bean_factory()
    if bf is not None:
        try:
            from springbootai.context.bean_definition import BeanDefinition
            definition = BeanDefinition(bean_class=type(bean), bean_name=name)
            bf.register_bean_definition(name, definition)
            bf.register_instance(name, bean)
        except Exception as exc:
            logger.debug("Bean %s 同步到 BeanFactory 失败: %s", name, exc)


# ==================== 类型化配置 dataclass ====================

@dataclass
class ChainsProps:
    default_verbose: bool = field(default=False, metadata={"env": "LC_CHAIN_VERBOSE"})


@dataclass
class AgentsProps:
    default_type: str = field(default="react", metadata={"env": "LC_AGENT_TYPE"})
    max_iterations: int = field(default=10, metadata={"env": "LC_AGENT_MAX_ITER"})


@dataclass
class VectorStoreProps:
    type: str = field(default="faiss", metadata={"env": "LC_VECTOR_STORE"})
    persist_dir: str = field(default="./data/vectors", metadata={"env": "LC_PERSIST_DIR"})
    collection: str = field(default="default", metadata={"env": "LC_COLLECTION"})


@dataclass
class RetrieverProps:
    type: str = field(default="similarity", metadata={"env": "LC_RETRIEVER"})
    k: int = field(default=4, metadata={"env": "LC_RETRIEVER_K"})


@dataclass
class MemoryProps:
    type: str = field(default="buffer", metadata={"env": "LC_MEMORY"})
    max_messages: int = field(default=20, metadata={"env": "LC_MEMORY_MAX"})


@dataclass
class LangChainProperties:
    """springbootai.langchain.* 的类型化配置根。"""
    enabled: bool = field(default=True, metadata={"env": "LC_ENABLED"})
    default_llm: str = field(default="auto", metadata={"env": "LC_DEFAULT_LLM"})
    chains: ChainsProps = field(default_factory=ChainsProps)
    agents: AgentsProps = field(default_factory=AgentsProps)
    vector_store: VectorStoreProps = field(default_factory=VectorStoreProps)
    retriever: RetrieverProps = field(default_factory=RetrieverProps)
    memory: MemoryProps = field(default_factory=MemoryProps)
    # partners 是动态字典：name -> {api_key, model, base_url, temperature, ...}
    partners: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ==================== 绑定器（复用 ai.autoconfig 的 _bind 逻辑） ====================

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
    """递归绑定 dataclass：yml 子树 + env 覆盖 + 类型转换。"""
    if not isinstance(data, dict):
        data = {}
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        yml_key = f.name.replace("_", "-")
        raw = data.get(yml_key, _MISSING)
        if raw is _MISSING:
            raw = data.get(f.name, _MISSING)
        env_name = f.metadata.get("env")
        if env_name and env_name in os.environ:
            raw = os.environ[env_name]

        # 嵌套 dataclass
        ftype = f.type
        if dataclasses.is_dataclass(ftype):
            sub = raw if isinstance(raw, dict) else {}
            kwargs[f.name] = _bind(ftype, sub)
            continue

        if raw is _MISSING:
            continue
        kwargs[f.name] = _coerce(raw, ftype)
    return cls(**kwargs)


def bind_langchain_config(lc_config: Dict[str, Any]) -> LangChainProperties:
    """从 springbootai.langchain 子树绑定出类型化的 LangChainProperties。"""
    props = _bind(LangChainProperties, lc_config or {})
    # partners 单独处理（动态 dict，不递归绑定）
    partners_raw = (lc_config or {}).get("partners", {})
    if isinstance(partners_raw, dict):
        props.partners = partners_raw
    return props


# ==================== Bean 构建 ====================

def _build_langchain_model(props: LangChainProperties,
                           registry: BeanRegistry,
                           spring_chat_model=None):
    """
    构建 langchain BaseChatModel Bean。

    - default_llm=auto: 复用 springbootAI 的 aiChatModel（优先参数传入，否则 registry 取）
      并通过 adapters 桥接为 langchain BaseChatModel。
    - default_llm=<partner_name>: 用 PartnerProviderFactory 创建该 partner 聊天模型
      （返回的是已包装的 springbootAI ChatModel，再桥接为 langchain BaseChatModel）。
    """
    from springbootai.langchain.adapters import SpringChatModelToLangChain

    provider = props.default_llm
    if provider == "auto" or not provider:
        if spring_chat_model is None:
            spring_chat_model = registry.get("aiChatModel")
        if spring_chat_model is None:
            raise ValueError(
                "default-llm=auto 但未找到 aiChatModel Bean。"
                "请先 configure_ai() 或设置 springbootai.langchain.default-llm 为具体 partner。")
        return SpringChatModelToLangChain(spring_chat_model).build()

    # partner 创建
    from springbootai.langchain.partners import PartnerProviderFactory
    cfg = props.partners.get(provider, {})
    if not cfg:
        logger.warning("default-llm=%s 但 partners.%s 未配置，降级 auto", provider, provider)
        spring_chat_model = spring_chat_model or registry.get("aiChatModel")
        return SpringChatModelToLangChain(spring_chat_model).build()
    spring_chat_model, _ = PartnerProviderFactory.create(provider, cfg)
    return SpringChatModelToLangChain(spring_chat_model).build()


def _build_langchain_embeddings(props: LangChainProperties,
                                registry: BeanRegistry,
                                spring_embedding_model=None):
    """构建 langchain Embeddings Bean（复用 aiEmbeddingModel）。"""
    from springbootai.langchain.adapters import SpringEmbeddingToLangChain
    if spring_embedding_model is None:
        spring_embedding_model = registry.get("aiEmbeddingModel")
    if spring_embedding_model is None:
        logger.warning("未找到 aiEmbeddingModel Bean，部分 RAG 功能将不可用")
        return None
    return SpringEmbeddingToLangChain(spring_embedding_model).build()


def _register_partners(props: LangChainProperties, registry: BeanRegistry,
                       beans: Dict[str, Any]) -> None:
    """遍历配置的 partner，逐个实例化并注册 Bean。"""
    if not props.partners:
        return
    from springbootai.langchain.partners import PartnerProviderFactory
    for name, cfg in props.partners.items():
        # default-llm 指向的 partner 已作为 lcLangChainModel 主模型注册，
        # 这里仍为它注册一份 lcPartnerChatModel_<name> Bean 供单独注入
        if not isinstance(cfg, dict) or not cfg:
            continue
        try:
            chat, emb = PartnerProviderFactory.create(name, cfg)
            _register_bean(registry, f"lcPartnerChatModel_{name}", chat)
            beans[f"lcPartnerChatModel_{name}"] = chat
            if emb is not None:
                _register_bean(registry, f"lcPartnerEmbeddingModel_{name}", emb)
                beans[f"lcPartnerEmbeddingModel_{name}"] = emb
            logger.info("Partner '%s' 已注册为 Bean", name)
        except (ImportError, Exception) as exc:
            logger.warning("Partner '%s' 注册失败（跳过）: %s", name, exc)


def configure_langchain(registry: Optional[BeanRegistry] = None,
                        config: Optional[Any] = None,
                        chat_model=None,
                        embedding_model=None,
                        spring_embedding_model=None) -> Dict[str, Any]:
    """
    LangChain 模块自动配置入口 - 读取配置、绑定 LangChainProperties、构建并注册 Bean。

    Args:
        registry: BeanRegistry（默认全局单例）
        config: 配置加载器（默认全局 config_loader）
        chat_model: 已有的 springbootAI ChatModel（default-llm=auto 时复用）
        embedding_model: 已有的 springbootAI EmbeddingModel
        spring_embedding_model: 兼容旧参数名（同 embedding_model）

    Returns:
        已注册的 Bean 名称 -> Bean 映射
    """
    if registry is None:
        registry = BeanRegistry()
    if config is None:
        config = config_loader

    lc_config = config.get_prefix_config("springbootai.langchain") or {}
    props = bind_langchain_config(lc_config)

    if not props.enabled:
        logger.info("springbootai.langchain.enabled=false，跳过 LangChain 模块装配")
        return {}

    beans: Dict[str, Any] = {}

    # 1. langchain BaseChatModel + Embeddings（桥接 springbootAI 既有 Bean）
    lc_model = _build_langchain_model(props, registry, chat_model)
    _register_bean(registry, "lcLangChainModel", lc_model)
    beans["lcLangChainModel"] = lc_model

    emb = _build_langchain_embeddings(
        props, registry, embedding_model or spring_embedding_model)
    if emb is not None:
        _register_bean(registry, "lcEmbeddings", emb)
        beans["lcEmbeddings"] = emb

    # 2. 各能力 Bean（@Component/@Service 类实例化，注入 lc_model / emb）
    from springbootai.langchain.prompts.templates import PromptTemplateFactory
    from springbootai.langchain.chains.services import ChainService
    from springbootai.langchain.agents.services import AgentService
    from springbootai.langchain.memory.memory import MemoryFactory
    from springbootai.langchain.parsers.parsers import OutputParserFactory
    from springbootai.langchain.loaders.loaders import DocumentLoaderRegistry
    from springbootai.langchain.retrievers.retrievers import RetrieverFactory
    from springbootai.langchain.vectorstores.stores import VectorStoreFactory
    from springbootai.langchain.indexes.index import IndexService
    from springbootai.langchain.tools.tools import ToolFactory
    from springbootai.langchain.utilities.utils import UtilityRegistry
    from springbootai.langchain.callbacks.handlers import CallbackRegistry

    prompt_registry = PromptTemplateFactory()
    _register_bean(registry, "lcPromptRegistry", prompt_registry)
    beans["lcPromptRegistry"] = prompt_registry

    chain_service = ChainService(lcLangChainModel=lc_model)
    _register_bean(registry, "lcChainService", chain_service)
    beans["lcChainService"] = chain_service

    agent_service = AgentService(lcLangChainModel=lc_model)
    _register_bean(registry, "lcAgentService", agent_service)
    beans["lcAgentService"] = agent_service

    memory_factory = MemoryFactory()
    _register_bean(registry, "lcMemoryFactory", memory_factory)
    beans["lcMemoryFactory"] = memory_factory

    parser_registry = OutputParserFactory()
    _register_bean(registry, "lcParserRegistry", parser_registry)
    beans["lcParserRegistry"] = parser_registry

    loader_registry = DocumentLoaderRegistry()
    _register_bean(registry, "lcLoaderRegistry", loader_registry)
    beans["lcLoaderRegistry"] = loader_registry

    retriever_factory = RetrieverFactory()
    _register_bean(registry, "lcRetrieverFactory", retriever_factory)
    beans["lcRetrieverFactory"] = retriever_factory

    vector_store_factory = VectorStoreFactory()
    _register_bean(registry, "lcVectorStoreFactory", vector_store_factory)
    beans["lcVectorStoreFactory"] = vector_store_factory

    index_service = IndexService(lcEmbeddings=emb, lcLangChainModel=lc_model)
    _register_bean(registry, "lcIndexService", index_service)
    beans["lcIndexService"] = index_service

    tool_factory = ToolFactory()
    _register_bean(registry, "lcToolFactory", tool_factory)
    beans["lcToolFactory"] = tool_factory

    utility_registry = UtilityRegistry()
    _register_bean(registry, "lcUtilityRegistry", utility_registry)
    beans["lcUtilityRegistry"] = utility_registry

    callback_registry = CallbackRegistry()
    _register_bean(registry, "lcCallbackRegistry", callback_registry)
    beans["lcCallbackRegistry"] = callback_registry

    # 3. 各启用 partner 单独注册（含非默认 partner）
    _register_partners(props, registry, beans)

    logger.info("LangChain 模块自动配置完成: default-llm=%s, beans=%d, partners=%d",
                props.default_llm, len(beans), len(props.partners))
    return beans
