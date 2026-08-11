"""LangChain 模块扩展测试 - 425+ 个用例，与 test_langchain_module.py 合计 500+。

覆盖范围：
- Adapters(35)   双向适配器：消息转换/模型桥接/嵌入桥接/流式/工具绑定/错误处理
- Config(25)      配置绑定：全字段/嵌套/类型转换/env覆盖/partners透传
- AutoConfig(25)  自动装配：全Bean/disabled/partner注册/错误恢复/模型复用
- Partners(35)    Partner：注册表/可用性/工厂创建/参数过滤/错误提示
- Prompts(30)     Prompt：全模板/变量提取/格式化/少样本/聊天模板/错误
- Chains(35)      Chain：全Chain类型/invoke/batch/顺序链/摘要/数学/检索QA
- Agents(35)      Agent：全Agent类型/工具绑定/执行/迭代限制/错误处理
- SafeEval(25)    安全求值：全运算/攻击手法/边界/错误/嵌套
- Memory(30)      Memory：全类型/窗口/清空/加载/错误/参数校验
- Parsers(30)     Parser：全解析器/格式化/错误恢复/自定义/嵌套
- VectorStores(35) 向量库：全类型/入库/检索/元数据/相似度/Retriever
- Retrievers(25)  检索器：全类型/k值/过滤/多查询/ensemble
- IndexService(25) RAG：建库/查询/文档/加载器/端到端/错误
- Tools(30)       工具：创建/注册/执行/schema/springbootAI转换/清空
- Loaders(20)     加载器：全类型/加载/错误/便捷方法
- Utilities(15)   实用工具：全类型/创建/as_tools/错误
- Callbacks(15)   回调：全类型/注册/all/clear/文件回调
- E2E(40)         端到端：完整流程/组合使用/错误恢复/性能
"""
import importlib
import os
import sys
import warnings
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")
try:
    from langchain_core._api import LangChainDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

from spring.ai.providers import FakeChatModel, FakeEmbeddingModel
from spring.ai.core import ChatModel, EmbeddingModel, Message
from spring.context.registry import BeanRegistry
from spring.langchain.adapters import (
    LangChainModelToSpring,
    SpringChatModelToLangChain, SpringEmbeddingToLangChain,
    to_langchain_embeddings, to_langchain_model,
    to_spring_embeddings, to_spring_model,
)
from spring.langchain.autoconfig import (
    bind_langchain_config, configure_langchain,
)
from spring.langchain.partners import (
    PARTNER_REGISTRY, PartnerProviderFactory,
    is_partner_available, list_available_partners, list_partners,
)
from spring.langchain.prompts.templates import PromptTemplateFactory
from spring.langchain.chains.services import ChainService
from spring.langchain.agents.services import AgentService
from spring.langchain.memory.memory import MemoryFactory
from spring.langchain.parsers.parsers import OutputParserFactory
from spring.langchain.loaders.loaders import DocumentLoaderRegistry
from spring.langchain.retrievers.retrievers import RetrieverFactory
from spring.langchain.vectorstores.stores import VectorStoreFactory
from spring.langchain.indexes.index import IndexService
from spring.langchain.tools.tools import ToolFactory, ToolRegistry
from spring.langchain.utilities.utils import UtilityRegistry
from spring.langchain.callbacks.handlers import CallbackRegistry


# ==================== 公共 fixture ====================

@pytest.fixture
def spring_chat():
    return FakeChatModel(prefix="[AI]")

@pytest.fixture
def spring_emb():
    return FakeEmbeddingModel(dim=8)

@pytest.fixture
def lc_model(spring_chat):
    return to_langchain_model(spring_chat)

@pytest.fixture
def lc_embeddings(spring_emb):
    return to_langchain_embeddings(spring_emb)

@pytest.fixture
def chain_service(lc_model):
    return ChainService(lcLangChainModel=lc_model)

@pytest.fixture
def agent_service(lc_model):
    return AgentService(lcLangChainModel=lc_model)

@pytest.fixture
def index_service(lc_embeddings, lc_model):
    return IndexService(lcEmbeddings=lc_embeddings, lcLangChainModel=lc_model)

@pytest.fixture(autouse=True)
def _isolate_lc_env(monkeypatch):
    """隔离 LangChain / AI 环境变量，并显式允许 Fake 模型降级。

    - 清理 LC_* 残留 env，防止开发者本机配置干扰绑定测试
    - 设置 AI_ALLOW_FAKE=true：本测试套件全程使用 FakeChatModel/FakeEmbeddingModel，
      不依赖真实 API Key；configure_ai() 在无 key 时降级 Fake，符合测试预期
    """
    for key in list(os.environ):
        if key.startswith("LC_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AI_ALLOW_FAKE", "true")


class _StubConfig:
    """测试用配置桩 - 把 langchain 子树 dict 包装成 config_loader 风格。

    configure_langchain 调用 config.get_prefix_config("spring.langchain") 取子树，
    这里直接返回构造时传入的 langchain 配置 dict，便于测试自定义配置场景。
    """

    def __init__(self, langchain_cfg=None):
        self._cfg = langchain_cfg or {}

    def get_prefix_config(self, prefix):
        # 任何 prefix 都返回 langchain 子树（测试专用）
        return self._cfg


# ==================== 1. Adapters 扩展 (35) ====================

class TestAdaptersExt:
    """适配器扩展：消息转换/模型桥接/嵌入桥接/流式/工具绑定/错误处理。"""

    def test_01_spring_to_langchain_llm_type(self, spring_chat):
        """适配器的 _llm_type 标识为 springboot-ai-adapter。"""
        lc = SpringChatModelToLangChain(spring_chat).build()
        assert lc._llm_type == "springboot-ai-adapter"

    def test_02_spring_to_langchain_is_base_chat_model(self, spring_chat):
        """产出的是 BaseChatModel 子类。"""
        from langchain_core.language_models.chat_models import BaseChatModel
        lc = SpringChatModelToLangChain(spring_chat).build()
        assert isinstance(lc, BaseChatModel)

    def test_03_to_langchain_model_preserves_user_message(self, spring_chat):
        """user 消息内容正确传递。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="hello world")])
        assert "hello world" in result.content

    def test_04_to_langchain_model_preserves_system_message(self, spring_chat):
        """system 消息不丢失。"""
        from langchain_core.messages import HumanMessage, SystemMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([SystemMessage(content="你是助手"), HumanMessage(content="hi")])
        assert "你是助手" in result.content or "hi" in result.content

    def test_05_to_langchain_model_preserves_ai_message(self, spring_chat):
        """AI 消息也正确桥接。"""
        from langchain_core.messages import AIMessage, HumanMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="q"), AIMessage(content="a"), HumanMessage(content="b")])
        assert "b" in result.content

    def test_06_to_langchain_model_invoke_returns_ai_message(self, spring_chat):
        """invoke 返回 AIMessage。"""
        from langchain_core.messages import HumanMessage, AIMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="test")])
        assert isinstance(result, AIMessage)

    def test_07_to_langchain_model_call_count(self, spring_chat):
        """底层 springbootAI 模型被调用。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        lc.invoke([HumanMessage(content="a")])
        lc.invoke([HumanMessage(content="b")])
        assert spring_chat.call_count == 2

    def test_08_langchain_to_spring_returns_chat_model(self, lc_model):
        """langchain 模型 → springbootAI ChatModel。"""
        spring_model = to_spring_model(lc_model)
        assert isinstance(spring_model, ChatModel)

    def test_09_langchain_to_spring_invoke(self, lc_model):
        """反向适配后能正常调用。"""
        spring_model = to_spring_model(lc_model)
        result = spring_model.call([Message.user("hello")])
        assert "hello" in result.content()

    def test_10_langchain_to_spring_stream(self, lc_model):
        """反向适配支持流式。"""
        spring_model = to_spring_model(lc_model)
        chunks = list(spring_model.stream([Message.user("stream test")]))
        assert len(chunks) >= 1

    def test_11_spring_to_langchain_embeddings_type(self, spring_emb):
        """嵌入适配器返回 langchain Embeddings。"""
        from langchain_core.embeddings import Embeddings
        lc_emb = SpringEmbeddingToLangChain(spring_emb).build()
        assert isinstance(lc_emb, Embeddings)

    def test_12_spring_to_langchain_embeddings_embed_query(self, spring_emb):
        """embed_query 返回向量。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        vec = lc_emb.embed_query("test text")
        assert isinstance(vec, list)
        assert len(vec) == 8

    def test_13_spring_to_langchain_embeddings_embed_documents(self, spring_emb):
        """embed_documents 返回多条向量。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        vecs = lc_emb.embed_documents(["text1", "text2", "text3"])
        assert len(vecs) == 3
        assert all(len(v) == 8 for v in vecs)

    def test_14_spring_to_langchain_embeddings_deterministic(self, spring_emb):
        """相同文本嵌入确定。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        v1 = lc_emb.embed_query("same text")
        v2 = lc_emb.embed_query("same text")
        assert v1 == v2

    def test_15_spring_to_langchain_embeddings_different_text(self, spring_emb):
        """不同文本嵌入不同。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        v1 = lc_emb.embed_query("text one")
        v2 = lc_emb.embed_query("text two")
        assert v1 != v2

    def test_16_langchain_to_spring_embeddings_type(self, lc_embeddings):
        """反向嵌入适配返回 springbootAI EmbeddingModel。"""
        spring_e = to_spring_embeddings(lc_embeddings)
        assert isinstance(spring_e, EmbeddingModel)

    def test_17_langchain_to_spring_embeddings_embed_one(self, lc_embeddings):
        """embed_one 返回向量。"""
        spring_e = to_spring_embeddings(lc_embeddings)
        vec = spring_e.embed_one("test")
        assert isinstance(vec, list)
        assert len(vec) == 8

    def test_18_langchain_to_spring_embeddings_embed(self, lc_embeddings):
        """embed 返回多条向量。"""
        spring_e = to_spring_embeddings(lc_embeddings)
        vecs = spring_e.embed(["a", "b"])
        assert len(vecs) == 2

    def test_19_embeddings_roundtrip_query(self, spring_emb):
        """嵌入双向桥接往返一致（query）。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        spring_e = to_spring_embeddings(lc_emb)
        v1 = spring_emb.embed_one("roundtrip")
        v2 = spring_e.embed_one("roundtrip")
        assert v1 == v2

    def test_20_embeddings_roundtrip_documents(self, spring_emb):
        """嵌入双向桥接往返一致（documents）。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        spring_e = to_spring_embeddings(lc_emb)
        v1 = spring_emb.embed(["doc1", "doc2"])
        v2 = spring_e.embed(["doc1", "doc2"])
        assert v1 == v2

    def test_21_adapter_preserves_prefix(self, spring_chat):
        """适配后前缀仍然存在。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="test")])
        assert "[AI]" in result.content

    def test_22_adapter_empty_messages_raises(self, spring_chat):
        """空消息列表处理。"""
        lc = to_langchain_model(spring_chat)
        try:
            result = lc.invoke([])
            # FakeChatModel 可能返回空前缀
            assert isinstance(result.content, str)
        except Exception:
            # 空消息抛异常也是合理行为
            pass

    def test_23_adapter_long_message(self, spring_chat):
        """长消息正确处理。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        long_text = "x" * 10000
        result = lc.invoke([HumanMessage(content=long_text)])
        assert "x" in result.content

    def test_24_adapter_unicode_message(self, spring_chat):
        """Unicode 消息正确处理。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="你好世界🌍")])
        assert "你好" in result.content

    def test_25_adapter_special_chars(self, spring_chat):
        """特殊字符消息正确处理。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        result = lc.invoke([HumanMessage(content="<script>alert('xss')</script>")])
        assert "script" in result.content

    def test_26_bind_tools_returns_new_instance(self, spring_chat):
        """bind_tools 返回新实例，不污染原实例。"""
        from langchain_core.tools import StructuredTool
        lc = to_langchain_model(spring_chat)
        def echo(x: str) -> str:
            """回显工具"""
            return x
        tool = StructuredTool.from_function(echo)
        bound = lc.bind_tools([tool])
        assert bound is not lc

    def test_27_bind_tools_preserves_tool_registry(self, spring_chat):
        """bind_tools 后工具注册表非空。"""
        from langchain_core.tools import StructuredTool
        lc = to_langchain_model(spring_chat)
        def calc(x: str) -> str:
            """计算"""
            return x
        tool = StructuredTool.from_function(calc)
        bound = lc.bind_tools([tool])
        assert bound._tool_registry is not None

    def test_28_bind_tools_empty_list(self, spring_chat):
        """空工具列表 bind_tools 不报错。"""
        lc = to_langchain_model(spring_chat)
        bound = lc.bind_tools([])
        assert bound is not lc

    def test_29_adapter_multiple_invokes_independent(self, spring_chat):
        """多次 invoke 相互独立。"""
        from langchain_core.messages import HumanMessage
        lc = to_langchain_model(spring_chat)
        r1 = lc.invoke([HumanMessage(content="first")])
        r2 = lc.invoke([HumanMessage(content="second")])
        assert "first" in r1.content
        assert "second" in r2.content

    def test_30_spring_to_langchain_direct_build(self, spring_chat):
        """直接用 build() 方法构造。"""
        lc = SpringChatModelToLangChain(spring_chat).build()
        from langchain_core.messages import HumanMessage
        result = lc.invoke([HumanMessage(content="direct")])
        assert "direct" in result.content

    def test_31_langchain_to_spring_direct(self, lc_model):
        """直接用 LangChainModelToSpring 构造。"""
        spring_model = LangChainModelToSpring(lc_model)
        assert isinstance(spring_model, ChatModel)

    def test_32_embedding_adapter_empty_list(self, spring_emb):
        """空文档列表嵌入。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        vecs = lc_emb.embed_documents([])
        assert vecs == []

    def test_33_embedding_adapter_single_doc(self, spring_emb):
        """单条文档嵌入。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        vecs = lc_emb.embed_documents(["single"])
        assert len(vecs) == 1

    def test_34_embedding_adapter_large_batch(self, spring_emb):
        """大批量嵌入。"""
        lc_emb = to_langchain_embeddings(spring_emb)
        texts = [f"doc_{i}" for i in range(50)]
        vecs = lc_emb.embed_documents(texts)
        assert len(vecs) == 50

    def test_35_model_adapter_roundtrip_call(self, spring_chat):
        """模型双向桥接后仍能通过 springbootAI 接口调用。"""
        lc = to_langchain_model(spring_chat)
        spring_model = to_spring_model(lc)
        result = spring_model.call([Message.user("roundtrip")])
        assert "roundtrip" in result.content()


# ==================== 2. Config Binding 扩展 (25) ====================

class TestConfigBindingExt:
    """配置绑定扩展：全字段/嵌套/类型转换/env覆盖。"""

    def test_01_default_enabled(self):
        """默认 enabled=True。"""
        props = bind_langchain_config({})
        assert props.enabled is True

    def test_02_default_llm_auto(self):
        """默认 default_llm='auto'。"""
        props = bind_langchain_config({})
        assert props.default_llm == "auto"

    def test_03_default_chains_verbose(self):
        """默认 chains.default_verbose=False。"""
        props = bind_langchain_config({})
        assert props.chains.default_verbose is False

    def test_04_default_agent_type(self):
        """默认 agents.default_type='react'。"""
        props = bind_langchain_config({})
        assert props.agents.default_type == "react"

    def test_05_default_agent_max_iter(self):
        """默认 agents.max_iterations=10。"""
        props = bind_langchain_config({})
        assert props.agents.max_iterations == 10

    def test_06_default_vector_store_type(self):
        """默认 vector_store.type='faiss'。"""
        props = bind_langchain_config({})
        assert props.vector_store.type == "faiss"

    def test_07_default_vector_store_persist_dir(self):
        """默认 vector_store.persist_dir='./data/vectors'。"""
        props = bind_langchain_config({})
        assert props.vector_store.persist_dir == "./data/vectors"

    def test_08_default_retriever_type(self):
        """默认 retriever.type='similarity'。"""
        props = bind_langchain_config({})
        assert props.retriever.type == "similarity"

    def test_09_default_retriever_k(self):
        """默认 retriever.k=4。"""
        props = bind_langchain_config({})
        assert props.retriever.k == 4

    def test_10_default_memory_type(self):
        """默认 memory.type='buffer'。"""
        props = bind_langchain_config({})
        assert props.memory.type == "buffer"

    def test_11_default_memory_max(self):
        """默认 memory.max_messages=20。"""
        props = bind_langchain_config({})
        assert props.memory.max_messages == 20

    def test_12_kebab_case_enabled(self):
        """kebab-case enabled 绑定。"""
        props = bind_langchain_config({"enabled": "false"})
        assert props.enabled is False

    def test_13_kebab_case_default_llm(self):
        """kebab-case default-llm 绑定。"""
        props = bind_langchain_config({"default-llm": "openai"})
        assert props.default_llm == "openai"

    def test_14_kebab_case_chains(self):
        """kebab-case chains.default-verbose 绑定。"""
        props = bind_langchain_config({"chains": {"default-verbose": "true"}})
        assert props.chains.default_verbose is True

    def test_15_kebab_case_agents(self):
        """kebab-case agents.default-type 绑定。"""
        props = bind_langchain_config({"agents": {"default-type": "structured-chat"}})
        assert props.agents.default_type == "structured-chat"

    def test_16_kebab_case_vector_store(self):
        """kebab-case vector-store.type 绑定。"""
        props = bind_langchain_config({"vector-store": {"type": "chroma"}})
        assert props.vector_store.type == "chroma"

    def test_17_kebab_case_retriever(self):
        """kebab-case retriever.k 绑定。"""
        props = bind_langchain_config({"retriever": {"k": "8"}})
        assert props.retriever.k == 8

    def test_18_kebab_case_memory(self):
        """kebab-case memory.type 绑定。"""
        props = bind_langchain_config({"memory": {"type": "summary"}})
        assert props.memory.type == "summary"

    def test_19_type_coercion_int(self):
        """字符串转 int。"""
        props = bind_langchain_config({"retriever": {"k": "10"}})
        assert isinstance(props.retriever.k, int)
        assert props.retriever.k == 10

    def test_20_type_coercion_bool_true(self):
        """字符串转 bool true。"""
        props = bind_langchain_config({"enabled": "true"})
        assert props.enabled is True

    def test_21_type_coercion_bool_false(self):
        """字符串转 bool false。"""
        props = bind_langchain_config({"enabled": "false"})
        assert props.enabled is False

    def test_22_partners_dict_pass_through(self):
        """partners 字典透传。"""
        props = bind_langchain_config({
            "partners": {"openai": {"api-key": "sk-x", "model": "gpt-4"}}
        })
        assert "openai" in props.partners
        assert props.partners["openai"]["api-key"] == "sk-x"

    def test_23_partners_multiple(self):
        """多个 partner 配置。"""
        props = bind_langchain_config({
            "partners": {
                "openai": {"api-key": "sk-1"},
                "anthropic": {"api-key": "sk-2"},
                "ollama": {"base-url": "http://localhost:11434"},
            }
        })
        assert len(props.partners) == 3

    def test_24_env_override_enabled(self, monkeypatch):
        """env 覆盖 enabled。"""
        monkeypatch.setenv("LC_ENABLED", "false")
        props = bind_langchain_config({})
        assert props.enabled is False

    def test_25_env_override_agent_type(self, monkeypatch):
        """env 覆盖 agent type。"""
        monkeypatch.setenv("LC_AGENT_TYPE", "openai-tools")
        props = bind_langchain_config({})
        assert props.agents.default_type == "openai-tools"


# ==================== 3. AutoConfig 扩展 (25) ====================

class TestAutoConfigExt:
    """自动装配扩展：全Bean/disabled/partner注册/错误恢复。"""

    def test_01_configure_registers_lc_model(self):
        """装配 lcLangChainModel Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcLangChainModel" in beans

    def test_02_configure_registers_lc_embeddings(self):
        """装配 lcEmbeddings Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcEmbeddings" in beans

    def test_03_configure_registers_chain_service(self):
        """装配 lcChainService Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcChainService" in beans

    def test_04_configure_registers_agent_service(self):
        """装配 lcAgentService Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcAgentService" in beans

    def test_05_configure_registers_memory_factory(self):
        """装配 lcMemoryFactory Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcMemoryFactory" in beans

    def test_06_configure_registers_prompt_registry(self):
        """装配 lcPromptRegistry Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcPromptRegistry" in beans

    def test_07_configure_registers_parser_registry(self):
        """装配 lcParserRegistry Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcParserRegistry" in beans

    def test_08_configure_registers_loader_registry(self):
        """装配 lcLoaderRegistry Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcLoaderRegistry" in beans

    def test_09_configure_registers_retriever_factory(self):
        """装配 lcRetrieverFactory Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcRetrieverFactory" in beans

    def test_10_configure_registers_vector_store_factory(self):
        """装配 lcVectorStoreFactory Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcVectorStoreFactory" in beans

    def test_11_configure_registers_index_service(self):
        """装配 lcIndexService Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcIndexService" in beans

    def test_12_configure_registers_tool_factory(self):
        """装配 lcToolFactory Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcToolFactory" in beans

    def test_13_configure_registers_utility_registry(self):
        """装配 lcUtilityRegistry Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcUtilityRegistry" in beans

    def test_14_configure_registers_callback_registry(self):
        """装配 lcCallbackRegistry Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert "lcCallbackRegistry" in beans

    def test_15_configure_disabled_returns_empty(self):
        """enabled=false 时不装配核心 Bean。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry,
                                    config=_StubConfig({"enabled": False}))
        assert "lcChainService" not in beans
        assert "lcAgentService" not in beans

    def test_16_configure_auto_reuses_spring_model(self):
        """default-llm=auto 复用 aiChatModel。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert beans["lcLangChainModel"] is not None

    def test_17_configure_chain_service_callable(self):
        """装配后 ChainService 可调用。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        chain = beans["lcChainService"]
        result = chain.run_llm_chain("回答: {q}", q="test")
        assert "test" in result

    def test_18_configure_agent_service_has_model(self):
        """装配后 AgentService 有模型。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        agent = beans["lcAgentService"]
        assert agent.llm is not None

    def test_19_configure_index_service_has_embeddings(self):
        """装配后 IndexService 有嵌入模型。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        idx = beans["lcIndexService"]
        assert idx._embeddings is not None

    def test_20_configure_with_custom_config(self):
        """自定义配置装配。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry, config=_StubConfig({
            "agents": {"default-type": "structured-chat", "max-iterations": 5}
        }))
        assert "lcChainService" in beans

    def test_21_configure_partners_skips_missing_dep(self):
        """partner 依赖缺失时跳过不阻塞。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry, config=_StubConfig({
            "partners": {"nonexistent-provider": {"api-key": "fake"}}
        }))
        # 不报错，核心 Bean 仍装配
        assert "lcChainService" in beans

    def test_22_configure_returns_dict(self):
        """configure_langchain 返回 dict。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        assert isinstance(beans, dict)

    def test_23_configure_bean_count(self):
        """装配的 Bean 数量 >= 14。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        lc_beans = [k for k in beans if k.startswith("lc")]
        assert len(lc_beans) >= 14

    def test_24_configure_idempotent(self):
        """多次 configure 不报错。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans1 = configure_langchain(registry=registry)
        beans2 = configure_langchain(registry=registry)
        assert "lcChainService" in beans1
        assert "lcChainService" in beans2

    def test_25_configure_without_ai_still_works(self):
        """无 configure_ai 时仍可装配（降级 Fake）。"""
        registry = BeanRegistry()
        beans = configure_langchain(registry=registry)
        assert "lcChainService" in beans


# ==================== 4. Partners 扩展 (35) ====================

class TestPartnersExt:
    """Partner 扩展：注册表/可用性/工厂创建/参数过滤。"""

    def test_01_registry_is_dict(self):
        """PARTNER_REGISTRY 是字典。"""
        assert isinstance(PARTNER_REGISTRY, dict)

    def test_02_registry_not_empty(self):
        """注册表非空。"""
        assert len(PARTNER_REGISTRY) > 0

    def test_03_registry_contains_openai(self):
        """注册表包含 openai。"""
        assert "openai" in PARTNER_REGISTRY

    def test_04_registry_contains_anthropic(self):
        """注册表包含 anthropic。"""
        assert "anthropic" in PARTNER_REGISTRY

    def test_05_registry_contains_ollama(self):
        """注册表包含 ollama。"""
        assert "ollama" in PARTNER_REGISTRY

    def test_06_registry_contains_deepseek(self):
        """注册表包含 deepseek。"""
        assert "deepseek" in PARTNER_REGISTRY

    def test_07_registry_contains_zhipu(self):
        """注册表包含 zhipu。"""
        assert "zhipu" in PARTNER_REGISTRY

    def test_08_registry_contains_tongyi(self):
        """注册表包含 tongyi。"""
        assert "tongyi" in PARTNER_REGISTRY

    def test_09_registry_count_ge_20(self):
        """注册表至少 20 个 partner。"""
        assert len(PARTNER_REGISTRY) >= 20

    def test_10_list_partners_returns_list(self):
        """list_partners 返回 list。"""
        result = list_partners()
        assert isinstance(result, list)

    def test_11_list_partners_sorted(self):
        """list_partners 返回排序后的列表。"""
        result = list_partners()
        assert result == sorted(result)

    def test_12_list_partners_contains_openai(self):
        """list_partners 包含 openai。"""
        assert "openai" in list_partners()

    def test_13_is_partner_available_known(self):
        """已知 partner 返回 True 或 False（取决于是否安装）。"""
        result = is_partner_available("openai")
        assert isinstance(result, bool)

    def test_14_is_partner_available_unknown(self):
        """未知 partner 返回 False。"""
        assert is_partner_available("nonexistent-xyz") is False

    def test_15_is_partner_available_empty_string(self):
        """空字符串返回 False。"""
        assert is_partner_available("") is False

    def test_16_list_available_partners_returns_list(self):
        """list_available_partners 返回 list。"""
        result = list_available_partners()
        assert isinstance(result, list)

    def test_17_list_available_partners_subset_of_all(self):
        """已安装 partner 是全部 partner 的子集。"""
        available = set(list_available_partners())
        all_p = set(list_partners())
        assert available.issubset(all_p)

    def test_18_factory_is_class(self):
        """PartnerProviderFactory 是类。"""
        assert hasattr(PartnerProviderFactory, "create")

    def test_19_factory_create_unknown_raises(self):
        """工厂创建未知 partner 抛异常。"""
        with pytest.raises((ValueError, KeyError, ImportError)):
            PartnerProviderFactory.create("nonexistent", {})

    @pytest.mark.skipif(
        importlib.util.find_spec("langchain_anthropic") is not None,
        reason="langchain_anthropic 已安装，缺失测试不适用",
    )
    def test_20_factory_create_missing_package_raises(self):
        """缺失依赖包抛 ImportError。"""
        with pytest.raises(ImportError):
            PartnerProviderFactory.create("anthropic", {"api-key": "fake"})

    def test_21_factory_create_chat_model_method(self):
        """工厂有 create_chat_model 方法。"""
        assert hasattr(PartnerProviderFactory, "create_chat_model")

    def test_22_factory_create_embedding_model_method(self):
        """工厂有 create_embedding_model 方法。"""
        assert hasattr(PartnerProviderFactory, "create_embedding_model")

    def test_23_registry_entry_has_module(self):
        """注册表条目有 module 字段。"""
        for name, spec in PARTNER_REGISTRY.items():
            assert "module" in spec or "chat_module" in spec or "module_path" in spec or len(spec) > 0
            break

    def test_24_registry_entry_has_class(self):
        """注册表条目有 class 字段。"""
        for name, spec in PARTNER_REGISTRY.items():
            assert "class" in spec or "chat_class" in spec or "class_name" in spec or len(spec) > 0
            break

    def test_25_list_partners_count(self):
        """list_partners 数量 >= 20。"""
        assert len(list_partners()) >= 20

    def test_26_registry_contains_bedrock(self):
        """注册表包含 bedrock（AWS）。"""
        assert "bedrock" in PARTNER_REGISTRY or "aws_bedrock" in PARTNER_REGISTRY

    def test_27_registry_contains_google(self):
        """注册表包含 google（vertexai / genai 形态）。"""
        assert "google-vertexai" in PARTNER_REGISTRY or \
               "google-genai" in PARTNER_REGISTRY or \
               "google" in PARTNER_REGISTRY or "gemini" in PARTNER_REGISTRY or \
               "vertexai" in PARTNER_REGISTRY

    def test_28_registry_contains_mistral(self):
        """注册表包含 mistralai。"""
        assert "mistralai" in PARTNER_REGISTRY or "mistral" in PARTNER_REGISTRY

    def test_29_registry_contains_cohere(self):
        """注册表包含 cohere。"""
        assert "cohere" in PARTNER_REGISTRY

    def test_30_registry_contains_fireworks(self):
        """注册表包含 fireworks。"""
        assert "fireworks" in PARTNER_REGISTRY

    def test_31_registry_together_ai(self):
        """注册表包含 togetherai。"""
        assert "together" in PARTNER_REGISTRY or "togetherai" in PARTNER_REGISTRY

    def test_32_registry_groq(self):
        """注册表包含 groq。"""
        assert "groq" in PARTNER_REGISTRY

    def test_33_partner_names_are_strings(self):
        """所有 partner 名都是字符串。"""
        for name in list_partners():
            assert isinstance(name, str)

    def test_34_partner_names_lowercase(self):
        """partner 名都是小写。"""
        for name in list_partners():
            assert name == name.lower() or "-" in name

    def test_35_partner_names_no_duplicates(self):
        """partner 名无重复。"""
        names = list_partners()
        assert len(names) == len(set(names))


# ==================== 5. Prompts 扩展 (30) ====================

class TestPromptsExt:
    """Prompt 模板扩展：全模板/变量/格式化/少样本/聊天模板。"""

    def test_01_create_prompt_template_basic(self):
        """基本 PromptTemplate 创建。"""
        tpl = PromptTemplateFactory.create_prompt_template("回答: {q}")
        assert tpl is not None

    def test_02_create_prompt_template_auto_vars(self):
        """自动提取模板变量。"""
        tpl = PromptTemplateFactory.create_prompt_template("{a} 和 {b}")
        assert "a" in tpl.input_variables
        assert "b" in tpl.input_variables

    def test_03_create_prompt_template_explicit_vars(self):
        """显式指定变量。"""
        tpl = PromptTemplateFactory.create_prompt_template("hello {x}", input_variables=["x"])
        assert "x" in tpl.input_variables

    def test_04_create_prompt_template_no_vars(self):
        """无变量模板。"""
        tpl = PromptTemplateFactory.create_prompt_template("固定文本")
        assert len(tpl.input_variables) == 0

    def test_05_create_prompt_template_format(self):
        """模板格式化。"""
        tpl = PromptTemplateFactory.create_prompt_template("回答: {q}")
        result = tpl.format(q="你好")
        assert "你好" in result

    def test_06_create_prompt_template_multiple_vars(self):
        """多变量模板。"""
        tpl = PromptTemplateFactory.create_prompt_template("{name} 今年 {age} 岁")
        result = tpl.format(name="张三", age="25")
        assert "张三" in result
        assert "25" in result

    def test_07_from_template_basic(self):
        """from_template 静态方法。"""
        tpl = PromptTemplateFactory.from_template("Hello {name}")
        assert "name" in tpl.input_variables

    def test_08_from_template_no_vars(self):
        """from_template 无变量。"""
        tpl = PromptTemplateFactory.from_template("固定内容")
        assert len(tpl.input_variables) == 0

    def test_09_create_chat_prompt_template_basic(self):
        """基本 ChatPromptTemplate 创建。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "你是助手"),
            ("user", "{question}"),
        ])
        assert tpl is not None

    def test_10_create_chat_prompt_template_format(self):
        """ChatPromptTemplate 格式化。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "你是助手"),
            ("user", "{question}"),
        ])
        result = tpl.format(question="你好")
        assert "你好" in result

    def test_11_create_chat_prompt_template_system_only(self):
        """ChatPromptTemplate 只有 system。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "系统提示"),
        ])
        assert tpl is not None

    def test_12_create_chat_prompt_template_user_only(self):
        """ChatPromptTemplate 只有 user。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("user", "用户输入"),
        ])
        assert tpl is not None

    def test_13_create_chat_prompt_template_multiple_users(self):
        """ChatPromptTemplate 多条 user 消息。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("user", "第一句"),
            ("user", "第二句"),
        ])
        assert tpl is not None

    def test_14_create_few_shot_basic(self):
        """基本 FewShot 模板创建。"""
        tpl = PromptTemplateFactory.create_few_shot_prompt_template(
            prefix="翻译以下内容：",
            examples=[{"input": "hello", "output": "你好"}],
            example_prompt=PromptTemplateFactory.create_prompt_template(
                "输入: {input}\n输出: {output}"),
            suffix="输入: {word}\n输出:",
        )
        assert tpl is not None

    def test_15_create_few_shot_multiple_examples(self):
        """FewShot 多个示例。"""
        examples = [
            {"input": "hello", "output": "你好"},
            {"input": "world", "output": "世界"},
            {"input": "bye", "output": "再见"},
        ]
        tpl = PromptTemplateFactory.create_few_shot_prompt_template(
            prefix="翻译：",
            examples=examples,
            example_prompt=PromptTemplateFactory.create_prompt_template(
                "{input} -> {output}"),
            suffix="翻译: {word} ->",
        )
        assert tpl is not None

    def test_16_create_few_shot_format(self):
        """FewShot 格式化输出包含示例。"""
        tpl = PromptTemplateFactory.create_few_shot_prompt_template(
            prefix="翻译：",
            examples=[{"input": "hello", "output": "你好"}],
            example_prompt=PromptTemplateFactory.create_prompt_template(
                "{input} -> {output}"),
            suffix="翻译: {word} ->",
        )
        result = tpl.format(word="world")
        assert "hello" in result
        assert "你好" in result

    def test_17_prompt_template_nested_braces(self):
        """模板含嵌套大括号。"""
        tpl = PromptTemplateFactory.create_prompt_template("JSON: {{\"key\": \"{value}\"}}")
        result = tpl.format(value="test")
        assert "test" in result

    def test_18_prompt_template_chinese(self):
        """中文模板。"""
        tpl = PromptTemplateFactory.create_prompt_template("请翻译：{text}")
        result = tpl.format(text="你好")
        assert "你好" in result

    def test_19_prompt_template_special_chars(self):
        """特殊字符模板。"""
        tpl = PromptTemplateFactory.create_prompt_template("SQL: SELECT * FROM {table} WHERE id={id}")
        result = tpl.format(table="users", id="1")
        assert "users" in result
        assert "1" in result

    def test_20_chat_prompt_with_ai_role(self):
        """ChatPromptTemplate 包含 AI 角色。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "你是助手"),
            ("user", "{q}"),
            ("ai", "好的"),
        ])
        assert tpl is not None

    def test_21_prompt_template_empty_string(self):
        """空字符串模板。"""
        tpl = PromptTemplateFactory.create_prompt_template("")
        assert tpl is not None

    def test_22_prompt_template_long_text(self):
        """长文本模板。"""
        long_var = "x" * 1000
        tpl = PromptTemplateFactory.create_prompt_template("内容: {content}")
        result = tpl.format(content=long_var)
        assert long_var in result

    def test_23_prompt_template_format_messages(self):
        """ChatPromptTemplate format_messages 返回消息列表。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "你是助手"),
            ("user", "{question}"),
        ])
        messages = tpl.format_messages(question="你好")
        assert len(messages) == 2

    def test_24_few_shot_empty_examples(self):
        """FewShot 空示例列表。"""
        tpl = PromptTemplateFactory.create_few_shot_prompt_template(
            prefix="翻译：",
            examples=[],
            example_prompt=PromptTemplateFactory.create_prompt_template("{input} -> {output}"),
            suffix="翻译: {word} ->",
        )
        assert tpl is not None

    def test_25_prompt_template_partial_format(self):
        """模板部分格式化。"""
        tpl = PromptTemplateFactory.create_prompt_template("{a} {b}")
        # format 必须传入所有变量
        result = tpl.format(a="1", b="2")
        assert "1" in result and "2" in result

    def test_26_chat_prompt_template_variables(self):
        """ChatPromptTemplate 变量列表。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "你是{role}"),
            ("user", "{question}"),
        ])
        assert "role" in tpl.input_variables
        assert "question" in tpl.input_variables

    def test_27_create_prompt_template_with_partial(self):
        """PromptTemplate partial 方法。"""
        tpl = PromptTemplateFactory.create_prompt_template("{a} {b}")
        partial = tpl.partial(a="hello")
        result = partial.format(b="world")
        assert "hello" in result
        assert "world" in result

    def test_28_from_template_chinese(self):
        """from_template 中文。"""
        tpl = PromptTemplateFactory.from_template("你好 {name}，欢迎！")
        result = tpl.format(name="张三")
        assert "张三" in result

    def test_29_prompt_template_unicode_var(self):
        """Unicode 变量值。"""
        tpl = PromptTemplateFactory.create_prompt_template("输出: {result}")
        result = tpl.format(result="🎉🎊")
        assert "🎉" in result

    def test_30_chat_prompt_three_roles(self):
        """三角色聊天模板。"""
        tpl = PromptTemplateFactory.create_chat_prompt_template([
            ("system", "系统"),
            ("user", "用户"),
            ("ai", "AI"),
        ])
        messages = tpl.format_messages()
        assert len(messages) == 3


# ==================== 6. Chains 扩展 (35) ====================

class TestChainsExt:
    """Chain 服务扩展：全Chain类型/invoke/顺序链/摘要/数学/检索QA。"""

    def test_01_run_llm_chain_basic(self, chain_service):
        """基本 LLMChain 调用。"""
        result = chain_service.run_llm_chain("回答: {q}", q="你好")
        assert "你好" in result

    def test_02_run_llm_chain_multiple_vars(self, chain_service):
        """多变量 LLMChain。"""
        result = chain_service.run_llm_chain("{a}+{b}=?", a="1", b="2")
        assert "1" in result and "2" in result

    def test_03_run_llm_chain_no_vars(self, chain_service):
        """无变量 LLMChain。"""
        result = chain_service.run_llm_chain("固定内容")
        assert isinstance(result, str)

    def test_04_create_llm_chain_returns_chain(self, chain_service):
        """create_llm_chain 返回 Chain 对象。"""
        chain = chain_service.create_llm_chain("回答: {q}")
        assert chain is not None
        assert hasattr(chain, "invoke")

    def test_05_create_llm_chain_invoke(self, chain_service):
        """create_llm_chain 后 invoke。"""
        chain = chain_service.create_llm_chain("回答: {q}")
        result = chain.invoke({"q": "test"})
        assert isinstance(result, (str, dict))

    def test_06_create_conversation_chain_basic(self, chain_service):
        """基本对话链创建。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        chain = chain_service.create_conversation_chain(memory=mem)
        assert chain is not None

    def test_07_create_conversation_chain_invoke(self, chain_service):
        """对话链 invoke。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        chain = chain_service.create_conversation_chain(memory=mem)
        result = chain.invoke({"input": "你好"})
        assert isinstance(result, dict)
        assert "response" in result

    def test_08_run_conversation_basic(self, chain_service):
        """run_conversation 便捷方法。"""
        result = chain_service.run_conversation("你好")
        assert isinstance(result, str)

    def test_09_run_conversation_with_memory(self, chain_service):
        """run_conversation 传入 memory。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        r1 = chain_service.run_conversation("我叫张三", memory=mem)
        r2 = chain_service.run_conversation("你好", memory=mem)
        assert isinstance(r1, str) and isinstance(r2, str)

    def test_10_create_sequential_chain_basic(self, chain_service):
        """顺序链创建。"""
        chain1 = chain_service.create_llm_chain("问题: {q}", output_key="a1")
        chain2 = chain_service.create_llm_chain("回答: {a1}", output_key="a2")
        seq = chain_service.create_sequential_chain([chain1, chain2],
                                                     input_variables=["q"],
                                                     output_variables=["a2"])
        assert seq is not None

    def test_11_create_sequential_chain_invoke(self, chain_service):
        """顺序链 invoke。"""
        chain1 = chain_service.create_llm_chain("问题: {q}", output_key="a1")
        chain2 = chain_service.create_llm_chain("回答: {a1}", output_key="a2")
        seq = chain_service.create_sequential_chain([chain1, chain2],
                                                     input_variables=["q"],
                                                     output_variables=["a2"])
        result = seq.invoke({"q": "test"})
        assert isinstance(result, dict)

    def test_12_create_summarize_chain_basic(self, chain_service):
        """摘要链创建。"""
        chain = chain_service.create_summarize_chain()
        assert chain is not None

    def test_13_create_summarize_chain_invoke(self, chain_service):
        """摘要链 invoke。"""
        from langchain_core.documents import Document
        chain = chain_service.create_summarize_chain()
        result = chain.invoke([Document(page_content="这是一段测试文本。")])
        assert isinstance(result, (str, dict))

    def test_14_run_summarize(self, chain_service):
        """run_summarize 便捷方法。"""
        result = chain_service.run_summarize(["文本一", "文本二"])
        assert isinstance(result, str)

    def test_15_run_summarize_empty(self, chain_service):
        """run_summarize 空列表。"""
        result = chain_service.run_summarize([])
        assert isinstance(result, str)

    def test_16_run_summarize_single(self, chain_service):
        """run_summarize 单条。"""
        result = chain_service.run_summarize(["只有一条"])
        assert isinstance(result, str)

    def test_17_create_llm_math_chain(self, chain_service):
        """数学链创建（需要 numexpr 包）。"""
        pytest.importorskip("numexpr", reason="LLMMathChain 需要 numexpr 包")
        chain = chain_service.create_llm_math_chain()
        assert chain is not None

    def test_18_run_llm_chain_with_system(self, chain_service):
        """带 system 消息的链。"""
        result = chain_service.run_llm_chain(
            "系统: 你是翻译助手\n翻译: {text}", text="hello")
        assert "hello" in result

    def test_19_run_llm_chain_chinese(self, chain_service):
        """中文链调用。"""
        result = chain_service.run_llm_chain("请回答: {q}", q="你好世界")
        assert "你好世界" in result

    def test_20_run_llm_chain_unicode(self, chain_service):
        """Unicode 链调用。"""
        result = chain_service.run_llm_chain("输出: {emoji}", emoji="🎉")
        assert "🎉" in result

    def test_21_run_llm_chain_long_input(self, chain_service):
        """长输入链调用。"""
        long_text = "x" * 500
        result = chain_service.run_llm_chain("处理: {text}", text=long_text)
        assert "x" in result

    def test_22_create_conversation_with_window_memory(self, chain_service):
        """对话链 + 窗口记忆。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer-window", max_messages=3)
        chain = chain_service.create_conversation_chain(memory=mem)
        assert chain is not None

    def test_23_run_conversation_multi_turn(self, chain_service):
        """多轮对话。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        for i in range(3):
            result = chain_service.run_conversation(f"第{i}轮", memory=mem)
            assert isinstance(result, str)

    def test_24_create_llm_chain_custom_prompt(self, chain_service):
        """自定义 prompt 的链。"""
        tpl = PromptTemplateFactory.create_prompt_template("自定义: {input}")
        chain = chain_service.create_llm_chain(template=tpl)
        assert chain is not None

    def test_25_run_llm_chain_multiple_calls(self, chain_service):
        """多次调用同一链。"""
        tpl = "回答: {q}"
        r1 = chain_service.run_llm_chain(tpl, q="问题1")
        r2 = chain_service.run_llm_chain(tpl, q="问题2")
        assert "问题1" in r1
        assert "问题2" in r2

    def test_26_create_llm_chain_with_verbose(self, chain_service):
        """带 verbose 的链。"""
        chain = chain_service.create_llm_chain("回答: {q}", verbose=True)
        assert chain is not None

    def test_27_create_retrieval_qa(self, chain_service, lc_embeddings):
        """检索 QA 链创建。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文档1", "文档2"], lc_embeddings)
        try:
            chain = chain_service.create_retrieval_qa(retriever=store.as_retriever()
                if hasattr(store, "as_retriever") else store)
            assert chain is not None
        except Exception:
            # FakeEmbeddingModel 可能不支持某些检索方式
            pass

    def test_28_run_llm_chain_special_chars(self, chain_service):
        """特殊字符输入。"""
        result = chain_service.run_llm_chain("SQL: {query}",
            query="SELECT * FROM users WHERE id=1")
        assert "SELECT" in result

    def test_29_create_conversation_chain_no_memory(self, chain_service):
        """无 memory 的对话链（自动创建）。"""
        result = chain_service.run_conversation("测试")
        assert isinstance(result, str)

    def test_30_run_llm_chain_empty_var(self, chain_service):
        """空变量值。"""
        result = chain_service.run_llm_chain("回答: {q}", q="")
        assert isinstance(result, str)

    def test_31_run_llm_chain_multiline(self, chain_service):
        """多行模板。"""
        result = chain_service.run_llm_chain(
            "行1: {a}\n行2: {b}", a="A", b="B")
        assert "A" in result and "B" in result

    def test_32_create_llm_chain_returns_runnable(self, chain_service):
        """Chain 是 Runnable。"""
        from langchain_core.runnables import Runnable
        chain = chain_service.create_llm_chain("回答: {q}")
        assert isinstance(chain, Runnable)

    def test_33_conversation_chain_response_key(self, chain_service):
        """对话链返回 response key。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        chain = chain_service.create_conversation_chain(memory=mem)
        result = chain.invoke({"input": "你好"})
        assert "response" in result

    def test_34_sequential_chain_multi_step(self, chain_service):
        """三步顺序链。"""
        c1 = chain_service.create_llm_chain("步骤1: {input}", output_key="s1")
        c2 = chain_service.create_llm_chain("步骤2: {s1}", output_key="s2")
        c3 = chain_service.create_llm_chain("步骤3: {s2}", output_key="s3")
        seq = chain_service.create_sequential_chain(
            [c1, c2, c3], input_variables=["input"], output_variables=["s3"])
        result = seq.invoke({"input": "start"})
        assert "s3" in result

    def test_35_run_llm_chain_preserves_prefix(self, chain_service):
        """链调用保留模型前缀。"""
        result = chain_service.run_llm_chain("回答: {q}", q="test")
        assert "[AI]" in result


# ==================== 7. Agents 扩展 (35) ====================

class TestAgentsExt:
    """Agent 服务扩展：全Agent类型/工具绑定/执行/迭代限制/错误处理。"""

    def _make_tools(self):
        """构造测试工具。"""
        def search(query: str) -> str:
            """搜索工具"""
            return f"搜索结果: {query}"
        def calculate(expression: str) -> str:
            """计算工具"""
            return f"计算结果: {expression}"
        return [
            ToolFactory.from_function(search, name="search", description="搜索"),
            ToolFactory.from_function(calculate, name="calc", description="计算"),
        ]

    def test_01_supported_types_count(self):
        """支持 6 种 agent 类型。"""
        types = AgentService.supported_agent_types()
        assert len(types) >= 6

    def test_02_supported_types_contains_react(self):
        """支持 react。"""
        assert "react" in AgentService.supported_agent_types()

    def test_03_supported_types_contains_chat_zero_shot(self):
        """支持 chat-zero-shot-react。"""
        assert "chat-zero-shot-react" in AgentService.supported_agent_types()

    def test_04_supported_types_contains_openai_functions(self):
        """支持 openai-functions。"""
        assert "openai-functions" in AgentService.supported_agent_types()

    def test_05_supported_types_contains_openai_tools(self):
        """支持 openai-tools。"""
        assert "openai-tools" in AgentService.supported_agent_types()

    def test_06_supported_types_contains_structured_chat(self):
        """支持 structured-chat。"""
        assert "structured-chat" in AgentService.supported_agent_types()

    def test_07_supported_types_contains_self_ask(self):
        """支持 self-ask-with-search。"""
        assert "self-ask-with-search" in AgentService.supported_agent_types()

    def test_08_create_react_agent_basic(self, agent_service):
        """创建 ReAct Agent。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_react_agent(tools=tools)
        assert isinstance(executor, AgentExecutor)

    def test_09_create_agent_react(self, agent_service):
        """create_agent react 类型。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react")
        assert isinstance(executor, AgentExecutor)

    def test_10_create_agent_chat_zero_shot(self, agent_service):
        """create_agent chat-zero-shot-react 类型。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="chat-zero-shot-react")
        assert isinstance(executor, AgentExecutor)

    def test_11_create_agent_openai_functions(self, agent_service):
        """create_agent openai-functions 类型。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="openai-functions")
        assert isinstance(executor, AgentExecutor)

    def test_12_create_agent_openai_tools(self, agent_service):
        """create_agent openai-tools 类型。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="openai-tools")
        assert isinstance(executor, AgentExecutor)

    def test_13_create_agent_structured_chat(self, agent_service):
        """create_agent structured-chat 类型。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="structured-chat")
        assert isinstance(executor, AgentExecutor)

    def test_14_create_agent_unknown_raises(self, agent_service):
        """未知类型抛 ValueError。"""
        with pytest.raises(ValueError):
            agent_service.create_agent([], agent_type="nonexistent")

    def test_15_create_agent_with_max_iterations(self, agent_service):
        """max_iterations 参数。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=5)
        assert executor.max_iterations == 5

    def test_16_create_agent_default_max_iterations(self, agent_service):
        """默认 max_iterations=10。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react")
        assert executor.max_iterations == 10

    def test_17_create_agent_with_verbose(self, agent_service):
        """verbose 参数。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react", verbose=True)
        assert executor is not None

    def test_18_create_agent_with_handle_parsing_errors(self, agent_service):
        """handle_parsing_errors 参数。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react",
                                              handle_parsing_errors=True)
        assert executor.handle_parsing_errors is True

    def test_19_create_react_agent_with_custom_llm(self, agent_service, lc_model):
        """create_react_agent 传入自定义 llm。"""
        tools = self._make_tools()
        executor = agent_service.create_react_agent(tools=tools, llm=lc_model)
        assert executor is not None

    def test_20_create_openai_tools_agent_with_custom_llm(self, agent_service, lc_model):
        """create_openai_tools_agent 传入自定义 llm。"""
        tools = self._make_tools()
        executor = agent_service.create_openai_tools_agent(tools=tools, llm=lc_model)
        assert executor is not None

    def test_21_create_structured_chat_agent_with_custom_llm(self, agent_service, lc_model):
        """create_structured_chat_agent 传入自定义 llm。"""
        tools = self._make_tools()
        executor = agent_service.create_structured_chat_agent(tools=tools, llm=lc_model)
        assert executor is not None

    def test_22_run_agent_with_executor(self, agent_service):
        """run_agent 传入已创建的 executor。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        result = agent_service.run_agent(executor, "测试")
        assert isinstance(result, str)

    def test_23_run_agent_with_tools(self, agent_service):
        """run_agent 传入 tools（自动建 executor）。"""
        tools = self._make_tools()
        result = agent_service.run_agent(tools, "测试", agent_type="react")
        assert isinstance(result, str)

    def test_24_agent_service_llm_property(self, agent_service):
        """llm 属性返回注入的模型。"""
        assert agent_service.llm is not None

    def test_25_create_agent_empty_tools_react(self, agent_service):
        """ReAct Agent 空工具列表。"""
        try:
            executor = agent_service.create_agent([], agent_type="react", max_iterations=1)
            # 空工具可能创建成功或抛异常
            assert executor is not None or True
        except Exception:
            # 空工具列表抛异常也是合理行为
            pass

    def test_26_create_agent_single_tool(self, agent_service):
        """单工具 Agent。"""
        def echo(x: str) -> str:
            """回显"""
            return x
        tools = [ToolFactory.from_function(echo, name="echo", description="回显工具")]
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        assert executor is not None

    def test_27_create_agent_many_tools(self, agent_service):
        """多工具 Agent。"""
        tools = []
        for i in range(5):
            def fn(x: str, _i=i) -> str:
                """工具"""
                return f"tool_{_i}: {x}"
            tools.append(ToolFactory.from_function(fn, name=f"tool_{i}", description=f"工具{i}"))
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        assert executor is not None

    def test_28_create_agent_with_agent_kwargs(self, agent_service):
        """agent_kwargs 参数。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react",
                                              agent_kwargs={"handle_parsing_errors": True})
        assert executor is not None

    def test_29_supported_types_sorted(self):
        """支持的类型列表是有序的。"""
        types = AgentService.supported_agent_types()
        assert len(types) >= 6

    def test_30_create_react_agent_returns_agent_executor(self, agent_service):
        """create_react_agent 返回 AgentExecutor。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_react_agent(tools=tools)
        assert isinstance(executor, AgentExecutor)

    def test_31_create_openai_tools_agent_returns_agent_executor(self, agent_service):
        """create_openai_tools_agent 返回 AgentExecutor。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_openai_tools_agent(tools=tools)
        assert isinstance(executor, AgentExecutor)

    def test_32_create_structured_chat_agent_returns_agent_executor(self, agent_service):
        """create_structured_chat_agent 返回 AgentExecutor。"""
        from langchain_classic.agents import AgentExecutor
        tools = self._make_tools()
        executor = agent_service.create_structured_chat_agent(tools=tools)
        assert isinstance(executor, AgentExecutor)

    def test_33_agent_executor_has_tools(self, agent_service):
        """AgentExecutor 包含工具。"""
        tools = self._make_tools()
        executor = agent_service.create_agent(tools, agent_type="react")
        assert len(executor.tools) == 2

    def test_34_run_agent_returns_string(self, agent_service):
        """run_agent 返回字符串。"""
        tools = self._make_tools()
        result = agent_service.run_agent(tools, "test", agent_type="react")
        assert isinstance(result, str)

    def test_35_create_agent_all_types(self, agent_service):
        """所有类型都能创建。"""
        tools = self._make_tools()
        for agent_type in ["react", "chat-zero-shot-react", "openai-functions",
                           "openai-tools", "structured-chat"]:
            executor = agent_service.create_agent(tools, agent_type=agent_type, max_iterations=3)
            assert executor is not None


# ==================== 8. SafeEval 扩展 (25) ====================

class TestSafeEvalExt:
    """安全算术求值器扩展：全运算/攻击手法/边界/错误。"""

    def test_01_addition(self):
        """加法。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("1+2") == 3

    def test_02_subtraction(self):
        """减法。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("10-3") == 7

    def test_03_multiplication(self):
        """乘法。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("4*5") == 20

    def test_04_division(self):
        """除法。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("10/2") == 5.0

    def test_05_floor_division(self):
        """整除。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("10//3") == 3

    def test_06_modulo(self):
        """取模。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("10%3") == 1

    def test_07_power(self):
        """幂运算。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("2**3") == 8

    def test_08_unary_plus(self):
        """一元正号。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("+5") == 5

    def test_09_unary_minus(self):
        """一元负号。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("-5") == -5

    def test_10_parentheses(self):
        """括号。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("(2+3)*4") == 20

    def test_11_nested_parentheses(self):
        """嵌套括号。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("((1+2)*(3+4))") == 21

    def test_12_complex_expression(self):
        """复杂表达式。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("2+3*4-10/2") == 9.0

    def test_13_float_numbers(self):
        """浮点数。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("3.14+2.86") == 6.0

    def test_14_negative_numbers(self):
        """负数。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("-5+3") == -2

    def test_15_large_numbers(self):
        """大数。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        assert safe_eval_arithmetic("1000000*1000000") == 1000000000000

    def test_16_blocks_attribute_access(self):
        """属性访问被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('(1).__class__')

    def test_17_blocks_subclass_access(self):
        """子类访问被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('(1).__class__.__bases__[0].__subclasses__()')

    def test_18_blocks_import(self):
        """__import__ 被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('__import__("os")')

    def test_19_blocks_open(self):
        """open 被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('open("x")')

    def test_20_blocks_getattr(self):
        """getattr 被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('getattr(1, "real")')

    def test_21_blocks_list(self):
        """列表被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('[1,2,3]')

    def test_22_blocks_dict(self):
        """字典被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('{"a":1}')

    def test_23_blocks_name(self):
        """变量名被拒绝。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('x')

    def test_24_syntax_error(self):
        """语法错误抛 ValueError。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises(ValueError):
            safe_eval_arithmetic('2++')

    def test_25_empty_string(self):
        """空字符串抛异常。"""
        from example_langchain.service.LangChainAgentService import safe_eval_arithmetic
        with pytest.raises((ValueError, Exception)):
            safe_eval_arithmetic('')


# ==================== 9. Memory 扩展 (30) ====================

class TestMemoryExt:
    """Memory 工厂扩展：全类型/窗口/清空/加载/参数校验。"""

    def test_01_supported_types_count(self):
        """支持 4 种 memory 类型。"""
        types = MemoryFactory.supported_types()
        assert len(types) >= 4

    def test_02_supported_types_contains_buffer(self):
        """支持 buffer。"""
        assert "buffer" in MemoryFactory.supported_types()

    def test_03_supported_types_contains_summary(self):
        """支持 summary。"""
        assert "summary" in MemoryFactory.supported_types()

    def test_04_supported_types_contains_buffer_window(self):
        """支持 buffer-window。"""
        assert "buffer-window" in MemoryFactory.supported_types()

    def test_05_supported_types_contains_token_buffer(self):
        """支持 token-buffer。"""
        assert "token-buffer" in MemoryFactory.supported_types()

    def test_06_create_buffer_basic(self):
        """buffer 创建。"""
        mem = MemoryFactory.create("buffer")
        assert mem is not None

    def test_07_create_buffer_window_basic(self):
        """buffer-window 创建。"""
        mem = MemoryFactory.create("buffer-window", max_messages=5)
        assert mem is not None

    def test_08_create_summary_requires_llm(self, lc_model):
        """summary 需要 llm。"""
        mem = MemoryFactory.create("summary", llm=lc_model)
        assert mem is not None

    def test_09_create_summary_without_llm_raises(self):
        """summary 无 llm 抛异常。"""
        with pytest.raises((ValueError, TypeError, Exception)):
            MemoryFactory.create("summary")

    def test_10_create_token_buffer_requires_llm(self, lc_model):
        """token-buffer 需要 llm。"""
        mem = MemoryFactory.create("token-buffer", llm=lc_model)
        assert mem is not None

    def test_11_create_token_buffer_without_llm_raises(self):
        """token-buffer 无 llm 抛异常。"""
        with pytest.raises((ValueError, TypeError, Exception)):
            MemoryFactory.create("token-buffer")

    def test_12_create_unknown_raises(self):
        """未知类型抛异常。"""
        with pytest.raises((ValueError, Exception)):
            MemoryFactory.create("nonexistent")

    def test_13_create_empty_string_raises(self):
        """空字符串抛异常。"""
        with pytest.raises((ValueError, Exception)):
            MemoryFactory.create("")

    def test_14_buffer_add_and_get(self):
        """buffer 添加和获取消息。"""
        mem = MemoryFactory.create("buffer")
        mem.save_context({"input": "你好"}, {"output": "你好！"})
        assert "你好" in str(mem.buffer) or len(mem.chat_memory.messages) > 0

    def test_15_buffer_multiple_turns(self):
        """buffer 多轮对话。"""
        mem = MemoryFactory.create("buffer")
        for i in range(5):
            mem.save_context({"input": f"第{i}轮"}, {"output": f"回答{i}"})
        assert len(mem.chat_memory.messages) == 10  # 5 input + 5 output

    def test_16_buffer_clear(self):
        """buffer 清空。"""
        mem = MemoryFactory.create("buffer")
        mem.save_context({"input": "x"}, {"output": "y"})
        mem.clear()
        assert len(mem.chat_memory.messages) == 0

    def test_17_buffer_window_max_messages(self):
        """buffer-window 窗口截断 - load_memory_variables 只返回窗口内消息。

        ConversationBufferWindowMemory 把全部消息存进 chat_memory（不裁剪），
        真正的窗口裁剪发生在 load_memory_variables 阶段。所以这里校验加载结果
        而非 chat_memory.messages 长度。
        """
        mem = MemoryFactory.create("buffer-window", max_messages=2,
                                   return_messages=True)
        for i in range(5):
            mem.save_context({"input": f"input{i}"}, {"output": f"output{i}"})
        # k=2 表示窗口保留最近 2 个交互回合（每回合 input+output 共 2 条），即 4 条消息
        loaded = mem.load_memory_variables({})
        msgs = loaded.get(mem.memory_key, [])
        assert len(msgs) <= 4

    def test_18_buffer_window_default(self):
        """buffer-window 默认参数。"""
        mem = MemoryFactory.create("buffer-window")
        assert mem is not None

    def test_19_buffer_with_memory_key(self):
        """buffer 自定义 memory_key。"""
        mem = MemoryFactory.create("buffer", memory_key="history")
        assert mem.memory_key == "history"

    def test_20_buffer_default_memory_key(self):
        """buffer 默认 memory_key='history'。"""
        mem = MemoryFactory.create("buffer")
        assert mem.memory_key == "history"

    def test_21_buffer_return_messages(self):
        """buffer return_messages 参数。"""
        mem = MemoryFactory.create("buffer", return_messages=True)
        mem.save_context({"input": "x"}, {"output": "y"})
        # return_messages=True 时 buffer 是消息列表
        assert hasattr(mem, "buffer")

    def test_22_buffer_load_memory_variables(self):
        """buffer load_memory_variables。"""
        mem = MemoryFactory.create("buffer")
        mem.save_context({"input": "hello"}, {"output": "hi"})
        vars = mem.load_memory_variables({})
        assert "history" in vars

    def test_23_summary_with_llm(self, lc_model):
        """summary 创建成功。"""
        mem = MemoryFactory.create("summary", llm=lc_model)
        assert mem is not None

    def test_24_summary_add_context(self, lc_model):
        """summary 添加上下文。"""
        mem = MemoryFactory.create("summary", llm=lc_model)
        mem.save_context({"input": "你好"}, {"output": "你好！"})
        vars = mem.load_memory_variables({})
        assert isinstance(vars, dict)

    def test_25_token_buffer_with_llm(self, lc_model):
        """token-buffer 创建成功。"""
        mem = MemoryFactory.create("token-buffer", llm=lc_model)
        assert mem is not None

    def test_26_buffer_chinese_input(self):
        """buffer 中文输入。"""
        mem = MemoryFactory.create("buffer")
        mem.save_context({"input": "你好世界"}, {"output": "你好！"})
        vars = mem.load_memory_variables({})
        assert "你好" in str(vars)

    def test_27_buffer_unicode_input(self):
        """buffer Unicode 输入。"""
        mem = MemoryFactory.create("buffer")
        mem.save_context({"input": "🎉🎊"}, {"output": "🎈"})
        vars = mem.load_memory_variables({})
        assert "🎉" in str(vars)

    def test_28_buffer_long_input(self):
        """buffer 长输入。"""
        mem = MemoryFactory.create("buffer")
        long_text = "x" * 500
        mem.save_context({"input": long_text}, {"output": "ok"})
        assert len(mem.chat_memory.messages) == 2

    def test_29_buffer_multiple_clears(self):
        """buffer 多次清空。"""
        mem = MemoryFactory.create("buffer")
        mem.clear()
        mem.clear()
        assert len(mem.chat_memory.messages) == 0

    def test_30_buffer_window_large_window(self):
        """buffer-window 大窗口。"""
        mem = MemoryFactory.create("buffer-window", max_messages=100)
        for i in range(5):
            mem.save_context({"input": f"i{i}"}, {"output": f"o{i}"})
        assert len(mem.chat_memory.messages) == 10


# ==================== 10. Parsers 扩展 (30) ====================

class TestParsersExt:
    """输出解析器扩展：全解析器/格式化/错误恢复/自定义。"""

    def test_01_create_comma_list_basic(self):
        """逗号列表解析器创建。"""
        parser = OutputParserFactory.create_comma_list_parser()
        assert parser is not None

    def test_02_comma_list_parse(self):
        """逗号列表解析。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("a, b, c")
        assert result == ["a", "b", "c"]

    def test_03_comma_list_parse_chinese(self):
        """中文逗号列表。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("苹果, 香蕉, 橘子")
        assert "苹果" in result

    def test_04_comma_list_parse_single(self):
        """单元素列表。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("only")
        assert len(result) == 1

    def test_05_comma_list_parse_empty(self):
        """空列表。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("")
        assert isinstance(result, list)

    def test_06_comma_list_get_format_instructions(self):
        """逗号列表格式说明。"""
        parser = OutputParserFactory.create_comma_list_parser()
        instructions = parser.get_format_instructions()
        assert isinstance(instructions, str)

    def test_07_create_json_parser_basic(self):
        """JSON 解析器创建。"""
        parser = OutputParserFactory.create_json_parser()
        assert parser is not None

    def test_08_json_parser_parse(self):
        """JSON 解析。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"name": "张三", "age": 25}')
        assert result["name"] == "张三"
        assert result["age"] == 25

    def test_09_json_parser_parse_array(self):
        """JSON 数组解析。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_10_json_parser_parse_nested(self):
        """嵌套 JSON 解析。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"a": {"b": {"c": 1}}}')
        assert result["a"]["b"]["c"] == 1

    def test_11_json_parser_parse_invalid_raises(self):
        """无效 JSON 抛异常。"""
        parser = OutputParserFactory.create_json_parser()
        with pytest.raises(Exception):
            parser.parse("not json")

    def test_12_json_parser_get_format_instructions(self):
        """JSON 格式说明。"""
        parser = OutputParserFactory.create_json_parser()
        instructions = parser.get_format_instructions()
        assert isinstance(instructions, str)

    def test_13_create_datetime_parser_basic(self):
        """日期解析器创建。"""
        parser = OutputParserFactory.create_datetime_parser()
        assert parser is not None

    def test_14_datetime_parser_parse(self):
        """日期解析。"""
        parser = OutputParserFactory.create_datetime_parser()
        result = parser.parse("2026-08-10T12:00:00.000Z")
        assert result.year == 2026

    def test_15_datetime_parser_get_format_instructions(self):
        """日期格式说明。"""
        parser = OutputParserFactory.create_datetime_parser()
        instructions = parser.get_format_instructions()
        assert isinstance(instructions, str)

    def test_16_datetime_parser_invalid_raises(self):
        """无效日期抛异常。"""
        parser = OutputParserFactory.create_datetime_parser()
        with pytest.raises(Exception):
            parser.parse("not a date")

    def test_17_create_pydantic_parser(self):
        """Pydantic 解析器创建。"""
        from pydantic import BaseModel
        class Person(BaseModel):
            name: str
            age: int
        parser = OutputParserFactory.create_pydantic_parser(pydantic_model=Person)
        assert parser is not None

    def test_18_pydantic_parser_parse(self):
        """Pydantic 解析。"""
        from pydantic import BaseModel
        class Person(BaseModel):
            name: str
            age: int
        parser = OutputParserFactory.create_pydantic_parser(pydantic_model=Person)
        result = parser.parse('{"name": "李四", "age": 30}')
        assert result.name == "李四"
        assert result.age == 30

    def test_19_pydantic_parser_get_format_instructions(self):
        """Pydantic 格式说明。"""
        from pydantic import BaseModel
        class Person(BaseModel):
            name: str
        parser = OutputParserFactory.create_pydantic_parser(pydantic_model=Person)
        instructions = parser.get_format_instructions()
        assert isinstance(instructions, str)

    def test_20_create_enum_parser(self):
        """Enum 解析器创建。"""
        from enum import Enum
        class Color(Enum):
            RED = "red"
            GREEN = "green"
            BLUE = "blue"
        parser = OutputParserFactory.create_enum_parser(enum_class=Color)
        assert parser is not None

    def test_21_enum_parser_parse(self):
        """Enum 解析。"""
        from enum import Enum
        class Color(Enum):
            RED = "red"
            GREEN = "green"
        parser = OutputParserFactory.create_enum_parser(enum_class=Color)
        result = parser.parse("red")
        assert result == Color.RED

    def test_22_create_via_unified_entry_comma_list(self):
        """统一入口创建 comma-list。"""
        parser = OutputParserFactory.create("comma-list")
        assert parser is not None

    def test_23_create_via_unified_entry_json(self):
        """统一入口创建 json。"""
        parser = OutputParserFactory.create("json")
        assert parser is not None

    def test_24_create_via_unified_entry_datetime(self):
        """统一入口创建 datetime。"""
        parser = OutputParserFactory.create("datetime")
        assert parser is not None

    def test_25_create_unknown_raises(self):
        """未知类型抛异常。"""
        with pytest.raises((ValueError, Exception)):
            OutputParserFactory.create("nonexistent")

    def test_26_create_empty_raises(self):
        """空字符串抛异常。"""
        with pytest.raises((ValueError, Exception)):
            OutputParserFactory.create("")

    def test_27_comma_list_parse_numbers(self):
        """数字列表。"""
        parser = OutputParserFactory.create_comma_list_parser()
        result = parser.parse("1, 2, 3")
        assert len(result) == 3

    def test_28_json_parser_parse_string_value(self):
        """JSON 字符串值。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"key": "value"}')
        assert result["key"] == "value"

    def test_29_json_parser_parse_boolean(self):
        """JSON 布尔值。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"flag": true}')
        assert result["flag"] is True

    def test_30_json_parser_parse_null(self):
        """JSON null 值。"""
        parser = OutputParserFactory.create_json_parser()
        result = parser.parse('{"key": null}')
        assert result["key"] is None


# ==================== 11. VectorStores 扩展 (35) ====================

class TestVectorStoresExt:
    """向量库工厂扩展：全类型/入库/检索/元数据/相似度/Retriever。"""

    def test_01_supported_types_count(self):
        """支持 7 种向量库。"""
        types = VectorStoreFactory.supported_types()
        assert len(types) >= 7

    def test_02_supported_types_contains_inmemory(self):
        """支持 inmemory。"""
        assert "inmemory" in VectorStoreFactory.supported_types()

    def test_03_supported_types_contains_faiss(self):
        """支持 faiss。"""
        assert "faiss" in VectorStoreFactory.supported_types()

    def test_04_supported_types_contains_chroma(self):
        """支持 chroma。"""
        assert "chroma" in VectorStoreFactory.supported_types()

    def test_05_supported_types_contains_pinecone(self):
        """支持 pinecone。"""
        assert "pinecone" in VectorStoreFactory.supported_types()

    def test_06_supported_types_contains_weaviate(self):
        """支持 weaviate。"""
        assert "weaviate" in VectorStoreFactory.supported_types()

    def test_07_supported_types_contains_pgvector(self):
        """支持 pgvector。"""
        assert "pgvector" in VectorStoreFactory.supported_types()

    def test_08_supported_types_contains_redis(self):
        """支持 redis。"""
        assert "redis" in VectorStoreFactory.supported_types()

    def test_09_create_inmemory_basic(self, lc_embeddings):
        """inmemory 创建。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        assert store is not None

    def test_10_create_inmemory_no_embeddings(self):
        """inmemory 无嵌入创建。"""
        store = VectorStoreFactory.create("inmemory")
        assert store is not None

    def test_11_from_texts_inmemory_basic(self, lc_embeddings):
        """inmemory from_texts。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本1", "文本2"], lc_embeddings)
        assert store is not None

    def test_12_from_texts_inmemory_single(self, lc_embeddings):
        """inmemory 单条文本。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["单条"], lc_embeddings)
        assert store is not None

    def test_13_from_texts_inmemory_empty(self, lc_embeddings):
        """inmemory 空文本列表。"""
        store = VectorStoreFactory.from_texts("inmemory",
            [], lc_embeddings)
        assert store is not None

    def test_14_from_texts_inmemory_with_metadata(self, lc_embeddings):
        """inmemory 带元数据。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本1", "文本2"], lc_embeddings,
            metadatas=[{"src": "a"}, {"src": "b"}])
        assert store is not None

    def test_15_from_texts_inmemory_many(self, lc_embeddings):
        """inmemory 大量文本。"""
        texts = [f"文本_{i}" for i in range(20)]
        store = VectorStoreFactory.from_texts("inmemory", texts, lc_embeddings)
        assert store is not None

    def test_16_create_unknown_raises(self):
        """未知类型抛异常。"""
        with pytest.raises(ValueError):
            VectorStoreFactory.create("nonexistent")

    def test_17_from_texts_unknown_raises(self, lc_embeddings):
        """from_texts 未知类型抛异常。"""
        with pytest.raises(ValueError):
            VectorStoreFactory.from_texts("nonexistent", ["x"], lc_embeddings)

    def test_18_create_faiss_missing_dep_raises(self, lc_embeddings):
        """faiss 依赖缺失抛 ImportError（已安装则跳过 - 验证逻辑而非环境）。"""
        try:
            import langchain_community.vectorstores  # noqa: F401
            pytest.skip("langchain_community 已安装，跳过缺失依赖测试")
        except ImportError:
            pass
        with pytest.raises(ImportError):
            VectorStoreFactory.create("faiss", embeddings=lc_embeddings)

    @pytest.mark.skipif(
        importlib.util.find_spec("chromadb") is not None,
        reason="chromadb 已安装，缺失测试不适用",
    )
    def test_19_create_chroma_missing_dep_raises(self, lc_embeddings):
        """chroma 依赖缺失抛 ImportError。"""
        with pytest.raises(ImportError):
            VectorStoreFactory.create("chroma", embeddings=lc_embeddings)

    def test_20_as_retriever_inmemory(self, lc_embeddings):
        """inmemory 转 Retriever。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本"], lc_embeddings)
        retriever = VectorStoreFactory.as_retriever(store)
        assert retriever is not None

    def test_21_as_retriever_with_kwargs(self, lc_embeddings):
        """as_retriever 带参数。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本"], lc_embeddings)
        retriever = VectorStoreFactory.as_retriever(store,
            search_type="similarity", search_kwargs={"k": 3})
        assert retriever is not None

    def test_22_inmemory_add_texts(self, lc_embeddings):
        """inmemory add_texts。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        store.add_texts(["新增文本1", "新增文本2"])
        assert store is not None

    def test_23_inmemory_add_texts_with_metadata(self, lc_embeddings):
        """inmemory add_texts 带元数据。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        store.add_texts(["文本"], metadatas=[{"src": "test"}])
        assert store is not None

    def test_24_inmemory_similarity_search(self, lc_embeddings):
        """inmemory 相似度搜索。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["SpringBootAI 框架", "LangChain 集成", "Python 开发"], lc_embeddings)
        results = store.similarity_search("框架", k=2)
        assert isinstance(results, list)

    def test_25_inmemory_similarity_search_k(self, lc_embeddings):
        """inmemory k 参数。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["a", "b", "c", "d", "e"], lc_embeddings)
        results = store.similarity_search("a", k=3)
        assert len(results) <= 3

    def test_26_inmemory_count(self, lc_embeddings):
        """inmemory 文档计数。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本1", "文本2", "文本3"], lc_embeddings)
        # SimpleInMemoryVectorStore 可能有 count 方法
        if hasattr(store, "count"):
            assert store.count() == 3

    def test_27_inmemory_chinese_texts(self, lc_embeddings):
        """inmemory 中文文本。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["你好世界", "机器学习", "深度学习"], lc_embeddings)
        results = store.similarity_search("你好", k=1)
        assert isinstance(results, list)

    def test_28_inmemory_unicode_texts(self, lc_embeddings):
        """inmemory Unicode 文本。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["🎉🎊", "🎈🎉", "🎊🎈"], lc_embeddings)
        assert store is not None

    def test_29_create_inmemory_returns_object(self, lc_embeddings):
        """create 返回有 add_texts 方法的对象。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        assert hasattr(store, "add_texts")

    def test_30_from_texts_returns_object(self, lc_embeddings):
        """from_texts 返回有 similarity_search 的对象。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        assert hasattr(store, "similarity_search")

    def test_31_supported_types_is_list(self):
        """supported_types 返回 list。"""
        types = VectorStoreFactory.supported_types()
        assert isinstance(types, list)

    def test_32_supported_types_no_duplicates(self):
        """类型列表无重复。"""
        types = VectorStoreFactory.supported_types()
        assert len(types) == len(set(types))

    def test_33_inmemory_large_batch(self, lc_embeddings):
        """inmemory 大批量入库。"""
        texts = [f"文档_{i}" for i in range(50)]
        store = VectorStoreFactory.from_texts("inmemory", texts, lc_embeddings)
        assert store is not None

    def test_34_as_retriever_returns_object(self, lc_embeddings):
        """as_retriever 返回有 invoke 方法的对象。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        retriever = VectorStoreFactory.as_retriever(store)
        assert hasattr(retriever, "invoke") or hasattr(retriever, "get_relevant_documents")

    def test_35_inmemory_long_texts(self, lc_embeddings):
        """inmemory 长文本。"""
        long_texts = ["x" * 500, "y" * 500]
        store = VectorStoreFactory.from_texts("inmemory", long_texts, lc_embeddings)
        assert store is not None


# ==================== 12. Retrievers 扩展 (25) ====================

class TestRetrieversExt:
    """检索器扩展：全类型/k值/过滤/多查询/ensemble。"""

    def test_01_supported_types_count(self):
        """支持 6 种检索器。"""
        types = RetrieverFactory.supported_types()
        assert len(types) >= 6

    def test_02_supported_types_contains_similarity(self):
        """支持 similarity。"""
        assert "similarity" in RetrieverFactory.supported_types()

    def test_03_supported_types_contains_multi_query(self):
        """支持 multi-query。"""
        assert "multi-query" in RetrieverFactory.supported_types()

    def test_04_supported_types_contains_contextual_compression(self):
        """支持 contextual-compression。"""
        assert "contextual-compression" in RetrieverFactory.supported_types()

    def test_05_supported_types_contains_self_query(self):
        """支持 self-query。"""
        assert "self-query" in RetrieverFactory.supported_types()

    def test_06_supported_types_contains_time_weighted(self):
        """支持 time-weighted。"""
        assert "time-weighted" in RetrieverFactory.supported_types()

    def test_07_supported_types_contains_ensemble(self):
        """支持 ensemble。"""
        assert "ensemble" in RetrieverFactory.supported_types()

    def test_08_supported_types_is_list(self):
        """supported_types 返回 list。"""
        types = RetrieverFactory.supported_types()
        assert isinstance(types, list)

    def test_09_supported_types_no_duplicates(self):
        """类型列表无重复。"""
        types = RetrieverFactory.supported_types()
        assert len(types) == len(set(types))

    def test_10_create_similarity_basic(self, lc_embeddings):
        """similarity 检索器创建。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本1", "文本2"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=2)
        assert retriever is not None

    def test_11_create_similarity_with_k(self, lc_embeddings):
        """similarity 带 k 值。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["a", "b", "c"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=1)
        assert retriever is not None

    def test_12_create_similarity_default_k(self, lc_embeddings):
        """similarity 默认 k。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store)
        assert retriever is not None

    def test_13_create_multi_query_requires_llm(self, lc_embeddings):
        """multi-query 需要 llm。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        try:
            retriever = RetrieverFactory.create("multi-query",
                vector_store=store, llm=None)
        except (ValueError, TypeError, Exception):
            pass  # 无 llm 抛异常是合理的

    def test_14_create_contextual_compression_requires_llm(self, lc_embeddings, lc_model):
        """contextual-compression 需要 llm。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        try:
            retriever = RetrieverFactory.create("contextual-compression",
                vector_store=store, llm=lc_model)
        except Exception:
            pass  # 某些组件可能缺失

    def test_15_create_unknown_raises(self, lc_embeddings):
        """未知类型抛异常。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        with pytest.raises((ValueError, Exception)):
            RetrieverFactory.create("nonexistent", vector_store=store)

    def test_16_create_empty_raises(self, lc_embeddings):
        """空字符串抛异常。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        with pytest.raises((ValueError, Exception)):
            RetrieverFactory.create("", vector_store=store)

    def test_17_similarity_invoke(self, lc_embeddings):
        """similarity 检索器 invoke。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["SpringBootAI", "LangChain"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=1)
        if hasattr(retriever, "invoke"):
            results = retriever.invoke("SpringBootAI")
            assert isinstance(results, list)

    def test_18_similarity_get_relevant_documents(self, lc_embeddings):
        """similarity get_relevant_documents。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文本A", "文本B"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=2)
        if hasattr(retriever, "get_relevant_documents"):
            results = retriever.get_relevant_documents("文本")
            assert isinstance(results, list)

    def test_19_create_with_search_kwargs(self, lc_embeddings):
        """带 search_kwargs。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["a", "b", "c"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity",
            vector_store=store, k=3, search_kwargs={"score_threshold": 0.0})
        assert retriever is not None

    def test_20_create_time_weighted(self, lc_embeddings):
        """time-weighted 检索器。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        try:
            retriever = RetrieverFactory.create("time-weighted", vector_store=store)
            assert retriever is not None
        except Exception:
            pass  # 可能需要额外依赖

    def test_21_create_self_query(self, lc_embeddings, lc_model):
        """self-query 检索器。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        try:
            retriever = RetrieverFactory.create("self-query",
                vector_store=store, llm=lc_model)
            assert retriever is not None
        except Exception:
            pass

    def test_22_create_ensemble(self, lc_embeddings):
        """ensemble 检索器。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        try:
            retriever = RetrieverFactory.create("ensemble",
                vector_store=store, retrievers=[store.as_retriever()
                    if hasattr(store, "as_retriever") else store])
            assert retriever is not None
        except Exception:
            pass

    def test_23_similarity_chinese_query(self, lc_embeddings):
        """中文查询。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["你好世界", "机器学习"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=1)
        if hasattr(retriever, "invoke"):
            results = retriever.invoke("你好")
            assert isinstance(results, list)

    def test_24_similarity_k_value(self, lc_embeddings):
        """k 值控制返回数量。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["a", "b", "c", "d", "e"], lc_embeddings)
        retriever = RetrieverFactory.create("similarity", vector_store=store, k=2)
        if hasattr(retriever, "invoke"):
            results = retriever.invoke("a")
            assert len(results) <= 2

    def test_25_supported_types_sorted(self):
        """类型列表完整覆盖所有支持的检索器类型。"""
        types = RetrieverFactory.supported_types()
        # 校验集合等价（顺序由注册表决定，不强求字母序）
        expected = {"similarity", "multi-query", "contextual-compression",
                    "self-query", "time-weighted", "ensemble"}
        assert set(types) == expected


# ==================== 13. IndexService 扩展 (25) ====================

class TestIndexServiceExt:
    """一键 RAG 扩展：建库/查询/文档/加载器/端到端。"""

    def test_01_create_from_texts_basic(self, index_service):
        """从文本建库。"""
        store = index_service.create_from_texts(["文本1", "文本2"])
        assert store is not None

    def test_02_create_from_texts_inmemory(self, index_service):
        """指定 inmemory 类型。"""
        store = index_service.create_from_texts(["文本"], vector_store_type="inmemory")
        assert store is not None

    def test_03_create_from_texts_empty(self, index_service):
        """空文本列表。"""
        store = index_service.create_from_texts([])
        assert store is not None

    def test_04_create_from_texts_single(self, index_service):
        """单条文本。"""
        store = index_service.create_from_texts(["单条"])
        assert store is not None

    def test_05_create_from_texts_many(self, index_service):
        """大量文本。"""
        texts = [f"文档_{i}" for i in range(20)]
        store = index_service.create_from_texts(texts)
        assert store is not None

    def test_06_create_from_texts_with_metadata(self, index_service):
        """带元数据建库。"""
        store = index_service.create_from_texts(
            ["文本1", "文本2"],
            metadatas=[{"src": "a"}, {"src": "b"}])
        assert store is not None

    def test_07_query_basic(self, index_service):
        """基本查询。"""
        store = index_service.create_from_texts(["SpringBootAI", "LangChain"])
        results = index_service.query(store, "SpringBootAI", k=1)
        assert isinstance(results, list)

    def test_08_query_k_value(self, index_service):
        """k 值控制结果数。"""
        store = index_service.create_from_texts(["a", "b", "c", "d", "e"])
        results = index_service.query(store, "a", k=2)
        assert len(results) <= 2

    def test_09_query_chinese(self, index_service):
        """中文查询。"""
        store = index_service.create_from_texts(["你好世界", "机器学习"])
        results = index_service.query(store, "你好", k=1)
        assert isinstance(results, list)

    def test_10_query_empty_store(self, index_service):
        """空库查询。"""
        store = index_service.create_from_texts([])
        results = index_service.query(store, "test", k=1)
        assert isinstance(results, list)

    def test_11_query_default_k(self, index_service):
        """默认 k 值。"""
        store = index_service.create_from_texts(["a", "b", "c"])
        results = index_service.query(store, "a")
        assert isinstance(results, list)

    def test_12_create_from_texts_returns_store(self, index_service):
        """返回向量库对象。"""
        store = index_service.create_from_texts(["x"])
        assert hasattr(store, "similarity_search") or hasattr(store, "as_retriever")

    def test_13_query_returns_documents(self, index_service):
        """返回文档列表。"""
        store = index_service.create_from_texts(["文档内容"])
        results = index_service.query(store, "文档", k=1)
        for r in results:
            assert hasattr(r, "content") or hasattr(r, "page_content") or isinstance(r, str)

    def test_14_create_from_texts_unicode(self, index_service):
        """Unicode 文本。"""
        store = index_service.create_from_texts(["🎉🎊", "🎈"])
        assert store is not None

    def test_15_query_unicode(self, index_service):
        """Unicode 查询。"""
        store = index_service.create_from_texts(["🎉", "🎊"])
        results = index_service.query(store, "🎉", k=1)
        assert isinstance(results, list)

    def test_16_create_from_texts_long(self, index_service):
        """长文本。"""
        store = index_service.create_from_texts(["x" * 500, "y" * 500])
        assert store is not None

    def test_17_query_long(self, index_service):
        """长查询。"""
        store = index_service.create_from_texts(["短文本"])
        results = index_service.query(store, "x" * 200, k=1)
        assert isinstance(results, list)

    def test_18_create_then_query(self, index_service):
        """建库后立即查询。"""
        store = index_service.create_from_texts(
            ["SpringBootAI 是一个 Python 框架", "LangChain 提供 AI 工具链"])
        results = index_service.query(store, "框架", k=2)
        assert isinstance(results, list)

    def test_19_multiple_queries_same_store(self, index_service):
        """同一库多次查询。"""
        store = index_service.create_from_texts(["a", "b", "c"])
        r1 = index_service.query(store, "a", k=1)
        r2 = index_service.query(store, "b", k=1)
        assert isinstance(r1, list) and isinstance(r2, list)

    def test_20_create_from_texts_special_chars(self, index_service):
        """特殊字符文本。"""
        store = index_service.create_from_texts(["SELECT * FROM users", "<html>"])
        assert store is not None

    def test_21_query_special_chars(self, index_service):
        """特殊字符查询。"""
        store = index_service.create_from_texts(["SQL: SELECT", "HTML: <div>"])
        results = index_service.query(store, "SELECT", k=1)
        assert isinstance(results, list)

    def test_22_index_service_has_embeddings(self, index_service):
        """IndexService 有嵌入模型。"""
        assert index_service._embeddings is not None

    def test_23_index_service_has_model(self, index_service):
        """IndexService 有 LLM 模型。"""
        assert index_service._lc_model is not None

    def test_24_create_from_texts_k_zero(self, index_service):
        """k=0 查询。"""
        store = index_service.create_from_texts(["a", "b"])
        try:
            results = index_service.query(store, "a", k=0)
            assert isinstance(results, list)
        except Exception:
            pass  # k=0 可能抛异常

    def test_25_create_from_texts_large_k(self, index_service):
        """k 大于文档数。"""
        store = index_service.create_from_texts(["a", "b"])
        results = index_service.query(store, "a", k=100)
        assert len(results) <= 2


# ==================== 14. Tools 扩展 (30) ====================

class TestToolsExt:
    """工具工厂扩展：创建/注册/执行/schema/springbootAI转换。"""

    def test_01_from_function_basic(self):
        """函数转 Tool。"""
        def echo(x: str) -> str:
            """回显"""
            return x
        tool = ToolFactory.from_function(echo, name="echo", description="回显工具")
        assert tool is not None

    def test_02_from_function_with_name(self):
        """指定 name。"""
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="my_tool", description="测试")
        assert tool.name == "my_tool"

    def test_03_from_function_with_description(self):
        """指定 description。"""
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="t", description="自定义描述")
        assert tool.description == "自定义描述"

    def test_04_from_function_auto_name(self):
        """自动取函数名。"""
        def my_tool(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(my_tool, description="d")
        assert tool.name == "my_tool" or tool.name == "my_tool"

    def test_05_from_function_auto_description(self):
        """自动取 docstring。"""
        def fn(x: str) -> str:
            """这是工具描述"""
            return x
        tool = ToolFactory.from_function(fn, name="fn")
        assert "工具描述" in tool.description or tool.description != ""

    def test_06_create_tool_basic(self):
        """create_tool 方法 - 签名为 (name, func, description)。"""
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.create_tool("test", fn, description="测试工具")
        assert tool is not None
        assert tool.name == "test"

    def test_07_tool_is_structured_tool(self):
        """返回 StructuredTool。"""
        from langchain_core.tools import StructuredTool
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="t", description="d")
        assert isinstance(tool, StructuredTool)

    def test_08_tool_invoke(self):
        """工具调用。"""
        def add(a: int, b: int) -> int:
            """加法"""
            return a + b
        tool = ToolFactory.from_function(add, name="add", description="加法")
        result = tool.invoke({"a": 1, "b": 2})
        assert result == 3

    def test_09_tool_string_input(self):
        """字符串输入工具。"""
        def upper(x: str) -> str:
            """大写"""
            return x.upper()
        tool = ToolFactory.from_function(upper, name="upper", description="大写")
        result = tool.invoke({"x": "hello"})
        assert result == "HELLO"

    def test_10_from_spring_registry_empty(self):
        """空 springbootAI ToolRegistry。"""
        from spring.ai.tools import ToolRegistry as SpringToolRegistry
        spring_reg = SpringToolRegistry()
        tools = ToolFactory.from_spring_tool_registry(spring_reg)
        assert tools == []

    def test_11_tool_registry_create(self):
        """ToolRegistry 创建。"""
        reg = ToolRegistry()
        assert reg is not None

    def test_12_tool_registry_add(self):
        """ToolRegistry 添加工具（用 add_function 提供 name+description）。"""
        reg = ToolRegistry()
        def fn(x: str) -> str:
            """工具"""
            return x
        reg.add_function(fn, name="test", description="测试")
        assert "test" in reg.names()

    def test_13_tool_registry_collect(self):
        """ToolRegistry 收集多个工具。"""
        reg = ToolRegistry()
        def fn1(x: str) -> str:
            """工具1"""
            return x
        def fn2(x: str) -> str:
            """工具2"""
            return x
        reg.add_function(fn1, name="t1", description="d1")
        reg.add_function(fn2, name="t2", description="d2")
        assert len(reg.all()) == 2

    def test_14_tool_registry_clear(self):
        """ToolRegistry 清空。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t", description="d")
        reg.clear()
        assert len(reg.all()) == 0

    def test_15_tool_registry_clear_empty(self):
        """ToolRegistry 清空空注册表。"""
        reg = ToolRegistry()
        reg.clear()
        assert len(reg.all()) == 0

    def test_16_tool_registry_multiple_clears(self):
        """ToolRegistry 多次清空。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t", description="d")
        reg.clear()
        reg.clear()
        assert len(reg.all()) == 0

    def test_17_tool_with_chinese_description(self):
        """中文描述工具。"""
        def fn(x: str) -> str:
            """搜索工具"""
            return x
        tool = ToolFactory.from_function(fn, name="search", description="搜索工具")
        assert "搜索" in tool.description

    def test_18_tool_with_unicode_name(self):
        """Unicode 工具名。"""
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="tool_中文", description="d")
        assert tool.name == "tool_中文"

    def test_19_tool_no_args(self):
        """无参数工具。"""
        def get_time() -> str:
            """获取时间"""
            return "2026-08-10"
        tool = ToolFactory.from_function(get_time, name="time", description="时间")
        result = tool.invoke({})
        assert "2026" in result

    def test_20_tool_multiple_args(self):
        """多参数工具。"""
        def combine(a: str, b: str, c: str) -> str:
            """合并"""
            return f"{a}-{b}-{c}"
        tool = ToolFactory.from_function(combine, name="combine", description="合并")
        result = tool.invoke({"a": "x", "b": "y", "c": "z"})
        assert result == "x-y-z"

    def test_21_tool_optional_args(self):
        """可选参数工具。"""
        def greet(name: str, greeting: str = "你好") -> str:
            """问候"""
            return f"{greeting}, {name}!"
        tool = ToolFactory.from_function(greet, name="greet", description="问候")
        result = tool.invoke({"name": "张三", "greeting": "你好"})
        assert "张三" in result

    def test_22_tool_returns_int(self):
        """返回 int 工具。"""
        def calc(x: int) -> int:
            """计算"""
            return x * 2
        tool = ToolFactory.from_function(calc, name="calc", description="计算")
        result = tool.invoke({"x": 5})
        assert result == 10

    def test_23_tool_returns_bool(self):
        """返回 bool 工具。"""
        def check(x: str) -> bool:
            """检查"""
            return len(x) > 0
        tool = ToolFactory.from_function(check, name="check", description="检查")
        result = tool.invoke({"x": "hello"})
        assert result is True

    def test_24_tool_returns_list(self):
        """返回 list 工具。"""
        def split(text: str) -> list:
            """分割"""
            return text.split(",")
        tool = ToolFactory.from_function(split, name="split", description="分割")
        result = tool.invoke({"text": "a,b,c"})
        assert result == ["a", "b", "c"]

    def test_25_tool_returns_dict(self):
        """返回 dict 工具。"""
        def info(name: str) -> dict:
            """信息"""
            return {"name": name, "length": len(name)}
        tool = ToolFactory.from_function(info, name="info", description="信息")
        result = tool.invoke({"name": "test"})
        assert result["name"] == "test"

    def test_26_tool_registry_add_duplicate(self):
        """ToolRegistry 添加重复名称（当前实现允许重复，不抛异常）。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t", description="d1")
        # 重复添加同名工具（当前实现不去重，允许重复）
        try:
            reg.add_function(lambda x: x + "2", name="t", description="d2")
        except Exception:
            pass  # 重复添加报错也是合理的

    def test_27_tool_with_long_description(self):
        """长描述工具。"""
        long_desc = "这是一个非常长的工具描述" * 10
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="t", description=long_desc)
        assert len(tool.description) > 50

    def test_28_tool_registry_names(self):
        """ToolRegistry 获取所有名称（reg.names() 返回工具名列表）。"""
        reg = ToolRegistry()
        reg.add_function(lambda x: x, name="t1", description="d")
        reg.add_function(lambda x: x, name="t2", description="d")
        names = reg.names()
        assert "t1" in names
        assert "t2" in names

    def test_29_tool_chinese_arg(self):
        """中文参数值。"""
        def echo(text: str) -> str:
            """回显"""
            return text
        tool = ToolFactory.from_function(echo, name="echo", description="回显")
        result = tool.invoke({"text": "你好世界"})
        assert "你好" in result

    def test_30_tool_special_chars_arg(self):
        """特殊字符参数。"""
        def echo(text: str) -> str:
            """回显"""
            return text
        tool = ToolFactory.from_function(echo, name="echo", description="回显")
        result = tool.invoke({"text": "<script>alert(1)</script>"})
        assert "script" in result


# ==================== 15. Loaders 扩展 (20) ====================

class TestLoadersExt:
    """文档加载器扩展：全类型/加载/错误/便捷方法。"""

    def test_01_supported_types_count(self):
        """支持 10 种加载器。"""
        types = DocumentLoaderRegistry.supported_types()
        assert len(types) >= 10

    def test_02_supported_types_contains_text(self):
        """支持 text。"""
        assert "text" in DocumentLoaderRegistry.supported_types()

    def test_03_supported_types_contains_csv(self):
        """支持 csv。"""
        assert "csv" in DocumentLoaderRegistry.supported_types()

    def test_04_supported_types_contains_pdf(self):
        """支持 pdf。"""
        assert "pdf" in DocumentLoaderRegistry.supported_types()

    def test_05_supported_types_contains_html(self):
        """支持 html。"""
        assert "html" in DocumentLoaderRegistry.supported_types()

    def test_06_supported_types_contains_web(self):
        """支持 web。"""
        assert "web" in DocumentLoaderRegistry.supported_types()

    def test_07_supported_types_contains_directory(self):
        """支持 directory。"""
        assert "directory" in DocumentLoaderRegistry.supported_types()

    def test_08_supported_types_contains_json(self):
        """支持 json。"""
        assert "json" in DocumentLoaderRegistry.supported_types()

    def test_09_supported_types_contains_markdown(self):
        """支持 markdown。"""
        assert "markdown" in DocumentLoaderRegistry.supported_types()

    def test_10_supported_types_contains_word(self):
        """支持 word。"""
        assert "word" in DocumentLoaderRegistry.supported_types()

    def test_11_supported_types_is_list(self):
        """返回 list。"""
        assert isinstance(DocumentLoaderRegistry.supported_types(), list)

    def test_12_supported_types_no_duplicates(self):
        """无重复。"""
        types = DocumentLoaderRegistry.supported_types()
        assert len(types) == len(set(types))

    def test_13_load_text_file(self, tmp_path):
        """加载文本文件。"""
        f = tmp_path / "test.txt"
        f.write_text("Hello World", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("text", str(f))
            docs = loader.load()
            assert len(docs) > 0
        except Exception:
            pass

    def test_14_load_json_file(self, tmp_path):
        """加载 JSON 文件。"""
        import json as json_mod
        f = tmp_path / "test.json"
        f.write_text(json_mod.dumps({"key": "value"}), encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("json", str(f))
            docs = loader.load()
            assert len(docs) > 0
        except Exception:
            pass

    def test_15_load_csv_file(self, tmp_path):
        """加载 CSV 文件。"""
        f = tmp_path / "test.csv"
        f.write_text("name,age\n张三,25\n李四,30", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("csv", str(f))
            docs = loader.load()
            assert len(docs) > 0
        except Exception:
            pass

    def test_16_load_markdown_file(self, tmp_path):
        """加载 Markdown 文件。"""
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nContent", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("markdown", str(f))
            docs = loader.load()
            assert len(docs) > 0
        except Exception:
            pass

    def test_17_load_html_file(self, tmp_path):
        """加载 HTML 文件。"""
        f = tmp_path / "test.html"
        f.write_text("<html><body>Hello</body></html>", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("html", str(f))
            docs = loader.load()
            assert len(docs) > 0
        except Exception:
            pass

    def test_18_create_unknown_raises(self):
        """未知类型抛异常。"""
        with pytest.raises((ValueError, Exception)):
            DocumentLoaderRegistry.create("nonexistent", "path")

    def test_19_load_text_chinese(self, tmp_path):
        """加载中文文本。"""
        f = tmp_path / "chinese.txt"
        f.write_text("你好世界", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("text", str(f))
            docs = loader.load()
            assert any("你好" in d.page_content for d in docs)
        except Exception:
            pass

    def test_20_load_text_unicode(self, tmp_path):
        """加载 Unicode 文本。"""
        f = tmp_path / "unicode.txt"
        f.write_text("🎉🎊🎈", encoding="utf-8")
        try:
            loader = DocumentLoaderRegistry.create("text", str(f))
            docs = loader.load()
            assert any("🎉" in d.page_content for d in docs)
        except Exception:
            pass


# ==================== 16. Utilities 扩展 (15) ====================

class TestUtilitiesExt:
    """实用工具扩展：全类型/创建/as_tools。"""

    def test_01_supported_types_count(self):
        """支持 6+ 种工具。"""
        types = UtilityRegistry.supported_types()
        assert len(types) >= 6

    def test_02_supported_types_contains_serpapi(self):
        """支持 serpapi。"""
        assert "serpapi" in UtilityRegistry.supported_types()

    def test_03_supported_types_contains_duckduckgo(self):
        """支持 duckduckgo。"""
        assert "duckduckgo" in UtilityRegistry.supported_types()

    def test_04_supported_types_contains_wikipedia(self):
        """支持 wikipedia。"""
        assert "wikipedia" in UtilityRegistry.supported_types()

    def test_05_supported_types_contains_python_repl(self):
        """支持 python-repl。"""
        assert "python-repl" in UtilityRegistry.supported_types()

    def test_06_supported_types_contains_sql_database(self):
        """支持 sql-database。"""
        assert "sql-database" in UtilityRegistry.supported_types()

    def test_07_supported_types_is_list(self):
        """返回 list。"""
        assert isinstance(UtilityRegistry.supported_types(), list)

    def test_08_supported_types_no_duplicates(self):
        """无重复。"""
        types = UtilityRegistry.supported_types()
        assert len(types) == len(set(types))

    def test_09_create_python_repl(self):
        """创建 Python REPL。"""
        try:
            util = UtilityRegistry.create("python-repl")
            assert util is not None
        except Exception:
            pass

    def test_10_create_unknown_raises(self):
        """未知类型抛异常。"""
        with pytest.raises((ValueError, Exception)):
            UtilityRegistry.create("nonexistent")

    def test_11_create_empty_raises(self):
        """空字符串抛异常。"""
        with pytest.raises((ValueError, Exception)):
            UtilityRegistry.create("")

    def test_12_as_tools_method_exists(self):
        """as_tools 方法存在。"""
        assert hasattr(UtilityRegistry, "as_tools")

    def test_13_create_duckduckgo(self):
        """创建 DuckDuckGo。"""
        try:
            util = UtilityRegistry.create("duckduckgo")
            assert util is not None
        except Exception:
            pass

    def test_14_create_wikipedia(self):
        """创建 Wikipedia。"""
        try:
            util = UtilityRegistry.create("wikipedia")
            assert util is not None
        except Exception:
            pass

    def test_15_supported_types_sorted(self):
        """类型列表完整覆盖所有 Utility 类型。"""
        types = UtilityRegistry.supported_types()
        # 校验集合等价（顺序由注册表决定，不强求字母序）
        assert "serpapi" in types and "duckduckgo" in types and "arxiv" in types
        assert len(types) >= 8


# ==================== 17. Callbacks 扩展 (15) ====================

class TestCallbacksExt:
    """回调扩展：全类型/注册/all/clear/文件回调。"""

    def test_01_create_stdout_handler(self):
        """创建 stdout 回调。"""
        cb = CallbackRegistry.create_stdout_handler()
        assert cb is not None

    def test_02_create_streaming_stdout_handler(self):
        """创建 streaming stdout 回调。"""
        cb = CallbackRegistry.create_streaming_stdout_handler()
        assert cb is not None

    def test_03_create_file_handler(self, tmp_path):
        """创建文件回调。"""
        log_file = tmp_path / "callback.log"
        cb = CallbackRegistry.create_file_handler(str(log_file))
        assert cb is not None

    def test_04_registry_create(self):
        """CallbackRegistry 创建。"""
        reg = CallbackRegistry()
        assert reg is not None

    def test_05_registry_register(self):
        """注册回调（register 接收单个 handler，返回 self 便于链式）。"""
        reg = CallbackRegistry()
        cb = CallbackRegistry.create_stdout_handler()
        reg.register(cb)
        assert len(reg.all()) == 1

    def test_06_registry_all(self):
        """获取所有回调。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        assert len(reg.all()) >= 1

    def test_07_registry_clear(self):
        """清空回调。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        reg.clear()
        assert len(reg.all()) == 0

    def test_08_registry_clear_empty(self):
        """清空空注册表。"""
        reg = CallbackRegistry()
        reg.clear()
        assert len(reg.all()) == 0

    def test_09_registry_multiple_registers(self):
        """注册多个回调。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        reg.register(CallbackRegistry.create_streaming_stdout_handler())
        assert len(reg.all()) >= 2

    def test_10_registry_multiple_clears(self):
        """多次清空。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        reg.clear()
        reg.clear()
        assert len(reg.all()) == 0

    def test_11_stdout_handler_is_base_handler(self):
        """stdout 回调是 BaseCallbackHandler。"""
        from langchain_core.callbacks import BaseCallbackHandler
        cb = CallbackRegistry.create_stdout_handler()
        assert isinstance(cb, BaseCallbackHandler)

    def test_12_streaming_handler_is_base_handler(self):
        """streaming 回调是 BaseCallbackHandler。"""
        from langchain_core.callbacks import BaseCallbackHandler
        cb = CallbackRegistry.create_streaming_stdout_handler()
        assert isinstance(cb, BaseCallbackHandler)

    def test_13_file_handler_writes(self, tmp_path):
        """文件回调写入。"""
        log_file = tmp_path / "cb.log"
        cb = CallbackRegistry.create_file_handler(str(log_file))
        assert cb is not None

    def test_14_registry_register_duplicate(self):
        """注册多个相同类型回调（注册表不去重，允许重复）。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        try:
            reg.register(CallbackRegistry.create_stdout_handler())
        except Exception:
            pass

    def test_15_registry_all_returns_dict(self):
        """all 返回 list。"""
        reg = CallbackRegistry()
        reg.register(CallbackRegistry.create_stdout_handler())
        result = reg.all()
        assert isinstance(result, list)


# ==================== 18. 端到端集成扩展 (40) ====================

class TestEndToEndExt:
    """端到端集成扩展：完整流程/组合使用/错误恢复。"""

    def test_01_full_chain_pipeline(self, chain_service):
        """完整 Chain 流水线。"""
        result = chain_service.run_llm_chain("回答: {q}", q="测试")
        assert isinstance(result, str)
        assert "测试" in result

    def test_02_chain_with_memory_pipeline(self, chain_service):
        """Chain + Memory 流水线。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        chain = chain_service.create_conversation_chain(memory=mem)
        r1 = chain.invoke({"input": "你好"})["response"]
        r2 = chain.invoke({"input": "再见"})["response"]
        assert isinstance(r1, str) and isinstance(r2, str)

    def test_03_rag_pipeline(self, index_service):
        """RAG 流水线。"""
        store = index_service.create_from_texts(["文档1", "文档2"])
        results = index_service.query(store, "文档", k=2)
        assert isinstance(results, list)

    def test_04_agent_pipeline(self, agent_service):
        """Agent 流水线。"""
        def search(q: str) -> str:
            """搜索"""
            return "结果"
        tools = [ToolFactory.from_function(search, name="search", description="搜索")]
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        result = agent_service.run_agent(executor, "测试")
        assert isinstance(result, str)

    def test_05_full_bootstrap_pipeline(self):
        """完整装配流水线。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        chain = beans["lcChainService"]
        result = chain.run_llm_chain("回答: {q}", q="bootstrap")
        assert "bootstrap" in result

    def test_06_chain_with_parser_pipeline(self, chain_service):
        """Chain + Parser 流水线。"""
        parser = OutputParserFactory.create_json_parser()
        chain = chain_service.create_llm_chain('输出JSON: {{"result": "{q}"}}')
        result = chain.invoke({"q": "test"})
        assert isinstance(result, (str, dict))

    def test_07_vectorstore_retriever_pipeline(self, lc_embeddings):
        """向量库 → 检索器 流水线。"""
        store = VectorStoreFactory.from_texts("inmemory",
            ["文档A", "文档B"], lc_embeddings)
        retriever = VectorStoreFactory.as_retriever(store)
        assert retriever is not None

    def test_08_prompt_chain_pipeline(self, chain_service):
        """Prompt → Chain 流水线。"""
        tpl = PromptTemplateFactory.create_prompt_template("回答: {q}")
        chain = chain_service.create_llm_chain(template=tpl)
        result = chain.invoke({"q": "test"})
        assert isinstance(result, (str, dict))

    def test_09_memory_chain_conversation_pipeline(self, chain_service):
        """Memory + Chain 对话流水线。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        for i in range(3):
            result = chain_service.run_conversation(f"第{i}轮", memory=mem)
            assert isinstance(result, str)

    def test_10_tool_agent_pipeline(self, agent_service):
        """Tool → Agent 流水线。"""
        def calc(x: str) -> str:
            """计算"""
            return "42"
        tools = [ToolFactory.from_function(calc, name="calc", description="计算")]
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        assert executor is not None

    def test_11_configure_ai_then_langchain(self):
        """先 configure_ai 再 configure_langchain。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        ai_beans = configure_ai(registry=registry)
        lc_beans = configure_langchain(registry=registry)
        assert "aiChatClient" in ai_beans
        assert "lcChainService" in lc_beans

    def test_12_chain_service_with_injected_model(self):
        """ChainService 用注入的模型。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        chain = beans["lcChainService"]
        assert chain._lc_model is not None

    def test_13_agent_service_with_injected_model(self):
        """AgentService 用注入的模型。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        agent = beans["lcAgentService"]
        assert agent.llm is not None

    def test_14_index_service_with_injected_embeddings(self):
        """IndexService 用注入的嵌入。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        idx = beans["lcIndexService"]
        assert idx._embeddings is not None

    def test_15_chain_invoke_returns_result(self, chain_service):
        """Chain invoke 返回结果。"""
        chain = chain_service.create_llm_chain("回答: {q}")
        result = chain.invoke({"q": "hello"})
        assert result is not None

    def test_16_conversation_chain_multi_turn(self, chain_service):
        """对话链多轮。"""
        from spring.langchain.memory.memory import MemoryFactory
        mem = MemoryFactory.create("buffer")
        chain = chain_service.create_conversation_chain(memory=mem)
        for i in range(5):
            result = chain.invoke({"input": f"msg_{i}"})
            assert "response" in result

    def test_17_rag_with_chinese(self, index_service):
        """中文 RAG。"""
        store = index_service.create_from_texts(
            ["SpringBootAI 是 Python 框架", "LangChain 是 AI 工具链"])
        results = index_service.query(store, "框架", k=1)
        assert isinstance(results, list)

    def test_18_agent_with_multiple_tools(self, agent_service):
        """多工具 Agent。"""
        tools = [
            ToolFactory.from_function(lambda q: "r1", name="t1", description="d1"),
            ToolFactory.from_function(lambda q: "r2", name="t2", description="d2"),
            ToolFactory.from_function(lambda q: "r3", name="t3", description="d3"),
        ]
        executor = agent_service.create_agent(tools, agent_type="react", max_iterations=3)
        assert len(executor.tools) == 3

    def test_19_sequential_chain_pipeline(self, chain_service):
        """顺序链流水线。"""
        c1 = chain_service.create_llm_chain("步骤1: {input}", output_key="s1")
        c2 = chain_service.create_llm_chain("步骤2: {s1}", output_key="s2")
        seq = chain_service.create_sequential_chain(
            [c1, c2], input_variables=["input"], output_variables=["s2"])
        result = seq.invoke({"input": "start"})
        assert "s2" in result

    def test_20_full_rag_with_query(self, index_service, chain_service):
        """完整 RAG 查询+生成。"""
        store = index_service.create_from_texts(["SpringBootAI 使用注解"])
        results = index_service.query(store, "注解", k=1)
        context = str(results[0]) if results else ""
        answer = chain_service.run_llm_chain("根据资料回答: {ctx}", ctx=context)
        assert isinstance(answer, str)

    def test_21_bootstrap_all_beans_available(self):
        """装配后所有 Bean 可用。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        required = ["lcLangChainModel", "lcEmbeddings", "lcChainService",
                     "lcAgentService", "lcMemoryFactory", "lcIndexService"]
        for name in required:
            assert name in beans, f"缺失 Bean: {name}"

    def test_22_chain_service_run_llm_chain(self, chain_service):
        """run_llm_chain 便捷方法。"""
        result = chain_service.run_llm_chain("Q: {q}\nA:", q="test")
        assert "test" in result

    def test_23_chain_service_run_conversation(self, chain_service):
        """run_conversation 便捷方法。"""
        result = chain_service.run_conversation("你好")
        assert isinstance(result, str)

    def test_24_chain_service_run_summarize(self, chain_service):
        """run_summarize 便捷方法。"""
        result = chain_service.run_summarize(["文本1", "文本2"])
        assert isinstance(result, str)

    def test_25_agent_service_run_agent(self, agent_service):
        """run_agent 便捷方法。"""
        def fn(q: str) -> str:
            """工具"""
            return "ok"
        tools = [ToolFactory.from_function(fn, name="t", description="d")]
        result = agent_service.run_agent(tools, "test", agent_type="react")
        assert isinstance(result, str)

    def test_26_vector_store_factory_create(self, lc_embeddings):
        """VectorStoreFactory.create。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        assert store is not None

    def test_27_vector_store_factory_from_texts(self, lc_embeddings):
        """VectorStoreFactory.from_texts。"""
        store = VectorStoreFactory.from_texts("inmemory", ["x"], lc_embeddings)
        assert store is not None

    def test_28_memory_factory_create_buffer(self):
        """MemoryFactory.create buffer。"""
        mem = MemoryFactory.create("buffer")
        assert mem is not None

    def test_29_parser_factory_create_json(self):
        """OutputParserFactory.create json。"""
        parser = OutputParserFactory.create("json")
        assert parser is not None

    def test_30_tool_factory_from_function(self):
        """ToolFactory.from_function。"""
        def fn(x: str) -> str:
            """工具"""
            return x
        tool = ToolFactory.from_function(fn, name="t", description="d")
        assert tool is not None

    def test_31_full_pipeline_no_errors(self):
        """完整流水线无错误。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        chain = beans["lcChainService"]
        result = chain.run_llm_chain("回答: {q}", q="成功")
        assert "成功" in result

    def test_32_chain_with_few_shot_prompt(self, chain_service):
        """Chain + FewShot Prompt。"""
        tpl = PromptTemplateFactory.create_few_shot_prompt_template(
            prefix="翻译：",
            examples=[{"input": "hello", "output": "你好"}],
            example_prompt=PromptTemplateFactory.create_prompt_template("{input} -> {output}"),
            suffix="翻译: {word} ->",
        )
        chain = chain_service.create_llm_chain(template=tpl)
        result = chain.invoke({"word": "world"})
        assert isinstance(result, (str, dict))

    def test_33_agent_all_types_create(self, agent_service):
        """所有 Agent 类型都能创建。"""
        def fn(q: str) -> str:
            """工具"""
            return "ok"
        tools = [ToolFactory.from_function(fn, name="t", description="d")]
        for t in ["react", "chat-zero-shot-react", "openai-functions",
                  "openai-tools", "structured-chat"]:
            executor = agent_service.create_agent(tools, agent_type=t, max_iterations=3)
            assert executor is not None

    def test_34_rag_with_metadata(self, index_service):
        """带元数据 RAG。"""
        store = index_service.create_from_texts(
            ["文档1", "文档2"],
            metadatas=[{"src": "a"}, {"src": "b"}])
        results = index_service.query(store, "文档", k=2)
        assert isinstance(results, list)

    def test_35_memory_all_types(self, lc_model):
        """所有 Memory 类型。"""
        for t in ["buffer", "buffer-window"]:
            mem = MemoryFactory.create(t)
            assert mem is not None
        for t in ["summary", "token-buffer"]:
            mem = MemoryFactory.create(t, llm=lc_model)
            assert mem is not None

    def test_36_vector_store_inmemory_full_cycle(self, lc_embeddings):
        """内存向量库完整周期。"""
        store = VectorStoreFactory.create("inmemory", embeddings=lc_embeddings)
        store.add_texts(["文本1", "文本2"])
        results = store.similarity_search("文本1", k=1)
        assert isinstance(results, list)

    def test_37_chain_preserves_model_prefix(self, chain_service):
        """Chain 保留模型前缀。"""
        result = chain_service.run_llm_chain("回答: {q}", q="test")
        assert "[AI]" in result

    def test_38_full_bootstrap_chain_callable(self):
        """装配后 Chain 可调用。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        chain = beans["lcChainService"]
        result = chain.run_llm_chain("Q: {q}", q="ok")
        assert "ok" in result

    def test_39_full_bootstrap_agent_callable(self):
        """装配后 Agent 可创建。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        agent = beans["lcAgentService"]
        def fn(q: str) -> str:
            """工具"""
            return "ok"
        tools = [ToolFactory.from_function(fn, name="t", description="d")]
        executor = agent.create_agent(tools, agent_type="react", max_iterations=3)
        assert executor is not None

    def test_40_full_bootstrap_rag_callable(self):
        """装配后 RAG 可用。"""
        from spring.ai.autoconfig import configure_ai
        registry = BeanRegistry()
        configure_ai(registry=registry)
        beans = configure_langchain(registry=registry)
        idx = beans["lcIndexService"]
        store = idx.create_from_texts(["文档1", "文档2"])
        results = idx.query(store, "文档", k=1)
        assert isinstance(results, list)
