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

    def similarity_search(self, request: SearchRequest) -> List[Document]:
        emb = request.embedding
        if emb is None and self._embedding_model and request.query:
            emb = self._embedding_model.embed_one(request.query)
        if emb is None:
            return []

        scored = []
        for doc in self._docs:
            if not doc.embedding:
                continue
            score = cosine_similarity(emb, doc.embedding)
            if score >= request.similarity_threshold:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:request.top_k]]

    def count(self) -> int:
        return len(self._docs)

    def clear(self) -> None:
        self._docs.clear()


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

    复用框架 spring.utils.redis_client.RedisClient 封装（与 RedisChatMemory 统一接口）：
    优先用框架封装的 hash_set/hash_get_all/delete_key（自动 JSON 序列化/反序列化）；
    若传入原生 redis.Redis 或测试 FakeRedis（仅有 hset/hgetall/delete），自动降级原生接口。

    用 Redis hash 存储文档（id -> JSON{content,embedding,metadata}），
    检索时拉取全部并在 Python 端计算余弦相似度。
    适合中小规模（< 10 万文档）多副本部署；更大规模建议接入 RediSearch FTVECTOR。
    """

    KEY_PREFIX = "springpy:ai:vectorstore:"

    def __init__(self, redis_client=None, collection: str = "default",
                 embedding_model=None):
        self._client = redis_client
        self.collection = collection
        self._embedding_model = embedding_model

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

    def _all_docs(self) -> List[Document]:
        if self._client is None:
            return []
        if self._is_framework_client(self._client):
            # 框架封装：hash_get_all 已自动 JSON 反序列化
            raw = self._client.hash_get_all(self._key()) or {}
        else:
            try:
                raw = self._raw_client(self._client).hgetall(self._key()) or {}
            except Exception:
                return []
        docs: List[Document] = []
        for field, val in raw.items():
            d = _safe_json_loads(val)
            if not d:
                continue
            docs.append(Document(
                id=d.get("id", field if isinstance(field, str) else str(field)),
                content=d.get("content", ""),
                embedding=d.get("embedding", []),
                metadata=d.get("metadata", {}),
            ))
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
            score = cosine_similarity(emb, doc.embedding)
            if score >= request.similarity_threshold:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:request.top_k]]

    def count(self) -> int:
        return len(self._all_docs())

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
