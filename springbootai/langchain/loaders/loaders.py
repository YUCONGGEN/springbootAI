"""Bounded, policy-aware LangChain document loader registry.

Local sources are restricted to ``AI_LOADER_ALLOWED_ROOTS`` (``os.pathsep``
separated); when unset, the process working directory is the only allowed
root. Callers may pass ``allowed_roots`` explicitly. Every loader accepts the
security-only keyword arguments ``max_source_bytes``, ``max_content_bytes``
and ``max_documents``. Web loading permits only a directly connected public
HTTP(S) response: redirects, environment proxies, private DNS answers and
unverifiable/private connected peers are rejected by default.
"""
from __future__ import annotations

import importlib
import ipaddress
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence
from urllib.parse import urlparse


logger = logging.getLogger("Spring.LangChain")

DEFAULT_MAX_SOURCE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_CONTENT_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_DOCUMENTS = 1000
DEFAULT_WEB_TIMEOUT = 10.0


def _allow_private_network() -> bool:
    return os.environ.get(
        "AI_LOADER_ALLOW_PRIVATE_NETWORK", "false"
    ).strip().lower() in {"true", "1", "yes", "on"}


def _is_unsafe_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    return not parsed.is_global


def _is_private_url(url_str: str) -> bool:
    """Resolve every answer and reject if any destination is not public."""
    try:
        parsed = urlparse(url_str)
        hostname = parsed.hostname or ""
        if not hostname:
            return True
        if hostname.lower().rstrip(".") in {
            "localhost", "metadata", "metadata.google.internal",
        }:
            return True
        try:
            addresses = {str(ipaddress.ip_address(hostname))}
        except ValueError:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        return not addresses or any(
            _is_unsafe_address(address) for address in addresses
        )
    except (OSError, ValueError):
        return True


def _validate_url(url_str: str) -> None:
    if not isinstance(url_str, str) or not url_str or len(url_str) > 2048 or "\x00" in url_str:
        raise PermissionError("URL 无效或超过 2048 字符")
    parsed = urlparse(url_str)
    if parsed.scheme not in {"http", "https"}:
        raise PermissionError("仅允许 http/https URL")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise PermissionError("URL 必须包含主机且不能包含凭据")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise PermissionError("URL 端口无效") from exc
    if parsed.fragment:
        raise PermissionError("URL 不允许包含片段")
    if not _allow_private_network() and _is_private_url(url_str):
        raise PermissionError(
            "拒绝私网、回环、保留、元数据或无法解析的 URL 地址"
        )


def _configured_roots(explicit: Optional[Sequence[str]] = None) -> List[Path]:
    if isinstance(explicit, (str, os.PathLike)):
        explicit = [str(explicit)]
    if explicit:
        values = list(explicit)
    else:
        configured = os.environ.get("AI_LOADER_ALLOWED_ROOTS", "")
        values = (
            [item for item in configured.split(os.pathsep) if item]
            if configured else [os.getcwd()]
        )
    roots = []
    for value in values:
        try:
            root = Path(value).resolve(strict=True)
        except OSError as exc:
            raise PermissionError("配置的文档允许根目录不存在") from exc
        if not root.is_dir():
            raise PermissionError("文档允许根目录必须是目录")
        roots.append(root)
    return roots


def _under_root(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _validate_file_path(
    file_path: str,
    *,
    allowed_roots: Optional[Sequence[str]] = None,
    expect_directory: bool = False,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
) -> str:
    """Resolve symlinks and enforce an application-data directory allowlist."""
    if not isinstance(file_path, str) or not file_path or "\x00" in file_path:
        raise PermissionError("文件路径不能为空")
    try:
        resolved = Path(file_path).resolve(strict=True)
        roots = _configured_roots(allowed_roots)
        if not _under_root(resolved, roots):
            raise PermissionError("文件路径不在 AI_LOADER_ALLOWED_ROOTS 允许目录内")
        if expect_directory and not resolved.is_dir():
            raise PermissionError("文档源必须是目录")
        if not expect_directory and not resolved.is_file():
            raise PermissionError("文档源必须是普通文件")

        maximum = max(1, int(max_source_bytes))
        document_limit = max(1, int(max_documents))
        if not expect_directory:
            if resolved.stat().st_size > maximum:
                raise PermissionError("文档源超过 max_source_bytes")
        else:
            count = 0
            total = 0
            for candidate in resolved.rglob("*"):
                if not candidate.is_file():
                    continue
                target = candidate.resolve(strict=True)
                if not _under_root(target, roots):
                    raise PermissionError("目录包含指向允许根目录之外的文件")
                size = target.stat().st_size
                if size > maximum:
                    raise PermissionError("目录内文件超过 max_source_bytes")
                count += 1
                total += size
                if count > document_limit:
                    raise PermissionError("目录文件数超过 max_documents")
                if total > maximum * min(document_limit, 1000):
                    raise PermissionError("目录输入总量过大")
        return str(resolved)
    except PermissionError:
        raise
    except (OSError, ValueError) as exc:
        raise PermissionError("无法安全解析文档路径") from exc


def _peer_address(response: Any) -> Optional[str]:
    candidates = [
        getattr(getattr(response.raw, "connection", None), "sock", None),
        getattr(getattr(response.raw, "_connection", None), "sock", None),
    ]
    try:
        candidates.append(response.raw._fp.fp.raw._sock)
    except AttributeError:
        pass
    for sock in candidates:
        if sock is not None:
            try:
                return str(sock.getpeername()[0])
            except OSError:
                continue
    return None


class _SafeWebLoader:
    """Fetch one public web page with peer validation and streaming limits."""

    def __init__(
        self,
        source: str,
        *,
        max_source_bytes: int,
        timeout: float = DEFAULT_WEB_TIMEOUT,
        headers: Optional[dict] = None,
        encoding: Optional[str] = None,
        bs_kwargs: Optional[dict] = None,
    ):
        self.source = source
        self.max_source_bytes = max(1, int(max_source_bytes))
        self.timeout = min(DEFAULT_WEB_TIMEOUT, max(0.1, float(timeout)))
        self.headers = dict(headers or {})
        self.encoding = encoding
        self.bs_kwargs = dict(bs_kwargs or {})

    def load(self) -> List[Any]:
        _validate_url(self.source)
        try:
            import requests
            from bs4 import BeautifulSoup
            from langchain_core.documents import Document
        except ImportError as exc:
            raise ImportError(
                "web 加载器需要 requests、beautifulsoup4 和 langchain-core"
            ) from exc

        session = requests.Session()
        session.trust_env = False
        response = None
        try:
            response = session.get(
                self.source,
                headers=self.headers,
                timeout=(self.timeout, self.timeout),
                stream=True,
                allow_redirects=False,
                verify=True,
            )
            if 300 <= response.status_code < 400:
                raise PermissionError("网页重定向被拒绝；请显式校验最终 URL")
            response.raise_for_status()
            peer = _peer_address(response)
            if not _allow_private_network() and (
                peer is None or _is_unsafe_address(peer)
            ):
                raise PermissionError("实际网络连接对端不是可验证的公网地址")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_source_bytes:
                raise PermissionError("网页响应超过 max_source_bytes")
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(
                allowed in content_type
                for allowed in ("text/html", "application/xhtml+xml", "text/plain")
            ):
                raise PermissionError("网页响应 Content-Type 不受支持")
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_source_bytes:
                    raise PermissionError("网页响应超过 max_source_bytes")
                chunks.append(chunk)
            charset = self.encoding or response.encoding or "utf-8"
            html = b"".join(chunks).decode(charset, errors="replace")
            soup = BeautifulSoup(html, "html.parser", **self.bs_kwargs)
            title = soup.title.get_text(strip=True) if soup.title else ""
            return [Document(
                page_content=soup.get_text("\n", strip=True),
                metadata={"source": self.source, "title": title},
            )]
        finally:
            if response is not None:
                response.close()
            session.close()


class _BoundedLoader:
    def __init__(self, loader: Any, max_documents: int, max_content_bytes: int):
        self._loader = loader
        self._max_documents = max(1, int(max_documents))
        self._max_content_bytes = max(1, int(max_content_bytes))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)

    def _bounded(self, documents: Iterable[Any]):
        total = 0
        for count, document in enumerate(documents, start=1):
            if count > self._max_documents:
                raise PermissionError("加载结果超过 max_documents")
            content = getattr(document, "page_content", "")
            total += len(str(content).encode("utf-8"))
            metadata = getattr(document, "metadata", {})
            total += len(json.dumps(
                metadata, ensure_ascii=False, default=str
            ).encode("utf-8"))
            if total > self._max_content_bytes:
                raise PermissionError("加载结果超过 max_content_bytes")
            yield document

    def load(self) -> List[Any]:
        return list(self._bounded(self._loader.load()))

    def lazy_load(self):
        method = getattr(self._loader, "lazy_load", None)
        documents = method() if callable(method) else self._loader.load()
        yield from self._bounded(documents)


class DocumentLoaderRegistry:
    """Create loaders behind URL, path, count, and byte safety boundaries."""

    _LOADER_MAP = {
        "text": ("langchain_community.document_loaders", "TextLoader", False),
        "csv": ("langchain_community.document_loaders", "CSVLoader", False),
        "pdf": ("langchain_community.document_loaders", "PyPDFLoader", True),
        "pdf-unstructured": ("langchain_community.document_loaders", "UnstructuredPDFLoader", True),
        "html": ("langchain_community.document_loaders", "UnstructuredHTMLLoader", True),
        "web": ("langchain_community.document_loaders", "WebBaseLoader", True),
        "directory": ("langchain_community.document_loaders", "DirectoryLoader", False),
        "json": ("langchain_community.document_loaders", "JSONLoader", False),
        "markdown": ("langchain_community.document_loaders", "UnstructuredMarkdownLoader", True),
        "word": ("langchain_community.document_loaders", "UnstructuredWordDocumentLoader", True),
    }

    @classmethod
    def _loader_class(cls, loader_type: str):
        spec = cls._LOADER_MAP.get(loader_type)
        if not spec:
            raise ValueError(
                f"未知 loader_type: {loader_type}。支持: {list(cls._LOADER_MAP)}"
            )
        module_name, class_name, optional = spec
        try:
            return getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as exc:
            hint = " 及对应可选依赖" if optional else ""
            raise ImportError(
                f"加载器 {loader_type} 依赖未安装；请安装 langchain-community{hint}"
            ) from exc

    @classmethod
    def create(cls, loader_type: str, source: str, **kwargs) -> Any:
        """Create a bounded loader.

        Security kwargs are consumed by this registry and are not forwarded:
        ``allowed_roots``, ``max_source_bytes``, ``max_content_bytes`` and
        ``max_documents``. The ``web`` loader additionally accepts only
        ``timeout``, ``headers``, ``encoding`` and ``bs_kwargs``.
        """
        if loader_type not in cls._LOADER_MAP:
            raise ValueError(
                f"未知 loader_type: {loader_type}。支持: {list(cls._LOADER_MAP)}"
            )
        allowed_roots = kwargs.pop("allowed_roots", None)
        max_source_bytes = int(kwargs.pop(
            "max_source_bytes", DEFAULT_MAX_SOURCE_BYTES
        ))
        max_documents = int(kwargs.pop("max_documents", DEFAULT_MAX_DOCUMENTS))
        max_content_bytes = int(kwargs.pop(
            "max_content_bytes", DEFAULT_MAX_CONTENT_BYTES
        ))
        if min(max_source_bytes, max_documents, max_content_bytes) <= 0:
            raise ValueError("loader limits must be positive")

        if loader_type == "web":
            _validate_url(source)
            supported = {"timeout", "headers", "encoding", "bs_kwargs"}
            unexpected = set(kwargs) - supported
            if unexpected:
                raise ValueError(
                    "web loader 不支持参数: " + ", ".join(sorted(unexpected))
                )
            loader = _SafeWebLoader(
                source, max_source_bytes=max_source_bytes, **kwargs
            )
        else:
            source = _validate_file_path(
                source,
                allowed_roots=allowed_roots,
                expect_directory=loader_type == "directory",
                max_source_bytes=max_source_bytes,
                max_documents=max_documents,
            )
            loader = cls._loader_class(loader_type)(source, **kwargs)
        return _BoundedLoader(loader, max_documents, max_content_bytes)

    @classmethod
    def load(cls, loader_type: str, source: str, **kwargs) -> List[Any]:
        return cls.create(loader_type, source, **kwargs).load()

    @classmethod
    def load_text(cls, file_path: str, encoding: str = "utf-8", **kwargs) -> List[Any]:
        return cls.load("text", file_path, encoding=encoding, **kwargs)

    @classmethod
    def load_csv(cls, file_path: str, **kwargs) -> List[Any]:
        return cls.load("csv", file_path, **kwargs)

    @classmethod
    def load_pdf(cls, file_path: str, **kwargs) -> List[Any]:
        return cls.load("pdf", file_path, **kwargs)

    @classmethod
    def load_web(cls, url: str, **kwargs) -> List[Any]:
        return cls.load("web", url, **kwargs)

    @classmethod
    def load_directory(
        cls,
        dir_path: str,
        glob: str = "**/[!.]*",
        loader_type: str = "text",
        **kwargs,
    ) -> List[Any]:
        if loader_type in {"web", "directory"}:
            raise ValueError("directory 内部 loader_type 必须是文件加载器")
        security_names = {
            "allowed_roots", "max_source_bytes", "max_documents",
            "max_content_bytes",
        }
        security = {
            name: kwargs.pop(name) for name in list(kwargs) if name in security_names
        }
        loader = cls.create(
            "directory",
            dir_path,
            glob=glob,
            loader_cls=cls._loader_class(loader_type),
            loader_kwargs=kwargs,
            **security,
        )
        return loader.load()

    @classmethod
    def supported_types(cls) -> list:
        return list(cls._LOADER_MAP)
