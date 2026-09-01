# 事务事件 —— 操作完成后自动发通知

> SpringBootAI 2.3.11
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 你遇到了什么问题？

用户下单后要发短信通知。但如果短信发出去了、订单保存却失败了，用户收到短信但根本没有订单——这就尴尬了。你需要的顺序是：**先确保订单保存成功，再发短信**。

## ① 是什么

**"先存好，再说"**——等数据库事务提交成功后再执行某个操作（发短信、发邮件、刷新缓存）。事务回滚了，这些操作就不执行。

## ② 怎么用

```python
from springbootai.tx import TransactionalEventListener, TransactionPhase

# 定义事件
class OrderCreatedEvent:
    def __init__(self, order_id):
        self.order_id = order_id

# 事件监听器
@Service
class OrderEventListener:
    @TransactionalEventListener(phase=TransactionPhase.AFTER_COMMIT)
    def on_order_created(self, event: OrderCreatedEvent):
        # 这个只在事务成功提交后才执行！
        print(f"订单 {event.order_id} 已保存，正在发送通知...")
        # 输出: 订单 123 已保存，正在发送通知...

# 在 @Transactional 方法中发布事件
ctx.publish_event(OrderCreatedEvent(123))
```

## 事务阶段说明

| 阶段 | 什么时候触发 | 干什么用 |
|---|---|---|
| `BEFORE_COMMIT` | 事务提交前（同步执行） | 提交前的最后校验 |
| `AFTER_COMMIT` | 事务成功提交后 | **最常用**：发通知、刷新缓存 |
| `AFTER_ROLLBACK` | 事务回滚后 | 记录回滚日志、清理补偿数据 |
| `AFTER_COMPLETION` | 事务完成（无论成败） | 释放资源、清理临时数据 |

## ③ 运行结果

- 订单保存成功 → 事务提交 → `AFTER_COMMIT` 触发 → 发短信 ✅
- 订单保存失败 → 事务回滚 → `AFTER_COMMIT` 不触发 → 不发短信 ✅

## mini-FAQ

**Q：在事务外发布事件会怎样？**
监听器会立即执行（因为根本没有事务），和普通函数调用一样。

**Q：监听器抛异常会回滚事务吗？**
不会。`AFTER_COMMIT` 时事务已经提交了，监听器异常只会打日志。如果监听逻辑也必须成功，用消息队列做重试。

**Q：监听器里能再开新事务吗？**
不建议。避免嵌套事务和不必要的复杂度。

---

## 普通应用事件：@ApplicationEvent + @EventListener

事务事件需要 `@TransactionalEventListener`（只在事务提交后触发）。如果你不需要事务——比如用户注册后发欢迎邮件、配置变更后刷新缓存——用普通应用事件更简单。

### 是什么？

**`@ApplicationEvent` 定义事件，`@EventListener` 监听事件。** 就像广播站——有人广播"用户注册了"，所有调到这个频道的收音机（监听器）同时收到消息。

### 怎么用？

```python
from springbootai.annotations import Service, EventListener
from springbootai.annotations.core import ApplicationEvent
from springbootai.context.application_context import ApplicationContext

# 1. 定义事件（继承 ApplicationEvent）
class UserRegisteredEvent(ApplicationEvent):
    def __init__(self, source=None, user_id=None, email=None):
        super().__init__(source=source)
        self.user_id = user_id
        self.email = email

# 2. 监听事件
@Service
class UserEventListener:

    @EventListener(UserRegisteredEvent)  # 监听 UserRegisteredEvent
    def on_user_registered(self, event: UserRegisteredEvent):
        print(f"发送欢迎邮件到 {event.email}")
        # 输出: 发送欢迎邮件到 alice@example.com

# 3. 发布事件
ctx = ApplicationContext()
ctx.publish_event(UserRegisteredEvent(user_id=1, email="alice@example.com"))
```

### 事件 vs 事务事件

| 特性 | `@EventListener` | `@TransactionalEventListener` |
|------|------------------|-------------------------------|
| 触发时机 | 发布即触发 | 事务提交/回滚后才触发 |
| 依赖事务 | 否 | 是 |
| 典型场景 | 发邮件、刷新缓存、记录日志 | 订单提交后发通知、事务回滚后清理 |

### 参数说明

**@EventListener：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `event_type` | `Type[ApplicationEvent]` | 监听的事件类型（不填则监听所有事件） |
| `order` | `int` | 执行顺序（小的先执行，默认 0） |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| 事件类不继承 `ApplicationEvent` | 必须继承，否则 `@EventListener` 无法匹配 |
| 在监听器里做耗时操作阻塞发布方 | 耗时操作用 `@Async` 异步执行或用消息队列 |
| 以为 `@EventListener` 能替代事务事件 | 需要事务保证的操作必须用 `@TransactionalEventListener` |
