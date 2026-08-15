# 多数据源 —— 读写分离

> 框架版本：SpringBootAI 2.2.6
> 返回 [README 模块导航](../README.md#模块文档导航)

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

---

## 改进记录

### 连接池泄漏检测仅告警不强制回收 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`spring/orm/pymybatis/pool/connection_pool.py` _detect_leaks()

**现象**：`_detect_leaks()` 检测到连接借出时间超过 `leak_timeout` 后，仅 `logger.warning()`，不强制回收连接。泄漏的连接会一直占用配额，最终耗尽连接池。

**改进方案**：增加配置项 `leak_recovery_enabled`（默认 True），超时后强制 `mark_free()` + `_dispose_connection()`。回收前尝试 `connection.rollback()` 清理未提交事务。

### Docker IP 自动检测每次连接失败都调用 subprocess — 中 ⏳ 待处理 (v2.3.0)

**位置**：`spring/orm/pymybatis/pool/connection_pool.py` _detect_docker_ip()

**现象**：MySQL 连接失败且 host 为 localhost/127.0.0.1 时，每次都会 `subprocess.run(['docker', 'ps', ...])`。非 Docker 环境下每次约 100-300ms 无意义开销。

**改进方案**：缓存检测结果（进程级），同一端口只检测一次；检测失败后设置负缓存（60 秒内不再重试）；增加配置开关 `datasource.docker_auto_detect`（默认 False）。

### is_valid() 连接有效性检查逻辑不完整 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`spring/orm/pymybatis/pool/connection_pool.py` is_valid()

**现象**：没有 `ping` 也没有 `isclosed` 的连接（如某些 SQLite 实现）永远返回 True，无法检测真实有效性。

**改进方案**：兜底执行轻量查询 `SELECT 1` 验证连接有效性。

### SQLite 连接池 check_same_thread=False 的线程安全风险 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`spring/orm/pymybatis/pool/connection_pool.py` SQLite 连接创建

**现象**：SQLite 连接设置 `check_same_thread=False` 允许跨线程使用，但多线程并发写入可能导致 `database is locked`。

**改进方案**：启用 WAL 模式 `PRAGMA journal_mode=WAL`，文档中明确说明 SQLite 连接池适用于开发/测试，生产环境应使用 MySQL/PostgreSQL。
