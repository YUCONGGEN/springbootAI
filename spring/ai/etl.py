"""
文档 ETL - DocumentReader（读取原始文档） + TextSplitter（切片），为 RAG 入库服务。

对齐 Spring AI 的 DocumentReader / TextSplitter 抽象。
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TextDocument:
    """ETL 文档"""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return self.metadata.get("source", "")


class DocumentReader(ABC):
    """文档读取器抽象"""

    @abstractmethod
    def read(self) -> List[TextDocument]:
        """读取并返回文档列表"""


class TextReader(DocumentReader):
    """纯文本/Markdown 文件读取器"""

    def __init__(self, source: str = "", encoding: str = "utf-8"):
        self.source = source
        self.encoding = encoding

    def read(self) -> List[TextDocument]:
        if not self.source:
            return []
        # 从文件路径读取
        if os.path.isfile(self.source):
            with open(self.source, "r", encoding=self.encoding) as f:
                return [TextDocument(content=f.read(),
                                     metadata={"source": self.source})]
        # 直接作为文本内容
        return [TextDocument(content=self.source, metadata={"source": "inline"})]

    def read_text(self, content: str, source: str = "inline") -> TextDocument:
        """直接读取文本字符串"""
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
                 min_chunk_size: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def split(self, documents: List[TextDocument]) -> List[TextDocument]:
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
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, documents: List[TextDocument]) -> List[TextDocument]:
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
