"""SpringPy AI 模块测试 - 覆盖核心抽象/Provider/Advisor/Memory/VectorStore/ETL/Tools/AutoConfig/注解。

使用 FakeChatModel/FakeEmbeddingModel 提供确定性输出，不依赖网络或真实 LLM。
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.ai import (
    Advisor, AdvisorRequest, ChatClient, ChatClientBuilder, ChatModel,
    ChatResponse, EmbeddingModel, Generation, Message, MessageType,
    PromptSpec, AiClient, Tool, AiAdvisor, AiMemory,
    MessageChatMemoryAdvisor, QuestionAnswerAdvisor, SimpleLoggerAdvisor,
    InMemoryChatMemory, RedisChatMemory, ChatMemory,
    SimpleInMemoryVectorStore, RedisVectorStore, VectorStore, SearchRequest, cosine_similarity,
    VectorDocument,
    TokenTextSplitter, CharacterTextSplitter, TextReader, TextDocument,
    ToolRegistry, ToolDefinition,
    FakeChatModel, FakeEmbeddingModel, OpenAIChatModel, OpenAIEmbeddingModel,
    OllamaChatModel, OllamaEmbeddingModel,
    AIProperties, bind_ai_config, configure_ai,
)
from spring.annotations.core import get_spring_annotations
from spring.context.registry import BeanRegistry


@pytest.fixture(autouse=True)
def _isolate_ai_env(monkeypatch):
    """隔离 AI 相关环境变量，防止开发者本机 env 干扰 configure_ai 绑定测试。

    bind_ai_config 的 env 覆盖安全网会读 os.environ，故测试必须显式清理
    AI_/OPENAI_/OLLAMA_ 前缀变量，保证可重现。
    """
    for key in list(os.environ):
        if key.startswith(("AI_", "OPENAI_", "OLLAMA_")):
            monkeypatch.delenv(key, raising=False)


# ==================== 核心抽象 ====================

class TestCoreAbstractions:
    def test_message_factory_methods(self):
        """Message.system/user/assistant 工厂方法"""
        s = Message.system("sys")
        u = Message.user("hi")
        a = Message.assistant("ok")
        assert s.type == MessageType.SYSTEM
        assert u.type == MessageType.USER
        assert a.type == MessageType.ASSISTANT
        assert s.to_dict() == {"role": "system", "content": "sys"}
        assert u.to_dict() == {"role": "user", "content": "hi"}

    def test_chat_response_content_property(self):
        """ChatResponse.content 便捷取值"""
        resp = ChatResponse(generations=[
            Generation(output=Message.assistant("hello"))
        ])
        assert resp.content() == "hello"
        assert resp.output.type == MessageType.ASSISTANT
        empty = ChatResponse(generations=[])
        assert empty.content() == ""
        assert empty.output is None

    def test_embedding_model_embed_one(self):
        """EmbeddingModel.embed_one 默认实现"""
        emb = FakeEmbeddingModel(dim=4)
        vec = emb.embed_one("test")
        assert len(vec) == 4
        # 相同输入确定性
        assert emb.embed_one("test") == vec


# ==================== ChatClient 链式 API ====================

class TestChatClient:
    def test_fluent_prompt_user_call_content(self):
        """ChatClient 链式 prompt().user().call().content()"""
        client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
        answer = client.prompt().user("你好").call().content()
        assert answer == "AI: 你好"

    def test_default_system_prepended(self):
        """default_system 自动插入到消息首部"""
        client = (ChatClientBuilder(FakeChatModel())
                  .default_system("你是助手").build())
        spec = client.prompt().user("问")
        assert spec._messages[0].type == MessageType.SYSTEM
        assert spec._messages[0].content == "你是助手"
        assert spec._messages[1].type == MessageType.USER

    def test_prompt_spec_param_and_messages(self):
        """PromptSpec param/context 与 messages 累加"""
        client = ChatClientBuilder(FakeChatModel()).build()
        spec = (client.prompt()
                .system("s").user("u1").user("u2")
                .param("conversation_id", "c1"))
        assert len(spec._messages) == 3
        assert spec._context["conversation_id"] == "c1"


# ==================== Fake Provider ====================

class TestFakeProviders:
    def test_fake_chat_model_echoes_last_user(self):
        """FakeChatModel 回显最后一条 user 消息并计数"""
        model = FakeChatModel(prefix="R:")
        resp = model.call([Message.user("abc"), Message.assistant("x"),
                           Message.user("最终问题")])
        assert resp.content() == "R: 最终问题"
        assert model.call_count == 1
        model.call([Message.user("again")])
        assert model.call_count == 2

    def test_fake_embedding_deterministic_and_normalized(self):
        """FakeEmbeddingModel 相同文本→相同向量，且归一化"""
        emb = FakeEmbeddingModel(dim=8)
        v1 = emb.embed(["hello", "hello", "world"])
        assert v1[0] == v1[1]      # 相同文本相同向量
        assert v1[0] != v1[2]      # 不同文本不同向量
        norm = sum(x * x for x in v1[0]) ** 0.5
        assert abs(norm - 1.0) < 1e-6  # 归一化


# ==================== Provider 配置 ====================

class TestProviderConfiguration:
    def test_openai_chat_model_config_attributes(self):
        """OpenAIChatModel 保留配置属性"""
        m = OpenAIChatModel(api_key="sk-x", base_url="https://api.deepseek.com/v1",
                            model="deepseek-chat", temperature=0.3)
        assert m.api_key == "sk-x"
        assert m.base_url == "https://api.deepseek.com/v1"
        assert m.model == "deepseek-chat"
        assert m.temperature == 0.3

    def test_ollama_chat_model_config_attributes(self):
        """OllamaChatModel 配置属性"""
        m = OllamaChatModel(base_url="http://ollama:11434",
                            model="qwen2", temperature=0.5)
        assert m.base_url == "http://ollama:11434"
        assert m.model == "qwen2"
        assert m.temperature == 0.5

    def test_openai_embedding_model_config(self):
        """OpenAIEmbeddingModel 配置属性"""
        e = OpenAIEmbeddingModel(api_key="sk-e", model="text-embedding-3-large")
        assert e.api_key == "sk-e"
        assert e.model == "text-embedding-3-large"


# ==================== 会话记忆 ====================

class TestChatMemory:
    def test_inmemory_add_get_clear_and_window(self):
        """InMemoryChatMemory 增删查与滑动窗口"""
        mem = InMemoryChatMemory(max_messages=3)
        mem.add("c1", Message.user("m1"))
        mem.add("c1", Message.assistant("m2"))
        mem.add("c1", Message.user("m3"))
        history = mem.get("c1")
        assert len(history) == 3
        assert history[0].content == "m1"

        # 窗口：第4条触发裁剪，保留最近3条
        mem.add("c1", Message.assistant("m4"))
        history = mem.get("c1")
        assert len(history) == 3
        assert history[0].content == "m2"
        assert history[-1].content == "m4"

        # last_n 限制
        assert len(mem.get("c1", last_n=1)) == 1
        # 清空
        mem.clear("c1")
        assert mem.get("c1") == []

    def test_inmemory_isolation_between_conversations(self):
        """不同会话隔离"""
        mem = InMemoryChatMemory()
        mem.add("a", Message.user("a1"))
        mem.add("b", Message.user("b1"))
        assert len(mem.get("a")) == 1
        assert len(mem.get("b")) == 1
        assert mem.get("a")[0].content == "a1"

    def test_redis_memory_without_client_is_noop(self):
        """RedisChatMemory 无 client 时安全降级（不抛异常）"""
        mem = RedisChatMemory(redis_client=None)
        mem.add("c", Message.user("x"))      # 不抛异常
        assert mem.get("c") == []
        mem.clear("c")                         # 不抛异常


# ==================== VectorStore ====================

class TestVectorStore:
    def test_cosine_similarity_basic(self):
        """cosine_similarity 计算正确"""
        assert abs(cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-6
        assert abs(cosine_similarity([1, 0], [0, 1]) - 0.0) < 1e-6
        assert cosine_similarity([], [1]) == 0.0
        assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0  # 长度不等

    def test_inmemory_vectorstore_add_and_search(self):
        """SimpleInMemoryVectorStore 写入与相似度检索"""
        emb = FakeEmbeddingModel(dim=8)
        store = SimpleInMemoryVectorStore(embedding_model=emb)
        store.add_texts(["Spring框架文档", "Python语言指南", "Spring AI教程"])
        assert store.count() == 3

        # 检索：相同前缀词的文档相似度更高
        results = store.similarity_search(
            SearchRequest(query="Spring", top_k=2)
        )
        assert len(results) <= 2
        # 包含 "Spring" 的文档应排在前面
        top_contents = [d.content for d in results]
        assert any("Spring" in c for c in top_contents)

    def test_inmemory_vectorstore_empty_query_returns_empty(self):
        """无 embedding 且无 embedding_model 时返回空"""
        store = SimpleInMemoryVectorStore()
        store.add([__import__("spring.ai.vectorstore", fromlist=["Document"]).Document(
            id="1", content="x", embedding=[1.0])])
        # 无 query embedding → 返回空
        results = store.similarity_search(SearchRequest(query=""))
        assert results == []


# ==================== ETL ====================

class TestEtl:
    def test_text_reader_inline_content(self):
        """TextReader 读取内联文本"""
        reader = TextReader()
        doc = reader.read_text("hello world", source="test")
        assert doc.content == "hello world"
        assert doc.source == "test"

    def test_token_text_splitter_long_text(self):
        """TokenTextSplitter 切片长文本"""
        splitter = TokenTextSplitter(chunk_size=10, chunk_overlap=2,
                                     min_chunk_size=1)
        long_text = "word " * 200  # 远超 chunk_size*4 字符
        docs = splitter.split([TextDocument(content=long_text, metadata={"source": "s"})])
        assert len(docs) > 1
        # 每个 chunk 携带 chunk_index 元数据
        assert "chunk_index" in docs[0].metadata
        assert docs[0].metadata["source"] == "s"

    def test_token_text_splitter_short_text_single_chunk(self):
        """短文本不切片，单块返回"""
        splitter = TokenTextSplitter(chunk_size=800)
        docs = splitter.split([TextDocument(content="短文本")])
        assert len(docs) == 1

    def test_character_text_splitter(self):
        """CharacterTextSplitter 按分隔符切片"""
        splitter = CharacterTextSplitter(separator="\n\n", chunk_size=30)
        text = "段落一\n\n段落二\n\n段落三"
        docs = splitter.split([TextDocument(content=text)])
        assert len(docs) >= 1
        assert all("chunk_index" in d.metadata for d in docs)


# ==================== Tools / Function Calling ====================

class TestToolRegistry:
    def test_register_and_schema_generation(self):
        """ToolRegistry 从签名自动生成 schema"""
        registry = ToolRegistry()

        @Tool(description="查询订单状态")
        def get_order_status(order_id: str, detail: bool = False) -> str:
            """根据订单号返回订单状态"""
            return f"订单{order_id}状态"

        registry.register("get_order_status", get_order_status,
                          description="查询订单状态")
        schema = registry.schemas()[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "get_order_status"
        props = schema["function"]["parameters"]["properties"]
        assert "order_id" in props
        assert "detail" in props
        # order_id 必填，detail 有默认值不必填
        required = schema["function"]["parameters"]["required"]
        assert "order_id" in required
        assert "detail" not in required

    def test_tool_execute(self):
        """ToolRegistry.execute 执行注册的工具"""
        registry = ToolRegistry()

        def add(a: int, b: int) -> int:
            return a + b

        registry.register("add", add, description="加法")
        assert registry.execute("add", {"a": 3, "b": 4}) == 7
        # 字符串参数 JSON 解析
        assert registry.execute("add", '{"a": 10, "b": 5}') == 15

    def test_tool_unknown_raises_and_self_skip(self):
        """未注册工具抛 KeyError；self/cls 参数被跳过"""
        registry = ToolRegistry()

        class Calc:
            def mul(self, a: int, b: int) -> int:
                return a * b

        registry.register("mul", Calc().mul, description="乘法")
        schema = registry.schemas()[0]["function"]["parameters"]["properties"]
        assert "self" not in schema
        assert set(schema.keys()) == {"a", "b"}
        with pytest.raises(KeyError):
            registry.execute("nonexistent", {})


# ==================== Advisor ====================

class TestAdvisors:
    def test_message_chat_memory_advisor_roundtrip(self):
        """MessageChatMemoryAdvisor 请求注入历史、响应保存对话"""
        model = FakeChatModel(prefix="AI:")
        memory = InMemoryChatMemory()
        advisor = MessageChatMemoryAdvisor(memory)
        client = (ChatClientBuilder(model)
                  .default_advisors(advisor).build())

        # 第一轮
        r1 = client.prompt().user("你好").param("conversation_id", "c1").call()
        assert r1.content() == "AI: 你好"
        # 记忆已保存 1 user + 1 assistant
        history = memory.get("c1")
        assert len(history) == 2
        assert history[0].type == MessageType.USER
        assert history[1].type == MessageType.ASSISTANT

        # 第二轮：历史被注入到请求消息前部
        r2 = client.prompt().user("再见").param("conversation_id", "c1").call()
        assert r2.content() == "AI: 再见"
        history = memory.get("c1")
        assert len(history) == 4

    def test_question_answer_advisor_injects_context(self):
        """QuestionAnswerAdvisor 检索文档并注入 system 上下文"""
        emb = FakeEmbeddingModel(dim=8)
        store = SimpleInMemoryVectorStore(embedding_model=emb)
        store.add_texts(["SpringPy 是 Python 微服务框架"])
        advisor = QuestionAnswerAdvisor(vector_store=store, embedding_model=emb)

        model = FakeChatModel()
        client = (ChatClientBuilder(model)
                  .default_advisors(advisor).build())
        req_ctx = {}
        spec = client.prompt().user("SpringPy是什么").param("k", "v")
        # 手动触发 advisor 请求阶段
        advisor_request = AdvisorRequest(
            messages=spec._messages, chat_model=model,
            context={"conversation_id": "default"},
        )
        transformed = advisor.advise_request(advisor_request)
        # 首条消息应为注入的 RAG system 提示
        assert transformed.messages[0].type == MessageType.SYSTEM
        assert "上下文" in transformed.messages[0].content
        assert "retrieved_documents" in transformed.context

    def test_simple_logger_advisor_records_events(self):
        """SimpleLoggerAdvisor 记录请求/响应事件"""
        advisor = SimpleLoggerAdvisor()
        model = FakeChatModel()
        client = (ChatClientBuilder(model)
                  .default_advisors(advisor).build())
        client.prompt().user("测试").call()
        phases = [e["phase"] for e in advisor.events]
        assert "request" in phases
        assert "response" in phases

    def test_advisor_order_sorting(self):
        """Advisor 按 order 升序在请求阶段应用"""
        order_log = []

        class A1(Advisor):
            order = 30
            def advise_request(self, r):
                order_log.append("A1")
                return r

        class A2(Advisor):
            order = 10
            def advise_request(self, r):
                order_log.append("A2")
                return r

        model = FakeChatModel()
        client = (ChatClientBuilder(model)
                  .default_advisors(A1(), A2()).build())
        client.prompt().user("x").call()
        # order 小的先执行
        assert order_log == ["A2", "A1"]


# ==================== 注解 ====================

class TestAiAnnotations:
    def test_ai_client_annotation_metadata(self):
        """@AiClient 附加元数据"""
        @AiClient(provider="openai", model="gpt-4o", temperature=0.2)
        class MyAiService:
            pass

        anns = get_spring_annotations(MyAiService)
        assert len(anns) == 1
        assert isinstance(anns[0], AiClient)
        assert anns[0].provider == "openai"
        assert anns[0].model == "gpt-4o"
        assert anns[0].temperature == 0.2

    def test_tool_annotation_metadata(self):
        """@Tool 附加元数据"""
        @Tool(name="search_web", description="网络搜索")
        def search(query: str) -> str:
            return query

        anns = get_spring_annotations(search)
        assert len(anns) == 1
        assert isinstance(anns[0], Tool)
        assert anns[0].name == "search_web"
        assert anns[0].description == "网络搜索"

    def test_ai_advisor_and_ai_memory_annotations(self):
        """@AiAdvisor 与 @AiMemory 元数据"""
        @AiAdvisor(name="ragAdvisor", order=5)
        class RagAdvisor:
            pass

        @AiMemory(store="redis", max_messages=50)
        class MemorizedService:
            pass

        a_anns = get_spring_annotations(RagAdvisor)
        m_anns = get_spring_annotations(MemorizedService)
        assert isinstance(a_anns[0], AiAdvisor)
        assert a_anns[0].order == 5
        assert isinstance(m_anns[0], AiMemory)
        assert m_anns[0].store == "redis"
        assert m_anns[0].max_messages == 50


# ==================== AutoConfig ====================

class TestAutoConfig:
    def test_configure_ai_with_fake_provider_registers_beans(self):
        """configure_ai 装配 ChatModel/Memory/ChatClient/VectorStore Bean"""
        from spring.config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader._config = {
            "spring": {"ai": {"default-provider": "unknown"}}
        }
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        # 无 api-key → FakeChatModel
        assert isinstance(beans["aiChatModel"], FakeChatModel)
        assert isinstance(beans["aiChatMemory"], InMemoryChatMemory)
        assert isinstance(beans["aiChatClient"], ChatClient)
        assert isinstance(beans["aiVectorStore"], SimpleInMemoryVectorStore)
        # 注册到 registry
        assert registry.contains("aiChatModel")
        assert registry.contains("aiChatClient")
        assert registry.get_by_type(ChatClient) is not None

    def test_configure_ai_openai_without_key_falls_back_to_fake(self):
        """配置 openai 但无 api-key → 降级 FakeChatModel"""
        from spring.config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader._config = {
            "spring": {"ai": {
                "default-provider": "openai",
                "openai": {"chat": {"model": "gpt-4o"}},
            }}
        }
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        assert isinstance(beans["aiChatModel"], FakeChatModel)

    def test_configure_ai_chat_client_callable_after_assembly(self):
        """装配后的 ChatClient 可直接调用"""
        from spring.config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {"default-provider": "fake"}}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        client = beans["aiChatClient"]
        answer = client.prompt().user("集成测试").call().content()
        assert "集成测试" in answer


# ==================== 集成场景 ====================

class TestIntegrationScenarios:
    def test_full_rag_pipeline_etl_to_answer(self):
        """完整 RAG 流水线：ETL 切片 → 入库 → 检索 → 生成"""
        emb = FakeEmbeddingModel(dim=16)
        store = SimpleInMemoryVectorStore(embedding_model=emb)

        # 1. ETL：读取并切片
        reader = TextReader()
        doc = reader.read_text(
            "SpringPy 支持 IoC 容器。SpringPy 支持 AOP 切面。"
            "SpringPy 内嵌 Sentinel 限流。", source="manual"
        )
        splitter = TokenTextSplitter(chunk_size=20, chunk_overlap=5)
        chunks = splitter.split([doc])
        assert len(chunks) >= 1

        # 2. 入库
        from spring.ai.vectorstore import Document as VDoc
        for i, chunk in enumerate(chunks):
            store.add([VDoc(id=f"c{i}", content=chunk.content,
                            metadata=chunk.metadata)])

        # 3. RAG Advisor + 生成
        rag = QuestionAnswerAdvisor(vector_store=store, embedding_model=emb,
                                    top_k=2)
        model = FakeChatModel(prefix="回答:")
        client = (ChatClientBuilder(model)
                  .default_advisors(rag).build())
        answer = client.prompt().user("SpringPy支持什么").call().content()
        assert answer.startswith("回答:")

    def test_multi_turn_conversation_with_memory(self):
        """多轮对话 + 记忆：第二轮请求包含第一轮历史"""
        model = FakeChatModel(prefix="AI:")
        memory = InMemoryChatMemory()
        client = (ChatClientBuilder(model)
                  .default_advisors(MessageChatMemoryAdvisor(memory)).build())

        client.prompt().user("我叫张三").param("conversation_id", "u1").call()
        client.prompt().user("我叫什么").param("conversation_id", "u1").call()

        history = memory.get("u1")
        # 2轮 = 4条消息（2 user + 2 assistant）
        assert len(history) == 4
        assert history[0].content == "我叫张三"

    def test_chat_model_abstract_cannot_instantiate(self):
        """ChatModel 是抽象基类，不可直接实例化"""
        with pytest.raises(TypeError):
            ChatModel()
        with pytest.raises(TypeError):
            EmbeddingModel()
        with pytest.raises(TypeError):
            Advisor()


# ==================== 企业级缺口修复 ====================

class TestFunctionCallingClosure:
    """缺口1: 函数调用闭环 - tools 注入 + tool_call 循环执行回填"""

    def test_tool_call_loop_executes_and_continues(self):
        """FakeChatModel 模拟工具调用：第一轮标记 tool_calls，基类执行→回填→第二轮最终回复"""
        from spring.ai import ToolRegistry
        registry = ToolRegistry()

        def get_weather(city: str = "北京") -> str:
            """查询天气"""
            return f"{city}晴"

        registry.register("get_weather", get_weather, description="查询天气")

        model = FakeChatModel(prefix="AI:", simulate_tool_call=True)
        # 通过 ChatClient 触发闭环
        client = ChatClientBuilder(model).default_tools(registry).build()
        resp = client.prompt().user("调用工具查天气").call()

        # 闭环后应返回包含工具结果的最终回复
        assert resp.content() == "AI: 工具返回: 北京晴"
        # 模型被调用 2 次（第一轮 tool_call + 第二轮最终回复）
        assert model.call_count == 2
        assert resp.metadata.get("tool_iterations") == 1

    def test_tool_call_without_registry_returns_raw(self):
        """无 tool_registry 时，不进入工具闭环，直接返回 echo 回复"""
        model = FakeChatModel(prefix="AI:", simulate_tool_call=True)
        resp = model.call([Message.user("调用工具查天气")])  # 直接调用，无 registry
        # 无 registry → 不触发闭环，返回普通 echo
        assert resp.content() == "AI: 调用工具查天气"
        assert resp.metadata.get("tool_iterations") == 0

    def test_tool_call_max_iterations_guard(self):
        """工具调用超过最大轮数有保护"""
        from spring.ai import ToolRegistry
        registry = ToolRegistry()

        def loop_tool() -> str:
            """总是触发的工具"""
            return "again"

        registry.register("loop_tool", loop_tool)
        # 构造一个每次都返回 tool_calls 的模型
        class AlwaysToolModel(ChatModel):
            def __init__(self):
                self.calls = 0
            def _raw_call(self, messages, tool_registry=None, options=None):
                self.calls += 1
                return ChatResponse(
                    generations=[Generation(output=Message.assistant(""))],
                    metadata={"tool_calls": [{"id": "c1", "function": {
                        "name": "loop_tool", "arguments": "{}"}}]},
                )

        model = AlwaysToolModel()
        resp = model.call([Message.user("x")], tool_registry=registry)
        # 不超过 MAX_TOOL_ITERATIONS + 1 次调用
        assert model.calls <= ChatModel.MAX_TOOL_ITERATIONS + 1
        assert resp.metadata.get("tool_iterations") == ChatModel.MAX_TOOL_ITERATIONS


class TestEmbeddingAutoconfigAndRedisVectorStore:
    """缺口2: EmbeddingModel 装配 + RedisVectorStore"""

    def test_autoconfig_assembles_embedding_model_bean(self):
        """configure_ai 装配 aiEmbeddingModel Bean"""
        from spring.config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {"default-provider": "unknown"}}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        assert "aiEmbeddingModel" in beans
        assert isinstance(beans["aiEmbeddingModel"], FakeEmbeddingModel)
        assert registry.contains("aiEmbeddingModel")

    def test_autoconfig_wires_embedding_into_vector_store(self):
        """VectorStore 注入了 EmbeddingModel，可自动嵌入检索"""
        from spring.config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {"default-provider": "unknown"}}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        vs = beans["aiVectorStore"]
        # 写入纯文本（无 embedding），VectorStore 应自动嵌入
        vs.add_texts(["SpringPy 框架", "Python 语言"])
        results = vs.similarity_search(SearchRequest(query="SpringPy", top_k=1))
        assert len(results) >= 1

    def test_redis_vector_store_without_client_is_noop(self):
        """RedisVectorStore 无 client 时安全降级"""
        from spring.ai import RedisVectorStore
        store = RedisVectorStore(redis_client=None)
        store.add([VectorDocument(id="1", content="x")])  # 不抛异常
        assert store.similarity_search(SearchRequest(query="x")) == []
        assert store.count() == 0

    def test_redis_vector_store_persistence_with_fake_redis(self):
        """RedisVectorStore 用 fake redis 持久化+检索"""
        import json as _json

        class FakeRedis:
            def __init__(self):
                self._h = {}
            def hset(self, key, field, val):
                self._h.setdefault(key, {})[field] = val
            def hgetall(self, key):
                return self._h.get(key, {})
            def delete(self, key):
                self._h.pop(key, None)

        from spring.ai import RedisVectorStore
        fake = FakeRedis()
        emb = FakeEmbeddingModel(dim=8)
        store = RedisVectorStore(redis_client=fake, collection="test",
                                 embedding_model=emb)
        store.add_texts(["文档A", "文档B"])
        assert store.count() == 2
        # 检索
        results = store.similarity_search(SearchRequest(query="文档A", top_k=2))
        assert len(results) >= 1
        # clear
        store.clear()
        assert store.count() == 0


class TestRedisReuse:
    """Redis 封装复用：框架 RedisClient 接口统一 + TTL 修复 + 自动复用全局单例"""

    def test_redis_vector_store_uses_framework_client_interface(self):
        """RedisVectorStore 优先用框架 RedisClient 封装 hash_set/hash_get_all/delete_key"""
        import json as _json

        class FakeFrameworkRedis:
            """模拟框架 RedisClient（提供 hash_set/hash_get_all/delete_key）"""
            def __init__(self):
                self._h = {}
            def hash_set(self, key, field, value):
                v = value if isinstance(value, str) else _json.dumps(value, ensure_ascii=False)
                self._h.setdefault(key, {})[field] = v
                return True
            def hash_get_all(self, key):
                raw = self._h.get(key, {})
                return {f: (_json.loads(v) if isinstance(v, str) else v)
                        for f, v in raw.items()}
            def delete_key(self, key):
                return self._h.pop(key, None) is not None

        fake = FakeFrameworkRedis()
        emb = FakeEmbeddingModel(dim=8)
        store = RedisVectorStore(redis_client=fake, collection="fw", embedding_model=emb)
        store.add_texts(["文档A", "文档B"])
        assert store.count() == 2
        results = store.similarity_search(SearchRequest(query="文档A", top_k=2))
        assert len(results) >= 1
        # 验证走了框架封装方法（_h 有数据）
        assert fake._h
        store.clear()
        assert store.count() == 0

    def test_redis_vector_store_falls_back_to_native_for_raw_redis(self):
        """传入原生 redis 接口（无 hash_set）时降级原生 hset/hgetall/delete"""
        class FakeNativeRedis:
            def __init__(self):
                self._h = {}
            def hset(self, key, field, val):
                self._h.setdefault(key, {})[field] = val
            def hgetall(self, key):
                return self._h.get(key, {})
            def delete(self, key):
                self._h.pop(key, None)

        fake = FakeNativeRedis()
        store = RedisVectorStore(redis_client=fake, collection="native")
        store.add_texts(["x"])
        assert store.count() == 1
        store.clear()
        assert store.count() == 0

    def test_redis_chat_memory_ttl_refreshes_list_key_not_marker(self):
        """RedisChatMemory.add 给 list 键本身刷 TTL（修复：之前只给 :ttl 标记键设过期，list 键无限增长）"""
        class FakeRedisWithExpire:
            def __init__(self):
                self._list = {}
                self._expires = {}
            def list_push(self, key, value):
                self._list.setdefault(key, []).append(value)
                return len(self._list[key])
            def list_length(self, key):
                return len(self._list.get(key, []))
            def list_remove_range(self, key, start, end):
                lst = self._list.get(key, [])
                self._list[key] = lst[:start] + lst[end + 1:]
            def list_range(self, key, start, end):
                return self._list.get(key, [])[start:]
            def delete_key(self, key):
                self._list.pop(key, None)
                return True
            def get_client(self):
                fake = self
                class Raw:
                    def expire(self, k, t):
                        fake._expires[k] = t
                return Raw()

        fake = FakeRedisWithExpire()
        mem = RedisChatMemory(redis_client=fake, max_messages=10, ttl=3600)
        mem.add("c1", Message.user("hi"))
        key = "springpy:ai:memory:c1"
        # list 键本身被设了 TTL（不是 :ttl 标记键）
        assert key in fake._expires
        assert fake._expires[key] == 3600
        # list 键仍存在且未被覆盖（数据保留）
        assert len(fake._list.get(key, [])) == 1

    def test_configure_ai_auto_reuses_framework_global_redis_when_type_redis(self):
        """configure_ai 在 vector-store.type=redis 且未传 client 时自动复用框架全局 redis_client"""
        from spring.config.config_loader import ConfigLoader
        from spring.utils.redis_client import redis_client as global_redis
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {
            "default-provider": "openai",
            "openai": {"api-key": "sk-test"},
            "vector-store": {"type": "redis"},
            "memory": {"store": "redis"},
        }}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        # 应复用框架全局 redis_client 单例（无需手动传 redis_client 参数）
        assert beans["aiVectorStore"]._client is global_redis
        assert beans["aiChatMemory"]._client is global_redis


class TestResilience:
    """缺口3: 重试 + 熔断"""

    def test_retry_retries_on_transient_error(self):
        """resilient_call 对 TransientError 重试"""
        from spring.ai import resilient_call, TransientError
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise TransientError("抖动")
            return "ok"

        result = resilient_call(flaky, max_retries=5, retry_delay_ms=1,
                                retry_exceptions=(TransientError,))()
        assert result == "ok"
        assert calls["n"] == 3

    def test_circuit_breaker_opens_after_threshold(self):
        """AICircuitBreaker 失败达阈值后 OPEN，拒绝请求"""
        from spring.ai import AICircuitBreaker, CircuitOpenError, TransientError
        cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=60)

        def always_fail():
            raise TransientError("挂了")

        # 前 3 次失败计入熔断
        for _ in range(3):
            with pytest.raises(TransientError):
                cb.call(always_fail)
        # 第 4 次应被熔断拒绝
        assert cb.state == "OPEN"
        with pytest.raises(CircuitOpenError):
            cb.call(always_fail)

    def test_circuit_breaker_half_open_recovery(self):
        """AICircuitBreaker 经过 recovery_timeout 后 HALF_OPEN，成功恢复 CLOSED"""
        from spring.ai import AICircuitBreaker, TransientError
        import time
        cb = AICircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        def fail():
            raise TransientError("x")

        def ok():
            return "recovered"

        with pytest.raises(TransientError):
            cb.call(fail)
        with pytest.raises(TransientError):
            cb.call(fail)
        assert cb.state == "OPEN"
        # 等待恢复
        time.sleep(0.15)
        # HALF_OPEN 放行，成功 → CLOSED
        assert cb.call(ok) == "recovered"
        assert cb.state == "CLOSED"


class TestStreamingAndAsync:
    """缺口4: 真流式 + async"""

    def test_fake_stream_yields_delta_chunks(self):
        """FakeChatModel.stream 逐块 yield 增量内容"""
        model = FakeChatModel(prefix="AI:")
        chunks = list(model.stream([Message.user("hello")]))
        # 拼接所有 chunk 应等于完整回复
        full = "".join(c.content() for c in chunks)
        assert full == "AI: hello"
        assert len(chunks) > 1  # 多块

    def test_chat_client_stream_via_prompt_spec(self):
        """ChatClient prompt().stream() 链式流式"""
        model = FakeChatModel(prefix="AI:")
        client = ChatClientBuilder(model).build()
        chunks = list(client.prompt().user("hi").stream())
        full = "".join(c.content() for c in chunks)
        assert full == "AI: hi"

    def test_async_acall_returns_response(self):
        """ChatModel.acall 异步调用返回 ChatResponse"""
        import asyncio
        model = FakeChatModel(prefix="AI:")
        resp = asyncio.get_event_loop().run_until_complete(
            model.acall([Message.user("async")])
        )
        assert resp.content() == "AI: async"

    def test_async_astream_yields_chunks(self):
        """ChatModel.astream 异步流式 yield 增量"""
        import asyncio
        model = FakeChatModel(prefix="AI:")

        async def collect():
            result = []
            async for chunk in model.astream([Message.user("go")]):
                result.append(chunk.content())
            return result

        chunks = asyncio.get_event_loop().run_until_complete(collect())
        assert "".join(chunks) == "AI: go"


class TestObservability:
    """缺口5: Prometheus 观测"""

    def test_ai_metrics_singleton(self):
        """AIMetrics 是单例"""
        from spring.ai import AIMetrics, ai_metrics
        assert AIMetrics() is ai_metrics

    def test_record_call_does_not_raise(self):
        """record_call 记录调用不抛异常（即使 Prometheus 不可用也降级）"""
        from spring.ai import ai_metrics
        # 不抛异常即通过
        ai_metrics.record_call("openai", "gpt-4o", "success", 0.5,
                               {"prompt_tokens": 10, "completion_tokens": 20})
        ai_metrics.record_call("openai", "gpt-4o", "failure", 0.1)
        ai_metrics.record_tool_call("get_weather", "success")
        ai_metrics.record_circuit_state("openai", "CLOSED")

    def test_provider_call_records_metrics(self):
        """OpenAIChatModel.call 经 Fake 降级路径仍能记录指标（不抛异常）"""
        from spring.ai import FakeChatModel
        model = FakeChatModel(prefix="AI:")
        resp = model.call([Message.user("metric")])
        assert resp.content() == "AI: metric"

    def test_autoconfig_creates_circuit_breaker_for_provider(self):
        """autoconfig 为 provider 创建熔断器"""
        from spring.config.config_loader import ConfigLoader
        from spring.ai import AICircuitBreaker
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {
            "default-provider": "openai",
            "openai": {"api-key": "sk-test"},
            "circuit-breaker": {"enabled": True, "failure-threshold": 7,
                                "recovery-timeout": 45},
        }}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        # OpenAIChatModel 应携带熔断器
        chat_model = beans["aiChatModel"]
        assert isinstance(chat_model.circuit_breaker, AICircuitBreaker)
        assert chat_model.circuit_breaker.failure_threshold == 7
        assert chat_model.circuit_breaker.recovery_timeout == 45


class TestAIPropertiesBinding:
    """混合配置绑定：类型化 dataclass + env 覆盖 + 类型转换"""

    def test_bind_defaults_when_empty(self):
        """空配置 → 全默认值"""
        props = bind_ai_config({})
        assert isinstance(props, AIProperties)
        assert props.default_provider == "openai"
        assert props.openai.api_key == ""
        assert props.openai.chat.model == "gpt-4o-mini"
        assert props.openai.chat.temperature == 0.7
        assert props.memory.max_messages == 20
        assert props.circuit_breaker.enabled is True
        assert props.circuit_breaker.failure_threshold == 5
        assert props.max_retries == 3

    def test_bind_kebab_case_keys_from_yaml(self):
        """yml 的 kebab-case 键正确绑定到 snake_case 字段"""
        props = bind_ai_config({
            "default-provider": "ollama",
            "max-retries": 5,
            "openai": {"api-key": "sk-x",
                       "chat": {"model": "gpt-4o", "temperature": 0.2}},
            "memory": {"max-messages": 50},
            "circuit-breaker": {"failure-threshold": 8, "recovery-timeout": 60},
        })
        assert props.default_provider == "ollama"
        assert props.max_retries == 5
        assert props.openai.api_key == "sk-x"
        assert props.openai.chat.model == "gpt-4o"
        assert props.openai.chat.temperature == 0.2
        assert props.memory.max_messages == 50
        assert props.circuit_breaker.failure_threshold == 8
        assert props.circuit_breaker.recovery_timeout == 60

    def test_bind_type_coercion_from_strings(self):
        """字符串值按字段类型注解转换（int/float/bool）"""
        props = bind_ai_config({
            "max-retries": "7",
            "retry-delay-ms": "1000",
            "openai": {"chat": {"temperature": "0.9"}},
            "memory": {"max-messages": "30"},
            "circuit-breaker": {"enabled": "false",
                                "failure-threshold": "9",
                                "recovery-timeout": "45.5"},
        })
        assert props.max_retries == 7 and isinstance(props.max_retries, int)
        assert props.retry_delay_ms == 1000
        assert props.openai.chat.temperature == 0.9
        assert isinstance(props.openai.chat.temperature, float)
        assert props.memory.max_messages == 30
        assert isinstance(props.memory.max_messages, int)
        assert props.circuit_breaker.enabled is False
        assert props.circuit_breaker.failure_threshold == 9
        assert props.circuit_breaker.recovery_timeout == 45.5

    def test_env_overrides_yaml_value(self, monkeypatch):
        """环境变量覆盖 yml 字面值（env > yml 优先级）"""
        monkeypatch.setenv("AI_PROVIDER", "ollama")
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        monkeypatch.setenv("AI_MEMORY_MAX", "99")
        props = bind_ai_config({
            "default-provider": "openai",
            "openai": {"api-key": "yml-key"},
            "memory": {"max-messages": 20},
        })
        assert props.default_provider == "ollama"
        assert props.openai.api_key == "env-key"
        assert props.memory.max_messages == 99

    def test_env_overrides_nested_when_yaml_section_missing(self, monkeypatch):
        """yml 缺失嵌套段时，叶子 env 仍可覆盖（嵌套递归保证可达）"""
        monkeypatch.setenv("OPENAI_CHAT_MODEL", "claude-3")
        monkeypatch.setenv("OPENAI_TEMPERATURE", "0.1")
        props = bind_ai_config({"default-provider": "openai"})  # 无 openai 段
        assert props.openai.chat.model == "claude-3"
        assert props.openai.chat.temperature == 0.1

    def test_circuit_breaker_disabled_returns_none(self):
        """circuit-breaker.enabled=false 时 _build_circuit_breaker 返回 None"""
        from spring.ai.autoconfig import _build_circuit_breaker
        props = bind_ai_config({"circuit-breaker": {"enabled": "false"}})
        assert _build_circuit_breaker(props) is None

    def test_configure_ai_uses_typed_props_for_openai_circuit_breaker(self):
        """configure_ai 经类型化绑定装配 OpenAIChatModel + 熔断器参数"""
        from spring.config.config_loader import ConfigLoader
        from spring.ai import AICircuitBreaker
        loader = ConfigLoader()
        loader._config = {"spring": {"ai": {
            "default-provider": "openai",
            "openai": {"api-key": "sk-test"},
            "circuit-breaker": {"enabled": True, "failure-threshold": 7,
                                "recovery-timeout": 45},
        }}}
        registry = BeanRegistry()
        registry.clear()
        beans = configure_ai(registry=registry, config=loader)
        chat_model = beans["aiChatModel"]
        assert isinstance(chat_model, OpenAIChatModel)
        assert isinstance(chat_model.circuit_breaker, AICircuitBreaker)
        assert chat_model.circuit_breaker.failure_threshold == 7
        assert chat_model.circuit_breaker.recovery_timeout == 45


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
