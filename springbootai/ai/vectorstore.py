"""
向量存储抽象与内存实现 - 为 RAG 提供文档向量的存储与相似度检索。

生产环境可替换为 PGVector / Milvus / Chroma 等实现（实现同一 VectorStore 接口）。
"""
import asyncio
import json
import logging
import math
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger("Spring.AI.VectorStore")


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
    filter_metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int):
            raise TypeError("SearchRequest top_k must be an integer")
        if self.top_k <= 0:
            raise ValueError("SearchRequest top_k must be greater than zero")
        if self.top_k > 1000:
            raise ValueError("SearchRequest top_k must not exceed 1000")
        try:
            threshold = float(self.similarity_threshold)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "SearchRequest similarity_threshold must be a finite number"
            ) from exc
        if not math.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
            raise ValueError(
                "SearchRequest similarity_threshold must be between -1 and 1"
            )
        self.similarity_threshold = threshold


class VectorStore(ABC):
    """向量存储抽象"""

    @abstractmethod
    def add(self, documents: List[Document]) -> None:
        """写入文档（需已包含 embedding）"""

    @abstractmethod
    def similarity_search(self, request: SearchRequest) -> List[Document]:
        """相似度检索"""


def _parse_filter_expression(filter_expression: str) -> tuple[str, str]:
    """Parse the public ``key:value`` filter syntax without fail-open cases."""
    expression = str(filter_expression)
    if ":" not in expression:
        raise ValueError("filter_expression must use non-empty 'key:value' syntax")
    key, _, value = expression.partition(":")
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise ValueError("filter_expression key and value must not be empty")
    return key, value


def _positive_limit(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be in [1, {maximum}]")
    return value


def _validate_document_resource(
        document: Document, *, max_content_length: int,
        max_embedding_dimensions: int, max_metadata_size: int) -> None:
    if len(str(document.content)) > max_content_length:
        raise ValueError("vector document content exceeds configured limit")
    if not isinstance(document.embedding, (list, tuple)):
        raise ValueError("vector document embedding must be a list or tuple")
    if len(document.embedding or []) > max_embedding_dimensions:
        raise ValueError("vector embedding dimensions exceed configured limit")
    if not isinstance(document.metadata, dict):
        raise ValueError("vector document metadata must be an object")
    try:
        metadata_size = len(json.dumps(
            document.metadata or {}, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("vector document metadata must be JSON serializable") from exc
    if metadata_size > max_metadata_size:
        raise ValueError("vector document metadata exceeds configured limit")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        left = [float(value) for value in a]
        right = [float(value) for value in b]
    except (TypeError, ValueError):
        return 0.0
    if not all(math.isfinite(value) for value in (*left, *right)):
        return 0.0
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    na = math.sqrt(sum(x * x for x in left))
    nb = math.sqrt(sum(y * y for y in right))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SimpleInMemoryVectorStore(VectorStore):
    """内存向量存储 - 开发/测试用，余弦相似度"""

    def __init__(self, embedding_model=None, max_documents: int = 10_000,
                 max_content_length: int = 1_000_000,
                 max_embedding_dimensions: int = 65_536,
                 max_metadata_size: int = 256 * 1024):
        self._docs: List[Document] = []
        self._embedding_model = embedding_model
        self._lock = threading.RLock()
        self.max_documents = _positive_limit(
            max_documents, "max_documents", 1_000_000)
        self.max_content_length = _positive_limit(
            max_content_length, "max_content_length", 100_000_000)
        self.max_embedding_dimensions = _positive_limit(
            max_embedding_dimensions, "max_embedding_dimensions", 1_000_000)
        self.max_metadata_size = _positive_limit(
            max_metadata_size, "max_metadata_size", 10_000_000)

    def add(self, documents: List[Document]) -> None:
        prepared = []
        for doc in documents:
            if not doc.embedding and self._embedding_model and doc.content:
                doc.embedding = self._embedding_model.embed_one(doc.content)
            _validate_document_resource(
                doc, max_content_length=self.max_content_length,
                max_embedding_dimensions=self.max_embedding_dimensions,
                max_metadata_size=self.max_metadata_size,
            )
            prepared.append(doc)
        with self._lock:
            if len(self._docs) + len(prepared) > self.max_documents:
                raise RuntimeError("in-memory vector document limit exceeded")
            self._docs.extend(prepared)

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None) -> None:
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add([Document(id=f"doc-{uuid.uuid4().hex}", content=text,
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
                filter_metadata=kwargs.get("filter_metadata"),
            )
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []

        parsed_filter = (
            _parse_filter_expression(request.filter_expression)
            if request.filter_expression else None
        )
        scored = []
        with self._lock:
            documents = list(self._docs)
        for doc in documents:
            if not doc.embedding:
                continue
            # RAG 租户隔离：filter_expression 仅返回匹配文档
            if parsed_filter:
                if not RedisVectorStore._match_parsed_filter(doc, parsed_filter):
                    continue
            if request.filter_metadata:
                if not RedisVectorStore._match_metadata(doc, request.filter_metadata):
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
        with self._lock:
            return len(self._docs)

    def clear(self) -> None:
        with self._lock:
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
        """异步检索；同步 embedding/检索工作移出事件循环。"""
        return await asyncio.to_thread(self.invoke, query, config)


class LangChainVectorStore(VectorStore):
    """
    LangChain 向量存储适配器 - 包装 langchain 生态的 VectorStore（FAISS/Chroma 等）。

    设计原则：能用 LangChain 就用 LangChain（不做重复造轮子）。本类不自行实现
    向量索引与检索，而是包装一个外部 langchain 向量存储实例（须提供
    add_texts / similarity_search_by_vector），把框架统一的 VectorStore 接口
    映射到 langchain 的成熟实现。需要先安装对应 langchain 向量库（如
    langchain_community.vectorstores.FAISS / langchain_chroma）并自行构建实例传入。
    """

    def __init__(self, langchain_store=None, embedding_model=None,
                 max_batch_documents: int = 10_000,
                 max_content_length: int = 1_000_000,
                 max_embedding_dimensions: int = 65_536,
                 max_metadata_size: int = 256 * 1024):
        self._store = langchain_store
        self._embedding_model = embedding_model
        self.max_batch_documents = _positive_limit(
            max_batch_documents, "max_batch_documents", 1_000_000)
        self.max_content_length = _positive_limit(
            max_content_length, "max_content_length", 100_000_000)
        self.max_embedding_dimensions = _positive_limit(
            max_embedding_dimensions, "max_embedding_dimensions", 1_000_000)
        self.max_metadata_size = _positive_limit(
            max_metadata_size, "max_metadata_size", 10_000_000)

    def _validate_documents(self, documents: List[Document]) -> None:
        if len(documents) > self.max_batch_documents:
            raise ValueError("vector document batch exceeds configured limit")
        for document in documents:
            _validate_document_resource(
                document, max_content_length=self.max_content_length,
                max_embedding_dimensions=self.max_embedding_dimensions,
                max_metadata_size=self.max_metadata_size,
            )

    def add(self, documents: List[Document]) -> None:
        if self._store is None:
            return
        self._validate_documents(documents)
        self._store.add_texts(
            [d.content for d in documents],
            metadatas=[d.metadata for d in documents],
        )

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None) -> None:
        if self._store is None:
            return
        metadata_values = list(metadatas or [])[:len(texts)]
        metadata_values.extend(
            {} for _ in range(len(texts) - len(metadata_values)))
        documents = [Document(
            id=f"langchain-input-{index}", content=text,
            metadata=(metadata_values[index]
                      if index < len(metadata_values) else {}),
        ) for index, text in enumerate(texts)]
        self._validate_documents(documents)
        self._store.add_texts(texts, metadatas=metadata_values)

    def similarity_search(self, request: SearchRequest) -> List[Document]:
        if self._store is None:
            return []
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []
        filters = dict(request.filter_metadata or {})
        if request.filter_expression:
            key, value = _parse_filter_expression(request.filter_expression)
            filters.setdefault(key, value)
        scored_docs = None
        relevance_search = getattr(
            self._store, "similarity_search_with_relevance_scores", None)
        if relevance_search is not None and request.query:
            try:
                search_kwargs: Dict[str, Any] = {"k": request.top_k}
                if filters:
                    search_kwargs["filter"] = filters
                scored_docs = list(
                    relevance_search(request.query, **search_kwargs))
            except TypeError as exc:
                if not filters:
                    raise
                raise RuntimeError(
                    "the configured LangChain vector store does not support "
                    "metadata filters required for isolated retrieval"
                ) from exc
            if len(scored_docs) > self.max_batch_documents:
                raise RuntimeError(
                    "LangChain vector result batch exceeds configured limit")
            scored_docs = scored_docs[:request.top_k]
            docs = [item[0] for item in scored_docs]
        elif request.similarity_threshold != 0.0:
            raise RuntimeError(
                "the configured LangChain vector store cannot enforce "
                "similarity_threshold; provide a backend implementing "
                "similarity_search_with_relevance_scores"
            )
        elif filters:
            try:
                docs = list(self._store.similarity_search_by_vector(
                    emb, k=request.top_k, filter=filters))
            except TypeError as exc:
                # Never issue an unfiltered query when tenant/user isolation was
                # requested. That would turn a compatibility fallback into a
                # cross-tenant disclosure.
                raise RuntimeError(
                    "the configured LangChain vector store does not support "
                    "metadata filters required for isolated retrieval"
                ) from exc
        else:
            docs = list(self._store.similarity_search_by_vector(
                emb, k=request.top_k))
        if len(docs) > self.max_batch_documents:
            raise RuntimeError(
                "LangChain vector result batch exceeds configured limit")
        docs = docs[:request.top_k]
        result: List[Document] = []
        for i, d in enumerate(docs):
            if scored_docs is not None:
                try:
                    score = float(scored_docs[i][1])
                except (IndexError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "LangChain vector store returned an invalid relevance score"
                    ) from exc
                if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                    raise RuntimeError(
                        "LangChain vector store returned an invalid relevance score")
                if score < request.similarity_threshold:
                    continue
            raw_embedding = getattr(d, "embedding", None)
            document = Document(
                id=getattr(d, "id", "") or f"langchain-{i}",
                content=getattr(d, "page_content", str(d)),
                embedding=(list(raw_embedding)
                           if isinstance(raw_embedding, (list, tuple)) else []),
                metadata=getattr(d, "metadata", {}) or {},
            )
            self._validate_documents([document])
            result.append(document)
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
                 embedding_model=None, max_scan: int = 10000,
                 max_content_length: int = 1_000_000,
                 max_embedding_dimensions: int = 65_536,
                 max_metadata_size: int = 256 * 1024,
                 max_scan_bytes: int = 100 * 1024 * 1024):
        self._client = redis_client
        self.collection = collection
        self._embedding_model = embedding_model
        if isinstance(max_scan, bool) or not isinstance(max_scan, int):
            raise TypeError("RedisVectorStore max_scan must be an integer")
        if not 1 <= max_scan <= 1_000_000:
            raise ValueError("RedisVectorStore max_scan must be in [1, 1000000]")
        self.max_scan = max_scan
        self.max_content_length = _positive_limit(
            max_content_length, "max_content_length", 100_000_000)
        self.max_embedding_dimensions = _positive_limit(
            max_embedding_dimensions, "max_embedding_dimensions", 1_000_000)
        self.max_metadata_size = _positive_limit(
            max_metadata_size, "max_metadata_size", 10_000_000)
        self.max_scan_bytes = _positive_limit(
            max_scan_bytes, "max_scan_bytes", 1_000_000_000)

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
            _validate_document_resource(
                doc, max_content_length=self.max_content_length,
                max_embedding_dimensions=self.max_embedding_dimensions,
                max_metadata_size=self.max_metadata_size,
            )
            record = {
                "id": doc.id, "content": doc.content,
                "embedding": doc.embedding or [], "metadata": doc.metadata,
            }
            try:
                raw = self._raw_client(self._client)
                if raw is not None and hasattr(raw, "hset"):
                    raw.hset(
                        self._key(), doc.id,
                        json.dumps(record, ensure_ascii=False))
                elif self._is_framework_client(self._client):
                    self._client.hash_set(self._key(), doc.id, record)
                else:
                    raise RuntimeError("Redis client does not support hash writes")
            except Exception as exc:
                logger.warning(
                    "Redis vector write failed collection=%s error_type=%s",
                    self.collection, type(exc).__name__,
                )
                raise RuntimeError("Redis vector write failed") from None

    def add_texts(self, texts: List[str],
                  metadatas: Optional[List[Dict]] = None,
                  ids: Optional[List[str]] = None) -> None:
        for i, text in enumerate(texts):
            doc_id = (ids[i] if ids and i < len(ids)
                      else f"doc-{uuid.uuid4().hex}")
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add([Document(id=doc_id, content=text, metadata=meta)])

    def _all_docs(self, max_scan: Optional[int] = None) -> List[Document]:
        if self._client is None:
            return []
        max_scan = max_scan if max_scan is not None else self.max_scan
        # Prefer incremental HSCAN. HGETALL defeats max_scan because Redis must
        # materialize the entire collection before Python can truncate it.
        raw_client = self._raw_client(self._client)
        docs: List[Document] = []
        scanned = 0
        scanned_bytes = 0

        def consume(entries) -> None:
            nonlocal scanned, scanned_bytes
            for redis_field, val in entries:
                if max_scan > 0 and scanned >= max_scan:
                    return
                try:
                    field_size = len(
                        redis_field if isinstance(redis_field, bytes)
                        else str(redis_field).encode("utf-8"))
                    if isinstance(val, bytes):
                        value_size = len(val)
                    elif isinstance(val, str):
                        value_size = len(val.encode("utf-8"))
                    else:
                        value_size = len(json.dumps(
                            val, ensure_ascii=False).encode("utf-8"))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "Redis vector record is not serializable") from exc
                scanned_bytes += field_size + value_size
                if scanned_bytes > self.max_scan_bytes:
                    raise RuntimeError("Redis vector scan exceeds max_scan_bytes")
                data = _safe_json_loads(val)
                if not isinstance(data, dict):
                    raise RuntimeError("Redis vector record contains invalid JSON")
                document = Document(
                    id=data.get(
                        "id",
                        redis_field if isinstance(redis_field, str)
                        else str(redis_field),
                    ),
                    content=data.get("content", ""),
                    embedding=data.get("embedding", []),
                    metadata=data.get("metadata", {}),
                )
                try:
                    _validate_document_resource(
                        document,
                        max_content_length=self.max_content_length,
                        max_embedding_dimensions=self.max_embedding_dimensions,
                        max_metadata_size=self.max_metadata_size,
                    )
                except ValueError as exc:
                    raise RuntimeError(
                        "Redis vector record exceeds configured resource limits"
                    ) from exc
                docs.append(document)
                scanned += 1

        try:
            if raw_client is not None and hasattr(raw_client, "hscan"):
                cursor = 0
                while True:
                    cursor, batch = raw_client.hscan(
                        self._key(), cursor=cursor,
                        count=min(max_scan or self.max_scan, 1000),
                    )
                    consume((batch or {}).items())
                    if max_scan and max_scan > 0 and scanned >= max_scan:
                        break
                    if int(cursor) == 0:
                        break
            elif raw_client is not None and hasattr(raw_client, "hgetall"):
                consume((raw_client.hgetall(self._key()) or {}).items())
            elif self._is_framework_client(self._client):
                consume((self._client.hash_get_all(self._key()) or {}).items())
            else:
                return []
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(
                "Redis vector scan failed collection=%s error_type=%s",
                self.collection, type(exc).__name__,
            )
            raise RuntimeError("Redis vector scan failed") from None
        return docs

    def similarity_search(self, request: SearchRequest) -> List[Document]:
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []
        total = self.count()
        if total > self.max_scan:
            raise RuntimeError(
                f"Redis vector collection contains {total} documents, exceeding "
                f"max_scan={self.max_scan}; use a vector index or raise the limit")
        parsed_filter = (
            _parse_filter_expression(request.filter_expression)
            if request.filter_expression else None
        )
        scored = []
        for doc in self._all_docs():
            if not doc.embedding:
                continue
            # RAG 租户隔离：filter_expression 为 "key:value" 格式，仅返回匹配文档
            if parsed_filter:
                if not self._match_parsed_filter(doc, parsed_filter):
                    continue
            if request.filter_metadata:
                if not self._match_metadata(doc, request.filter_metadata):
                    continue
            score = cosine_similarity(emb, doc.embedding)
            if score >= request.similarity_threshold:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:request.top_k]]

    @staticmethod
    def _match_filter(doc: Document, filter_expr: str) -> bool:
        """检查文档 metadata 是否匹配 filter_expression。

        仅支持非空 ``"key:value"``，非法表达式会被拒绝而不是降级查询。
        """
        return RedisVectorStore._match_parsed_filter(
            doc, _parse_filter_expression(filter_expr))

    @staticmethod
    def _match_parsed_filter(doc: Document,
                             parsed_filter: tuple[str, str]) -> bool:
        if not isinstance(doc.metadata, dict):
            return False
        key, value = parsed_filter
        return str(doc.metadata.get(key)) == value

    @staticmethod
    def _match_metadata(doc: Document, filters: Dict[str, Any]) -> bool:
        """Require every metadata predicate to match (fail-closed AND ACL)."""
        if not isinstance(doc.metadata, dict):
            return False
        return all(str(doc.metadata.get(key)) == str(value)
                   for key, value in filters.items())

    def count(self) -> int:
        if self._client is None:
            return 0
        raw = self._raw_client(self._client)
        try:
            if raw is not None and hasattr(raw, "hlen"):
                return int(raw.hlen(self._key()))
        except Exception as exc:
            logger.warning(
                "Redis vector count failed collection=%s error_type=%s",
                self.collection, type(exc).__name__,
            )
            raise RuntimeError("Redis vector count failed") from None
        return len(self._all_docs(max_scan=0))

    def clear(self) -> None:
        if self._client is None:
            return
        try:
            if self._is_framework_client(self._client):
                self._client.delete_key(self._key())
            else:
                self._raw_client(self._client).delete(self._key())
        except Exception as exc:
            logger.warning(
                "Redis vector clear failed collection=%s error_type=%s",
                self.collection, type(exc).__name__,
            )
            raise RuntimeError("Redis vector clear failed") from None
