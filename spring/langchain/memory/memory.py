"""
会话记忆工厂 - 封装 langchain classic 的 Conversation Memory，作为 @Component Bean。

封装的 Memory 类型（对齐 langchain-master libs/langchain/langchain_classic/memory/）：
- buffer: ConversationBufferMemory（完整历史）
- summary: ConversationSummaryMemory（用 LLM 摘要压缩历史）
- buffer-window: ConversationBufferWindowMemory（滑动窗口，保留最近 N 条）
- token-buffer: ConversationTokenBufferMemory（按 token 数截断）
- entity: ConversationEntityMemory（实体感知记忆，提取和追踪对话中的实体）
- combined: CombinedMemory（组合多种记忆类型）
- read-only-shared: ReadOnlySharedMemory（只读共享记忆，多 Agent 共享上下文）
"""
import logging
from typing import Any, Optional


logger = logging.getLogger("Spring.LangChain")


class MemoryFactory:
    """
    会话记忆工厂 Bean。

    通过 create(memory_type, llm, **kwargs) 统一入口创建各类记忆。
    summary/token-buffer 需要传入 llm（langchain BaseChatModel）做摘要/计数。
    """

    @staticmethod
    def create(memory_type: str = "buffer",
               llm: Optional[Any] = None,
               memory_key: str = "history",
               max_messages: int = 20,
               **kwargs) -> Any:
        """
        创建会话记忆。

        Args:
            memory_type: buffer | summary | buffer-window | token-buffer |
                         entity | combined | read-only-shared
            llm: langchain BaseChatModel（summary/token-buffer/entity 必填）
            memory_key: 历史在 prompt 中的变量名
            max_messages: buffer-window 的窗口大小；token-buffer 的 token 上限
            kwargs: 类型特定参数
                - entity: llm(必填), memory_key, extractor(可选)
                - combined: memories(memory 列表, 必填)
                - read-only-shared: memory(共享的 memory 实例, 必填)
        """
        if memory_type == "buffer":
            from langchain_classic.memory import ConversationBufferMemory
            return ConversationBufferMemory(memory_key=memory_key,
                                            return_messages=kwargs.get("return_messages", True))

        if memory_type == "summary":
            from langchain_classic.memory import ConversationSummaryMemory
            if llm is None:
                raise ValueError("summary 记忆需要 llm 参数")
            return ConversationSummaryMemory(llm=llm, memory_key=memory_key,
                                             return_messages=kwargs.get("return_messages", True))

        if memory_type == "buffer-window":
            from langchain_classic.memory import ConversationBufferWindowMemory
            return ConversationBufferWindowMemory(
                k=max_messages, memory_key=memory_key,
                return_messages=kwargs.get("return_messages", True))

        if memory_type == "token-buffer":
            from langchain_classic.memory import ConversationTokenBufferMemory
            if llm is None:
                raise ValueError("token-buffer 记忆需要 llm 参数")
            return ConversationTokenBufferMemory(
                llm=llm, max_token_limit=max_messages, memory_key=memory_key,
                return_messages=kwargs.get("return_messages", True))

        if memory_type == "entity":
            from langchain_classic.memory import ConversationEntityMemory
            if llm is None:
                raise ValueError("entity 记忆需要 llm 参数")
            return ConversationEntityMemory(
                llm=llm, memory_key=kwargs.get("entity_key", "entities"),
                return_messages=kwargs.get("return_messages", True),
            )

        if memory_type == "combined":
            memories = kwargs.get("memories")
            if not memories:
                raise ValueError("combined 记忆需要 memories 参数（记忆列表）")
            from langchain_classic.memory import CombinedMemory
            return CombinedMemory(memories=list(memories))

        if memory_type == "read-only-shared":
            shared = kwargs.get("memory")
            if shared is None:
                raise ValueError("read-only-shared 记忆需要 memory 参数（共享的 memory 实例）")
            from langchain_classic.memory import ReadOnlySharedMemory
            return ReadOnlySharedMemory(memory=shared)

        raise ValueError(
            f"未知 memory_type: {memory_type}。支持: buffer|summary|buffer-window|"
            f"token-buffer|entity|combined|read-only-shared"
        )

    @staticmethod
    def supported_types() -> list:
        """返回支持的记忆类型。"""
        return ["buffer", "summary", "buffer-window", "token-buffer",
                "entity", "combined", "read-only-shared"]
