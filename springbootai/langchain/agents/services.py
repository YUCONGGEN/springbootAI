"""
Agent 服务 - 封装 langchain classic 的各类 Agent，作为 @Service Bean。

封装的 Agent 类型（对齐 langchain-master libs/langchain/langchain_classic/agents/）：
- react: ZERO_SHOT_REACT_DESCRIPTION（经典 ReAct）
- chat-zero-shot-react: CHAT_ZERO_SHOT_REACT_DESCRIPTION（对话版 ReAct）
- conversational: CHAT_CONVERSATIONAL_REACT_DESCRIPTION（带记忆的事务型 Agent）
- openai-tools: OPENAI_FUNCTIONS / create_openai_tools_agent（OpenAI 函数调用）
- structured-chat: create_structured_chat_agent（结构化工具调用）
- self-ask-with-search: SELF_ASK_WITH_SEARCH
- xml: XMLAgent（XML 格式 Agent）

All agents receive langchain BaseChatModel (bridged from springbootAI ChatModel).

Deprecation warnings from langchain_classic are centrally suppressed by springbootai.langchain.__init__.
"""
import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger("Spring.LangChain")


# Agent 类型名 -> langchain_classic AgentType 枚举值
# 注意：structured-chat 没有对应的 AgentType 枚举值，需要走 create_structured_chat_agent
_AGENT_TYPE_MAP = {
    "react": "ZERO_SHOT_REACT_DESCRIPTION",
    "chat-zero-shot-react": "CHAT_ZERO_SHOT_REACT_DESCRIPTION",
    "conversational": "CHAT_CONVERSATIONAL_REACT_DESCRIPTION",
    "openai-functions": "OPENAI_FUNCTIONS",
    "self-ask-with-search": "SELF_ASK_WITH_SEARCH",
}

# structured-chat/openai-tools/xml 走专用工厂函数（无 AgentType 枚举值）
_SPECIAL_AGENT_TYPES = {"structured-chat", "openai-tools", "xml"}


class AgentService:
    """
    Agent 服务 Bean - 统一创建与执行 langchain classic Agent。

    构造时注入 lcLangChainModel（langchain BaseChatModel 适配）。
    """

    def __init__(self, lcLangChainModel: Any = None):
        self._lc_model = lcLangChainModel

    @property
    def llm(self):
        return self._lc_model

    # ==================== Agent 创建 ====================

    def create_agent(self, tools: Sequence[Any],
                     agent_type: str = "react",
                     llm: Optional[Any] = None,
                     verbose: bool = False,
                     max_iterations: int = 10,
                     handle_parsing_errors: bool = True,
                     agent_kwargs: Optional[dict] = None) -> Any:
        """
        创建 AgentExecutor（旧版 initialize_agent 风格，最通用）。

        Args:
            tools: langchain BaseTool 列表
            agent_type: react | chat-zero-shot-react | openai-functions |
                        self-ask-with-search | structured-chat | openai-tools
            llm: langchain 模型（默认用注入的）
            max_iterations: 最大推理轮数
            handle_parsing_errors: 解析失败时是否自动恢复

        structured-chat / openai-tools 走专用工厂函数（无 AgentType 枚举），
        其余走 initialize_agent。
        """
        # structured-chat / openai-tools 走专用工厂
        if agent_type == "structured-chat":
            executor = self.create_structured_chat_agent(tools, llm=llm)
            # initialize_agent 的 max_iterations 参数在此设置
            executor.max_iterations = max_iterations
            return executor
        if agent_type == "openai-tools":
            executor = self.create_openai_tools_agent(tools, llm=llm)
            executor.max_iterations = max_iterations
            return executor
        if agent_type == "xml":
            executor = self.create_xml_agent(tools, llm=llm)
            executor.max_iterations = max_iterations
            return executor

        from langchain_classic.agents import initialize_agent, AgentType
        type_name = _AGENT_TYPE_MAP.get(agent_type)
        if type_name is None or not hasattr(AgentType, type_name):
            raise ValueError(
                f"未知 agent_type: {agent_type}。支持: "
                f"{list(_AGENT_TYPE_MAP.keys()) + list(_SPECIAL_AGENT_TYPES)}"
            )
        agent_enum = getattr(AgentType, type_name)
        return initialize_agent(
            tools, llm or self._lc_model, agent=agent_enum,
            verbose=verbose, max_iterations=max_iterations,
            handle_parsing_errors=handle_parsing_errors,
            agent_kwargs=agent_kwargs or {},
        )

    def create_react_agent(self, tools: Sequence[Any],
                           llm: Optional[Any] = None) -> Any:
        """创建 ReAct AgentExecutor（新版 create_react_agent + AgentExecutor）。"""
        from langchain_classic.agents import create_react_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate
        # ReAct 标准 prompt（langchain 1.x 要求 prompt 含 {tool_names} 变量）
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a helpful assistant. Answer using tools when needed.\n"
             "You have access to the following tools:\n{tools}\n"
             "You must format your action as one of [{tool_names}].\n"
             "Use this format:\n"
             "Thought: ...\nAction: tool_name\nAction Input: tool input\n"
             "Observation: tool result\n... (repeat)\nThought: I know the answer\n"
             "Final Answer: your answer"),
            ("user", "{input}\n{agent_scratchpad}"),
        ])
        agent = create_react_agent(llm or self._lc_model, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools,
                             handle_parsing_errors=True)

    def create_openai_tools_agent(self, tools: Sequence[Any],
                                  llm: Optional[Any] = None) -> Any:
        """创建 OpenAI tools AgentExecutor。"""
        from langchain_classic.agents import create_openai_tools_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_openai_tools_agent(llm or self._lc_model, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools,
                             handle_parsing_errors=True)

    def create_structured_chat_agent(self, tools: Sequence[Any],
                                     llm: Optional[Any] = None) -> Any:
        """创建 structured-chat AgentExecutor。

        注意：langchain 1.x 的 create_structured_chat_agent 要求 prompt 含
        {tools} 和 {tool_names} 变量（与 create_react_agent 一致），否则抛
        ValueError: Prompt missing required variables。
        """
        from langchain_classic.agents import create_structured_chat_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Respond to the human as helpfully and accurately as possible.\n"
             "You have access to the following tools:\n{tools}\n"
             "You must format your action as one of [{tool_names}].\n"
             "Use this format:\n"
             "Thought: ...\nAction: tool_name\nAction Input: {{...}}\n"
             "Observation: tool result\n... (repeat)\n"
             "Thought: I know the answer\nFinal Answer: your answer"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_structured_chat_agent(llm or self._lc_model, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools,
                             handle_parsing_errors=True)

    def create_xml_agent(self, tools: Sequence[Any],
                         llm: Optional[Any] = None) -> Any:
        """创建 XML AgentExecutor。

        对齐 langchain-master agents/xml，使用 XML 格式进行工具调用。
        适合需要结构化输入/输出的场景。
        """
        from langchain_classic.agents import create_xml_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a helpful assistant. Use XML format for tool calls.\n"
             "Available tools: {tools}\n"
             "Format:\n"
             "<tool>{tool_name}</tool>\n"
             "<tool_input>{input}</tool_input>"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_xml_agent(llm or self._lc_model, tools, prompt)
        return AgentExecutor(agent=agent, tools=tools,
                             handle_parsing_errors=True)

    # ==================== 便捷执行 ====================

    def run_agent(self, executor_or_tools, user_input: str,
                  agent_type: str = "react",
                  llm: Optional[Any] = None,
                  max_iterations: int = 10) -> str:
        """
        便捷执行 Agent。

        Args:
            executor_or_tools: 已创建的 AgentExecutor，或 tools 列表（自动建 executor）
            user_input: 用户输入
            agent_type: 当传入 tools 时生效
        """
        if hasattr(executor_or_tools, "invoke"):
            executor = executor_or_tools
        else:
            executor = self.create_agent(executor_or_tools, agent_type=agent_type,
                                         llm=llm, max_iterations=max_iterations)
        result = executor.invoke({"input": user_input})
        return result.get("output") if isinstance(result, dict) else str(result)

    @staticmethod
    def supported_agent_types() -> list:
        """返回支持的 agent 类型（含专用工厂类型）。"""
        return list(_AGENT_TYPE_MAP.keys()) + sorted(_SPECIAL_AGENT_TYPES)
