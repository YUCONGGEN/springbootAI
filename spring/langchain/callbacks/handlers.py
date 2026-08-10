"""
回调处理器注册表 - 封装 langchain classic 的 CallbackHandler，作为 @Component Bean。

封装的回调：
- stdout: StdOutCallbackHandler（标准输出，调试用）
- streaming-stdout: StreamingStdOutCallbackHandler（流式输出）
- file: FileCallbackHandler（写文件）
"""
import logging
from typing import Any, List, Optional


logger = logging.getLogger("Spring.LangChain")


class CallbackRegistry:
    """回调处理器注册表 Bean - 统一创建与管理回调处理器。"""

    def __init__(self):
        self._handlers: List[Any] = []

    @staticmethod
    def create_stdout_handler() -> Any:
        """标准输出回调（打印完整步骤，调试 Chain/Agent 用）。"""
        from langchain_core.callbacks import StdOutCallbackHandler
        return StdOutCallbackHandler()

    @staticmethod
    def create_streaming_stdout_handler() -> Any:
        """流式标准输出回调。"""
        from langchain_core.callbacks import StreamingStdOutCallbackHandler
        return StreamingStdOutCallbackHandler()

    @staticmethod
    def create_file_handler(filename: str) -> Any:
        """文件回调（写入指定文件）。"""
        from langchain_classic.callbacks import FileCallbackHandler
        return FileCallbackHandler(filename)

    def register(self, handler: Any) -> "CallbackRegistry":
        """注册一个回调处理器到注册表。"""
        self._handlers.append(handler)
        return self

    def all(self) -> List[Any]:
        """返回已注册的全部回调。"""
        return list(self._handlers)

    def clear(self) -> None:
        self._handlers.clear()
