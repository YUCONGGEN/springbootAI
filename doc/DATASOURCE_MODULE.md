# 多数据源 —— 读写分离

> 框架版本：SpringBootAI 2.2.5
> 返回 [八大模块总览](EIGHT_MODULES.md)

---

## 你遇到了什么问题？

数据库压力太大，查询和写入挤在一台机器上。你想把查询路由到从库，写入路由到主库——但不想在代码里手动切换连接。

## ① 是什么

**读写分离——查询走从库，写入走主库。** 就像超市收银台（写入）和购物通道（读取）分开，互不干扰。主库负责写入保证数据一致，从库负责读取分担压力。

## ② 怎么用

```python
from spring.datasource import DynamicRoutingDataSource, DS, Master, Slave, routing_scope

# 1. 构造多数据源路由器
router = DynamicRoutingDataSource(
    master=master_pool,                                 # 主库连接池（写入）
    slaves={"slave1": slave_pool_1, "slave2": slave_pool_2},  # 从库池（读取）
)

# 2. 编程式切换：with 块内走从库，块外走主库
with routing_scope("slave1"):
    conn = router.get_connection()  # 这个连接来自 slave1
# 出了 with 块，又回到主库

# 3. 注解式切换（更常用）
@Service
class UserService:
    @Master                               # 强制走主库
    def create_user(self, user):
        # 写入操作，走主库
        pass

    @Slave                                # 走从库（默认第一个）
    def list_users(self):
        # 查询操作，走从库
        pass

    @DS("slave2")                         # 指定走 slave2
    def search_users(self, keyword):
        # 查特定从库
        pass
```

## ③ 运行结果

加了 `@Master` 的方法，所有数据库操作走主库。加了 `@Slave` 的方法，所有数据库操作走从库。你不用在代码里写任何连接切换逻辑。

## mini-FAQ

**Q：刚写入主库的数据，马上去从库查，能查到吗？**
不一定。主从同步有延迟（通常几十毫秒到几秒）。写入后立即需要读最新数据的场景，应该在读取方法上标注 `@Master`。

**Q：事务中能切换数据源吗？**
不能。一个事务只绑定一个数据库连接，事务中途切换数据源不会生效。

**Q：从库挂了怎么办？**
框架默认路由到第一个从库，不可用会报错。需要配置连接超时和重试，或者做从库故障转移。
