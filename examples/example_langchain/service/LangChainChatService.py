"""
LangChain 聊天服务 - 演示用 ChainService + PromptTemplateFactory 做问答/翻译/总结。

通过构造器 @Autowired 注入 lcChainService（由 configure_langchain 注册到 BeanFactory）。
"""
from springbootai.annotations.core import Autowired, Service, Slf4j
from springbootai.langchain.chains.services import ChainService
from springbootai.langchain.prompts.templates import PromptTemplateFactory


@Slf4j
@Service
class LangChainChatService:
    """聊天/问答服务 - 基于 LLMChain。"""

    @Autowired
    def __init__(self, chain_service: ChainService,
                 prompt_registry: PromptTemplateFactory):
        self.chain_service = chain_service
        self.prompt_registry = prompt_registry

    def ask(self, question: str) -> str:
        """基础问答。"""
        return self.chain_service.run_llm_chain(
            "你是一个有用的助手。请回答用户问题。\n问题：{q}\n回答：", q=question)

    def translate(self, text: str, target_lang: str = "英文") -> str:
        """翻译。"""
        return self.chain_service.run_llm_chain(
            "请把以下文本翻译成{lang}：\n{text}\n翻译：",
            lang=target_lang, text=text)

    def summarize(self, text: str) -> str:
        """总结。"""
        return self.chain_service.run_summarize([text])
