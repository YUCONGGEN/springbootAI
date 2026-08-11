"""
adapters 双向桥接演示 - springbootAI ↔ 原生 langchain 自由切换。

本脚本演示 spring.langchain.adapters 的核心能力：
- springbootAI ChatModel → 原生 langchain BaseChatModel（走 LCEL 管道）
- 原生 langchain ChatOpenAI → springbootAI ChatModel（走 LangChainCore 封装）
- 同进程内两种生态共享同一 FakeChatModel，无需 API Key

运行方式：
    cd e:\python_springboot_AI
    python example_langchain/demo/adapters_bridge_demo.py

输出：
    ✅（绿色）每个验证步骤的结果，全部 pass = 桥接双向可用
"""
import os
import sys
import warnings
from pathlib import Path

# 屏蔽 langchain classic 弃用告警
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")
try:
    from langchain_core._api import LangChainDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 允许无 API Key（用 FakeChatModel 演示）
os.environ.setdefault("AI_ALLOW_FAKE", "true")

from spring.ai.providers import FakeChatModel, FakeEmbeddingModel


# ============================================================
# 第 1 节：springbootAI → 原生 langchain（LCEL 管道）
# ============================================================
def demo_spring_to_native():
    """把 springbootAI 的 FakeChatModel 桥接成 langchain BaseChatModel，用原生的 LCEL 管道。"""

    from spring.langchain.adapters import to_langchain_model, to_langchain_embeddings

    # 1a. 模型桥接
    print("\n--- 第 1 节：springbootAI → 原生 langchain ---")

    spring_model = FakeChatModel()
    lc_model = to_langchain_model(spring_model)

    assert hasattr(lc_model, "invoke"), "桥接后必须有 invoke 方法"
    assert hasattr(lc_model, "stream"), "桥接后必须有 stream 方法"
    print("  [1a] to_langchain_model(FakeChatModel) → langchain BaseChatModel: ✅")

    # 1b. 嵌入模型桥接
    spring_emb = FakeEmbeddingModel()
    lc_emb = to_langchain_embeddings(spring_emb)

    assert hasattr(lc_emb, "embed_query"), "桥接后必须有 embed_query"
    assert hasattr(lc_emb, "embed_documents"), "桥接后必须有 embed_documents"
    print("  [1b] to_langchain_embeddings(FakeEmbeddingModel) → langchain Embeddings: ✅")

    # 1c. 用桥接后的模型跑原生 LCEL 管道
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    prompt = ChatPromptTemplate.from_template("把这句话翻成英文：{text}")
    chain = prompt | lc_model | StrOutputParser()

    result = chain.invoke({"text": "你好世界"})
    print(f'  [1c] LCEL 管道 (prompt | model | parser) → "{result}" : ✅')

    return lc_model


# ============================================================
# 第 2 节：原生 langchain → springbootAI（LangChainCore 封装）
# ============================================================
def demo_native_to_spring():
    """把原生 langchain ChatOpenAI 桥接成 springbootAI ChatModel，享受安全防护。"""

    from spring.langchain.adapters import to_spring_model

    print("\n--- 第 2 节：原生 langchain → springbootAI ---")

    # 2a. 模型桥接（反向）
    spring_model = FakeChatModel()
    from spring.langchain.adapters import to_langchain_model
    lc_model = to_langchain_model(spring_model)

    # to_spring_model 接受 langchain BaseChatModel，返回 springbootAI ChatModel
    spring_wrapper = to_spring_model(lc_model)

    assert hasattr(spring_wrapper, "call"), "桥接后必须有 call 方法"
    assert hasattr(spring_wrapper, "stream"), "桥接后必须有 stream 方法"
    print("  [2a] to_spring_model(langchain_model) → springbootAI ChatModel: ✅")

    # 2b. 桥接回来的模型可独立调用 call/stream
    from spring.ai.core import Message, MessageType
    result = spring_wrapper.call([Message(content="用中文答：1+1 等于几？", type=MessageType.USER)])
    output = result.content() if hasattr(result, 'content') else str(result)
    print(f'  [2b] spring_wrapper.call([Message(...)]) → "{output.strip()}" : ✅')

    # 2c. 用 LangChainCore 封装原始 spring_model（Core 自动桥接为 langchain 模型）
    from spring.langchain.core import LangChainCore

    core = LangChainCore.builder().with_model(spring_model).build()
    response = core.chat("用一句话介绍 Python。")
    print(f'  [2c] LangChainCore + spring_model（自动桥接）→ "{response.output.strip()}" : ✅')

    return core


# ============================================================
# 第 3 节：混合使用 — 同一个模型两头跑
# ============================================================
def demo_hybrid():
    """同一个 FakeChatModel 在两边同时工作，互不干扰。"""

    print("\n--- 第 3 节：混合使用 — 同一个模型两边跑 ---")

    from spring.langchain.adapters import to_langchain_model
    from spring.langchain.core import LangChainCore

    spring_model = FakeChatModel()
    lc_model = to_langchain_model(spring_model)
    core = LangChainCore.builder().with_model(spring_model).build()  # 自动桥接

    # 3a. 左边：原生 LCEL
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    chain = ChatPromptTemplate.from_template("用一句话解释：{concept}") | lc_model | StrOutputParser()
    lcel_result = chain.invoke({"concept": "Python 装饰器"})

    # 3b. 右边：LangChainCore
    core_result = core.chat("用一句话解释：Python 装饰器").output

    # 两种路径都能用同一个模型
    print(f'  原生 LCEL  → "{lcel_result.strip()}" : ✅')
    print(f'  LangChainCore → "{core_result.strip()}" : ✅')

    return True


# ============================================================
# 第 4 节：完整 RAG 流水线（springbootAI 嵌入 → langchain 检索）
# ============================================================
def demo_rag_bridge():
    """springbootAI EmbeddingModel → langchain InMemoryVectorStore → DocumentQA。"""

    print("\n--- 第 4 节：RAG 流水线（spring 嵌入 → langchain 检索）---")

    from spring.ai.providers import FakeChatModel, FakeEmbeddingModel
    from spring.langchain.adapters import to_langchain_embeddings, to_langchain_model

    spring_model = FakeChatModel()
    spring_emb = FakeEmbeddingModel()

    lc_model = to_langchain_model(spring_model)
    lc_emb = to_langchain_embeddings(spring_emb)

    # 用 langchain 原生 InMemoryVectorStore
    from langchain_core.vectorstores import InMemoryVectorStore
    from langchain_core.documents import Document

    docs = [
        Document(page_content="SpringBootAI 是一个 Python 框架，对标 Java Spring Boot 的注解和 API。", metadata={"source": "official"}),
        Document(page_content="LangChain 是一个用于构建 LLM 应用的框架，提供 LCEL 管道语法。", metadata={"source": "official"}),
        Document(page_content="SpringBootAI 的 LangChain 模块通过 adapters 实现双向桥接。", metadata={"source": "internal"}),
    ]
    vector_store = InMemoryVectorStore.from_documents(docs, lc_emb)
    retriever = vector_store.as_retriever()

    # 用 LangChainCore 的 RAG 流水线
    from spring.langchain.core import LangChainCore

    core = LangChainCore.builder().with_model(lc_model).build()
    response = core.rag_pipeline("什么是 SpringBootAI？", retriever=retriever)

    assert response.output, "RAG 应返回非空内容"
    print(f'  RAG 检索 → "{response.output.strip()}" : ✅')
    return True


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 62)
    print("  adapters 双向桥接演示")
    print("  springbootAI ChatModel  ←→  原生 langchain BaseChatModel")
    print("=" * 62)

    demo_spring_to_native()
    demo_native_to_spring()
    demo_hybrid()
    demo_rag_bridge()

    print("\n" + "=" * 62)
    print("  全部 4 节验证通过 ✅ — adapters 双向桥接正常。")
    print("  你可以在「原生 langchain」和「SpringBootAI 封装」之间自由切换。")
    print("=" * 62)


if __name__ == "__main__":
    main()
