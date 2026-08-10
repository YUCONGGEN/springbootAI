"""
向量存储工厂 - 封装 langchain classic 的 VectorStore，作为 @Component Bean。

封装的向量库：
- faiss: FAISS（需 faiss-cpu + langchain_community）
- chroma: Chroma（需 langchain_chroma）
- inmemory: SimpleInMemoryVectorStore（springbootAI 内置，无依赖）
- redis: Redis（需 redis）
- pinecone: Pinecone（需 langchain_pinecone）
- weaviate: Weaviate（需 langchain_weaviate）
- pgvector: PGVector（需 langchain_postgres）

所有外部向量库均懒加载，缺失时抛带安装提示的 ImportError。
inmemory 始终可用（复用 spring.ai.vectorstore.SimpleInMemoryVectorStore）。
"""
import logging
from typing import Any, List, Optional


logger = logging.getLogger("Spring.LangChain")


def _ensure_spring_embedding(embeddings: Any) -> Any:
    """把 langchain Embeddings 适配回 springbootAI EmbeddingModel。

    SimpleInMemoryVectorStore 是 springbootAI 内置向量库，其 add() 调用
    ``embedding_model.embed_one()``（springbootAI 接口）；而本工厂接收的
    embeddings 通常是 langchain Embeddings（只有 embed_query/embed_documents）。
    这里在传入 inmemory 向量库前做一次反向桥接，保证接口匹配。
    若已是 springbootAI EmbeddingModel（有 embed_one）则原样返回。
    """
    if embeddings is None:
        return None
    if hasattr(embeddings, "embed_one"):
        return embeddings  # 已是 springbootAI EmbeddingModel
    # langchain Embeddings -> springbootAI EmbeddingModel
    from spring.langchain.adapters import LangChainEmbeddingToSpring
    return LangChainEmbeddingToSpring(embeddings)


class VectorStoreFactory:
    """向量存储工厂 Bean - 按类型创建 langchain 向量库实例。"""

    # 类型 -> (模块, 类名)
    _STORE_MAP = {
        "faiss":    ("langchain_community.vectorstores", "FAISS"),
        "chroma":   ("langchain_chroma", "Chroma"),
        "pinecone": ("langchain_pinecone", "Pinecone"),
        "weaviate": ("langchain_weaviate", "Weaviate"),
        "pgvector": ("langchain_postgres", "PGVector"),
        "redis":    ("langchain_community.vectorstores", "Redis"),
    }

    @staticmethod
    def create(store_type: str, embeddings: Any = None,
               **kwargs) -> Any:
        """
        创建向量库实例。

        Args:
            store_type: faiss | chroma | pinecone | weaviate | pgvector | redis
            embeddings: langchain Embeddings（由 adapters 桥接自 springbootAI EmbeddingModel）
            kwargs: 透传给向量库构造器
        """
        if store_type == "inmemory":
            # 复用 springbootAI 内置内存向量库（无需任何依赖）
            from spring.ai.vectorstore import SimpleInMemoryVectorStore
            return SimpleInMemoryVectorStore(
                embedding_model=_ensure_spring_embedding(embeddings))

        spec = VectorStoreFactory._STORE_MAP.get(store_type)
        if not spec:
            raise ValueError(
                f"未知 store_type: {store_type}。支持: inmemory + {list(VectorStoreFactory._STORE_MAP.keys())}"
            )
        module_name, class_name = spec
        try:
            import importlib
            module = importlib.import_module(module_name)
            store_cls = getattr(module, class_name)
        except ImportError as exc:
            raise ImportError(
                f"向量库 {store_type} 依赖未安装（{exc}）。"
                f"请 pip install {module_name.replace('_', '-')}"
            ) from exc
        # 多数 langchain 向量库构造器接受 embedding 参数
        try:
            return store_cls(embedding=embeddings, **kwargs) \
                if embeddings is not None else store_cls(**kwargs)
        except TypeError:
            # 部分库（如 FAISS）无直接构造器，需 from_texts；返回类供 from_texts 使用
            return store_cls

    @staticmethod
    def from_texts(store_type: str, texts: List[str], embeddings: Any,
                   metadatas: Optional[List[dict]] = None,
                   **kwargs) -> Any:
        """
        从文本列表直接构建向量库并写入（FAISS / Chroma 等标准入口）。

        Args:
            store_type: faiss | chroma | ...
            texts: 文本列表
            embeddings: langchain Embeddings
            metadatas: 每条文本的元数据
        """
        if store_type == "inmemory":
            from spring.ai.vectorstore import SimpleInMemoryVectorStore
            store = SimpleInMemoryVectorStore(
                embedding_model=_ensure_spring_embedding(embeddings))
            store.add_texts(texts, metadatas=metadatas)
            return store

        spec = VectorStoreFactory._STORE_MAP.get(store_type)
        if not spec:
            raise ValueError(f"未知 store_type: {store_type}")
        module_name, class_name = spec
        try:
            import importlib
            module = importlib.import_module(module_name)
            store_cls = getattr(module, class_name)
        except ImportError as exc:
            raise ImportError(
                f"向量库 {store_type} 依赖未安装（{exc}）。"
                f"请 pip install {module_name.replace('_', '-')}"
            ) from exc
        return store_cls.from_texts(texts, embeddings,
                                    metadatas=metadatas or [{}] * len(texts),
                                    **kwargs)

    @staticmethod
    def supported_types() -> list:
        """返回支持的向量库类型。"""
        return ["inmemory"] + list(VectorStoreFactory._STORE_MAP.keys())

    @staticmethod
    def as_retriever(vector_store: Any, search_type: str = "similarity",
                     search_kwargs: Optional[dict] = None) -> Any:
        """把向量库转为 langchain Retriever。"""
        return vector_store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs or {"k": 4},
        )
