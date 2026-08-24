# SpringBootAI Cloud 模块 —— 小白也能看懂的微服务指南

> SpringBootAI 2.3.8

---

## 什么时候需要微服务？

**如果你的系统不超过 1000 个用户，你大概率不需要微服务。先看完这段再决定是否继续。**

### 你遇到了什么问题？

你的单体应用越来越庞大，某个模块挂了整个系统都崩；或者某个功能访问量特别大，其他功能也被拖慢。你想拆分成多个独立的小应用，但不知道从哪下手。

### 一句话大白话

**微服务就是把一个大应用拆成多个小应用，每个小应用只专注做一件事。** 就像一家公司：不是所有人挤在一个办公室干所有活，而是分成销售部、财务部、仓库——每个部门各司其职，通过内部电话沟通。

拆分之后，新问题来了：部门之间怎么找到对方？（服务注册发现）一个部门瘫痪了怎么办？（熔断降级）来访的人太多怎么分流？（网关和限流）——这就是 Cloud 模块要解决的。

### 新手选型指南

**你可能不需要微服务，如果：**

- 项目是小型内部系统，用户量在几百人以内
- 团队只有 2-3 个开发者
- 没有独立部署不同模块的需求
- 单体应用跑得好好的

> 结论：**先做单体，跑起来再说。** 单体应用更容易开发、调试、部署。

**你应该考虑微服务，如果：**

- 不同模块需要独立部署（比如订单模块频繁更新，但用户模块很少变）
- 某个模块需要单独扩容（比如秒杀时只给订单服务加机器）
- 多个团队各自维护不同的服务

### 学习路线

1. 先用固定 URL 跑通 Feign 调用
2. 再启动 Nacos，把固定 URL 改成服务名发现
3. 为远程调用增加超时、Fallback 和 Sentinel
4. 有统一入口需求时再部署 Gateway
5. 最后才处理分布式事务

---

## 名词速查表

| 名词 | 一句话大白话 | 生活类比 |
|---|---|---|
| Nacos 服务发现 | 自动签到系统——新员工入职自动登记，找人时查通讯录就行 | 公司内部通讯录 |
| Nacos 配置中心 | 总控制台——改一处配置，所有门店自动调价 | 连锁店总部调价系统 |
| Feign | 打电话叫外卖——你不用自己跑到餐厅，电话里说就行 | 打电话叫外卖 |
| LoadBalancer | 排队分流——哪个窗口空着去哪个 | 银行叫号系统 |
| Sentinel | 水库大坝——控制流量，防止系统被冲垮 | 三峡大坝 |
| Gateway | 公司前台——所有访客先到前台，前台根据来意分派到不同部门 | 公司大堂前台 |
| Seata | 跨国转账——需要确保两边银行的账都对得上 | 国际汇款 |
| Trace | 快递单号——跟踪一个包裹经过的所有中转站 | 快递追踪 |

---

## 一、Nacos 服务注册 —— 自动签到系统

### 你遇到了什么问题？

你的用户服务跑在 `192.168.1.10:8081`，订单服务跑在 `192.168.1.20:8082`。订单服务要调用用户服务，你得把地址写死在代码里。哪天用户服务换了一台机器，你就得改代码重新部署——太蠢了。

### ① 是什么

**服务注册就像是自动签到系统。** 每天早上员工刷卡签到，公司系统就知道谁来了、坐在哪个工位。Nacos 就是这个签到系统——每个服务启动时自动"签到"（注册），其他服务要找人时查一下通讯录（服务发现）就知道对方在哪里。

### ② 怎么用

先用 pip 安装 Nacos 客户端：

```powershell
python -m pip install "springbootAI[nacos]"
```

在 `application.yml` 中配置：

```yaml
# Nacos 最小配置 —— 照着填就行
discovery:
  enabled: true                    # 开启服务注册发现
  server_addr: 127.0.0.1:8848     # Nacos 服务器地址（默认端口 8848）
  namespace: ""                    # 命名空间，留空用默认
  group: DEFAULT_GROUP             # 分组名称
  username: nacos                  # 用户名
  password: nacos                  # 密码
  timeout: 3                       # 每个 SDK HTTP 请求的超时（秒），服务离线时快速降级
```

`discovery` 是可选模块，默认 `enabled: false`。开启后仍不会无限等待：默认每个
Nacos 请求最多等待 3 秒（支持 `NACOS_TIMEOUT`、`DISCOVERY_TIMEOUT` 或同名 Nacos
配置覆盖，合法范围为大于 0 且不超过 60 秒）。认证失败、服务离线等错误会按
`startup.fail_fast` 配置处理；关闭模块时框架不会创建 Nacos 客户端。

Spring Cloud Config 同样是可选模块。配置中心的 timeout、重试次数、间隔和乘数会
在框架边界内规范化（至少尝试一次，重试间隔最多 60 秒）；YAML 层级为空或类型错误
时回退到安全默认值，不会因可选配置中心配置错误阻断应用启动。

在启动类上加注解：

```python
from springbootai.annotations import SpringBootApplication
from springbootai.annotations.cloud import EnableDiscoveryClient

@SpringBootApplication
@EnableDiscoveryClient(client_type="nacos")  # 开启"自动签到"功能
class Application:
    pass
```

### ③ 运行结果

应用启动后会自动向 Nacos 注册自己的 IP 和端口。打开 Nacos 控制台（http://127.0.0.1:8848/nacos），你能看到自己的服务已经出现在服务列表里了。停止应用后，服务会自动从列表中消失。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 多个服务之间需要互相调用 | 只有一个服务，没有调用需求 |
| 服务可能会换机器、换端口 | 服务地址永远不会变 |
| 服务实例数量动态变化 | 用固定 IP+端口就够了 |

---

## 二、Nacos 配置中心 —— 总控制台

### 你遇到了什么问题？

你把数据库密码、第三方 API 密钥写在了 `application.yml` 里。有一天数据库密码改了，你不得不改配置文件、重新打包、重新部署所有服务——改了 10 个服务，搞了一下午。

### ① 是什么

**配置中心就像是连锁店的总部调价系统。** 以前每家店各自定价，改一个价格要打 100 个电话。有了总部调价系统，在总部改一次，所有门店自动更新。Nacos 配置中心就是这个"总部系统"——在 Nacos 上改配置，所有服务自动生效，不用重启。

### ② 怎么用

先安装 Nacos 客户端：

```powershell
python -m pip install "springbootAI[nacos]"
```

在 Nacos 控制台创建 `welding-dev.yml`，内容就是普通应用 YAML。例如：

```yaml
spring:
  application:
    name: welding-app
server:
  port: 8090
jwt:
  expires_in: 28800
database:
  enabled: true
  driver: sqlite
  database: ./runtime/welding.db
management:
  admin:
    # 该配置由框架内置读取，不需要项目自己实现监控 Controller 或拦截器。
    request-metrics:
      enabled: true
      include-paths: ["/api/**"]
```

本地无需保存业务 `application.yml`。部署时只提供 Nacos 的引导环境变量：

```powershell
$env:NACOS_CONFIG_ENABLED = "true"
$env:NACOS_CONFIG_SERVER_ADDR = "127.0.0.1:8848"
$env:NACOS_CONFIG_DATA_ID = "welding-dev.yml"
$env:NACOS_CONFIG_GROUP = "DEFAULT_GROUP"
$env:NACOS_CONFIG_NAMESPACE = ""
$env:NACOS_CONFIG_FAIL_FAST = "true"
python -m welding_app.Application
```

也可以把这些最小引导信息放进本地 YAML（业务配置仍放 Nacos）：

```yaml
spring:
  cloud:
    nacos:
      config:
        enabled: true
        server-addr: 127.0.0.1:8848
        data-id: welding-dev.yml
        group: DEFAULT_GROUP
        namespace: ""
        fail-fast: true
        refresh-enabled: true
        refresh-interval-seconds: 5
```

`timeout-ms` 的有效范围为 1-120000（默认 5000），`refresh-interval-seconds`
的有效范围为 1-3600（默认 5）。超过上限时框架自动收敛到安全上限，避免
错误配置导致启动、热刷新或关闭流程长时间阻塞。

Nacos YAML 覆盖本地同名项；环境变量和命令行参数优先级更高。例如可通过
`MANAGEMENT_ADMIN_REQUEST_METRICS_ENABLED=true` 和
`MANAGEMENT_ADMIN_REQUEST_METRICS_INCLUDE_PATHS=/api/**` 覆盖上面的 Nacos 管理面板配置。
远程配置不存在或
无法连接时，`fail-fast: true` 会拒绝启动；为 `false` 时应用继续使用本地配置和框架默认值。

读取动态值使用字段注解：

```python
from springbootai.annotations import Service
from springbootai.annotations.cloud import NacosValue

@Service
class ConfigService:
    app_version = NacosValue("${app.version:unknown}", auto_refreshed=True)
```

如果整个类都需要动态配置，用 `@RefreshScope`：

```python
from springbootai.annotations import Service
from springbootai.annotations.cloud import RefreshScope

@Service
@RefreshScope  # 贴上"可刷新"标签
class DynamicConfigService:
    def __init__(self):
        # Nacos 配置刷新后，框架会重新绑定配置字段
        self.feature_flag = True
        self.timeout = 30
```

框架会启动一个可控的后台轮询监听器自动检查 Nacos 配置变更（Windows、Docker
和不同 SDK 版本下都可正常停止）。手动触发刷新仅用于测试或自定义流程：

```python
from springbootai.aop.cloud_aop import trigger_config_refresh

trigger_config_refresh()  # 触发一次配置刷新，所有 @RefreshScope 的 Bean 重新创建
```

### ③ 运行结果

在 Nacos 控制台把 `app.version` 从 `1.0` 改成 `2.0`，应用无需重启；
`@NacosValue(auto_refreshed=True)` 与 `@RefreshScope` Bean 会在配置刷新后获得新值。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 配置经常变动（开关、阈值、地址） | 配置几年不变 |
| 多个服务共享同一份配置 | 每个服务配置完全不同 |
| 不想重启就能改配置 | 不介意重启 |

---

## 三、Feign —— 打电话叫外卖

### 你遇到了什么问题？

订单服务要调用用户服务查用户信息。你要手写 HTTP 请求：拼 URL、设请求头、解析响应、处理超时、处理异常……每次调用都要写几十行代码，烦死了。

### ① 是什么

**Feign 就像打电话叫外卖——你不用自己跑到餐厅，也不用亲自下厨，打个电话说你要什么，外卖就送到你面前。** Feign 让你像调用本地方法一样调用远程 HTTP 服务，框架帮你搞定网络通信。

### ② 怎么用

先开启 Feign 扫描：

```python
from springbootai.annotations import SpringBootApplication
from springbootai.annotations.cloud import EnableFeignClients

@SpringBootApplication
@EnableFeignClients(base_packages=["com.example.feign"])  # 扫描这个包下的 Feign 接口
class Application:
    pass
```

声明远程调用接口：

```python
from springbootai.annotations.cloud import FeignClient
from springbootai.annotations import GetMapping, PostMapping

@FeignClient(value="user-service", path="/api")  # 目标服务名是 user-service
class UserFeign:
    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        pass  # 框架自动帮你实现网络请求

    @PostMapping("/users")
    def create_user(self, name: str, email: str):
        pass
```

构建客户端并调用：

```python
from springbootai.annotations.cloud import FeignClient
from springbootai.cloud.feign import create_declared_feign_client

# 从注解元数据构造客户端
annotation = next(
    item for item in UserFeign.__spring_annotations__
    if isinstance(item, FeignClient)
)
user_client = create_declared_feign_client(UserFeign, annotation)

# 像调本地方法一样调远程服务
user = user_client.get_user(1)
print(user)  # 输出: {"id": 1, "name": "张三", "email": "zhangsan@example.com"}
```

本地调试时可以跳过声明式接口，直接指定 URL：

```python
from springbootai.cloud.feign import create_feign_client

# url 参数直接指定目标地址，不经过 Nacos
client = create_feign_client(
    "user-service",
    path="/api",
    url="http://127.0.0.1:8081",  # 直接指定地址
    timeout=5,                     # 超时 5 秒
)
user = client.get("/users/1")
client.close()
# 输出: {"id": 1, "name": "张三"}
```

### ③ 运行结果

调用 `user_client.get_user(1)` 时，Feign 自动向 `http://user-service/api/users/1` 发起 GET 请求，把 JSON 响应解析成字典返回。你完全不用关心 HTTP 细节。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 服务之间需要 HTTP 调用 | 不需要跨服务调用 |
| 想用声明式写法代替手写 HTTP 代码 | 需要高度自定义的 HTTP 请求 |
| 结合 Nacos 做服务发现 | 单服务架构 |

---

## 四、LoadBalancer —— 排队分流

### 你遇到了什么问题？

你的用户服务部署了 3 台机器：`192.168.1.10:8081`、`192.168.1.11:8081`、`192.168.1.12:8081`。请求来了该发给哪台？总不能随便选或者手动轮换吧？

### ① 是什么

**负载均衡就像是排队分流——银行有 3 个窗口，你拿号之后系统自动分配你去当前空闲的窗口。** LoadBalancer 从服务的多个实例中自动选一个来处理请求，让每台机器压力均匀。

### ② 怎么用

配合 Feign 使用，只要目标服务在 Nacos 注册了多个实例，Feign 调用时自动负载均衡。不需要额外代码。

在需要自己控制 HTTP 客户端时，可以用 `@LoadBalanced` 注解：

```python
# @LoadBalanced 给 HTTP 客户端加上负载均衡能力
# 标注在 @Bean 方法上，不能标注在字段或类上
```

### ③ 运行结果

当用户服务有 3 个实例时，Feign 发起的请求会自动分散到 3 个实例上，不会全打到同一台机器。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 一个服务部署了多个实例 | 每种服务只有一个实例 |
| 需要分散请求压力 | 用 Nginx/Kong 等外部负载均衡器就行 |

---

## 五、Sentinel —— 水库大坝

### 你遇到了什么问题？

秒杀活动来了，瞬间涌进来 10 万个请求，你的订单服务扛不住直接 OOM 崩溃。或者库存服务挂了，但订单服务还在不断调用它，导致订单服务也被拖死——一个服务挂了，像多米诺骨牌一样全倒了。

### ① 是什么

**Sentinel 就像是水库大坝。** 洪水来了，大坝控制放水量，保护下游不被冲垮；下游出问题，大坝关闸断流，防止连带破坏。Sentinel 三个核心能力：

- **限流**：每秒只放行 100 个请求，超过的直接拒绝——就像大坝控制放水量
- **熔断**：下游服务错误率超过 50%，自动"切断电路"不再调用它——就像保险丝熔断
- **降级**：熔断后给一个兜底响应，比如"系统繁忙请稍后重试"——就像断电后用应急灯

### ② 怎么用

```python
from springbootai.annotations import Service
from springbootai.annotations.cloud import SentinelResource

@Service
class OrderService:
    @SentinelResource(
        value="create_order",                  # 资源名
        fallback="create_order_fallback"       # 出问题时的兜底方法
    )
    def create_order(self, user_id: str, product_id: str):
        # 正常逻辑：创建订单
        return {"order_id": "ORD_123", "status": "success"}

    def create_order_fallback(self, user_id: str, product_id: str):
        # 兜底逻辑：系统繁忙时返回友好提示
        return {"status": "degraded", "message": "系统繁忙，请稍后重试"}

# 结果：
# 正常时调用 create_order → {"order_id": "ORD_123", "status": "success"}
# 限流或异常时自动调用 create_order_fallback → {"status": "degraded", "message": "系统繁忙，请稍后重试"}
```

两个关键概念的区别：

| 概念 | 什么时候触发 | 干什么用 |
|---|---|---|
| `block_handler` | 被限流/熔断主动阻断 | 处理"请稍后重试"的提示 |
| `fallback` | 业务逻辑抛异常 | 处理"服务暂时不可用"的兜底 |

### ③ 运行结果

配置 QPS 限制为每秒 10 次后，当第 11 个请求到达时，不会进入 `create_order` 方法，直接返回 `create_order_fallback` 的结果。用户看到的是友好的"系统繁忙"提示，而不是报错页面。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 接口可能被突发流量打垮 | 流量非常稳定且远低于系统容量 |
| 下游服务不稳定需要熔断保护 | 不依赖任何外部服务 |
| 秒杀、抢购等高并发场景 | 内部定时任务之类的后台服务 |

---

## 六、Gateway —— 公司前台

### 你遇到了什么问题？

你的系统有 10 个微服务，每个都有自己的地址和端口。前端要记住 10 个地址，而且每个服务都要各自处理跨域、鉴权、限流——代码重复到爆炸。外部用户直接访问内部服务也不安全。

### ① 是什么

**Gateway 就像是公司前台——所有访客必须先到前台登记，前台根据来意把你分派到相应的部门。** 前台统一处理签到、安全检查、引导分流。Gateway 就是你的 API 前台：

- 所有外部请求统一从网关进来
- 网关根据路径转发到对应的内部服务
- 在网关统一做鉴权、限流、日志

### ② 怎么用

在启动类开启网关：

```python
from springbootai.annotations import SpringBootApplication
from springbootai.annotations.cloud import EnableGateway

@SpringBootApplication
@EnableGateway  # 开启"公司前台"功能
class GatewayApplication:
    pass
```

配置路由规则：

```python
from springbootai.cloud.gateway import GatewayRouter

# 创建网关路由器
gateway = GatewayRouter(timeout=5, max_body_size=10 * 1024 * 1024)  # 超时5秒，最大请求体10MB

# 添加路由：/api/users/** 开头的请求转发到用户服务
gateway.route(
    "/api/users/**",                         # 匹配这个路径
    uri="http://127.0.0.1:8081",             # 转发到这个地址
    strip_prefix=True,                       # 去掉 /api/users 前缀
)

# 添加路由：/api/orders/** 开头的请求转发到订单服务
gateway.route(
    "/api/orders/**",
    uri="http://127.0.0.1:8082",
    strip_prefix=True,
)

# 安装到 FastAPI 应用
gateway.install(app, "/api/{path:path}")

# 结果：
# 用户访问 http://网关地址/api/users/profile
# → 网关转发到 http://127.0.0.1:8081/profile
# 用户访问 http://网关地址/api/orders/list
# → 网关转发到 http://127.0.0.1:8082/list
```

### ③ 运行结果

前端只需要知道网关地址，所有请求都走网关。网关负责转发到正确的服务，前端不用管后面有几个服务、地址是什么。

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 有多个微服务需要统一入口 | 只有一个服务 |
| 需要在入口统一鉴权、日志、限流 | 内部微服务之间的调用 |
| 前端需要对接多个后端服务 | 用 Nginx/Kong 已经解决了问题 |

> **注意**：框架内嵌网关适合内部微服务路由。公网入口、HTTPS 证书管理、WAF 防火墙等需求，建议用 Nginx 或 Kong 等专业网关。

---

## 七、Seata 分布式事务 —— 跨国转账

### 你遇到了什么问题？

用户下单涉及三个操作：① 订单服务创建订单、② 库存服务扣库存、③ 支付服务扣款。前两步成功了，第三步扣款失败——但库存已经扣了，用户钱没扣，老板哭了。

### ① 是什么

**分布式事务像一张跨服务的操作单。** 协调器记录这张单据由哪些服务参与，并通知每个参与者确认或撤销。它比本地数据库事务复杂：网络可能中断，回调可能重复，服务也可能在任意阶段重启，因此业务代码必须设计幂等和恢复逻辑。

Seata 就是负责跨多个服务协调事务的：

- **local 模式**：只做事务追踪，不做跨服务协调。开发调试用。
- **http 模式**：持久化补偿协调。服务挂了重启后能恢复未完成的事务。**但它不具备强一致性**——就像发微信让对方确认，你发了但对方可能没收到。
- **distributed 模式**：通过仓库提供的 Java bridge 对接真实 Seata Server，Python 业务分支使用 TCC 的 prepare/commit/rollback 回调。它具备真实 XID、TC 协调和 TCC fence。
- **at 模式**：通过 ORM 拦截器自动记录 SQL 的 before/after image，生成 undo_log，全局事务回滚时自动反向恢复数据。不需要 Java bridge，适合单服务多表事务回滚。详见 [AT 模式使用指南](#at-模式使用指南)。

### ② 怎么用

```python
from springbootai.annotations import Service, Autowired
from springbootai.annotations.cloud import GlobalTransactional

@Service
class OrderService:
    @Autowired
    def __init__(self, inventory_feign, payment_feign):
        self.inventory_feign = inventory_feign  # 库存服务的 Feign 客户端
        self.payment_feign = payment_feign      # 支付服务的 Feign 客户端

    @GlobalTransactional(timeout=30000, name="create_order_tx")  # 30 秒超时
    def create_order(self, user_id: str, product_id: str, amount: float):
        # 第 1 步：保存订单
        order = self.save_order(user_id, product_id, amount)

        # 第 2 步：远程调用库存服务扣库存
        self.inventory_feign.deduct(product_id, 1)

        # 第 3 步：远程调用支付服务扣款
        self.payment_feign.deduct(user_id, amount)

        return order
```

上面的写法只演示事务入口，**不会自动把普通 Feign 调用变成可回滚操作**。库存和支付服务必须在收到 XID 后调用 `register_branch(...)`，并提供持久化的 prepare/commit/rollback HTTP 端点。prepare 只做资源预留，commit 确认资源，rollback 释放资源；三者都要使用业务幂等键。

`distributed` 最小配置：

```yaml
seata:
  enabled: true
  mode: distributed
  application_id: order-service
  transaction_group: springpy_tx_group
  bridge_url: http://127.0.0.1:18091
  bridge_token: ${SEATA_BRIDGE_TOKEN}
  callback_allowed_hosts:
    - inventory.internal
    - payment.internal
```

业务分支注册示意：

```python
from springbootai.cloud.seata import seata_manager

branch_id = seata_manager.register_branch(
    xid=xid,
    branch_id=f"inventory-{order_id}",
    resource_id=f"inventory:{sku}",
    callback_url="http://inventory.internal/seata/branch",
    service_name="inventory-service",
    metadata={"order_id": order_id, "sku": sku, "quantity": quantity},
)
```

bridge 会依次调用：

```text
POST /seata/branch/{branch_id}/prepare
POST /seata/branch/{branch_id}/commit    # 全局提交时
POST /seata/branch/{branch_id}/rollback  # 全局回滚时
```

http 补偿模式配置：

```yaml
seata:
  enabled: true
  mode: http                           # 使用 http 补偿模式
  http_compensation_enabled: true      # 必须显式开启
  store_path: ./data/seata-http.sqlite3  # 协调器数据存储位置
  recover_on_startup: true             # 启动时恢复未完成事务
  recovery_grace_ms: 30000             # 宽限期 30 秒
  recovery_interval_s: 30              # 每 30 秒扫描一次
```

### ③ 运行结果

`@GlobalTransactional` 负责开始和结束全局事务，并传播 XID。只有显式注册的 TCC 分支才由 Seata 协调；普通 HTTP/Feign 调用不会被自动撤销。本仓库集成测试验证真实 Seata TC 的 begin、分支注册、prepare、commit 和 rollback，但业务表的资源预留与释放仍由业务服务负责。

### 什么时候用 / 什么时候不用

| 场景 | 用什么模式 | 为什么 |
|---|---|---|
| 开发调试 | `local` | 只在本地追踪事务，不做跨服务协调 |
| 非关键业务的补偿流程 | `http` | 能持久化和恢复，但不是强一致 |
| 单服务多表事务回滚 | `at` | ORM 拦截器自动记录 undo_log，回滚时自动恢复 |
| 支付/订单/库存等核心业务 | 经过业务验证的 TCC/Saga/Outbox | `distributed` 可提供 TCC 协调，但必须完成业务资源、幂等与故障验证 |

### ⚠️ 重要警告

**http 模式不等于强一致性。** distributed 模式失败时会拒绝静默降级，但 TCC 的最终正确性仍取决于业务 prepare/commit/rollback 是否持久化、幂等并正确处理空回滚和悬挂。没有这些实现和故障测试，不要把它用于支付、订单或库存核心链路。`at` 模式自动处理单表 undo，但不支持 JOIN、子查询和跨服务事务。

### AT 模式使用指南

#### ① 是什么

AT（Automatic Transaction）模式是 Seata 最常用的事务模式。它自动拦截 SQL，在执行前查询数据快照（before image），执行后查询新快照（after image），把两个快照存入 `undo_log` 表。全局事务回滚时，根据 undo_log 自动反向恢复数据。

**大白话**：就像你改文件前先备份一份，改错了用备份恢复。AT 模式自动帮你做"备份"和"恢复"。

#### ② 怎么用

```python
from springbootai.cloud.seata import seata_manager, SeataTransactionManager
from springbootai.cloud.seata_at_proxy import SeataATProxy

# 1. 设置 AT 模式
seata_manager.set_mode("at")

# 2. 在 SqlSession 上安装 AT 拦截器（框架启动时执行一次）
at_proxy = SeataATProxy(sql_session, seata_manager)
at_proxy.install()

# 3. 业务代码中开启全局事务
@GlobalTransactional
def transfer(from_id, to_id, amount):
    # UPDATE 和 DELETE 会自动记录 undo_log
    mapper.update_balance(from_id, -amount)
    mapper.update_balance(to_id, +amount)
    # 如果这里抛异常，undo_log 会自动恢复余额
```

#### ③ 工作流程

```
开启全局事务 (begin)
    │
    ▼
执行 UPDATE account SET balance=50 WHERE id=1
    │
    ├─ 1. 拦截器查询 before image: SELECT * FROM account WHERE id=1 → {id:1, balance:100}
    ├─ 2. 执行原 SQL: UPDATE account SET balance=50 WHERE id=1
    ├─ 3. 拦截器查询 after image: SELECT * FROM account WHERE id=1 → {id:1, balance:50}
    └─ 4. 存入 undo_log: before={balance:100}, after={balance:50}
    │
    ▼
全局事务回滚 (rollback)
    │
    └─ 读取 undo_log → 用 before image 恢复: UPDATE account SET balance=100 WHERE id=1
```

#### ④ 限制

- 仅支持单表 SQL（不支持 JOIN / 子查询）
- INSERT 的 undo 需要知道主键（不支持自增回填）
- WHERE 条件直接用于 before image 查询
- 仅在 `seata_manager.is_in_transaction()` 为 True 时生效

---

## 八、Trace —— 快递单号

### 你遇到了什么问题？

一个用户请求经过了 5 个微服务，某个环节出错了，你想查日志——每个服务都有自己的日志，你怎么把这些日志串起来找到完整调用链？

### ① 是什么

**Trace 就像是快递单号——包裹从发货到你手里，经过好几个中转站，你扫一下单号就知道全过程。** Trace 给每个请求生成一个全局唯一的 traceId，这个 traceId 在所有服务间传递，日志里带上它，你就能追踪整个调用链。

### ② 怎么用

```python
from springbootai.annotations import Trace

@Trace("order-service.create")  # 这个方法被追踪
def create_order_traced(user_id: int):
    # 你的业务逻辑
    pass
# 结果：日志中会带上 traceId，串联整个请求链路
```

### ③ 运行结果

查看日志时，同一个 traceId 的所有日志跨越多个服务串联在一起，你可以清楚看到请求从哪个服务进来、经过了哪些服务、在哪个环节出了问题。

---

## 九、新手常见错误 ❌/✅

| # | ❌ 错误做法 | ✅ 正确做法 |
|---|---|---|
| 1 | "微服务一定比单体好，所有项目都该用微服务" | 小项目用微服务反而增加复杂度。先做单体，等真的需要拆分时再加微服务 |
| 2 | "Nacos 配置改了，服务马上生效" | 只有加了 `auto_refreshed=True` 或 `@RefreshScope` 的配置才会自动刷新。普通的 `@Value` 不会刷新 |
| 3 | "Feign 调用和本地方法一模一样，不用处理错误" | Feign 调用要走网络，有超时、失败、重试等问题。必须配置 fallback 或超时处理 |
| 4 | "加了 `@SentinelResource` 就万事大吉" | 必须配置 fallback 方法，否则限流时客户端会收到异常而不是友好提示 |
| 5 | "加上 `@GlobalTransactional` 就和数据库事务一样" | 完全不同。必须注册 TCC 分支并实现持久化、幂等的三阶段业务回调；`http` 模式只是补偿 |
| 6 | "Gateway 可以替代 Nginx" | 框架内嵌网关适合内部微服务路由。公网入口、HTTPS、WAF 还是用 Nginx/Kong |

---

## 十、FAQ

### Q1：本地测试 Feign 一定要装 Nacos 吗？

不用。用 `url` 参数直接指定目标地址：

```python
client = create_feign_client("svc", url="http://127.0.0.1:8081")
```

### Q2：Feign 能在 async 方法里用吗？

Feign 底层用的是同步 `requests.Session`，在 `async def` 方法里直接调用会阻塞事件循环。需要在同步 Service/Controller 中使用，或用 `await asyncio.to_thread(...)` 包装。

### Q3：多服务调试太麻烦了，怎么简化？

先在一个进程里用单体模式开发。等业务逻辑稳定了，再按模块拆分成独立服务部署。

### Q4：`@RefreshScope` 能加在 Controller 上吗？

不能。会导致请求参数解析异常。动态配置读取建议放在 Service 层。

### Q5：事务中能切换数据源吗？

不能。一个事务只绑定一个数据库连接，事务中途切数据源不会生效。

### Q6：Sentinel 一定要装 Dashboard 吗？

不用。内嵌引擎支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流，无需 Sentinel Dashboard。

---

## 附录：架构限制说明

### HTTP 补偿模式 ≠ 强一致性

http 模式的持久化能力仅保证协调器元数据不丢、重启可恢复、补偿幂等，**不等于强一致性**。支付/订单/库存等核心业务应采用经过业务验证的 TCC、Saga 或 Outbox/可靠消息方案；仅把模式切成 `distributed` 仍不够。

### Distributed 模式要求

1. 部署 Seata Server（https://seata.io）
2. 启动 `deploy/seata-bridge`，配置共享 token、callback host 白名单和事务组
3. 为 bridge 数据源创建官方 `tcc_fence_log`，业务服务实现持久化的 TCC 回调
4. 设置 `SEATA_ENABLED=true`、`seata.mode=distributed`

> `distributed` 模式无法连接 bridge/Seata Server 时会启动失败，不会静默降级到 `local`。这只是 fail-closed 保护，不代表业务 TCC 实现已经通过一致性认证。

### 相关代码位置

- [`springbootai/cloud/seata.py`](../springbootai/cloud/seata.py) — `SeataTransactionManager` 四模式实现（local/http/distributed/at）
- [`springbootai/cloud/seata_at_proxy.py`](../springbootai/cloud/seata_at_proxy.py) — AT 模式数据源代理（ORM 拦截器 + undo_log）
- [`springbootai/cloud/transaction_store.py`](../springbootai/cloud/transaction_store.py) — `SQLiteTransactionStore`（WAL + 原子状态迁移）

---

## 改进记录

### Seata distributed 模式桥接失败无降级 — 高 ✅ 已修复 (v2.3.0)

**位置**：`springbootai/cloud/seata.py` begin_transaction() distributed 分支

**现象**：`begin_transaction(mode='distributed')` 调用外部 Seata bridge，若 bridge 不可达，异常处理不充分——事务状态可能停留在 `BEGINNING`，后续 `commit()`/`rollback()` 行为未定义。

**修复方案**：新增 `fallback_to_local` 配置项（默认 False），bridge 未初始化或 begin 失败时降级为本地事务 + 警告日志。降级时上下文已设置（in_transaction=True），直接返回 tx_id。

### Seata recovery worker 无优雅停机 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/cloud/seata.py` recovery worker 线程

**现象**：recovery worker 是守护线程（`daemon=True`），应用退出时被强杀，正在恢复中的事务可能丢失。

**改进方案**：注册 `atexit` 钩子或接入 `springbootai.core.graceful_shutdown`，停机前等待 recovery worker 完成当前任务；设置停机超时（默认 30 秒）。

### RabbitMQ 消息发布未处理 JSON 序列化失败 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/messaging/rabbitmq.py` publish_to_queue()

**现象**：`publish_to_queue` 对消息体 `json.dumps()` 时，若包含不可序列化对象（如 `datetime`），会抛 `TypeError`，当前未捕获，调用方收到未包装的 `TypeError`。

**改进方案**：捕获 `TypeError`，包装为 `MessageSerializationError`；提供自定义 `default` 回调支持 `datetime` → ISO 格式自动转换。

### RabbitMQ 连接失败无重试 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/messaging/rabbitmq.py` get_channel()

**现象**：`get_channel()` 连接失败直接抛异常，无重试逻辑。网络抖动场景下首次连接失败即导致服务不可用。

**改进方案**：集成 `springbootai.retry` 的 `@Retryable`，配置指数退避（初始 1 秒，倍数 2，最大 30 秒，最多 5 次）。
