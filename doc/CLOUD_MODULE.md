# SpringBootAI Cloud 模块 —— 小白也能看懂的微服务指南

> 框架版本：SpringBootAI 2.0.0

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
```

在启动类上加注解：

```python
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableDiscoveryClient

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

```python
from spring.annotations import Service
from spring.annotations.cloud import NacosValue

@Service
class ConfigService:
    # auto_refreshed=True 表示 Nacos 上的值变了，这里自动更新
    @NacosValue(value="${app.version}", auto_refreshed=True)
    def get_version(self):
        return self._app_version
# 结果：首次读取 Nacos 中的 app.version 值，之后改了自动刷新
```

如果整个类都需要动态配置，用 `@RefreshScope`：

```python
from spring.annotations import Service
from spring.annotations.cloud import RefreshScope

@Service
@RefreshScope  # 贴上"可刷新"标签
class DynamicConfigService:
    def __init__(self):
        # Nacos 配置刷新后，这个 Service 会重新创建，拿到最新配置
        self.feature_flag = True
        self.timeout = 30
```

手动触发刷新：

```python
from spring.aop.cloud_aop import trigger_config_refresh

trigger_config_refresh()  # 触发一次配置刷新，所有 @RefreshScope 的 Bean 重新创建
```

### ③ 运行结果

在 Nacos 控制台把 `app.version` 从 `1.0` 改成 `2.0`，你的应用不用重启，`get_version()` 返回的就是 `2.0` 了。

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
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableFeignClients

@SpringBootApplication
@EnableFeignClients(base_packages=["com.example.feign"])  # 扫描这个包下的 Feign 接口
class Application:
    pass
```

声明远程调用接口：

```python
from spring.annotations.cloud import FeignClient
from spring.annotations import GetMapping, PostMapping

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
from spring.annotations.cloud import FeignClient
from spring.cloud.feign import create_declared_feign_client

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
from spring.cloud.feign import create_feign_client

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
from spring.annotations import Service
from spring.annotations.cloud import SentinelResource

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
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableGateway

@SpringBootApplication
@EnableGateway  # 开启"公司前台"功能
class GatewayApplication:
    pass
```

配置路由规则：

```python
from spring.cloud.gateway import GatewayRouter

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

**分布式事务就像是跨国转账。** 你在中国的银行向美国银行转 100 美元，必须确保：你的账户扣了 100 美元，同时对方的账户加 100 美元。两边要么都成功，要么都失败——不能出现钱扣了但对方没收到的情况。

Seata 就是负责跨多个服务协调事务的：

- **local 模式**：只做事务追踪，不做跨服务协调。开发调试用。
- **http 模式**：持久化补偿协调。服务挂了重启后能恢复未完成的事务。**但它不具备强一致性**——就像发微信让对方确认，你发了但对方可能没收到。
- **distributed 模式**：对接真实 Seata Server，具备全局锁和 undo_log 回滚。**这是唯一具备强一致性的模式**。

### ② 怎么用

```python
from spring.annotations import Service, Autowired
from spring.annotations.cloud import GlobalTransactional

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
        # 结果：任意一步失败，前面成功的步骤都会回滚
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

`@GlobalTransactional` 标注的方法中，所有远程调用被纳入一个全局事务。任何一步失败，全局事务回滚，已执行的操作被撤销。

### 什么时候用 / 什么时候不用

| 场景 | 用什么模式 | 为什么 |
|---|---|---|
| 开发调试 | `local` | 只在本地追踪事务，不做跨服务协调 |
| 非关键业务的补偿流程 | `http` | 能持久化和恢复，但不是强一致 |
| 支付/订单/库存等核心业务 | `distributed` | 唯一具备强一致性的模式 |

### ⚠️ 重要警告

**http 模式不等于强一致性。** 它就像发微信让对方确认——消息发出去了，但如果对方没收到或者系统崩溃了，需要不断重试。真正的 Seata distributed 模式就像银行转账：要么成功、要么失败，不会有中间状态。

---

## 八、Trace —— 快递单号

### 你遇到了什么问题？

一个用户请求经过了 5 个微服务，某个环节出错了，你想查日志——每个服务都有自己的日志，你怎么把这些日志串起来找到完整调用链？

### ① 是什么

**Trace 就像是快递单号——包裹从发货到你手里，经过好几个中转站，你扫一下单号就知道全过程。** Trace 给每个请求生成一个全局唯一的 traceId，这个 traceId 在所有服务间传递，日志里带上它，你就能追踪整个调用链。

### ② 怎么用

```python
from spring.annotations import Trace

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
| 5 | "分布式事务和数据库事务一样可靠" | 完全不同。只有 Seata `distributed` 模式才具备强一致性，`http` 模式只是补偿 |
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

http 模式的持久化能力仅保证协调器元数据不丢、重启可恢复、补偿幂等，**不等于强一致性**。支付/订单/库存等核心业务强一致场景必须使用 `distributed` 模式对接真实 Seata Server，或采用可靠消息最终一致方案。

### Distributed 模式要求

1. 部署 Seata Server（https://seata.io）
2. 安装兼容的企业 Seata Python SDK
3. 配置 `registry.conf` / `file.conf`，创建 `seata_undo_log` 表
4. 设置 `SEATA_ENABLED=true`、`seata.mode=distributed`

> ⚠️ `distributed` 模式未检测到兼容 SDK 时会启动失败（不会静默降级到 `local`），避免核心业务在无强一致保障下继续运行。

### 相关代码位置

- [`spring/cloud/seata.py`](../spring/cloud/seata.py) — `SeataTransactionManager` 三模式实现
- [`spring/cloud/transaction_store.py`](../spring/cloud/transaction_store.py) — `SQLiteTransactionStore`（WAL + 原子状态迁移）
