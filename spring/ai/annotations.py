"""
SpringBootAI AI 注解 - @AiClient / @Tool / @AiAdvisor / @AiMemory

复用 spring.annotations.core.SpringAnnotation 基础设施，
保持与现有注解一致的元数据收集机制（__spring_annotations__）。
"""
from typing import Callable, List, Optional, Type

from spring.annotations.core import SpringAnnotation


class AiClient(SpringAnnotation):
    """
    @AiClient - 标注一个服务类使用 AI 客户端。

    框架启动时为该类注入对应的 ChatClient（按 provider 配置自动创建）。

    参数：
        provider: 模型提供者，如 openai/ollama；为空时读取 spring.ai.default-provider
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
