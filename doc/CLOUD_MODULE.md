# SpringBootAI Cloud 模块使用指南

> 对齐 Spring Cloud Alibaba：服务注册发现 / 配置中心动态刷新 / Feign 远程调用 / Sentinel 限流熔断 / Gateway / 负载均衡 / 分布式事务。
> 本文档从 README.md 第 5.10 节（Cloud 注解）与第 14.3 节（功能说明）分离而来。
> 框架版本：SpringBootAI 1.8.2

---

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

**注意事项**：`value` 值必须和目标服务的 `spring.application.name` 完全一致；目标服务有 context-path 时通过 `path` 属性指定。**不兼容 Java interface proxy**，需显式使用 `spring.cloud.feign` 中的客户端工厂。

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

gateway = GatewayRouter(discovery_client=nacos_discovery)
gateway.route("/api/users/**", "user-service", strip_prefix=True)
```

内嵌轻量 ASGI/WSGI 网关，支持路由转发、路径重写、过滤器链、负载均衡；复杂网关需求可使用 Kong/APISIX 等专业网关。

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

**注意事项**：只在事务发起入口方法添加，参与方不需要；不支持嵌套事务；所有异常都会触发回滚；禁止在异步线程中使用（事务上下文无法传递）。

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

**仍存在的架构限制**：

- `http` 模式的事务协调器运行在**应用进程内**（元数据持久化到本地 SQLite），通过 HTTP 端点通知分支提交/回滚，依赖**幂等回调**完成最终一致。
- 它**不具备** Seata AT 的全局锁、undo_log 回滚、分支资源代理等强一致性语义。
- 因此**不能据此宣称**支付、订单、库存等场景具备**企业级分布式一致性**。

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

**代码实现位置**：[`spring/cloud/seata.py`](../spring/cloud/seata.py) — `SeataTransactionManager` 三模式实现；持久化存储 [`spring/cloud/transaction_store.py`](../spring/cloud/transaction_store.py)。
