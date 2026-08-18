"""LangChain annotation example using Spring's configured ChainService."""

from springbootai.langchain import LangChainCall, LangChainClient


@LangChainClient
class WritingAssistant:
    @LangChainCall("Translate {text} to {language}. Return only the translation.")
    def translate(self, text: str, language: str = "Chinese") -> str:
        """Calling this method executes ChainService.run_llm_chain."""
        raise NotImplementedError

    @LangChainCall(mode="summarize", input_name="paragraphs")
    async def summarize(self, paragraphs: list[str]) -> str:
        """Async callers are moved to a worker thread automatically."""
        raise NotImplementedError


# After configure_ai() and configure_langchain():
# assistant = WritingAssistant()
# print(assistant.translate("Spring makes Python services easy."))
