# SpringBootAI Cloud 模块使用指南

> 对齐 Spring Cloud Alibaba：服务注册发现 / 配置中心动态刷新 / Feign 远程调用 / Sentinel 限流熔断 / Gateway / 负载均衡 / 分布式事务。
> 本文档从 README.md 第 5.10 节（Cloud 注解）与第 14.3 节（功能说明）分离而来。
> 框架版本：SpringBootAI 1.8.3

---

## 零、新手先读

### 0.1 Cloud 模块解决什么问题

当一个应用拆成多个服务后，需要知道“服务在哪里”、调用失败怎么办、流量过大怎么办，以及如何统一入口。Cloud 模块提供这些基础能力，但不是所有项目都需要微服务。一个小型内部系统优先做成单体，通常更容易开发和运维。

### 0.2 常见名词的大白话解释

| 名词 | 作用 | 类比 |
|---|---|---|
| Nacos 服务发现 | 记录每个服务的 IP 和端口 | 通讯录 |
| Feign | 用统一客户端调用其他 HTTP 服务 | 电话 |
| LoadBalancer | 多个实例中选择一个 | 分配接线员 |
| Sentinel | 限流、熔断和降级 | 保险丝 |
| Gateway | 对外统一入口并转发到内部服务 | 总机 |
| Trace | 给跨服务请求添加同一个链路编号 | 快递单号 |
| Seata / 补偿事务 | 协调多个服务的提交或补偿 | 跨部门流程单 |

### 0.3 应该按什么顺序学习

1. 先用固定 `url` 跑通 Feign 调用。
2. 再启动 Nacos，把固定 URL 改成服务名发现。
3. 为远程调用增加超时、Fallback 和 Sentinel。
4. 有统一入口需求时再部署 Gateway。
5. 最后才处理分布式事务；支付、订单、库存强一致必须使用真实协调器。

### 0.4 最小 Nacos 配置

```yaml
discovery:
  enabled: true
  server_addr: 127.0.0.1:8848
  namespace: ""
  group: DEFAULT_GROUP
  username: nacos
  password: nacos
```

还需要安装客户端：

```powershell
python -m pip install "springbootAI[nacos]"
```

验证时不要只看应用启动日志。还应打开 Nacos 控制台，确认服务名、实例 IP、端口和健康状态正确，并停止一个实例验证它会被摘除。

## 一、注解参考

#### @EnableDiscoveryClient

**参数**：`client_type`（str，默认 "nacos"，nacos/eureka/consul）

```python
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableDiscoveryClient

@SpringBootApplication
@EnableDiscoveryClient(client_type="nacos")
class Application:
    pass
```

**边界**：注解提供发现元数据；实际初始化由 `discovery.enabled` 和 `ApplicationContext` 启动流程控制。Nacos 需要安装 `nacos-sdk-python`，并配置 `NACOS_SERVER`、`NACOS_USERNAME`、`NACOS_PASSWORD`；Nacos 2.2+ Docker 还需要服务端 `NACOS_AUTH_TOKEN`、`NACOS_AUTH_IDENTITY_KEY` 和 `NACOS_AUTH_IDENTITY_VALUE`。

#### @NacosValue

**参数**：`value`（str，必填，如 `"${user.name}"`）、`auto_refreshed`（bool，默认 False）

```python
from spring.annotations import Service
from spring.annotations.cloud import NacosValue

@Service
class ConfigService:
    @NacosValue(value="${app.version}", auto_refreshed=True)
    def get_version(self):
        return self._app_version
```

**边界**：与 `@Value` 的区别是支持 `auto_refreshed` 动态刷新；基础类型效果最好，复杂实体类推荐用 `@ConfigurationProperties`。

#### @RefreshScope

**含义**：配置刷新作用域，添加此注解的类在配置变更时会重新创建实例。**参数**：无。

```python
from spring.annotations import Service
from spring.annotations.cloud import RefreshScope

@Service
@RefreshScope
class DynamicConfigService:
    def __init__(self):
        self.feature_flag = True
        self.timeout = 30
```

**触发刷新**：

```python
from spring.aop.cloud_aop import trigger_config_refresh

trigger_config_refresh()
```

**注意事项**：不能标注在 `@Controller` 上，会导致请求参数解析异常；动态配置读取建议放在 Service 层；会创建代理类，存在循环依赖的 Bean 会启动失败。

#### @EnableFeignClients

**参数**：`base_packages`（List[str]，默认 None，默认扫描启动类同包）

```python
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableFeignClients

@SpringBootApplication
@EnableFeignClients(base_packages=["com.example.feign"])
class Application:
    pass
```

#### @FeignClient

**参数**：`value`（str，必填，目标服务名）、`path`（str，默认 ""）、`fallback`（Type，默认 None）、`fallback_factory`（Type，默认 None）、`url`（str，默认 ""，调试用）

```python
from spring.annotations.cloud import FeignClient
from spring.annotations import GetMapping, PostMapping

@FeignClient(value="user-service", path="/api")
class UserFeign:
    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        pass  # 由 Feign 自动实现

    @PostMapping("/users")
    def create_user(self, name: str, email: str):
        pass
```

当前不会仅凭类声明自动创建 Java interface proxy，需要显式构建客户端：

```python
from spring.annotations.cloud import FeignClient
from spring.cloud.feign import create_declared_feign_client

annotation = next(
    item for item in UserFeign.__spring_annotations__
    if isinstance(item, FeignClient)
)
user_client = create_declared_feign_client(UserFeign, annotation)
user = user_client.get_user(1)
```

本地调试也可以跳过声明式接口：

```python
from spring.cloud.feign import create_feign_client

client = create_feign_client(
    "user-service",
    path="/api",
    url="http://127.0.0.1:8081",
    timeout=5,
)
user = client.get("/users/1")
client.close()
```

**注意事项**：`value` 必须和目标服务注册到 Nacos 的名称完全一致；目标服务有路径前缀时通过 `path` 指定。Feign 当前使用同步 `requests.Session`，在 async 业务方法中直接调用会阻塞事件循环，应使用同步 Service/Controller 的线程池路径或显式 `await asyncio.to_thread(...)`。生产环境必须设置超时并验证连接池耗尽和下游失败。

#### @SentinelResource

**参数**（内嵌引擎版）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | 资源名，为空时用类名.方法名 |
| block_handler | str | "" | 限流/熔断处理方法名 |
| fallback | str | "" | 业务异常降级方法名 |
| hotkey | str/bool | ""/False | 热点参数名（或是否启用热点参数限流） |
| exceptions_to_ignore | list | None | 忽略的异常类型列表 |

```python
from spring.annotations import Service
from spring.annotations.cloud import SentinelResource

@Service
class OrderService:
    @SentinelResource(value="create_order", fallback="create_order_fallback")
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}

    def create_order_fallback(self, user_id: str, product_id: str):
        return {"status": "degraded", "message": "系统繁忙，请稍后重试"}
```

**blockHandler vs fallback 区别**：**blockHandler** 处理 Sentinel 主动阻断（限流、系统保护、黑名单等）；**fallback** 处理业务异常、远程调用失败。降级/限流处理方法的返回值、参数列表必须和原方法完全一致。内嵌引擎支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流，无需 Sentinel Dashboard。

#### @EnableGateway

**参数**：无。仅网关模块启动类添加，业务服务禁止引入。配合 `GatewayRouter` 使用：

```python
from spring.cloud.gateway import GatewayRouter

gateway = GatewayRouter(timeout=5, max_body_size=10 * 1024 * 1024)
gateway.route(
    "/api/users/**",
    uri="http://127.0.0.1:8081",
    strip_prefix=True,
)
gateway.install(app, "/api/{path:path}")
```

`route()` 只添加路由规则，`install()` 才会把异步端点注册到 FastAPI 应用。上例使用固定 `uri`，最适合第一次验证；按服务名发现时传入的 discovery adapter 需要提供 `get_instances(service_id)` 并返回包含 `ip`、`port`、可选 `scheme` 的字典列表。不要直接把 `handle_asgi` 当成普通三参数 ASGI 函数注册。内嵌网关支持异步转发、路径重写、过滤器链和负载均衡；公网入口、复杂鉴权、WAF、灰度发布等需求应使用 Kong/APISIX 等专业网关。

#### @LoadBalanced

**参数**：无。只能标注在 `@Bean` 修饰的创建 RestTemplate 的方法上，不能标注在注入字段、类上。实际请求仍需配合框架负载均衡客户端。

#### @GlobalTransactional

**参数**：`timeout`（int，默认 60000，毫秒）、`name`（str，默认 ""）、`rollback_for`（List[Type]，默认 []）、`no_rollback_for`（List[Type]，默认 []）

```python
from spring.annotations import Service, Autowired
from spring.annotations.cloud import GlobalTransactional

@Service
class OrderService:
    @Autowired
    def __init__(self, inventory_feign, payment_feign):
        self.inventory_feign = inventory_feign
        self.payment_feign = payment_feign

    @GlobalTransactional(timeout=30000, name="create_order_tx")
    def create_order(self, user_id: str, product_id: str, amount: float):
        order = self.save_order(user_id, product_id, amount)
        self.inventory_feign.deduct(product_id, 1)   # 远程调用
        self.payment_feign.deduct(user_id, amount)   # 远程调用
        return order
```

**注意事项**：只在事务发起入口方法添加，参与方不需要重复开启全局事务；不支持嵌套。受管 `async def` 方法已经支持事务上下文隔离，协调器的同步 I/O 会移入线程池；但自己创建的裸线程、进程池或脱离当前任务的后台任务不会自动继承事务上下文。

---

## 二、功能说明

- **Sentinel 限流熔断**：通过 `@SentinelResource` 注解使用，支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流。
- **OpenTelemetry 追踪**：通过 `@Trace` 注解使用，自动生成并传播 W3C `traceparent` 标准 traceId/spanId，自动注入 HTTP 请求和 Feign 调用，追踪信息通过日志输出。
- **Seata 分布式事务（三模式）**：通过 `@GlobalTransactional` 注解使用，支持 `local`/`http`/`distributed` 三种模式。`distributed` 对接真实 Seata Server；`http` 为持久化补偿协调器（**非 AT 强一致性**，详见下文"架构限制与生产边界"）；Feign 客户端自动传播 XID。
- **API Gateway**：`@EnableGateway` + `GatewayRouter`，支持路由转发、路径重写、全局过滤器、负载均衡。
- **ORM DDL 自动建表**：`@entity` + `database.ddl-auto`（JPA ddl-auto 风格）。

```python
from spring.annotations import SentinelResource, Trace, GlobalTransactional

@SentinelResource(value="createOrder", block_handler="handle_block", fallback="handle_fallback")
def create_order(user_id: int, product_id: int):
    pass

@Trace("order-service.create")
def create_order_traced(user_id: int):
    pass

@GlobalTransactional(timeout=60000)
def place_order(user_id: int, product_id: int):
    order_service.create(user_id, product_id)
    inventory_service.deduct(product_id)
```

---

## 三、架构限制与生产边界

### HTTP 补偿模式 ≠ Seata AT 强一致性

> **已修复（文档披露）**：早期文档将 `http` 模式表述为"HTTP-AT 分布式事务"，该表述容易误导。现明确披露架构限制，避免被误读为具备企业级分布式一致性。

**HTTP 补偿模式当前实现**：

- 全局事务、分支、状态和回调 URL 持久化到 SQLite WAL，不再以进程内字典作为事实来源。
- 同一主机上的多个 worker 可以共享同一个 `store_path`；状态转换使用原子更新，避免两个 worker 同时完成同一事务。
- worker 启动后会周期扫描未完成事务；超时的 `BEGIN` 会回滚，崩溃留下的提交/回滚状态会在宽限期后接管。
- 仅注册 Python 本地函数的回调无法跨进程恢复。需要重启恢复的分支必须提供持久化的 HTTP `callback_url`，并保证提交/回滚接口幂等。
- 远端回调成功但本地确认落库前发生崩溃时，恢复器可能再次调用回调，因此接口必须接受重复请求并返回同一业务结果。
- 它**不具备** Seata AT 的全局锁、undo_log 回滚、分支资源代理等强一致性语义。
- 因此**不能据此宣称**支付、订单、库存等场景具备**企业级分布式一致性**。

最小配置（仅限补偿流程和企业试点，不会通过生产强一致校验）：

```yaml
seata:
  enabled: true
  mode: http
  http_compensation_enabled: true
  store_path: ./data/seata-http.sqlite3
  recover_on_startup: true
  recovery_grace_ms: 30000
  recovery_interval_s: 30
```

| 配置 | 作用 | 新手建议 |
|---|---|---|
| `store_path` | 保存协调状态的 SQLite 文件 | 使用绝对路径或持久化数据盘，同主机 worker 必须完全一致 |
| `recover_on_startup` | 启动时扫描未完成事务 | 保持 `true` |
| `recovery_grace_ms` | 接管疑似死亡 worker 前等待多久 | 大于一次回调的最大正常耗时 |
| `recovery_interval_s` | 运行期间多久扫描一次 | 30 秒起步，按业务恢复目标调整 |

验证补偿模式至少要覆盖：正常提交、业务异常回滚、远端 500、回调超时、重复回调、杀死 worker 后恢复，以及 SQLite 文件不可写时启动失败。

**生产场景选型**：

| 场景 | 推荐模式 | 说明 |
|------|---------|------|
| 开发调试 / 单服务事务追踪 | `local` | 仅追踪事务上下文，无跨服务协调 |
| 故障演练 / 补偿流程验证 | `http` | 持久化补偿，支持重启恢复，**非强一致** |
| **生产强一致（支付/订单/库存）** | `distributed` | 必须部署真实 Seata Server + 兼容 Python SDK |

`distributed` 模式要求：

1. 部署 Seata Server（https://seata.io）
2. 安装与本适配层 API 兼容的企业 Seata Python SDK
3. 配置 `registry.conf` / `file.conf`，创建 `seata_undo_log` 表
4. 启动时设置 `SEATA_ENABLED=true`、`seata.mode=distributed`

> ⚠️ `distributed` 模式未检测到兼容 SDK 时**失败关闭**（不静默降级到 `local`），避免核心业务在无强一致保障下继续运行。

### HTTP 持久化补偿配置（v1.8.2 落地）

`http` 模式在 v1.8.2 兑现了"持久化补偿协调器"的承诺：事务/分支元数据落盘到 SQLite（WAL 模式），支持重启恢复、幂等提交、过期分支回滚、并发 commit 单次 claim 与 `PARTIAL_COMMIT`/`PARTIAL_ROLLBACK` 失败关闭。**但架构限制不变**——协调器仍运行在应用进程内，不具备 Seata AT 全局锁/undo_log 回滚/分支资源代理等强一致性语义。

```yaml
seata:
  enabled: ${SEATA_ENABLED:false}
  mode: ${SEATA_MODE:local}            # local | http | distributed
  http_compensation_enabled: ${SEATA_HTTP_COMPENSATION_ENABLED:false}  # http 模式必须显式 opt-in
  store_path: ${SEATA_HTTP_STORE_PATH:./data/seata-http.sqlite3}       # SQLite 路径
  recover_on_startup: ${SEATA_HTTP_RECOVER_ON_STARTUP:true}            # 启动时恢复未完成事务
  recovery_grace_ms: ${SEATA_HTTP_RECOVERY_GRACE_MS:30000}             # 完成 lease 宽限期
  recovery_interval_s: ${SEATA_HTTP_RECOVERY_INTERVAL_S:30}            # recovery worker 轮询间隔
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `http_compensation_enabled` | `false` | `mode=http` 时必须显式设为 `true`，否则 `init_seata` 抛 `ValueError`（失败关闭，防误用） |
| `store_path` | `./data/seata-http.sqlite3` | SQLite 文件路径；跨主机部署须指向共享事务数据库或改用 `distributed` |
| `recover_on_startup` | `true` | 启动时调用 `recover_pending_transactions`，提交 BEGIN 态过期事务的回滚 |
| `recovery_grace_ms` | `30000` | COMMITTING/ROLLING_BACK 的完成 lease 宽限期，超时后可被 reclaim |
| `recovery_interval_s` | `30` | 后台 recovery worker 轮询间隔 |

**运行时行为**：
- `SpringApplication` 启动时若 `seata.mode=http` 则启动 recovery worker，关闭时停止。
- `/actuator/health` 的 seata 探针在 http 模式下返回 `UP` + `warning: Persistent compensation only; no Seata AT consistency` + `active_global_tx`/`active_branches` 计数 + `store_path`（不再虚报 DOWN）。
- `@GlobalTransactional` 异步路径用 `asyncio.to_thread` 包装 SQLite 阻塞操作，避免事件循环阻塞。
- 兼容旧配置项 `experimental_http_enabled`（作为 `http_compensation_enabled` 的 fallback）。

> ⚠️ **再次强调**：上述持久化能力仅保证协调器元数据不丢、重启可恢复、补偿幂等，**仍不等于企业级分布式一致性**。支付/订单/库存等核心业务强一致场景必须使用 `distributed` 模式对接真实 Seata Server，或采用可靠消息最终一致方案。

**代码实现位置**：[`spring/cloud/seata.py`](../spring/cloud/seata.py) — `SeataTransactionManager` 三模式实现；持久化存储 [`spring/cloud/transaction_store.py`](../spring/cloud/transaction_store.py) — `SQLiteTransactionStore`（WAL + 原子状态迁移 + 外键级联）。
