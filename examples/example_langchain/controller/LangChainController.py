"""
LangChain REST 控制器 - 暴露 /api/lc/* 接口演示迁移后的全部能力。

端点：
- POST /api/lc/chat          基础问答
- POST /api/lc/translate     翻译
- POST /api/lc/summarize     总结
- POST /api/lc/agent         Agent 执行
- POST /api/lc/rag/add       RAG 文档入库
- POST /api/lc/rag/query     RAG 检索问答
- POST /api/lc/memory        带记忆的对话
- POST /api/lc/math          数学计算
- POST /api/lc/parse-list    列表解析
- GET  /api/lc/providers     列出已启用 partner
- GET  /api/lc/capabilities  列出模块全部能力
- POST /api/lc/embed         文本嵌入
"""
from spring.annotations.core import (
    Autowired, GetMapping, PostMapping, RequestMapping,
    RestController, Slf4j,
)
from spring.annotations.security import Authenticate
from spring.web.result import Result
from example_langchain.service.LangChainChatService import LangChainChatService
from example_langchain.service.LangChainAgentService import LangChainAgentService
from example_langchain.service.LangChainRagService import LangChainRagService
from example_langchain.service.LangChainChainService import LangChainChainService


@RestController
@RequestMapping("/api/lc")
@Authenticate(roles=["USER", "ADMIN"])
@Slf4j
class LangChainController:
    """LangChain 模块能力暴露控制器。

    安全：所有端点默认要求认证（@Authenticate），防止未授权调用导致
    模型费用滥用、嵌入接口刷量、RAG 投毒和服务拒绝。
    """

    @Autowired
    def __init__(self, chat_service: LangChainChatService,
                 agent_service: LangChainAgentService,
                 rag_service: LangChainRagService,
                 chain_service: LangChainChainService):
        self.chat_service = chat_service
        self.agent_service = agent_service
        self.rag_service = rag_service
        self.chain_service = chain_service

    # ==================== 聊天 / 问答 ====================

    @PostMapping("/chat")
    def chat(self, body: dict):
        """基础问答。body: {"question": "..."}"""
        question = body.get("question", "")
        if not question:
            return Result.bad_request(message="question 不能为空")
        answer = self.chat_service.ask(question)
        return Result.success(data={"question": question, "answer": answer})

    @PostMapping("/translate")
    def translate(self, body: dict):
        """翻译。body: {"text": "...", "target_lang": "英文"}"""
        text = body.get("text", "")
        target = body.get("target_lang", "英文")
        result = self.chat_service.translate(text, target)
        return Result.success(data={"text": text, "target": target,
                                    "translation": result})

    @PostMapping("/summarize")
    def summarize(self, body: dict):
        """总结。body: {"text": "..."}"""
        text = body.get("text", "")
        if not text:
            return Result.bad_request(message="text 不能为空")
        summary = self.chat_service.summarize(text)
        return Result.success(data={"summary": summary})

    # ==================== Agent ====================

    @PostMapping("/agent")
    def agent(self, body: dict):
        """Agent 执行。body: {"question": "...", "agent_type": "react"}"""
        question = body.get("question", "")
        agent_type = body.get("agent_type", "react")
        try:
            output = self.agent_service.run(question, agent_type=agent_type)
            return Result.success(data={"question": question, "output": output})
        except Exception as exc:
            self.logger.error("Agent 执行失败: %s", exc)
            return Result.internal_error(message=f"Agent 执行失败: {exc}")

    # ==================== RAG ====================

    @PostMapping("/rag/add")
    def rag_add(self, body: dict):
        """RAG 文档入库。body: {"docs": ["文本1", "文本2"]}"""
        docs = body.get("docs", [])
        if not docs:
            return Result.bad_request(message="docs 不能为空")
        result = self.rag_service.add_documents(docs)
        return Result.success(data=result)

    @PostMapping("/rag/query")
    def rag_query(self, body: dict):
        """RAG 检索问答。body: {"question": "...", "k": 3}"""
        question = body.get("question", "")
        k = body.get("k", 3)
        if not question:
            return Result.bad_request(message="question 不能为空")
        result = self.rag_service.query(question, k=k)
        return Result.success(data=result)

    # ==================== Chain / Memory / Parser ====================

    @PostMapping("/memory")
    def memory_chat(self, body: dict):
        """带记忆的对话。body: {"input": "..."}"""
        user_input = body.get("input", "")
        response = self.chain_service.chat_with_memory(user_input)
        return Result.success(data={"input": user_input, "response": response})

    @PostMapping("/math")
    def math(self, body: dict):
        """数学计算。body: {"expression": "2+3*4"}"""
        expression = body.get("expression", "")
        result = self.chain_service.math(expression)
        return Result.success(data={"expression": expression, "result": result})

    @PostMapping("/parse-list")
    def parse_list(self, body: dict):
        """列表解析。body: {"text": "a, b, c"}"""
        text = body.get("text", "")
        items = self.chain_service.parse_list(text)
        return Result.success(data={"items": items})

    # ==================== 元信息 ====================

    @GetMapping("/providers")
    def providers(self):
        """列出当前环境已安装的 partner 提供商。"""
        from spring.langchain.partners import list_partners, list_available_partners
        return Result.success(data={
            "total": len(list_partners()),
            "available": list_available_partners(),
            "all": list_partners(),
        })

    @GetMapping("/capabilities")
    def capabilities(self):
        """列出模块全部能力。"""
        from spring.langchain.memory.memory import MemoryFactory
        from spring.langchain.loaders.loaders import DocumentLoaderRegistry
        from spring.langchain.retrievers.retrievers import RetrieverFactory
        from spring.langchain.vectorstores.stores import VectorStoreFactory
        from spring.langchain.agents.services import AgentService
        from spring.langchain.utilities.utils import UtilityRegistry
        return Result.success(data={
            "memory": MemoryFactory.supported_types(),
            "loaders": DocumentLoaderRegistry.supported_types(),
            "retrievers": RetrieverFactory.supported_types(),
            "vectorstores": VectorStoreFactory.supported_types(),
            "agents": AgentService.supported_agent_types(),
            "utilities": UtilityRegistry.supported_types(),
        })

    @PostMapping("/embed")
    def embed(self, body: dict):
        """文本嵌入。body: {"texts": ["a", "b"]}"""
        from spring.context.registry import BeanRegistry
        texts = body.get("texts", [])
        emb_model = BeanRegistry().get("aiEmbeddingModel")
        if emb_model is None:
            return Result.bad_request(message="嵌入模型未装配")
        vectors = emb_model.embed(texts)
        return Result.success(data={
            "count": len(vectors),
            "dim": len(vectors[0]) if vectors else 0,
            "vectors": vectors,
        })
