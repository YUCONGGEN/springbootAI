"""
SpringBootAI AI 核心抽象 - 对齐 Spring AI 的 ChatClient / ChatModel / EmbeddingModel / Advisor。

设计原则：
- 模型调用层 (ChatModel/EmbeddingModel) 屏蔽 Provider 差异，底层可走 LangChain 或原生 HTTP
- ChatClient 提供链式 API（prompt().user().call().content()），与 Spring AI 风格一致
- Advisor 封装 RAG / Memory 等横切模式，在模型调用前后介入
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ==================== 消息与响应 ====================

class MessageType:
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """单条对话消息"""
    content: str
    type: str = MessageType.USER
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.SYSTEM)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.USER)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        return cls(content=content, type=MessageType.ASSISTANT)

    def to_dict(self) -> Dict[str, str]:
        d = {"role": self.type, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Generation:
    """单次生成结果"""
    output: Message
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """模型响应"""
    generations: List[Generation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> Optional[Message]:
        return self.generations[0].output if self.generations else None

    def content(self) -> str:
        """便捷取值：返回首条生成的文本（对齐 Spring AI 的 call().content()）"""
        if self.generations:
            return self.generations[0].output.content
        return ""


# ==================== 模型抽象 ====================

def _is_tool_registry(obj) -> bool:
    return obj is not None and hasattr(obj, "schemas") and hasattr(obj, "execute")


class ChatModel(ABC):
    """聊天模型抽象 - 屏蔽 OpenAI/Ollama/LangChain 差异。

    函数调用闭环在基类 call() 中实现：Provider 的 _raw_call 把模型请求的
    tool_calls 放入 response.metadata['tool_calls']，基类统一执行→回填→续写。
    """

    MAX_TOOL_ITERATIONS = 5

    @abstractmethod
    def _raw_call(self, messages: List[Message],
                  tool_registry=None,
                  options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """Provider 实现：单次模型调用。若模型请求工具，将 tool_calls 列表
        放入返回的 ChatResponse.metadata['tool_calls']（每项含 id/function{name,arguments}）。
        tool_registry 用于把工具 schema 注入请求体。"""

    def call(self, messages: List[Message],
             tool_registry=None,
             options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """同步调用 - 含函数调用闭环"""
        import json as _json
        from spring.ai.observability import ai_metrics

        working = list(messages)
        resp = None
        for iteration in range(self.MAX_TOOL_ITERATIONS + 1):
            resp = self._raw_call(working, tool_registry, options)
            resp.metadata = resp.metadata or {}
            resp.metadata["tool_iterations"] = iteration
            tool_calls = resp.metadata.get("tool_calls")

            # 无工具调用 → 返回最终回复
            if not tool_calls or not _is_tool_registry(tool_registry):
                return resp

            # 有工具调用 → 追加 assistant 消息 + 执行工具 + 回填
            working.append(resp.output)
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args_raw = func.get("arguments", "{}")
                try:
                    args = (_json.loads(args_raw) if isinstance(args_raw, str)
                            else args_raw)
                    result = tool_registry.execute(name, args)
                    ai_metrics.record_tool_call(name, "success")
                except Exception as exc:
                    result = f"工具执行失败: {exc}"
                    ai_metrics.record_tool_call(name, "failure")
                working.append(Message(
                    content=str(result), type=MessageType.TOOL, name=name,
                    metadata={"tool_call_id": tc.get("id", "")},
                ))

        # 超过最大轮数
        return resp

    def stream(self, messages: List[Message],
               tool_registry=None,
               options: Optional[Dict[str, Any]] = None):
        """流式调用（SSE delta 生成器），默认降级为单次 yield"""
        yield self._raw_call(messages, tool_registry, options)

    async def astream(self, messages: List[Message],
                      tool_registry=None,
                      options: Optional[Dict[str, Any]] = None):
        """异步流式生成器，默认降级为同步 stream"""
        for chunk in self.stream(messages, tool_registry=tool_registry,
                                 options=options):
            yield chunk

    async def acall(self, messages: List[Message],
                    tool_registry=None,
                    options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """异步调用，默认降级为同步 call（子类可覆盖实现真异步）"""
        import asyncio
        return await asyncio.to_thread(self.call, messages, tool_registry, options)


class EmbeddingModel(ABC):
    """嵌入模型抽象"""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入"""

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]


# ==================== Advisor ====================

@dataclass
class AdvisorRequest:
    """Advisor 请求上下文"""
    messages: List[Message]
    chat_model: ChatModel
    tool_registry: Optional[Any] = None
    context: Dict[str, Any] = field(default_factory=dict)
    options: Optional[Dict[str, Any]] = None


class Advisor(ABC):
    """
    Advisor - 封装 RAG / Memory / 日志等横切模式。
    advise_request 在模型调用前转换请求；advise_response 在调用后转换响应。
    """
    order: int = 0

    @abstractmethod
    def advise_request(self, request: AdvisorRequest) -> AdvisorRequest:
        """转换请求"""

    def advise_response(self, response: ChatResponse,
                        request: AdvisorRequest) -> ChatResponse:
        """转换响应（默认透传）"""
        return response


# ==================== ChatClient 链式 API ====================

class PromptSpec:
    """链式 Prompt 构造器"""

    def __init__(self, chat_client: "ChatClient"):
        self._client = chat_client
        self._messages: List[Message] = []
        self._advisors: List[Advisor] = list(chat_client.default_advisors)
        # tool_registry：None 或 ToolRegistry 或待注册的可调用对象列表
        self._tool_registry = chat_client.default_tool_registry
        self._pending_tools: List[Any] = []
        self._context: Dict[str, Any] = {}

    def system(self, text: str) -> "PromptSpec":
        self._messages.append(Message.system(text))
        return self

    def user(self, text: str) -> "PromptSpec":
        self._messages.append(Message.user(text))
        return self

    def messages(self, msgs: List[Message]) -> "PromptSpec":
        self._messages.extend(msgs)
        return self

    def advisors(self, *advisors: Advisor) -> "PromptSpec":
        self._advisors.extend(advisors)
        return self

    def tools(self, *tools: Any) -> "PromptSpec":
        """注册工具 - 可传入 ToolRegistry 或若干可调用函数"""
        for t in tools:
            if t is None:
                continue
            # 已是 ToolRegistry
            if hasattr(t, "schemas") and hasattr(t, "execute"):
                self._tool_registry = t
            else:
                self._pending_tools.append(t)
        return self

    def param(self, key: str, value: Any) -> "PromptSpec":
        self._context[key] = value
        return self

    def _resolve_registry(self):
        """合并默认 registry 与本次 pending 工具"""
        from spring.ai.tools import ToolRegistry
        registry = self._tool_registry
        if self._pending_tools:
            if registry is None:
                registry = ToolRegistry()
            else:
                registry = ToolRegistry()  # 不污染默认 registry
                if self._tool_registry is not None:
                    for name in self._tool_registry.names():
                        td = self._tool_registry.get(name)
                        registry.register(name, td.func, td.description)
            for i, func in enumerate(self._pending_tools):
                name = getattr(func, "__name__", f"tool_{i}")
                desc = (func.__doc__ or "").strip().split("\n")[0]
                registry.register(name, func, description=desc)
        return registry

    def call(self) -> ChatResponse:
        return self._client._execute(
            self._messages, self._advisors,
            self._resolve_registry(), self._context
        )

    def stream(self):
        """流式调用生成器"""
        yield from self._client._execute_stream(
            self._messages, self._advisors,
            self._resolve_registry(), self._context
        )

    def content(self) -> str:
        return self.call().content()


class ChatClient:
    """
    ChatClient - Spring AI 风格的链式聊天客户端。

    用法：
        client = ChatClient(chat_model).default_system("你是助手").build()
        answer = client.prompt().user("你好").call().content()
    """

    def __init__(self, chat_model: ChatModel):
        self.chat_model = chat_model
        self._default_system: Optional[str] = None
        self.default_advisors: List[Advisor] = []
        self.default_tool_registry: Optional[Any] = None

    def default_system(self, text: str) -> "ChatClient":
        self._default_system = text
        return self

    def default_advisors_set(self, *advisors: Advisor) -> "ChatClient":
        self.default_advisors = list(advisors)
        return self

    def default_tools_set(self, tool_registry: Any) -> "ChatClient":
        """设置默认 ToolRegistry"""
        self.default_tool_registry = tool_registry
        return self

    def build(self) -> "ChatClient":
        return self

    def prompt(self) -> PromptSpec:
        spec = PromptSpec(self)
        if self._default_system:
            spec._messages.insert(0, Message.system(self._default_system))
        return spec

    def _execute(self, messages: List[Message], advisors: List[Advisor],
                 tool_registry, context: Dict[str, Any]) -> ChatResponse:
        # 请求阶段：按 order 升序应用 advisor
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = advisor.advise_request(request)

        # 模型调用（携带 tool_registry 以启用函数调用闭环）
        response = self.chat_model.call(
            request.messages, tool_registry=request.tool_registry,
            options=request.options
        )

        # 响应阶段：按 order 降序应用 advisor
        for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
            response = advisor.advise_response(response, request)
        return response

    def _execute_stream(self, messages: List[Message], advisors: List[Advisor],
                        tool_registry, context: Dict[str, Any]):
        # 流式：advisor 先做请求预处理，逐块 yield；全部消费完后再统一回调
        # advise_response（例如 MessageChatMemoryAdvisor 保存会话记忆）。
        # 修复：之前流式模式从不调用 advise_response，导致"流式 + 记忆"时对话
        # 永远不会被持久化。
        request = AdvisorRequest(
            messages=list(messages), chat_model=self.chat_model,
            tool_registry=tool_registry, context=dict(context),
        )
        for advisor in sorted(advisors, key=lambda a: a.order):
            request = advisor.advise_request(request)

        chunks: List[ChatResponse] = []
        for chunk in self.chat_model.stream(
                request.messages, tool_registry=request.tool_registry,
                options=request.options):
            chunks.append(chunk)
            yield chunk

        # 聚合全部流式块，回调响应阶段 advisor（触发记忆保存/日志/审计等副作用）
        if chunks:
            combined = ChatResponse(
                generations=[Generation(output=Message.assistant(
                    "".join(c.content() for c in chunks)))],
                metadata={"provider": (chunks[-1].metadata or {}).get("provider"),
                          "stream": True, "combined": True},
            )
            for advisor in sorted(advisors, key=lambda a: a.order, reverse=True):
                combined = advisor.advise_response(combined, request)


class ChatClientBuilder:
    """ChatClient 构造器 - 对齐 Spring AI 的 ChatClient.Builder"""

    def __init__(self, chat_model: ChatModel):
        self._client = ChatClient(chat_model)

    def default_system(self, text: str) -> "ChatClientBuilder":
        self._client.default_system(text)
        return self

    def default_advisors(self, *advisors: Advisor) -> "ChatClientBuilder":
        self._client.default_advisors_set(*advisors)
        return self

    def default_tools(self, tool_registry: Any) -> "ChatClientBuilder":
        self._client.default_tools_set(tool_registry)
        return self

    def build(self) -> ChatClient:
        return self._client.build()
