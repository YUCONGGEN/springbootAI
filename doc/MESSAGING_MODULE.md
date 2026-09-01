# SpringBootAI 消息队列模块指南

> SpringBootAI 2.3.11

---

## 消息队列模块是什么？

**消息队列 = 系统间的"传送带"——生产者把消息放到传送带上就走，消费者在另一头按自己的节奏取。** 有了它，发消息的人和收消息的人不用同时在场：下单服务发完消息立刻返回，库存、积分、通知各自慢慢处理。这套机制由 RabbitMQ 提供，框架在此基础上封装了两个核心工具：

- **`@RabbitListener`**：贴在方法上，告诉框架"这个方法要监听某个队列，有消息就调用我"。
- **`RabbitTemplate` / `rabbit_template`**：一个现成的发送工具，一行代码把消息丢到队列里。

> 💡 比喻：`RabbitTemplate` 是寄快递的窗口，`@RabbitListener` 是收件人。你只管寄件和签收，中间的运输（连接、通道、序列化、确认）框架全包了。

### 🔥 核心组件速查

| 组件 | 一句话作用 | 是不是注解 | 写在哪 |
|------|----------|-----------|--------|
| `@RabbitListener` | 标记一个方法为队列消费者，有消息自动调用 | 是（方法上） | `@Service` 等 Bean 的方法上 |
| `RabbitTemplate` / `rabbit_template` | 发送消息到队列或交换机 | 否（工具类） | 任意可调用处 |
| `register_rabbit_listener` | 把 `@RabbitListener` 方法绑定到 RabbitMQ 队列 | 否（框架内部函数） | 框架启动时自动调用 |

### 决策指引：我想做什么该看哪节？

| 我想做的事 | 看哪节 |
|-----------|--------|
| 写一个方法接收队列消息 | [@RabbitListener 消费消息](#1-rabbitlistener-消费消息) |
| 在代码里发送一条消息到队列 | [RabbitTemplate 发送消息](#2-rabbittemplate-发送消息) |
| 搞懂框架是怎么把监听器和队列绑起来的 | [register_rabbit_listener（框架内部）](#3-register_rabbit_listener框架内部) |
| 配置 RabbitMQ 连接地址 | [配置与依赖](#配置与依赖) |
| 了解底层连接管理细节 | [底层实现：RabbitMQClient](#底层实现rabbitmqclient) |

---

## 1. @RabbitListener 消费消息

### 是什么？

**就像订报纸——你告诉报童"我要订 `order.create` 这份报纸"，之后每来一期他就塞到你门里（调用你的方法）。** 你不用主动去查有没有新消息，框架在后台线程帮你盯着队列，有消息就自动调用被 `@RabbitListener` 标记的方法。

### 注解参数速查表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `queue` | `str` | **必填** | 要监听的队列名称 |
| `exchange` | `str` | `""` | 交换机名称；填了会自动声明交换机并把队列绑定上去 |
| `routing_key` | `str` | `""`（实际等于 `queue`） | 路由键；不填时默认用 `queue` 的值 |
| `auto_ack` | `bool` | `False` | 是否自动确认；`False` 表示手动确认（方法抛异常时消息会重新入队） |
| `prefetch_count` | `int` | `1` | 预取数量；控制消费者一次最多拿多少条未确认消息，调大可提高吞吐 |

### 怎么用？

**步骤一：写一个 `@Service`，方法上贴 `@RabbitListener`**

```python
from springbootai.annotations import RabbitListener, Service


@Service
class OrderConsumer:
    # 框架启动后会自动声明 order.create 队列，并在后台线程消费
    @RabbitListener(queue="order.create")
    def handle_order(self, message):
        print(f"Received order: {message}")
```

**步骤二：在 `application.yml` 中启用 RabbitMQ**

```yaml
rabbitmq:
  enabled: true                      # 必须为 true，否则监听器不会注册、消费者不会启动
  host: ${RABBITMQ_HOST:localhost}
  port: ${RABBITMQ_PORT:5672}
  username: ${RABBITMQ_USERNAME:guest}
  password: ${RABBITMQ_PASSWORD:guest}
  virtual_host: ${RABBITMQ_VHOST:/}
  connection_timeout: ${RABBITMQ_CONNECTION_TIMEOUT:5}
  socket_timeout: ${RABBITMQ_SOCKET_TIMEOUT:5}
  stack_timeout: ${RABBITMQ_STACK_TIMEOUT:5}
  connection_attempts: ${RABBITMQ_CONNECTION_ATTEMPTS:1}
```

**步骤三（进阶）：使用交换机 + 路由键**

```python
@Service
class OrderConsumer:
    # 会自动声明 exchange=orders、queue=order.create，并按 routing_key 绑定
    @RabbitListener(
        queue="order.create",
        exchange="orders",
        routing_key="order.create",
        auto_ack=False,          # 手动确认：处理失败消息会重新入队
        prefetch_count=10,       # 一次最多预取 10 条，提高吞吐
    )
    def handle_order(self, message):
        # message 已被自动反序列化：dict/list 会 JSON 解析，否则是字符串
        print(f"Received order: {message}")
```

### 消息体是怎么传给方法的？

框架在收到 RabbitMQ 投递的原始字节后，会自动解析再传给你的方法参数：

| 原始消息 | 方法收到的 `message` |
|---------|---------------------|
| JSON 字符串 `{"order_id": 1}` | `dict`：`{"order_id": 1}` |
| JSON 数组 `[1, 2, 3]` | `list`：`[1, 2, 3]` |
| 非 JSON 文本 | `str`（UTF-8 解码） |
| 空消息 | `None` |

> 方法支持同步函数，也支持 `async def`——框架检测到返回的是 awaitable 会用 `asyncio.run()` 执行。

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 把 `@RabbitListener` 贴在普通类（没 `@Service`）的方法上 | 必须贴在**框架管理的 Bean**（如 `@Service`、`@Component`）的方法上，否则不会被扫描和注册 |
| 忘了在 `application.yml` 里设 `rabbitmq.enabled: true` | `enabled` 默认是 `false`。不开启的话，监听器不会注册、消费者线程也不会启动，队列里有消息也收不到 |
| 没装 `pika` 就用 `@RabbitListener` | `pika` 是可选依赖，没装时 `RabbitListener` 会被设为 `None`，注解会报错。先 `pip install pika` |
| `auto_ack=True` 后方法里抛异常 | 自动确认模式下消息一出队就算处理完，抛异常消息就丢了。需要可靠消费就保持 `auto_ack=False`，失败会自动重新入队 |
| 在监听方法里做耗时阻塞操作 | 消费是在后台线程跑的，阻塞会卡住该队列的消费。耗时任务建议转发给 `@Async` 方法或丢回线程池 |

---

## 2. RabbitTemplate 发送消息

### 是什么？

**`RabbitTemplate` 是框架提供的消息发送工具类，不是注解。** 你不需要自己 new 连接、开通道、序列化、发完再关——直接调用它的 `send()` 方法，一行代码搞定。框架已经在模块加载时创建了一个全局单例 `rabbit_template`，拿来即用。

### send 方法参数速查表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `queue` | `str` | **必填** | 目标队列名称 |
| `body` | `Any` | **必填** | 消息体；`dict` 会 JSON 序列化，其他类型转 `str` |
| `exchange` | `str` | `""` | 交换机名称；填了走交换机路由，不填直接投到队列 |
| `routing_key` | `str` | `""` | 路由键；走交换机时使用，不填默认用 `queue` |
| `persistent` | `bool` | `True` | 是否持久化；`True` 表示消息写入磁盘，RabbitMQ 重启不丢 |

### 怎么用？

**场景一：直接发到队列（最常用）**

```python
from springbootai.annotations.messaging import rabbit_template

# 发送一个 dict，框架会自动 json.dumps 序列化
rabbit_template.send("order.create", {"order_id": 1, "amount": 99.9})

# 发送字符串也行
rabbit_template.send("notification", "订单已创建")
```

**场景二：通过交换机 + 路由键发送**

```python
from springbootai.annotations.messaging import rabbit_template

# 走 orders 交换机，按 order.created 路由键投递
rabbit_template.send(
    queue="order.create",
    body={"order_id": 2, "amount": 199.0},
    exchange="orders",
    routing_key="order.created",
    persistent=True,            # 持久化，RabbitMQ 重启不丢消息
)
```

**场景三：在 Controller / Service 中发送**

```python
from springbootai.annotations import RestController, PostMapping, Service
from springbootai.annotations.messaging import rabbit_template
from springbootai.web.result import Result


@RestController
class OrderController:
    @PostMapping("/orders")
    def create_order(self):
        # 下单后异步通知库存系统
        rabbit_template.send("order.create", {"order_id": 1, "amount": 99.9})
        return Result.success(data={"order_id": 1})


@Service
class OrderService:
    def place_order(self, order_id: int):
        rabbit_template.send("order.create", {"order_id": order_id})
```

### 内部路由逻辑

`RabbitTemplate.send()` 会根据是否传 `exchange` 走不同路径：

```
传了 exchange → rabbitmq_client.publish(exchange, routing_key or queue, body)
没传 exchange → rabbitmq_client.publish_to_queue(queue, body)   # 等价于 exchange="" + routing_key=queue
```

两种方式都会自动序列化消息体（`dict` → JSON，其他 → `str`），并按 `persistent` 设置消息的持久化属性。

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 自己 `RabbitTemplate()` new 实例 | 直接用全局单例 `from springbootai.annotations.messaging import rabbit_template`，new 出来的也能用但没必要 |
| 发送前忘了开 `rabbitmq.enabled` | 发送依赖底层连接，`enabled=false` 时连接没建立，`send()` 会抛连接异常 |
| 发送不可序列化对象（如自定义类实例） | `body` 只支持 `dict`/`list`/`str` 等可序列化类型。自定义对象请先转成 `dict` |
| 以为 `queue` 参数在走交换机时没用 | 走交换机时 `queue` 主要用于默认 `routing_key`。建议同时明确 `routing_key`，避免歧义 |

---

## 3. register_rabbit_listener（框架内部）

### 是什么？

**这是框架内部使用的注册函数，你通常不需要直接调用它。** 当框架扫描到一个被 `@RabbitListener` 标记的 Bean 方法时，会自动调用这个函数，把方法绑定到 RabbitMQ 队列上。

> 你只需知道它的存在即可——理解它有助于排查"为什么我的监听器没生效"。

### 它做了什么？

调用 `register_rabbit_listener(annotation, callback)` 时，会按顺序执行：

1. **声明队列**：`rabbitmq_client.declare_queue(annotation.queue)`——队列不存在则自动创建（默认持久化）
2. **声明交换机并绑定**（仅当配置了 `exchange`）：
   - `rabbitmq_client.declare_exchange(annotation.exchange)`——声明交换机（默认 `direct` 类型）
   - `rabbitmq_client.bind_queue(queue, exchange, routing_key)`——把队列按路由键绑定到交换机
3. **注册消费**：`rabbitmq_client.consume(queue, callback, auto_ack, prefetch_count)`——注册回调并设置预取数量

### 何时被调用？

框架启动流程中，Bean 初始化阶段会扫描每个 Bean 的方法：

```python
# springbootai/context/bean_factory.py（简化示意）
def _register_rabbit_listeners(self, instance):
    # 前置检查：rabbitmq.enabled 必须为 true 且连接已建立
    if not config.get_value('rabbitmq.enabled', False):
        return
    if connection is None or connection.is_closed:
        return
    # 扫描方法上的 @RabbitListener 注解并注册
    for name, method in inspect.getmembers(instance.__class__):
        for annotation in getattr(method, '__spring_annotations__', []):
            if isinstance(annotation, RabbitListener):
                register_rabbit_listener(annotation, getattr(instance, name))
```

> ⚠️ 这意味着：监听器只对**框架管理的 Bean**生效。你自己 `new` 出来的对象，方法上就算贴了 `@RabbitListener` 也不会被注册。

### 启动后消费何时开始？

所有 Bean 初始化完成后，`main.py` 会在一个**守护线程**里启动消费循环：

```python
# springbootai/main.py（简化示意）
if config.get('rabbitmq', {}).get('enabled', False):
    rabbitmq_client.start_consuming_background()   # 守护线程，主进程退出时自动结束
```

---

## 配置与依赖

### 安装依赖

`pika` 是**可选依赖**，未安装时 `RabbitListener` 和 `RabbitTemplate` 会被设为 `None`（注解不可用，但不影响框架其他功能启动）：

```bash
pip install pika
```

### application.yml 配置

> ⚠️ 配置项在**顶层 `rabbitmq:`** 下（不是 `spring.rabbitmq:`），且必须显式设置 `enabled: true` 才会启用。

```yaml
rabbitmq:
  enabled: ${RABBITMQ_ENABLED:false}        # 默认关闭；启用后才会建连、注册监听器、启动消费
  host: ${RABBITMQ_HOST:localhost}
  port: ${RABBITMQ_PORT:5672}
  username: ${RABBITMQ_USERNAME:guest}
  password: ${RABBITMQ_PASSWORD:guest}
  virtual_host: ${RABBITMQ_VHOST:/}
  # 服务不可用时的启动保护：三类网络超时均为秒，连接默认只尝试一次
  connection_timeout: ${RABBITMQ_CONNECTION_TIMEOUT:5}
  socket_timeout: ${RABBITMQ_SOCKET_TIMEOUT:5}
  stack_timeout: ${RABBITMQ_STACK_TIMEOUT:5}
  connection_attempts: ${RABBITMQ_CONNECTION_ATTEMPTS:1}
  retry_delay: ${RABBITMQ_RETRY_DELAY:0}
  blocked_connection_timeout: ${RABBITMQ_BLOCKED_CONNECTION_TIMEOUT:300}
```

所有值都支持用环境变量覆盖（`${VAR:默认值}` 语法），便于不同环境（开发/测试/生产）切换：

```bash
# PowerShell 示例
$env:RABBITMQ_HOST = "192.168.1.100"
$env:RABBITMQ_USERNAME = "admin"
$env:RABBITMQ_PASSWORD = "secret"
```

### 启用条件检查清单

要让消息队列正常工作，以下条件**必须同时满足**：

| # | 条件 | 不满足的后果 |
|---|------|-------------|
| 1 | 已 `pip install pika` | `RabbitListener` / `RabbitTemplate` 为 `None`，导入即报错 |
| 2 | `rabbitmq.enabled: true` | 不建连、不注册监听器、不启动消费线程 |
| 3 | RabbitMQ 服务可达且账号正确 | 启动时连接失败，按 `startup.fail_fast` 决定是否中断启动 |
| 4 | `@RabbitListener` 在框架管理的 Bean 上 | 方法不会被扫描注册，队列有消息也收不到 |

---

## 底层实现：RabbitMQClient

### 是什么？

`springbootai/messaging/rabbitmq.py` 中的 `RabbitMQClient` 是 RabbitMQ 连接的底层管理者，采用**单例模式**。全局实例 `rabbitmq_client` 在模块加载时创建，`@RabbitListener` 和 `RabbitTemplate` 都基于它工作。

### 核心能力速查表

| 方法 | 作用 |
|------|------|
| `configure(host, port, ...)` | 重新配置连接参数（读取配置后调用，会重置旧连接） |
| `connect()` | 建立 RabbitMQ 连接和通道 |
| `declare_queue(name, durable=True)` | 声明队列（默认持久化） |
| `declare_exchange(name, type="direct")` | 声明交换机（默认 direct 类型） |
| `bind_queue(queue, exchange, routing_key)` | 把队列按路由键绑定到交换机 |
| `publish(exchange, routing_key, body, persistent=True)` | 通过交换机发布消息 |
| `publish_to_queue(queue, body, persistent=True)` | 直接发布消息到队列 |
| `consume(queue, callback, auto_ack=False, prefetch_count=1)` | 注册消费者回调 |
| `start_consuming_background()` | 在守护线程启动消费循环（非阻塞） |
| `stop_consuming()` | 停止消费 |
| `close()` | 关闭连接 |

### 关键设计点

- **单例 + `configure`**：`__init__` 用 `_initialized` 守卫防止重复初始化，所以读取配置后必须用 `configure()` 重新设置连接参数，否则会停留在默认值 `localhost:5672`。
- **消息确认机制**：`auto_ack=False` 时，方法处理成功会 `basic_ack`；抛异常会 `basic_nack` 并 `requeue=True`（消息重新入队重试）。
- **心跳保活**：连接参数设置 `heartbeat=600`、`blocked_connection_timeout=300`，防止长连接被中间网络设备断开。
- **启动不阻塞**：`connection_timeout`、`socket_timeout`、`stack_timeout` 默认均为 5 秒，
  `connection_attempts` 默认 1、`retry_delay` 默认 0。RabbitMQ 未启动时会在有限时间内
  返回错误，由 `startup.fail_fast` 决定是否终止进程；组件关闭（`enabled=false`）时完全
  不建连。生产环境可按网络情况调大超时，但不要设置为 0 或无限重试。
- **消费在守护线程**：`start_consuming_background()` 启动的线程是 daemon，主进程退出时自动结束，不会阻塞关闭。

### 初始化流程

```
应用启动 (main.py)
   │
   ├─ 读取 rabbitmq.enabled
   │     └─ false → 跳过，消息功能完全不可用
   │     └─ true  → 调用 init_rabbitmq(config)
   │                  ├─ rabbitmq_client.configure(...)   # 应用配置
   │                  └─ rabbitmq_client.connect()        # 建立连接
   │
   ├─ Bean 初始化 (bean_factory.py)
   │     └─ 扫描 @RabbitListener 方法
   │          └─ register_rabbit_listener()  # 声明队列/交换机 + 注册回调
   │
   └─ 启动后台消费 (main.py)
        └─ rabbitmq_client.start_consuming_background()  # 守护线程消费
```

---

## 代码位置与测试

| 模块 | 实现位置 | 说明 |
|------|---------|------|
| `@RabbitListener` 注解 | `springbootai/annotations/messaging.py` | 监听注解定义 + 注册函数 + 全局 `rabbit_template` |
| `RabbitTemplate` | `springbootai/annotations/messaging.py` | 消息发送模板（全局单例 `rabbit_template`） |
| `register_rabbit_listener` | `springbootai/annotations/messaging.py` | 监听器注册（框架内部调用） |
| `RabbitMQClient` | `springbootai/messaging/rabbitmq.py` | 底层连接管理单例 + `init_rabbitmq` |
| 注解导出 | `springbootai/annotations/__init__.py` | `RabbitListener` / `RabbitTemplate`（pika 缺失时为 `None`） |
| Bean 注册监听器 | `springbootai/context/bean_factory.py` | `_register_rabbit_listeners` 扫描并绑定 |
| 启动初始化 | `springbootai/main.py` | `init_rabbitmq` + `start_consuming_background` |
| 示例代码 | `examples/example_all/service/MessagingService.py`、`examples/example_all/controller/MessagingController.py` | 完整收发示例 |

| 测试 | 测试文件 | 覆盖内容 |
|------|---------|---------|
| 注解契约 | `tests/test_annotations_contract.py` | `test_rabbit_annotation_and_template_paths`：注解参数、装饰器、`register_rabbit_listener`、`RabbitTemplate.send` 的队列/交换机两条路径 |

> 注意：与 RabbitMQ 真实服务的端到端联调需要先启动一个 RabbitMQ 实例（例如 `docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management-alpine`），再把 `rabbitmq.enabled` 设为 `true`。

---

## FAQ

### Q1: pika 没装会影响框架启动吗？

不会。`springbootai/annotations/__init__.py` 用 `try/except ImportError` 包裹了消息注解的导入，pika 缺失时 `RabbitListener` 和 `RabbitTemplate` 会被设为 `None`，框架其他功能照常启动。只有当你真正使用消息功能时才会报错。

### Q2: 为什么我的 `@RabbitListener` 方法收不到消息？

按顺序排查：
1. `application.yml` 里 `rabbitmq.enabled` 是不是 `true`？（默认 `false`）
2. pika 装了吗？`RabbitListener` 是不是 `None`？
3. 方法所在的类有没有加 `@Service` / `@Component` 等注解？（必须是框架管理的 Bean）
4. RabbitMQ 服务起了吗？连接有没有报错？看启动日志。
5. 发消息时队列名和监听的 `queue` 参数一致吗？

### Q3: `RabbitTemplate` 和 `rabbit_template` 是什么关系？

`RabbitTemplate` 是类，`rabbit_template` 是框架在模块加载时创建的全局单例实例（`rabbit_template = RabbitTemplate()`）。日常使用直接导入 `rabbit_template` 调用 `send()` 即可，不需要自己 new。

### Q4: 消息处理失败会怎样？

取决于 `auto_ack`：
- `auto_ack=False`（默认）：方法抛异常时，框架会 `basic_nack` 并把消息**重新入队**，稍后会再次投递。适合需要可靠消费的场景。
- `auto_ack=True`：消息一出队就确认，方法抛异常消息就丢了。仅适合允许丢失的场景。

### Q5: 为什么配置写在 `rabbitmq:` 而不是 `spring.rabbitmq:`？

框架配置统一按功能域分顶层键（如 `database`、`redis`、`rabbitmq`、`jwt`），`main.py` 通过 `config.get('rabbitmq', {})` 读取。这与 Spring Boot 的 `spring.rabbitmq.*` 命名不同，是 SpringBootAI 自身的约定。

### Q6: 能同时监听多个队列吗？

可以。在一个 Bean 里写多个 `@RabbitListener` 方法，每个监听不同队列即可。它们会在同一个消费线程里轮询处理；如果需要更高吞吐，可以调整 `prefetch_count` 或拆分到不同 Bean。

---

## Kafka 消息队列

### Kafka 是什么？

**Kafka 是分布式流处理平台，适合高吞吐量、可持久化、可回放的消息场景。** 与 RabbitMQ 的"传送带"模型不同，Kafka 更像"日志"——消息按顺序追加到分区（Partition）中持久化存储，消费者按偏移量（Offset）主动拉取。

**Kafka 与 RabbitMQ 的核心差异：**

| 维度 | Kafka | RabbitMQ |
|------|-------|----------|
| 消费模型 | 拉取模型（Consumer 主动 poll） | 推送模型（Broker 推送） |
| 消息存储 | 持久化到磁盘（按 offset 保存） | 确认后删除 |
| 消息回溯 | 支持（重置 offset 即可重放） | 不支持 |
| 路由方式 | 按 topic + partition + key | 按 exchange + routing_key |
| 典型场景 | 日志聚合 / 流处理 / 事件溯源 | 任务队列 / RPC / 解耦 |

> 💡 选型建议：需要可靠投递、任务分发的选 RabbitMQ；需要高吞吐、消息回溯、流处理的选 Kafka。

### 核心组件速查

| 组件 | 一句话作用 | 是不是注解 | 写在哪 |
|------|----------|-----------|--------|
| `@KafkaListener` | 标记一个方法为 Kafka 主题消费者 | 是（方法上） | `@Service` 等 Bean 的方法上 |
| `KafkaTemplate` / `kafka_template` | 发送消息到 Kafka 主题 | 否（工具类） | 任意可调用处 |
| `KafkaClient` | Kafka 底层连接管理（生产者 + 消费者） | 否（单例类） | 框架内部 |
| `init_kafka` | 从 `application.yml` 初始化 Kafka 客户端 | 否（框架函数） | 框架启动时调用 |

### @KafkaListener 消费消息

**像订频道——你告诉框架"我要订阅 `order-events` 这个频道"，框架在后台线程轮询拉取消息，有新消息就调用你的方法。**

**注解参数速查表：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `topics` | `str` / `List[str]` | **必填** | 要订阅的主题，支持单个字符串或列表 |
| `groupId` | `str` | `""` | 消费者组 ID；不填则用全局 `spring.kafka.consumer.group-id` |

**代码示例：**

```python
from springbootai.annotations import Service
from springbootai.annotations.messaging import KafkaListener


@Service
class OrderEventConsumer:
    # 框架启动后会自动注册消费者，并在后台线程轮询消息
    @KafkaListener(topics=["order-events"], groupId="order-service")
    def handle_order_event(self, message):
        # message 是 dict，包含 topic/partition/offset/key/value/timestamp
        print(f"Received from {message['topic']}: {message['value']}")
        print(f"Partition={message['partition']}, Offset={message['offset']}")
```

**消息体结构：** 框架把 Kafka 原始消息封装成 dict 传给回调方法：

| 字段 | 类型 | 说明 |
|------|------|------|
| `topic` | `str` | 主题名 |
| `partition` | `int` | 分区号 |
| `offset` | `int` | 偏移量 |
| `key` | `str` / `None` | 分区键（已解码） |
| `value` | `Any` | 消息体（自动 JSON 反序列化） |
| `timestamp` | `int` | 时间戳（毫秒） |

> 与 `@RabbitListener` 的差异：Kafka 监听 `topics`（数组），Rabbit 监听 `queue`（单个）；Kafka 需要 `groupId`，Rabbit 不需要；Kafka 消息含 partition/offset，Rabbit 只有 body。

### KafkaTemplate 发送消息

**`KafkaTemplate` 是 Kafka 消息发送工具类，不是注解。** 框架在模块加载时已创建全局单例 `kafka_template`，直接导入使用即可。

**send 方法参数速查表：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `topic` | `str` | **必填** | 目标主题 |
| `value` | `Any` | `None` | 消息体（自动 JSON 序列化） |
| `key` | `str` / `None` | `None` | 分区键；相同 key 路由到同一分区 |
| `headers` | `Dict[str, str]` / `None` | `None` | 消息头 |

**代码示例：**

```python
from springbootai.annotations.messaging import kafka_template

# 场景一：异步发送（立即返回 future）
kafka_template.send("order-events", value={"order_id": 1, "amount": 99.9})

# 场景二：带分区键发送（相同 key 的消息进同一分区，保证顺序）
kafka_template.send("order-events", value={"order_id": 2}, key="order-2")

# 场景三：同步发送并等待确认（可靠性要求高时用）
kafka_template.send_and_wait("order-events", value={"order_id": 3}, key="order-3")
```

**在 Controller / Service 中使用：**

```python
from springbootai.annotations import RestController, PostMapping
from springbootai.annotations.messaging import kafka_template
from springbootai.web.result import Result


@RestController
class OrderController:
    @PostMapping("/orders")
    def create_order(self):
        # 下单后异步通知下游系统
        kafka_template.send("order-events", value={"order_id": 1, "amount": 99.9})
        return Result.success(data={"order_id": 1})
```

### 配置方式

Kafka 配置写在 `application.yml` 的 `spring.kafka` 下：

```yaml
spring:
  kafka:
    bootstrap-servers: ${KAFKA_BOOTSTRAP_SERVERS:localhost:9092}   # Broker 地址，多个用逗号分隔
    consumer:
      group-id: ${KAFKA_GROUP_ID:default-group}                    # 消费者组 ID
      auto-offset-reset: latest                                    # 无 offset 时从哪里开始消费（latest/earliest）
    producer:
      acks: all                                                    # 确认级别（0/1/all）
      retries: 3                                                   # 重试次数
```

**配置项说明：**

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `spring.kafka.bootstrap-servers` | `localhost:9092` | Kafka Broker 地址列表 |
| `spring.kafka.consumer.group-id` | `default-group` | 消费者组 ID |
| `spring.kafka.consumer.auto-offset-reset` | `latest` | Offset 重置策略：`latest`（只消费新消息）/ `earliest`（从头消费） |

**环境变量覆盖：**

```bash
# PowerShell 示例
$env:KAFKA_BOOTSTRAP_SERVERS = "192.168.1.100:9092,192.168.1.101:9092"
$env:KAFKA_GROUP_ID = "order-service"
```

**安装依赖：**

```bash
pip install kafka-python
```

> ⚠️ `kafka-python` 是可选依赖，未安装时调用 `@KafkaListener` / `KafkaTemplate` 会抛 `ImportError`，但不影响框架其他功能启动。

### 与 Java Spring Kafka 的对照表

| 功能 | Java Spring Kafka | SpringBootAI |
|------|-------------------|--------------|
| 消费注解 | `@KafkaListener(topics=..., groupId=...)` | `@KafkaListener(topics=..., groupId=...)` |
| 发送模板 | `KafkaTemplate.send(topic, data)` | `KafkaTemplate.send(topic, value=...)` |
| 全局模板实例 | `@Autowired KafkaTemplate` | `from springbootai.annotations.messaging import kafka_template` |
| 消费者组配置 | `spring.kafka.consumer.group-id` | `spring.kafka.consumer.group-id` |
| Bootstrap 配置 | `spring.kafka.bootstrap-servers` | `spring.kafka.bootstrap-servers` |
| Offset 重置 | `spring.kafka.consumer.auto-offset-reset` | `spring.kafka.consumer.auto-offset-reset` |
| 序列化 | 配置 `Producer/Deserializer` 类 | 框架内置 JSON 序列化 |
| 消息确认 | `Acknowledgment` 对象手动确认 | `enable_auto_commit=True` 自动确认 |
| 底层客户端 | `org.apache.kafka.clients` | `kafka-python` |
