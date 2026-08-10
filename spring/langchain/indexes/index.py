"""
索引服务 - 封装 langchain classic 的 VectorStoreIndexCreator，作为 @Service Bean。

VectorStoreIndexCreator 一行代码完成「文档加载 -> 切片 -> 嵌入 -> 入库 -> 检索」
全流程，是对 RAG 最简封装。本服务在其外提供 Spring 风格入口。
"""
import logging
from typing import Any, List, Optional


logger = logging.getLogger("Spring.LangChain")


class IndexService:
    """
    索引服务 Bean - 封装 VectorStoreIndexCreator 与 RAG 全流程便捷方法。

    构造时注入 lcEmbeddings（langchain Embeddings 适配）与 lcLangChainModel。
    """

    def __init__(self, lcEmbeddings: Any = None,
                 lcLangChainModel: Any = None):
        self._embeddings = lcEmbeddings
        self._lc_model = lcLangChainModel

    def create_from_documents(self, documents: List[Any],
                              vector_store_cls: Any = None,
                              **kwargs) -> Any:
        """
        从 Document 列表创建索引（向量库）。

        Args:
            documents: langchain_core.documents.Document 列表
            vector_store_cls: 向量库类（默认 FAISS，需安装）
        """
        from langchain_classic.indexes import VectorStoreIndexCreator
        creator = VectorStoreIndexCreator(
            embedding=self._embeddings,
            vectorstore_cls=vector_store_cls,
            **kwargs)
        return creator.from_documents(documents)

    def create_from_loaders(self, loaders: List[Any],
                            vector_store_cls: Any = None,
                            **kwargs) -> Any:
        """从 DocumentLoader 列表创建索引。"""
        from langchain_classic.indexes import VectorStoreIndexCreator
        creator = VectorStoreIndexCreator(
            embedding=self._embeddings,
            vectorstore_cls=vector_store_cls,
            **kwargs)
        return creator.from_loaders(loaders)

    def create_from_texts(self, texts: List[str],
                          metadatas: Optional[List[dict]] = None,
                          vector_store_type: str = "inmemory") -> Any:
        """
        便捷：从文本列表直接建索引。

        Args:
            texts: 文本列表
            metadatas: 元数据列表
            vector_store_type: inmemory | faiss | chroma ...
        """
        from spring.langchain.vectorstores.stores import VectorStoreFactory
        return VectorStoreFactory.from_texts(
            vector_store_type, texts, self._embeddings, metadatas=metadatas)

    def query(self, index_or_store: Any, question: str, k: int = 4) -> List[Any]:
        """便捷：在索引上做相似度检索。

        优先用 langchain 标准的 ``as_retriever().invoke()``；当向量库是
        springbootAI 内置 SimpleInMemoryVectorStore（无 as_retriever）时，
        回退到 ``similarity_search`` 直接检索。
        """
        # 兼容 VectorStoreIndexCreator 返回的 VectorStoreIndex 与裸 VectorStore
        store = getattr(index_or_store, "vectorstore", index_or_store)
        if hasattr(store, "as_retriever"):
            retriever = store.as_retriever(search_kwargs={"k": k})
            return retriever.invoke(question)
        # springbootAI SimpleInMemoryVectorStore 路径
        if hasattr(store, "similarity_search"):
            from spring.ai.vectorstore import SearchRequest
            # 若 store 持有 embedding_model，让它自行嵌入；否则用注入的 embeddings
            q_emb = None
            emb_model = getattr(store, "_embedding_model", None) or self._embeddings
            if emb_model is not None and hasattr(emb_model, "embed_one"):
                q_emb = emb_model.embed_one(question)
            elif emb_model is not None and hasattr(emb_model, "embed_query"):
                q_emb = emb_model.embed_query(question)
            return store.similarity_search(
                SearchRequest(query=question, embedding=q_emb, top_k=k))
        raise ValueError("不支持的向量库类型：无 as_retriever 或 similarity_search 方法")
