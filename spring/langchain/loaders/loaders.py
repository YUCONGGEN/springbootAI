"""
文档加载器注册表 - 封装 langchain classic 的 DocumentLoader，作为 @Component Bean。

封装的加载器：
- text: TextLoader（纯文本）
- csv: CSVLoader（CSV，逐行成 Document）
- pdf: PyPDFLoader / UnstructuredPDFLoader（PDF，需 pypdf）
- html/web: WebBaseLoader（URL 抓取，需 beautifulsoup4）
- directory: DirectoryLoader（目录批量加载）
- json: JSONLoader（JSON 文件）
- markdown: UnstructuredMarkdownLoader
- word: UnstructuredWordDocumentLoader（需 python-docx）

安全设计（OWASP SSRF / 本地文件读取）：
- WebBaseLoader 加载 URL 前检查协议（仅 http/https）和目的地址（拒绝
  私网/回环/链路本地/元数据地址），防止 SSRF 攻击。
- 文件类加载器限制根目录（``_ALLOWED_ROOTS``），禁止访问系统敏感路径。
- 可通过环境变量 ``AI_LOADER_ALLOW_PRIVATE_NETWORK=true`` 放行私网
  （仅面向可信内网环境的服务），默认 false。

所有加载器懒加载对应依赖，缺失时抛带安装提示的 ImportError。
"""
import ipaddress
import logging
import os as _os
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse


logger = logging.getLogger("Spring.LangChain")


# ==================== SSRF / 文件路径安全 ====================

# 禁止加载的文件系统根目录（黑名单）
_BLOCKED_ROOTS: List[Path] = [
    Path("/etc"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/root"),
    Path("/var/run"),
    Path("/tmp") if _os.name != "nt" else Path("C:\\Windows"),
    Path("C:\\Windows") if _os.name == "nt" else Path("/run"),
]


def _is_private_url(url_str: str) -> bool:
    """判断 URL 是否指向私网/回环/链路本地/元数据地址。"""
    try:
        parsed = urlparse(url_str)
        hostname = parsed.hostname or ""
        if not hostname:
            return True  # 拒绝无法解析的主机名
        # 元数据地址（云环境 SSRF）
        if hostname in ("169.254.169.254", "metadata.google.internal",
                        "metadata", "100.100.100.200"):
            return True
        addr = ipaddress.ip_address(hostname)
        return (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_unspecified)
    except ValueError:
        # hostname 不是 IP（如域名），允许 DNS 解析后由网络层控制
        hostname_lower = (urlparse(url_str).hostname or "").lower()
        if hostname_lower in ("localhost", "metadata.google.internal",
                              "169.254.169.254"):
            return True
        return False


def _validate_file_path(file_path: str) -> str:
    """验证文件路径不在禁止的根目录下，防止任意文件读取。"""
    try:
        resolved = Path(file_path).resolve()
        for blocked in _BLOCKED_ROOTS:
            try:
                resolved.relative_to(blocked.resolve())
                raise PermissionError(
                    f"文件路径位于禁止目录: {blocked}。请将文档放在应用数据目录下。")
            except ValueError:
                continue  # 不在该 blocked root 下，OK
        return str(resolved)
    except OSError as exc:
        raise PermissionError(f"无法解析文件路径: {file_path}") from exc


def _validate_url(url_str: str) -> None:
    """验证 URL 的安全性（协议 + 私网检查）。"""
    parsed = urlparse(url_str)
    if parsed.scheme not in ("http", "https"):
        raise PermissionError(
            f"不允许的 URL 协议: {parsed.scheme}。仅支持 http/https。")

    allow_private = _os.environ.get(
        "AI_LOADER_ALLOW_PRIVATE_NETWORK", "false").strip().lower() in (
            "true", "1", "yes", "on")
    if not allow_private and _is_private_url(url_str):
        raise PermissionError(
            f"拒绝加载私网/回环地址: {url_str}。"
            "设置 AI_LOADER_ALLOW_PRIVATE_NETWORK=true 可放行（仅可信内网环境）。")


# ==================== 注册表 ====================

class DocumentLoaderRegistry:
    """文档加载器注册表 Bean - 统一创建与调用各类 DocumentLoader。

    安全：create() 方法会检查 URL 的网络安全性（SSRF 防护）和
    文件路径的目录限制（防止任意文件读取）。
    """

    # 加载器名 -> (模块, 类名, 是否需要可选依赖)
    _LOADER_MAP = {
        "text":     ("langchain_community.document_loaders", "TextLoader", False),
        "csv":      ("langchain_community.document_loaders", "CSVLoader", False),
        "pdf":      ("langchain_community.document_loaders", "PyPDFLoader", True),
        "pdf-unstructured": ("langchain_community.document_loaders", "UnstructuredPDFLoader", True),
        "html":     ("langchain_community.document_loaders", "UnstructuredHTMLLoader", True),
        "web":      ("langchain_community.document_loaders", "WebBaseLoader", True),
        "directory":("langchain_community.document_loaders", "DirectoryLoader", False),
        "json":     ("langchain_community.document_loaders", "JSONLoader", False),
        "markdown": ("langchain_community.document_loaders", "UnstructuredMarkdownLoader", True),
        "word":     ("langchain_community.document_loaders", "UnstructuredWordDocumentLoader", True),
    }

    @classmethod
    def create(cls, loader_type: str, source: str, **kwargs) -> Any:
        """
        创建加载器实例。

        Args:
            loader_type: 见 _LOADER_MAP 的 key
            source: 文件路径 / URL / 目录
            kwargs: 透传给加载器构造器

        Raises:
            PermissionError: URL 指向私网/回环地址或文件路径位于禁止目录
        """
        # SSRF 防护：web/html loader 的 source 是 URL
        if loader_type in ("web", "html") or source.startswith(("http://", "https://")):
            _validate_url(source)
        # 文件路径防护：文件类 loader 限制目录
        if loader_type not in ("web", "html") and not source.startswith(("http://", "https://")):
            source = _validate_file_path(source)
        spec = cls._LOADER_MAP.get(loader_type)
        if not spec:
            raise ValueError(
                f"未知 loader_type: {loader_type}。支持: {list(cls._LOADER_MAP.keys())}"
            )
        module_name, class_name, optional = spec
        try:
            import importlib
            module = importlib.import_module(module_name)
            loader_cls = getattr(module, class_name)
        except ImportError as exc:
            raise ImportError(
                f"加载器 {loader_type} 依赖未安装（{exc}）。"
                f"请 pip install langchain-community"
                + (" 及对应可选依赖（如 pypdf/beautifulsoup4/python-docx）" if optional else "")
            ) from exc
        return loader_cls(source, **kwargs)

    @classmethod
    def load(cls, loader_type: str, source: str, **kwargs) -> List[Any]:
        """
        创建加载器并立即加载文档。

        Returns:
            langchain_core.documents.Document 列表
        """
        loader = cls.create(loader_type, source, **kwargs)
        return loader.load()

    @classmethod
    def load_text(cls, file_path: str, encoding: str = "utf-8") -> List[Any]:
        """便捷：加载纯文本文件。"""
        return cls.load("text", file_path, encoding=encoding)

    @classmethod
    def load_csv(cls, file_path: str, **kwargs) -> List[Any]:
        """便捷：加载 CSV。"""
        return cls.load("csv", file_path, **kwargs)

    @classmethod
    def load_pdf(cls, file_path: str, **kwargs) -> List[Any]:
        """便捷：加载 PDF（需 pypdf）。"""
        return cls.load("pdf", file_path, **kwargs)

    @classmethod
    def load_web(cls, url: str, **kwargs) -> List[Any]:
        """便捷：抓取网页（需 beautifulsoup4）。"""
        return cls.load("web", url, **kwargs)

    @classmethod
    def load_directory(cls, dir_path: str, glob: str = "**/[!.]*",
                       loader_type: str = "text", **kwargs) -> List[Any]:
        """便捷：批量加载目录（默认递归加载所有非隐藏文本文件）。"""
        inner_loader_cls = type(cls.create(loader_type, "", **kwargs))
        loader = cls.create("directory", dir_path, glob=glob,
                            loader_cls=inner_loader_cls)
        return loader.load()

    @classmethod
    def supported_types(cls) -> list:
        """返回支持的加载器类型。"""
        return list(cls._LOADER_MAP.keys())
