# SpringBootAI AI 模块使用指南

> 对齐 Spring AI 2.0：ChatClient / Advisor / Tools / RAG / Function Calling / ETL / 多厂商 LangChain 化 / 韧性 / 观测。
> 本文档从 README.md 第 12 节分离而来，作为 AI 模块的独立完整说明。
> 安装：`pip install springbootAI[ai]` ｜ 框架版本：SpringBootAI 1.8.4 / SpringBootAI AI 1.3.0

---

## 阅读前准备

第一次使用先完成 [新手入门指南](BEGINNER_GUIDE.md) 的普通 HTTP 接口，再学习本模块。调用云端模型通常会产生费用并把请求内容发送给第三方 Provider；不要把生产密钥、个人信息、未脱敏客户数据直接放入提示词。建议先用测试密钥、限额账号或本地 Ollama 跑通最小示例。

学习顺序建议：基础聊天 -> 流式输出 -> 会话记忆 -> Tools -> RAG -> Redis 持久化与监控。每一步都先验证错误处理、超时和费用，再进入下一步。

SpringBootAI AI 模块对齐 **Spring AI 2.0**，提供 `ChatClient`/`ChatModel`/`EmbeddingModel`/`Advisor`/`Tools` 抽象，底层复用 LangChain 生态做模型适配（未安装时降级原生 HTTP），上层保留 Spring 风格的统一配置（`application.yml` 的 `spring.ai.*`）与依赖注入（BeanRegistry）。

**核心能力**：
- **多 Provider 适配**：OpenAI / Ollama / DeepSeek / Moonshot / Zhipu（LangChain 优先，HTTP 降级）
- **ChatClient 链式 API**：`client.prompt().user("...").call().content()`，对齐 Spring AI
- **Function Calling 闭环**：tools 自动注入请求体 + tool_call 循环执行回填续写（最多 5 轮）
- **RAG**：QuestionAnswerAdvisor + VectorStore（InMemory / Redis 持久化）
- **会话记忆**：MessageChatMemoryAdvisor（InMemory / Redis，多轮对话）
- **文档 ETL**：TextReader / TokenTextSplitter / CharacterTextSplitter
- **企业级能力**：熔断重试韧性（复用 spring.retry）、真流式 SSE+async、Prometheus 观测、Redis 向量存储
- **类型化配置绑定**：`AIProperties` dataclass + env 覆盖安全网

### 12.0 新手入门：AI 模块是什么？用来做什么？

> 如果你是第一次接触本项目，请先读这一节。它会用大白话讲清楚：**为什么要用 AI 模块**、**它有哪些东西**、**怎么一步一步用起来**。后面的 12.1~12.11 是详细的技术文档，遇到不懂的再回来查这里。

#### ① 它是干什么的？（目的）

简单说：**让你的 Python 程序能调用大语言模型（LLM）**——也就是让程序会「说话、理解、写代码、回答问题、查资料、调用工具」。

现实里它常被用来做这些事：

- **智能客服/聊天机器人**：程序能记住对话、像真人一样回答（记忆 + 聊天）
- **知识库问答**：把你自己的一堆文档喂进去，程序能"读了你的资料再回答"（这就是 **RAG**）
- **写代码助手**：让模型根据你的要求生成或改写代码
- **流程自动化**：让模型决定调用哪个函数（比如查天气、算价格），这就是 **Function Calling（工具调用）**

你不需要自己训练模型，只需要**申请一个模型的 API Key，然后在配置里填进去**，就能用了。

#### ② 里面有哪些概念？（新手版比喻）

| 术语 | 大白话 | 比喻 |
|------|--------|------|
| **ChatModel**（模型） | 真正"会说话"的那个大脑 | 大脑 |
| **API Key** | 使用模型的"钥匙"，证明你有权限、按用量付费 | 门禁卡 |
| **ChatClient** | 你和大模型对话的方式（链式写法） | 说话的嘴 |
| **Prompt** | 你发给模型的指令/问题 | 你说的话 |
| **Memory**（记忆） | 让模型记住前面的对话，能多轮聊下去 | 记性 |
| **RAG**（知识库问答） | 先把资料切碎存起来，回答时先检索相关资料再回答 | 查资料再答题 |
| **EmbeddingModel** | 把文字变成一串数字，用来做"相似度查找" | 给文字贴标签编号 |
| **VectorStore**（向量库） | 存这些"数字编号"的地方，用来快速检索 | 资料索引柜 |
| **Tools / Function Calling** | 让模型调用你写好的 Python 函数 | 手脚 |
| **Advisor**（顾问） | 挂在对话前后的"插件"，帮你做记忆、检索等 | 助手 |
| **ETL** | 把文档读进来、切成小块、存进向量库的流程 | 整理资料入库 |
| **FakeChatModel** | 不联网的假模型，专门用来开发/测试，不花钱 | 练习机器人 |

#### ③ 新手三步走：从零跑通第一个 AI 程序

**第 1 步：安装依赖**

```bash
pip install -r requirements-ai.txt
```

**第 2 步：先在本地用"假模型"跑通（不花钱、不联网）**

> 假模型不需要 API Key，非常适合先理解代码怎么写、流程怎么走。

```python
from spring.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

**第 3 步：接上真实模型（需要申请 Key）**

1. 去模型厂商官网申请 API Key（比如 DeepSeek、OpenAI、Moonshot）
2. 设置环境变量（把 `sk-你的真实key` 换成你自己的），**不要把真实 Key 写进代码或文档**：

```bash
export AI_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-你的真实key
```

3. 用自动装配的方式运行：

```python
from spring.ai import configure_ai

beans = configure_ai()          # 读环境变量/application.yml，自动创建好所有 AI 组件
client = beans["aiChatClient"]  # 拿到的就是"会聊天的助手"
print(client.prompt().user("你好").call().content())
```

到这里，你就已经成功让程序和大模型对话了。

#### ④ 进阶：最常用的 3 个能力（新手按需选学）

- **想让它记住多轮对话** → 看 [12.3/12.5 记忆](#123-ai-注解)（加一个 MemoryAdvisor 即可）
- **想让它"读了你的资料再回答"** → 看 [12.6 RAG/ETL](#126-文档-etl知识库入库)：先把文档切碎入库，再提问
- **想让它调用你的函数** → 看 [12.7 工具调用](#127-工具函数调用)：用 `@Tool` 装饰你的函数

#### ⑤ 新手常见误区

- ❌ 以为必须自己训练模型 → ✅ 只需申请 API Key
- ❌ 把真实 Key 写进代码/文档提交到公开仓库 → ✅ 用环境变量注入
- ❌ 问完就忘、无法多轮 → ✅ 需要加 Memory（记忆）
- ❌ 问"我自己的资料"模型说不知道 → ✅ 要用 RAG，先把资料切碎入库再问
- ❌ 没配 Key 就以为是真模型在回答 → ✅ 没配 Key 会静默降级成 `FakeChatModel`，生产环境务必设 `AI_ALLOW_FAKE=false` 防止误用假数据

### 12.1 快速开始

```bash
pip install -r requirements-ai.txt
```

最小示例（无需真实 API key，降级 FakeChatModel 即可运行）：

```python
from spring.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

接入真实 OpenAI 兼容模型：

```python
from spring.ai import configure_ai

# 读取 application.yml 的 spring.ai.* 配置，自动装配所有 Bean
beans = configure_ai()
client = beans["aiChatClient"]
print(client.prompt().user("你好").call().content())
```

只需在 `application.yml` 或环境变量配置 `OPENAI_API_KEY` 即可启用真实模型；未配置时降级 `FakeChatModel`（开发/测试友好）。

### 12.2 配置（application.yml）

```yaml
spring:
  ai:
    default-provider: ${AI_PROVIDER:openai}   # openai | ollama | deepseek | moonshot | zhipu
    max-retries: ${AI_MAX_RETRIES:3}
    retry-delay-ms: ${AI_RETRY_DELAY_MS:500}
    openai:
      api-key: ${OPENAI_API_KEY:}
      base-url: ${OPENAI_BASE_URL:https://api.openai.com/v1}  # 兼容 Azure
      chat:
        model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
        temperature: ${OPENAI_TEMPERATURE:0.7}
      embedding:
        model: ${OPENAI_EMBEDDING_MODEL:text-embedding-3-small}
    ollama:
      base-url: ${OLLAMA_BASE_URL:http://localhost:11434}
      chat:
        model: ${OLLAMA_CHAT_MODEL:llama3}
        temperature: ${OLLAMA_TEMPERATURE:0.7}
    # OpenAI 兼容多厂商（经 OpenAICompatChatModel 接入，底层优先 LangChain 专用包）
    deepseek:
      api-key: ${DEEPSEEK_API_KEY:}
      base-url: ${DEEPSEEK_BASE_URL:https://api.deepseek.com}
      model: ${DEEPSEEK_MODEL:deepseek-chat}
      temperature: ${DEEPSEEK_TEMPERATURE:0.7}
    moonshot:
      api-key: ${MOONSHOT_API_KEY:}
      base-url: ${MOONSHOT_BASE_URL:https://api.moonshot.cn/v1}
      model: ${MOONSHOT_MODEL:moonshot-v1-8k}
      temperature: ${MOONSHOT_TEMPERATURE:0.7}
    zhipu:
      api-key: ${ZHIPUAI_API_KEY:}
      base-url: ${ZHIPUAI_BASE_URL:https://open.bigmodel.cn/api/paas/v4}
      model: ${ZHIPUAI_MODEL:glm-4-flash}
      temperature: ${ZHIPUAI_TEMPERATURE:0.7}
    vector-store:
      type: ${AI_VECTOR_STORE:inmemory}        # inmemory | redis
      collection: ${AI_VECTOR_COLLECTION:default}
    memory:
      store: ${AI_MEMORY_STORE:inmemory}        # inmemory | redis
      max-messages: ${AI_MEMORY_MAX:20}
    circuit-breaker:
      enabled: ${AI_CB_ENABLED:true}
      failure-threshold: ${AI_CB_FAILURE_THRESHOLD:5}
      recovery-timeout: ${AI_CB_RECOVERY_TIMEOUT:30}
```

**配置读取（混合方式）**：`configure_ai()` 读取 `spring.ai.*` 子树后，用类型化 `AIProperties` dataclass 绑定。优先级：**环境变量 > application.yml > dataclass 默认值**。环境变量通过两条路径生效：① config_loader 解析 yml 的 `${ENV:default}` 占位符；② dataclass 字段 `metadata["env"]` 声明的 env 名作为覆盖安全网（即使 yml 写死字面值也能被同名 env 覆盖）。字段类型注解驱动自动类型转换（`int`/`float`/`bool`），无需手动 `int()`/`float()`。

```python
from spring.ai import AIProperties, bind_ai_config

props: AIProperties = bind_ai_config({
    "default-provider": "openai",
    "openai": {"api-key": "sk-x", "chat": {"temperature": "0.3"}},  # 字符串自动转 float
    "circuit-breaker": {"enabled": "false"},                          # 字符串自动转 bool
})
assert props.openai.chat.temperature == 0.3
assert isinstance(props.openai.chat.temperature, float)
assert props.circuit_breaker.enabled is False
```

**环境变量速查**：

| 配置键 | 环境变量 | 默认值 |
|--------|---------|--------|
| default-provider | AI_PROVIDER | openai |
| max-retries | AI_MAX_RETRIES | 3 |
| retry-delay-ms | AI_RETRY_DELAY_MS | 500 |
| openai.api-key | OPENAI_API_KEY | （空，降级 Fake） |
| openai.base-url | OPENAI_BASE_URL | https://api.openai.com/v1 |
| openai.chat.model | OPENAI_CHAT_MODEL | gpt-4o-mini |
| openai.chat.temperature | OPENAI_TEMPERATURE | 0.7 |
| openai.embedding.model | OPENAI_EMBEDDING_MODEL | text-embedding-3-small |
| ollama.base-url | OLLAMA_BASE_URL | http://localhost:11434 |
| ollama.chat.model | OLLAMA_CHAT_MODEL | llama3 |
| vector-store.type | AI_VECTOR_STORE | inmemory |
| vector-store.collection | AI_VECTOR_COLLECTION | default |
| memory.store | AI_MEMORY_STORE | inmemory |
| memory.max-messages | AI_MEMORY_MAX | 20 |
| circuit-breaker.enabled | AI_CB_ENABLED | true |
| circuit-breaker.failure-threshold | AI_CB_FAILURE_THRESHOLD | 5 |
| circuit-breaker.recovery-timeout | AI_CB_RECOVERY_TIMEOUT | 30 |

**Redis 持久化（复用框架 RedisClient）**：当 `vector-store.type=redis` 或 `memory.store=redis` 时，`configure_ai` 自动复用框架全局 `spring.utils.redis_client.redis_client` 单例，**无需手动传 redis_client 参数**。`RedisVectorStore` 与 `RedisChatMemory` 统一用框架 `RedisClient` 封装接口（`hash_set`/`hash_get_all`/`list_push`/`list_range`），同一个 client 同时满足两者。若传入原生 `redis.Redis` 或测试 stub，自动降级原生接口。会话记忆 list 键每次 add 刷新 TTL（默认 86400 秒），防止 Redis 无限增长。

### 12.3 AI 注解

#### @AiClient

**参数**：`provider`（str，默认 ""，openai/ollama/deepseek/moonshot/zhipu，空时读 spring.ai.default-provider）、`model`（str，默认 ""）、`temperature`（float，默认 None）

```python
from spring.ai import AiClient

@AiClient(provider="openai", model="gpt-4o", temperature=0.3)
class ChatService:
    pass
```

#### @Tool

**参数**：`name`（str，默认 ""，空时用函数名）、`description`（str，默认 ""，空时取 docstring）、`return_description`（str，默认 ""）

```python
from spring.ai import Tool

@Tool(description="查询订单状态")
def get_order_status(order_id: str, detail: bool = False) -> str:
    """根据订单号返回订单状态"""
    return f"订单{order_id}已发货"
```

#### @AiAdvisor / @AiMemory

```python
from spring.ai import AiAdvisor, AiMemory

@AiAdvisor(name="ragAdvisor", order=5)
class RagAdvisor: ...

@AiMemory(store="redis", max_messages=50)
class ChatService: ...
```

### 12.4 ChatClient 链式 API

```python
from spring.ai import ChatClientBuilder, FakeChatModel

model = FakeChatModel(prefix="AI:")
client = (ChatClientBuilder(model)
          .default_system("你是助手")
          .build())

# 链式调用
answer = client.prompt().user("你好").call().content()
# 便捷终端方法
answer = client.prompt().user("你好").content()
```

### 12.5 Advisor —— RAG 与会话记忆

Advisor 在模型调用前后介入，按 `order` 升序应用请求阶段、降序应用响应阶段。

```python
from spring.ai import (
    ChatClientBuilder, FakeChatModel, FakeEmbeddingModel,
    InMemoryChatMemory, MessageChatMemoryAdvisor,
    QuestionAnswerAdvisor, SimpleInMemoryVectorStore,
)

emb = FakeEmbeddingModel(dim=16)
store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts(["SpringBootAI 支持 IoC 容器", "SpringBootAI 内嵌 Sentinel 限流"])

memory = InMemoryChatMemory()
client = (ChatClientBuilder(FakeChatModel(prefix="回答:"))
          .default_advisors(
              MessageChatMemoryAdvisor(memory),   # 多轮记忆
              QuestionAnswerAdvisor(              # RAG 检索增强
                  vector_store=store, embedding_model=emb, top_k=2),
          )
          .build())

# 多轮对话（通过 conversation_id 关联历史）
client.prompt().user("我叫张三").param("conversation_id", "u1").call()
client.prompt().user("我叫什么").param("conversation_id", "u1").call()
```

### 12.6 文档 ETL（知识库入库）

> **能用 LangChain 就用 LangChain（不做重复造轮子）**：`TokenTextSplitter`/`CharacterTextSplitter` 的切片逻辑优先委托 `langchain-text-splitters` 的 `RecursiveCharacterTextSplitter`/`CharacterTextSplitter`（自动按 `\n\n`/`\n`/空格/标点逐级切分，语义更佳），并补齐框架的 `chunk_index` 元数据；未安装该包时自动降级内置实现。安装：`pip install langchain-text-splitters==0.3.8`。向量检索可用 `LangChainVectorStore` 包装 langchain 生态的 FAISS/Chroma 等成熟向量库。

```python
from spring.ai import TextReader, TokenTextSplitter, SimpleInMemoryVectorStore

# 1. 读取
doc = TextReader().read_text("长文档内容...", source="manual")
# 2. 切片（安装 langchain-text-splitters 后优先走 LangChain 实现）
chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
# 3. 入库
store = SimpleInMemoryVectorStore()
for c in chunks:
    store.add_texts([c.content])
```

**向量存储（LangChain 适配器）**：

```python
from langchain_community.vectorstores import FAISS
from spring.ai import LangChainVectorStore

lc_store = FAISS.from_texts(["文档A", "文档B"], embedding=your_langchain_embedding)
store = LangChainVectorStore(langchain_store=lc_store)   # 包装为框架 VectorStore
```

### 12.7 工具/函数调用

```python
from spring.ai import ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="加法")
def add(a: int, b: int) -> int:
    return a + b

registry.register("add", add, description="加法")

# 查看自动生成的 schema（供 Provider 注入模型）
print(registry.schemas())
# 模型决定调用时执行
assert registry.execute("add", {"a": 1, "b": 2}) == 3
```

### 12.8 自动装配（AutoConfig）

`configure_ai()` 读取 `spring.ai.*` 配置，构建并注册 ChatModel/EmbeddingModel/ChatMemory/VectorStore/ChatClient Bean 到 BeanRegistry（含熔断器注入）。未配置 api-key 时自动降级为 FakeChatModel/FakeEmbeddingModel。

```python
from spring.ai import configure_ai
from spring.context.registry import BeanRegistry

registry = BeanRegistry()
beans = configure_ai(registry=registry)   # 读取 application.yml
client = beans["aiChatClient"]
answer = client.prompt().user("你好").call().content()
```

自动装配产出的 Bean：

| Bean 名 | 类型 | 说明 |
|---------|------|------|
| aiChatModel | ChatModel | 聊天模型（含熔断器） |
| aiEmbeddingModel | EmbeddingModel | 嵌入模型（RAG 自动嵌入） |
| aiVectorStore | VectorStore | 向量存储（inmemory/redis） |
| aiChatMemory | ChatMemory | 会话记忆（inmemory/redis） |
| aiChatClient | ChatClient | 聊天客户端（注入默认 Memory Advisor） |

### 12.9 模块组成

| 文件 | 职责 |
|------|------|
| spring/ai/core.py | ChatClient/ChatModel/EmbeddingModel/Advisor/Message 抽象（含 tool_call 执行闭环） |
| spring/ai/annotations.py | @AiClient/@Tool/@AiAdvisor/@AiMemory 注解 |
| spring/ai/providers.py | OpenAI兼容/Ollama/DeepSeek/Moonshot/ZhipuAI Provider（LangChain优先，HTTP降级）+ Fake测试模型 + 真流式SSE/async |
| spring/ai/advisors.py | QuestionAnswerAdvisor(RAG)/MessageChatMemoryAdvisor/SimpleLoggerAdvisor |
| spring/ai/memory.py | ChatMemory (InMemory/Redis) |
| spring/ai/vectorstore.py | VectorStore 抽象 + SimpleInMemoryVectorStore + RedisVectorStore（持久化）+ LangChainVectorStore（适配器） |
| spring/ai/etl.py | TextReader/TokenTextSplitter/CharacterTextSplitter（切片优先委托 langchain-text-splitters，未装则降级内置） |
| spring/ai/tools.py | ToolRegistry 函数调用注册表（签名自动生成 schema） |
| spring/ai/resilience.py | AICircuitBreaker 熔断状态机 + resilient_call 重试（复用 spring.retry） |
| spring/ai/observability.py | AIMetrics 单例（复用 PrometheusMetrics，记录调用/token/延迟/熔断） |
| spring/ai/autoconfig.py | AIProperties 类型化绑定 + spring.ai.* 配置装配 Bean |

### 12.10 企业级能力

#### 12.10.1 闭环 Function Calling

Provider 把工具 schema 注入请求体，模型返回 tool_calls 时由 `ChatModel.call()` 基类统一执行→回填 tool 消息→续写，最多 5 轮防死循环。业务侧只需注册工具并传入 `default_tools`，无需手写循环。

```python
from spring.ai import ChatClientBuilder, FakeChatModel, ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="查询天气")
def get_weather(city: str = "北京") -> str:
    return f"{city} 晴"

registry.register("get_weather", get_weather)

client = (ChatClientBuilder(FakeChatModel(prefix="AI:", simulate_tool_call=True))
          .default_tools(registry).build())
# 模型自动调用 get_weather → 回填结果 → 续写最终回复
print(client.prompt().user("调用工具查天气").call().content())
```

#### 12.10.2 韧性：重试 + 熔断

`resilient_call()` 复用框架 `spring.retry.retry_decorator.retry` 对 `TransientError`（429/5xx/超时/连接错误）自动重试；`AICircuitBreaker` 复用 `spring.aop.comprehensive_aop` 的 CLOSED/OPEN/HALF_OPEN 状态机，失败达阈值熔断、`recovery-timeout` 后半开放行探测，保护下游 LLM API。Redis 可用时跨实例共享熔断状态，不可用时降级本地内存。Provider 的 HTTP 调用默认经 `resilient_call` 包装，配置即可调（见 12.2 配置中 `max-retries`、`circuit-breaker` 段）。

**生产安全开关**：`AI_ALLOW_FAKE` 环境变量控制 api_key 缺失时的行为。
- `true`（默认）：api_key 缺失时静默降级 `FakeChatModel`，适合开发/测试
- `false`：api_key 缺失时抛 `ValueError`，防止生产环境配错返回假数据

```bash
# 生产环境务必设置：
export AI_ALLOW_FAKE=false
export OPENAI_API_KEY=sk-xxx
```

#### 12.10.3 真流式 SSE + async

`stream()` 解析 SSE `data:` 增量行逐块 yield（OpenAI）/ NDJSON（Ollama）；`astream()` 用 asyncio.Queue 桥接为异步生成器；`acall()` 用 `asyncio.to_thread` 异步调用。

```python
# 同步流式
for chunk in model.stream([Message.user("讲个故事")]):
    print(chunk.content(), end="", flush=True)

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
```

#### 12.10.4 Prometheus 观测

`AIMetrics` 单例复用框架 `PrometheusMetrics`，自动注册五项指标，Provider 调用前后自动记录，对接企业 Prometheus+Grafana：

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| ai_calls_total | Counter | provider,model,status | 模型调用次数（success/failure） |
| ai_tokens_total | Counter | provider,type | token 用量（prompt/completion） |
| ai_call_duration_seconds | Histogram | provider,model | 调用延迟分布 |
| ai_tool_calls_total | Counter | tool,status | 工具调用次数 |
| ai_circuit_breaker_state | Gauge | provider | 熔断器状态(0=CLOSED,1=OPEN,2=HALF_OPEN) |

#### 12.10.5 RedisVectorStore（RAG 持久化）

`RedisVectorStore` 用 Redis hash 持久化文档（键 `springpy:ai:vectorstore:{collection}`），支持多副本跨实例检索；注入 EmbeddingModel 实现检索时自动嵌入。`max_scan` 参数限制单次检索扫描上限（默认 10000），防止大规模文档 OOM。配置 `vector-store.type: redis` 即用（自动复用框架全局 redis_client 单例），无 client 时安全降级为内存。

```python
from spring.ai import RedisVectorStore, FakeEmbeddingModel, SearchRequest

store = RedisVectorStore(redis_client=redis_client,
                         collection="docs",
                         embedding_model=FakeEmbeddingModel(dim=16))
store.add_texts(["SpringBootAI 文档一", "SpringBootAI 文档二"])
# 检索时自动 embed query
results = store.similarity_search(SearchRequest(query="SpringBootAI", top_k=2))
```

`configure_ai()` 会按 `spring.ai.vector-store.type` 自动装配 `aiVectorStore`（redis 或 inmemory）并注入 `aiEmbeddingModel`，让 RAG 真正自动可用。

### 12.11 DeepSeek 全特性演示用例（已实测通过）

本节用 **DeepSeek**（OpenAI 兼容接口，走 `OpenAICompatChatModel`）跑通 AI 模块全部能力：聊天 / 流式 / 多轮记忆 / RAG / 工具调用 / ETL / 韧性 / 自动装配 / 观测。以下代码均经真实 DeepSeek API 调用验证通过。

**统一配置**（application.yml，或等价的 `AI_PROVIDER` / `DEEPSEEK_API_KEY` 环境变量）：

```yaml
spring:
  ai:
    default-provider: deepseek
    max-retries: 3
    retry-delay-ms: 500
    deepseek:
      api-key: ${DEEPSEEK_API_KEY}
      base-url: https://api.deepseek.com
      model: deepseek-chat
      temperature: 0.7
    vector-store:
      type: inmemory        # deepseek 无 Embedding API，RAG 检索用确定性向量演示
      collection: deepseek-demo
    memory:
      store: inmemory
      max-messages: 20
```

#### 12.11.1 自动装配 + 基础聊天

```python
from spring.ai import configure_ai

beans = configure_ai()                      # 读取 application.yml 自动装配（AI_PROVIDER=deepseek）
client = beans["aiChatClient"]              # 已注入 DeepSeek + Memory Advisor
print(client.prompt().user("用一句话介绍 SpringBootAI").call().content())
```

等价手动构建：

```python
from spring.ai import OpenAICompatChatModel, ChatClientBuilder

model = OpenAICompatChatModel(
    provider="deepseek",
    api_key="YOUR_DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
    temperature=0.7,
)
client = ChatClientBuilder(model).default_system("你是一名资深 Python 架构师").build()
print(client.prompt().user("什么是依赖注入?").call().content())
```

#### 12.11.2 真流式 SSE + async

> `astream()` 是异步生成器，**不要**对其 `await`。

```python
from spring.ai import OpenAICompatChatModel, Message

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")

# 同步逐块输出
for chunk in model.stream([Message.user("写一首关于春天的五言诗")]):
    print(chunk.content(), end="", flush=True)
print()

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
```

#### 12.11.3 多轮会话记忆

```python
from spring.ai import InMemoryChatMemory, MessageChatMemoryAdvisor, OpenAICompatChatModel, ChatClientBuilder

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")
memory = InMemoryChatMemory()
client = (ChatClientBuilder(model)
          .default_advisors(MessageChatMemoryAdvisor(memory))
          .build())

client.prompt().user("我叫李明，记住我").param("conversation_id", "u-1001").call()
print(client.prompt().user("我叫什么？").param("conversation_id", "u-1001").call().content())
# DeepSeek 会根据多轮上下文回答"李明"
```

#### 12.11.4 RAG 知识库问答（ETL 入库 + 检索增强）

> DeepSeek 目前**不提供 Embedding API**，RAG 检索嵌入使用确定性 `FakeEmbeddingModel`（仅作演示），生产可换 OpenAI/本地 embedding 向量库。

```python
from spring.ai import (
    OpenAICompatChatModel, FakeEmbeddingModel, SimpleInMemoryVectorStore,
    QuestionAnswerAdvisor, ChatClientBuilder, TextReader, TokenTextSplitter,
)

chat_model = OpenAICompatChatModel(provider="deepseek",
                                   api_key="YOUR_DEEPSEEK_API_KEY",
                                   base_url="https://api.deepseek.com",
                                   model="deepseek-chat")
emb = FakeEmbeddingModel(dim=16)

# 1. 知识库入库（读 -> 切 -> 存）
raw = "SpringBootAI 内嵌 Sentinel 限流与 OpenTelemetry 追踪；支持 Mapper 注解与 XML 混合。"
doc = TextReader().read_text(raw, source="manual")
chunks = TokenTextSplitter(chunk_size=200, chunk_overlap=50).split([doc])

store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts([c.content for c in chunks])

# 2. RAG 问答
client = (ChatClientBuilder(chat_model)
          .default_advisors(QuestionAnswerAdvisor(vector_store=store,
                                                  embedding_model=emb, top_k=2))
          .build())
print(client.prompt().user("SpringBootAI 是否支持 XML 与注解混合?").call().content())
```

#### 12.11.5 Function Calling 工具调用

```python
from spring.ai import OpenAICompatChatModel, ToolRegistry, Tool, ChatClientBuilder

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")

registry = ToolRegistry()

@Tool(description="查询城市天气")
def get_weather(city: str = "北京") -> str:
    return f"{city}：晴，25℃"

@Tool(description="计算两数之和")
def add(a: int, b: int) -> int:
    return a + b

registry.register("get_weather", get_weather)
registry.register("add", add)

client = ChatClientBuilder(model).default_tools(registry).build()
print(client.prompt().user("帮我查询上海的天气，并计算 3+5").call().content())
# DeepSeek 自动解析工具调用 -> 框架执行 -> 回填 -> 续写最终回复（最多 5 轮闭环）
```

#### 12.11.6 文档 ETL（切片入库，LangChain 优先）

```python
from spring.ai import TextReader, TokenTextSplitter, CharacterTextSplitter

# langchain-text-splitters 已安装时，内部自动委托 RecursiveCharacterTextSplitter
reader = TextReader()
doc = reader.read_text(open("README.md", encoding="utf-8").read(), source="README.md")

tok_chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
char_chunks = CharacterTextSplitter(chunk_size=500, chunk_overlap=100).split([doc])
print(f"token 切片: {len(tok_chunks)} 段, char 切片: {len(char_chunks)} 段")
```

#### 12.11.7 韧性：重试 + 熔断（真实 Provider）

```python
from spring.ai import OpenAICompatChatModel, AICircuitBreaker, Message

cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=30)
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat",
                              circuit_breaker=cb, max_retries=3, retry_delay_ms=500)
# 网络抖动时自动重试；连续失败达阈值熔断保护下游
print(model.call([Message.user("你好")]).content())
```

#### 12.11.8 Spring 注解版（@AiClient + @Tool）

```python
from spring.ai import AiClient, Tool

@AiClient(provider="deepseek", model="deepseek-chat", temperature=0.3)
class DeepSeekAssistant:
    """由容器装配的 DeepSeek 助手"""

    @Tool(description="查询订单状态")
    def order_status(self, order_id: str) -> str:
        return f"订单 {order_id} 已发货"

print(DeepSeekAssistant().order_status("A-123"))   # -> 订单 A-123 已发货
```

#### 12.11.9 Prometheus 观测

```python
from spring.ai import ai_metrics, OpenAICompatChatModel, Message

# 直接打点（record_call 为位置参数 duration，单位秒）
ai_metrics.record_call("deepseek", "deepseek-chat", "success",
                       0.5, {"prompt_tokens": 120, "completion_tokens": 80})

# 推荐：自动计时并打点成功/失败的上下文管理器
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")
with ai_metrics.observe("deepseek", "deepseek-chat") as m:
    resp = model.call([Message.user("你好")])        # 成功/失败自动记录
print(resp.content())
```

> **安全提醒**：以上示例使用 `${DEEPSEEK_API_KEY}` / `YOUR_DEEPSEEK_API_KEY` 占位符，**切勿把真实 key 写进代码或文档**。运行前请通过环境变量注入，避免泄露：
>
> ```bash
> export DEEPSEEK_API_KEY=sk-你的真实key
> ```
>
> 若真实 key 曾提交到公开仓库，请立即到 DeepSeek 控制台吊销并轮换。

---
