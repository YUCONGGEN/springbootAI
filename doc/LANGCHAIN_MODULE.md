# SpringBootAI LangChain 模块使用指南

> 把 [LangChain](https://github.com/langchain-ai/langchain) classic 全套能力（Chains / Agents / Memory / Retrievers / VectorStores / Parsers / Loaders）封装为 Spring 风格 Bean，配合 30+ 第三方模型提供商（OpenAI / Anthropic / Ollama / DeepSeek / ZhipuAI / Tongyi …）开箱即用。
> 安装：`pip install springbootAI[ai]` ｜ 框架版本：SpringBootAI 1.8.8 / LangChain 模块 1.0.0

---

## 阅读前准备

第一次使用请先读完 [新手入门指南](BEGINNER_GUIDE.md) 的普通 HTTP 接口，再学习 [AI 模块使用指南](AI_MODULE.md) 的基础聊天，最后读本文件。

本模块**复用** `spring.ai` 装配出的 `aiChatModel` / `aiEmbeddingModel` Bean 作为底层模型，再做一层 LangChain 适配。因此**没有真实 API Key 也能跑通**——设置 `AI_ALLOW_FAKE=true` 后会降级 `FakeChatModel`，整个 LangChain 流程依然可演示。

学习顺序建议：基础问答 → Prompt 模板 → Memory 多轮 → Chain → Agent → RAG → 输出解析 → 自定义 Partner。每一步先验证错误处理、超时和费用，再进入下一步。

### 0.1 这个模块是干什么的？（大白话版）

简单说：**让你的 SpringBootAI 应用直接使用 LangChain 生态的全部能力**，而不用自己手动 `from langchain.xxx import ...` 再去管实例化和依赖注入。

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

### 0.2 里面的概念（新手比喻）

| 术语 | 大白话 | 比喻 |
|------|--------|------|
| **LangChain** | 一个流行的 Python AI 框架，提供 Chain / Agent / Memory 等抽象 | 一整套现成工具箱 |
| **Partner（提供商）** | 提供大模型 API 的厂商（OpenAI、Anthropic、Ollama、智谱、通义…） | 模型供货商 |
| **Chain（链）** | 把多个步骤串起来执行的任务流（先翻译再总结） | 流水线 |
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
| **Adapter（适配器）** | springbootAI 模型 ↔ langchain 模型的双向桥接 | 转接头 |

### 0.3 新手三步走：从零跑通第一个 LangChain 程序

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

### 0.4 新手常见误区

- ❌ 以为要自己 `import langchain.xxx` 再 `new` → ✅ 全部走 `@Autowired` 注入 `lc*Service` Bean
- ❌ 直接在 Controller 里写 LangChain 代码 → ✅ Controller 只调 Service，Service 通过 `@Autowired` 拿 `lcChainService`
- ❌ 30 个 partner 全装上拖慢启动 → ✅ 按需在 `application.yml` 的 `spring.langchain.partners` 下配置，未配置的不加载
- ❌ 以为 `lcLangChainModel` 是 springbootAI 模型 → ✅ 它是**langchain `BaseChatModel`**（由 `aiChatModel` 桥接而来）；要 springbootAI 模型请用 `aiChatModel`
- ❌ RAG 流程忘记配嵌入模型 → ✅ `configure_ai` 默认会装 `aiEmbeddingModel`，缺失时 RAG 会告警但不崩溃

---

## 1. 模块全景

```
spring.langchain/
├── adapters.py          # 双向桥接：springbootAI ↔ langchain 模型/嵌入/向量库
├── partners.py          # 30+ Partner 提供商工厂注册表（懒加载）
├── autoconfig.py        # 从 application.yml 装配全部 lc* Bean
├── prompts/templates.py # PromptTemplate / ChatPromptTemplate / FewShot 工厂
├── chains/services.py   # LLMChain / ConversationChain / SequentialChain / RetrievalQA / 摘要 / LLMMath
├── agents/services.py   # ReAct / OpenAI-tools / structured-chat Agent
├── memory/memory.py     # buffer / summary / buffer-window / token-buffer
├── parsers/parsers.py   # comma-list / datetime / json / pydantic / enum
├── loaders/loaders.py   # text / csv / pdf / web / directory / json
├── retrievers/retrievers.py  # similarity / multi-query / contextual-compression / self-query / time-weighted / ensemble
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

---

## 2. 配置（application.yml）

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
    # 未列出的 partner 缺省不启用；列出但依赖未安装的会自动跳过并告警
    partners:
      openai:
        api-key: ${OPENAI_API_KEY:}
        model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
        temperature: ${OPENAI_TEMPERATURE:0.7}
      ollama:
        base-url: ${OLLAMA_BASE_URL:http://localhost:11434}
        model: ${OLLAMA_CHAT_MODEL:llama3}
      # 示例：启用 Anthropic（需 pip install langchain-anthropic）
      # anthropic:
      #   api-key: ${ANTHROPIC_API_KEY:}
      #   model: claude-3-5-sonnet-20241022
```

**配置读取（混合方式）**：`configure_langchain()` 读取 `spring.langchain.*` 子树后，用类型化 `LangChainProperties` dataclass 绑定。优先级：**环境变量 > application.yml > dataclass 默认值**。环境变量通过两条路径生效：① `config_loader` 解析 yml 的 `${ENV:default}` 占位符；② dataclass 字段 `metadata["env"]` 声明的 env 名作为覆盖安全网（即使 yml 写死字面值也能被同名 env 覆盖）。

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

**环境变量速查**：

| 配置键 | 环境变量 | 默认值 |
|--------|---------|--------|
| enabled | LC_ENABLED | true |
| default-llm | LC_DEFAULT_LLM | auto |
| chains.default-verbose | LC_CHAIN_VERBOSE | false |
| agents.default-type | LC_AGENT_TYPE | react |
| agents.max-iterations | LC_AGENT_MAX_ITER | 10 |
| vector-store.type | LC_VECTOR_STORE | faiss |
| vector-store.persist-dir | LC_PERSIST_DIR | ./data/vectors |
| vector-store.collection | LC_COLLECTION | default |
| retriever.type | LC_RETRIEVER | similarity |
| retriever.k | LC_RETRIEVER_K | 4 |
| memory.type | LC_MEMORY | buffer |
| memory.max-messages | LC_MEMORY_MAX | 20 |

`partners` 是动态字典，没有固定字段名——它的 key 就是 partner 名（如 `openai` / `anthropic`），value 是该 partner 的配置（`api_key` / `model` / `base_url` / `temperature` 等），由 `PartnerProviderFactory._filter_kwargs` 自动过滤出该 partner 类构造器接受的参数。

---

## 3. 双向适配器（adapters.py）

springbootAI 自己有一套模型抽象（`ChatModel` / `EmbeddingModel`），langchain 也有一套（`BaseChatModel` / `Embeddings`）。两套接口不能直接互调，所以提供四个适配器：

| 适配器 | 方向 | 用途 |
|--------|------|------|
| `SpringChatModelToLangChain` | spring → langchain | 把 `aiChatModel` 包成 langchain `BaseChatModel`，喂给 Chain / Agent |
| `SpringEmbeddingToLangChain` | spring → langchain | 把 `aiEmbeddingModel` 包成 langchain `Embeddings`，喂给 VectorStore |
| `LangChainModelToSpring` | langchain → spring | 把 partner 的 `ChatOpenAI` 等包成 springbootAI `ChatModel` |
| `LangChainEmbeddingToSpring` | langchain → spring | 把 partner 的 `OpenAIEmbeddings` 等包成 springbootAI `EmbeddingModel` |

便捷函数：

```python
from spring.langchain.adapters import (
    to_langchain_model, to_langchain_embeddings,
    to_spring_model, to_spring_embeddings,
)

# springbootAI ChatModel -> langchain BaseChatModel
lc_model = to_langchain_model(spring_chat_model)
# springbootAI EmbeddingModel -> langchain Embeddings
lc_emb = to_langchain_embeddings(spring_embedding_model)
# langchain 模型 -> springbootAI ChatModel（partner 用）
spring_chat = to_spring_model(lc_chat_model)
# langchain Embeddings -> springbootAI EmbeddingModel
spring_emb = to_spring_embeddings(lc_embeddings)
```

**为什么需要双向？** 默认场景下你的模型来自 `spring.ai`（springbootAI 原生），LangChain 组件需要 langchain 接口，所以走 spring → langchain。但当你直接用某个 partner（比如 Anthropic）时，`PartnerProviderFactory` 创建的是 langchain 模型，如果你想把它注入到 springbootAI 的 `ChatClient`，就要走 langchain → spring。两条路都通，按需取用。

---

## 4. Partner 提供商（partners.py）

### 4.1 注册表

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

完整列表见 [partners.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/partners.py) 的 `PARTNER_REGISTRY`。

### 4.2 探测与实例化

```python
from spring.langchain.partners import (
    list_partners, list_available_partners, is_partner_available,
    PartnerProviderFactory,
)

# 全部支持的 partner（30+）
print(list_partners())
# 当前环境已安装依赖、可用的 partner
print(list_available_partners())
# 探测单个
print(is_partner_available("anthropic"))  # False（未装 langchain-anthropic）

# 实例化（返回已包装为 springbootAI ChatModel 的元组）
chat, emb = PartnerProviderFactory.create("openai", {
    "api_key": "sk-xxx", "model": "gpt-4o-mini", "temperature": 0.7
})
# chat 是 springbootAI ChatModel；emb 是 springbootAI EmbeddingModel 或 None
```

**懒加载机制**：`PartnerProviderFactory.create` 用 `importlib.import_module` 按需导入对应包。缺失依赖时抛带安装提示的 `ImportError`：

```
ImportError: 无法导入 langchain_anthropic（No module named 'langchain_anthropic'）。
请安装对应 partner 包：pip install langchain-anthropic
```

**参数过滤**：`_filter_kwargs` 会读取 partner 类的 `model_fields`（pydantic v2）或 `__fields__`（v1）或 `__init__` 签名，只保留构造器接受的参数，避免 pydantic 报未知字段。同时自动把 `kebab-case`（yml 风格）转成 `snake_case`（Python 风格）。

### 4.3 在 application.yml 中启用 Partner

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

### 4.4 让某个 Partner 作为默认 LLM

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

## 5. 各能力 Bean 详解

### 5.1 PromptTemplateFactory（prompts）

```python
from spring.langchain.prompts.templates import PromptTemplateFactory

factory = PromptTemplateFactory()

# 1. 普通 PromptTemplate（单变量）
pt = factory.create_prompt_template("请把以下文本翻译成{lang}：{text}")
print(pt.format(lang="英文", text="你好"))

# 2. ChatPromptTemplate（多角色）
ct = factory.create_chat_prompt_template([
    {"role": "system", "content": "你是翻译助手"},
    {"role": "user", "content": "把'{text}'翻译成{lang}"},
])
msgs = ct.format_messages(text="你好", lang="英文")

# 3. FewShotPromptTemplate（带示例）
fs = factory.create_few_shot_prompt_template(
    examples=[{"input": "高兴", "output": "sad"}],   # 反义词示例
    example_prompt=factory.create_prompt_template("输入：{input}\n输出：{output}"),
    suffix="输入：{input}\n输出：",
    input_variables=["input"],
)
print(fs.format(input="大"))
```

> ⚠️ 兼容性提示：旧版 langchain 有 `ChatPromptTemplate.from_tuples`，langchain 1.x 已移除。本工厂内部统一用 `from_messages`，无需关心版本差异。

### 5.2 ChainService（chains）

封装 langchain classic 的各类 Chain：

| 方法 | 对应 langchain Chain | 用途 |
|------|---------------------|------|
| `run_llm_chain(template, **inputs)` | `LLMChain` | 单次问答（模板字符串 + 变量） |
| `run_conversation(input, memory)` | `ConversationChain` | 带记忆多轮对话 |
| `create_sequential_chain(chains, ...)` | `SequentialChain` | 串联多 Chain（先翻译再总结） |
| `run_summarize(texts)` | `load_summarize_chain` | 文档摘要 |
| `create_llm_math_chain()` | `LLMMathChain` | 数学计算 |
| `create_retrieval_qa(retriever)` | `RetrievalQA` | RAG 问答 |

```python
from spring.langchain.chains.services import ChainService

# 注入 lcLangChainModel（由 configure_langchain 自动创建）
service = ChainService(lcLangChainModel=lc_model)

# 1. 单次问答（便捷方法 run_llm_chain：模板字符串 + 变量）
print(service.run_llm_chain("回答问题：{q}", q="什么是 SpringBootAI？"))

# 2. 带记忆多轮（memory 不传时自动创建 buffer）
print(service.run_conversation("我叫张三"))
print(service.run_conversation("我叫什么？"))  # 会记住"张三"

# 3. 串联：先翻译再总结
from langchain.chains import LLMChain
from langchain_core.prompts import PromptTemplate
t_chain = LLMChain(llm=lc_model, prompt=PromptTemplate.from_template("翻译成英文：{input}"))
s_chain = LLMChain(llm=lc_model, prompt=PromptTemplate.from_template("一句话总结：{input}"))
print(service.run_sequential("SpringBootAI 是一个 Python Web 框架",
                             chains=[t_chain, s_chain]))
```

### 5.3 AgentService（agents）

封装 6 种 Agent 类型：

| agent_type | 对应 langchain | 适用场景 |
|-----------|----------------|----------|
| `react` | `ZERO_SHOT_REACT_DESCRIPTION` | 经典 ReAct，通用 |
| `chat-zero-shot-react` | `CHAT_ZERO_SHOT_REACT_DESCRIPTION` | 对话版 ReAct |
| `openai-functions` | `OPENAI_FUNCTIONS` | OpenAI 原生函数调用 |
| `openai-tools` | `create_openai_tools_agent` | OpenAI tools API（推荐） |
| `structured-chat` | `create_structured_chat_agent` | 结构化工具调用（多行 JSON 参数） |
| `self-ask-with-search` | `SELF_ASK_WITH_SEARCH` | 自问自答搜索 |

> `structured-chat` 和 `openai-tools` 走专用工厂函数（无 `AgentType` 枚举值），但已集成进 `create_agent(agent_type=...)` 统一入口，无需单独调用 `create_structured_chat_agent` / `create_openai_tools_agent`。

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

# 2. 新版 create_react_agent（推荐）
executor = agent_service.create_react_agent(tools=[DuckDuckGoSearchRun()])
print(agent_service.run_agent(executor, "Python 3.12 发布日期？"))

# 3. OpenAI tools agent（需 OpenAI 模型）
executor = agent_service.create_openai_tools_agent(tools=[...])
```

> ⚠️ 兼容性提示：langchain 1.x 的 `create_react_agent` 要求 prompt 含 `{tool_names}` 变量。本服务的 prompt 模板已内置该变量，无需手动处理。

### 5.4 MemoryFactory（memory）

| type | 对应 langchain Memory | 特点 |
|------|----------------------|------|
| `buffer` | `ConversationBufferMemory` | 全量保留 |
| `summary` | `ConversationSummaryMemory` | LLM 摘要压缩 |
| `buffer-window` | `ConversationBufferWindowMemory` | 只保留最近 N 轮 |
| `token-buffer` | `ConversationTokenBufferMemory` | 按 token 数截断 |

```python
from spring.langchain.memory.memory import MemoryFactory

# buffer-window：max_messages 控制窗口大小（非 k）
memory = MemoryFactory.create("buffer-window", max_messages=5)
chain_service.run_conversation("你好", memory=memory)
```

### 5.5 OutputParserFactory（parsers）

把模型返回的文本解析成结构化 Python 对象：

```python
from spring.langchain.parsers.parsers import OutputParserFactory

# 1. 列表解析
parser = OutputParserFactory.create("comma-list")
print(parser.parse("a, b, c"))   # ['a', 'b', 'c']

# 2. 日期解析
parser = OutputParserFactory.create("datetime")
print(parser.parse("2026-08-10T12:00:00.000Z"))  # datetime(2026, 8, 10, 12, 0)

# 3. JSON 解析
parser = OutputParserFactory.create("json")
print(parser.parse('{"name": "张三", "age": 18}'))

# 4. Pydantic 解析（结构化输出）- 参数名是 pydantic_model（非 pydantic_object）
from pydantic import BaseModel
class Person(BaseModel):
    name: str
    age: int
parser = OutputParserFactory.create("pydantic", pydantic_model=Person)
print(parser.parse('{"name": "张三", "age": 18}'))  # Person(name='张三', age=18)
```

> ⚠️ `DatetimeOutputParser` 默认期望 ISO 8601 带毫秒格式，如 `2026-08-10T12:00:00.000Z`。不带毫秒的字符串可能解析失败。

### 5.6 DocumentLoaderRegistry（loaders）

从多种来源读取文档：

```python
from spring.langchain.loaders.loaders import DocumentLoaderRegistry

registry = DocumentLoaderRegistry()

# 1. 文本文件（注意：source 是文件路径，不是文本内容）
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

> ⚠️ `TextLoader` 的 source 参数是**文件路径**，不能直接传文本字符串。如果要把内存中的字符串变成 Document，请直接 `from langchain_core.documents import Document; doc = Document(page_content="Hello")`。

### 5.7 VectorStoreFactory（vectorstores）

| store_type | 对应 langchain | 依赖 |
|-----------|----------------|------|
| `inmemory` | springbootAI `SimpleInMemoryVectorStore` | 无（内置） |
| `faiss` | `FAISS` | faiss-cpu + langchain_community |
| `chroma` | `Chroma` | langchain_chroma |
| `pinecone` | `Pinecone` | langchain_pinecone |
| `weaviate` | `Weaviate` | langchain_weaviate |
| `pgvector` | `PGVector` | langchain_postgres |
| `redis` | `Redis` | langchain_community + redis |

```python
from spring.langchain.vectorstores.stores import VectorStoreFactory

# 1. 内存向量库（无需任何依赖）
store = VectorStoreFactory.from_texts(
    "inmemory",
    ["SpringBootAI 用 @Service", "LangChain 提供 Chain"],
    embeddings=lc_emb,
)

# 2. FAISS（需 pip install faiss-cpu langchain-community）
store = VectorStoreFactory.from_texts(
    "faiss",
    ["文档A", "文档B"],
    embeddings=lc_emb,
)
```

> ⚠️ **桥接细节**：`inmemory` 类型用的是 springbootAI 内置 `SimpleInMemoryVectorStore`，它的 `add()` 调用 `embedding_model.embed_one()`（springbootAI 接口）。而本工厂接收的 `embeddings` 通常是 langchain `Embeddings`（只有 `embed_query`/`embed_documents`）。工厂内部用 `_ensure_spring_embedding` 做反向桥接，保证接口匹配——你不需要关心，直接传 langchain Embeddings 即可。

### 5.8 RetrieverFactory（retrievers）

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
```

### 5.9 IndexService（indexes）—— 一键 RAG

把"创建向量库 + 写入文档 + 检索"三步合一：

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
```

> ⚠️ springbootAI 内置 `SimpleInMemoryVectorStore` 没有 `as_retriever` 方法，`IndexService.query` 会自动回退到 `similarity_search` 直接检索。

### 5.10 ToolFactory / ToolRegistry（tools）

```python
from spring.langchain.tools.tools import ToolFactory, ToolRegistry

# 1. 把普通函数包成 langchain StructuredTool
def add(a: int, b: int) -> int:
    """加法"""
    return a + b
tool = ToolFactory.from_function(add, name="add", description="加法")

# 2. ToolRegistry 收集多个工具（add / add_function / all）
registry = ToolRegistry()
registry.add_function(add, name="add", description="加法")
# 供 Agent 使用：all() 返回 langchain BaseTool 列表
tools = registry.all()
```

### 5.11 UtilityRegistry（utilities）

LangChain 内置的现成工具，按需懒加载：

```python
from spring.langchain.utilities.utils import UtilityRegistry

# 1. DuckDuckGo 搜索（无需 API Key）
search = UtilityRegistry.create("duckduckgo")
print(search.run("Python 3.12 发布日期"))

# 2. Wikipedia
wiki = UtilityRegistry.create("wikipedia")
print(wiki.run("LangChain"))

# 3. Python REPL（执行代码）- 注意是连字符 python-repl，非下划线
repl = UtilityRegistry.create("python-repl")

# 4. Arxiv（论文搜索）
arxiv = UtilityRegistry.create("arxiv")

# 5. SQLDatabase（连数据库）- 注意是连字符 sql-database
db = UtilityRegistry.create("sql-database", uri="sqlite:///test.db")
```

### 5.12 CallbackRegistry（callbacks）

挂在模型调用流程上的监听器：

```python
from spring.langchain.callbacks.handlers import CallbackRegistry

# 1. 标准输出回调（无统一 create 方法，用专用工厂方法）
cb = CallbackRegistry.create_stdout_handler()
# 2. 流式标准输出
cb = CallbackRegistry.create_streaming_stdout_handler()
# 3. 写文件
cb = CallbackRegistry.create_file_handler("./llm.log")

# 传给 Chain：通过 langchain 的 config={"callbacks": [...]} 参数
chain = chain_service.create_llm_chain(prompt=your_prompt)
result = chain.invoke({"q": "你好"}, config={"callbacks": [cb]})
```

> ⚠️ 便捷方法 `run_llm_chain` / `run_conversation` 不暴露 callbacks 参数。需要回调时请用 `create_xxx_chain()` 取得 Chain 实例后手动 `invoke(input, config={"callbacks": [...]})`。

---

## 6. 自动装配（configure_langchain）

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

### 6.1 双重注册机制

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

> ⚠️ `BeanFactory.get_bean` 要求先有 `BeanDefinition` 才会查 `_bean_instances`，只 `register_instance` 不够。`_register_bean` 同时注册 definition + instance，让两套查找都生效。

### 6.2 装配时机

`configure_langchain` 必须在 `@Service` 实例化**之前**完成，否则 `@Autowired` 找不到 `lc*` Bean。在 SpringBootAI 应用中，推荐用 `@Configuration` 类在 `__init__` 中触发：

```python
@Configuration
class LangChainAppConfig:
    def __init__(self):
        registry = BeanRegistry()
        configure_ai(registry=registry, config=config_loader)
        configure_langchain(registry=registry, config=config_loader)
```

`@Configuration` 类在 `ApplicationContext.refresh` 的 `_register_configuration_beans` 阶段被实例化（早于 `@Service` 的 `_autowire_value_annotations` 阶段），因此 lc* Bean 一定先于 `@Service` 就绪。

---

## 7. 示例应用（example_langchain）

项目自带一个完整的演示应用 [example_langchain/](file:///e:/spring/springbootAI-master/springbootAI-master/example_langchain)，演示如何把 LangChain 模块集成进 SpringBootAI 应用：

```
example_langchain/
├── Application.py                              # @SpringBootApplication 启动类
├── config/LangChainAppConfig.py                # @Configuration 装配 AI + LangChain
├── controller/LangChainController.py           # @RestController REST 接口
└── service/
    ├── LangChainChatService.py                 # 问答/翻译/摘要
    ├── LangChainAgentService.py                # Agent 执行
    ├── LangChainRagService.py                  # RAG 入库/检索
    └── LangChainChainService.py                # Chain/Memory/Math/Parser
```

### 7.1 启动

```bash
# 无 API Key 也能跑（降级 FakeChatModel）
$env:AI_ALLOW_FAKE = "true"
python example_langchain/Application.py
# 服务监听 8081 端口
```

### 7.2 HTTP 接口

| 方法 | 路径 | 功能 | 请求体 |
|------|------|------|--------|
| POST | `/api/lc/chat` | 基础问答 | `{"question": "..."}` |
| POST | `/api/lc/translate` | 翻译 | `{"text": "...", "target_lang": "英文"}` |
| POST | `/api/lc/summarize` | 总结 | `{"text": "..."}` |
| POST | `/api/lc/agent` | Agent 执行 | `{"question": "...", "agent_type": "react"}` |
| POST | `/api/lc/rag/add` | RAG 文档入库 | `{"docs": ["文本1", "文本2"]}` |
| POST | `/api/lc/rag/query` | RAG 检索问答 | `{"question": "...", "k": 3}` |
| POST | `/api/lc/memory` | 带记忆对话 | `{"input": "..."}` |
| POST | `/api/lc/math` | 数学计算 | `{"expression": "2+3*4"}` |
| POST | `/api/lc/parse-list` | 列表解析 | `{"text": "a, b, c"}` |
| POST | `/api/lc/embed` | 文本嵌入 | `{"texts": ["a", "b"]}` |
| GET | `/api/lc/providers` | 列出已启用 partner | — |
| GET | `/api/lc/capabilities` | 列出模块全部能力 | — |

调用示例：

```bash
curl -X POST http://localhost:8081/api/lc/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "什么是 SpringBootAI？"}'

curl -X POST http://localhost:8081/api/lc/rag/add \
  -H "Content-Type: application/json" \
  -d '{"docs": ["SpringBootAI 是 Python Web 框架", "LangChain 提供 AI 抽象"]}'

curl -X POST http://localhost:8081/api/lc/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question": "SpringBootAI 是什么？", "k": 2}'
```

### 7.3 分层规范

演示应用严格遵守 SpringBootAI 分层：

- **Controller**（`LangChainController`）：只接 HTTP 请求、校验参数、调用 Service、包装 `Result` 返回，不写业务逻辑。
- **Service**（`LangChainChatService` 等）：业务规则，通过 `@Autowired` 注入 `lcChainService` / `lcAgentService` / `lcIndexService` 等 Bean。
- **Configuration**（`LangChainAppConfig`）：启动时装配 AI + LangChain 模块。
- **Application**（`Application`）：`@SpringBootApplication` 触发组件扫描。

```python
@Service
class LangChainChatService:
    @Autowired
    def __init__(self, lcChainService: ChainService):
        self.chain = lcChainService

    def ask(self, question: str) -> str:
        return self.chain.run_simple(question)
```

---

## 8. 单元测试

测试文件 [tests/test_langchain_module.py](file:///e:/spring/springbootAI-master/springbootAI-master/tests/test_langchain_module.py) 覆盖 15 个测试类、66 个测试方法：

| 测试类 | 覆盖范围 |
|--------|----------|
| `TestAdapters` | 四个双向适配器的调用与桥接正确性 |
| `TestLangChainProperties` | 类型化配置绑定、env 覆盖、类型转换 |
| `TestAutoConfig` | `configure_langchain` 装配的 Bean 完整性与双重注册 |
| `TestPartners` | Partner 注册表、探测、实例化（用 fake 模型） |
| `TestPromptTemplates` | 三种 Prompt 模板的格式化 |
| `TestChainService` | LLMChain / Conversation / Sequential / Summary / Math |
| `TestAgentService` | ReAct / OpenAI-tools / structured-chat Agent |
| `TestMemoryFactory` | 四种 Memory 类型的创建与使用 |
| `TestOutputParsers` | comma-list / datetime / json / pydantic |
| `TestVectorStoreFactory` | inmemory 向量库的入库与检索 |
| `TestRetrieverFactory` | similarity 检索器 |
| `TestIndexService` | 一键 RAG 流程 |
| `TestToolFactory` | Tool 创建与注册 |
| `TestUtilityRegistry` | DuckDuckGo / Wikipedia 工具探测 |
| `TestEndToEndIntegration` | 端到端 RAG 流水线（fake 模型跑通） |

运行测试：

```bash
cd e:\spring\springbootAI-master\springbootAI-master
python -m pytest tests/test_langchain_module.py -v
```

测试全部用 `FakeChatModel` / `FakeEmbeddingModel` 跑，无需真实 API Key、无需联网。

---

## 9. 完整迁移说明（给从 langchain-master 迁过来的用户）

### 9.1 迁移策略

`langchain-master` 是整个 LangChain 框架的 monorepo（含 ~28 个 classic 子模块 + 30+ partner 包，数千个文件）。本模块**没有**把 langchain 源码复制进 springbootAI，而是：

1. **保留 langchain 作为 pip 依赖**：用户 `pip install langchain langchain-classic langchain-openai ...` 即可。
2. **封装为 Spring 风格 Bean**：每个 langchain 组件（Chain / Agent / Memory / VectorStore / Retriever / Parser / Loader / Tool / Utility / Callback）都对应一个 `@Service` / `@Component` 类，由 `configure_langchain()` 统一装配。
3. **partner 用注册表懒加载**：30+ 提供商用一张 `PARTNER_REGISTRY` 描述元数据，按 `application.yml` 配置按需实例化，未配置的不加载。

### 9.2 迁移前后对照

| 原 langchain 用法 | 迁移后 SpringBootAI 用法 |
|------------------|------------------------|
| `from langchain.chains import LLMChain; LLMChain(llm=model, prompt=pt).run("hi")` | `chain_service.run_simple("hi")` |
| `from langchain.agents import initialize_agent; initialize_agent(tools, llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION)` | `agent_service.create_agent(tools, agent_type="react")` |
| `from langchain.memory import ConversationBufferMemory; ConversationBufferMemory()` | `MemoryFactory.create("buffer")` |
| `from langchain_community.vectorstores import FAISS; FAISS.from_texts(texts, embedding=emb)` | `VectorStoreFactory.from_texts("faiss", texts, embeddings=emb)` |
| `from langchain_openai import ChatOpenAI; ChatOpenAI(api_key=..., model=...)` | `application.yml` 配 `partners.openai`，`configure_langchain` 自动注册 |
| 手动 `new` 一堆组件 | `@Autowired` 注入 `lc*Service` Bean |

### 9.3 迁移后保留的能力

- ✅ 全部 Chain 类型（LLMChain / ConversationChain / SequentialChain / RetrievalQA / Summarization / LLMMath）
- ✅ 全部 Agent 类型（ReAct / chat-zero-shot-react / openai-functions / openai-tools / structured-chat / self-ask-with-search）
- ✅ 全部 Memory 类型（buffer / summary / buffer-window / token-buffer）
- ✅ 全部主流 VectorStore（FAISS / Chroma / Pinecone / Weaviate / PGVector / Redis / inmemory）
- ✅ 全部 Retriever 类型（similarity / multi-query / contextual-compression / self-query / time-weighted / ensemble）
- ✅ 全部 OutputParser（comma-list / datetime / json / pydantic / enum）
- ✅ 全部 DocumentLoader（text / csv / pdf / web / directory / json）
- ✅ 全部 Utility（SerpAPI / DuckDuckGo / Wikipedia / PythonREPL / SQLDatabase / Arxiv）
- ✅ 全部 Callback（StdOut / StreamingStdOut / File）
- ✅ 30+ Partner 提供商（OpenAI / Anthropic / Ollama / DeepSeek / ZhipuAI / Tongyi / Mistral / Cohere / Bedrock …）

### 9.4 已修复的兼容性问题

迁移过程中修复了以下 langchain 1.x 兼容性问题（详见各源码文件注释）：

| 问题 | 修复方式 | 位置 |
|------|---------|------|
| `ChatPromptTemplate.from_tuples` 在 1.x 被移除 | 改用 `from_messages` | prompts/templates.py |
| `create_react_agent` 要求 prompt 含 `{tool_names}` | 在 system prompt 中加入该变量 | agents/services.py |
| `create_structured_chat_agent` 同样要求 `{tools}`/`{tool_names}` | 同上，补全 prompt 变量 | agents/services.py |
| `structured-chat`/`openai-tools` 未接入 `create_agent` 统一入口 | `create_agent` 内部分流到专用工厂 | agents/services.py |
| `bind_tools` 返回 self 未真正绑定工具 | 转为 springbootAI ToolRegistry + 返回新实例 | adapters.py |
| `LLMChain` 弃用告警刷屏 | `warnings.filterwarnings` 屏蔽 | agents/services.py |
| springbootAI `SimpleInMemoryVectorStore` 接口与 langchain `Embeddings` 不匹配 | `_ensure_spring_embedding` 反向桥接 | vectorstores/stores.py |
| `SimpleInMemoryVectorStore` 无 `as_retriever` 方法 | 回退到 `similarity_search` 直接检索 | indexes/index.py |
| `ConversationChain` 未传 memory 时空指针 | 自动创建默认 buffer memory | chains/services.py |
| `calculator`/`math` 用 `eval()` 存在沙箱逃逸漏洞 | 用 AST 安全求值器替代 `eval` | example_langchain |
| `LangChainRagService` 绕过 `IndexService` 重复实现 | 复用 `IndexService.create_from_texts`/`query` | example_langchain |
| `MemoryFactory` buffer-window 冗余传 llm | 移除不必要的 llm 参数 | memory.py |
| `autoconfig._register_partners` 冗余 `pass` | 删除空操作 | autoconfig.py |
| 文档方法名/参数名与代码不一致（11 处） | 全部对齐 | LANGCHAIN_MODULE.md |

---

## 10. 常见问题（FAQ）

**Q1：没有 API Key 能跑吗？**
A：能。设置 `AI_ALLOW_FAKE=true`，`configure_ai` 会降级 `FakeChatModel` / `FakeEmbeddingModel`，整个 LangChain 流程（Chain / Agent / RAG / Memory）都能演示，只是模型回复是假数据。

**Q2：怎么换 partner？**
A：两种方式：① 改 `application.yml` 的 `spring.langchain.default-llm` 为 partner 名（如 `anthropic`），并在 `partners.anthropic` 下配 key/model；② 直接 `PartnerProviderFactory.create("anthropic", cfg)` 手动创建。

**Q3：某个 partner 的包没装会怎样？**
A：`configure_langchain` 会捕获 `ImportError`，告警 `"Partner 'xxx' 注册失败（跳过）"`，不阻塞启动。其他 partner 和模块功能不受影响。

**Q4：FAISS / Chroma 等向量库怎么选？**
A：学习/测试用 `inmemory`（无依赖）；中小规模用 `faiss`（`pip install faiss-cpu`）；持久化用 `chroma` 或 `redis`；生产大规模用 `pinecone` / `weaviate` / `pgvector`。

**Q5：RAG 报 `嵌入模型未装配`？**
A：`configure_ai` 默认会装 `aiEmbeddingModel`，但需要 `OPENAI_API_KEY`（或 `OLLAMA_BASE_URL`）。无 Key 时设 `AI_ALLOW_FAKE=true` 会降级 `FakeEmbeddingModel(dim=16)`，RAG 可演示但不真实。

**Q6：`@Autowired` 注入 `lcChainService` 报 `Cannot resolve parameter`？**
A：确认 `@Configuration` 类的 `__init__` 中调用了 `configure_langchain`，且该 `@Configuration` 类在 `@Service` 之前被实例化（SpringBootAI 默认保证这个顺序）。

**Q7：怎么自定义一个 partner？**
A：在 `PARTNER_REGISTRY` 中加一项 `name -> (module, chat_cls, emb_cls)`，然后在 `application.yml` 的 `partners.<name>` 下配置即可。无需改任何 `@Service` 代码。

---

## 11. 模块组成速查

| 文件 | 职责 |
|------|------|
| [adapters.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/adapters.py) | springbootAI ↔ langchain 模型/嵌入/向量库 双向桥接 |
| [partners.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/partners.py) | 30+ Partner 提供商工厂注册表（懒加载） |
| [autoconfig.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/autoconfig.py) | LangChainProperties + configure_langchain 自动装配 |
| [prompts/templates.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/prompts/templates.py) | PromptTemplate / ChatPromptTemplate / FewShot 工厂 |
| [chains/services.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/chains/services.py) | ChainService（LLMChain / Conversation / Sequential / RetrievalQA / 摘要 / Math） |
| [agents/services.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/agents/services.py) | AgentService（ReAct / OpenAI-tools / structured-chat） |
| [memory/memory.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/memory/memory.py) | MemoryFactory（buffer / summary / buffer-window / token-buffer） |
| [parsers/parsers.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/parsers/parsers.py) | OutputParserFactory（comma-list / datetime / json / pydantic / enum） |
| [loaders/loaders.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/loaders/loaders.py) | DocumentLoaderRegistry（text / csv / pdf / web / directory / json） |
| [retrievers/retrievers.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/retrievers/retrievers.py) | RetrieverFactory（similarity / multi-query / …） |
| [vectorstores/stores.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/vectorstores/stores.py) | VectorStoreFactory（FAISS / Chroma / Pinecone / Weaviate / PGVector / Redis / inmemory） |
| [indexes/index.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/indexes/index.py) | IndexService（一键 RAG） |
| [tools/tools.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/tools/tools.py) | ToolFactory / ToolRegistry（langchain Tool 与 springbootAI @Tool 互转） |
| [utilities/utils.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/utilities/utils.py) | UtilityRegistry（SerpAPI / DuckDuckGo / Wikipedia / PythonREPL / SQLDatabase / Arxiv） |
| [callbacks/handlers.py](file:///e:/spring/springbootAI-master/springbootAI-master/spring/langchain/callbacks/handlers.py) | CallbackRegistry（StdOut / StreamingStdOut / File） |
| [example_langchain/](file:///e:/spring/springbootAI-master/springbootAI-master/example_langchain) | 完整演示应用（Controller + Service + Configuration） |
| [tests/test_langchain_module.py](file:///e:/spring/springbootAI-master/springbootAI-master/tests/test_langchain_module.py) | 15 个测试类、66 个测试方法 |

---

## 12. 与 spring.ai 模块的关系

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
