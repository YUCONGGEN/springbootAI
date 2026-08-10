"""
LangChain Partner 提供商工厂 - 统一注册表，按配置懒加载 30+ 第三方 LLM/嵌入提供商。

设计思路：
- 不为每个 partner 写一个 @Service 类（30+ provider 会爆炸），而是用一张注册表
  name -> (langchain_module, chat_class_name, embedding_class_name) 描述元数据。
- PartnerProviderFactory.create(name, cfg) 用 importlib 懒加载对应 langchain 包，
  缺失依赖时抛友好错误（不污染全局启动），并自动包装为 springbootAI ChatModel /
  EmbeddingModel（通过 adapters 的 LangChainModelToSpring / LangChainEmbeddingToSpring）。
- configure_langchain 遍历 spring.langchain.partners.<name> 子树，按需注册
  lcPartnerChatModel_<name> / lcPartnerEmbeddingModel_<name> Bean。

这样用户只需在 application.yml 写一段 partner 配置即可启用，无需写任何 Java/Python 代码。
"""
import importlib
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Spring.LangChain")


# ==================== Partner 注册表 ====================
# 每项: name -> (langchain_module, chat_class_name, embedding_class_name_or_None)
# chat/embedding 类名在对应 langchain_module 顶层导出。embedding 为 None 表示该
# provider 无官方嵌入（如 Anthropic / Groq）。所有包均按需 pip install，缺省不安装。

PARTNER_REGISTRY: Dict[str, Tuple[str, str, Optional[str]]] = {
    # ---- OpenAI 系 ----
    "openai":       ("langchain_openai", "ChatOpenAI", "OpenAIEmbeddings"),
    "azure-openai": ("langchain_openai", "AzureChatOpenAI", "AzureOpenAIEmbeddings"),
    # ---- Anthropic / Claude ----
    "anthropic":    ("langchain_anthropic", "ChatAnthropic", None),
    # ---- 本地 / 开源 ----
    "ollama":       ("langchain_ollama", "ChatOllama", "OllamaEmbeddings"),
    "huggingface":  ("langchain_huggingface", "ChatHuggingFace", "HuggingFaceEmbeddings"),
    "llamacpp":     ("langchain_community", "ChatLlamaCpp", None),
    # ---- Google ----
    "google-vertexai": ("langchain_google_vertexai", "ChatVertexAI", "VertexAIEmbeddings"),
    "google-genai":    ("langchain_google_genai", "ChatGoogleGenerativeAI", "GoogleGenerativeAIEmbeddings"),
    # ---- Mistral / Cohere / xAI ----
    "mistralai":    ("langchain_mistralai", "ChatMistralAI", "MistralAIEmbeddings"),
    "cohere":       ("langchain_cohere", "ChatCohere", "CohereEmbeddings"),
    "xai":          ("langchain_xai", "ChatXAI", None),
    # ---- 云厂商聚合 ----
    "bedrock":      ("langchain_aws", "ChatBedrock", "BedrockEmbeddings"),
    "together":     ("langchain_together", "ChatTogether", None),
    "fireworks":    ("langchain_fireworks", "ChatFireworks", "FireworksEmbeddings"),
    "nvidia":       ("langchain_nvidia_ai_endpoints", "ChatNVIDIA", "NVIDIAEmbeddings"),
    "ai21":         ("langchain_ai21", "ChatAI21", "AI21Embeddings"),
    "databricks":   ("langchain_databricks", "ChatDatabricks", "DatabricksEmbeddings"),
    "perplexity":   ("langchain_perplexity", "ChatPerplexity", None),
    "groq":         ("langchain_groq", "ChatGroq", None),
    "sambanova":    ("langchain_sambanova", "ChatSambaStudio", None),
    "premai":       ("langchain_premai", "ChatPremAI", "PremAIEmbeddings"),
    "edenai":       ("langchain_edenai", "ChatEdenAI", "EdenAIEmbeddings"),
    "friendli":     ("langchain_friendli", "ChatFriendli", None),
    # ---- 国内厂商 ----
    "deepseek":     ("langchain_deepseek", "ChatDeepSeek", "DeepSeekEmbeddings"),
    "zhipu":        ("langchain_zhipuai", "ChatZhipuAI", None),
    "moonshot":     ("langchain_community", "ChatMoonshot", None),
    "tongyi":       ("langchain_community", "ChatTongyi", None),
    "baichuan":     ("langchain_community", "ChatBaichuan", None),
    "hunyuan":      ("langchain_community", "ChatTencentHunyuan", None),
    "minimax":      ("langchain_community", "ChatMinimax", None),
    "volcengine":   ("langchain_community", "ChatVolcEngine", None),
    "ernie":        ("langchain_community", "ChatErnie", None),
    "spark":        ("langchain_community", "ChatSpark", None),
}


def list_partners() -> List[str]:
    """返回注册表支持的全部 partner 名称。"""
    return sorted(PARTNER_REGISTRY.keys())


def is_partner_available(name: str) -> bool:
    """探测某个 partner 的 langchain 包是否已安装（不实例化）。"""
    spec = PARTNER_REGISTRY.get(name)
    if not spec:
        return False
    module_name = spec[0]
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def list_available_partners() -> List[str]:
    """返回当前环境已安装的 partner 列表。"""
    return [name for name in PARTNER_REGISTRY if is_partner_available(name)]


# ==================== 工厂 ====================

def _import_class(module_name: str, class_name: str):
    """从模块导入类名，失败抛带安装提示的 ImportError。"""
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"无法导入 {module_name}（{exc}）。请安装对应 partner 包："
            f"pip install {module_name.replace('_', '-')}"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(
            f"{module_name} 中未找到类 {class_name}，请升级该包到较新版本。"
        )
    return cls


def _filter_kwargs(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """过滤配置字典，只保留类构造器接受的参数（避免 pydantic 报未知字段）。"""
    # 优先用类属性 _fields（pydantic v1）或 model_fields（v2）
    allowed = set()
    if hasattr(cls, "model_fields"):
        allowed.update(cls.model_fields.keys())
    if hasattr(cls, "__fields__"):
        allowed.update(cls.__fields__.keys())
    # 兜底：用 __init__ 签名
    if not allowed:
        import inspect
        sig = inspect.signature(cls.__init__)
        for pname, p in sig.parameters.items():
            if pname != "self" and p.kind != p.VAR_KEYWORD:
                allowed.add(pname)
    out = {}
    for k, v in cfg.items():
        # kebab-case -> snake_case
        sk = k.replace("-", "_")
        if sk in allowed or k in allowed:
            out[sk if sk in allowed else k] = v
    return out


class PartnerProviderFactory:
    """
    Partner 提供商工厂 - 按 name + 配置实例化 langchain partner 模型，
    并自动包装为 springbootAI ChatModel / EmbeddingModel。

    用法：
        chat, emb = PartnerProviderFactory.create("openai",
                                                   {"api_key": "...", "model": "gpt-4o-mini"})
    """

    @staticmethod
    def create(name: str, cfg: Dict[str, Any]) -> Tuple[Any, Any]:
        """
        实例化 partner。

        Args:
            name: partner 名称（见 PARTNER_REGISTRY）
            cfg: 配置字典（api_key/model/base_url/temperature 等）

        Returns:
            (spring_chat_model, spring_embedding_model_or_None)
            spring_chat_model 已包装为 springbootAI ChatModel；
            若该 partner 无嵌入则第二个返回 None。
        """
        from spring.langchain.adapters import (
            LangChainEmbeddingToSpring, LangChainModelToSpring,
        )

        spec = PARTNER_REGISTRY.get(name)
        if not spec:
            raise ValueError(
                f"未知 partner: {name}。支持的 partner: {list_partners()}"
            )
        module_name, chat_cls_name, emb_cls_name = spec

        # 懒加载 + 友好错误
        chat_cls = _import_class(module_name, chat_cls_name)
        chat_kwargs = _filter_kwargs(chat_cls, cfg)
        lc_chat = chat_cls(**chat_kwargs)
        spring_chat = LangChainModelToSpring(lc_chat)

        spring_emb = None
        if emb_cls_name:
            try:
                emb_cls = _import_class(module_name, emb_cls_name)
                emb_kwargs = _filter_kwargs(emb_cls, cfg)
                lc_emb = emb_cls(**emb_kwargs)
                spring_emb = LangChainEmbeddingToSpring(lc_emb)
            except (ImportError, Exception) as exc:
                # 嵌入可选 - 缺失不阻塞聊天模型
                logger.debug("partner %s 嵌入不可用: %s", name, exc)
                spring_emb = None

        logger.info("Partner '%s' 已实例化: chat=%s, embedding=%s",
                    name, type(lc_chat).__name__,
                    "有" if spring_emb else "无")
        return spring_chat, spring_emb

    @staticmethod
    def create_chat_model(name: str, cfg: Dict[str, Any]):
        """仅实例化聊天模型。"""
        chat, _ = PartnerProviderFactory.create(name, cfg)
        return chat

    @staticmethod
    def create_embedding_model(name: str, cfg: Dict[str, Any]):
        """仅实例化嵌入模型（无嵌入的 partner 返回 None）。"""
        _, emb = PartnerProviderFactory.create(name, cfg)
        return emb
