# SpringBootAI LangGraph 模块使用指南

这是一份“第一次接触也能跟着做”的教程。你不需要先学会 LangGraph 的全部概念，按章节复制命令，就可以跑出第一个流程。

## 先说结论：LangGraph 用来做什么

如果你的需求只是“用户问一句，模型答一句”，先使用 [AI 模块](AI_MODULE.md) 的 `ChatClient`，不需要 LangGraph。

如果一个 AI 业务要经过多个步骤，例如：

```text
收到申请 -> 判断风险 -> 普通申请直接回答
                    -> 大额申请暂停，等待人工批准 -> 继续执行
```

这时 LangGraph 很合适。它把流程画成一张“可执行的流程图”。流程中的数据叫 **State（状态）**，每个处理步骤叫 **Node（节点）**，步骤之间的连接叫 **Edge（边）**。

可以把它理解成公司的审批单：

| LangGraph 名称 | 小白理解 |
|---|---|
| State | 审批单上不断补充的字段，如金额、风险、结果 |
| Node | 一个处理岗位，如“计算风险”“调用 AI”“人工审核” |
| Edge | 规定下一步交给哪个岗位 |
| Checkpoint | 把审批单保存下来，服务重启后还能接着处理 |
| Interrupt | 在付款、删数据等危险动作前按下暂停键 |
| thread_id | 一张审批单的唯一编号 |

本项目的 `springbootai.langgraph` 只是 Spring 风格的配置和安全外壳，真正的图执行交给官方 `langgraph`，不会重新实现图引擎。模型、重试、熔断和工具权限统一复用 `springbootai.ai`，避免一套应用维护两套 AI 客户端。

## 目录

1. [安装可选依赖](#1-安装可选依赖)
2. [五分钟跑通 demo](#2-五分钟跑通-demo)
3. [看懂最小代码](#3-看懂最小代码)
4. [把 Fake 模型换成 springbootai.ai](#4-把-fake-模型换成-springai)
5. [写条件分支](#5-写条件分支)
6. [人工审核和恢复](#6-人工审核和恢复)
7. [application.yml 配置](#7-applicationyml-配置)
8. [在 Spring 应用中使用](#8-在-spring-应用中使用)
9. [同步、异步和流式调用](#9-同步异步和流式调用)
10. [测试](#10-测试)
11. [常见错误](#11-常见错误)
12. [生产上线前检查](#12-生产上线前检查)

## 1. 安装可选依赖

LangGraph 不属于核心包，也不会随 LangChain classic 自动安装。只有需要状态图时才安装它：

```bash
# 从 PyPI 安装项目的可选 extra
pip install springbootAI[langgraph]

# 在本源码仓库中安装锁定版本
pip install -r requirements-langgraph.txt
```

本项目当前锁定：

```text
langgraph==1.2.9
langgraph-checkpoint-sqlite==3.1.1
```

以下命令可以确认安装成功：

```bash
python -c "import langgraph; print(langgraph.__version__)"
```

没有安装 LangGraph 时，原有 Web、AI、LangChain classic 功能仍可使用；只有真正创建 `LangGraphWorkflow` 才会提示安装 `springbootAI[langgraph]`。

## 2. 五分钟跑通 demo

仓库已经提供一个不需要真实 API Key 的示例。它使用 AI 模块中的 `FakeChatModel`，不会访问网络：

```bash
python examples/example_langgraph/demo.py
```

你会看到三段结果：

```text
普通请求结果: ... risk=normal ...
大额请求状态: ... __interrupt__ ...
人工批准后恢复: ... approved=True
```

这三段分别表示：普通路径完成、大额路径暂停、用同一个线程号恢复成功。

示例源码在 [examples/example_langgraph/demo.py](../examples/example_langgraph/demo.py)。它模拟“订单审核”流程：金额小于 1000 直接结束，金额达到 1000 时要求人工审核。示例使用内存检查点，只适合学习；生产不能照搬这一点，见[第 12 章](#12-生产上线前检查)。

## 3. 看懂最小代码

先写一个只会“加一”的图，确认你理解基本结构：

```python
from typing import TypedDict
from langgraph.graph import END
from springbootai.langgraph import LangGraphProperties, LangGraphWorkflow

# 1. 定义流程中会传递哪些字段
class State(TypedDict, total=False):
    value: int

# 2. 创建一个图，State 是它的数据格式
graph = LangGraphWorkflow(
    LangGraphProperties(enabled=True, name="increment"),
    state_schema=State,
)

# 3. 节点读取 state，返回需要更新的字段
def increment(state: State):
    return {"value": state["value"] + 1}

graph.add_node("increment", increment)

# 4. 规定从入口开始，执行完后结束
graph.set_entry_point("increment")
graph.add_edge("increment", END)

# 5. 调用图。thread_id 是这一次流程的唯一编号
result = graph.invoke({"value": 1}, thread_id="user-42-request-1")
print(result["value"])  # 2
```

逐行理解：

1. `State` 是一张表的列定义，节点之间只通过它传递数据。
2. `add_node` 注册处理函数。函数最好短小、无隐藏全局变量，便于测试。
3. `set_entry_point` 表示第一步；`END` 表示流程结束。
4. 节点可以只返回部分字段，LangGraph 会把它合并回原状态。
5. `invoke` 是同步调用。Web 的 `async def` 路由请使用 `ainvoke`，见第 9 章。

## 4. 把 Fake 模型换成 springbootai.ai

不要在每个节点里写 `ChatOpenAI(...)`，也不要把 API Key 写进代码。先让 AI 模块统一创建 `aiChatModel`，LangGraph 再拿来使用：

```python
from springbootai.context.registry import BeanRegistry
from springbootai.ai.autoconfig import configure_ai
from springbootai.langgraph.autoconfig import configure_langgraph
from springbootai.ai.core import Message

registry = BeanRegistry()
configure_ai(registry=registry)
beans = configure_langgraph(
    registry=registry,
    config={"spring": {"langgraph": {"enabled": True}}},
)
runtime = beans["langGraphRuntime"]

def answer(state):
    response = runtime.call_model([Message.user(state["question"])])
    return {"answer": response.content()}
```

`runtime.call_model` 会复用 `springbootai.ai` 的 provider、重试、熔断和工具策略。配置真实模型只需要设置环境变量，例如：

```powershell
$env:AI_PROVIDER = "openai"
$env:OPENAI_API_KEY = "sk-your-key"
```

开发时可以使用 demo 的 Fake 模型：

```powershell
$env:AI_ALLOW_FAKE = "true"
```

生产请保持 `AI_ALLOW_FAKE=false`，否则 Key 配置错误时可能悄悄降级成假模型。

## 5. 写条件分支

条件边就是“根据结果走不同路线”。例如金额达到 1000 才进入审核：

```python
def classify(state):
    return {"risk": "review" if state["amount"] >= 1000 else "normal"}

def route(state):
    return "approval" if state["risk"] == "review" else "finish"

graph.add_node("classify", classify)
graph.add_node("approval", approval)
graph.add_node("finish", lambda state: {})
graph.set_entry_point("classify")
graph.add_conditional_edges(
    "classify", route,
    {"approval": "approval", "finish": "finish"},
)
graph.add_edge("approval", "finish")
graph.add_edge("finish", END)
```

路由函数应该只做判断，不写数据库、不扣款。真正有副作用的动作放到单独节点，并做好幂等键，这样失败重试不会重复扣款。

## 6. 人工审核和恢复

涉及付款、发邮件、删除数据、写 SQL 的节点不能让模型直接执行。使用 `interrupt` 暂停：

```python
from langgraph.types import interrupt

def approval(state):
    decision = interrupt({
        "message": "金额较高，请人工确认",
        "amount": state["amount"],
    })
    return {"approved": decision == "approve"}
```

调用时必须使用检查点和线程号：

```python
from springbootai.langgraph import LangGraphProperties, LangGraphWorkflow

graph = LangGraphWorkflow(
    LangGraphProperties(
        enabled=True,
        checkpointer="memory",
        allow_in_memory=True,  # 仅 demo/测试
    ),
    state_schema=State,
)

paused = graph.invoke(
    {"amount": 2000},
    thread_id="order-1001",
    tenant_id="tenant-a",
)
print(paused["__interrupt__"])  # 展示给审核人

resumed = graph.resume(
    thread_id="order-1001",
    tenant_id="tenant-a",
    resume_value="approve",
)
```

拒绝、修改、批准都要记录审计日志。不能只相信前端传来的“已批准”字段。

### 6.1 验证服务重启后可以继续

可选依赖包含官方 `langgraph-checkpoint-sqlite`。下面的工厂会关闭 pickle fallback，并只允许内置安全类型反序列化：

```python
from springbootai.langgraph import LangGraphProperties, LangGraphWorkflow
from springbootai.langgraph import open_sqlite_checkpointer

properties = LangGraphProperties(
    enabled=True,
    checkpointer="injected",
)

# 第一次启动：创建 workflow，执行到 interrupt 后退出 with，连接会正确关闭。
with open_sqlite_checkpointer("./data/checkpoints.sqlite") as saver:
    graph = LangGraphWorkflow(properties, state_schema=State, checkpointer=saver)
    # 按前面的方式注册节点和边，然后执行：
    paused = graph.invoke(
        {"amount": 2000},
        thread_id="order-1001",
        tenant_id="tenant-a",
    )

# 服务重启：重新打开同一文件并用同一组 id 重建同一张图，之后恢复。
with open_sqlite_checkpointer("./data/checkpoints.sqlite") as saver:
    graph = LangGraphWorkflow(properties, state_schema=State, checkpointer=saver)
    # 必须注册与第一次启动相同的节点和边。
    result = graph.resume(
        thread_id="order-1001",
        tenant_id="tenant-a",
        resume_value="approve",
    )
```

SQLite 适合本地开发、演示和单进程服务，不适合 Gunicorn 多 worker 或多台机器共享。企业生产需要使用官方的 PostgreSQL 等共享 checkpointer，并通过 `checkpointer="injected"` 注入；数据库账号只授予 checkpoint 表所需权限，数据库不可由不可信用户写入。不要把 SQLite 文件放进临时目录或容器临时层，否则容器重建后状态仍会丢失。

## 7. application.yml 配置

项目根目录已放好完整示例。最安全的默认配置是关闭：

```yaml
spring:
  langgraph:
    enabled: ${LG_ENABLED:false}
    name: ${LG_NAME:springbootai}
    timeout-seconds: ${LG_TIMEOUT_SECONDS:60}
    max-steps: ${LG_MAX_STEPS:25}
    checkpointer: ${LG_CHECKPOINTER:none} # none | memory | injected
    allow-in-memory: ${LG_ALLOW_IN_MEMORY:false}
    require-thread-id: ${LG_REQUIRE_THREAD_ID:true}
    max-input-bytes: ${LG_MAX_INPUT_BYTES:65536}
    stream-mode: ${LG_STREAM_MODE:updates}
```

常用配置说明：

| 配置 | 默认值 | 小白解释 |
|---|---:|---|
| `enabled` | `false` | 是否启用这个模块 |
| `timeout-seconds` | `60` | 一次流程最多等待多久 |
| `max-steps` | `25` | 最多走多少步，防止图写错后无限循环 |
| `checkpointer` | `none` | 是否保存流程状态 |
| `memory` | 仅测试 | 状态只放内存，进程重启就没了 |
| `injected` | 生产 | 由应用注入 PostgreSQL/Mongo 等持久化实现 |
| `require-thread-id` | `true` | 是否强制每次调用带流程编号 |
| `max-input-bytes` | `65536` | 限制外部输入大小，防止超大请求拖垮服务 |

## 8. 在 Spring 应用中使用

示例应用的 `LangChainAppConfig` 会按顺序装配：

```text
configure_ai() -> aiChatModel / aiEmbeddingModel
configure_langchain() -> lc* Bean
configure_langgraph() -> langGraphRuntime
```

LangGraph 默认关闭，所以旧应用不会因为没有安装 extra 而启动失败。打开后可以从 `BeanRegistry` 获取：

```python
from springbootai.context.registry import BeanRegistry

runtime = BeanRegistry().get("langGraphRuntime")
workflow = runtime.workflow(state_schema=State, name="order_flow")
```

Controller 只接收请求和返回结果，节点编排放在 Service 中。不要在 Controller 里直接创建图或保存全局用户状态。

## 9. 同步、异步和流式调用

| 使用位置 | 应该调用 |
|---|---|
| 命令行、定时任务 | `invoke` / `stream` |
| FastAPI `async def` 路由 | `ainvoke` / `astream` |
| 等待人工决定 | `resume` |

```python
result = await workflow.ainvoke(
    {"question": "你好"}, thread_id="t-1", tenant_id="tenant-a"
)

async for update in workflow.astream(
    {"question": "你好"}, thread_id="t-2", tenant_id="tenant-a"
):
    print(update)
```

LangGraph 能编排异步节点，但不能把同步数据库、Feign 或 AI HTTP 自动变成异步。同步操作请使用项目已有线程池或异步客户端；AI provider 也要设置连接和读取超时。`timeout-seconds` 是调用方等待上限，超时后的工作线程不能被 Python 强行杀死，因此节点必须幂等。

## 10. 测试

先运行 LangGraph 专项测试：

```bash
pytest tests/test_langgraph_module.py -v
```

测试覆盖：

- 配置绑定和危险的内存 checkpointer 默认拒绝；
- 同步 `invoke`、异步 `ainvoke`、`stream`、`astream`；
- 条件路由和最大步数；
- `thread_id`/`tenant_id` 隔离要求；
- `interrupt` 暂停和 `resume` 恢复；
- SQLite 连接关闭并重新打开后的真实恢复，以及严格反序列化策略；
- 自动装配关闭时不注册 Bean，开启时复用 AI 模型。

再运行相关回归：

```bash
pytest tests/test_ai_module.py tests/test_langchain_module.py -v
```

没有安装 LangGraph 的环境会跳过专项测试；CI 会安装 `requirements-langgraph.txt`，所以 CI 中会执行真实图运行测试。

## 11. 常见错误

### `LangGraph is not installed`

执行：

```bash
pip install springbootAI[langgraph]
```

确认当前 Python 和 pip 是同一个环境：

```bash
python -m pip show langgraph
```

### `thread_id is required`

调用时补上 `thread_id="业务单号-请求号"`。这是为了让流程可追踪、可恢复，不建议关闭。

### `tenant_id is required when a checkpointer is enabled`

启用检查点时再传 `tenant_id`。多租户系统不能让不同租户共享同一个状态命名空间。

### `in-memory checkpointer is disabled`

这是故意的安全保护。内存检查点只用于测试：

```python
LangGraphProperties(checkpointer="memory", allow_in_memory=True)
```

生产请改用 `checkpointer="injected"` 并注入持久化实现。

### `LangGraph execution timed out`

降低单次图的工作量，并检查 `springbootai.ai` provider 的 HTTP timeout、重试和熔断配置。不要只把 LangGraph timeout 调得无限大。

## 12. 生产上线前检查

1. 依赖锁定为经过测试的版本，CI 执行单元测试、集成测试和 `pip-audit`。
2. 生产使用持久化 checkpointer，绝不使用 `InMemorySaver`；多 worker 共享同一数据库后端，不能共享本地 SQLite 文件。
3. 所有调用带稳定的 `thread_id` 和 `tenant_id`，并在服务端校验租户归属。
4. 付款、发消息、写库等节点具备幂等键、超时、重试上限和审计日志。
5. 工具继续使用 `springbootai.ai` 的白名单、参数大小限制、执行超时和人工审批策略。
6. 不在节点里保存 API Key、数据库密码或全局连接；统一从 Spring 配置和 Bean 获取。
7. 生产压测覆盖普通路径、条件分支、模型慢响应、checkpointer 故障、重复恢复和并发线程。
8. 监控图名、节点耗时、失败原因、重试次数和中断恢复次数，但过滤提示词和业务敏感字段。
9. checkpoint 数据库拒绝不可信写入；序列化器保持 `pickle_fallback=False` 和严格类型白名单。

LangGraph 的官方定位和基础概念参见[官方概览](https://docs.langchain.com/oss/python/langgraph/)。人工审核必须配合 checkpointer，生产应使用持久化实现，参见[官方 HITL 文档](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)。

## 13. 注解式工作流

不想手工连续调用 `add_node()`、`add_edge()` 时，可以把图结构直接写在类和方法上。注解只收集结构，执行仍由官方 LangGraph `StateGraph` 完成。

### 13.1 最小可运行示例

```python
from typing import TypedDict
from springbootai.langgraph import GraphEdge, GraphInvoke, GraphNode, LangGraph


class State(TypedDict):
    value: int


@GraphEdge("increment", "double")
@LangGraph(state_schema=State, name="counter")
class CounterFlow:
    @GraphNode(entry=True)
    def increment(self, state: State):
        return {"value": state["value"] + 1}

    @GraphNode(end=True)
    def double(self, state: State):
        return {"value": state["value"] * 2}

    @GraphInvoke
    def run(self, input_state: State, thread_id: str):
        raise NotImplementedError


result = CounterFlow().run({"value": 2}, thread_id="request-001")
print(result)  # {'value': 6}
```

各注解的作用：

| 注解 | 放在哪里 | 作用 |
|---|---|---|
| `@LangGraph` | 类 | 声明状态类型、图名和执行边界 |
| `@GraphNode` | 方法 | 把方法注册成节点 |
| `@GraphEdge` | 类 | 连接两个节点，可重复使用 |
| `@GraphRoute` | 方法 | 根据状态选择条件分支 |
| `@GraphInvoke` | 方法 | 调用该方法时真正执行整张图 |

每张图必须恰好有一个 `entry=True`。`end=True` 会自动连接 LangGraph 的 `END`。节点名重复、边指向不存在的节点、没有入口或多个入口都会在构建时失败。

### 13.2 条件分支

```python
@LangGraph(state_schema=State, name="risk_flow")
class RiskFlow:
    @GraphNode(entry=True)
    def classify(self, state):
        return {"path": "manual" if state["score"] > 80 else "auto"}

    @GraphRoute("classify", {"manual": "review", "auto": "approve"})
    def route(self, state):
        return state["path"]

    @GraphNode(end=True)
    def review(self, state):
        return {"status": "WAITING_REVIEW"}

    @GraphNode(end=True)
    def approve(self, state):
        return {"status": "APPROVED"}
```

`@GraphRoute` 方法只负责返回路径键，不是普通节点。`paths` 显式列出允许的目标，避免任意字符串被当成节点名。

### 13.3 异步执行

```python
@GraphInvoke
async def run_async(self, input_state: State, thread_id: str, tenant_id: str):
    raise NotImplementedError

result = await flow.run_async(
    {"value": 1},
    thread_id="order-1001",
    tenant_id="tenant-a",
)
```

异步占位方法会调用 `workflow.ainvoke()`。普通占位方法调用 `workflow.invoke()`。第一次调用会构建并编译图，实例内部缓存同一个 workflow；并发首次调用使用锁，避免重复构建。对延迟敏感的生产服务仍建议在 startup 中显式预构建：

```python
from springbootai.langgraph import build_langgraph

flow = RiskFlow()
build_langgraph(flow)
```

### 13.4 配置继承和覆盖

如果容器中已有 `langGraphRuntime`，注解默认继承它的超时、最大步数、checkpointer、输入上限和 `require_thread_id`。只在确实需要时覆盖：

```python
@LangGraph(
    state_schema=State,
    name="short_flow",
    timeout_seconds=15,
    max_steps=8,
    max_input_bytes=16_384,
)
class ShortFlow:
    ...
```

没有自动装配 Runtime 时，注解采用安全默认值：必须传 `thread_id`、最大 25 步、输入 64 KiB、60 秒调用等待上限、不保存 checkpoint。

生产需要人工中断或恢复时，继续使用 `checkpointer="injected"` 和外部持久化 checkpointer。注解不会把内存 checkpoint 变成多 worker 共享存储。

### 13.5 在节点中复用 Spring AI 和 MCP

节点就是普通实例方法，可以构造器注入 `LangGraphRuntime`、`ChatClient` 或一个 `@MCPClient`：

```python
@GraphNode
async def fetch_order(self, state):
    order = await self.order_mcp.order_status(state["order_id"])
    return {"order": order}

@GraphNode
async def explain(self, state):
    response = await self.langgraph_runtime.acall_model([
        {"role": "user", "content": f"解释订单：{state['order']}"}
    ])
    return {"answer": response.content}
```

这里 MCP 负责外部工具通信，Spring AI 负责模型调用，LangGraph 只负责编排。三层各用现成实现，没有重复造协议、Agent 或状态图引擎。

可直接运行 [annotation_demo.py](../examples/example_langgraph/annotation_demo.py)：

```bash
python examples/example_langgraph/annotation_demo.py
```

专项测试：

```bash
pytest tests/test_ai_declarative_annotations.py tests/test_langgraph_module.py -v
```
