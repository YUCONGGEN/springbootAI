# MCP 客户端、服务端与注解使用指南

本文从零说明 SpringBootAI 的 MCP 模块。看完后，你可以：

- 把本项目中的安全工具发布成 MCP Server；
- 从本项目连接外部 MCP Server；
- 用 `@MCPClient`、`@MCPCall` 像调用普通方法一样调用远程工具；
- 用 `@MCPServer`、`@MCPTool`、`@MCPResource`、`@MCPPrompt` 声明服务端；
- 把外部 MCP 工具接入现有 Spring AI、LangChain 或 LangGraph 流程。

本模块使用官方 MCP Python SDK，不自行实现协议。当前锁定版本是 `mcp==2.0.0`。

## 1. MCP 是什么

MCP 全称 Model Context Protocol。它解决的是“AI 应用怎样用统一协议发现并调用外部能力”的问题。

三个名词先记住：

| 名词 | 用途 | 例子 |
|---|---|---|
| Tool | 执行一个动作 | 查询订单、计算价格 |
| Resource | 读取一份内容 | 帮助文档、配置说明 |
| Prompt | 获取可复用提示词 | 代码审查模板 |

MCP 不是 LangChain，也不是 LangGraph。MCP 负责“连接外部能力”，LangChain 负责模型、Chain、Agent 等 AI 能力，LangGraph 负责有状态流程编排。三者可以组合使用。

## 2. 安装

发布包安装：

```bash
pip install "springbootAI[mcp]"
```

源码仓库安装：

```bash
pip install -r requirements-mcp.txt
```

验证：

```bash
python -c "import mcp, spring.mcp; print('MCP ready')"
```

没有安装 MCP 依赖且 `spring.mcp.enabled=false` 时，核心项目仍可正常运行。

## 3. 第一个注解式 MCP Server

下面代码发布一个加法工具、一份帮助资源和一个提示词：

```python
from spring.mcp import (
    MCPPrompt, MCPResource, MCPServer, MCPTool, build_mcp_server,
)


@MCPServer(
    name="order-tools",
    transport="streamable-http",
    host="127.0.0.1",
    port=8001,
    path="/mcp",
    allowed_tools=["add"],
)
class OrderMCPServer:
    @MCPTool(description="两个整数相加")
    def add(self, a: int, b: int) -> int:
        return a + b

    @MCPResource("guide://quickstart")
    def quickstart(self) -> str:
        return "调用 add 时传入整数 a 和 b。"

    @MCPPrompt(description="生成讲解算式的提示词")
    def explain(self, expression: str) -> str:
        return f"请给小学生讲解算式 {expression}。"


server = build_mcp_server(OrderMCPServer())
server.run()
```

运行后地址是 `http://127.0.0.1:8001/mcp`。

`allowed_tools` 必须明确填写。只写了 `@MCPTool`、却没有进入白名单的方法不会发布。`dangerous=True` 的工具还必须同时设置 `allow_dangerous_tools=True`，因此删除、付款、发消息等动作不会因为误写一个注解就对外开放。

完整文件见 [annotation_demo.py](../example_mcp/annotation_demo.py)。不使用注解的等价写法见 [server.py](../example_mcp/server.py)。

## 4. 第一个注解式 MCP Client

先启动仓库示例服务端：

```bash
python -m example_mcp.server
```

再声明客户端。`@MCPClient("demo")` 的名字必须与配置或 `MCPClientProperties.name` 一致：

```python
from spring.mcp import (
    MCPCall, MCPClient, MCPClientProperties,
    bind_mcp_client, build_client_manager,
)


@MCPClient("demo")
class CalculatorClient:
    @MCPCall("add")
    def add(self, a: int, b: int) -> int:
        raise NotImplementedError  # 声明占位，不会执行

    @MCPCall("order_status")
    async def order_status(self, order_id: str) -> dict:
        raise NotImplementedError


manager = build_client_manager([
    MCPClientProperties(
        name="demo",
        transport="streamable-http",
        url="http://127.0.0.1:8001/mcp",
        allowed_tools=("add", "order_status"),
        timeout_seconds=10,
    )
])

client = bind_mcp_client(CalculatorClient(), manager)
try:
    print(client.add(2, 5))
finally:
    manager.close_sync()
```

调用 `client.add(2, 5)` 时发生的事情是：读取方法参数，检查客户端和工具白名单，通过 MCP 发送请求，等待服务端返回，再把结构化结果作为方法返回值。原方法体不会执行。

FastAPI 的 `async def` 路由应调用注解的 `async def` 方法，这条路径使用 `await manager.acall_tool(...)`，不会用同步网络 I/O 阻塞事件循环。

## 5. 使用 application.yml 自动装配

最小客户端配置：

```yaml
spring:
  mcp:
    enabled: true
    auto-connect: true
    clients:
      orders:
        transport: streamable-http
        url: https://mcp.example.com/mcp
        timeout-seconds: 20
        tool-prefix: orders__
        allowed-tools: [get_order]
        dangerous-tools: []
        allow-dangerous-tools: false
        max-argument-bytes: 65536
        max-result-chars: 100000
```

应用启动装配阶段调用：

```python
from spring.mcp import configure_mcp

beans = configure_mcp()
manager = beans["mcpClientManager"]
```

`configure_mcp()` 会注册：

| Bean | 作用 |
|---|---|
| `mcpClientManager` | 管理持久 MCP 连接和生命周期 |
| `mcpToolRegistry` | 把允许的远程工具变成 Spring AI 工具 |
| `aiEffectiveToolRegistry` | 合并本地工具与远程工具，不绕过各自策略 |
| `mcpServer` | 配置启用服务端时创建的服务实例 |

应用关闭时必须调用 `mcpClientManager.close_sync()`。否则连接、后台事件循环和子进程可能不能及时释放。若希望由 ASGI 生命周期管理连接，可设置 `auto-connect: false`，在 startup 中连接、shutdown 中关闭。

## 6. 把 MCP 工具给 Spring AI、LangChain 和 LangGraph

`configure_mcp()` 创建的 `aiEffectiveToolRegistry` 会挂到现有 `aiChatClient`。模型只能看到服务器允许、客户端也允许、最终执行策略仍允许的交集。

LangChain Agent 可把 Spring AI 工具转换为 LangChain 工具后使用。LangGraph 节点可以复用 `langGraphRuntime.tool_registry`，也可以在一个普通节点中调用注解客户端：

```python
from spring.langgraph import GraphNode

class OrderFlow:
    def __init__(self, order_client):
        self.order_client = order_client

    @GraphNode
    async def load_order(self, state):
        order = await self.order_client.order_status(state["order_id"])
        return {"order": order}
```

这里只组合已有能力，没有重新实现 Agent、图引擎或 MCP 协议。

## 7. stdio 子进程模式

stdio 适合由客户端启动本机工具进程：

```python
import sys
from spring.mcp import MCPClientProperties

props = MCPClientProperties(
    name="local-calc",
    transport="stdio",
    command=sys.executable,
    args=("-m", "example_mcp.stdio_server"),
    allowed_tools=("multiply",),
)
```

stdio 服务端不能向标准输出打印日志，因为标准输出属于 MCP 协议通道。日志必须写标准错误或文件。仓库测试会真的启动这个子进程并调用 `multiply`，不是同进程模拟。

## 8. 挂载到现有 FastAPI 应用

不能把 MCP ASGI app 当作普通 `@GetMapping` 或三参数路由函数注册。应使用 ASGI mount，并启动 MCP session manager：

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

server = build_mcp_server(OrderMCPServer())

@asynccontextmanager
async def lifespan(app):
    async with server.mounted_lifespan():
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/", server.streamable_http_app())
```

若 MCP 与业务 API 使用同一 FastAPI，建议为 MCP 使用独立路径并在反向代理层设置请求体、超时、认证和限流。

## 9. 生产安全要求

1. 非本机 HTTP 客户端默认只允许 HTTPS。临时开启 `allow_insecure_http` 不适合生产。
2. 监听非回环地址时必须 `auth_required=true`，并提供 issuer、resource server URL、scope 和真实 `token_verifier`。
3. `allowed_tools` 使用最小白名单，不在生产使用 `*`。
4. 把查询工具与写入工具分开部署；危险工具保留人工确认、幂等键和审计日志。
5. 不把 API Key 写入源码。HTTP Header 和 stdio 环境变量应来自密钥管理系统。
6. 注解直连和 AI 工具桥接都执行工具白名单、危险标记、参数大小、结果大小和超时限制；服务端还按 JSON Schema 校验输入。
7. MCP Server 是能力入口，不是权限系统。工具内部仍要校验用户、租户和资源归属。
8. `allowed_hosts`、`allowed_origins` 和请求体上限不要为了“先跑通”而全部放开。

公开服务示意：

```python
@MCPServer(
    name="orders",
    host="0.0.0.0",
    allowed_tools=["get_order"],
    auth_required=True,
    auth_issuer_url="https://auth.example.com",
    resource_server_url="https://api.example.com/mcp",
    required_scopes=["mcp:read"],
    allowed_hosts=["api.example.com"],
    allowed_origins=["https://console.example.com"],
)
class OrdersServer:
    ...

server = build_mcp_server(OrdersServer(), token_verifier=my_token_verifier)
```

## 10. 健康检查和故障处理

```python
status = manager.health()
# {"orders": "UP", "inventory": "DOWN"}
```

`fail_fast: true` 表示关键 MCP 服务连接失败时启动失败；非关键能力可设为 `false`，但业务必须明确处理工具缺失，不应假装调用成功。

常见错误：

| 错误 | 原因 | 处理 |
|---|---|---|
| `requires HTTPS outside localhost` | 远程地址使用明文 HTTP | 配置 HTTPS |
| `not allowed` | 工具不在白名单 | 核对客户端和服务端白名单 |
| `manager bean is unavailable` | 未装配也未注入 manager | 调用 `configure_mcp` 或 `bind_mcp_client` |
| `allowed_tools must explicitly list` | 注解服务未声明发布名单 | 在 `@MCPServer` 填 `allowed_tools` |
| 调用超时 | 服务不可达或工具耗时太长 | 检查网络、服务日志和工具自身超时 |

## 11. 测试

```bash
pytest tests/test_mcp_module.py -v
```

测试覆盖配置拒绝策略、工具白名单、危险工具、Schema、资源、Prompt、注解客户端、注解服务端、Spring AI 工具桥接、真实 Streamable HTTP 和真实 stdio 子进程。

不需要真实大模型 API Key。HTTP 集成测试会在本机随机端口启动临时 Uvicorn 服务，测试结束后关闭。
