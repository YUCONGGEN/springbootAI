"""
LangChain RAG 服务 - 演示完整 RAG 流水线：文档入库 -> 检索 -> 生成。

复用 IndexService 的 create_from_texts / query 方法，避免重复实现向量库逻辑
（IndexService 内部已处理 springbootAI SimpleInMemoryVectorStore 与 langchain
Embeddings 的接口桥接，参见 _ensure_spring_embedding）。
"""
from spring.annotations.core import Autowired, Service, Slf4j
from spring.langchain.chains.services import ChainService
from spring.langchain.indexes.index import IndexService


@Slf4j
@Service
class LangChainRagService:
    """RAG 服务 - 基于内存向量库的检索增强问答。"""

    @Autowired
    def __init__(self, index_service: IndexService,
                 chain_service: ChainService):
        self.index_service = index_service
        self.chain_service = chain_service
        self._store = None  # 懒初始化向量库

    def _ensure_store(self):
        """懒初始化内存向量库（复用 IndexService 的 create_from_texts）。

        IndexService 内部会调用 VectorStoreFactory.from_texts("inmemory", ...)，
        并通过 _ensure_spring_embedding 把 langchain Embeddings 桥接为
        springbootAI EmbeddingModel，保证 SimpleInMemoryVectorStore 接口匹配。
        """
        if self._store is None:
            # 用空列表触发初始化（拿到一个空向量库实例）
            self._store = self.index_service.create_from_texts(
                [], vector_store_type="inmemory")
        return self._store

    def add_documents(self, texts: list) -> dict:
        """把文本列表写入向量库。

        复用 VectorStoreFactory.from_texts 的入库逻辑，而不是手动算向量再 add。
        """
        if not texts:
            return {"added": 0, "total": self._store.count() if self._store else 0}
        # 直接用 IndexService 重新构建（内存库重建比增量 add 更可靠）
        # 保留已有文本 + 新文本
        existing = self._collect_existing_texts()
        all_texts = existing + texts
        self._store = self.index_service.create_from_texts(
            all_texts, vector_store_type="inmemory")
        return {"added": len(texts), "total": len(all_texts)}

    def _collect_existing_texts(self) -> list:
        """从当前向量库收集已存的文本（用于增量重建）。"""
        if self._store is None:
            return []
        # SimpleInMemoryVectorStore 持有 _documents 字段
        docs = getattr(self._store, "_documents", None) or \
               getattr(self._store, "documents", None) or []
        result = []
        for d in docs:
            content = getattr(d, "content", None) or \
                      getattr(d, "page_content", None) or str(d)
            result.append(content)
        return result

    def query(self, question: str, k: int = 3) -> dict:
        """检索 + 生成。

        检索阶段复用 IndexService.query（内部回退 similarity_search）；
        生成阶段用 ChainService.run_llm_chain 把检索结果作为上下文。
        """
        store = self._ensure_store()
        # 检索（复用 IndexService 的 query 方法，处理 as_retriever / similarity_search 分支）
        results = self.index_service.query(store, question, k=k)
        # 提取文本内容（兼容 langchain Document 和 springbootAI Document）
        context_parts = []
        retrieved = []
        for d in results:
            content = getattr(d, "content", None) or \
                      getattr(d, "page_content", None) or str(d)
            score = getattr(d, "score", 0.0)
            context_parts.append(content)
            retrieved.append({"content": content, "score": score})
        context = "\n".join(context_parts)
        # 生成
        answer = self.chain_service.run_llm_chain(
            "根据以下资料回答问题。\n资料：\n{ctx}\n\n问题：{q}\n回答：",
            ctx=context or "(无相关资料)", q=question)
        return {
            "question": question,
            "retrieved": retrieved,
            "answer": answer,
        }
