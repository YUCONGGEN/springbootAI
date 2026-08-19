"""AI 注解完整用例（中文说明）。

本文件只声明 Bean 和方法，不启动网络服务；真实项目由 IoC 容器注入
``aiChatClient``、``aiEmbeddingModel``、``aiVectorStore`` 和 ``lcAgentService``。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from springbootai.annotations import (
    Agent,
    AiCache,
    AiRetry,
    ContentModeration,
    Embedding,
    Prompt,
    RAG,
    StructuredOutput,
    TokenUsage,
    VectorStore,
)


class WeldInspection(BaseModel):
    """模型结构化输出示例。"""

    passed: bool
    reason: str


class WeldAiService:
    """一个类展示十个 AI 注解如何组合。"""

    embedding_model = Embedding()  # 自动注入 EmbeddingModel
    vector_store = VectorStore()    # 自动注入 VectorStore

    @Prompt("请总结焊接记录：{record}")
    @TokenUsage()
    def summarize(self, record: str) -> str:
        """方法体只保留业务参数，框架负责调用模型。"""
        return record

    @RAG(top_k=3)
    @AiRetry(attempts=3, delay_ms=100)
    @AiCache(ttl=60, key="{question}")
    @ContentModeration(blocked_terms=["恶意指令"])
    def answer(self, question: str) -> str:
        """返回值作为知识库查询词，框架完成检索增强问答。"""
        return question

    @Prompt("请输出 JSON：{record}")
    @StructuredOutput(WeldInspection)
    def inspect(self, record: str) -> WeldInspection:
        """模型 JSON 自动绑定为 Pydantic 对象。"""
        return record  # type: ignore[return-value]


@Agent(agent_type="react", max_iterations=5)
class WeldAgent:
    """Agent 类声明；方法参数仍由项目定义。"""

    def run(self, question: str) -> str:
        return question


def build_ai_annotation_examples() -> dict[str, Any]:
    """返回示例对象，供 example_all 查询器和测试读取。"""
    return {
        "service": WeldAiService,
        "agent": WeldAgent,
        "output_model": WeldInspection,
    }

