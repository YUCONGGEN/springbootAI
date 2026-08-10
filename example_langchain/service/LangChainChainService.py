"""
LangChain Chain 服务 - 演示 SequentialChain / LLMMathChain / 会话记忆。
"""
from spring.annotations.core import Autowired, Service, Slf4j
from spring.langchain.chains.services import ChainService
from spring.langchain.memory.memory import MemoryFactory
from spring.langchain.parsers.parsers import OutputParserFactory


@Slf4j
@Service
class LangChainChainService:
    """多种 Chain 用法演示。"""

    @Autowired
    def __init__(self, chain_service: ChainService,
                 memory_factory: MemoryFactory,
                 parser_registry: OutputParserFactory):
        self.chain_service = chain_service
        self.memory_factory = memory_factory
        self.parser_registry = parser_registry

    def chat_with_memory(self, user_input: str) -> str:
        """带会话记忆的对话（buffer memory）。"""
        memory = self.memory_factory.create("buffer")
        return self.chain_service.run_conversation(user_input, memory=memory)

    def math(self, expression: str) -> str:
        """数学计算链。"""
        try:
            chain = self.chain_service.create_llm_math_chain()
            result = chain.invoke({"question": expression})
            if isinstance(result, dict):
                return result.get("answer") or str(result)
            return str(result)
        except Exception as exc:
            # FakeChatModel 无法真正算数学，降级本地安全求值
            # 不使用 eval()（存在沙箱逃逸风险），改用 AST 安全求值器
            self.logger.warning("LLMMathChain 失败，降级本地计算: %s", exc)
            from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
            try:
                return str(safe_eval_arithmetic(expression))
            except Exception:
                return f"无法计算: {expression}"

    def parse_list(self, text: str) -> list:
        """用逗号列表解析器解析输出。"""
        parser = self.parser_registry.create_comma_list_parser()
        try:
            return parser.parse(text)
        except Exception:
            return [t.strip() for t in text.split(",") if t.strip()]
