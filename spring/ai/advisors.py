"""
Advisor 实现 - QuestionAnswerAdvisor（RAG）与 MessageChatMemoryAdvisor（会话记忆）。
"""
from typing import Any, Dict, List, Optional

from spring.ai.core import (
    Advisor, AdvisorRequest, ChatResponse, Generation, Message, MessageType,
)
from spring.ai.memory import ChatMemory
from spring.ai.vectorstore import SearchRequest, VectorStore


class MessageChatMemoryAdvisor(Advisor):
    """
    会话记忆 Advisor - 在请求前注入历史消息，在响应后保存本次对话。

    通过 request.context['conversation_id'] 指定会话 ID。
    """
    order = 10

    def __init__(self, memory: ChatMemory, max_messages: int = 20):
        self.memory = memory
        self.max_messages = max_messages

    def advise_request(self, request: AdvisorRequest) -> AdvisorRequest:
        conv_id = request.context.get("conversation_id", "default")
        history = self.memory.get(conv_id, last_n=self.max_messages)
        # 历史 + 本次输入合并
        request.messages = history + request.messages
        return request

    def advise_response(self, response: ChatResponse,
                        request: AdvisorRequest) -> ChatResponse:
        conv_id = request.context.get("conversation_id", "default")
        # 保存用户输入（最后一条 user 消息）
        for msg in reversed(request.messages):
            if msg.type == MessageType.USER:
                self.memory.add(conv_id, msg)
                break
        # 保存模型回复
        if response.output:
            self.memory.add(conv_id, response.output)
        return response


class QuestionAnswerAdvisor(Advisor):
    """
    RAG Advisor - 检索相关文档并拼接到 system 提示中，实现检索增强生成。

    对齐 Spring AI 的 QuestionAnswerAdvisor：在请求前从 VectorStore 检索相关上下文，
    注入到 prompt 中。
    """
    order = 20

    DEFAULT_PROMPT_TEMPLATE = (
        "你是一个知识助手。请根据以下上下文回答用户问题。"
        "如果上下文不包含答案，请说明你不知道，不要编造。\n\n"
        "上下文:\n{context}\n\n"
    )

    def __init__(self, vector_store: VectorStore,
                 prompt_template: str = "",
                 top_k: int = 4,
                 embedding_model=None):
        self.vector_store = vector_store
        self.prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE
        self.top_k = top_k
        self.embedding_model = embedding_model

    def advise_request(self, request: AdvisorRequest) -> AdvisorRequest:
        # 取最后一条用户消息作为查询
        query = ""
        for msg in reversed(request.messages):
            if msg.type == MessageType.USER:
                query = msg.content
                break
        if not query:
            return request

        # 构建检索请求
        emb = None
        if self.embedding_model:
            emb = self.embedding_model.embed_one(query)
        search_req = SearchRequest(
            query=query, embedding=emb, top_k=self.top_k,
            similarity_threshold=0.1,
        )
        docs = self.vector_store.similarity_search(search_req)
        if not docs:
            return request

        context = "\n---\n".join(d.content for d in docs)
        system_text = self.prompt_template.format(context=context)
        # 在最前面插入 RAG system 提示
        new_messages = [Message.system(system_text)] + list(request.messages)
        request.messages = new_messages
        # 记录引用文档
        request.context["retrieved_documents"] = [
            {"id": d.id, "content": d.content[:200]} for d in docs
        ]
        return request


class SimpleLoggerAdvisor(Advisor):
    """
    日志 Advisor - 记录请求与响应，演示 Advisor 横切能力（企业级可观测性）。
    """
    order = 0

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def advise_request(self, request: AdvisorRequest) -> AdvisorRequest:
        self.events.append({
            "phase": "request",
            "message_count": len(request.messages),
            "tools": len(request.tool_registry.names())
            if request.tool_registry else 0,
        })
        return request

    def advise_response(self, response: ChatResponse,
                        request: AdvisorRequest) -> ChatResponse:
        self.events.append({
            "phase": "response",
            "content_length": len(response.content()),
        })
        return response
