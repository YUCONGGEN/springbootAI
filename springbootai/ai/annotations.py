"""
SpringBootAI AI 注解。

复用 springbootai.annotations.core.SpringAnnotation 基础设施，
保持与现有注解一致的元数据收集机制（__spring_annotations__）。
"""
from typing import Any, Optional, Sequence, Type

from springbootai.annotations.core import SpringAnnotation

__all__ = [
    "AiClient", "Tool", "AiAdvisor", "AiMemory", "Prompt", "RAG",
    "StructuredOutput", "Agent", "Embedding", "VectorStore", "AiRetry",
    "AiCache", "TokenUsage", "ContentModeration",
]


class AiClient(SpringAnnotation):
    """
    @AiClient - 标注一个服务类使用 AI 客户端。

    框架启动时为该类注入对应的 ChatClient（按 provider 配置自动创建）。

    参数：
        provider: 模型提供者，如 openai/ollama；为空时读取 springbootai.ai.default-provider
        model: 具体模型名覆盖（如 gpt-4o-mini / llama3）
    """
    _annotation_type = "ai"

    def __init__(self, provider: str = "", model: str = "",
                 temperature: Optional[float] = None):
        super().__init__(provider=provider, model=model,
                         temperature=temperature)


class Tool(SpringAnnotation):
    """
    @Tool - 将一个函数注册为可被 LLM 调用的工具（Function Calling）。

    框架从函数签名 + docstring 自动生成 tool schema，模型决定调用时由
    ToolRegistry 执行并回填结果。

    用法：
        @Tool(description="查询订单状态")
        def get_order_status(order_id: str) -> str:
            '''根据订单号返回订单状态'''
            ...
    """
    _annotation_type = "ai"

    def __init__(self, name: str = "", description: str = "",
                 return_description: str = ""):
        super().__init__(name=name, description=description,
                         return_description=return_description)


class AiAdvisor(SpringAnnotation):
    """
    @AiAdvisor - 标注一个类为 Advisor Bean（RAG / Memory 等横切逻辑）。

    被 @AiAdvisor 标注的类会被注册到 BeanRegistry，并自动附加到 ChatClient。
    """
    _annotation_type = "ai"

    def __init__(self, name: str = "", order: int = 0):
        super().__init__(name=name, order=order)


class AiMemory(SpringAnnotation):
    """
    @AiMemory - 标注一个 ChatClient/Service 启用会话记忆。

    参数：
        store: 存储类型，inmemory / redis
        max_messages: 保留的最大历史消息数（滑动窗口）
    """
    _annotation_type = "ai"

    def __init__(self, store: str = "inmemory", max_messages: int = 20):
        super().__init__(store=store, max_messages=max_messages)


class Prompt(SpringAnnotation):
    """声明式 Prompt 模板。模板参数使用 ``str.format`` 绑定方法参数。"""
    _annotation_type = "ai"

    def __init__(self, template: str = "", system: str = "",
                 client: str = "aiChatClient", response: str = "content"):
        super().__init__(template=template, system=system, client=client,
                         response=response)


class RAG(SpringAnnotation):
    """让方法自动使用框架 VectorStore 检索并调用 ChatClient。"""
    _annotation_type = "ai"

    def __init__(self, top_k: int = 4, vector_store: str = "aiVectorStore",
                 embedding: str = "aiEmbeddingModel", prompt_template: str = "",
                 client: str = "aiChatClient"):
        super().__init__(top_k=max(1, int(top_k)), vector_store=vector_store,
                         embedding=embedding, prompt_template=prompt_template,
                         client=client)


class StructuredOutput(SpringAnnotation):
    """将 ChatResponse/JSON 文本安全绑定为 Pydantic 模型。"""
    _annotation_type = "ai"

    def __new__(cls, *args, **kwargs):
        # ``@StructuredOutput(MyModel)`` 中的模型类型是配置，不是装饰目标。
        if args and isinstance(args[0], type):
            return object.__new__(cls)
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, model: Type[Any] = dict, strict: bool = True):
        super().__init__(model=model, strict=bool(strict))


class Agent(SpringAnnotation):
    """声明式 Agent；优先复用已装配的 ``lcAgentService``。"""
    _annotation_type = "ai"

    def __init__(self, agent_type: str = "react", tools: Optional[Sequence[Any]] = None,
                 max_iterations: int = 10, service: str = "lcAgentService",
                 client: str = "aiChatClient"):
        super().__init__(agent_type=agent_type, tools=list(tools or []),
                         max_iterations=max(1, int(max_iterations)), service=service,
                         client=client)


class Embedding(SpringAnnotation):
    """声明注入 ``EmbeddingModel`` Bean；字段形式也可写成 ``field = Embedding()``。"""
    _annotation_type = "ai_injection"

    def __init__(self, bean: str = "aiEmbeddingModel"):
        super().__init__(bean=bean)


class VectorStore(SpringAnnotation):
    """声明注入 ``VectorStore`` Bean；字段形式也可写成 ``field = VectorStore()``。"""
    _annotation_type = "ai_injection"

    def __init__(self, bean: str = "aiVectorStore"):
        super().__init__(bean=bean)


class AiRetry(SpringAnnotation):
    """AI 方法级重试，复用框架 resilient_call。"""
    _annotation_type = "ai"

    def __init__(self, attempts: int = 3, delay_ms: int = 200,
                 backoff: float = 1.0, exceptions: tuple = (Exception,)):
        super().__init__(attempts=max(1, int(attempts)), delay_ms=max(0, int(delay_ms)),
                         backoff=max(1.0, float(backoff)), exceptions=exceptions)


class AiCache(SpringAnnotation):
    """AI 结果缓存；默认内存缓存，TTL 到期自动淘汰。"""
    _annotation_type = "ai"

    def __init__(self, ttl: float = 300.0, key: str = ""):
        super().__init__(ttl=max(0.0, float(ttl)), key=key)


class TokenUsage(SpringAnnotation):
    """记录模型响应中的 prompt/completion/total token 用量。"""
    _annotation_type = "ai"

    def __init__(self, provider: str = "", model: str = ""):
        super().__init__(provider=provider, model=model)


class ContentModeration(SpringAnnotation):
    """调用前后敏感内容拦截。未配置 blocked_terms 时不改变业务行为。"""
    _annotation_type = "ai"

    def __init__(self, blocked_terms: Optional[Sequence[str]] = None,
                 check_input: bool = True, check_output: bool = True):
        super().__init__(blocked_terms=tuple(str(x) for x in (blocked_terms or ())),
                         check_input=bool(check_input), check_output=bool(check_output))
