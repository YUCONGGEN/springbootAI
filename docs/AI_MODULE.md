# SpringPy AI 模块

SpringPy AI 模块对齐 **Spring AI 2.0** 的 `ChatClient`/`ChatModel`/`EmbeddingModel`/`Advisor`/`ETL` 抽象，底层复用 LangChain 生态做模型适配（未安装 LangChain 时自动降级为原生 HTTP 调用），上层保留 Spring 风格的统一配置（`application.yml` 的 `spring.ai.*`）与依赖注入（BeanRegistry）。

- **版本**：v1.6.0
- **测试**：66 用例（test_ai_module.py），全量 686 用例 0 失败
- **状态**：✅ 可用

## 目录

1. [快速开始](#1-快速开始)
2. [配置](#2-配置applicationyml)
3. [AI 注解](#3-ai-注解)
4. [ChatClient 链式 API](#4-chatclient-链式 api对齐-spring-ai)
5. [Advisor —— RAG 与会话记忆](#5-advisor--rag-与会话记忆)
6. [文档 ETL（知识库入库）](#6-文档-etl知识库入库)
7. [工具/函数调用](#7-工具函数调用)
8. [自动装配（AutoConfig）](#8-自动装配autoconfig)
9. [模块组成](#9-模块组成)
10. [企业级能力](#10-企业级能力)

---

## 1. 快速开始

```bash
# 安装 AI 可选依赖（LangChain 生态，==锁版本）
pip install -r requirements-ai.txt
```

最小示例（无需真实 API key，降级 FakeChatModel 即可运行）：

```python
from spring.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

接入真实 OpenAI 兼容模型（OpenAI/DeepSeek/Moonshot）：

```python
from spring.ai import configure_ai

# 读取 application.yml 的 spring.ai.* 配置，自动装配所有 Bean
beans = configure_ai()
client = beans["aiChatClient"]
print(client.prompt().user("你好").call().content())
```

只需在 `application.yml` 或环境变量配置 `OPENAI_API_KEY` 即可启用真实模型。

---

## 2. 配置（application.yml）

```yaml
spring:
  ai:
    default-provider: ${AI_PROVIDER:openai}   # openai | ollama
    max-retries: ${AI_MAX_RETRIES:3}
    retry-delay-ms: ${AI_RETRY_DELAY_MS:500}
    openai:
      api-key: ${OPENAI_API_KEY:}
      base-url: ${OPENAI_BASE_URL:https://api.openai.com/v1}  # 兼容 DeepSeek/Moonshot
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

### 配置读取（混合方式）

`configure_ai()` 读取 `spring.ai.*` 子树后，用类型化 `AIProperties` dataclass 绑定。优先级：**环境变量 > application.yml > dataclass 默认值**。

环境变量通过两条路径生效：
1. config_loader 解析 yml 的 `${ENV:default}` 占位符
2. dataclass 字段 `metadata["env"]` 声明的 env 名作为覆盖安全网（即使 yml 写死字面值也能被同名 env 覆盖）

字段类型注解驱动自动类型转换（`int`/`float`/`bool`），无需手动 `int()`/`float()`：

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

### 环境变量速查

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

### Redis 持久化（复用框架 RedisClient）

当 `vector-store.type=redis` 或 `memory.store=redis` 时，`configure_ai` 自动复用框架全局 `spring.utils.redis_client.redis_client` 单例，**无需手动传 redis_client 参数**。

`RedisVectorStore` 与 `RedisChatMemory` 统一用框架 `RedisClient` 封装接口（`hash_set`/`hash_get_all`/`list_push`/`list_range`），同一个 client 同时满足两者。若传入原生 `redis.Redis` 或测试 stub，自动降级原生接口。会话记忆 list 键每次 add 刷新 TTL（默认 86400 秒），防止 Redis 无限增长。

### AI 可选依赖

AI 模块采用"可选依赖 + 降级"设计，未安装任何 AI 依赖时仍可用（降级原生 HTTP + FakeChatModel）。安装 `requirements-ai.txt` 后自动启用 LangChain 生态适配（OpenAI/Ollama）。

---

## 3. AI 注解

### @AiClient

标注一个服务类使用 AI 客户端，框架按 provider 配置自动注入 ChatClient。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| provider | str | "" | 模型提供者 openai/ollama，空时读 spring.ai.default-provider |
| model | str | "" | 模型名覆盖 |
| temperature | float | None | 采样温度覆盖 |

```python
from spring.ai import AiClient

@AiClient(provider="openai", model="gpt-4o", temperature=0.3)
class ChatService:
    pass
```

### @Tool

将函数注册为可被 LLM 调用的工具（Function Calling），框架从签名自动生成 schema。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | "" | 工具名（空时用函数名） |
| description | str | "" | 描述（空时取 docstring） |
| return_description | str | "" | 返回值描述 |

```python
from spring.ai import Tool

@Tool(description="查询订单状态")
def get_order_status(order_id: str, detail: bool = False) -> str:
    """根据订单号返回订单状态"""
    return f"订单{order_id}已发货"
```

### @AiAdvisor / @AiMemory

```python
from spring.ai import AiAdvisor, AiMemory

@AiAdvisor(name="ragAdvisor", order=5)
class RagAdvisor: ...

@AiMemory(store="redis", max_messages=50)
class ChatService: ...
```

---

## 4. ChatClient 链式 API（对齐 Spring AI）

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

---

## 5. Advisor —— RAG 与会话记忆

Advisor 在模型调用前后介入，按 `order` 升序应用请求阶段、降序应用响应阶段。

```python
from spring.ai import (
    ChatClientBuilder, FakeChatModel, FakeEmbeddingModel,
    InMemoryChatMemory, MessageChatMemoryAdvisor,
    QuestionAnswerAdvisor, SimpleInMemoryVectorStore,
)

emb = FakeEmbeddingModel(dim=16)
store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts(["SpringPy 支持 IoC 容器", "SpringPy 内嵌 Sentinel 限流"])

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

---

## 6. 文档 ETL（知识库入库）

```python
from spring.ai import TextReader, TokenTextSplitter, SimpleInMemoryVectorStore

# 1. 读取
doc = TextReader().read_text("长文档内容...", source="manual")
# 2. 切片
chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
# 3. 入库
store = SimpleInMemoryVectorStore()
for c in chunks:
    store.add_texts([c.content])
```

---

## 7. 工具/函数调用

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

> 闭环 Function Calling（tools 自动注入请求体 + tool_call 循环执行回填续写）见 [10.1](#101-闭环-function-calling)。

---

## 8. 自动装配（AutoConfig）

`configure_ai()` 读取 `spring.ai.*` 配置，构建并注册 ChatModel/EmbeddingModel/ChatMemory/VectorStore/ChatClient Bean 到 BeanRegistry（含熔断器注入）。未配置 api-key 时自动降级为 FakeChatModel/FakeEmbeddingModel（开发/测试友好）。

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

---

## 9. 模块组成

| 文件 | 职责 |
|------|------|
| spring/ai/core.py | ChatClient/ChatModel/EmbeddingModel/Advisor/Message 抽象（含 tool_call 执行闭环） |
| spring/ai/annotations.py | @AiClient/@Tool/@AiAdvisor/@AiMemory 注解 |
| spring/ai/providers.py | OpenAI兼容/Ollama Provider（LangChain优先，HTTP降级）+ Fake测试模型 + 真流式SSE/async |
| spring/ai/advisors.py | QuestionAnswerAdvisor(RAG)/MessageChatMemoryAdvisor/SimpleLoggerAdvisor |
| spring/ai/memory.py | ChatMemory (InMemory/Redis) |
| spring/ai/vectorstore.py | VectorStore 抽象 + SimpleInMemoryVectorStore + RedisVectorStore（持久化） |
| spring/ai/etl.py | TextReader/TokenTextSplitter/CharacterTextSplitter |
| spring/ai/tools.py | ToolRegistry 函数调用注册表（签名自动生成 schema） |
| spring/ai/resilience.py | AICircuitBreaker 熔断状态机 + resilient_call 重试（复用 spring.retry） |
| spring/ai/observability.py | AIMetrics 单例（复用 PrometheusMetrics，记录调用/token/延迟/熔断） |
| spring/ai/autoconfig.py | AIProperties 类型化绑定 + spring.ai.* 配置装配 Bean |

---

## 10. 企业级能力

AI 模块在基础抽象之上补齐了 5 项企业级能力，复用框架已有的 AOP/重试/Prometheus 基础设施，开箱即用。

### 10.1 闭环 Function Calling

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

### 10.2 韧性：重试 + 熔断（复用 spring.retry）

`resilient_call()` 复用框架 `spring.retry.retry_decorator.retry` 对 `TransientError`（429/5xx/超时/连接错误）自动重试；`AICircuitBreaker` 镜像 `spring.aop.comprehensive_aop` 的 CLOSED/OPEN/HALF_OPEN 状态机，失败达阈值熔断、`recovery-timeout` 后半开放行探测，保护下游 LLM API。Provider 的 HTTP 调用默认经 `resilient_call` 包装，配置即可调：

```yaml
spring:
  ai:
    max-retries: 3
    retry-delay-ms: 500
    circuit-breaker:
      enabled: true
      failure-threshold: 5
      recovery-timeout: 30
```

### 10.3 真流式 SSE + async

`stream()` 解析 SSE `data:` 增量行逐块 yield（OpenAI）/ NDJSON（Ollama）；`astream()` 用 asyncio.Queue 桥接为异步生成器；`acall()` 用 `asyncio.to_thread` 异步调用。聊天场景刚需。

```python
# 同步流式
for chunk in model.stream([Message.user("讲个故事")]):
    print(chunk.content(), end="", flush=True)

# 异步流式
import asyncio
async def chat():
    async for chunk in await model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
```

### 10.4 Prometheus 观测（复用框架 prometheus 配置）

`AIMetrics` 单例复用框架 `PrometheusMetrics`，自动注册五项指标，Provider 调用前后自动记录，对接企业 Prometheus+Grafana：

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| ai_calls_total | Counter | provider,model,status | 模型调用次数（success/failure） |
| ai_tokens_total | Counter | provider,type | token 用量（prompt/completion） |
| ai_call_duration_seconds | Histogram | provider,model | 调用延迟分布 |
| ai_tool_calls_total | Counter | tool,status | 工具调用次数 |
| ai_circuit_breaker_state | Gauge | provider | 熔断器状态(0=CLOSED,1=OPEN,2=HALF_OPEN) |

### 10.5 RedisVectorStore（RAG 持久化）

`RedisVectorStore` 用 Redis hash 持久化文档（键 `springpy:ai:vectorstore:{collection}`），支持多副本跨实例检索；注入 EmbeddingModel 实现检索时自动嵌入。配置 `vector-store.type: redis` 即用（自动复用框架全局 redis_client 单例），无 client 时安全降级为内存。

```python
from spring.ai import RedisVectorStore, FakeEmbeddingModel, SearchRequest

store = RedisVectorStore(redis_client=redis_client,
                         collection="docs",
                         embedding_model=FakeEmbeddingModel(dim=16))
store.add_texts(["SpringPy 文档一", "SpringPy 文档二"])
# 检索时自动 embed query
results = store.similarity_search(SearchRequest(query="SpringPy", top_k=2))
```

`configure_ai()` 会按 `spring.ai.vector-store.type` 自动装配 `aiVectorStore`（redis 或 inmemory）并注入 `aiEmbeddingModel`，让 RAG 真正自动可用。
