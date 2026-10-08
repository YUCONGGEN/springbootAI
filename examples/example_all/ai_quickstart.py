"""最少样板代码的 AI 用法。Service 由应用的 IoC 容器扫描和创建。"""

from pydantic import BaseModel

from springbootai.ai import ChatClient, FakeChatModel
from springbootai.annotations import Prompt, RAG, Service


class Inspection(BaseModel):
    passed: bool
    reason: str


@Service
class Assistant:
    @Prompt("用三句话总结：{text}")
    def summarize(self, text: str) -> str:
        ...

    @Prompt("检查这份记录：{text}")
    async def inspect(self, text: str) -> Inspection:
        ...

    @RAG(top_k=3)
    def answer(self, question: str) -> str:
        ...


def main():
    """独立脚本可直接用客户端，无网络和密钥也能运行。"""
    client = ChatClient(FakeChatModel(prefix="AI:"))
    print(client.chat("你好"))
    for text in client.stream_text("请介绍一下自己"):
        print(text, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
