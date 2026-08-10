"""
LangChain 模块完整能力演示 - 一键跑通 12 个能力子模块。

本脚本是「小白教学版」demo：不依赖 Spring 容器 / HTTP 服务 / 真实 API Key，
直接用 FakeChatModel + FakeEmbeddingModel 演示 spring.langchain 全部能力的用法。
适合：
- 新手快速理解每个能力 Bean 是什么、怎么用、产出什么
- 集成时作为「对照实现」复制粘贴
- CI 冒烟测试（无网络也能跑通）

运行方式：
    cd e:\\spring\\springbootAI-master\\springbootAI-master
    set AI_ALLOW_FAKE=true
    python -m example_langchain.demo.langchain_full_demo

或直接：
    python example_langchain/demo/langchain_full_demo.py

章节：
  1. 适配层（springbootAI ↔ langchain 双向桥接）
  2. Prompt 模板（字符串/对话/Few-shot）
  3. Chain（LLMChain/Conversation/Sequential/Math）
  4. Agent（ReAct/工具调用）
  5. Memory（buffer/window/summary/token-buffer）
  6. OutputParser（list/datetime/json/pydantic/enum）
  7. VectorStore（inmemory 入库 + 检索 + as_retriever）
  8. Retriever（similarity）
  9. IndexService（一键 RAG：建库 + 查询）
 10. Tools（StructuredTool / Tool / ToolRegistry）
 11. DocumentLoader（Text/CSV/JSON）
 12. Utility（懒加载第三方工具）
 13. Callbacks（stdout/streaming/file）
 14. SafeEval（安全算术求值，防沙箱逃逸）
"""
import os
import sys
import warnings
from pathlib import Path

# 屏蔽 langchain classic 弃用告警（迁移目的即兼容旧 API，告警无意义）
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")
try:
    from langchain_core._api import LangChainDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except ImportError:
    pass

# 把项目根目录加入 sys.path，便于直接 python xxx.py 运行
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 无 API Key 时降级 FakeChatModel（保证 demo 可独立运行）
os.environ.setdefault("AI_ALLOW_FAKE", "true")

from spring.ai.providers import FakeChatModel, FakeEmbeddingModel
from spring.langchain.adapters import (
    SpringChatModelToLangChain, SpringEmbeddingToLangChain,
    LangChainModelToSpring, LangChainEmbeddingToSpring,
    to_langchain_model, to_langchain_embeddings,
    to_spring_model, to_spring_embeddings,
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
from spring.langchain.partners import list_partners, list_available_partners


# ==================== 公共：构造 Fake 模型（无需 API Key） ====================

def build_fake_model():
    """构造 FakeChatModel（前缀 [AI]）+ FakeEmbeddingModel（8 维）。

    FakeChatModel 行为：回复 "[AI] <用户最后一条消息>"，确定性输出。
    FakeEmbeddingModel 行为：基于文本哈希生成归一化向量，相同文本相同向量。
    """
    spring_chat = FakeChatModel(prefix="[AI]")
    spring_emb = FakeEmbeddingModel(dim=8)
    return spring_chat, spring_emb


def banner(title):
    """打印章节分隔横幅。"""
    line = "=" * 70
    print(f"\n{line}\n  {title}\n{line}")


# ==================== 1. 适配层 ====================

def demo_adapters():
    """springbootAI ChatModel/EmbeddingModel ↔ langchain BaseChatModel/Embeddings 双向桥接。

    用途：让 springbootAI 装配的模型 Bean 能被 langchain 的 Chain/Agent 直接消费，
         反过来让 langchain 生态的 partner 模型能注入 springbootAI ChatClient。
    """
    banner("1. 适配层 Adapters - springbootAI ↔ langchain 双向桥接")
    spring_chat, spring_emb = build_fake_model()

    # 1.1 springbootAI -> langchain（最常用：让 LLMChain 用 springbootAI 模型）
    lc_model = to_langchain_model(spring_chat)
    from langchain_core.messages import HumanMessage
    result = lc_model.invoke([HumanMessage(content="你好")])
    print(f"  [spring→lc] 模型回复: {result.content}")
    print(f"  [spring→lc] _llm_type: {lc_model._llm_type}")

    # 1.2 嵌入桥接
    lc_emb = to_langchain_embeddings(spring_emb)
    vec = lc_emb.embed_query("测试文本")
    print(f"  [spring→lc] 嵌入维度: {len(vec)}")

    # 1.3 langchain -> springbootAI（让 partner 模型注入 ChatClient）
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    fake_lc = FakeListChatModel(responses=["langchain-says-hi"])
    spring_model = to_spring_model(fake_lc)
    from spring.ai.core import Message
    resp = spring_model.call([Message.user("ping")])
    print(f"  [lc→spring] 模型回复: {resp.content()}")
    print(f"  [lc→spring] provider 元数据: {resp.metadata.get('provider')}")

    # 1.4 isinstance 校验（适配器实现了 langchain 接口）
    from langchain_core.embeddings import Embeddings
    print(f"  [校验] 嵌入适配器是否为 langchain Embeddings: {isinstance(lc_emb, Embeddings)}")


# ==================== 2. Prompt 模板 ====================

def demo_prompts():
    """3 类 Prompt 模板创建。

    用途：把 prompt 字符串/对话结构/示例模板统一封装，供 Chain 消费。
    """
    banner("2. Prompt 模板 - 字符串/对话/Few-shot")
    # 2.1 字符串模板（自动从 {var} 解析变量）
    tpl = PromptTemplateFactory.create_prompt_template("Q: {q}\nA:")
    print(f"  [字符串模板] 变量: {tpl.input_variables}")
    print(f"  [字符串模板] 格式化: {tpl.format(q='你好')}")

    # 2.2 对话模板（支持 dict 和 tuple 两种形态）
    chat_tpl = PromptTemplateFactory.create_chat_prompt_template([
        {"role": "system", "content": "你是 {role}"},
        {"role": "user", "content": "{question}"},
    ])
    print(f"  [对话模板] 变量: {chat_tpl.input_variables}")
    msgs = chat_tpl.format_messages(role="翻译官", question="hello")
    print(f"  [对话模板] 消息数: {len(msgs)}, 首条角色: {msgs[0].type}")

    # 2.3 Few-shot 模板（带示例）
    example_prompt = PromptTemplateFactory.create_prompt_template(
        "输入: {input}\n输出: {output}")
    few_shot = PromptTemplateFactory.create_few_shot_prompt_template(
        examples=[{"input": "你好", "output": "Hello"}],
        example_prompt=example_prompt,
        suffix="输入: {word}\n输出:",
        input_variables=["word"],
    )
    print(f"  [Few-shot] 变量: {few_shot.input_variables}")


# ==================== 3. Chain ====================

def demo_chains():
    """Chain 服务 - LLMChain / Conversation / Sequential / Math。

    用途：把 prompt + llm + memory 组合成可执行链，是 langchain classic 的核心。
    """
    banner("3. Chain - LLMChain/Conversation/Sequential/Math")
    spring_chat, _ = build_fake_model()
    lc_model = to_langchain_model(spring_chat)
    svc = ChainService(lcLangChainModel=lc_model)

    # 3.1 LLMChain 一行调用（字符串模板自动包装）
    result = svc.run_llm_chain("回答: {q}", q="什么是 Spring Boot")
    print(f"  [LLMChain] 结果: {result}")

    # 3.2 带 memory 的对话
    mem = MemoryFactory.create("buffer")
    r1 = svc.run_conversation("我叫张三", memory=mem)
    r2 = svc.run_conversation("我叫什么", memory=mem)
    print(f"  [Conversation] 第1轮: {r1}")
    print(f"  [Conversation] 第2轮（复用 memory）: {r2}")

    # 3.3 顺序链（多步串联）
    from spring.langchain.prompts.templates import PromptTemplateFactory
    c1 = svc.create_llm_chain(
        PromptTemplateFactory.create_prompt_template("步骤1: {input}"),
        output_key="s1")
    c2 = svc.create_llm_chain(
        PromptTemplateFactory.create_prompt_template("步骤2: {s1}"),
        output_key="s2")
    seq = svc.create_sequential_chain(
        chains=[c1, c2], input_variables=["input"], output_variables=["s2"])
    seq_result = seq.invoke({"input": "数据"})
    print(f"  [Sequential] 最终输出: {seq_result.get('s2')}")

    # 3.4 数学链（FakeChatModel 无法真算，会降级）
    try:
        math_chain = svc.create_llm_math_chain()
        math_result = math_chain.invoke({"question": "2 + 3"})
        print(f"  [LLMMath] 结果: {math_result}")
    except Exception as exc:
        print(f"  [LLMMath] Fake 模型无法计算（预期）: {type(exc).__name__}")


# ==================== 4. Agent ====================

def demo_agents():
    """Agent 服务 - ReAct / 工具调用。

    用途：让 LLM 自主选择工具完成任务（搜索/计算/查询等）。
    """
    banner("4. Agent - ReAct 工具调用")
    spring_chat, _ = build_fake_model()
    lc_model = to_langchain_model(spring_chat)
    svc = AgentService(lcLangChainModel=lc_model)

    # 定义两个工具
    def search(query: str) -> str:
        """搜索工具 - 根据关键词返回结果。"""
        return f"搜索结果: {query}"

    def calculate(expression: str) -> str:
        """计算工具 - 算术表达式求值。"""
        try:
            return str(eval(expression))  # demo 仅演示，生产用 safe_eval_arithmetic
        except Exception:
            return "无法计算"

    tools = [
        ToolFactory.from_function(search, name="search", description="搜索信息"),
        ToolFactory.from_function(calculate, name="calculator",
                                  description="数学计算"),
    ]
    executor = svc.create_agent(tools, agent_type="react", max_iterations=3)
    result = svc.run_agent(executor, "现在几点")
    print(f"  [ReAct Agent] 结果: {result}")

    # 支持的 agent 类型
    print(f"  [支持的 agent 类型]: {svc.supported_agent_types()}")


# ==================== 5. Memory ====================

def demo_memory():
    """会话记忆 - buffer / window / summary / token-buffer。

    用途：让 Chain/Agent 记住多轮对话历史。
    """
    banner("5. Memory - buffer/window/summary/token-buffer")
    spring_chat, _ = build_fake_model()
    lc_model = to_langchain_model(spring_chat)

    # 5.1 buffer（完整历史）
    mem = MemoryFactory.create("buffer")
    mem.save_context({"input": "你好"}, {"output": "你好！"})
    print(f"  [buffer] 消息数: {len(mem.chat_memory.messages)}")

    # 5.2 buffer-window（滑动窗口）
    win = MemoryFactory.create("buffer-window", max_messages=2)
    for i in range(5):
        win.save_context({"input": f"第{i}轮"}, {"output": f"回答{i}"})
    loaded = win.load_memory_variables({})
    print(f"  [buffer-window k=2] 加载消息数: {len(loaded.get(win.memory_key, []))}")

    # 5.3 summary（需要 llm 做摘要）
    try:
        summ = MemoryFactory.create("summary", llm=lc_model)
        summ.save_context({"input": "今天天气好"}, {"output": "是的，适合出门"})
        print(f"  [summary] 创建成功，类型: {type(summ).__name__}")
    except Exception as exc:
        print(f"  [summary] 失败: {exc}")

    print(f"  [支持的 memory 类型]: {MemoryFactory.supported_types()}")


# ==================== 6. OutputParser ====================

def demo_parsers():
    """输出解析器 - list / datetime / json / pydantic / enum。

    用途：把 LLM 的自由文本输出解析为结构化数据。
    """
    banner("6. OutputParser - list/datetime/json/pydantic/enum")
    # 6.1 逗号列表
    p = OutputParserFactory.create_comma_list_parser()
    print(f"  [comma-list] 解析 'a, b, c': {p.parse('a, b, c')}")

    # 6.2 datetime
    dp = OutputParserFactory.create_datetime_parser()
    print(f"  [datetime] 解析 '2026-08-10T12:00:00.000Z': {dp.parse('2026-08-10T12:00:00.000Z')}")

    # 6.3 json
    jp = OutputParserFactory.create_json_parser()
    print(f"  [json] 解析 '{{\"a\": 1}}': {jp.parse('{\"a\": 1}')}")

    # 6.4 pydantic 结构化
    from pydantic import BaseModel
    class Person(BaseModel):
        name: str
        age: int
    pp = OutputParserFactory.create_pydantic_parser(Person)
    print(f"  [pydantic] 格式说明前 80 字: {pp.get_format_instructions()[:80]}...")

    # 6.5 enum
    from enum import Enum
    class Color(Enum):
        RED = "red"
        GREEN = "green"
    ep = OutputParserFactory.create_enum_parser(enum_class=Color)
    print(f"  [enum] 解析 'red': {ep.parse('red')}")


# ==================== 7. VectorStore ====================

def demo_vectorstores():
    """向量库 - inmemory 入库 + 相似度检索 + as_retriever。

    用途：RAG 的存储层，把文档向量化后按相似度检索。
    """
    banner("7. VectorStore - inmemory 入库/检索/Retriever")
    _, spring_emb = build_fake_model()
    lc_emb = to_langchain_embeddings(spring_emb)

    # 7.1 从文本建库
    store = VectorStoreFactory.from_texts(
        "inmemory",
        ["Spring Boot 是 Java 框架", "Python 是解释型语言",
         "Spring AI 集成 LangChain"],
        lc_emb)
    print(f"  [inmemory] 文档数: {store.count()}")

    # 7.2 相似度检索（支持 k 参数）
    results = store.similarity_search("Spring", k=2)
    print(f"  [检索] 查询 'Spring' k=2 命中: {[d.content for d in results]}")

    # 7.3 转 Retriever
    retriever = store.as_retriever(search_kwargs={"k": 1})
    docs = retriever.invoke("Python")
    print(f"  [Retriever] invoke 'Python' 命中: {[d.content for d in docs]}")

    # 7.4 支持的向量库类型
    print(f"  [支持的向量库]: {VectorStoreFactory.supported_types()}")


# ==================== 8. Retriever ====================

def demo_retrievers():
    """检索器工厂 - similarity / multi-query / ensemble 等。

    用途：把向量库包装成 Retriever，供 RetrievalQA 消费。
    """
    banner("8. Retriever - similarity 检索")
    _, spring_emb = build_fake_model()
    lc_emb = to_langchain_embeddings(spring_emb)
    store = VectorStoreFactory.from_texts("inmemory", ["文档A", "文档B"], lc_emb)

    # similarity 检索器
    retriever = RetrieverFactory.create(
        retriever_type="similarity", vector_store=store, k=2)
    docs = retriever.invoke("文档")
    print(f"  [similarity] 命中 {len(docs)} 条文档")

    print(f"  [支持的检索器]: {RetrieverFactory.supported_types()}")


# ==================== 9. IndexService（一键 RAG） ====================

def demo_index_service():
    """IndexService - 一键 RAG：建库 + 查询。

    用途：封装 VectorStore + Retriever + RetrievalQA，一行完成 RAG 流水线。
    """
    banner("9. IndexService - 一键 RAG")
    spring_chat, spring_emb = build_fake_model()
    lc_model = to_langchain_model(spring_chat)
    lc_emb = to_langchain_embeddings(spring_emb)
    idx = IndexService(lcEmbeddings=lc_emb, lcLangChainModel=lc_model)

    # 9.1 从文本建库
    store = idx.create_from_texts(["LangChain 是 LLM 框架", "Spring Boot 是 Java 框架"])
    print(f"  [建库] 文档数: {store.count()}")

    # 9.2 查询
    results = idx.query(store, "LangChain", k=1)
    print(f"  [查询] 命中 {len(results)} 条")
    for r in results:
        if hasattr(r, "content"):
            print(f"    - {r.content}")
        else:
            print(f"    - {r}")


# ==================== 10. Tools ====================

def demo_tools():
    """工具 - StructuredTool / Tool / ToolRegistry。

    用途：把 Python 函数转为 langchain BaseTool，供 Agent 调用。
    """
    banner("10. Tools - StructuredTool/Tool/ToolRegistry")
    # 10.1 from_function（自动从签名+docstring 生成 schema）
    def add(a: int, b: int) -> int:
        """两数相加。"""
        return a + b
    tool = ToolFactory.from_function(add, name="add", description="加法")
    print(f"  [StructuredTool] name={tool.name}, invoke(1,2)={tool.invoke({'a': 1, 'b': 2})}")

    # 10.2 create_tool（简单形式）
    simple = ToolFactory.create_tool("echo", lambda x: x, description="回显")
    print(f"  [Tool] name={simple.name}")

    # 10.3 ToolRegistry（收集多个工具）
    reg = ToolRegistry()
    reg.add_function(add, name="add", description="加法")
    reg.add_function(lambda x: x.upper(), name="upper", description="大写")
    print(f"  [ToolRegistry] 工具名: {reg.names()}")


# ==================== 11. DocumentLoader ====================

def demo_loaders(tmp_path):
    """文档加载器 - Text / CSV / JSON。

    用途：把文件内容加载为 langchain Document，供向量库/摘要链消费。
    """
    banner("11. DocumentLoader - Text/CSV/JSON")
    loader = DocumentLoaderRegistry()

    # 11.1 Text 加载
    txt_file = tmp_path / "demo.txt"
    txt_file.write_text("Hello LangChain\n第二行内容", encoding="utf-8")
    docs = loader.load_text(str(txt_file))
    print(f"  [Text] 加载 {len(docs)} 个文档, 内容: {docs[0].page_content[:30]}")

    # 11.2 CSV 加载
    csv_file = tmp_path / "demo.csv"
    csv_file.write_text("name,age\n张三,20\n李四,25", encoding="utf-8")
    try:
        csv_docs = loader.load_csv(str(csv_file))
        print(f"  [CSV] 加载 {len(csv_docs)} 行")
    except Exception as exc:
        print(f"  [CSV] 失败（缺依赖？）: {type(exc).__name__}")

    # 11.3 JSON 加载（JSONLoader 需 jq_schema 指定提取字段）
    json_file = tmp_path / "demo.json"
    json_file.write_text('[{"text": "条目1"}, {"text": "条目2"}]', encoding="utf-8")
    try:
        # jq_schema='.text' 表示从每个对象取 text 字段
        json_docs = loader.load("json", str(json_file), jq_schema=".text")
        print(f"  [JSON] 加载 {len(json_docs)} 个文档, 首条: {json_docs[0].page_content}")
    except (ImportError, Exception) as exc:
        print(f"  [JSON] 失败（缺 jq 依赖或 schema）: {type(exc).__name__}")


# ==================== 12. Utility ====================

def demo_utilities():
    """Utility 注册表 - 懒加载第三方工具（搜索/百科/计算）。

    用途：把 langchain_community 的实用工具统一注册，按需创建。
    """
    banner("12. Utility - 懒加载第三方工具")
    print(f"  [支持的 Utility]: {UtilityRegistry.supported_types()}")
    # 实际创建会触发依赖导入，缺失时抛 ImportError（带安装提示）
    try:
        ddg = UtilityRegistry.create("duckduckgo")
        print(f"  [DuckDuckGo] 创建成功: {type(ddg).__name__}")
    except ImportError as exc:
        print(f"  [DuckDuckGo] 未安装（预期）: {str(exc)[:80]}")


# ==================== 13. Callbacks ====================

def demo_callbacks(tmp_path):
    """回调 - stdout / streaming / file。

    用途：观察 Chain/Agent 的执行过程（调试用）。
    """
    banner("13. Callbacks - stdout/streaming/file")
    # 13.1 stdout 回调
    stdout_cb = CallbackRegistry.create_stdout_handler()
    print(f"  [stdout] 类型: {type(stdout_cb).__name__}")

    # 13.2 streaming 回调
    stream_cb = CallbackRegistry.create_streaming_stdout_handler()
    print(f"  [streaming] 类型: {type(stream_cb).__name__}")

    # 13.3 file 回调
    log_file = tmp_path / "callback.log"
    try:
        file_cb = CallbackRegistry.create_file_handler(str(log_file))
        print(f"  [file] 类型: {type(file_cb).__name__}")
    except Exception as exc:
        print(f"  [file] 失败: {type(exc).__name__}")

    # 13.4 注册表
    reg = CallbackRegistry()
    reg.register(stdout_cb).register(stream_cb)
    print(f"  [Registry] 已注册 {len(reg.all())} 个回调")


# ==================== 14. SafeEval（安全算术求值） ====================

def demo_safe_eval():
    """安全算术求值 - AST 遍历替代 eval，防沙箱逃逸。

    用途：calculator/math 工具用，避免 eval() 被注入恶意代码。
    """
    banner("14. SafeEval - AST 安全算术求值")
    from example_langchain.service.LangChainAgentService import safe_eval_arithmetic

    # 14.1 正常算术
    expressions = ["2 + 3", "10 * 4", "100 / 7", "2 ** 10", "(1 + 2) * 3"]
    for expr in expressions:
        result = safe_eval_arithmetic(expr)
        print(f"  [算术] {expr} = {result}")

    # 14.2 攻击手法全部拒绝
    attacks = [
        "__import__('os').system('rm -rf /')",  # 模块导入
        "open('/etc/passwd').read()",            # 文件读取
        "().__class__.__bases__[0].__subclasses__()",  # 沙箱逃逸
        "eval('1+1')",                           # 嵌套 eval
    ]
    for attack in attacks:
        try:
            safe_eval_arithmetic(attack)
            print(f"  [攻击] ⚠️ 未拒绝: {attack}")
        except (ValueError, Exception) as exc:
            print(f"  [攻击] ✅ 已拒绝: {attack[:40]}... ({type(exc).__name__})")


# ==================== 15. Partner 注册表 ====================

def demo_partners():
    """Partner 注册表 - 30+ 第三方模型提供商懒加载。

    用途：在 application.yml 配置 spring.langchain.partners.<name> 即可启用。
    """
    banner("15. Partner - 30+ 第三方模型提供商")
    all_partners = list_partners()
    available = list_available_partners()
    print(f"  [注册表] 总数: {len(all_partners)}")
    print(f"  [已安装] 数量: {len(available)}")
    print(f"  [主流 partner] openai/anthropic/ollama/deepseek/zhipu/tongyi/moonshot")
    print(f"  [前 10 个]: {all_partners[:10]}")


# ==================== 主入口 ====================

def main():
    """运行全部 demo 章节。"""
    print("=" * 70)
    print("  SpringBootAI LangChain 模块完整能力演示".center(60))
    print("  （使用 FakeChatModel/FakeEmbeddingModel，无需 API Key）")
    print("=" * 70)

    import tempfile
    tmp_path = Path(tempfile.mkdtemp())

    # 依次运行 15 个章节
    demo_adapters()
    demo_prompts()
    demo_chains()
    demo_agents()
    demo_memory()
    demo_parsers()
    demo_vectorstores()
    demo_retrievers()
    demo_index_service()
    demo_tools()
    demo_loaders(tmp_path)
    demo_utilities()
    demo_callbacks(tmp_path)
    demo_safe_eval()
    demo_partners()

    print("\n" + "=" * 70)
    print("  ✅ 全部 15 个章节演示完成！".center(60))
    print("=" * 70)
    print("""
  下一步：
  - 启动完整 HTTP 服务：python example_langchain/Application.py
  - 访问接口：POST http://localhost:8081/api/lc/chat  body={"message":"你好"}
  - 查看测试：python -m pytest tests/test_langchain_module.py tests/test_langchain_ext.py
  - 配置真实模型：在 application.yml 设置 spring.ai.openai.api-key
""")


if __name__ == "__main__":
    main()
