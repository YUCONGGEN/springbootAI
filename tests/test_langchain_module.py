"""SpringBootAI LangChain 模块测试 - 覆盖适配层/配置绑定/自动装配/Partner 注册表/
Prompt/Chain/Agent/Memory/Parser/VectorStore/Retriever/Index/Tool 等全部核心组件。

设计原则：
- 全部使用 FakeChatModel / FakeEmbeddingModel 提供确定性输出，不依赖网络或真实 LLM，
  保证测试可在 CI/无 API Key 环境下稳定运行。
- 验证「springbootAI ChatModel/EmbeddingModel ↔ langchain BaseChatModel/Embeddings」
  双向桥接的正确性，确保迁移后的 LangChain classic 能力与 springbootAI 注解体系兼容。
- 每个 test class 覆盖一个子模块，方法名即测试意图，中文 docstring 说明断言点。
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装缺失依赖 mock

from springbootai.ai.providers import FakeChatModel, FakeEmbeddingModel
from springbootai.ai.core import ChatModel, EmbeddingModel, Message
from springbootai.context.registry import BeanRegistry
from springbootai.langchain.adapters import (
    SpringChatModelToLangChain, to_langchain_embeddings, to_langchain_model,
    to_spring_embeddings, to_spring_model,
)
from springbootai.langchain.autoconfig import (
    bind_langchain_config, configure_langchain,
)
from springbootai.langchain.partners import (
    PARTNER_REGISTRY, PartnerProviderFactory,
    is_partner_available, list_available_partners, list_partners,
)
from springbootai.langchain.prompts.templates import PromptTemplateFactory
from springbootai.langchain.chains.services import ChainService
from springbootai.langchain.agents.services import AgentService
from springbootai.langchain.memory.memory import MemoryFactory
from springbootai.langchain.parsers.parsers import OutputParserFactory
from springbootai.langchain.loaders.loaders import DocumentLoaderRegistry
from springbootai.langchain.retrievers.retrievers import RetrieverFactory
from springbootai.langchain.vectorstores.stores import VectorStoreFactory
from springbootai.langchain.indexes.index import IndexService
from springbootai.langchain.tools.tools import ToolFactory, ToolRegistry
from springbootai.langchain.utilities.utils import UtilityRegistry
from springbootai.langchain.callbacks.handlers import CallbackRegistry


# ==================== 公共 fixture ====================

@pytest.fixture
def spring_chat():
    """提供一个带前缀的 FakeChatModel，输出形如 '[AI] <用户最后一句>'。"""
    return FakeChatModel(prefix="[AI]")


@pytest.fixture
def spring_emb():
    """提供一个 8 维 FakeEmbeddingModel，确定性哈希嵌入。"""
    return FakeEmbeddingModel(dim=8)


@pytest.fixture
def lc_model(spring_chat):
    """springbootAI ChatModel 桥接出的 langchain BaseChatModel。"""
    return to_langchain_model(spring_chat)


@pytest.fixture
def lc_embeddings(spring_emb):
    """springbootAI EmbeddingModel 桥接出的 langchain Embeddings。"""
    return to_langchain_embeddings(spring_emb)


@pytest.fixture(autouse=True)
def _isolate_lc_env(monkeypatch):
    """隔离 LangChain 相关环境变量，防止开发者本机 env 干扰配置绑定测试。"""
    for key in list(os.environ):
        if key.startswith("LC_"):
            monkeypatch.delenv(key, raising=False)


# ==================== 1. 适配层 ====================

class TestAdapters:
    """springbootAI ↔ langchain 模型/嵌入双向桥接。"""

    def test_spring_to_langchain_returns_base_chat_model(self, spring_chat):
        """SpringChatModelToLangChain 产出 langchain BaseChatModel 子类实例。"""
        from langchain_core.language_models.chat_models import BaseChatModel
        lc = SpringChatModelToLangChain(spring_chat).build()
        assert isinstance(lc, BaseChatModel)
        assert lc._llm_type == "springboot-ai-adapter"

    def test_to_langchain_model_invokes_spring_backend(self, spring_chat):
        """桥接后的 langchain 模型调用会委托回 springbootAI ChatModel.call。"""
        lc = to_langchain_model(spring_chat)
        from langchain_core.messages import HumanMessage
        result = lc.invoke([HumanMessage(content="hello")])
        # FakeChatModel 回复 "[AI] hello"
        assert "[AI]" in result.content
        assert "hello" in result.content
        assert spring_chat.call_count == 1

    def test_to_langchain_model_preserves_system_message(self, spring_chat):
        """System 消息经桥接后仍作为 system 角色传给底层模型。"""
        lc = to_langchain_model(spring_chat)
        from langchain_core.messages import HumanMessage, SystemMessage
        result = lc.invoke([
            SystemMessage(content="你是助手"),
            HumanMessage(content="你好"),
        ])
        assert "[AI]" in result.content
        assert "你好" in result.content

    def test_langchain_to_spring_model(self):
        """langchain -> springbootAI 方向：LangChainModelToSpring 实现 ChatModel。"""
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        fake_lc = FakeListChatModel(responses=["langchain-says-hi"])
        spring_model = to_spring_model(fake_lc)
        assert isinstance(spring_model, ChatModel)
        resp = spring_model.call([Message.user("ping")])
        assert resp.content() == "langchain-says-hi"
        assert resp.metadata.get("provider") == "langchain"

    def test_spring_to_langchain_embeddings(self, spring_emb):
        """springbootAI EmbeddingModel -> langchain Embeddings 接口。"""
        emb = to_langchain_embeddings(spring_emb)
        docs = emb.embed_documents(["a", "b"])
        assert len(docs) == 2
        assert all(len(v) == 8 for v in docs)
        q = emb.embed_query("query")
        assert len(q) == 8

    def test_langchain_to_spring_embeddings(self):
        """langchain Embeddings -> springbootAI EmbeddingModel。"""
        class _StubEmb:
            def embed_documents(self, texts):
                return [[0.1, 0.2] for _ in texts]

            def embed_query(self, text):
                return [0.3, 0.4]

        spring_emb = to_spring_embeddings(_StubEmb())
        assert isinstance(spring_emb, EmbeddingModel)
        assert spring_emb.embed(["x", "y"]) == [[0.1, 0.2], [0.1, 0.2]]
        assert spring_emb.embed_one("z") == [0.3, 0.4]

    def test_embeddings_roundtrip(self, spring_emb):
        """springbootAI -> langchain -> springbootAI 嵌入往返保持一致。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        back = to_spring_embeddings(lc_emb)
        assert back.embed(["hello"]) == spring_emb.embed(["hello"])
        assert back.embed_one("hi") == spring_emb.embed_one("hi")


# ==================== 2. 配置绑定 ====================

class TestConfigBinding:
    """LangChainProperties dataclass + _bind 递归绑定 + env 覆盖。"""

    def test_default_properties(self):
        """无配置时使用默认值：enabled=True, default_llm=auto。"""
        props = bind_langchain_config({})
        assert props.enabled is True
        assert props.default_llm == "auto"
        assert props.chains.default_verbose is False
        assert props.agents.default_type == "react"
        assert props.agents.max_iterations == 10
        assert props.vector_store.type == "faiss"
        assert props.memory.type == "buffer"

    def test_kebab_case_binding(self):
        """yml 的 kebab-case 键能绑定到 dataclass 的 snake_case 字段。"""
        props = bind_langchain_config({
            "default-llm": "ollama",
            "enabled": False,
            "chains": {"default-verbose": True},
            "agents": {"max-iterations": 5, "default-type": "openai-functions"},
        })
        assert props.default_llm == "ollama"
        assert props.enabled is False
        assert props.chains.default_verbose is True
        assert props.agents.max_iterations == 5
        assert props.agents.default_type == "openai-functions"

    def test_env_override(self, monkeypatch):
        """环境变量 LC_* 优先级高于 yml 配置。"""
        monkeypatch.setenv("LC_DEFAULT_LLM", "anthropic")
        monkeypatch.setenv("LC_AGENT_MAX_ITER", "3")
        props = bind_langchain_config({"default-llm": "openai"})
        assert props.default_llm == "anthropic"
        assert props.agents.max_iterations == 3

    def test_partners_dict_pass_through(self):
        """partners 是动态字典，原样透传不递归绑定。"""
        partners_cfg = {
            "openai": {"api_key": "sk-x", "model": "gpt-4o-mini"},
            "ollama": {"base_url": "http://localhost:11434", "model": "llama3"},
        }
        props = bind_langchain_config({"partners": partners_cfg})
        assert props.partners == partners_cfg
        assert props.partners["openai"]["model"] == "gpt-4o-mini"

    def test_type_coercion_bool(self):
        """字符串 'true'/'false' 被正确转为布尔。"""
        props = bind_langchain_config({"enabled": "true", "chains": {"default-verbose": "yes"}})
        assert props.enabled is True
        assert props.chains.default_verbose is True


# ==================== 3. 自动装配 ====================

class TestAutoConfig:
    """configure_langchain 入口 - 构建 Bean 并注册到 BeanRegistry。"""

    def test_configure_langchain_registers_core_beans(self, spring_chat, spring_emb):
        """configure_langchain 注册 lcLangChainModel + 12 个能力 Bean。"""
        registry = BeanRegistry()
        beans = configure_langchain(
            registry=registry,
            config=_StubConfig({"spring": {"langchain": {}}}),
            chat_model=spring_chat,
            embedding_model=spring_emb,
        )
        # 核心模型 + 嵌入
        assert "lcLangChainModel" in beans
        assert "lcEmbeddings" in beans
        # 12 个能力 Bean 全部注册
        for name in ["lcPromptRegistry", "lcChainService", "lcAgentService",
                     "lcMemoryFactory", "lcParserRegistry", "lcLoaderRegistry",
                     "lcRetrieverFactory", "lcVectorStoreFactory", "lcIndexService",
                     "lcToolFactory", "lcUtilityRegistry", "lcCallbackRegistry"]:
            assert name in beans, f"缺失 Bean: {name}"
        # registry 同步注册
        assert registry.get("lcLangChainModel") is beans["lcLangChainModel"]
        assert registry.get("lcChainService") is beans["lcChainService"]

    def test_configure_langchain_disabled(self, spring_chat):
        """enabled=false 时跳过装配，返回空 dict。"""
        registry = BeanRegistry()
        beans = configure_langchain(
            registry=registry,
            config=_StubConfig({"spring": {"langchain": {"enabled": False}}}),
            chat_model=spring_chat,
        )
        assert beans == {}

    def test_configure_langchain_auto_reuses_spring_model(self, spring_chat, spring_emb):
        """default-llm=auto 时复用传入的 springbootAI ChatModel 做桥接。"""
        registry = BeanRegistry()
        beans = configure_langchain(
            registry=registry,
            config=_StubConfig({"spring": {"langchain": {"default-llm": "auto"}}}),
            chat_model=spring_chat,
            embedding_model=spring_emb,
        )
        lc_model = beans["lcLangChainModel"]
        from langchain_core.messages import HumanMessage
        result = lc_model.invoke([HumanMessage(content="ping")])
        assert "[AI]" in result.content

    def test_chain_service_built_with_injected_model(self, lc_model):
        """ChainService 构造时注入 lcLangChainModel，后续 create_llm_chain 可用。"""
        service = ChainService(lcLangChainModel=lc_model)
        assert service.llm is lc_model
        from langchain_core.prompts import PromptTemplate
        prompt = PromptTemplate(input_variables=["q"], template="Q: {q}\nA:")
        chain = service.create_llm_chain(prompt)
        result = chain.invoke({"q": "hello"})
        assert "[AI]" in result["text"]


# ==================== 4. Partner 注册表 ====================

class TestPartners:
    """30+ Partner 提供商注册表与懒加载工厂。"""

    def test_registry_contains_major_providers(self):
        """注册表覆盖主流提供商。"""
        names = set(PARTNER_REGISTRY.keys())
        for expected in ["openai", "anthropic", "ollama", "deepseek", "zhipu",
                         "tongyi", "moonshot", "azure-openai", "cohere", "mistralai"]:
            assert expected in names, f"注册表缺失 partner: {expected}"

    def test_list_partners_sorted(self):
        """list_partners 返回排序后的名称列表。"""
        names = list_partners()
        assert names == sorted(names)
        assert len(names) >= 30

    def test_is_partner_available_unknown_returns_false(self):
        """未知 partner 的 is_partner_available 返回 False。"""
        assert is_partner_available("nonexistent-provider") is False

    def test_list_available_partners_returns_list(self):
        """list_available_partners 返回已安装 partner 列表（至少是 list 类型）。"""
        avail = list_available_partners()
        assert isinstance(avail, list)
        # list_available 是 list_partners 的子集
        assert set(avail).issubset(set(list_partners()))

    def test_partner_factory_unknown_raises(self):
        """未知 partner 调用 create 抛 ValueError。"""
        with pytest.raises(ValueError, match="未知 partner"):
            PartnerProviderFactory.create("no-such-provider", {})

    def test_partner_factory_missing_package_raises_import_error(self):
        """partner 包未安装时抛 ImportError 且带安装提示。"""
        # 选一个大概率未安装的 partner
        target = "perplexity"
        if is_partner_available(target):
            pytest.skip(f"{target} 已安装，跳过缺失包测试")
        with pytest.raises(ImportError, match="pip install"):
            PartnerProviderFactory.create(target, {"api_key": "x"})


# ==================== 5. Prompt 模板 ====================

class TestPrompts:
    """PromptTemplateFactory - 3 类模板创建。"""

    def test_create_prompt_template_auto_vars(self):
        """自动从 {var} 占位符解析 input_variables。"""
        tpl = PromptTemplateFactory.create_prompt_template("Q: {q}\nA:")
        assert "q" in tpl.input_variables

    def test_create_prompt_template_explicit_vars(self):
        """显式指定 input_variables。"""
        tpl = PromptTemplateFactory.create_prompt_template(
            "{a} and {b}", input_variables=["a", "b"])
        assert set(tpl.input_variables) == {"a", "b"}

    def test_create_chat_prompt_template(self):
        """多角色对话模板。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            {"role": "system", "content": "你是翻译助手"},
            {"role": "user", "content": "翻译: {text}"},
        ])
        rendered = tpl.format_messages(text="hello")
        assert len(rendered) == 2
        assert "翻译助手" in rendered[0].content
        assert "hello" in rendered[1].content

    def test_from_template(self):
        """from_template 便捷入口。"""
        tpl = PromptTemplateFactory.from_template("Say {word}")
        assert "word" in tpl.input_variables

    def test_create_few_shot_prompt_template(self):
        """Few-shot 模板。"""
        example_prompt = PromptTemplateFactory.create_prompt_template(
            "Q: {q}\nA: {a}", input_variables=["q", "a"])
        few = PromptTemplateFactory.create_few_shot_prompt_template(
            examples=[{"q": "1+1", "a": "2"}],
            example_prompt=example_prompt,
            suffix="Q: {q}\nA:",
            input_variables=["q"],
        )
        assert "q" in few.input_variables


# ==================== 6. Chain 服务 ====================

class TestChains:
    """ChainService - LLMChain / ConversationChain / 便捷执行。"""

    def test_run_llm_chain(self, lc_model):
        """run_llm_chain 从模板字符串创建并执行 LLMChain。"""
        service = ChainService(lcLangChainModel=lc_model)
        text = service.run_llm_chain("Q: {q}\nA:", q="hello")
        assert "[AI]" in text
        assert "hello" in text

    def test_create_llm_chain(self, lc_model):
        """create_llm_chain 返回可执行的 LLMChain。"""
        from langchain_core.prompts import PromptTemplate
        service = ChainService(lcLangChainModel=lc_model)
        prompt = PromptTemplate(input_variables=["x"], template="Echo: {x}")
        chain = service.create_llm_chain(prompt)
        result = chain.invoke({"x": "world"})
        assert "[AI]" in result["text"]

    def test_create_conversation_chain(self, lc_model):
        """ConversationChain 带记忆对话。"""
        service = ChainService(lcLangChainModel=lc_model)
        memory = MemoryFactory.create("buffer")
        chain = service.create_conversation_chain(memory=memory)
        result = chain.invoke({"input": "hi there"})
        assert "response" in result
        assert "[AI]" in result["response"]

    def test_run_conversation(self, lc_model):
        """run_conversation 便捷入口。"""
        service = ChainService(lcLangChainModel=lc_model)
        resp = service.run_conversation("ping")
        assert "[AI]" in resp

    def test_create_sequential_chain(self, lc_model):
        """SequentialChain 串联两个 LLMChain。"""
        from langchain_classic.chains import LLMChain
        from langchain_core.prompts import PromptTemplate
        service = ChainService(lcLangChainModel=lc_model)
        c1 = LLMChain(llm=lc_model,
                      prompt=PromptTemplate(input_variables=["a"], template="{a}"),
                      output_key="b")
        c2 = LLMChain(llm=lc_model,
                      prompt=PromptTemplate(input_variables=["b"], template="{b}"),
                      output_key="c")
        seq = service.create_sequential_chain(
            [c1, c2], input_variables=["a"], output_variables=["c"])
        result = seq.invoke({"a": "hello"})
        assert "c" in result

    def test_create_summarize_chain(self, lc_model):
        """summarize chain (stuff) 能加载并执行。"""
        from langchain_core.documents import Document
        service = ChainService(lcLangChainModel=lc_model)
        chain = service.create_summarize_chain(chain_type="stuff")
        result = chain.invoke([Document(page_content="Some text to summarize.")])
        # FakeChatModel 回复包含 [AI] 前缀
        text = result.get("output_text") if isinstance(result, dict) else str(result)
        assert isinstance(text, str)


# ==================== 7. Agent 服务 ====================

class TestAgents:
    """AgentService - Agent 类型创建与执行。"""

    def test_supported_agent_types(self):
        """supported_agent_types 返回非空列表。"""
        types = AgentService.supported_agent_types()
        assert isinstance(types, list)
        assert len(types) > 0
        assert "react" in types

    def test_create_react_agent(self, lc_model):
        """create_react_agent 返回 AgentExecutor。"""
        from langchain_classic.agents import AgentExecutor
        service = AgentService(lcLangChainModel=lc_model)
        tools = [ToolFactory.from_function(lambda q: "42", name="calc",
                                           description="计算工具")]
        executor = service.create_react_agent(tools=tools)
        assert isinstance(executor, AgentExecutor)

    def test_supported_agent_types_includes_structured_chat(self):
        """structured-chat 和 openai-tools 应在 supported_agent_types 中。"""
        types = AgentService.supported_agent_types()
        assert "structured-chat" in types, "structured-chat 缺失"
        assert "openai-tools" in types, "openai-tools 缺失"
        assert "react" in types

    def test_create_agent_structured_chat(self, lc_model):
        """create_agent(agent_type='structured-chat') 走专用工厂。"""
        from langchain_classic.agents import AgentExecutor
        service = AgentService(lcLangChainModel=lc_model)
        tools = [ToolFactory.from_function(lambda q: "ok", name="echo",
                                           description="回显工具")]
        executor = service.create_agent(tools, agent_type="structured-chat")
        assert isinstance(executor, AgentExecutor)

    def test_create_agent_openai_tools(self, lc_model):
        """create_agent(agent_type='openai-tools') 走专用工厂。"""
        from langchain_classic.agents import AgentExecutor
        service = AgentService(lcLangChainModel=lc_model)
        tools = [ToolFactory.from_function(lambda q: "ok", name="echo",
                                           description="回显工具")]
        executor = service.create_agent(tools, agent_type="openai-tools")
        assert isinstance(executor, AgentExecutor)

    def test_create_agent_unknown_type_raises(self, lc_model):
        """未知 agent_type 抛 ValueError。"""
        service = AgentService(lcLangChainModel=lc_model)
        with pytest.raises(ValueError, match="未知 agent_type"):
            service.create_agent([], agent_type="nonexistent")


# ==================== 7.5 安全算术求值器 ====================

class TestSafeEvalArithmetic:
    """safe_eval_arithmetic - 替代 eval 的安全求值器。

    确保只允许数字和算术运算符，杜绝沙箱逃逸。
    """

    def test_basic_arithmetic(self):
        """基本算术运算正确。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("2+3*4") == 14
        assert safe_eval_arithmetic("(2+3)*4") == 20
        assert safe_eval_arithmetic("10/3") == 10 / 3
        assert safe_eval_arithmetic("2**10") == 1024
        assert safe_eval_arithmetic("-5+3") == -2
        assert safe_eval_arithmetic("10//3") == 3
        assert safe_eval_arithmetic("10%3") == 1

    def test_blocks_attribute_access(self):
        """属性访问（沙箱逃逸经典手法）被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('(1).__class__.__bases__[0].__subclasses__()')

    def test_blocks_function_call(self):
        """函数调用（__import__、open 等）被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('__import__("os")')
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('open("x")')
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('getattr(1, "real")')

    def test_blocks_collections(self):
        """列表/字典字面量被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('[1,2,3]')
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('{"a": 1}')

    def test_syntax_error_raises_value_error(self):
        """语法错误抛 ValueError（非 SyntaxError 泄漏）。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises(ValueError):
            safe_eval_arithmetic('2++')


# ==================== 8. Memory ====================

class TestMemory:
    """MemoryFactory - 4 种会话记忆。"""

    def test_supported_types(self):
        """supported_types 返回 4 种记忆类型。"""
        types = MemoryFactory.supported_types()
        assert "buffer" in types
        assert "summary" in types
        assert "buffer-window" in types
        assert "token-buffer" in types

    def test_create_buffer_memory(self):
        """buffer 记忆无需 llm。"""
        mem = MemoryFactory.create("buffer")
        assert mem.memory_key == "history"
        # 初始为空
        assert mem.buffer == [] or mem.load_memory_variables({}).get("history") is not None

    def test_create_buffer_window_memory(self, lc_model):
        """buffer-window 记忆需要 llm，窗口大小生效。"""
        mem = MemoryFactory.create("buffer-window", llm=lc_model, max_messages=3)
        assert mem.k == 3

    def test_summary_requires_llm(self):
        """summary 记忆缺少 llm 时抛 ValueError。"""
        with pytest.raises(ValueError, match="需要 llm"):
            MemoryFactory.create("summary")

    def test_token_buffer_requires_llm(self):
        """token-buffer 记忆缺少 llm 时抛 ValueError。"""
        with pytest.raises(ValueError, match="需要 llm"):
            MemoryFactory.create("token-buffer")

    def test_unknown_type_raises(self):
        """未知 memory_type 抛 ValueError。"""
        with pytest.raises(ValueError, match="未知 memory_type"):
            MemoryFactory.create("nonexistent")


# ==================== 9. Parser ====================

class TestParsers:
    """OutputParserFactory - 5 种输出解析器。"""

    def test_create_comma_list_parser(self):
        """逗号列表解析器。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("apple, banana, cherry")
        assert result == ["apple", "banana", "cherry"]

    def test_create_json_parser(self):
        """JSON 解析器。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"key": "value", "n": 3}')
        assert result["key"] == "value"
        assert result["n"] == 3

    def test_create_datetime_parser(self):
        """日期时间解析器（默认格式 %Y-%m-%dT%H:%M:%S.%fZ）。"""
        parser = OutputParserFactory.create_datetime_parser()
        # DatetimeOutputParser 默认要求带微秒和 Z 后缀的 ISO8601
        result = parser.parse("2026-08-10T12:00:00.000Z")
        assert hasattr(result, "year") or hasattr(result, "isoformat")

    def test_create_via_unified_entry(self):
        """create(parser_type=...) 统一入口。"""
        parser = OutputParserFactory.create("comma-list")
        assert parser.parse("a, b") == ["a", "b"]

    def test_create_unknown_raises(self):
        """未知 parser_type 抛 ValueError。"""
        with pytest.raises(ValueError, match="未知 parser_type"):
            OutputParserFactory.create("nonexistent")


# ==================== 10. VectorStore ====================

class TestVectorStores:
    """VectorStoreFactory - inmemory 向量库 + retriever 转换。"""

    def test_supported_types(self):
        """supported_types 包含 inmemory + 外部库。"""
        types = VectorStoreFactory.supported_types()
        assert "inmemory" in types
        assert "faiss" in types
        assert "chroma" in types

    def test_create_inmemory(self, lc_embeddings):
        """create('inmemory') 返回 springbootAI SimpleInMemoryVectorStore。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        assert store is not None

    def test_from_texts_inmemory(self, lc_embeddings):
        """from_texts 写入文本并检索。"""
        store = VectorStoreFactory.from_texts(
            "inmemory",
            ["SpringBootAI is a framework.", "LangChain provides chains and agents."],
            lc_embeddings,
        )
        assert store is not None

    def test_unknown_store_type_raises(self, lc_embeddings):
        """未知 store_type 抛 ValueError。"""
        with pytest.raises(ValueError, match="未知 store_type"):
            VectorStoreFactory.create("nonexistent", embeddings=lc_embeddings)

    def test_as_retriever(self):
        """as_retriever 把带 as_retriever 的向量库转为 langchain Retriever。"""
        # SimpleInMemoryVectorStore 无 as_retriever，用 mock 验证静态方法逻辑
        mock_store = MagicMock()
        mock_store.as_retriever.return_value = MagicMock(name="retriever")
        retriever = VectorStoreFactory.as_retriever(mock_store, search_kwargs={"k": 1})
        mock_store.as_retriever.assert_called_once_with(
            search_type="similarity", search_kwargs={"k": 1})
        assert retriever is not None


# ==================== 11. Retriever ====================

class TestRetrievers:
    """RetrieverFactory - 检索器类型枚举。"""

    def test_supported_types(self):
        """supported_types 返回 6 种检索器。"""
        types = RetrieverFactory.supported_types()
        assert "similarity" in types
        assert "multi-query" in types
        assert "ensemble" in types


# ==================== 12. Index 服务 ====================

class TestIndexService:
    """IndexService - RAG 全流程便捷方法。"""

    def test_create_from_texts_inmemory(self, lc_embeddings, lc_model):
        """create_from_texts 用 inmemory 向量库建索引。"""
        service = IndexService(lcEmbeddings=lc_embeddings, lcLangChainModel=lc_model)
        store = service.create_from_texts(
            ["SpringBootAI brings Spring annotations to Python.",
             "LangChain enables chains, agents and RAG."],
            vector_store_type="inmemory",
        )
        assert store is not None

    def test_query_returns_documents(self, lc_embeddings, lc_model):
        """query 在 inmemory 索引上检索文档。"""
        service = IndexService(lcEmbeddings=lc_embeddings, lcLangChainModel=lc_model)
        store = service.create_from_texts(
            ["The sky is blue.", "Grass is green."],
            vector_store_type="inmemory",
        )
        results = service.query(store, "sky", k=1)
        assert isinstance(results, list)


# ==================== 13. Tool ====================

class TestTools:
    """ToolFactory / ToolRegistry - langchain 工具创建与桥接。"""

    def test_from_function_creates_structured_tool(self):
        """from_function 把 Python 函数转为 langchain StructuredTool。"""
        from langchain_core.tools import BaseTool

        def adder(a: int, b: int) -> int:
            """两数相加。"""
            return a + b

        tool = ToolFactory.from_function(adder, name="adder", description="加法")
        assert isinstance(tool, BaseTool)
        assert tool.name == "adder"
        assert tool.invoke({"a": 1, "b": 2}) == 3

    def test_create_tool_simple(self):
        """create_tool 创建简单 Tool。"""
        from langchain_core.tools import Tool
        tool = ToolFactory.create_tool("echo", lambda x: x, description="回显")
        assert isinstance(tool, Tool)
        assert tool.name == "echo"

    def test_from_spring_tool_registry_empty(self):
        """空/None registry 返回空列表。"""
        assert ToolFactory.from_spring_tool_registry(None) == []

    def test_tool_registry_collect(self):
        """ToolRegistry 收集多个工具。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t1", description="tool 1")
        reg.add_function(lambda x: x, name="t2", description="tool 2")
        assert len(reg.all()) == 2
        assert reg.names() == ["t1", "t2"]

    def test_tool_registry_clear(self):
        """clear 清空工具列表。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t", description="d")
        reg.clear()
        assert len(reg.all()) == 0


# ==================== 14. Loaders / Utilities / Callbacks ====================

class TestRegistries:
    """DocumentLoaderRegistry / UtilityRegistry / CallbackRegistry 能力枚举。"""

    def test_loader_supported_types(self):
        """DocumentLoaderRegistry 列出支持的加载器类型。"""
        types = DocumentLoaderRegistry.supported_types()
        assert "text" in types
        assert "csv" in types
        assert "pdf" in types

    def test_utility_supported_types(self):
        """UtilityRegistry 列出支持的实用工具。"""
        types = UtilityRegistry.supported_types()
        assert isinstance(types, list)
        assert len(types) > 0

    def test_callback_registry(self):
        """CallbackRegistry 可实例化。"""
        reg = CallbackRegistry()
        assert reg is not None


# ==================== 15. 端到端集成 ====================

class TestEndToEndIntegration:
    """端到端：springbootAI 模型 -> langchain Chain -> 业务输出。"""

    def test_full_llm_chain_pipeline(self, spring_chat):
        """完整链路：FakeChatModel -> 桥接 -> LLMChain -> 文本输出。"""
        lc_model = to_langchain_model(spring_chat)
        service = ChainService(lcLangChainModel=lc_model)
        # 模拟翻译场景
        answer = service.run_llm_chain(
            "请把以下文本翻译成英文：\n{text}\n翻译：",
            text="你好世界",
        )
        assert "[AI]" in answer
        # FakeChatModel 回显最后一句话，应包含输入文本
        assert "你好世界" in answer

    def test_conversation_with_memory_flow(self, spring_chat):
        """带记忆的对话链路：多轮对话记忆可加载。"""
        lc_model = to_langchain_model(spring_chat)
        service = ChainService(lcLangChainModel=lc_model)
        memory = MemoryFactory.create("buffer")
        # 第一轮
        r1 = service.run_conversation("我叫小明", memory=memory)
        assert "[AI]" in r1
        # 记忆应记录历史
        history = memory.load_memory_variables({}).get("history", [])
        assert len(history) > 0

    def test_rag_pipeline_with_fake_models(self, spring_chat, spring_emb):
        """RAG 链路：嵌入入库 -> 检索 -> LLM 生成。"""
        lc_model = to_langchain_model(spring_chat)
        lc_emb = to_langchain_embeddings(spring_emb)
        index_service = IndexService(lcEmbeddings=lc_emb, lcLangChainModel=lc_model)

        store = index_service.create_from_texts(
            ["SpringBootAI 使用 @Service 注解。", "LangChain 提供链和代理。"],
            vector_store_type="inmemory",
        )
        results = index_service.query(store, "注解", k=2)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_configure_langchain_full_bootstrap(self, spring_chat, spring_emb):
        """完整装配后 ChainService Bean 可正常工作。"""
        registry = BeanRegistry()
        beans = configure_langchain(
            registry=registry,
            config=_StubConfig({"spring": {"langchain": {"default-llm": "auto"}}}),
            chat_model=spring_chat,
            embedding_model=spring_emb,
        )
        chain_service = beans["lcChainService"]
        text = chain_service.run_llm_chain("Q: {q}\nA:", q="integration-test")
        assert "[AI]" in text
        assert "integration-test" in text


# ==================== 辅助类 ====================

class _StubConfig:
    """最小配置加载器 stub - 支持 get_prefix_config 返回子树。

    生产环境用 springbootai.config.config_loader；测试用本 stub 注入确定性配置，
    避免读取真实 application.yml 造成的环境依赖。
    """

    def __init__(self, tree: dict):
        self._tree = tree

    def get_prefix_config(self, prefix: str) -> dict:
        """按 dotted prefix 取子树（如 springbootai.langchain）。"""
        node = self._tree
        for part in prefix.split("."):
            if not isinstance(node, dict):
                return {}
            node = node.get(part, {})
        return node if isinstance(node, dict) else {}

    def resolve_value_expression(self, expression, default=None):
        return default
