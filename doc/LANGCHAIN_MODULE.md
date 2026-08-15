# SpringBootAI LangChain 模块使用指南 —— 小白也能看懂

> 把 [LangChain](https://github.com/langchain-ai/langchain) 全套能力（Chains / Agents / Memory / Retrievers / VectorStores / Parsers / Loaders）封装为 Spring 风格 Bean，配合 30+ 第三方模型提供商（OpenAI / Anthropic / Ollama / DeepSeek / ZhipuAI / Tongyi …）开箱即用。
> 安装：`pip install springbootAI[langchain]` ｜ 框架版本：SpringBootAI 2.2.6 / LangChain 模块 2.2.6

---

## 概念地图（先看这张图，再看下文）

```
                        ┌──────────────────────────────────┐
                        │     你的 Python 应用              │
                        │  @Service 类 → @Autowired 注入    │
                        └──────────────┬───────────────────┘
                                       │
                    configure_ai() ──→ configure_langchain()
                         │                     │
                         ▼                     ▼
                  spring.ai 模块        spring.langchain 模块
                  (ChatModel)           (LangChain 全家桶)
                         │                     │
                         │     ┌───────────────┤
                         │     │  转接头(Adapter)│
                         │     └───────┬───────┘
                         │             │
                         ▼             ▼
              ┌─────────────────────────────────────────┐
              │         LangChain 能力工厂               │
              │                                         │
              │  Chain（流水线）──── Agent（手脚+大脑）    │
              │  Memory（记性）──── Parser（文本→对象）   │
              │  Loader（搬运工）── Retriever（查资料）   │
              │  VectorStore（资料柜）─ Index（一键RAG）  │
              │  Tool（工具）───── Utility（现成工具包）  │
              │  Callback（监听器）                      │
              └─────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────────────────────────┐
              │         30+ Partner 提供商               │
              │  OpenAI / Anthropic / Ollama / DeepSeek  │
              │  ZhipuAI / Tongyi / Mistral / Cohere... │
              │  （按需懒加载，不用的不装）               │
              └─────────────────────────────────────────┘
```

---

## 阅读前准备

第一次使用请先读完 [新手入门指南](BEGINNER_GUIDE.md) 的普通 HTTP 接口，再学习 [AI 模块使用指南](AI_MODULE.md) 的基础聊天，最后读本文件。

本模块**复用** `spring.ai` 装配出的 `aiChatModel` / `aiEmbeddingModel` Bean 作为底层模型，再做一层 LangChain 适配。因此**没有真实 API Key 也能跑通**——设置 `AI_ALLOW_FAKE=true` 后会降级 `FakeChatModel`，整个 LangChain 流程依然可演示。

学习顺序建议：基础问答 → Prompt 模板 → Memory 多轮 → Chain → Agent → RAG → 输出解析 → 自定义 Partner。

---

## 第〇章：这个模块是干什么的？（大白话版）

### 一句话概括

**让你的 SpringBootAI 应用直接使用 LangChain 生态的全部能力**，而不用自己手动 `from langchain.xxx import ...` 再去管实例化和依赖注入。

### 为什么要用它？（三个痛点）

LangChain 本身是一个庞大的 Python 库（monorepo，~28 个 classic 子模块 + 30+ partner 包，数千个文件）。如果直接在代码里用，你会面临三个痛点：

1. **每个组件都要自己 `new` 一遍**：`ChatOpenAI()`、`ConversationBufferMemory()`、`FAISS.from_texts()`…… 散落在各处，重复且难以替换。
2. **没法和 SpringBootAI 的 IoC 容器协作**：`@Service` 类想用 LangChain 的 Chain，必须手动传参或全局变量，破坏分层。
3. **30+ partner 提供商的依赖管理很烦**：每个厂商一个 `langchain-xxx` 包，全装上会拖慢启动，按需装又容易漏。

本模块把这三件事一次性解决：

| 痛点 | 解决方式 |
|------|----------|
| 手动 new 组件 | 把每个组件封装为 `@Service` / `@Component` Bean，由 `configure_langchain()` 一次装配 |
| IoC 不协作 | 全部 Bean 注册到 `BeanRegistry` + `ApplicationContext.bean_factory`，可被 `@Autowired` 注入 |
| partner 管理 | 用一张注册表 `PARTNER_REGISTRY` 描述元数据，按 `application.yml` 配置懒加载 |

### 里面的概念（新手比喻）

| 术语 | 大白话 | 比喻 |
|------|--------|------|
| **LangChain** | 一个流行的 Python AI 框架，提供 Chain / Agent / Memory 等抽象 | 一整套现成工具箱 |
| **Partner（提供商）** | 提供大模型 API 的厂商（OpenAI、Anthropic、Ollama、智谱、通义…） | 模型供货商 |
| **Chain（链）** | 把多个步骤串起来执行的任务流（先翻译再总结） | 工厂流水线 |
| **Agent（代理）** | 让模型自己决定调用哪个工具来完成任务 | 会用工具的助手 |
| **Memory（记忆）** | 让对话能记住前几轮的内容 | 记性 |
| **Prompt 模板** | 带占位符的提示词，运行时填入变量 | 填空题模板 |
| **OutputParser（输出解析）** | 把模型返回的文本解析成 Python 对象（列表/日期/JSON/Pydantic） | 文本翻译器 |
| **DocumentLoader（文档加载）** | 从 txt / csv / pdf / 网页 / 目录读取文档 | 资料搬运工 |
| **Retriever（检索器）** | 从向量库里捞出和问题最相关的几段文档 | 查资料 |
| **VectorStore（向量库）** | 存文档向量并支持相似度检索的库（FAISS / Chroma / Redis…） | 资料索引柜 |
| **Index（索引）** | 一键把文档入库 + 检索 + 问答的快捷入口 | 一键 RAG |
| **Tool（工具）** | 让 Agent 调用的 Python 函数（查天气、算数学） | 手脚 |
| **Utility（工具集）** | LangChain 内置的现成工具（SerpAPI、Wikipedia、Python REPL） | 现成工具包 |
| **Callback（回调）** | 挂在模型调用流程上的钩子（打日志、流式输出、写文件） | 监听器 |
| **Adapter（适配器）** | springbootAI 模型 ↔ langchain 模型的双向桥接（就像 USB-C 转 HDMI 的转接头） | 转接头 |

### 新手三步走：从零跑通第一个 LangChain 程序

**第 1 步：安装依赖**

```bash
pip install -r requirements-ai.txt
# 至少需要 langchain-core / langchain-classic；可选 langchain-openai / langchain-community 等
```

**第 2 步：用"假模型"跑通（不花钱、不联网）**

```bash
# Windows PowerShell
$env:AI_ALLOW_FAKE = "true"
# Linux / macOS
export AI_ALLOW_FAKE=true
```

```python
from spring.context.registry import BeanRegistry
from spring.ai.autoconfig import configure_ai
from spring.langchain.autoconfig import configure_langchain

registry = BeanRegistry()
configure_ai(registry=registry)              # 1. 装配 spring.ai（降级 FakeChatModel）
beans = configure_langchain(registry=registry)  # 2. 装配 spring.langchain

chain_service = beans["lcChainService"]      # 拿到 ChainService Bean
print(chain_service.run_llm_chain("你好"))     # 用 LLMChain 跑一句话
# 输出: [AI] 你好
```

**第 3 步：接上真实模型（需要 API Key）**

```bash
export AI_PROVIDER=openai
export OPENAI_API_KEY=sk-你的真实key
```

无需改一行代码，`configure_ai()` 会自动从环境变量读取真实 Key 并装配真实模型；`configure_langchain()` 的 `default-llm=auto` 会复用 `aiChatModel` 桥接为 langchain `BaseChatModel`。

到这里，你就已经把整个 LangChain 能力装进了 SpringBootAI 容器。

### 新手常见误区

- ❌ 以为要自己 `import langchain.xxx` 再 `new` → ✅ 全部走 `@Autowired` 注入 `lc*Service` Bean
- ❌ 直接在 Controller 里写 LangChain 代码 → ✅ Controller 只调 Service，Service 通过 `@Autowired` 拿 `lcChainService`
- ❌ 30 个 partner 全装上拖慢启动 → ✅ 按需在 `application.yml` 的 `spring.langchain.partners` 下配置，未配置的不加载
- ❌ 以为 `lcLangChainModel` 是 springbootAI 模型 → ✅ 它是**langchain `BaseChatModel`**（由 `aiChatModel` 桥接而来）；要 springbootAI 模型请用 `aiChatModel`
- ❌ RAG 流程忘记配嵌入模型 → ✅ `configure_ai` 默认会装 `aiEmbeddingModel`，缺失时 RAG 会告警但不崩溃

---

## 第1章：模块全景

```
spring.langchain/
├── core.py              # LangChainCore 统一核心入口（构建器模式 + 一站式 API）
├── adapters.py          # 双向桥接：springbootAI ↔ langchain 模型/嵌入/向量库
├── partners.py          # 30+ Partner 提供商工厂注册表（懒加载）
├── autoconfig.py        # 从 application.yml 装配全部 lc* Bean
├── prompts/templates.py # PromptTemplate / ChatPromptTemplate / FewShot 工厂
├── chains/services.py   # LLMChain / ConversationChain / RetrievalQA / ConversationalRetrieval /
│                        # SequentialChain / APIChain / ConstitutionalChain / MultiPromptChain /
│                        # FlareChain / MapReduceChain / LLMMathChain / SummarizeChain
├── agents/services.py   # ReAct / chat-zero-shot-react / conversational / openai-tools /
│                        # structured-chat / self-ask-with-search / xml Agent
├── memory/memory.py     # buffer / summary / buffer-window / token-buffer / entity /
│                        # combined / read-only-shared
├── parsers/parsers.py   # comma-list / datetime / json / pydantic / enum
├── loaders/loaders.py   # text / csv / pdf / web / directory / json / markdown / word
├── retrievers/retrievers.py  # similarity / multi-query / contextual-compression /
│                              # self-query / time-weighted / ensemble
├── vectorstores/stores.py    # FAISS / Chroma / Pinecone / Weaviate / PGVector / Redis / inmemory
├── indexes/index.py     # VectorStoreIndexCreator 一键 RAG
├── tools/tools.py       # langchain Tool 与 springbootAI @Tool 互转
├── utilities/utils.py   # SerpAPI / DuckDuckGo / Wikipedia / PythonREPL / SQLDatabase / Arxiv
└── callbacks/handlers.py# StdOut / StreamingStdOut / File 回调
```

设计原则（与 Spring AI 对齐）：

- **配置即启用**：在 `application.yml` 写一段 `spring.langchain.partners.<name>` 即可启用一个厂商，零代码。
- **懒加载**：所有 partner 包、外部向量库均按需 `importlib.import_module`，缺失时抛带 `pip install` 提示的 `ImportError`，不污染全局启动。
- **双重注册**：每个 Bean 同时注册到 `BeanRegistry`（`registry.get(name)` 直取）和 `ApplicationContext.bean_factory`（`@Autowired` 按名称/类型注入），兼容两套用法。
- **降级友好**：无 API Key 时 `aiChatModel` 自动降级 `FakeChatModel`，整个 LangChain 流程仍可演示；某 partner 嵌入不可用时只告警不阻塞聊天。

### LangChainCore 统一核心入口

`LangChainCore` 是把分散在 13 个子模块的能力汇聚到一个对象上的统一编程入口：

```python
from spring.langchain.core import LangChainCore, create_langchain_core

# 方式 1：构建器模式（推荐）
core = (LangChainCore.builder()
        .with_model(lc_model)
        .with_tools([calculator_tool, search_tool])
        .with_agent_type("react")
        .build())

# 方式 2：快速创建
core = create_langchain_core(lc_model)

# 方式 3：从 application.yml 自动配置
core = LangChainCore.from_autoconfig()
```

**核心能力**：

| 方法 | 用途 | 大白话 |
|------|------|--------|
| `core.chat("hello")` | 便捷对话 | 一句话聊天 |
| `core.agent_chat("用搜索查天气")` | Agent 执行 | 让 Agent 自己决定怎么查 |
| `core.stream("hello")` | 流式对话 | 逐字输出 |
| `core.rag_pipeline("问题", documents=[...])` | 一站式 RAG | 入库+检索+回答一条龙 |
| `core.chains.create_llm_chain(...)` | Chain 创建 | 创建流水线 |
| `core.agents.create_react_agent(...)` | Agent 创建 | 创建助手 |
| `core.memory.create("buffer")` | Memory 创建 | 创建记性 |
| `core.loaders.load("pdf", "doc.pdf")` | 文档加载 | 读文件 |
| `core.retrievers.create("similarity", ...)` | 检索器创建 | 创建查资料的 |
| `core.vector_stores.from_texts("faiss", ...)` | 向量库创建 | 创建资料柜 |

**懒加载**：`chains`、`agents`、`memory` 等 11 个子模块属性在首次访问时才初始化，减少启动开销。`set_model()` 可热替换模型并自动刷新所有依赖它的子模块。

**响应类型**：`LangChainResponse` 统一封装 Chain/Agent 的返回结果：

```python
response: LangChainResponse = core.chat("什么是 SpringBootAI？")
print(response.output)           # 主输出文本
print(response.content)          # 同 output（兼容 spring.ai 命名）
print(response.metadata)          # {"chain_type": "llm", ...}
print(response.intermediate_steps)  # Agent 中间推理步骤
```

---

## 第2章：配置（application.yml）—— 一步一步配好

### 第1步：看懂完整配置

完整配置块已追加到项目根 `application.yml`：

```yaml
spring:
  langchain:
    enabled: ${LC_ENABLED:true}
    # default-llm: auto=复用 spring.ai 的 aiChatModel；或指定 partner 名（openai/anthropic/ollama/...）
    default-llm: ${LC_DEFAULT_LLM:auto}
    chains:
      default-verbose: ${LC_CHAIN_VERBOSE:false}
    agents:
      # react | chat-zero-shot-react | openai-functions | self-ask-with-search
      default-type: ${LC_AGENT_TYPE:react}
      max-iterations: ${LC_AGENT_MAX_ITER:10}
    vector-store:
      # inmemory | faiss | chroma | redis | pinecone | weaviate | pgvector
      type: ${LC_VECTOR_STORE:faiss}
      persist-dir: ${LC_PERSIST_DIR:./data/vectors}
      collection: ${LC_COLLECTION:default}
    retriever:
      # similarity | multi-query | contextual-compression | self-query | time-weighted | ensemble
      type: ${LC_RETRIEVER:similarity}
      k: ${LC_RETRIEVER_K:4}
    memory:
      # buffer | summary | buffer-window | token-buffer
      type: ${LC_MEMORY:buffer}
      max-messages: ${LC_MEMORY_MAX:20}
    # 各 partner 提供商配置：按 name 启用并配 key/model
    partners:
      openai:
        api-key: ${OPENAI_API_KEY:}
        model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
        temperature: ${OPENAI_TEMPERATURE:0.7}
      ollama:
        base-url: ${OLLAMA_BASE_URL:http://localhost:11434}
        model: ${OLLAMA_CHAT_MODEL:llama3}
```

### 第2步：理解配置是怎么被读取的

**大白话**：你写 yml 配置 → 框架读出来 → 自动填进一个 Python 对象（dataclass）→ 类型自动转换（字符串 `"15"` 变 `int` 15，`"true"` 变 `bool` True）。

优先级：**环境变量 > application.yml > dataclass 默认值**。

```python
from spring.langchain.autoconfig import LangChainProperties, bind_langchain_config

props: LangChainProperties = bind_langchain_config({
    "default-llm": "openai",
    "agents": {"max-iterations": "15"},          # 字符串自动转 int
    "memory": {"type": "summary"},
})
assert props.agents.max_iterations == 15
assert isinstance(props.agents.max_iterations, int)
assert props.memory.type == "summary"
```

### 第3步：环境变量速查

| 配置键 | 环境变量 | 默认值 | 改它能做什么 |
|--------|---------|--------|-------------|
| enabled | LC_ENABLED | true | 开关 LangChain 模块 |
| default-llm | LC_DEFAULT_LLM | auto | 选默认大模型 |
| chains.default-verbose | LC_CHAIN_VERBOSE | false | 要不要打印链的详细日志 |
| agents.default-type | LC_AGENT_TYPE | react | Agent 类型 |
| agents.max-iterations | LC_AGENT_MAX_ITER | 10 | Agent 最多推理几轮 |
| vector-store.type | LC_VECTOR_STORE | faiss | 向量库类型 |
| retriever.type | LC_RETRIEVER | similarity | 检索器类型 |
| retriever.k | LC_RETRIEVER_K | 4 | 每次检索返回几条结果 |
| memory.type | LC_MEMORY | buffer | 记忆类型 |
| memory.max-messages | LC_MEMORY_MAX | 20 | 最多记几轮对话 |

`partners` 是动态字典，没有固定字段名——它的 key 就是 partner 名（如 `openai` / `anthropic`），value 是该 partner 的配置（`api_key` / `model` / `base_url` / `temperature` 等）。

---

## 第3章：双向适配器 —— 转接头

> **Adapter 就像 USB-C 转 HDMI 的转接头**。springbootAI 的插头（`ChatModel` 接口）和 LangChain 的插座（`BaseChatModel` 接口）形状不一样，需要转接头才能连上。

springbootAI 自己有一套模型抽象（`ChatModel` / `EmbeddingModel`），langchain 也有一套（`BaseChatModel` / `Embeddings`）。两套接口不能直接互调，所以提供四个适配器：

| 适配器 | 方向 | 用途 | 比喻 |
|--------|------|------|------|
| `SpringChatModelToLangChain` | spring → langchain | 把 `aiChatModel` 包成 langchain `BaseChatModel`，喂给 Chain / Agent | USB-C 转 HDMI |
| `SpringEmbeddingToLangChain` | spring → langchain | 把 `aiEmbeddingModel` 包成 langchain `Embeddings`，喂给 VectorStore | USB-C 转 DP |
| `LangChainModelToSpring` | langchain → spring | 把 partner 的 `ChatOpenAI` 等包成 springbootAI `ChatModel` | HDMI 转 USB-C |
| `LangChainEmbeddingToSpring` | langchain → spring | 把 partner 的 `OpenAIEmbeddings` 等包成 springbootAI `EmbeddingModel` | DP 转 USB-C |

### 完整示例：双向桥接一条龙

```python
from spring.ai import FakeChatModel, FakeEmbeddingModel
from spring.langchain.adapters import (
    to_langchain_model, to_langchain_embeddings,
    to_spring_model, to_spring_embeddings,
)

# 假设你有一个 springbootAI 的模型
spring_chat = FakeChatModel(prefix="AI:")
spring_emb = FakeEmbeddingModel(dim=16)

# === 方向1：springbootAI → langchain ===
lc_model = to_langchain_model(spring_chat)
# lc_model 现在是 langchain BaseChatModel，可以直接放进 Chain/Agent 里
lc_emb = to_langchain_embeddings(spring_emb)
# lc_emb 现在是 langchain Embeddings，可以直接放进 VectorStore 里

# === 方向2：langchain → springbootAI ===
spring_chat2 = to_spring_model(lc_model)
# spring_chat2 又变回了 springbootAI ChatModel
spring_emb2 = to_spring_embeddings(lc_emb)
# spring_emb2 又变回了 springbootAI EmbeddingModel

# 验证：消息不丢失
from spring.ai import Message
result = lc_model.invoke([Message.user("你好").to_langchain()])
print(result.content)
# 输出: AI: 你好
```

### 为什么需要双向？

默认场景下你的模型来自 `spring.ai`（springbootAI 原生），LangChain 组件需要 langchain 接口，所以走 spring → langchain。但当你直接用某个 partner（比如 Anthropic）时，`PartnerProviderFactory` 创建的是 langchain 模型，如果你想把它注入到 springbootAI 的 `ChatClient`，就要走 langchain → spring。两条路都通，按需取用。

---

## 第4章：Partner 提供商

### 注册表

`PARTNER_REGISTRY` 是一张 `name -> (langchain_module, chat_class_name, embedding_class_name_or_None)` 的元数据表，覆盖 30+ 主流厂商：

| 分类 | Partner 名 | langchain 包 |
|------|-----------|--------------|
| OpenAI 系 | `openai` / `azure-openai` | langchain_openai |
| Anthropic | `anthropic` | langchain_anthropic |
| 本地/开源 | `ollama` / `huggingface` / `llamacpp` | langchain_ollama / langchain_huggingface / langchain_community |
| Google | `google-vertexai` / `google-genai` | langchain_google_vertexai / langchain_google_genai |
| 国际厂商 | `mistralai` / `cohere` / `xai` | langchain_mistralai / langchain_cohere / langchain_xai |
| 云厂商聚合 | `bedrock` / `together` / `fireworks` / `nvidia` / `ai21` / `databricks` / `perplexity` / `groq` / `sambanova` / `premai` / `edenai` / `friendli` | 各自专属包 |
| 国内厂商 | `deepseek` / `zhipu` / `moonshot` / `tongyi` / `baichuan` / `hunyuan` / `minimax` / `volcengine` / `ernie` / `spark` | langchain_deepseek / langchain_zhipuai / langchain_community |

完整列表见 `spring/langchain/partners.py` 的 `PARTNER_REGISTRY`。

### 探测与实例化

```python
from spring.langchain.partners import (
    list_partners, list_available_partners, is_partner_available,
    PartnerProviderFactory,
)

# 全部支持的 partner（30+）
print(list_partners())
# 输出: ['ai21', 'anthropic', 'azure-openai', 'baichuan', 'bedrock', ...]

# 当前环境已安装依赖、可用的 partner
print(list_available_partners())
# 输出: ['ollama', 'openai']（取决于你装了什么包）

# 探测单个
print(is_partner_available("anthropic"))  # False（未装 langchain-anthropic）

# 实例化（返回已包装为 springbootAI ChatModel 的元组）
chat, emb = PartnerProviderFactory.create("openai", {
    "api_key": "sk-xxx", "model": "gpt-4o-mini", "temperature": 0.7
})
# chat 是 springbootAI ChatModel；emb 是 springbootAI EmbeddingModel 或 None
```

### 懒加载机制

`PartnerProviderFactory.create` 用 `importlib.import_module` 按需导入对应包。缺失依赖时抛带安装提示的 `ImportError`：

```
ImportError: 无法导入 langchain_anthropic（No module named 'langchain_anthropic'）。
请安装对应 partner 包：pip install langchain-anthropic
```

### 在 application.yml 中启用 Partner

```yaml
spring:
  langchain:
    partners:
      openai:
        api-key: ${OPENAI_API_KEY:}
        model: gpt-4o-mini
      anthropic:                    # 启用 Anthropic
        api-key: ${ANTHROPIC_API_KEY:}
        model: claude-3-5-sonnet-20241022
      deepseek:                     # 启用 DeepSeek
        api-key: ${DEEPSEEK_API_KEY:}
        model: deepseek-chat
```

`configure_langchain()` 会遍历 `partners` 子树，为每个 partner 调用 `PartnerProviderFactory.create`，注册两个 Bean：

- `lcPartnerChatModel_<name>`：springbootAI ChatModel
- `lcPartnerEmbeddingModel_<name>`：springbootAI EmbeddingModel（无嵌入的 partner 不注册）

依赖未安装的 partner 会自动跳过并告警，不阻塞启动。

### 让某个 Partner 作为默认 LLM

```yaml
spring:
  langchain:
    default-llm: anthropic   # 不再复用 aiChatModel，改用 Anthropic
    partners:
      anthropic:
        api-key: ${ANTHROPIC_API_KEY:}
        model: claude-3-5-sonnet-20241022
```

此时 `lcLangChainModel` 会从 `PartnerProviderFactory.create("anthropic", ...)` 创建，再桥接为 langchain `BaseChatModel`。

---

## 第5章：各能力 Bean 详解

### 5.1 PromptTemplateFactory（填空题模板）

**大白话**：把"把'{text}'翻译成{lang}"这种带空格的句子，填上变量变成完整句子。

```python
from spring.langchain.prompts.templates import PromptTemplateFactory

factory = PromptTemplateFactory()

# 1. 普通 PromptTemplate（单变量）
pt = factory.create_prompt_template("请把以下文本翻译成{lang}：{text}")
print(pt.format(lang="英文", text="你好"))
# 输出: 请把以下文本翻译成英文：你好

# 2. ChatPromptTemplate（多角色）
ct = factory.create_chat_prompt_template([
    {"role": "system", "content": "你是翻译助手"},
    {"role": "user", "content": "把'{text}'翻译成{lang}"},
])
msgs = ct.format_messages(text="你好", lang="英文")
print(msgs)
# 输出: [SystemMessage(content="你是翻译助手"), HumanMessage(content="把'你好'翻译成英文")]

# 3. FewShotPromptTemplate（带示例）
fs = factory.create_few_shot_prompt_template(
    examples=[{"input": "高兴", "output": "sad"}],   # 反义词示例
    example_prompt=factory.create_prompt_template("输入：{input}\n输出：{output}"),
    suffix="输入：{input}\n输出：",
    input_variables=["input"],
)
print(fs.format(input="大"))
# 输出:
# 输入：高兴
# 输出：sad
# 输入：大
# 输出：
```

### 5.2 ChainService（流水线）

**大白话**：把多个步骤串起来执行——"先把英文翻译成中文 → 再把中文总结成一句话"。

封装 langchain classic 的各类 Chain：

| 方法 | 对应 langchain Chain | 用途 |
|------|---------------------|------|
| `run_llm_chain(template, **inputs)` | `LLMChain` | 单次问答（模板字符串 + 变量） |
| `run_conversation(input, memory)` | `ConversationChain` | 带记忆多轮对话 |
| `create_sequential_chain(chains, ...)` | `SequentialChain` | 串联多 Chain（先翻译再总结） |
| `run_summarize(texts)` | `load_summarize_chain` | 文档摘要 |
| `create_llm_math_chain()` | `LLMMathChain` | 数学计算 |
| `create_retrieval_qa(retriever)` | `RetrievalQA` | RAG 问答 |
| `create_conversational_retrieval_chain(retriever, memory)` | `ConversationalRetrievalChain` | 带记忆的多轮 RAG 问答 |
| `create_api_chain(api_docs)` | `APIChain` | 让 LLM 调用 REST API |
| `create_constitutional_chain(principles=...)` | `ConstitutionalChain` | AI 安全审查 |

```python
from spring.langchain.chains.services import ChainService

# 注入 lcLangChainModel（由 configure_langchain 自动创建）
service = ChainService(lcLangChainModel=lc_model)

# 1. 单次问答
print(service.run_llm_chain("回答问题：{q}", q="什么是 SpringBootAI？"))
# 输出: [AI] SpringBootAI是一个Python Web框架...

# 2. 带记忆多轮（memory 不传时自动创建 buffer）
print(service.run_conversation("我叫张三"))
# 输出: [AI] 你好张三，有什么可以帮助你的？
print(service.run_conversation("我叫什么？"))
# 输出: [AI] 你叫张三（因为记住了）

# 3. 串联：先翻译再总结
from langchain.chains import LLMChain
from langchain_core.prompts import PromptTemplate
t_chain = LLMChain(llm=lc_model, prompt=PromptTemplate.from_template("翻译成英文：{input}"))
s_chain = LLMChain(llm=lc_model, prompt=PromptTemplate.from_template("一句话总结：{input}"))
print(service.run_sequential("SpringBootAI 是一个 Python Web 框架",
                             chains=[t_chain, s_chain]))
# 输出: （先翻译成英文，再把英文总结成一句话）
```

### 5.3 AgentService（会用工具的助手）

**大白话**：Agent 不只是回答问题，它还会自己决定"我该不该用工具"——比如你问"今天北京天气怎么样"，它会自动调搜索工具去查。

封装 8 种 Agent 类型：

| agent_type | 对应 langchain | 适用场景 |
|-----------|----------------|----------|
| `react` | `ZERO_SHOT_REACT_DESCRIPTION` | 经典 ReAct，通用 |
| `chat-zero-shot-react` | `CHAT_ZERO_SHOT_REACT_DESCRIPTION` | 对话版 ReAct |
| `conversational` | `CHAT_CONVERSATIONAL_REACT_DESCRIPTION` | 带记忆的事务型 Agent |
| `openai-functions` | `OPENAI_FUNCTIONS` | OpenAI 原生函数调用 |
| `openai-tools` | `create_openai_tools_agent` | OpenAI tools API（推荐） |
| `structured-chat` | `create_structured_chat_agent` | 结构化工具调用 |
| `self-ask-with-search` | `SELF_ASK_WITH_SEARCH` | 自问自答搜索 |
| `xml` | `create_xml_agent` | XML 格式 Agent |

```python
from spring.langchain.agents.services import AgentService
from langchain_community.tools import DuckDuckGoSearchRun

agent_service = AgentService(lcLangChainModel=lc_model)

# 1. 旧版 initialize_agent 风格
executor = agent_service.create_agent(
    tools=[DuckDuckGoSearchRun()],
    agent_type="react",
    max_iterations=5,
)
print(agent_service.run_agent(executor, "今天北京天气怎么样？"))
# 输出: （Agent 自动搜索并返回结果）

# 2. 新版 create_react_agent（推荐）
executor = agent_service.create_react_agent(tools=[DuckDuckGoSearchRun()])
print(agent_service.run_agent(executor, "Python 3.12 发布日期？"))
# 输出: （Agent 搜索后回答）
```

### 5.4 MemoryFactory（记性）

**大白话**：对话记性——让你的程序记住"我叫张三"这件事，下轮问"我叫什么"时能答出来。

| type | 对应 langchain Memory | 特点 |
|------|----------------------|------|
| `buffer` | `ConversationBufferMemory` | 全量保留（记所有内容） |
| `summary` | `ConversationSummaryMemory` | LLM 摘要压缩（用一句话总结历史） |
| `buffer-window` | `ConversationBufferWindowMemory` | 只保留最近 N 轮 |
| `token-buffer` | `ConversationTokenBufferMemory` | 按 token 数截断 |
| `entity` | `ConversationEntityMemory` | 自动提取人名、地名等实体 |
| `combined` | `CombinedMemory` | 组合多种记忆类型 |
| `read-only-shared` | `ReadOnlySharedMemory` | 只读共享记忆（多 Agent 共享上下文） |

```python
from spring.langchain.memory.memory import MemoryFactory

# buffer-window：只记最近 5 轮
memory = MemoryFactory.create("buffer-window", max_messages=5)
chain_service.run_conversation("你好", memory=memory)
# 输出: [AI] 你好！
```

### 5.5 OutputParserFactory（文本→对象）

**大白话**：模型返回的是文本（字符串），Parser 把它变成 Python 对象——列表、日期、JSON、Pydantic 对象。

```python
from spring.langchain.parsers.parsers import OutputParserFactory

# 1. 列表解析（把 "a, b, c" 变成 ['a', 'b', 'c']）
parser = OutputParserFactory.create("comma-list")
print(parser.parse("a, b, c"))
# 输出: ['a', 'b', 'c']

# 2. 日期解析（把文本变 datetime 对象）
parser = OutputParserFactory.create("datetime")
print(parser.parse("2026-08-10T12:00:00.000Z"))
# 输出: datetime(2026, 8, 10, 12, 0)

# 3. JSON 解析（把 JSON 字符串变 dict）
parser = OutputParserFactory.create("json")
print(parser.parse('{"name": "张三", "age": 18}'))
# 输出: {'name': '张三', 'age': 18}

# 4. Pydantic 解析（把 JSON 字符串变 Pydantic 对象）
from pydantic import BaseModel
class Person(BaseModel):
    name: str
    age: int
parser = OutputParserFactory.create("pydantic", pydantic_model=Person)
print(parser.parse('{"name": "张三", "age": 18}'))
# 输出: Person(name='张三', age=18)
```

### 5.6 DocumentLoaderRegistry（资料搬运工）

**大白话**：从 txt / csv / pdf / 网页 / 目录读取文档，自动识别格式。

```python
from spring.langchain.loaders.loaders import DocumentLoaderRegistry

registry = DocumentLoaderRegistry()

# 1. 文本文件
docs = registry.load("text", "./hello.txt")
# 2. CSV
docs = registry.load("csv", "./data.csv")
# 3. PDF（需 pypdf）
docs = registry.load("pdf", "./report.pdf")
# 4. 网页（需 requests + beautifulsoup4）
docs = registry.load("web", "https://example.com")
# 5. 目录（递归读取所有支持的文件）
docs = registry.load("directory", "./docs")
# 6. JSON
docs = registry.load("json", "./data.json")
```

### 5.7 VectorStoreFactory（资料索引柜）

**大白话**：把文档变成向量存起来，以后可以按"相似度"快速查找。

| store_type | 对应 langchain | 依赖 | 适合场景 |
|-----------|----------------|------|---------|
| `inmemory` | springbootAI `SimpleInMemoryVectorStore` | 无（内置） | 学习/测试 |
| `faiss` | `FAISS` | faiss-cpu + langchain_community | 中小规模 |
| `chroma` | `Chroma` | langchain_chroma | 持久化 |
| `pinecone` | `Pinecone` | langchain_pinecone | 大规模生产 |
| `weaviate` | `Weaviate` | langchain_weaviate | 大规模生产 |
| `pgvector` | `PGVector` | langchain_postgres | PostgreSQL 用户 |
| `redis` | `Redis` | langchain_community + redis | 已有 Redis 的用户 |

```python
from spring.langchain.vectorstores.stores import VectorStoreFactory

# 1. 内存向量库（无需任何依赖）
store = VectorStoreFactory.from_texts(
    "inmemory",
    ["SpringBootAI 用 @Service", "LangChain 提供 Chain"],
    embeddings=lc_emb,
)
# 结果: 两段文本已被向量化存入内存

# 2. FAISS（需 pip install faiss-cpu langchain-community）
store = VectorStoreFactory.from_texts(
    "faiss",
    ["文档A", "文档B"],
    embeddings=lc_emb,
)
# 结果: 文本已存入本地 FAISS 索引
```

### 5.8 RetrieverFactory（查资料）

**大白话**：从向量库里捞出和问题最相关的几段文档。

| type | 对应 langchain Retriever | 特点 |
|------|-------------------------|------|
| `similarity` | 向量库原生 | 最简单的相似度检索 |
| `multi-query` | `MultiQueryRetriever` | LLM 生成多个变体问题再检索 |
| `contextual-compression` | `ContextualCompressionRetriever` | 检索后用 LLM 压缩无关片段 |
| `self-query` | `SelfQueryRetriever` | 用户元数据过滤 |
| `time-weighted` | `TimeWeightedVectorStoreRetriever` | 时间衰减 |
| `ensemble` | `EnsembleRetriever` | 混合检索（稀疏+密集） |

```python
from spring.langchain.retrievers.retrievers import RetrieverFactory

retriever = RetrieverFactory.create("similarity", vector_store=store, k=3)
docs = retriever.invoke("SpringBootAI 是什么？")
# 结果: docs = [最相关的3条文档]
```

### 5.9 IndexService（一键 RAG）

**大白话**："建立知识库 + 写入文档 + 检索"三步合成一步，一行代码搞定 RAG。

```python
from spring.langchain.indexes.index import IndexService

index_service = IndexService(lcEmbeddings=lc_emb, lcLangChainModel=lc_model)

# 1. 从文本列表建库
store = index_service.create_from_texts(
    ["SpringBootAI 使用 @Service 注解。", "LangChain 提供链和代理。"],
    vector_store_type="inmemory",
)

# 2. 检索
results = index_service.query(store, "注解", k=2)
for doc in results:
    print(doc.page_content if hasattr(doc, "page_content") else doc)
# 输出:
# SpringBootAI 使用 @Service 注解。
```

### 5.10 ToolFactory / ToolRegistry（工具工厂）

```python
from spring.langchain.tools.tools import ToolFactory, ToolRegistry

# 1. 把普通函数包成 langchain StructuredTool
def add(a: int, b: int) -> int:
    """加法"""
    return a + b
tool = ToolFactory.from_function(add, name="add", description="加法")
# 结果: tool 是一个 langchain BaseTool，可以喂给 Agent

# 2. ToolRegistry 收集多个工具
registry = ToolRegistry()
registry.add_function(add, name="add", description="加法")
tools = registry.all()
print(tools)
# 输出: [StructuredTool(name='add', ...)]
```

### 5.11 UtilityRegistry（现成工具包）

LangChain 内置的现成工具，按需懒加载：

```python
from spring.langchain.utilities.utils import UtilityRegistry

# 1. DuckDuckGo 搜索（无需 API Key）
search = UtilityRegistry.create("duckduckgo")
print(search.run("Python 3.12 发布日期"))
# 输出: （搜索结果）

# 2. Wikipedia
wiki = UtilityRegistry.create("wikipedia")
print(wiki.run("LangChain"))
# 输出: （Wikipedia 页面摘要）

# 3. Python REPL（执行代码）
repl = UtilityRegistry.create("python-repl")
# 4. Arxiv（论文搜索）
arxiv = UtilityRegistry.create("arxiv")
# 5. SQLDatabase（连数据库）
db = UtilityRegistry.create("sql-database", uri="sqlite:///test.db")
```

### 5.12 CallbackRegistry（监听器）

挂在模型调用流程上的监听器：

```python
from spring.langchain.callbacks.handlers import CallbackRegistry

# 1. 标准输出回调
cb = CallbackRegistry.create_stdout_handler()
# 2. 流式标准输出
cb = CallbackRegistry.create_streaming_stdout_handler()
# 3. 写文件
cb = CallbackRegistry.create_file_handler("./llm.log")

# 传给 Chain：通过 langchain 的 config={"callbacks": [...]} 参数
chain = chain_service.create_llm_chain(prompt=your_prompt)
result = chain.invoke({"q": "你好"}, config={"callbacks": [cb]})
```

---

## 第6章：自动装配（configure_langchain）

`configure_langchain()` 是模块入口，读取 `spring.langchain.*` 配置，构建并注册全部 `lc*` Bean：

```python
from spring.context.registry import BeanRegistry
from spring.config.config_loader import config_loader
from spring.ai.autoconfig import configure_ai
from spring.langchain.autoconfig import configure_langchain

registry = BeanRegistry()

# 1. 先装配 spring.ai（提供 aiChatModel / aiEmbeddingModel）
configure_ai(registry=registry, config=config_loader)

# 2. 再装配 spring.langchain（default-llm=auto 复用 aiChatModel）
beans = configure_langchain(registry=registry, config=config_loader)

# 3. 直接从返回值取 Bean
chain_service = beans["lcChainService"]
agent_service = beans["lcAgentService"]
index_service = beans["lcIndexService"]
# 结果: 三个服务 Bean 都可以直接用了
```

自动装配产出的 Bean：

| Bean 名 | 类型 | 说明 |
|---------|------|------|
| `lcLangChainModel` | langchain `BaseChatModel` | 由 `aiChatModel` 桥接，或 partner 创建 |
| `lcEmbeddings` | langchain `Embeddings` | 由 `aiEmbeddingModel` 桥接 |
| `lcPromptRegistry` | `PromptTemplateFactory` | Prompt 模板工厂 |
| `lcChainService` | `ChainService` | Chain 服务 |
| `lcAgentService` | `AgentService` | Agent 服务 |
| `lcMemoryFactory` | `MemoryFactory` | Memory 工厂 |
| `lcParserRegistry` | `OutputParserFactory` | 输出解析工厂 |
| `lcLoaderRegistry` | `DocumentLoaderRegistry` | 文档加载注册表 |
| `lcRetrieverFactory` | `RetrieverFactory` | 检索器工厂 |
| `lcVectorStoreFactory` | `VectorStoreFactory` | 向量库工厂 |
| `lcIndexService` | `IndexService` | 一键 RAG |
| `lcToolFactory` | `ToolFactory` | Tool 工厂 |
| `lcToolRegistry` | `ToolRegistry` | Tool 注册表 |
| `lcUtilityRegistry` | `UtilityRegistry` | 工具集注册表 |
| `lcCallbackRegistry` | `CallbackRegistry` | 回调注册表 |
| `lcPartnerChatModel_<name>` | springbootAI `ChatModel` | 各启用 partner 的聊天模型 |
| `lcPartnerEmbeddingModel_<name>` | springbootAI `EmbeddingModel` | 各启用 partner 的嵌入模型（可选） |

### 双重注册机制

`_register_bean` 同时把 Bean 注册到两套存储：

1. **BeanRegistry**：`registry.get("lcChainService")` 直取，用于脚本式调用。
2. **ApplicationContext.bean_factory**：`@Autowired` 按名称或类型注入，用于 `@Service` 类构造器。

```python
@Service
class MyService:
    @Autowired
    def __init__(self, lcChainService: ChainService):
        self.chain = lcChainService   # ✅ 自动注入
```

### 装配时机

`configure_langchain` 必须在 `@Service` 实例化**之前**完成，否则 `@Autowired` 找不到 `lc*` Bean。推荐用 `@Configuration` 类在 `__init__` 中触发：

```python
@Configuration
class LangChainAppConfig:
    def __init__(self):
        registry = BeanRegistry()
        configure_ai(registry=registry, config=config_loader)
        configure_langchain(registry=registry, config=config_loader)
```

---

## 第7章：示例应用（example_langchain）

项目自带一个完整的演示应用 `examples/example_langchain/`：

```
examples/example_langchain/
├── Application.py                              # @SpringBootApplication 启动类
├── config/LangChainAppConfig.py                # @Configuration 装配 AI + LangChain
├── controller/LangChainController.py           # @RestController REST 接口
└── service/
    ├── LangChainChatService.py                 # 问答/翻译/摘要
    ├── LangChainAgentService.py                # Agent 执行
    ├── LangChainRagService.py                  # RAG 入库/检索
    └── LangChainChainService.py                # Chain/Memory/Math/Parser
```

### 启动

```bash
# 无 API Key 也能跑（降级 FakeChatModel）
$env:AI_ALLOW_FAKE = "true"
python examples/example_langchain/Application.py
# 服务监听 8081 端口
```

### HTTP 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/lc/chat` | 基础问答 |
| POST | `/api/lc/translate` | 翻译 |
| POST | `/api/lc/summarize` | 总结 |
| POST | `/api/lc/agent` | Agent 执行 |
| POST | `/api/lc/rag/add` | RAG 文档入库 |
| POST | `/api/lc/rag/query` | RAG 检索问答 |
| POST | `/api/lc/memory` | 带记忆对话 |
| POST | `/api/lc/math` | 数学计算 |
| GET | `/api/lc/providers` | 列出已启用 partner |

调用示例：

```bash
curl -X POST http://localhost:8081/api/lc/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "什么是 SpringBootAI？"}'

curl -X POST http://localhost:8081/api/lc/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question": "SpringBootAI 是什么？", "k": 2}'
```

---

## 第8章：与 spring.ai 模块的关系

`spring.ai` 和 `spring.langchain` 是两个**互补**的模块：

| 维度 | spring.ai | spring.langchain |
|------|-----------|------------------|
| 定位 | Spring AI 2.0 对齐的统一抽象 | LangChain 生态的 Spring 封装 |
| 模型来源 | 自己实现 Provider（OpenAI/Ollama/DeepSeek/Moonshot/Zhipu） | 复用 spring.ai 的 `aiChatModel`，桥接为 langchain `BaseChatModel` |
| 核心抽象 | `ChatClient` / `Advisor` / `Tools` / RAG | `Chain` / `Agent` / `Memory` / `Retriever` |
| 配置前缀 | `spring.ai.*` | `spring.langchain.*` |
| 入口 | `configure_ai()` | `configure_langchain()` |
| 装配顺序 | 先 | 后（依赖 `aiChatModel`） |

**典型用法**：两个模块一起装。`configure_ai` 提供 `aiChatModel` / `aiEmbeddingModel`，`configure_langchain` 复用它们并封装出 Chain / Agent / Memory 等 LangChain 能力。

```python
configure_ai(registry=registry)              # 1. 先装 spring.ai
configure_langchain(registry=registry)        # 2. 再装 spring.langchain（复用 aiChatModel）
```

想用 Spring AI 风格的 `ChatClient` 链式 API + Advisor？用 `spring.ai`。想用 LangChain 的 `Chain` / `Agent` / `Memory` 抽象？用 `spring.langchain`。两者底层是同一个模型 Bean，不会重复计费。

---

## 第9章：边界与限制（必读）

### 依赖边界

| 安装方式 | 覆盖 | 包含内容 |
|----------|------|----------|
| `pip install springbootAI` | 核心框架 | FastAPI / ORM / AOP / JWT / 配置管理 |
| `pip install springbootAI[ai]` | AI 基础 | langchain-core、langchain-classic、langchain-openai、langchain-community、langchain-text-splitters、numpy、pydantic |
| `pip install springbootAI[langchain]` | LangChain 全套 | [ai] 全部 + faiss-cpu、pypdf、beautifulsoup4、sqlalchemy、langchain-experimental + 9 个 partner 包 |
| `pip install springbootAI[full]` | 所有模块 | [langchain] + MySQL/PostgreSQL/Redis/RabbitMQ/Nacos/Prometheus/Excel + 全部 partner 包 |

**边界说明**：

- **partner 懒加载**：36 个 partner 中 9 个列入 `[langchain]` extra，其余 15+ 个按需 `pip install`。
- **apt 内核**：`langchain-classic==1.0.8`、`langchain-core==1.5.1`、`langchain-openai==1.4.1` 三个核心包精确锁定版本。
- **不依赖 langgraph**：本模块不下发也不依赖 `langgraph`（>100MB），避免安装膨胀。
- **numpy 版本约束**：`numpy==1.26.4`（兼容 langchain 全部功能；2.x 会导致 FAISS 崩溃）。

### 架构边界

本模块**锁定 langchain classic (1.x) API**，不从 langchain v1 体系继承：

| 边界 | 说明 |
|------|------|
| **Classic API** | `LLMChain`、`ConversationChain`、`RetrievalQA`、`AgentExecutor`、`ConversationBufferMemory` 等使用 langchain_classic 1.0.8 |
| **不包含 langgraph** | `langgraph`（>100MB）不在依赖内。Agent 不持久化 checkpoint、不流式、不做 human-in-the-loop |
| **不包含 create_agent** | langchain v1 的 `create_agent()` 不在本模块 |
| **同步 API** | `ChatModel.call()` 返回 `ChatResponse`（同步） |
| **预期警告** | 导入本模块时 `langchain_classic` 的弃用警告会被静默。这些是框架级告警，非 bug |

### 安全边界

| 层次 | 控制措施 |
|------|----------|
| **危险工具** | `python-repl`、`sql-database` 默认禁用，需显式 `AI_ALLOW_DANGEROUS_TOOLS=true` 才可用 |
| **工具异常脱敏** | 异常仅暴露类型名（如 `[工具执行错误] KeyError`），完整 traceback 记录在服务端日志 |
| **会话隔离** | `conversation_id` 缺失时不降级为 `"default"`，直接跳过记忆注入（不串读历史） |
| **RAG 租户 ACL** | `similarity_search()` 强制执行 `filter_expression`，支持 `"tenant:A"` 或 `"user_id:42"` |
| **SSRF 防护** | URL 检查协议（仅 http/https）、拒绝私网/回环/元数据 IP |
| **eval 安全** | `safe_eval_arithmetic()` 用 AST 白名单（仅 +-*/** 等），拒绝函数调用/属性访问 |
| **pickle 禁用** | Redis 缓存 JSON 解码失败时不再调用 `pickle.loads()`，消除 RCE 面 |

### 兼容性边界

| 场景 | 兼容性 | 说明 |
|------|--------|------|
| **springbootAI FakeChatModel** | ✅ 完全支持 | Chain/Agent/RAG 均可演示 |
| **真实 OpenAI/Ollama/DeepSeek/Zhipu** | ✅ 完全支持 | Function Calling 可用 |
| **LangChain 原生 BaseChatModel** | ✅ 支持 | 通过 `to_spring_model()` 桥接 |
| **LCEL 管道 `prompt \| llm`** | ✅ 支持 | 可直接接入 LCEL |
| **langgraph StateGraph** | ❌ 不支持 | 本模块锁定 classic API |
| **Async 流式** | ⚠️ 部分支持 | `astream()` 通过线程池同步包装 |
| **Multimodal** | ⚠️ 部分支持 | 取决于底层 Provider |

---

## 新手常见问题 FAQ

**Q1：没有 API Key 能跑吗？**

A：能。设置 `AI_ALLOW_FAKE=true`，`configure_ai` 会降级 `FakeChatModel` / `FakeEmbeddingModel`，整个 LangChain 流程（Chain / Agent / RAG / Memory）都能演示，只是模型回复是假数据。

**Q2：怎么换 partner？**

A：两种方式：① 改 `application.yml` 的 `spring.langchain.default-llm` 为 partner 名（如 `anthropic`），并在 `partners.anthropic` 下配 key/model；② 直接 `PartnerProviderFactory.create("anthropic", cfg)` 手动创建。

**Q3：某个 partner 的包没装会怎样？**

A：`configure_langchain` 会捕获 `ImportError`，告警 `"Partner 'xxx' 注册失败（跳过）"`，不阻塞启动。其他 partner 和模块功能不受影响。

**Q4：FAISS / Chroma 等向量库怎么选？**

A：学习/测试用 `inmemory`（无依赖）；中小规模用 `faiss`（`pip install faiss-cpu`）；持久化用 `chroma` 或 `redis`；大规模用 `pinecone` / `weaviate` / `pgvector`。

**Q5：RAG 报 `嵌入模型未装配`？**

A：`configure_ai` 默认会装 `aiEmbeddingModel`，但需要 `OPENAI_API_KEY`（或 `OLLAMA_BASE_URL`）。无 Key 时设 `AI_ALLOW_FAKE=true` 会降级 `FakeEmbeddingModel(dim=16)`，RAG 可演示但不真实。

**Q6：`@Autowired` 注入 `lcChainService` 报 `Cannot resolve parameter`？**

A：确认 `@Configuration` 类的 `__init__` 中调用了 `configure_langchain`，且该 `@Configuration` 类在 `@Service` 之前被实例化（SpringBootAI 默认保证这个顺序）。

**Q7：怎么自定义一个 partner？**

A：在 `PARTNER_REGISTRY` 中加一项 `name -> (module, chat_cls, emb_cls)`，然后在 `application.yml` 的 `partners.<name>` 下配置即可。无需改任何 `@Service` 代码。

**Q8：如果 spring.ai 模块没装配，LangChain 模块还能用吗？**

A：`configure_langchain` 依赖 `aiChatModel`（通过 `default-llm=auto`），如果 `configure_ai` 没调过，会尝试自动降级。但推荐先调 `configure_ai`。

**Q9：Chain 和 Agent 有什么区别？什么时候用哪个？**

A：Chain 是固定的"流水线"——你定义好步骤，每次按顺序执行。Agent 是"自主决策"——你给它工具，它自己决定什么时候用哪个。简单任务用 Chain，复杂/不确定的任务用 Agent。

**Q10：一次对话能用多个 Chain 吗？**

A：可以，用 `SequentialChain` 把多个 Chain 串起来，前一个的输出是后一个的输入。

---

> **相关文档**：[AI 模块使用指南](AI_MODULE.md) | [AI & LangChain 测试指南](AI_LANGCHAIN_TEST_GUIDE.md) | [新手入门指南](BEGINNER_GUIDE.md)

## 注解式调用：把 Chain 和 Agent 写成普通方法

当一个 Service 只有“接收参数，然后调用固定 Chain”的样板代码时，可以用注解缩短它。注解不是新的 AI 引擎，底层仍调用本文前面介绍的 `ChainService` 和 `AgentService`。

### 最小 Chain 示例

先完成 `configure_ai()` 和 `configure_langchain()`，让容器中存在 `lcChainService`。然后声明服务：

```python
from spring.langchain import LangChainCall, LangChainClient


@LangChainClient
class WritingAssistant:
    @LangChainCall("Translate {text} to {language}. Return only the translation.")
    def translate(self, text: str, language: str = "Chinese") -> str:
        raise NotImplementedError


assistant = WritingAssistant()
print(assistant.translate("Hello"))
```

方法体是声明占位，调用时不会执行。框架会读取 `text`、`language`，再执行：

```python
lcChainService.run_llm_chain(prompt, text="Hello", language="Chinese")
```

不要在占位方法体中写业务副作用，因为它不会运行。真实业务预处理应放在调用注解方法之前，或写成图节点。

### 对话、总结和 Agent

```python
@LangChainClient
class Assistant:
    @LangChainCall(mode="conversation", input_name="question")
    def chat(self, question: str) -> str:
        raise NotImplementedError

    @LangChainCall(mode="summarize", input_name="paragraphs")
    def summarize(self, paragraphs: list[str]) -> str:
        raise NotImplementedError

    @LangChainCall(
        mode="agent",
        input_name="task",
        tools_bean="safeAgentTools",
        agent_type="react",
    )
    def execute(self, task: str) -> str:
        raise NotImplementedError
```

| mode | 底层调用 | 输入要求 |
|---|---|---|
| `chain` | `run_llm_chain` | 方法参数与提示词变量对应 |
| `conversation` | `run_conversation` | `input_name` 指向一个字符串 |
| `summarize` | `run_summarize` | `input_name` 指向字符串列表 |
| `agent` | `run_agent` | 字符串任务，并显式指定 `tools_bean` |

Agent 不接受调用者临时传工具。工具必须由容器预先注册，这能避免外部请求绕过工具白名单。危险工具仍要遵守 LangChain 模块原有的允许策略。

### 异步 Web 路由

```python
@LangChainClient
class Assistant:
    @LangChainCall("Summarize this text: {text}")
    async def summarize_one(self, text: str) -> str:
        raise NotImplementedError


@PostMapping("/summary")
async def summary(body):
    return await assistant.summarize_one(body["text"])
```

现有 LangChain classic 服务是同步的。异步注解会用工作线程执行同步 Chain，因此不会直接阻塞 Uvicorn 事件循环。线程不能中止已经发出的模型 HTTP 请求，所以仍必须配置 provider 连接超时、读取超时和有限重试。

注解默认拒绝超过 65536 字节的输入，可用 `max_input_bytes` 调小。这个限制按序列化后的 UTF-8 字节计算，不能替代模型 token 限制。

### 不使用全局 BeanRegistry

单元测试或手动装配时可以显式注入：

```python
from spring.langchain import bind_langchain_client

assistant = bind_langchain_client(
    Assistant(),
    chain_service=my_chain_service,
    agent_service=my_agent_service,
    tools=safe_tools,
    memory=my_memory,
)
```

完整示例见 [annotation_demo.py](../examples/example_langchain/demo/annotation_demo.py)，行为测试见 [test_ai_declarative_annotations.py](../tests/test_ai_declarative_annotations.py)。
