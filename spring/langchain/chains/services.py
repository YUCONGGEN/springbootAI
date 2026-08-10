"""
Chain 服务 - 封装 langchain classic 的各类 Chain，作为 @Service Bean。

封装的 Chain 类型：
- llm: LLMChain（基础：prompt + llm）
- conversation: ConversationChain（带会话记忆的对话）
- sequential: SequentialChain（多链顺序串联）
- retrieval-qa: RetrievalQA（基于检索的问答）
- map-reduce: MapReduceChain（长文本摘要）
- llm-math: LLMMathChain（数学计算）
- stuff-documents: StuffDocumentsChain（文档拼接）

所有方法接收 langchain BaseChatModel（由 adapters 桥接自 springbootAI ChatModel）。
"""
import logging
import warnings
from typing import Any, List, Optional


# 屏蔽 langchain classic 的弃用告警（迁移目的即兼容旧 API，告警无意义）
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")
try:
    from langchain_core._api import LangChainDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

logger = logging.getLogger("Spring.LangChain")


class ChainService:
    """
    Chain 服务 Bean - 统一创建与执行 langchain classic Chain。

    构造时注入 lcLangChainModel（springbootAI ChatModel 桥接出的 langchain 模型），
    业务侧调用各 create_xxx 方法获取 Chain 实例，再调 invoke 执行。
    """

    def __init__(self, lcLangChainModel: Any = None):
        # lcLangChainModel 由 configure_langchain 注册（langchain BaseChatModel 适配）
        self._lc_model = lcLangChainModel

    @property
    def llm(self):
        """当前注入的 langchain 模型。"""
        return self._lc_model

    # ==================== 基础 Chain ====================

    def create_llm_chain(self, prompt: Any = None, llm: Optional[Any] = None,
                         output_key: str = "text", verbose: bool = False,
                         template: Optional[str] = None,
                         input_variables: Optional[List[str]] = None) -> Any:
        """创建 LLMChain。

        Args:
            prompt: PromptTemplate / ChatPromptTemplate 实例；为字符串时自动转为
                    PromptTemplate（与 run_llm_chain 行为一致，便于业务侧一行调用）
            llm: 可选的自定义模型（默认用构造时注入的 lcLangChainModel）
            output_key: 输出键名（默认 "text"）
            verbose: 是否打印链执行过程
            template: 便捷别名 - 等价于传字符串 prompt（template="Q:{q}" 同 prompt="Q:{q}"）
            input_variables: 模板变量列表（仅 template 字符串场景生效）
        """
        from langchain_classic.chains import LLMChain
        # template 别名优先（与 prompt 互斥；二者都传时以 template 为准）
        if template is not None:
            prompt = template
        # 字符串模板自动包装为 PromptTemplate（langchain 1.x 的 LLMChain 已不再接受裸字符串）
        if isinstance(prompt, str):
            from spring.langchain.prompts.templates import PromptTemplateFactory
            prompt = PromptTemplateFactory.create_prompt_template(
                prompt, input_variables=input_variables)
        if prompt is None:
            raise ValueError("create_llm_chain 需要 prompt 或 template 参数")
        return LLMChain(llm=llm or self._lc_model, prompt=prompt,
                        output_key=output_key, verbose=verbose)

    def create_conversation_chain(self, memory: Optional[Any] = None,
                                  llm: Optional[Any] = None,
                                  verbose: bool = False) -> Any:
        """创建带记忆的 ConversationChain。"""
        from langchain_classic.chains import ConversationChain
        return ConversationChain(llm=llm or self._lc_model, memory=memory,
                                 verbose=verbose)

    def create_sequential_chain(self, chains: List[Any],
                                input_variables: List[str],
                                output_variables: List[str],
                                verbose: bool = False) -> Any:
        """创建 SequentialChain - 串联多个 Chain。"""
        from langchain_classic.chains import SequentialChain
        return SequentialChain(chains=chains, input_variables=input_variables,
                               output_variables=output_variables, verbose=verbose)

    # ==================== RAG / 文档 Chain ====================

    def create_retrieval_qa(self, retriever: Any,
                            chain_type: str = "stuff",
                            llm: Optional[Any] = None,
                            verbose: bool = False) -> Any:
        """
        创建 RetrievalQA - 基于检索器的问答链。

        Args:
            retriever: langchain Retriever（来自 RetrieverFactory）
            chain_type: stuff | map_reduce | refine | map_rerank
        """
        from langchain_classic.chains import RetrievalQA
        return RetrievalQA.from_chain_type(
            llm=llm or self._lc_model, retriever=retriever,
            chain_type=chain_type, verbose=verbose)

    def create_map_reduce_chain(self, llm: Optional[Any] = None) -> Any:
        """创建 MapReduce 文档链（长文本摘要）。"""
        from langchain_classic.chains.summarize import load_summarize_chain
        return load_summarize_chain(llm or self._lc_model,
                                    chain_type="map_reduce")

    def create_summarize_chain(self, llm: Optional[Any] = None,
                               chain_type: str = "stuff") -> Any:
        """加载摘要链（stuff / map_reduce / refine）。"""
        from langchain_classic.chains.summarize import load_summarize_chain
        return load_summarize_chain(llm or self._lc_model, chain_type=chain_type)

    # ==================== 工具型 Chain ====================

    def create_llm_math_chain(self, llm: Optional[Any] = None,
                              verbose: bool = False) -> Any:
        """创建 LLMMathChain - 让 LLM 做数学计算。"""
        from langchain_classic.chains import LLMMathChain
        return LLMMathChain(llm=llm or self._lc_model, verbose=verbose)

    # ==================== 便捷执行 ====================

    def run_llm_chain(self, prompt_template: str, **inputs) -> str:
        """便捷：从模板字符串创建 LLMChain 并执行，返回文本。"""
        from spring.langchain.prompts.templates import PromptTemplateFactory
        prompt = PromptTemplateFactory.from_template(prompt_template)
        chain = self.create_llm_chain(prompt)
        result = chain.invoke(inputs)
        return result.get("text") if isinstance(result, dict) else str(result)

    def run_conversation(self, user_input: str, memory: Optional[Any] = None) -> str:
        """便捷：执行一次对话链调用（未传 memory 时自动创建 buffer 记忆）。

        ⚠️ 多轮对话：每次调用不传 memory 时会创建新的 buffer，**不会累积历史**。
        要实现多轮记忆，调用方必须自己持有 memory 实例并重复传入：

            mem = MemoryFactory.create("buffer")
            svc.run_conversation("我叫张三", memory=mem)
            svc.run_conversation("我叫什么", memory=mem)  # 复用同一 mem
        """
        if memory is None:
            from spring.langchain.memory.memory import MemoryFactory
            memory = MemoryFactory.create("buffer")
        chain = self.create_conversation_chain(memory=memory)
        result = chain.invoke({"input": user_input})
        return result.get("response") if isinstance(result, dict) else str(result)

    def run_summarize(self, texts: List[str], llm: Optional[Any] = None) -> str:
        """便捷：对文本列表做摘要。"""
        from langchain_core.documents import Document
        chain = self.create_summarize_chain(llm=llm)
        docs = [Document(page_content=t) for t in texts]
        result = chain.invoke(docs)
        if isinstance(result, dict):
            return result.get("output_text") or result.get("summary_text") or ""
        return str(result)
