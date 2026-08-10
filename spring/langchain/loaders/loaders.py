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

所有加载器懒加载对应依赖，缺失时抛带安装提示的 ImportError。
"""
import logging
from typing import Any, List, Optional

from spring.annotations.core import Component

logger = logging.getLogger("Spring.LangChain")


@Component
class DocumentLoaderRegistry:
    """文档加载器注册表 Bean - 统一创建与调用各类 DocumentLoader。"""

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
        """
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
