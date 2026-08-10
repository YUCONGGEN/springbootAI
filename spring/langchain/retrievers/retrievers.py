"""
检索器工厂 - 封装 langchain classic 的 Retriever，作为 @Component Bean。

封装的检索器：
- similarity: 基础相似度（vector_store.as_retriever）
- multi-query: MultiQueryRetriever（用 LLM 生成多个查询变体提升召回）
- contextual-compression: ContextualCompressionRetriever（用 LLM 压缩检索结果）
- self-query: SelfQueryRetriever（结构化元数据过滤）
- time-weighted: TimeWeightedVectorRetriever（时间衰减）
- ensemble: EnsembleRetriever（多检索器融合）
"""
import logging
from typing import Any, List, Optional

from spring.annotations.core import Component

logger = logging.getLogger("Spring.LangChain")


@Component
class RetrieverFactory:
    """检索器工厂 Bean - 统一创建各类 Retriever。"""

    @staticmethod
    def create(retriever_type: str = "similarity",
               vector_store: Any = None,
               llm: Optional[Any] = None,
               k: int = 4,
               **kwargs) -> Any:
        """
        创建检索器。

        Args:
            retriever_type: similarity | multi-query | contextual-compression | self-query | time-weighted | ensemble
            vector_store: langchain VectorStore
            llm: langchain 模型（multi-query/contextual-compression/self-query 必填）
            k: 返回文档数
        """
        if retriever_type == "similarity":
            return vector_store.as_retriever(
                search_type="similarity", search_kwargs={"k": k})

        if retriever_type == "multi-query":
            from langchain_classic.retrievers import MultiQueryRetriever
            if llm is None:
                raise ValueError("multi-query 检索器需要 llm 参数")
            retriever = MultiQueryRetriever.from_llm(
                retriever=vector_store.as_retriever(search_kwargs={"k": k}),
                llm=llm)
            return retriever

        if retriever_type == "contextual-compression":
            from langchain_classic.retrievers import ContextualCompressionRetriever
            from langchain_classic.retrievers.document_compressors import LLMChainExtractor
            if llm is None:
                raise ValueError("contextual-compression 检索器需要 llm 参数")
            compressor = LLMChainExtractor.from_llm(llm)
            return ContextualCompressionRetriever(
                base_compressor=compressor,
                base_retriever=vector_store.as_retriever(search_kwargs={"k": k}))

        if retriever_type == "self-query":
            from langchain_classic.retrievers import SelfQueryRetriever
            if llm is None:
                raise ValueError("self-query 检索器需要 llm 参数")
            # 需要 metadata_field_info 与 document_contents，由调用方在 kwargs 提供
            return SelfQueryRetriever.from_llm(
                llm, vector_store,
                document_content_key=kwargs.get("document_content_key", "page_content"),
                metadata_field_info=kwargs.get("metadata_field_info", []),
                enable_limit=True)

        if retriever_type == "time-weighted":
            from langchain_classic.retrievers import TimeWeightedVectorRetriever
            return TimeWeightedVectorRetriever(
                vectorstore=vector_store,
                decay_rate=kwargs.get("decay_rate", 0.01),
                k=k)

        if retriever_type == "ensemble":
            from langchain_classic.retrievers import EnsembleRetriever
            retrievers = kwargs.get("retrievers", [])
            if not retrievers:
                raise ValueError("ensemble 检索器需要 retrievers 参数")
            weights = kwargs.get("weights")
            return EnsembleRetriever(retrievers=retrievers, weights=weights)

        raise ValueError(
            f"未知 retriever_type: {retriever_type}。支持: "
            "similarity|multi-query|contextual-compression|self-query|time-weighted|ensemble"
        )

    @staticmethod
    def supported_types() -> list:
        """返回支持的检索器类型。"""
        return ["similarity", "multi-query", "contextual-compression",
                "self-query", "time-weighted", "ensemble"]
