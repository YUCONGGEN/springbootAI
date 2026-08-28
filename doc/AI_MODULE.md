# SpringBootAI AI 模块使用指南 —— 小白也能看懂

> 让你的 Python 程序能和 ChatGPT、DeepSeek 等大模型聊天、回答问题、调用你的函数、读你的文档来回答。
> 安装：`pip install springbootAI[ai]` ｜ 框架版本：SpringBootAI 2.3.10

---

## 概念地图（先看这张图，再看下文）

```
                      ┌──────────────────────────────────────┐
                      │         你的 Python 程序              │
                      └──────────────┬───────────────────────┘
                                     │
                                     ▼
  用户问题  ──→  ChatClient  ──→  [ Advisors 安检通道 ]  ──→  ChatModel 大脑  ──→  回答
                  （说话的嘴）        │                           （真正干活的那个）
                                      │
                    ┌─────┬─────┬────┴────┬─────────┐
                    │     │     │         │         │
                    ▼     ▼     ▼         ▼         ▼
                Memory  RAG   Logger    Tools    其他...
               （记性）（翻书）（记日志）（手脚）
                         │
                         ▼
                   VectorStore ← EmbeddingModel ← ETL（读→切→存）
                   （资料柜）     （贴标签）        （整理入库）
```

- **ChatClient（说话的嘴）**：你把问题说出去的口子，也是接收回答的耳朵。就像和 ChatGPT 聊天一样，你打字、它回复。
- **Advisor（安检通道）**：每条问题在到达模型大脑之前，会经过一排"安检门"。每道门检查/做一件事：记忆门帮你翻聊天记录、RAG 门帮你查资料、日志门记录干了什么。
- **RAG（检索增强生成）**：就像是考试时让你可以翻书答题——先查到相关资料，再回答，答案更准确。
- **Tool Calling（工具调用）**：给 AI 装上手和脚，让它不仅能"说话"，还能"动手干活"——调用你写的 Python 函数查数据、算价格、发通知。

---

## 什么是 AI 模块？简单说...

**这个模块让你的 Python 程序能"调用大模型聊天"**——你写一个 Python 脚本，它能跟 ChatGPT、DeepSeek 等大模型对话、回答问题、调用你的函数、读你的文档来回答。

你不需要自己训练模型，只需要**申请一个模型的 API Key，然后在配置里填进去**，就能用了。

### 奶茶店比喻：一张表看懂所有概念

想象你开了一家奶茶店，你需要一个智能助手来帮你处理各种事：

| 概念 | 生活场景比喻 | 大白话 |
|------|-------------|--------|
| **ChatModel（模型）** | 雇的一个「会说话的员工大脑」 | 真正"会说话"的那个大脑 |
| **ChatClient（聊天客户端）** | 你跟这个员工对话的「嘴」 | 你和大模型对话的方式 |
| **Memory（记忆）** | 这个员工的「记性」 | 让模型记住前面的对话 |
| **RAG（知识库问答）** | 《奶茶配方手册》复印、裁剪、贴标签归档，问的时候先翻柜子再回答 | 翻书答题（开卷考试） |
| **Advisor（顾问/插件）** | 挂在回答问题前/后的「小助手」 | 安检通道，每道门检查一件事 |
| **EmbeddingModel（嵌入模型）** | 给每页配方贴「编号标签」，方便快速查找 | 把文字变成数字向量 |
| **VectorStore（向量库）** | 存编号标签和配方的档案柜 | 资料索引柜，快速查找 |
| **Tools / Function Calling** | 员工不仅能说话，还能动手——调用查账函数、查天气 | 给 AI 装上手和脚 |
| **ETL（文档处理流程）** | 把配方手册塞进档案柜：读→切→贴标签→入柜 | 文档整理入库流程 |
| **FakeChatModel（假模型）** | 不花钱、不联网的练习机器人 | 开发测试用的假模型 |

### 新手推荐路径

> **不要从头读到尾！按你的需求跳着看：**

| 你想做什么 | 看这一节 | 预计时间 |
|-----------|---------|---------|
| 只是想试试 AI 模块是什么感觉 | [新手入门](#新手入门从零跑通第一个-ai-程序) | 5 分钟 |
| 对接真实模型（DeepSeek / OpenAI） | [快速开始](#快速开始) + [配置](#配置applicationyml) | 10 分钟 |
| 让模型记住多轮对话 | [Advisor 中的 Memory 部分](#advisor--安检通道rag-与会话记忆) | 5 分钟 |
| 让模型读你的文档再回答 | [ETL](#文档-etl知识库入库) + [Advisor 中的 RAG 部分](#advisor--安检通道rag-与会话记忆) | 15 分钟 |
| 让模型调用你写的 Python 函数 | [工具调用](#工具函数调用给-ai-装上手和脚) | 10 分钟 |
| 线上部署（熔断/重试/监控） | [线上部署能力](#线上部署能力) | 15 分钟 |

---

## 阅读前准备

第一次使用先完成 [新手入门指南](BEGINNER_GUIDE.md) 的普通 HTTP 接口，再学习本模块。调用云端模型通常会产生费用并把请求内容发送给第三方 Provider；不要把密钥、个人信息、未脱敏客户数据直接放入提示词。建议先用测试密钥、限额账号或本地 Ollama 跑通最小示例。

学习顺序建议：基础聊天 → 流式输出 → 会话记忆 → Tools → RAG → Redis 持久化与监控。每一步都先验证错误处理和超时，再进入下一步。

**核心能力**：
- **多 Provider 适配**：OpenAI / Ollama / DeepSeek / Moonshot / Zhipu（LangChain 优先，HTTP 降级）
- **ChatClient 链式 API**：`client.prompt().user("...").call().content()`，对齐 Spring AI
- **Function Calling 闭环**：tools 自动注入请求体 + tool_call 循环执行回填续写（最多 5 轮）
- **RAG**：QuestionAnswerAdvisor + VectorStore（InMemory / Redis 持久化）
- **会话记忆**：MessageChatMemoryAdvisor（InMemory / Redis，多轮对话）
- **文档 ETL**：TextReader / TokenTextSplitter / CharacterTextSplitter
- **线上部署能力**：熔断重试、真流式 SSE+async、Prometheus 观测、Redis 向量存储
- **类型化配置绑定**：`AIProperties` dataclass + env 覆盖安全网

---

## 新手入门：从零跑通第一个 AI 程序

### ① 它能帮你做什么

**让你在 5 分钟内跑通人生第一个 AI 程序——即使没有 API Key、不懂任何 AI 概念。**

### ② 它到底干了什么

简单说：**让你的 Python 程序能调用大语言模型（LLM）**——也就是让程序会「说话、理解、写代码、回答问题、查资料、调用工具」。

现实里它常被用来做这些事：
- **智能客服/聊天机器人**：程序能记住对话、像真人一样回答（记忆 + 聊天）
- **知识库问答**：把你自己的一堆文档喂进去，程序能"读你的资料再回答"（这就是 RAG，开卷考试）
- **写代码助手**：让模型根据你的要求生成或改写代码
- **流程自动化**：让模型决定调用哪个函数（比如查天气、算价格），这就是 Function Calling

### ③ 新手三步走

**第 1 步：安装依赖**

```bash
pip install -r requirements-ai.txt
```

**第 2 步：先在本地用"假模型"跑通（不花钱、不联网）**

> 假模型不需要 API Key，非常适合先理解代码怎么写、流程怎么走。就像学车先在模拟器上练，不上真路。

```python
from springbootai.ai import ChatClientBuilder, FakeChatModel

# 创建一个假的聊天客户端（你说啥，它学你说话）
client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

**第 3 步：接上真实模型（需要申请 Key）**

1. 去模型厂商官网申请 API Key（比如 DeepSeek、OpenAI、Moonshot）
2. 设置环境变量（把 `sk-你的真实key` 换成你自己的），**不要把真实 Key 写进代码或文档**：

```bash
# Windows PowerShell
$env:AI_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "sk-你的真实key"
# Linux / macOS
export AI_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-你的真实key
```

3. 用自动装配的方式运行：

```python
from springbootai.ai import configure_ai

beans = configure_ai()          # 读环境变量/application.yml，自动创建好所有 AI 组件
client = beans["aiChatClient"]  # 拿到的就是"会聊天的助手"
print(client.prompt().user("你好").call().content())
# 输出: （DeepSeek 的真实回复，比如"你好！有什么可以帮助你的吗？"）
```

到这里，你就已经成功让程序和大模型对话了。

### ④ 进阶：最常用的 3 个能力（新手按需选学）

- **想让它记住多轮对话** → 看 [Advisor](#advisor--安检通道rag-与会话记忆)（加一个 MemoryAdvisor 即可）
- **想让它"读了你的资料再回答"** → 看 [ETL](#文档-etl知识库入库)：先把文档切碎入库，再提问
- **想让它调用你的函数** → 看 [工具调用](#工具函数调用给-ai-装上手和脚)：用 `@Tool` 装饰你的函数

### ⑤ 新手常见错误

- ❌ 以为必须自己训练模型 → ✅ 只需申请 API Key
- ❌ 把真实 Key 写进代码/文档提交到公开仓库 → ✅ 用环境变量注入
- ❌ 问完就忘、无法多轮 → ✅ 需要加 Memory（记忆）
- ❌ 问"我自己的资料"模型说不知道 → ✅ 要用 RAG，先把资料切碎入库再问
- ❌ 没配 Key 就以为会自动使用假模型 → ✅ 默认直接报错；仅开发/测试显式设 `AI_ALLOW_FAKE=true`
- ❌ 以为 RAG 是「把文档上传给模型」→ ✅ RAG 是「先检索相关片段，再把片段和问题一起发给模型」，文档不会上传到模型服务器
- ❌ 以为 Memory 有无限容量 → ✅ 默认最多存 20 条消息（可配置），超出会丢弃最早的消息

---

## 快速开始

> **就像和 ChatGPT 聊天一样**：你写一句 `client.prompt().user("你好").call().content()`，它就回复你一句话。

```bash
pip install -r requirements-ai.txt
```

### 最小示例（无需真实 API key，用假模型即可运行）

```python
from springbootai.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

### 接入真实 OpenAI 兼容模型

```python
from springbootai.ai import configure_ai

# 读取 application.yml 的 spring.ai.* 配置，自动装配所有 Bean
beans = configure_ai()
client = beans["aiChatClient"]
print(client.prompt().user("你好").call().content())
# 输出: （真实模型的回复，比如"你好！请问有什么可以帮你的？"）
```

只需在 `application.yml` 或环境变量配置 `OPENAI_API_KEY` 即可启用真实模型；未配置时默认直接报错。开发/测试如需假模型，应显式设置 `AI_ALLOW_FAKE=true`。

### 新手常见错误

| ❌ 错误写法 | ✅ 正确写法 | 说明 |
|------------|------------|------|
| 每次对话都重新 `ChatClientBuilder(...).build()` | 一次 build，反复使用 | `build()` 很轻量但没必要重复创建 |
| `.call()` 和 `.content()` 分不清 | `.call()` 返回对象，`.content()` 返回文本 | 想要文本就直接用 `.content()` |
| 不传 API Key | 配好 Key；仅开发测试设 `AI_ALLOW_FAKE=true` | 默认报错，不会静默返回假数据 |

---

## 配置（application.yml）

> **知道如何通过配置文件切换模型厂商、调温度、配向量库——不用改代码，只改配置。**

所有 AI 组件的参数推荐在 `spring.ai.*` 下配置（兼容旧版 `springbootai.ai.*`），支持环境变量 `${ENV:default}` 覆盖，优先级：**环境变量 > application.yml > 程序默认值**。

### 配置是怎么被读取的？

**大白话**：你写 yml 配置 → 框架读出来 → 自动填进一个 Python 对象（dataclass）→ 类型自动转换（字符串 `"0.3"` 变 `float` 0.3，`"true"` 变 `bool` True）。

```yaml
spring:
  ai:
    default-provider: ${AI_PROVIDER:openai}   # openai | ollama | deepseek | moonshot | zhipu
    max-retries: ${AI_MAX_RETRIES:3}
    retry-delay-ms: ${AI_RETRY_DELAY_MS:500}
    request-timeout-seconds: ${AI_REQUEST_TIMEOUT_SECONDS:60}
    max-output-tokens: ${AI_MAX_OUTPUT_TOKENS:4096}
    max-total-tokens: ${AI_MAX_TOTAL_TOKENS:100000}
    max-tool-iterations: ${AI_MAX_TOOL_ITERATIONS:5}
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

### 类型转换验证代码

```python
from springbootai.ai import AIProperties, bind_ai_config

props: AIProperties = bind_ai_config({
    "default-provider": "openai",
    "openai": {"api-key": "sk-x", "chat": {"temperature": "0.3"}},  # 字符串自动转 float
    "circuit-breaker": {"enabled": "false"},                          # 字符串自动转 bool
})
assert props.openai.chat.temperature == 0.3
# 结果: 断言通过，字符串 "0.3" 被自动转成了 float 0.3
assert isinstance(props.openai.chat.temperature, float)
# 结果: 断言通过
assert props.circuit_breaker.enabled is False
# 结果: 断言通过，字符串 "false" 被自动转成了 bool False
```

### 环境变量速查（改配置不碰代码）

| 配置键 | 环境变量 | 默认值 | 改它能做什么 |
|--------|---------|--------|-------------|
| default-provider | AI_PROVIDER | openai | 换模型厂商 |
| max-retries | AI_MAX_RETRIES | 3 | 网络出错重试几次 |
| retry-delay-ms | AI_RETRY_DELAY_MS | 500 | 每次重试间隔（毫秒） |
| request-timeout-seconds | AI_REQUEST_TIMEOUT_SECONDS | 60 | 单次模型请求超时（秒） |
| max-output-tokens | AI_MAX_OUTPUT_TOKENS | 4096 | 单次回复最大 Token |
| max-total-tokens | AI_MAX_TOTAL_TOKENS | 100000 | 一次模型/工具闭环累计 Token 上限 |
| max-tool-iterations | AI_MAX_TOOL_ITERATIONS | 5 | 工具调用闭环轮数上限 |
| openai.api-key | OPENAI_API_KEY | （空；默认报错） | OpenAI 的钥匙 |
| openai.base-url | OPENAI_BASE_URL | https://api.openai.com/v1 | 换代理/中转地址 |
| openai.chat.model | OPENAI_CHAT_MODEL | gpt-4o-mini | 换模型版本 |
| openai.chat.temperature | OPENAI_TEMPERATURE | 0.7 | 控制回复的随机性（0=死板，1=天马行空） |
| openai.embedding.model | OPENAI_EMBEDDING_MODEL | text-embedding-3-small | 换嵌入模型 |
| ollama.base-url | OLLAMA_BASE_URL | http://localhost:11434 | 本地 Ollama 地址 |
| ollama.chat.model | OLLAMA_CHAT_MODEL | llama3 | Ollama 用的模型 |
| vector-store.type | AI_VECTOR_STORE | inmemory | 向量库存在内存还是 Redis |
| vector-store.collection | AI_VECTOR_COLLECTION | default | 向量库分区名 |
| memory.store | AI_MEMORY_STORE | inmemory | 记忆存在内存还是 Redis |
| memory.max-messages | AI_MEMORY_MAX | 20 | 最多记几轮对话 |
| circuit-breaker.enabled | AI_CB_ENABLED | true | 是否开启熔断保护 |
| circuit-breaker.failure-threshold | AI_CB_FAILURE_THRESHOLD | 5 | 连续失败几次后熔断 |
| circuit-breaker.recovery-timeout | AI_CB_RECOVERY_TIMEOUT | 30 | 熔断后多久尝试恢复（秒） |

### Redis 持久化（复用框架 RedisClient）

**大白话**：当你在 yml 里写 `vector-store.type=redis` 或 `memory.store=redis`，框架会自动用已有的 Redis 连接——不需要你再传一遍 Redis 客户端。

当 `vector-store.type=redis` 或 `memory.store=redis` 时，`configure_ai` 自动复用框架全局 `springbootai.utils.redis_client.redis_client` 单例，**无需手动传 redis_client 参数**。`RedisVectorStore` 与 `RedisChatMemory` 统一用框架 `RedisClient` 封装接口（`hash_set`/`hash_get_all`/`list_push`/`list_range`），同一个 client 同时满足两者。若传入原生 `redis.Redis` 或测试 stub，自动降级原生接口。会话记忆 list 键每次 add 刷新 TTL（默认 86400 秒），防止 Redis 无限增长。

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 | 说明 |
|------------|------------|------|
| 改了 yml 不重启 | 配置只在 `configure_ai()` 调用时读取一次，改完要重启程序 | yml 不是实时生效的 |
| 同时配了环境变量和 yml，以为 yml 优先级高 | 环境变量优先级最高，会覆盖 yml | 环境变量 > yml > 默认值 |
| temperature 设为 0 以为模型最聪明 | temperature=0 只是让回复更确定、不变来变去，不等于更准确 | 一般设 0.5~0.8 |
| vector-store.type 写了 `redis` 但没装 Redis | 没装 Redis 时会静默降级到内存模式，不会报错 | 确认 Redis 可连接后再切换 |

---

## AI 注解

> **用装饰器（`@AiClient`、`@Tool`、`@AiAdvisor`）声明式地配置 AI 组件，而不是手动写一堆构造代码。**

`@AiClient` 声明用的哪个模型、`@Tool` 声明函数可被模型调用、`@AiAdvisor` 声明顾问插件、`@AiMemory` 声明记忆配置——这些注解会被 `configure_ai()` 收集并自动创建对应的 Bean。

### @AiClient

**大白话**：在类上贴这个标签，告诉框架"这个类要用哪个厂商的哪个模型，温度调多少"。

**参数**：`provider`（str，默认 ""，openai/ollama/deepseek/moonshot/zhipu，空时读 `spring.ai.default-provider`）、`model`（str，默认 ""）、`temperature`（float，默认 None）

```python
from springbootai.ai import AiClient

@AiClient(provider="openai", model="gpt-4o", temperature=0.3)
class ChatService:
    pass
```

### @Tool

**大白话**：在函数上贴这个标签，让大模型可以调用它——比如贴一个"查天气"标签，模型就能在需要时调用你的天气函数。

**参数**：`name`（str，默认 ""，空时用函数名）、`description`（str，默认 ""，空时取 docstring）、`return_description`（str，默认 ""）

```python
from springbootai.ai import Tool

@Tool(description="查询订单状态")
def get_order_status(order_id: str, detail: bool = False) -> str:
    """根据订单号返回订单状态"""
    return f"订单{order_id}已发货"
# 示例调用: get_order_status("A-123")
# 结果: '订单A-123已发货'
```

### @AiAdvisor / @AiMemory

```python
from springbootai.ai import AiAdvisor, AiMemory

@AiAdvisor(name="ragAdvisor", order=5)
class RagAdvisor: ...

@AiMemory(store="redis", max_messages=50)
class ChatService: ...
```

---

## ChatClient 链式 API —— 就像和 ChatGPT 聊天一样

> **就像和 ChatGPT 聊天一样**：你打字 `client.prompt().user("嗨").call().content()`，它回复你。用链式调用，像拼积木一样把对话步骤串起来。

`client.prompt().user("...").call().content()` 是最高频的调用模式，链式 API 支持设置系统消息、传参数、流式输出等。

```python
from springbootai.ai import ChatClientBuilder, FakeChatModel

model = FakeChatModel(prefix="AI:")
client = (ChatClientBuilder(model)
          .default_system("你是助手")
          .build())

# 链式调用
answer = client.prompt().user("你好").call().content()
# 结果: answer = "AI: 你是助手\nAI: 你好"

# 便捷终端方法（省略 .call()）
answer = client.prompt().user("你好").content()
# 结果: 同上，.content() 内部自动调用了 .call()
```

### 新手常见错误

| ❌ 错误写法 | ✅ 正确写法 | 说明 |
|------------|------------|------|
| `client.prompt().user("你好").call()` 然后不知道怎么取文本 | 用 `.content()` 直接拿到字符串 | `.call()` 返回 `ChatResponse` 对象，`.content()` 返回文本 |
| 每次对话都重新 `build()` | 一次 build，反复用 | `client` 是可以复用的 |
| 以为 `.call()` 是异步的 | `.call()` 是同步调用，会阻塞直到返回 | 想要异步用 `acall()` |

---

## Advisor —— 安检通道：RAG 与会话记忆

> **Advisor 就是安检通道**：每条消息在到达大模型之前，要经过一排"安检门"。每道门检查/做一件事：
> - **记忆门（MessageChatMemoryAdvisor）**：帮你翻之前的聊天记录，让模型知道上下文
> - **资料门（QuestionAnswerAdvisor）**：帮你查资料，把相关内容一起发给模型
> - **日志门（SimpleLoggerAdvisor）**：记录谁问了什么、花了多久

### 生活比喻

想象你是一个忙碌的经理，每次见客户前，你有两个小助手：
- **记忆小助手（MessageChatMemoryAdvisor）**：在门口递给你一个本子，上面记着你和这个客户之前聊过的所有内容，让你能接着上次的话题继续聊。
- **资料小助手（QuestionAnswerAdvisor）**：你去档案室查资料时，他已经提前帮你翻出了和客户问题最相关的几份文件，直接放在你桌上。

Advisor 在模型调用前后介入，按 `order` 升序应用请求阶段、降序应用响应阶段。

```python
from springbootai.ai import (
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
# 输出: "回答: 你叫张三"  ← 因为 Memory Advisor 记住了上一轮的内容

# 不带 conversation_id 的对话不会关联历史
client.prompt().user("我叫什么").call()
# 输出: "回答: 我叫什么"  ← FakeChatModel 只回显当前消息，因为没有历史
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 | 说明 |
|------------|------------|------|
| 以为加了 RAG Advisor 模型就自动知道所有文档内容 | RAG 只检索最相关的 `top_k` 条，不在检索结果里的内容模型不知道 | 检索范围有限，质量取决于切片和向量化 |
| `conversation_id` 写错导致记忆混乱 | 每个用户/会话用唯一的 `conversation_id`，不要共用 | 比如用用户ID+会话ID组合 |
| 以为 Advisor 越多越好 | 每个 Advisor 都会增加延迟，只加你需要的 | 一般 Memory + RAG 就够了 |

---

## 文档 ETL（知识库入库）—— RAG 的"开卷考试"准备

> **RAG 就是开卷考试**：考试时让你翻书答题——先查到相关资料，再回答，答案更准确。ETL 就是考试前把书整理好的过程。

### 三步走：读 → 切 → 存

```python
from springbootai.ai import TextReader, TokenTextSplitter, SimpleInMemoryVectorStore

# 第 1 步：读取文档
doc = TextReader().read_text("长文档内容...", source="manual")
# 结果: doc = Document(content="长文档内容...", metadata={"source": "manual"})

# 第 2 步：切成小块（安装 langchain-text-splitters 后优先走 LangChain 实现）
chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
# 结果: chunks = [Document(chunk_index=0, content="前800字..."), Document(chunk_index=1, content="接下来800字..."), ...]
# chunk_overlap=200 意思是相邻两块有 200 字的重叠，防止一句话被从中间切断

# 第 3 步：存入向量库
store = SimpleInMemoryVectorStore()
for c in chunks:
    store.add_texts([c.content])
# 结果: 所有文本块已入库，可以检索了
```

### 向量存储（LangChain 适配器）

**大白话**：如果你想用 LangChain 生态里更强大的向量库（比如 FAISS），可以用 `LangChainVectorStore` 把它包装成框架能识别的格式。

```python
from langchain_community.vectorstores import FAISS
from springbootai.ai import LangChainVectorStore

lc_store = FAISS.from_texts(["文档A", "文档B"], embedding=your_langchain_embedding)
store = LangChainVectorStore(langchain_store=lc_store)   # 包装为框架 VectorStore
# 结果: store 现在是框架标准 VectorStore，可以直接喂给 QuestionAnswerAdvisor
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 | 说明 |
|------------|------------|------|
| `chunk_size` 设得太大（比如 5000） | 推荐 500~1000 | 太大导致检索精度下降，太小导致语义碎片化 |
| `chunk_overlap` 设为 0 | 设为 chunk_size 的 10%~25% | 防止关键句被切在两块的边界 |
| 把整本小说一股脑塞进去 | 先清理文档（去掉无意义页码、页眉页脚），质 > 量 | 垃圾进，垃圾出 |

---

## 工具/函数调用 —— 给 AI 装上手和脚

> **Tool Calling 就是给 AI 装上手和脚**：原来它只能"说话"，现在它能"动手干活"——调用你写的 Python 函数来查数据、算价格、发通知。

`@Tool` 装饰函数 → 注册到 `ToolRegistry` → 模型自动决定何时调用 → 框架执行并回填结果 → 模型续写最终回复。全程你不需要写任何判断逻辑。

```python
from springbootai.ai import ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="加法")
def add(a: int, b: int) -> int:
    return a + b

registry.register("add", add, description="加法")

# 查看自动生成的 schema（供 Provider 注入模型）
print(registry.schemas())
# 输出: [{"name": "add", "description": "加法", "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}]

# 模型决定调用时执行
assert registry.execute("add", {"a": 1, "b": 2}) == 3
# 结果: 断言通过
```

### 新手常见错误

| ❌ 错误写法 | ✅ 正确写法 | 说明 |
|------------|------------|------|
| `@Tool(description="查询")` 太模糊 | `@Tool(description="根据订单号查询物流状态，返回是否已签收")` | 模型靠描述决定用不用这个工具，描述要具体 |
| 参数类型写了 `Any` | 明确写 `str`/`int`/`float`/`bool` | 模型需要知道参数类型才能正确传参 |
| 函数里写了 `print()` 看结果 | 用 `return` 返回值 | return 的结果会回填给模型，print 不会 |

---

## 自动装配（AutoConfig）

> **一行 `configure_ai()` 就帮你创建好所有 AI 组件（聊天模型、嵌入模型、向量库、记忆、ChatClient），不用手动一个个 new。**

### 一句话总结

`configure_ai()` 读取 `spring.ai.*` 配置（兼容旧版 `springbootai.ai.*`），构建并注册 ChatModel/EmbeddingModel/ChatMemory/VectorStore/ChatClient Bean 到 BeanRegistry（含熔断器注入）。未配置 api-key 时默认失败；只有显式设置 `AI_ALLOW_FAKE=true` 才降级为 FakeChatModel/FakeEmbeddingModel。

```python
from springbootai.ai import configure_ai
from springbootai.context.registry import BeanRegistry

registry = BeanRegistry()
beans = configure_ai(registry=registry)   # 读取 application.yml
client = beans["aiChatClient"]
answer = client.prompt().user("你好").call().content()
# 结果: answer = 模型的回复文本
```

自动装配产出的 Bean：

| Bean 名 | 类型 | 说明 |
|---------|------|------|
| aiChatModel | ChatModel | 聊天模型（含熔断器） |
| aiEmbeddingModel | EmbeddingModel | 嵌入模型（RAG 自动嵌入） |
| aiVectorStore | VectorStore | 向量存储（inmemory/redis） |
| aiChatMemory | ChatMemory | 会话记忆（inmemory/redis） |
| aiChatClient | ChatClient | 聊天客户端（注入默认 Memory Advisor） |

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 | 说明 |
|------------|------------|------|
| `registry` 参数不传，后续取不到 Bean | 不传 `registry` 时会自动创建一个，但推荐显式传入方便后续获取 | 传了更可控 |
| 以为 `configure_ai()` 要多次调用 | 整个应用生命周期只调用一次 | 重复调用会产生多个模型实例 |

---

## 模块组成

> 想改某个功能的代码时，能快速找到它在哪个文件里。

| 文件 | 职责 |
|------|------|
| springbootai/ai/core.py | ChatClient/ChatModel/EmbeddingModel/Advisor/Message 抽象（含 tool_call 执行闭环） |
| springbootai/ai/annotations.py | @AiClient/@Tool/@AiAdvisor/@AiMemory 注解 |
| springbootai/ai/providers.py | OpenAI兼容/Ollama/DeepSeek/Moonshot/ZhipuAI Provider（LangChain优先，HTTP降级）+ Fake测试模型 + 真流式SSE/async |
| springbootai/ai/advisors.py | QuestionAnswerAdvisor(RAG)/MessageChatMemoryAdvisor/SimpleLoggerAdvisor |
| springbootai/ai/memory.py | ChatMemory (InMemory/Redis) |
| springbootai/ai/vectorstore.py | VectorStore 抽象 + SimpleInMemoryVectorStore + RedisVectorStore（持久化）+ LangChainVectorStore（适配器） |
| springbootai/ai/etl.py | TextReader/TokenTextSplitter/CharacterTextSplitter（切片优先委托 langchain-text-splitters，未装则降级内置） |
| springbootai/ai/tools.py | ToolRegistry 函数调用注册表（签名自动生成 schema） |
| springbootai/ai/resilience.py | AICircuitBreaker 熔断状态机 + resilient_call 重试（复用 springbootai.retry） |
| springbootai/ai/observability.py | AIMetrics 单例（复用 PrometheusMetrics，记录调用/token/延迟/熔断） |
| springbootai/ai/autoconfig.py | AIProperties 类型化绑定 + spring.ai.* 配置装配 Bean |

---

## 线上部署能力

### 闭环 Function Calling

**大白话**：模型说"我想调用查天气函数"→ 框架帮你执行 → 把结果告诉模型 → 模型继续回答。这个循环是自动的，你只需要注册好工具，不需要写任何循环代码。

Provider 把工具 schema 注入请求体，模型返回 tool_calls 时由 `ChatModel.call()` 基类统一执行→回填 tool 消息→续写，最多 5 轮防死循环。业务侧只需注册工具并传入 `default_tools`，无需手写循环。

```python
from springbootai.ai import ChatClientBuilder, FakeChatModel, ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="查询天气")
def get_weather(city: str = "北京") -> str:
    return f"{city} 晴"

registry.register("get_weather", get_weather)

client = (ChatClientBuilder(FakeChatModel(prefix="AI:", simulate_tool_call=True))
          .default_tools(registry).build())
# 模型自动调用 get_weather → 回填结果 → 续写最终回复
print(client.prompt().user("调用工具查天气").call().content())
# 输出: "AI: 已调用 get_weather(city='北京') → 北京 晴"（FakeChatModel 模拟了整个闭环）
```

### 韧性：重试 + 熔断

> **线上环境大模型 API 偶尔会网络超时或返回 429（请求太多），你需要自动重试和熔断保护，防止你的服务被拖垮。**

**大白话**：想象你给外卖平台打电话订餐：
- **重试**：第一次占线，自动等 500ms 再打，最多打 3 次
- **熔断**：连续 5 次都打不通，就暂时不打了一一过 30 秒再试试看

`resilient_call()` 复用框架 `springbootai.retry.retry_decorator.retry` 对 `TransientError`（429/5xx/超时/连接错误）自动重试；`AICircuitBreaker` 复用 `springbootai.aop.comprehensive_aop` 的 CLOSED/OPEN/HALF_OPEN 状态机，失败达阈值熔断、`recovery-timeout` 后半开放行探测，保护下游 LLM API。Redis 可用时跨实例共享熔断状态，不可用时降级本地内存。HTTP、LangChain Chat 和 LangChain Embedding 路径统一应用该策略。流式响应只允许在尚未输出内容时重试；一旦输出过部分内容，中断会抛 `ProviderStreamError`，避免重复文本。

**线上安全开关**：`AI_ALLOW_FAKE` 环境变量控制 api_key 缺失时的行为。
- `true`：api_key 缺失时降级 `FakeChatModel`，仅适合开发/测试
- `false`（默认）：api_key 缺失时抛 `ValueError`，防止线上环境配错返回假数据

```bash
# 线上环境务必设置：
export AI_ALLOW_FAKE=false
export OPENAI_API_KEY=sk-xxx
```

### 真流式 SSE + async

> **让模型像 ChatGPT 一样逐字输出，而不是等几秒后一次性弹出一大段——用户体验更好。**

`stream()` 逐块产出文本（同步），`astream()` 异步逐块产出——都基于 SSE/NDJSON 协议解析。

```python
# 同步流式
for chunk in model.stream([Message.user("讲个故事")]):
    print(chunk.content(), end="", flush=True)
# 输出: （逐字/逐句输出故事内容，像打字机一样）
print()  # 最后换行

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
# 输出: （逐字输出的问候语）
```

### Prometheus 观测

> **你接了大模型 API，老板问你「花了多少钱」「调用了多少次」「平均延迟多少」——这些指标自动记录，接上 Grafana 就能可视化。**

`AIMetrics` 单例复用框架 `PrometheusMetrics`，自动注册五项指标，Provider 调用前后自动记录，对接 Prometheus+Grafana：

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| ai_calls_total | Counter | provider,model,status | 模型调用次数（success/failure） |
| ai_tokens_total | Counter | provider,type | token 用量（prompt/completion） |
| ai_call_duration_seconds | Histogram | provider,model | 调用延迟分布 |
| ai_tool_calls_total | Counter | tool,status | 工具调用次数 |
| ai_circuit_breaker_state | Gauge | provider | 熔断器状态(0=CLOSED,1=OPEN,2=HALF_OPEN) |

### RedisVectorStore（RAG 持久化）

> **重启服务后 RAG 知识库不丢失——存在 Redis 里，多个服务器共享同一份数据。**

`RedisVectorStore` 用 Redis hash 持久化文档（键 `springpy:ai:vectorstore:{collection}`），支持多副本跨实例检索；注入 EmbeddingModel 实现检索时自动嵌入。`max_scan` 参数限制单次检索扫描上限（默认 10000），防止大规模文档 OOM。配置 `vector-store.type: redis` 即用（自动复用框架全局 redis_client 单例），无 client 时安全降级为内存。

```python
from springbootai.ai import RedisVectorStore, FakeEmbeddingModel, SearchRequest

store = RedisVectorStore(redis_client=redis_client,
                         collection="docs",
                         embedding_model=FakeEmbeddingModel(dim=16))
store.add_texts(["SpringBootAI 文档一", "SpringBootAI 文档二"])
# 结果: 两段文本被嵌入后存入 Redis

# 检索时自动 embed query
results = store.similarity_search(SearchRequest(query="SpringBootAI", top_k=2))
# 结果: results = [最相关的两条文档]
```

`configure_ai()` 会按 `spring.ai.vector-store.type` 自动装配 `aiVectorStore`（redis 或 inmemory）并注入 `aiEmbeddingModel`，让 RAG 真正自动可用。

---

## DeepSeek 全特性演示用例（已实测通过）

> **用 DeepSeek 作为具体例子，跑通 AI 模块全部能力（聊天/流式/记忆/RAG/工具/ETL/韧性/注解/观测），所有代码都经过真实 API 验证。**

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

### 自动装配 + 基础聊天

```python
from springbootai.ai import configure_ai

beans = configure_ai()                      # 读取 application.yml 自动装配（AI_PROVIDER=deepseek）
client = beans["aiChatClient"]              # 已注入 DeepSeek + Memory Advisor
print(client.prompt().user("用一句话介绍 SpringBootAI").call().content())
# 输出: （DeepSeek 的真实回复，如"SpringBootAI 是一个..."）
```

等价手动构建：

```python
from springbootai.ai import OpenAICompatChatModel, ChatClientBuilder

model = OpenAICompatChatModel(
    provider="deepseek",
    api_key="YOUR_DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
    temperature=0.7,
)
client = ChatClientBuilder(model).default_system("你是一名资深 Python 架构师").build()
print(client.prompt().user("什么是依赖注入?").call().content())
# 输出: （DeepSeek 用架构师风格回答依赖注入）
```

### 真流式 SSE + async

> `astream()` 是异步生成器，**不要**对其 `await`。

```python
from springbootai.ai import OpenAICompatChatModel, Message

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")

# 同步逐块输出
for chunk in model.stream([Message.user("写一首关于春天的五言诗")]):
    print(chunk.content(), end="", flush=True)
print()
# 输出: （逐字输出的五言诗）

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
# 输出: （异步逐字输出的问候语）
```

### 多轮会话记忆

```python
from springbootai.ai import InMemoryChatMemory, MessageChatMemoryAdvisor, OpenAICompatChatModel, ChatClientBuilder

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
# 输出: （DeepSeek 根据多轮上下文回答"你叫李明"）
```

### RAG 知识库问答（ETL 入库 + 检索增强）

> DeepSeek 目前**不提供 Embedding API**，RAG 检索嵌入使用确定性 `FakeEmbeddingModel`（仅作演示），线上可换 OpenAI/本地 embedding 向量库。

```python
from springbootai.ai import (
    OpenAICompatChatModel, FakeEmbeddingModel, SimpleInMemoryVectorStore,
    QuestionAnswerAdvisor, ChatClientBuilder, TextReader, TokenTextSplitter,
)

chat_model = OpenAICompatChatModel(provider="deepseek",
                                   api_key="YOUR_DEEPSEEK_API_KEY",
                                   base_url="https://api.deepseek.com",
                                   model="deepseek-chat")
emb = FakeEmbeddingModel(dim=16)

# 第 1 步：知识库入库（读 -> 切 -> 存）
raw = "SpringBootAI 内嵌 Sentinel 限流与 OpenTelemetry 追踪；支持 Mapper 注解与 XML 混合。"
doc = TextReader().read_text(raw, source="manual")
chunks = TokenTextSplitter(chunk_size=200, chunk_overlap=50).split([doc])
# 结果: chunks = [包含 chunk_index 元数据的 Document 列表]

store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts([c.content for c in chunks])
# 结果: 文本内容已向量化并存入内存向量库

# 第 2 步：RAG 问答
client = (ChatClientBuilder(chat_model)
          .default_advisors(QuestionAnswerAdvisor(vector_store=store,
                                                  embedding_model=emb, top_k=2))
          .build())
print(client.prompt().user("SpringBootAI 是否支持 XML 与注解混合?").call().content())
# 输出: （DeepSeek 基于检索到的知识库内容回答——比如"是的，SpringBootAI 同时支持..."）
```

### Function Calling 工具调用

```python
from springbootai.ai import OpenAICompatChatModel, ToolRegistry, Tool, ChatClientBuilder

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
# 输出: （DeepSeek 自动解析工具调用 → 框架执行 get_weather("上海") 和 add(3, 5) → 回填 → 续写最终回复）
# 最终回复大致为："上海天气：晴，25℃；3+5=8"
```

### 文档 ETL（切片入库，LangChain 优先）

```python
from springbootai.ai import TextReader, TokenTextSplitter, CharacterTextSplitter

# langchain-text-splitters 已安装时，内部自动委托 RecursiveCharacterTextSplitter
reader = TextReader()
doc = reader.read_text(open("README.md", encoding="utf-8").read(), source="README.md")

tok_chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
char_chunks = CharacterTextSplitter(chunk_size=500, chunk_overlap=100).split([doc])
print(f"token 切片: {len(tok_chunks)} 段, char 切片: {len(char_chunks)} 段")
# 输出: token 切片: N 段, char 切片: M 段（取决于 README.md 的长度）
```

### 韧性：重试 + 熔断（真实 Provider）

```python
from springbootai.ai import OpenAICompatChatModel, AICircuitBreaker, Message

cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=30)
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat",
                              circuit_breaker=cb, max_retries=3, retry_delay_ms=500)
# 网络抖动时自动重试；连续失败达阈值熔断保护下游
print(model.call([Message.user("你好")]).content())
# 输出: （正常返回 DeepSeek 的回复；如果网络故障则自动重试）
```

### Spring 注解版（@AiClient + @Tool）

```python
from springbootai.ai import AiClient, Tool

@AiClient(provider="deepseek", model="deepseek-chat", temperature=0.3)
class DeepSeekAssistant:
    """由容器装配的 DeepSeek 助手"""

    @Tool(description="查询订单状态")
    def order_status(self, order_id: str) -> str:
        return f"订单 {order_id} 已发货"

print(DeepSeekAssistant().order_status("A-123"))
# 输出: 订单 A-123 已发货
```

### Prometheus 观测

```python
from springbootai.ai import ai_metrics, OpenAICompatChatModel, Message

# 直接打点（record_call 为位置参数 duration，单位秒）
ai_metrics.record_call("deepseek", "deepseek-chat", "success",
                       0.5, {"prompt_tokens": 120, "completion_tokens": 80})
# 结果: Prometheus 计数器 ai_calls_total{provider="deepseek",status="success"} +1

# 推荐：自动计时并打点成功/失败的上下文管理器
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")
with ai_metrics.observe("deepseek", "deepseek-chat") as m:
    resp = model.call([Message.user("你好")])        # 成功/失败自动记录
print(resp.content())
# 输出: （DeepSeek 的回复）
```

> **安全提醒**：以上示例使用 `${DEEPSEEK_API_KEY}` / `YOUR_DEEPSEEK_API_KEY` 占位符，**切勿把真实 key 写进代码或文档**。运行前请通过环境变量注入，避免泄露：
>
> ```bash
> export DEEPSEEK_API_KEY=sk-你的真实key
> ```
>
> 若真实 key 曾提交到公开仓库，请立即到 DeepSeek 控制台吊销并轮换。

---

## 新手常见问题 FAQ

**Q1：没有 API Key 能跑吗？**

A：能，但必须显式设置 `AI_ALLOW_FAKE=true`。默认值是 `false`，避免生产环境漏配 Key 后静默返回假数据。

**Q2：为什么我的程序突然不说话了（一直卡住）？**

A：最常见的原因是 API Key 没配好或过期了。检查一下环境变量是否设置正确，或者试试 `AI_ALLOW_FAKE=true` 能不能跑通假模型版本。

**Q3：temperature 到底是什么？设多少合适？**

A：temperature 控制模型回答的"创造性"。0 = 最死板（每次回答几乎一样），1 = 最天马行空（每次都可能不一样）。一般聊天设 0.7，做代码生成/数学推理设 0~0.3。

**Q4：RAG 和直接问模型有什么区别？**

A：直接问模型，模型只能用它训练时学到的知识回答（知识有截止日期）。RAG 是让模型先查你的资料再回答，能回答关于你专属资料的问题——就像开卷考试 vs 闭卷考试。

**Q5：tool_call 最多能调用几轮？**

A：最多 5 轮。这是为了防止模型和工具之间无限循环调用。如果模型不停地想调工具，第 6 次会被自动拦截。

**Q6：怎么知道我的程序用的是真模型还是假模型？**

A：在线环境设 `AI_ALLOW_FAKE=false`，如果没配 Key 会直接报错。开发时设 `true`，假模型的输出会带有你配置的前缀（比如 `"AI:"`），真模型不会有这个前缀。

**Q7：ETL 切片大小设多少合适？**

A：`chunk_size` 推荐 500~1000，`chunk_overlap` 推荐 `chunk_size` 的 10%~25%。太小语义碎片化，太大检索精度下降。

**Q8：向量库存在内存里，重启会不会丢？**

A：`inmemory` 类型会丢。如果要持久化，把 `vector-store.type` 改成 `redis`，数据就会存到 Redis 里，重启也不丢。

**Q9：Advisor 的执行顺序是怎样的？**

A：按 `order` 值从小到大执行。比如 Memory Advisor 设 `order=1`，RAG Advisor 设 `order=2`，那 Memory 先执行，RAG 后执行。

---

> **相关文档**：[LangChain 模块使用指南](LANGCHAIN_MODULE.md) | [AI & LangChain 测试指南](AI_LANGCHAIN_TEST_GUIDE.md) | [新手入门指南](BEGINNER_GUIDE.md)

---

## 企业加固记录（2.3.9）

- Memory 的 namespace 改为请求级参数，同一 `conversation_id` 在不同租户间不会串读；Redis 键中的外部 ID 会编码并限制长度。
- RAG 根据 `tenant_id`（无租户时可按 `user_id`）执行 metadata 过滤；底层向量库不支持过滤时拒绝降级为无过滤查询。
- 工具授权器收到请求级身份上下文；正超时只允许用于接受 `cancellation_token` 的协作式工具，超时返回后不会遗留后台副作用。
- LangChain Function Calling 保留 assistant tool calls 与 `tool_call_id`，绑定工具时不再修改共享模型实例。
- `max-output-tokens`、`max-total-tokens`、`max-tool-iterations` 与请求超时均已接入自动配置；超限会抛明确异常。

## 声明式 AI 注解（2.3.4）

以下注解由 BeanFactory 在受管 Bean 方法调用时执行，默认不改变普通方法；显式写出注解后才启用。ChatClient、AgentService、EmbeddingModel 和 VectorStore 均按 Bean 名称懒加载，因此配置可以来自本地 YAML、环境变量或 Nacos。

```python
from pydantic import BaseModel
from springbootai.annotations import (
    Prompt, RAG, StructuredOutput, Agent, Embedding, VectorStore,
    AiRetry, AiCache, TokenUsage, ContentModeration,
)

class WeldResult(BaseModel):
    passed: bool
    reason: str

class WeldingAiService:
    embedding_model = Embedding()       # 注入 aiEmbeddingModel
    vector_store = VectorStore()        # 注入 aiVectorStore

    @Prompt("请总结焊接记录：{record}")
    @TokenUsage()
    def summarize(self, record: str):
        pass                            # 框架调用 aiChatClient

    @RAG(top_k=4)
    @AiRetry(attempts=3, delay_ms=200)
    @AiCache(ttl=300, key="{question}")
    @ContentModeration(blocked_terms=["恶意指令"])
    def answer(self, question: str):
        return question                  # 返回值作为检索 query

    @Prompt("输出 JSON：{text}")
    @StructuredOutput(WeldResult)
    def classify(self, text: str):
        pass

@Agent(agent_type="react", max_iterations=5)
class WeldingAgent:
    def run(self, question: str):
        return question
```

`@Prompt` 返回文本（或 `response="response"` 返回 `ChatResponse`）；`@RAG` 先检索再问答；`@StructuredOutput` 支持 Pydantic v1/v2 以及 `dict`；`@Agent` 优先调用 `lcAgentService`，没有 LangChain Bean 时回退 ChatClient。`@AiRetry` 只包装该方法，`@AiCache` 使用稳定参数键和 TTL 内存缓存，`@TokenUsage` 不虚构调用次数而只累计 token，`@ContentModeration` 命中规则时抛出 `ContentModerationError`。第三方依赖未安装、AI Bean 未配置时不会阻断框架启动，但调用显式注解方法会给出明确的运行时错误。

示例和注解索引位于 `examples/example_all/ai_annotations_examples.py`、`annotation_showcase.py` 与 `FEATURE_CATALOG.md`，可用 `python -m example_all.feature_catalog Prompt` 查询真实定义和用法。
