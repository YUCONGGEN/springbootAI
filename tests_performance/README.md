# SpringBootAI 性能与容量测试

这套测试使用固定版本的 k6，通过 Docker 运行，不需要在本机安装 k6。默认会构建并启动一个双 worker 基准服务，覆盖异步/同步 Controller、请求体解析、内嵌 Gateway、Bean Validation、缓存增强、CSV、JPA 乐观锁和条件装配。

## 先理解四个数字

压测不是“请求越多越好”，而是观察服务在指定负载下是否仍然稳定。下面四个指标足够让第一次压测的人读懂结果：

| 指标 | 大白话解释 | 如何判断 |
|---|---|---|
| RPS | 每秒发出多少个请求（Requests Per Second） | 先从 smoke 开始，再逐步增加；不要一开始就把目标设到机器极限 |
| p95 | 95% 请求在多少毫秒内完成，剩下 5% 更慢 | 比平均值更能反映大多数用户的体验 |
| p99 | 99% 请求在多少毫秒内完成，最慢的 1% 之外的尾延迟 | 用来发现偶发慢请求、连接池等待和同步阻塞 |
| dropped iterations | k6 因为没有足够 VU 或服务太慢，没能按目标发出请求的次数 | 生产容量基线应为 0；非 0 说明压力模型或服务容量已达到边界 |

默认门禁是错误率 < 1%、p95 < 500 ms、p99 < 1000 ms、无 dropped iterations、无同步队列 503。门禁是示例起点，不是所有业务的通用标准；支付、文件上传等接口应按自己的 SLA 调整。

## 快速开始

在仓库根目录运行：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke
```

脚本会自动启动基准服务、等待健康检查、执行压测并清理容器。JSON 结果保存在 `tests_performance/results/`。

第一次只执行 `smoke`。它只持续 20 秒，作用是确认 Docker、构建、健康检查和路由都正常。smoke 通过后再执行 `baseline` 建立基线，最后才执行 `stress` 或 9 小时 `soak`。如果 smoke 都失败，不要直接增加 RPS；先查看终端里第一条错误和 `tests_performance/results/` 中最新 JSON。

## 压测档位

| Profile | 默认负载 | 用途 |
|---|---:|---|
| `smoke` | 5 RPS，20 秒 | 验证环境、路由和阈值 |
| `baseline` | 100 RPS，10 分钟 | 建立正常容量基线 |
| `stress` | 50 到 500 RPS 阶梯增长 | 寻找容量拐点和超载行为 |
| `soak` | 100 RPS，2 小时 | 检查连接、线程和内存长期稳定性 |

建议依次执行：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke
.\scripts\run-load-test.ps1 -Profile baseline -Rate 200 -Duration 15m
.\scripts\run-load-test.ps1 -Profile stress -TargetRps 1000 -MaxVus 2000
.\scripts\run-load-test.ps1 -Profile soak -Rate 200 -Duration 2h
```

## 压测业务服务

传入 `TargetUrl` 后不会启动基准服务。宿主机的 `localhost` 和 `127.0.0.1` 会自动转换为容器可访问的 `host.docker.internal`。

```powershell
.\scripts\run-load-test.ps1 `
  -Profile baseline `
  -Workload custom `
  -TargetUrl http://127.0.0.1:8080 `
  -CustomPath /api/orders `
  -CustomMethod POST `
  -CustomBody '{"sku":"SKU-1","quantity":1}' `
  -AuthToken 'replace-with-test-token' `
  -Rate 100 `
  -Duration 10m `
  -P95Ms 300 `
  -P99Ms 800
```

不要对生产写接口直接使用示例请求体。订单、支付等接口应使用隔离的测试租户、可回收数据和专用幂等键。

## 工作负载

- `mixed`：25% 异步、20% 同步阻塞、15% Gateway、10% JSON POST；Validation 与缓存各 7.5%，CSV、JPA、Conditional 各 5%。
- `async`：仅测试异步 Controller。
- `sync`：仅测试同步 Controller和线程池。
- `gateway`：仅测试异步 Gateway 转发和连接池。
- `echo`：仅测试 JSON 请求体解析和响应序列化。
- `cpu`：测试同步 CPU 任务，不代表多进程外部计算服务。
- `validation`：每次请求通过受管 Service 的 `@BeanValidate` AOP 校验 4 个字段约束。
- `cache`：每次请求执行 `@CachePut -> @Cacheable 命中 -> @CacheEvict -> @Cacheable 未命中`，并校验返回值和命中次数。
- `csv`：在内存中按 `@CsvProperty/@CsvIgnore` 完成写入和读取 round-trip；`-CsvRows` 控制每次请求的行数。
- `jpa`：每次请求在隔离的 SQLite 事务中执行一次 `@Version` 成功更新、一次旧版本冲突，并确认 `@Transient` 未进入映射。
- `conditional`：每次请求在真实应用上下文上重复求值五类 `@Conditional`；`-ConditionalEvaluations` 控制次数。
- `seata`：调用官方 Java bridge 的真实 TC，按 9:1 比例执行全局提交/回滚；它验证 TM/TC 通道和协调延迟，不会伪造 Python AT，也不替代带业务分支回调的 TCC 故障测试。
- `custom`：压测传入的真实业务路径。

可以逐项建立基线：

```powershell
.\scripts\run-load-test.ps1 -Profile baseline -Workload validation -Rate 300 -Duration 10m
.\scripts\run-load-test.ps1 -Profile baseline -Workload cache -Rate 300 -Duration 10m
.\scripts\run-load-test.ps1 -Profile baseline -Workload csv -CsvRows 200 -Rate 100 -Duration 10m
.\scripts\run-load-test.ps1 -Profile baseline -Workload jpa -Rate 100 -Duration 10m
.\scripts\run-load-test.ps1 -Profile baseline -Workload conditional -ConditionalEvaluations 500 -Rate 200 -Duration 10m
```

`jpa` 是框架乐观锁执行器的确定性微基准，不代表 MySQL/PostgreSQL 的真实连接池、锁等待和磁盘能力。生产容量测试仍应通过 `custom` 指向使用真实数据库的业务接口。

## 条件装配基准

条件注解主要影响启动和 BeanDefinition 注册，而不是业务请求热路径。下面的命令会在 Docker 中重复装配 200 个组件，其中 20% 按配置跳过，并对 p95 设置失败门禁：

```powershell
.\scripts\run-conditional-benchmark.ps1 `
  -Iterations 100 `
  -Components 500 `
  -P95Ms 500
```

结果写入 `tests_performance/results/conditional-assembly-*.json`，包含 min、avg、p50、p95、p99、max、注册数量和失败明细。

## 判定规则

默认门禁为：HTTP 错误率小于 1%、p95 小于 500 ms、p99 小于 1000 ms、无 dropped iterations、无同步线程池超载 `503`。任一阈值失败时 k6 和 PowerShell 脚本都会返回非零退出码。

重点查看结果中的：

- `failed_rate`：业务或协议错误比例。
- `p95_ms` / `p99_ms`：尾延迟。
- `dropped_iterations`：k6 无法维持目标到达率，可能是 VU 不足或服务显著变慢。
- `overload_responses`：SpringBootAI 有界同步队列主动拒绝的请求数。

压测最大容量时，应把 k6 放在独立机器上，避免负载发生器与服务竞争 CPU、网络和 Docker 资源。容量结论至少重复三次，并同时观察 `/actuator/prometheus`、数据库连接池和宿主机指标。

## Worker 恢复测试

下面的脚本会启动至少两个 worker，终止其中一个进程，并验证 Uvicorn 能在限定时间内拉起新 worker，同时统计恢复窗口中的请求失败数：

```powershell
.\scripts\run-worker-recovery-test.ps1 -Workers 4 -RecoverySeconds 15 -MaxFailures 2
```

结果同样写入 `tests_performance/results/`。该测试验证单 worker 崩溃恢复，不替代整机重启、网络分区和数据库故障演练。

## 真实 Seata 契约测试

项目不再安装未完成的非官方 Python Seata 包。`docker-compose.integration.yml` 会启动 Apache Seata Server 2.5.0、Java 客户端 bridge 和 TCC fence 表。启动后执行：

```powershell
$env:SEATA_BRIDGE_TOKEN='springpy-integration-secret'
$env:RUN_SEATA_INTEGRATION_TESTS='1'
docker compose -f docker-compose.integration.yml up -d --build --wait seata-server seata-bridge
pytest tests_integration/test_seata_distributed_contract.py -v
```

测试会启动宿主机回调端点，验证 `prepare -> commit` 和 `prepare -> rollback` 都由真实 Seata TC 驱动，并检查 XID、分支 ID、metadata 与共享 token。它还需要在业务数据库层验证提交、回滚、超时和进程崩溃恢复；TCC 回调必须由业务服务自己实现幂等、防空回滚和防悬挂。

只压测 TC 的 TM 通道（不启动基准应用）：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke -Workload seata -TargetUrl http://127.0.0.1:18091 -SeataBridgeToken springpy-integration-secret -Rate 5 -Duration 20s
.\scripts\run-load-test.ps1 -Profile soak -Workload seata -TargetUrl http://127.0.0.1:18091 -SeataBridgeToken springpy-integration-secret -Rate 100 -Duration 9h -MaxVus 1000
```

这个 workload 每次迭代创建一个真实全局事务并提交或回滚；它不注册业务 TCC 分支，因此不能代表订单、库存等业务最终一致性。业务压测应把 `custom` 指向真实业务接口，并让业务接口注册自己的 TCC 回调。

## 9 小时注解混合压测

在仓库根目录直接运行：

```powershell
.\scripts\run-9h-soak-test.ps1
```

默认持续 9 小时、100 次迭代/秒、4 个 Uvicorn worker。正式长跑前会先执行短混合烟测和三种测试切片装配门禁；HTTP 错误、业务断言、丢弃迭代或过载响应超过阈值都会返回非零退出码。JSON 报告写入 `tests_performance/results/`。

无需改脚本即可调整压力：

```powershell
.\scripts\run-9h-soak-test.ps1 -Rate 200 -Workers 8 -MaxVus 2000
```

同一个脚本支持任意 k6 时长。运行 24 小时全模块长稳压测：

```powershell
.\scripts\run-9h-soak-test.ps1 -Duration 24h -Rate 100 -Workers 4 -MaxVus 1000
```

该命令会先做 20 秒混合冒烟和测试切片装配检查，然后连续压测 24 小时。请保持 Docker Desktop 和当前 PowerShell 窗口运行；结果保存在 `tests_performance/results/`。第一次长测建议使用默认 100 RPS，确认 CPU、内存和 `dropped_iterations` 后再增加 `Rate`，否则压到负载机极限并不能代表服务容量。

混合模型覆盖 Controller、Gateway、Bean Validation、缓存、CSV、JPA 乐观锁、条件注解、Spring Data 分页与 Specification、`@DS/@Master/@Slave`、事务事件阶段、嵌套配置绑定与校验、i18n、Actuator，以及真实 WebSocket 和消息注解链路。

`SpringBootTest`、`WebMvcTest`、`DataJpaTest` 属于测试启动成本，不进入 9 小时请求热路径，使用独立装配基准：

```powershell
.\scripts\run-test-slice-benchmark.ps1 -Iterations 20 -P95Ms 1000
```

新增请求路径也都支持独立压测：`data`、`datasource`、`txevent`、`config`、`i18n`、`actuator`、`swagger`、`websocket`、`messaging`，通过 `run-load-test.ps1 -Workload <名称>` 选择。

`swagger` workload 会同时校验 `/openapi.json`、`/docs` 和 `/redoc`，并断言 OpenAPI 文档包含基准 Controller 的标签、`operationId`、响应描述和 Bearer 安全方案。

## AI、LangChain、LangGraph 和 MCP 压测

基准应用提供四条可以单独压测的路径。它们不是固定 JSON：每次请求都会进入相应框架的真实执行链。

- `ai`：执行 Spring AI `ChatClient` 和 `FakeChatModel`。
- `langchain`：执行 `@LangChainClient/@LangChainCall`、LangChain `LLMChain` 和 Spring 模型适配器。
- `langgraph`：执行由 `@LangGraph/@GraphNode/@GraphInvoke` 编译的真实 LangGraph 工作流。
- `mcp`：通过官方 MCP SDK 的进程内 Client/Server 会话调用 `@MCPTool`。

默认使用 Fake 模型，完全不访问外网，也不会产生模型费用。它测量的是框架调度、注解代理、序列化、线程切换和协议开销，不代表 OpenAI、Ollama 等真实模型的吞吐量。真实模型受供应商配额、网络和 Token 数影响，应使用 `custom` workload 指向隔离测试环境，并设置费用上限。

第一次运行先分别做 20 秒冒烟：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke -Workload ai
.\scripts\run-load-test.ps1 -Profile smoke -Workload langchain
.\scripts\run-load-test.ps1 -Profile smoke -Workload langgraph
.\scripts\run-load-test.ps1 -Profile smoke -Workload mcp
```

四个 workload 已加入 `mixed`，因此下面命令会连同 Web、数据库抽象、Swagger、WebSocket 等功能一起持续 9 小时：

```powershell
.\scripts\run-9h-soak-test.ps1 -Rate 100 -Workers 4 -MaxVus 1000
```

长测结束后重点检查四个 endpoint 标签的 p95、错误率、`dropped_iterations`，同时查看应用容器内存是否持续增长。MCP 压测会复用长生命周期会话，并在 worker 关闭时主动回收后台事件循环。
