# 测试切片 —— 只测试你关心的部分

> 框架版本：SpringBootAI 2.2.6
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 你遇到了什么问题？

每次跑测试都要启动整个应用——Web 层、数据库、缓存全部启动，慢得要死。你只想测 Controller 的请求响应，为什么要等数据库初始化？

## ① 是什么

**测试时不启动整个应用，只测你关心的那部分。** 就像检查汽车时，不需要发动整辆车，可以单独测发动机、刹车、车灯。测试切片让你只启动 Web 层或数据层，跑得更快，问题定位更准。

## ② 怎么用

```python
from spring.test import SpringBootTest, WebMvcTest, DataJpaTest

# 1. 全量上下文（集成测试）
with SpringBootTest(MyApp, config={"app": {"name": "demo"}}) as ctx:
    svc = ctx.get_bean("user_service")    # 拿到任何 Bean
    ctx.publish_event(MyEvent())          # 发布事件
# 结果：启动完整应用，什么都能测

# 2. Web 切片（只启动 Controller，不启动数据库）
with WebMvcTest(controllers=[UserController]) as mvc:
    resp = mvc.get_client().get("/api/users/42")
    print(resp.json())  # 验证 Controller 返回的数据
    # Controller 依赖的 Service 自动变成 Mock，不连真实数据库

# 3. 数据切片（只启动数据库层，不启动 Controller）
with DataJpaTest(entities=[User]) as jpa:
    repo = jpa.repository_for(User)
    repo.save(User(name="小明", age=20))
    assert repo.count() == 1
    # 数据存在内存 SQLite 中，测试结束自动销毁，不污染真实数据库
```

## 三种切片对比

| 切片 | 启动什么 | 不启动什么 | 适合测什么 |
|---|---|---|---|
| `SpringBootTest` | 全部 | 无 | 端到端集成测试 |
| `WebMvcTest` | Controller + Mock 依赖 | Service / Repository | Controller 请求响应 |
| `DataJpaTest` | 内存数据库 + Repository | Controller / Service | 数据库操作 |

## ③ 运行结果

- `WebMvcTest`：启动时间 < 1 秒（不用连数据库）
- `DataJpaTest`：启动时间 < 1 秒（不用起 Web 服务）
- 测试结束数据自动清理，不影响开发环境

## mini-FAQ

**Q：WebMvcTest 返回的数据结构是什么？**
返回的数据在 `resp.json()["data"]` 里，不是直接在根层级。这是框架统一的 Result 包装。

**Q：DataJpaTest 用的什么数据库？**
内存 SQLite，和生产环境的 MySQL/PostgreSQL 行为可能有差异（日期函数、字符集等）。

**Q：我能在 WebMvcTest 里用真实的 Service 吗？**
可以。设 `mock_dependencies=False`，然后手动注册你想用的真实 Service。
