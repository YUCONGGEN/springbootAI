# SpringBootAI 并发与弹性模块指南

> SpringBootAI 2.3.2

---

## 并发与弹性模块是什么？

**并发与弹性模块 = 系统的"红绿灯 + 保险丝 + 备用电源"——让程序在高并发和故障场景下依然稳得住。** 本文介绍八组注解工具，覆盖异步执行、定时任务、限流、熔断、幂等、锁等典型并发与弹性场景。你不需要一次性全部学会——遇到对应问题再来看就行。

打个比方：
- **@Async** 像把任务交给助理去办，你不用等他办完就能继续做别的事
- **@Scheduled** 像闹钟，到点自动响
- **@RateLimit** 像地铁早高峰限流，每分钟只放固定数量的人进站
- **@CircuitBreaker** 像家里的保险丝，电流异常时自动跳闸保护电器，过一会儿再试着合闸
- **@Idempotent** 像售票窗口的"已售"印章，同一张票无论点几次购买都只出一张
- **@Lock / @Synchronized** 像公共厕所门锁，进去的人锁门，外面的人排队等

### 🔥 新手最常用的 5 个注解速查

| 注解 | 一句话作用 | 写在哪 | 示例 |
|------|----------|--------|------|
| `@Async` | 方法异步执行，不阻塞调用方 | 方法上 | `@Async` |
| `@Scheduled` | 定时任务，到点自动执行 | 方法上 | `@Scheduled(fixed_rate=60000)` |
| `@RateLimit` | 限制方法在时间窗口内的调用次数 | 方法上 | `@RateLimit(max_requests=5, time_window=60)` |
| `@CircuitBreaker` | 连续失败后熔断，保护下游服务 | 方法上 | `@CircuitBreaker(failure_threshold=5, fallback_method="fb")` |
| `@Lock` | 分布式锁，防止并发修改 | 方法上 | `@Lock(key="{product_id}", expire=10)` |

### 决策指引：我想做什么该看哪节？

| 我想做的事 | 看哪节 |
|-----------|--------|
| 让耗时方法在后台跑，不卡住主流程 | [@Async](#1-async-异步执行注解) |
| 包装异步方法的返回值 | [@AsyncResult](#2-asyncresult-异步结果注解) |
| 定时执行任务（每分钟/每天凌晨等） | [@Scheduled](#3-scheduled-定时任务注解) |
| 限制接口调用频率（防刷短信/防爬） | [@RateLimit](#4-ratelimit-限流注解) |
| 调用外部服务失败时自动降级，避免雪崩 | [@CircuitBreaker](#5-circuitbreaker-熔断器注解) |
| 防止用户重复提交订单 | [@Idempotent](#6-idempotent-幂等性注解) |
| 跨进程加锁，防止多台机器并发扣库存 | [@Lock](#7-lock-分布式锁注解) |
| 单进程内方法串行执行 | [@Synchronized](#8-synchronized-方法同步注解) |

---

## 1. @Async 异步执行注解

### 是什么？

**就像把任务交给助理去办——你交代完就能去忙别的，助理在后台慢慢做，做完会通知你。** 标记了 `@Async` 的方法不会在调用方线程里同步执行，而是被丢到独立的线程/任务中运行，调用方立刻返回，不必等待方法体跑完。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |
| 参数 | 无 |

### 怎么用？

```python
from springbootai.annotations import Async, Service


@Service
class EmailService:
    @Async
    def send_email(self, to: str, subject: str):
        # 这个方法会在后台异步执行，不阻塞调用方
        import time
        time.sleep(5)  # 模拟发邮件耗时
        print(f"邮件已发送至 {to}")


# 调用方：send_email 立即返回，5 秒后才会看到打印
email_service.send_email("alice@example.com", "欢迎注册")
print("调用已返回")  # 这行会先于"邮件已发送至"打印
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 期望 `@Async` 方法立即返回结果并使用 | 异步方法的返回值不能直接拿到。需要返回值请配合 `@AsyncResult` 包装 |
| 在 `@Async` 方法里抛异常以为调用方能 catch 到 | 异步方法的异常在独立线程中抛出，调用方 catch 不到。需要在异步方法内部处理异常 |
| 把 `@Async` 加到非框架管理的对象的方法上 | `@Async` 依赖 AOP 拦截，只对框架管理的 Bean 生效，手动 `new` 出来的对象不会异步执行 |

---

## 2. @AsyncResult 异步结果注解

### 是什么？

**就像快递的"取件码"——你拿到一个凭证，凭证本身不是包裹，但可以凭它换到真正的包裹。** `@AsyncResult` 用来包装异步方法的返回值，让调用方可以通过它拿到异步计算的结果。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `async` |
| 参数 | `value: Any = None`（要包装的返回值，默认 `None`） |

### 怎么用？

```python
from springbootai.annotations import Async, AsyncResult, Service


@Service
class OrderService:
    @Async
    def create_order_async(self, user_id: str):
        # 耗时业务逻辑...
        import time
        time.sleep(3)
        result = {"order_id": "ORD-2026-0001", "user_id": user_id}
        # 用 @AsyncResult 包装返回值，调用方可凭它拿到结果
        return AsyncResult(result)


# 调用方：先拿到 AsyncResult 凭证，需要结果时再去取
future = order_service.create_order_async("U001")
# ... 这里可以继续做别的事 ...
# 需要结果时通过凭证获取（具体 API 以框架 AsyncResult 实现为准）
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 把 `@AsyncResult` 当成普通返回值直接使用 | 它是异步结果的包装/凭证，需要通过对应 API 取出真实值 |
| 同步方法里也用 `@AsyncResult` 包装返回值 | `@AsyncResult` 是为异步方法设计的，同步方法直接返回值即可 |

---

## 3. @Scheduled 定时任务注解

### 是什么？

**就像闹钟——到点自动响，不用你盯着时间。** 标记了 `@Scheduled` 的方法会按你设定的规则定时执行：可以每隔固定时间执行一次，也可以按 cron 表达式在特定时刻执行。支持同步方法和 `async def` 异步方法。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `scheduling` |
| 实现位置 | `springbootai/scheduling/scheduler.py` 的 `Scheduler` 类 |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `fixed_rate` | `Optional[int]` | `None` | 固定速率（毫秒），每隔固定时间执行一次（不管上次是否完成） |
| `fixed_delay` | `Optional[int]` | `None` | 固定延迟（毫秒），上次执行**完成后**等待固定时间再执行 |
| `cron` | `Optional[str]` | `None` | cron 表达式，支持 5 位（分 时 日 月 周）或 6 位（秒 分 时 日 月 周） |
| `initial_delay` | `int` | `0` | 初始延迟（毫秒），启动后等待多久才开始首次执行 |

> **约束**：`fixed_rate`、`fixed_delay`、`cron` 三者**必须且只能设置一个**，否则启动时会抛 `ValueError`。
>
> **cron 支持的特殊字符**：`*`（任意）、`-`（区间）、`,`（列表）、`/`（步长，如 `*/5` 表示每 5 个单位）。

### 怎么用？

```python
from springbootai.annotations import Scheduled, Service


@Service
class ReportService:
    @Scheduled(fixed_rate=60000)  # 每 60 秒执行一次
    def generate_report(self):
        print("生成日报...")

    @Scheduled(cron="0 0 2 * * ?")  # 每天凌晨 2 点执行
    def daily_cleanup(self):
        print("执行每日清理...")

    @Scheduled(fixed_delay=5000, initial_delay=10000)
    # 启动 10 秒后开始，每次执行完等 5 秒再执行
    def sync_data(self):
        print("同步数据...")

    @Scheduled(cron="*/30 * * * * *")  # 每 30 秒执行一次（6 位 cron，含秒）
    async def heartbeat(self):
        print("心跳上报...")
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 同时设置 `fixed_rate` 和 `cron` | 三选一，只能设一个。同时设多个会抛 `ValueError` |
| `fixed_rate=0` 或负数 | `fixed_rate` / `fixed_delay` 必须大于 0，`initial_delay` 不能小于 0 |
| 以为 `fixed_rate` 会等上次执行完 | `fixed_rate` 是固定周期，不管上次是否完成；要等执行完再延时用 `fixed_delay` |
| cron 表达式写成 7 位 | 本框架支持 5 位或 6 位，不支持 7 位（不含年） |

---

## 4. @RateLimit 限流注解

### 是什么？

**就像地铁早高峰限流——每分钟只放固定数量的人进站，超出的得排队等下一个窗口。** `@RateLimit` 限制方法在指定时间窗口内的调用次数，超过上限的请求会被拒绝，常用于防短信轰炸、防爬虫、保护下游服务。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_requests` | `int` | `100` | 时间窗口内允许的最大请求次数 |
| `time_window` | `int` | `60` | 时间窗口长度（秒） |
| `key` | `str` | `None` | 限流键，可按用户/IP 等维度分别限流；为空则全局限流 |

### 怎么用？

```python
from springbootai.annotations import RateLimit, RestController, PostMapping


@RestController
class SmsController:
    @PostMapping("/sms/send")
    @RateLimit(max_requests=5, time_window=60)  # 每分钟最多 5 次
    def send_sms(self, phone: str):
        return {"msg": "验证码已发送"}


@RestController
class UserController:
    @PostMapping("/user/login")
    # 按用户名分别限流：每个用户每分钟最多 3 次登录尝试
    @RateLimit(max_requests=3, time_window=60, key="{username}")
    def login(self, username: str, password: str):
        return {"msg": "登录成功"}
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 以为 `@RateLimit` 能跨多台服务器共享计数 | 默认是进程内计数，多实例部署时各算各的。要跨实例限流需接入 Redis 等共享存储 |
| `key` 写成普通字符串当全局键用 | `key` 支持 SpEL 表达式（如 `{phone}`），目的是按维度分别限流；想做全局限流就留空 |
| 把 `time_window` 单位当成毫秒 | `time_window` 单位是**秒**，而 `@Scheduled` 的 `fixed_rate` 是毫秒，别搞混 |

---

## 5. @CircuitBreaker 熔断器注解

### 是什么？

**就像家里的保险丝——电流正常时畅通无阻，一旦连续异常就自动跳闸保护电器，过一会儿再试着合闸看看恢复没有。** `@CircuitBreaker` 在方法连续失败达到阈值后进入"熔断"状态，后续调用直接快速失败（不再真正执行方法），等待恢复时间后进入"半开"状态试探性放行一次请求，成功则恢复正常，失败则继续熔断。常用于调用外部服务时防止故障雪崩。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `failure_threshold` | `int` | `5` | 失败阈值，连续失败达到此值后熔断 |
| `recovery_timeout` | `int` | `30` | 恢复超时（秒），熔断后等待此时间后尝试恢复（半开探测） |
| `fallback_method` | `str` | `None` | 降级方法名，熔断/失败时调用此方法返回兜底结果 |

### 怎么用？

```python
from springbootai.annotations import CircuitBreaker, Service


@Service
class PaymentService:
    @CircuitBreaker(
        failure_threshold=5,      # 连续失败 5 次后熔断
        recovery_timeout=30,      # 熔断 30 秒后半开探测
        fallback_method="pay_fallback",
    )
    def pay(self, order_id: str):
        # 调用第三方支付，可能失败
        return {"status": "success"}

    def pay_fallback(self, order_id: str):
        # 注意：降级方法的参数签名要与原方法一致
        return {"status": "degraded", "msg": "支付服务暂时不可用，已降级"}
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| `fallback_method` 指定的方法参数签名和原方法不一致 | 降级方法必须与原方法参数签名一致，否则框架无法正确传参 |
| 以为熔断后调用会一直阻塞等待 | 熔断期间调用会**快速失败**（走 fallback 或抛异常），不会阻塞 |
| 把 `failure_threshold` 设成 1 | 阈值=1 意味着失败一次就熔断，过于敏感，通常设 3~10 比较合理 |
| 以为 `recovery_timeout` 后就一定恢复 | `recovery_timeout` 后是进入"半开"状态试探一次，探测成功才真正恢复，失败则继续熔断 |

---

## 6. @Idempotent 幂等性注解

### 是什么？

**就像售票窗口盖"已售"章——同一张票无论你点几次购买，系统都只出一张票，后续点击直接返回已处理的结果。** `@Idempotent` 保证相同 key 的请求在过期时间内只执行一次，重复请求直接返回首次的结果，常用于防止用户重复提交订单、重复支付。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `key` | `str` | `None` | 幂等键，支持 SpEL 表达式（如 `{user_id}-{amount}`） |
| `expire` | `int` | `300` | 过期时间（秒），过期后相同 key 可再次执行 |
| `prefix` | `str` | `"idempotent"` | 键前缀，用于隔离不同业务 |

### 怎么用？

```python
from springbootai.annotations import Idempotent, RestController, PostMapping


@RestController
class OrderController:
    @PostMapping("/order/create")
    @Idempotent(key="{user_id}-{amount}", expire=10)
    # 10 秒内相同"用户+金额"的请求只处理一次
    def create_order(self, user_id: str, amount: float):
        return {"order_id": "12345"}


@RestController
class PayController:
    @PostMapping("/pay")
    # 用前缀隔离不同业务的幂等键，避免和订单创建冲突
    @Idempotent(key="{order_id}", expire=300, prefix="pay")
    def pay(self, order_id: str):
        return {"status": "success"}
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| `key` 留空 | `key` 是幂等的核心，留空会导致所有请求共用一个键，互相误判为重复 |
| `expire` 设得过短或过长 | 太短防不住网络重试，太长会误拦合法的二次操作。订单类一般 10~300 秒 |
| 用方法名当幂等键 | 方法名对所有调用都一样，起不到按业务维度判重的作用。要用业务字段（如订单号） |

---

## 7. @Lock 分布式锁注解

### 是什么？

**就像公共储物柜的钥匙——同一把钥匙同一时间只有一个人能拿到，拿到的人才能操作，操作完归还钥匙，下一个人才能用。** `@Lock` 是分布式锁，**跨进程**生效（依赖 Redis 等共享存储），保证多台机器同时只有一个请求能执行被保护的方法，常用于防止并发扣库存、并发修改同一资源。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `key` | `str` | `None` | 锁键，支持 SpEL 表达式（如 `{product_id}`） |
| `expire` | `int` | `10` | 锁过期时间（秒），防止持锁进程崩溃导致死锁 |
| `wait_timeout` | `int` | `5` | 获取锁等待超时（秒），超时未拿到锁则失败 |
| `prefix` | `str` | `"lock"` | 键前缀，用于隔离不同业务 |

### 怎么用？

```python
from springbootai.annotations import Lock, Service


@Service
class StockService:
    @Lock(key="{product_id}", expire=10, wait_timeout=5)
    # 同一商品同时只能有一个请求在扣库存
    def deduct_stock(self, product_id: str, quantity: int):
        # 此处可以安全地读取库存→判断→扣减，不会被打断
        return {"remaining": 100}


@Service
class AccountService:
    @Lock(key="{account_id}", expire=30, wait_timeout=10, prefix="transfer")
    # 转账场景：同一账户 30 秒内只允许一个操作
    def transfer(self, account_id: str, amount: float):
        return {"status": "ok"}
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 把 `expire` 设得比方法执行时间还短 | 锁过期后其他请求能抢到锁，会导致并发问题。`expire` 要略大于方法最大耗时 |
| `key` 留空导致所有调用共用一把锁 | 留空会让所有请求串行执行，失去并发能力。要按业务维度（如商品 ID）分别加锁 |
| 以为单进程内用 `@Lock` 就够了 | 单进程防并发用 `@Synchronized` 即可，开销更小。`@Lock` 适合多实例部署 |
| 依赖 `@Lock` 但没部署 Redis 等共享存储 | 分布式锁依赖共享存储实现，没配置共享存储时 `@Lock` 无法跨进程生效 |

---

## 8. @Synchronized 方法同步注解

### 是什么？

**就像公共厕所的门锁——进去的人锁门，外面的人排队等，里面的人出来下一个人才能进。** `@Synchronized` 是**进程内**的方法级同步锁，同一锁名的方法在同一时刻只有一个线程能执行，其他调用方会阻塞等待。开销比分布式锁小，适合单进程内的并发互斥。

### 注解速查表

| 属性 | 说明 |
|------|------|
| `_annotation_type` | `aop` |

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `lock_name` | `str` | `None` | 锁名称，相同锁名的方法串行执行；为空则按方法独立加锁 |

### 怎么用？

```python
from springbootai.annotations import Synchronized, Service


@Service
class CounterService:
    def __init__(self):
        self.count = 0

    @Synchronized(lock_name="counter")
    def increment(self):
        # 同一时刻只有一个线程能执行此方法
        # 即使有多个线程同时调用，也不会出现计数丢失
        current = self.count
        current += 1
        self.count = current
        return self.count


@Service
class CacheService:
    @Synchronized(lock_name="cache-refresh")
    # 不同方法用同一个 lock_name，它们之间也会串行执行
    def refresh_cache_a(self):
        ...

    @Synchronized(lock_name="cache-refresh")
    def refresh_cache_b(self):
        ...
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 多实例部署时用 `@Synchronized` 防并发 | `@Synchronized` 是进程内锁，多台机器各锁各的。跨进程要用 `@Lock` |
| 在 `@Synchronized` 方法里调用耗时 IO（如网络请求） | 同步锁会让其他线程阻塞等待，IO 耗时会拖慢所有排队请求。耗时操作应考虑用 `@Async` |
| 以为不同 `lock_name` 之间会互斥 | 只有相同 `lock_name` 才互斥，不同锁名各自独立 |

---

## 代码位置与测试

| 注解 | 实现位置 | 测试文件 |
|------|---------|---------|
| `@Async` | `springbootai/annotations/core.py` | `tests/test_async_annotation.py` |
| `@AsyncResult` | `springbootai/annotations/core.py` | `tests/test_async_annotation.py` |
| `@Scheduled` | `springbootai/scheduling/scheduler.py` | `tests/test_scheduling_module.py` |
| `@RateLimit` | `springbootai/annotations/core.py` | `tests/test_comprehensive_aop.py` |
| `@CircuitBreaker` | `springbootai/annotations/core.py` | `tests/test_comprehensive_aop.py` |
| `@Idempotent` | `springbootai/annotations/core.py` | `tests/test_comprehensive_aop.py` |
| `@Lock` | `springbootai/annotations/core.py` | `tests/test_comprehensive_aop.py` |
| `@Synchronized` | `springbootai/annotations/core.py` | `tests/test_comprehensive_aop.py` |

完整测试报告见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## FAQ

### Q1: @Async 和 @Synchronized 有什么区别？

两者方向相反：
- **`@Async`** 是"异步执行"——把方法丢到后台线程跑，**调用方不阻塞**，立刻往下走
- **`@Synchronized`** 是"同步互斥"——保证同一时刻只有一个线程能执行方法，**其他调用方会阻塞等待**

一句话：`@Async` 解决"不想等它跑完"，`@Synchronized` 解决"不能让它们同时跑"。

### Q2: @Lock 和 @Synchronized 有什么区别？

- **`@Lock`** 是**分布式锁**，跨进程生效，依赖 Redis 等共享存储，适合多实例部署
- **`@Synchronized`** 是**进程内锁**，只在本进程内生效，开销小，适合单进程并发互斥

决策建议：单进程用 `@Synchronized`（更快），多实例必须用 `@Lock`。

### Q3: @RateLimit 和 @Idempotent 有什么区别？

- **`@RateLimit`** 限制**频率**——"N 次 / 时间窗口"，允许在限额内多次成功执行，超出的拒绝
- **`@Idempotent`** 保证**唯一**——"过期时间内只执行一次"，重复请求直接返回首次结果

场景对比：防短信刷调用 `@RateLimit`，防订单重复提交用 `@Idempotent`。

### Q4: @Scheduled 的 fixed_rate 和 fixed_delay 有什么区别？

- **`fixed_rate`** 是固定周期——每隔 N 毫秒执行一次，**不管上次是否执行完**（若上次没执行完可能叠加）
- **`fixed_delay`** 是固定延迟——上次执行**完成后**再等 N 毫秒执行下一次

举例：方法本身耗时 3 秒，设 5 秒间隔：
- `fixed_rate=5000`：理论在 0s、5s、10s... 执行（实际受执行耗时影响）
- `fixed_delay=5000`：在 0s 执行，8s（0+3+5）执行第二次，16s（8+3+5）执行第三次

### Q5: @CircuitBreaker 的熔断状态有哪些？

三个状态：
1. **CLOSED（关闭）**：正常状态，请求正常通过。失败计数累加，达到 `failure_threshold` 后进入 OPEN
2. **OPEN（打开/熔断）**：请求直接快速失败（走 `fallback_method` 或抛异常），不真正执行方法。等待 `recovery_timeout` 秒后进入 HALF_OPEN
3. **HALF_OPEN（半开）**：放行一次试探请求。成功则恢复到 CLOSED，失败则回到 OPEN 继续等待

### Q6: 幂等键和锁键的 SpEL 表达式怎么写？

用 `{参数名}` 引用方法参数，支持组合：

```python
@Idempotent(key="{user_id}-{amount}")      # 用 user_id 和 amount 组合
@Lock(key="{product_id}")                  # 用 product_id
@RateLimit(key="{username}")               # 按 username 分别限流
```

框架会把这些占位符替换成实际参数值，作为键的一部分。

### Q7: 这些并发注解能叠加使用吗？

可以，但要注意顺序和语义。常见组合：

- `@RestController` + `@PostMapping` + `@RateLimit`：限流接口
- `@RestController` + `@PostMapping` + `@Idempotent`：防重复提交
- `@Service` + `@Lock` + 业务方法：防并发修改
- `@Service` + `@CircuitBreaker` + 外部调用：熔断降级

避免冲突组合，如对同一方法同时加 `@Async` 和 `@Synchronized`（一个要异步、一个要互斥，语义矛盾），需要明确你的核心诉求。
