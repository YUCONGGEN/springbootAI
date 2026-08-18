"""
向量存储抽象与内存实现 - 为 RAG 提供文档向量的存储与相似度检索。

生产环境可替换为 PGVector / Milvus / Chroma 等实现（实现同一 VectorStore 接口）。
"""
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Document:
    """向量文档"""
    id: str
    content: str
    embedding: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchRequest:
    """检索请求"""
    query: str
    embedding: Optional[List[float]] = None
    top_k: int = 4
    similarity_threshold: float = 0.0
    filter_expression: Optional[str] = None


class VectorStore(ABC):
    """向量存储抽象"""

    @abstractmethod
    def add(self, documents: List[Document]) -> None:
        """写入文档（需已包含 embedding）"""

    @abstractmethod
    def similarity_search(self, request: SearchRequest) -> List[Document]:
        """相似度检索"""


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SimpleInMemoryVectorStore(VectorStore):
    """内存向量存储 - 开发/测试用，余弦相似度"""

    def __init__(self, embedding_model=None):
        self._docs: List[Document] = []
        self._embedding_model = embedding_model

    def add(self, documents: List[Document]) -> None:
        for doc in documents:
            if not doc.embedding and self._embedding_model and doc.content:
                doc.embedding = self._embedding_model.embed_one(doc.content)
            self._docs.append(doc)

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None) -> None:
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add([Document(id=f"doc-{len(self._docs)}", content=text,
                               metadata=meta)])

    def similarity_search(self, request=None, **kwargs) -> List[Document]:
        """相似度检索。

        支持两种调用方式（向后兼容）：
        1. similarity_search(SearchRequest(query="...", top_k=4))  # 原生接口
        2. similarity_search("query", k=4) 或 similarity_search(query="...", k=4)
           # langchain 风格便捷入口：首参为字符串时视为 query，k 等价于 top_k

        Args:
            request: SearchRequest 实例（与 kwargs 二选一）
            kwargs: 当 request 为字符串或 None 时，支持 query / k / top_k /
                    embedding / similarity_threshold / filter_expression
        """
        # 字符串首参 → 当作 query
        if isinstance(request, str):
            kwargs.setdefault("query", request)
            request = None
        if request is None:
            request = SearchRequest(
                query=kwargs.get("query", ""),
                embedding=kwargs.get("embedding"),
                top_k=kwargs.get("k", kwargs.get("top_k", 4)),
                similarity_threshold=kwargs.get("similarity_threshold", 0.0),
                filter_expression=kwargs.get("filter_expression"),
            )
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []

        scored = []
        for doc in self._docs:
            if not doc.embedding:
                continue
            # RAG 租户隔离：filter_expression 仅返回匹配文档
            if request.filter_expression:
                if not RedisVectorStore._match_filter(doc, request.filter_expression):
                    continue
            score = cosine_similarity(emb, doc.embedding)
            if score >= request.similarity_threshold:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:request.top_k]]

    def as_retriever(self, search_type: str = "similarity",
                     search_kwargs: Optional[dict] = None) -> "_InMemoryRetriever":
        """把内存向量库转为 Retriever（langchain VectorStore.as_retriever 风格）。

        返回的 Retriever 暴露 invoke(query) / get_relevant_documents(query) 方法，
        便于 RetrieverFactory 与 RetrievalQA 直接消费。
        """
        return _InMemoryRetriever(self, search_kwargs or {"k": 4})

    def count(self) -> int:
        return len(self._docs)

    def clear(self) -> None:
        self._docs.clear()


class _InMemoryRetriever:
    """SimpleInMemoryVectorStore 的 Retriever 适配器。

    暴露 langchain Retriever 风格接口：invoke / get_relevant_documents /
    ainvoke，内部委托回向量库的 similarity_search。轻量实现，不引入
    langchain BaseRetriever 的 pydantic 依赖。
    """

    def __init__(self, store: "SimpleInMemoryVectorStore", search_kwargs: dict):
        self._store = store
        self._k = search_kwargs.get("k", 4)

    def invoke(self, query, config=None):
        """同步检索（langchain 1.x Runnable 风格入口）。"""
        if isinstance(query, str):
            return self._store.similarity_search(query, k=self._k)
        # query 为 dict 等结构时取其 query 字段
        q = getattr(query, "query", None) or (query.get("query") if isinstance(query, dict) else str(query))
        return self._store.similarity_search(q, k=self._k)

    def get_relevant_documents(self, query):
        """langchain classic Retriever 入口。"""
        return self.invoke(query)

    async def ainvoke(self, query, config=None):
        """异步检索（内存实现，直接同步返回）。"""
        return self.invoke(query, config)


class LangChainVectorStore(VectorStore):
    """
    LangChain 向量存储适配器 - 包装 langchain 生态的 VectorStore（FAISS/Chroma 等）。

    设计原则：能用 LangChain 就用 LangChain（不做重复造轮子）。本类不自行实现
    向量索引与检索，而是包装一个外部 langchain 向量存储实例（须提供
    add_texts / similarity_search_by_vector），把框架统一的 VectorStore 接口
    映射到 langchain 的成熟实现。需要先安装对应 langchain 向量库（如
    langchain_community.vectorstores.FAISS / langchain_chroma）并自行构建实例传入。
    """

    def __init__(self, langchain_store=None, embedding_model=None):
        self._store = langchain_store
        self._embedding_model = embedding_model

    def add(self, documents: List[Document]) -> None:
        if self._store is None:
            return
        self._store.add_texts(
            [d.content for d in documents],
            metadatas=[d.metadata for d in documents],
        )

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None) -> None:
        if self._store is None:
            return
        self._store.add_texts(texts, metadatas=metadatas or [{}] * len(texts))

    def similarity_search(self, request: SearchRequest) -> List[Document]:
        if self._store is None:
            return []
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []
        docs = self._store.similarity_search_by_vector(emb, k=request.top_k)
        result: List[Document] = []
        for i, d in enumerate(docs):
            result.append(Document(
                id=getattr(d, "id", "") or f"langchain-{i}",
                content=getattr(d, "page_content", str(d)),
                embedding=emb,
                metadata=getattr(d, "metadata", {}) or {},
            ))
        return result

    def count(self) -> int:
        return 0 if self._store is None else getattr(self._store, "count", lambda: 0)()

    def clear(self) -> None:
        if self._store is None:
            return
        deleter = getattr(self._store, "delete_collection", None) \
            or getattr(self._store, "clear", None)
        if deleter:
            deleter()


def _safe_json_loads(val: Any) -> Optional[dict]:
    """安全 JSON 解析（兼容 str/bytes/dict）"""
    if isinstance(val, dict):
        return val
    if isinstance(val, bytes):
        try:
            val = val.decode(errors="ignore")
        except Exception:
            return None
    if not isinstance(val, str):
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


class RedisVectorStore(VectorStore):
    """
    Redis 向量存储 - 持久化 + 跨实例共享。

    复用框架 springbootai.utils.redis_client.RedisClient 封装（与 RedisChatMemory 统一接口）：
    优先用框架封装的 hash_set/hash_get_all/delete_key（自动 JSON 序列化/反序列化）；
    若传入原生 redis.Redis 或测试 FakeRedis（仅有 hset/hgetall/delete），自动降级原生接口。

    用 Redis hash 存储文档（id -> JSON{content,embedding,metadata}），
    检索时拉取全部并在 Python 端计算余弦相似度。
    适合中小规模（< 10 万文档）多副本部署；更大规模建议接入 RediSearch FTVECTOR。

    max_scan 参数限制单次检索扫描上限，防止数据量过大时 OOM。
    """

    KEY_PREFIX = "springpy:ai:vectorstore:"

    def __init__(self, redis_client=None, collection: str = "default",
                 embedding_model=None, max_scan: int = 10000):
        self._client = redis_client
        self.collection = collection
        self._embedding_model = embedding_model
        self.max_scan = max_scan

    def _key(self) -> str:
        return f"{self.KEY_PREFIX}{self.collection}"

    @staticmethod
    def _is_framework_client(client) -> bool:
        """是否框架 RedisClient 封装（提供 hash_set/hash_get_all）"""
        return (client is not None and hasattr(client, "hash_set")
                and hasattr(client, "hash_get_all"))

    @staticmethod
    def _raw_client(client):
        """原生 redis 客户端：框架封装取内部 client，否则透传"""
        return client.get_client() if hasattr(client, "get_client") else client

    def add(self, documents: List[Document]) -> None:
        if self._client is None:
            return
        for doc in documents:
            if not doc.embedding and self._embedding_model and doc.content:
                doc.embedding = self._embedding_model.embed_one(doc.content)
            record = {
                "id": doc.id, "content": doc.content,
                "embedding": doc.embedding or [], "metadata": doc.metadata,
            }
            if self._is_framework_client(self._client):
                # 复用框架 RedisClient 封装（自动 JSON 序列化）
                self._client.hash_set(self._key(), doc.id, record)
            else:
                # 降级：原生 redis 接口（兼容 redis.Redis / 测试 FakeRedis）
                try:
                    self._raw_client(self._client).hset(
                        self._key(), doc.id,
                        json.dumps(record, ensure_ascii=False))
                except Exception:
                    pass

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None,
                  ids: Optional[List[str]] = None) -> None:
        for i, text in enumerate(texts):
            doc_id = ids[i] if ids and i < len(ids) else f"doc-{i}"
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add([Document(id=doc_id, content=text, metadata=meta)])

    def _all_docs(self, max_scan: Optional[int] = None) -> List[Document]:
        if self._client is None:
            return []
        max_scan = max_scan if max_scan is not None else self.max_scan
        # max_scan <= 0 表示无限制（count() 场景）
        if self._is_framework_client(self._client):
            # 框架封装：hash_get_all 已自动 JSON 反序列化
            raw = self._client.hash_get_all(self._key()) or {}
        else:
            try:
                raw = self._raw_client(self._client).hgetall(self._key()) or {}
            except Exception:
                return []
        docs: List[Document] = []
        scanned = 0
        for field, val in raw.items():
            if max_scan > 0 and scanned >= max_scan:
                break
            d = _safe_json_loads(val)
            if not d:
                continue
            docs.append(Document(
                id=d.get("id", field if isinstance(field, str) else str(field)),
                content=d.get("content", ""),
                embedding=d.get("embedding", []),
                metadata=d.get("metadata", {}),
            ))
            scanned += 1
        return docs

    def similarity_search(self, request: SearchRequest) -> List[Document]:
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []
        scored = []
        for doc in self._all_docs():
            if not doc.embedding:
                continue
            # RAG 租户隔离：filter_expression 为 "key:value" 格式，仅返回匹配文档
            if request.filter_expression:
                if not self._match_filter(doc, request.filter_expression):
                    continue
            score = cosine_similarity(emb, doc.embedding)
            if score >= request.similarity_threshold:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:request.top_k]]

    @staticmethod
    def _match_filter(doc: Document, filter_expr: str) -> bool:
        """检查文档 metadata 是否匹配 filter_expression。

        支持两种格式：
        - ``"key:value"`` — metadata 中的 key 值等于 value
        - ``"key:"`` — metadata 中 key 存在且非空即可
        """
        if ":" not in filter_expr:
            return str(filter_expr).lower() in str(doc.metadata).lower()
        key, _, value = filter_expr.partition(":")
        key = key.strip()
        actual = doc.metadata.get(key)
        if not value:  # 仅检查键是否存在
            return actual is not None and actual != ""
        return str(actual) == value.strip()

    def count(self) -> int:
        return len(self._all_docs(max_scan=0))  # 0 = 无限制，count 需准确

    def clear(self) -> None:
        if self._client is None:
            return
        if self._is_framework_client(self._client):
            self._client.delete_key(self._key())
        else:
            try:
                self._raw_client(self._client).delete(self._key())
            except Exception:
                pass
