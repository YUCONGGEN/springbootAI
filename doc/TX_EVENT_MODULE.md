# 事务事件 —— 操作完成后自动发通知

> 框架版本：SpringBootAI 2.2.6
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 你遇到了什么问题？

用户下单后要发短信通知。但如果短信发出去了、订单保存却失败了，用户收到短信但根本没有订单——这就尴尬了。你需要的顺序是：**先确保订单保存成功，再发短信**。

## ① 是什么

**"先存好，再说"**——等数据库事务提交成功后再执行某个操作（发短信、发邮件、刷新缓存）。事务回滚了，这些操作就不执行。

## ② 怎么用

```python
from spring.tx import TransactionalEventListener, TransactionPhase

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
