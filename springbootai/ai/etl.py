"""
文档 ETL - DocumentReader（读取原始文档） + TextSplitter（切片），为 RAG 入库服务。

对齐 Spring AI 的 DocumentReader / TextSplitter 抽象。
设计原则：能用 LangChain 就用 LangChain（不做重复造轮子）——
切片逻辑优先委托 `langchain-text-splitters` 的成熟实现（递归分隔符 / 字符分隔），
仅当该包未安装时降级为内置实现，保证开箱即用。
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


class DocumentTooLargeError(ValueError):
    """Raised before an ETL document can consume unbounded process memory."""


def _has_langchain_splitters() -> bool:
    """探测是否安装了 langchain-text-splitters（切片器专属轻量包）。"""
    try:
        import langchain_text_splitters  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class TextDocument:
    """ETL 文档"""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return self.metadata.get("source", "")


def _wrap_langchain_chunks(chunks: List[str],
                           doc: TextDocument) -> List[TextDocument]:
    """把 LangChain 切片结果映射为框架 TextDocument，并补齐 chunk_index 元数据。"""
    result: List[TextDocument] = []
    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue
        meta = dict(doc.metadata)
        meta["chunk_index"] = idx
        result.append(TextDocument(content=chunk, metadata=meta))
    return result


class DocumentReader(ABC):
    """文档读取器抽象"""

    @abstractmethod
    def read(self) -> List[TextDocument]:
        """读取并返回文档列表"""


class TextReader(DocumentReader):
    """纯文本/Markdown 文件读取器"""

    DEFAULT_MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, source: str | os.PathLike = "",
                 encoding: str = "utf-8",
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 strict_path: bool = False):
        self.source = source
        self.encoding = encoding
        try:
            self.max_bytes = int(max_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("TextReader max_bytes must be a non-negative integer") from exc
        if self.max_bytes < 0:
            raise ValueError("TextReader max_bytes must not be negative")
        self.strict_path = bool(strict_path)

    @classmethod
    def from_file(cls, path: str | os.PathLike, **kwargs) -> "TextReader":
        """Create a reader that fails clearly when the expected file is absent."""
        return cls(path, strict_path=True, **kwargs)

    def _check_size(self, size: int, source: str) -> None:
        if self.max_bytes > 0 and size > self.max_bytes:
            raise DocumentTooLargeError(
                f"Document exceeds max_bytes={self.max_bytes}: {source}")

    def read(self) -> List[TextDocument]:
        if not self.source:
            return []
        source = os.fspath(self.source)
        # 从文件路径读取
        if os.path.isfile(source):
            self._check_size(os.path.getsize(source), source)
            with open(source, "rb") as file_handle:
                read_size = self.max_bytes + 1 if self.max_bytes > 0 else -1
                raw = file_handle.read(read_size)
            self._check_size(len(raw), source)
            content = raw.decode(self.encoding)
            return [TextDocument(
                content=content, metadata={"source": source},
            )]
        if self.strict_path:
            raise FileNotFoundError(f"Document file does not exist: {source}")
        # 直接作为文本内容
        self._check_size(len(source.encode(self.encoding)), "inline")
        return [TextDocument(content=source, metadata={"source": "inline"})]

    def read_text(self, content: str, source: str = "inline") -> TextDocument:
        """直接读取文本字符串"""
        self._check_size(len(content.encode(self.encoding)), source)
        return TextDocument(content=content, metadata={"source": source})


class TextSplitter(ABC):
    """文档切片器抽象"""

    @abstractmethod
    def split(self, documents: List[TextDocument]) -> List[TextDocument]:
        """将文档切片为更小的块"""


class TokenTextSplitter(TextSplitter):
    """
    基于 token 近似计数的切片器。
    生产可替换为 tiktoken 精确计数；此处用字符近似（4 char ≈ 1 token）。
    """

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 200,
                 min_chunk_size: int | None = None):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        if self.chunk_size <= 0:
            raise ValueError("TokenTextSplitter chunk_size must be greater than zero")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError(
                "TokenTextSplitter chunk_overlap must be >= 0 and < chunk_size")
        # The historical default was 100.  For explicitly small chunk sizes,
        # treating that implicit default as an invalid user value broke normal
        # usage, so derive a bounded default while still rejecting an explicit
        # impossible minimum.
        self.min_chunk_size = (
            min(100, self.chunk_size)
            if min_chunk_size is None else int(min_chunk_size)
        )
        if not 0 <= self.min_chunk_size <= self.chunk_size:
            raise ValueError(
                "TokenTextSplitter min_chunk_size must be between 0 and chunk_size")

    def split(self, documents: List[TextDocument]) -> List[TextDocument]:
        # LangChain 优先：递归字符切片（自动按 \n\n/\n/空格/标点逐级切分，语义更佳）
        if _has_langchain_splitters():
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            lc = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size * 4,   # 保持 4 char ≈ 1 token 语义
                chunk_overlap=min(self.chunk_overlap * 4,
                                  self.chunk_size * 4 - 1),
            )
            result: List[TextDocument] = []
            for doc in documents:
                if not doc.content:
                    continue
                result.extend(_wrap_langchain_chunks(lc.split_text(doc.content), doc))
            return result

        result: List[TextDocument] = []
        for doc in documents:
            text = doc.content
            if not text:
                continue
            # token 近似：4 字符 ≈ 1 token
            chunk_chars = self.chunk_size * 4
            overlap_chars = self.chunk_overlap * 4
            if len(text) <= chunk_chars:
                result.append(TextDocument(content=text, metadata=dict(doc.metadata)))
                continue
            start = 0
            idx = 0
            while start < len(text):
                end = min(start + chunk_chars, len(text))
                chunk = text[start:end]
                if len(chunk) >= self.min_chunk_size * 4 or start == 0:
                    meta = dict(doc.metadata)
                    meta["chunk_index"] = idx
                    result.append(TextDocument(content=chunk, metadata=meta))
                    idx += 1
                if end >= len(text):
                    break
                start = end - overlap_chars
        return result


class CharacterTextSplitter(TextSplitter):
    """按分隔符切片"""

    def __init__(self, separator: str = "\n\n", chunk_size: int = 1000,
                 chunk_overlap: int = 200):
        self.separator = separator
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        if self.chunk_size <= 0:
            raise ValueError(
                "CharacterTextSplitter chunk_size must be greater than zero")
        if self.chunk_overlap < 0:
            raise ValueError(
                "CharacterTextSplitter chunk_overlap must not be negative")
        # Preserve the historical convenience where callers only reduced
        # chunk_size and relied on the default overlap being clamped.
        self.chunk_overlap = min(self.chunk_overlap, self.chunk_size - 1)

    def split(self, documents: List[TextDocument]) -> List[TextDocument]:
        # LangChain 优先：字符分隔切片
        if _has_langchain_splitters():
            from langchain_text_splitters import CharacterTextSplitter as LCCharSplit
            lc = LCCharSplit(
                separator=self.separator,
                chunk_size=self.chunk_size,
                # LangChain 要求 overlap < chunk_size；内置降级实现不应用 overlap，
                # 此处夹紧以保证默认 chunk_size=30 等边界场景在安装后同样可用
                chunk_overlap=min(self.chunk_overlap, self.chunk_size - 1),
            )
            result: List[TextDocument] = []
            for doc in documents:
                if not doc.content:
                    continue
                result.extend(_wrap_langchain_chunks(lc.split_text(doc.content), doc))
            return result

        result: List[TextDocument] = []
        for doc in documents:
            parts = doc.content.split(self.separator)
            buffer = ""
            idx = 0
            for part in parts:
                candidate = buffer + self.separator + part if buffer else part
                if len(candidate) > self.chunk_size and buffer:
                    meta = dict(doc.metadata)
                    meta["chunk_index"] = idx
                    result.append(TextDocument(content=buffer, metadata=meta))
                    idx += 1
                    buffer = part
                else:
                    buffer = candidate
            if buffer:
                meta = dict(doc.metadata)
                meta["chunk_index"] = idx
                result.append(TextDocument(content=buffer, metadata=meta))
        return result
