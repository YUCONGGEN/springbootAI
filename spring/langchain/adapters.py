"""
SpringBootAI LangChain 适配层 - 双向桥接 springbootAI 与 langchain 的模型/嵌入/向量库抽象。

设计目标：让「springbootAI 的 ChatClient / Advisor / RAG 体系」与「langchain 的
Chain / Agent 体系」共享同一个底层模型 Bean，避免重复配置 API Key 与重复建连。

桥接方向：
- springbootAI -> langchain：把已装配的 aiChatModel（spring.ai.ChatModel）适配为
  langchain 的 BaseChatModel，供 LLMChain / AgentExecutor / RetrievalQA 直接使用。
- langchain -> springbootAI：把 partner 包（如 ChatOpenAI / ChatAnthropic）适配为
  springbootAI 的 ChatModel，可注入 ChatClient 享受 Advisor / 函数调用闭环 / 熔断。

所有桥接均委托到底层 Bean，不重写算法、不缓存密钥。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from spring.ai.core import (
    ChatModel, ChatResponse, EmbeddingModel, Generation, Message, MessageType,
)

logger = logging.getLogger("Spring.LangChain")


# ==================== 消息类型映射 ====================

# springbootAI MessageType <-> langchain 消息类
def _spring_message_to_langchain(message: Message):
    """把 springbootAI Message 转为 langchain BaseMessage 子类实例。"""
    from langchain_core.messages import (
        AIMessage, HumanMessage, SystemMessage, ToolMessage,
    )
    t = message.type
    if t == MessageType.SYSTEM:
        return SystemMessage(content=message.content)
    if t == MessageType.ASSISTANT:
        return AIMessage(content=message.content)
    if t == MessageType.TOOL:
        return ToolMessage(content=message.content,
                          tool_call_id=str(message.metadata.get("tool_call_id", "")),
                          name=message.name or "")
    # 默认按用户消息处理
    return HumanMessage(content=message.content)


def _langchain_message_to_spring(lc_msg) -> Message:
    """把 langchain BaseMessage 转为 springbootAI Message。"""
    content = getattr(lc_msg, "content", str(lc_msg))
    cls_name = type(lc_msg).__name__
    if "System" in cls_name:
        return Message.system(content)
    if "AI" in cls_name or "Assistant" in cls_name:
        return Message.assistant(content)
    if "Tool" in cls_name:
        return Message(content=content, type=MessageType.TOOL,
                       name=getattr(lc_msg, "name", None))
    return Message.user(content)


# ==================== springbootAI ChatModel -> langchain BaseChatModel ====================

def _make_langchain_chat_model(spring_chat_model: ChatModel):
    """
    把 springbootAI ChatModel 适配为 langchain BaseChatModel 子类实例。

    采用动态子类化：继承 langchain_core.language_models.chat_models.BaseChatModel，
    实现 _generate / _llm_type，把调用委托回 spring_chat_model.call()。这样 LLMChain /
    AgentExecutor 等接收 BaseChatModel 的接口可直接复用 springbootAI 已装配的模型。
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import ConfigDict

    class _SpringChatModelAdapter(BaseChatModel):
        """springbootAI ChatModel -> langchain BaseChatModel 适配器。

        支持工具绑定：bind_tools 把 langchain BaseTool 列表转为 springbootAI
        ToolRegistry，返回新适配器实例。后续 _generate 调用时把 tool_registry
        传给 spring_model.call()，由 springbootAI 函数调用闭环统一执行工具并续写。
        这样 openai-functions / structured-chat agent 在真实模型下可正常调工具。
        """

        model_config = ConfigDict(arbitrary_types_allowed=True)

        def __init__(self, spring_model: ChatModel,
                     tool_registry=None, **kwargs):
            # 兼容 pydantic v1（langchain 1.x 仍以 v1 风格为主）
            super().__init__(**kwargs)
            # pydantic 模型禁止直接 setattr 私有属性，用 object.__setattr__ 绕过
            object.__setattr__(self, "_spring_model", spring_model)
            object.__setattr__(self, "_tool_registry", tool_registry)

        @property
        def _llm_type(self) -> str:
            return "springboot-ai-adapter"

        @property
        def _identifying_params(self) -> Dict[str, Any]:
            return {"adapter": "springbootAI.ChatModel"}

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            spring_msgs = [_langchain_message_to_spring(m) for m in messages]
            # 把 bind_tools 绑定的 tool_registry 传给 springbootAI call() 闭环
            tool_registry = getattr(self, "_tool_registry", None)
            resp = self._spring_model.call(spring_msgs, tool_registry=tool_registry)
            out_msg = resp.output if resp.output else Message.assistant("")
            lc_out = _spring_message_to_langchain(out_msg)
            usage = (resp.metadata or {}).get("usage") or {}
            gen = ChatGeneration(message=lc_out,
                                 generation_info={"usage": usage} if usage else None)
            return ChatResult(generations=[gen])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            import asyncio
            spring_msgs = [_langchain_message_to_spring(m) for m in messages]
            tool_registry = getattr(self, "_tool_registry", None)
            resp = await asyncio.to_thread(
                self._spring_model.call, spring_msgs, tool_registry)
            out_msg = resp.output if resp.output else Message.assistant("")
            lc_out = _spring_message_to_langchain(out_msg)
            return ChatResult(generations=[ChatGeneration(message=lc_out)])

        def bind_tools(self, tools, **kwargs):
            """
            绑定工具 - 把 langchain BaseTool 列表转为 springbootAI ToolRegistry，
            返回一个新的适配器实例（不修改自身）。

            后续 _generate 调用时把 tool_registry 传给 spring_model.call()，
            由 springbootAI 函数调用闭环统一执行工具 → 回填 → 续写。
            langchain AgentExecutor 收到的是最终文本结果（工具已执行完毕）。

            Args:
                tools: langchain BaseTool 列表（StructuredTool / Tool / @tool 装饰的函数）
            """
            from spring.ai.tools import ToolRegistry as SpringToolRegistry
            registry = SpringToolRegistry()
            for tool in tools or []:
                name = getattr(tool, "name", "") or "tool"
                # langchain StructuredTool 用 _run；Tool 用 func
                func = getattr(tool, "func", None)
                if func is None:
                    func = getattr(tool, "_run", None)
                if func is None:
                    logger.debug("工具 %s 无 func/_run，跳过", name)
                    continue
                desc = getattr(tool, "description", "") or ""
                try:
                    registry.register(name, func, description=desc)
                except Exception as exc:
                    logger.debug("工具 %s 注册失败: %s", name, exc)
            # 返回新实例，持有 tool_registry（不污染原适配器）
            return _SpringChatModelAdapter(
                spring_model=self._spring_model, tool_registry=registry)

    return _SpringChatModelAdapter(spring_model=spring_chat_model)


class SpringChatModelToLangChain:
    """
    springbootAI ChatModel -> langchain BaseChatModel 的工厂门面。

    用法：
        lc_model = SpringChatModelToLangChain(ai_chat_model).build()
        chain = LLMChain(llm=lc_model, prompt=...)
    """

    def __init__(self, spring_chat_model: ChatModel):
        self.spring_chat_model = spring_chat_model

    def build(self):
        """构造并返回 langchain BaseChatModel 适配实例。"""
        return _make_langchain_chat_model(self.spring_chat_model)


# ==================== langchain 模型 -> springbootAI ChatModel ====================

class LangChainModelToSpring(ChatModel):
    """
    langchain BaseChatModel / BaseLLM -> springbootAI ChatModel 适配器。

    让 partner 包（ChatOpenAI / ChatAnthropic / ChatOllama ...）可作为
    springbootAI ChatModel 注入 ChatClient，享受 Advisor / 函数调用闭环 / 熔断。

    用法：
        spring_model = LangChainModelToSpring(ChatOpenAI(api_key=..., model=...))
        client = ChatClient(spring_model).build()
    """

    def __init__(self, langchain_model):
        self._lc_model = langchain_model

    @property
    def langchain_model(self):
        return self._lc_model

    def _raw_call(self, messages: List[Message],
                  tool_registry=None,
                  options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        lc_messages = [_spring_message_to_langchain(m) for m in messages]

        # 传递 tool_registry：把 springbootAI ToolRegistry 转为 langchain Tool
        # 列表并绑定到模型，使 Function Calling 在反向适配路径下也生效
        model = self._lc_model
        if tool_registry is not None and hasattr(tool_registry, "schemas"):
            try:
                from langchain_core.tools import StructuredTool
                lc_tools = []
                for name in tool_registry.names():
                    td = tool_registry.get(name)
                    if td is None:
                        continue
                    lc_tools.append(StructuredTool.from_function(
                        name=name, func=td.func, description=td.description))
                if lc_tools and hasattr(model, "bind_tools"):
                    model = model.bind_tools(lc_tools)
            except Exception:
                pass  # bind_tools 不可用时跳过

        try:
            result = model.invoke(lc_messages)
        except Exception as exc:
            logger.error("langchain 模型调用失败: %s", exc)
            raise
        content = getattr(result, "content", str(result))
        usage = getattr(result, "usage_metadata", None) or {}
        # 提取 langchain 返回的 tool_calls
        lc_tc = getattr(result, "tool_calls", None) or []
        tool_calls = None
        if lc_tc:
            out = []
            for tc in lc_tc:
                out.append({
                    "id": getattr(tc, "id", "") or "",
                    "function": {"name": getattr(tc, "name", ""),
                                 "arguments": json.dumps(
                                     getattr(tc, "args", {}),
                                     ensure_ascii=False)},
                })
            if out:
                tool_calls = out
        meta = {"provider": "langchain",
                "backend": type(self._lc_model).__name__}
        if usage:
            meta["usage"] = usage
        if tool_calls:
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta,
        )

    def stream(self, messages: List[Message],
               tool_registry=None,
               options: Optional[Dict[str, Any]] = None):
        """流式 - 委托 langchain 模型的 stream()。"""
        lc_messages = [_spring_message_to_langchain(m) for m in messages]
        for chunk in self._lc_model.stream(lc_messages):
            content = getattr(chunk, "content", str(chunk))
            if content:
                yield ChatResponse(
                    generations=[Generation(output=Message.assistant(content))],
                    metadata={"provider": "langchain", "stream": True},
                )


# ==================== 嵌入互转 ====================

class SpringEmbeddingToLangChain:
    """
    springbootAI EmbeddingModel -> langchain Embeddings 适配器。

    让 langchain VectorStore（FAISS / Chroma）能复用 springbootAI 已装配的嵌入模型。
    """

    def __init__(self, spring_embedding_model: EmbeddingModel):
        self._spring_emb = spring_embedding_model

    def build(self):
        spring_emb = self._spring_emb

        # 显式继承 langchain Embeddings：让 isinstance(adapter, Embeddings) 为真，
        # 也便于 langchain VectorStore 在内部用 RunnableConfig / pydantic 校验时通过。
        try:
            from langchain_core.embeddings import Embeddings as _LCEmbeddings
        except ImportError:  # pragma: no cover - langchain_core 必装
            _LCEmbeddings = object

        class _SpringEmbeddingsAdapter(_LCEmbeddings):
            """langchain Embeddings 接口实现 - 委托 springbootAI EmbeddingModel。"""

            def embed_documents(self, texts: List[str]) -> List[List[float]]:
                return spring_emb.embed(texts)

            def embed_query(self, text: str) -> List[float]:
                return spring_emb.embed_one(text)

        return _SpringEmbeddingsAdapter()


class LangChainEmbeddingToSpring(EmbeddingModel):
    """langchain Embeddings -> springbootAI EmbeddingModel 适配器。"""

    def __init__(self, langchain_embeddings):
        self._lc_emb = langchain_embeddings

    def embed(self, texts: List[str]) -> List[List[float]]:
        return self._lc_emb.embed_documents(texts)

    def embed_one(self, text: str) -> List[float]:
        return self._lc_emb.embed_query(text)


# ==================== 便捷入口 ====================

def to_langchain_model(spring_chat_model: ChatModel):
    """便捷函数：springbootAI ChatModel -> langchain BaseChatModel。"""
    return SpringChatModelToLangChain(spring_chat_model).build()


def to_spring_model(langchain_model) -> ChatModel:
    """便捷函数：langchain 模型 -> springbootAI ChatModel。"""
    return LangChainModelToSpring(langchain_model)


def to_langchain_embeddings(spring_embedding_model: EmbeddingModel):
    """便捷函数：springbootAI EmbeddingModel -> langchain Embeddings。"""
    return SpringEmbeddingToLangChain(spring_embedding_model).build()


def to_spring_embeddings(langchain_embeddings) -> EmbeddingModel:
    """便捷函数：langchain Embeddings -> springbootAI EmbeddingModel。"""
    return LangChainEmbeddingToSpring(langchain_embeddings)
