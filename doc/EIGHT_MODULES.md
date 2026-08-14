# SpringBootAI 八大模块 —— 总览索引

> 框架版本：SpringBootAI 2.2.5
> 八大模块彼此独立，按需选用，不要为了"功能齐全"一次全部接入。

---

## 快速选择指南 —— 你想解决什么问题？

```
你遇到的问题                                 → 看哪个模块？          → 一句话
──────────────────────────────────────────────────────────────────────────────
列表接口需要分页、排序、条件筛选              → 一、Repository        → 不用手写SQL的分页查询
运维想看系统状态、配置、内存、线程           → 二、Actuator          → 系统健康检查面板
数据库压力大，想把查询和写入分开             → 三、多数据源           → 读写分离
下单后要发短信通知，但必须等存完才发         → 四、事务事件           → 操作完成后自动发通知
YAML 配置太长，想自动变成 Python 对象        → 五、配置绑定           → 把YAML配置自动变成Python对象
写测试不想启动整个应用，太慢了               → 六、测试切片           → 只测试你关心的部分
网站要做中英文切换                           → 七、i18n              → 中英文自动切换
浏览器需要实时推送消息（聊天、通知）         → 八、WebSocket         → 像微信一样实时通信
```

> **怎么选？** 遇到什么问题就看对应的那一节。不用从头读到尾。

---

## 模块文档索引

| # | 模块 | 独立文档 | 一句话说明 |
|---|------|----------|-----------|
| 一 | Spring Data Repository | [REPOSITORY_MODULE.md](REPOSITORY_MODULE.md) | 不用手写SQL的分页查询 |
| 二 | Actuator | [ACTUATOR_MODULE.md](ACTUATOR_MODULE.md) | 系统健康检查面板 + Spring Boot Admin 可视化 + Prometheus 指标 |
| 三 | 多数据源 | [DATASOURCE_MODULE.md](DATASOURCE_MODULE.md) | 读写分离 |
| 四 | 事务事件 | [TX_EVENT_MODULE.md](TX_EVENT_MODULE.md) | 操作完成后自动发通知 |
| 五 | 配置绑定 | [CONFIG_BINDING_MODULE.md](CONFIG_BINDING_MODULE.md) | 把YAML配置自动变成Python对象 |
| 六 | 测试切片 | [TEST_SLICE_MODULE.md](TEST_SLICE_MODULE.md) | 只测试你关心的部分 |
| 七 | i18n | [I18N_MODULE.md](I18N_MODULE.md) | 中英文自动切换 |
| 八 | WebSocket | [WEBSOCKET_MODULE.md](WEBSOCKET_MODULE.md) | 像微信一样实时通信 |

---

## 新手常见错误 ❌/✅

| # | ❌ 错误做法 | ✅ 正确做法 |
|---|---|---|
| 1 | 分页用 `Pageable.of(page=1, size=10)` 以为是第一页 | 页码从 0 开始：`Pageable.of(page=0, size=10)` 才是第一页 |
| 2 | 排序字段没建索引，大数据量分页巨慢 | 在数据库中给 `Sort.by()` 的字段建索引 |
| 3 | `/actuator` 暴露到公网，所有人都能看到 | 用 Nginx IP 白名单或网关认证，`enabled_endpoints` 只开需要的 |
| 4 | 主库写入后立刻从库读取，发现数据"丢了" | 主从有延迟，强一致读要用 `@Master` |
| 5 | 事务外发布事件，监听器立即执行 | 必须在 `@Transactional` 方法内 `publish_event` |
| 6 | 嵌套配置类忘了加 `@NestedConfigurationProperties` | 嵌套类必须加这个注解，否则子字段不绑定 |
| 7 | WebMvcTest 断言 `resp.json()["id"]` 取不到值 | 数据在 `resp.json()["data"]["id"]`，框架有统一的 Result 包装 |
| 8 | 用 `requests` 库测试 WebSocket | 用 `websockets` 库，WebSocket 不是 HTTP |

---

## 模块总览表

| 模块 | 用途 | 核心类/注解 | 安装方式 |
|---|---|---|---|
| Spring Data Repository | 分页、排序、条件查询 | `PagingAndSortingRepository` / `Pageable` / `Specification` | 自带，无需额外安装 |
| Actuator | 健康检查、配置查看、指标监控 | `/actuator/health` 等端点 | 自带，无需额外安装 |
| 多数据源 | 读写分离 | `@Master` / `@Slave` / `@DS` | 自带，无需额外安装 |
| 事务事件 | 事务提交后触发操作 | `@TransactionalEventListener` | 自带，无需额外安装 |
| 配置绑定 | YAML→Python 对象 | `@ConfigurationProperties` | 自带，无需额外安装 |
| 测试切片 | 只启动部分组件做测试 | `WebMvcTest` / `DataJpaTest` | 自带，无需额外安装 |
| i18n | 多语言自动切换 | `MessageSource` / `LocaleResolver` | 自带，无需额外安装 |
| WebSocket | 实时双向通信 | `@ServerEndpoint` / `@MessageMapping` | 自带，无需额外安装 |

> 八大模块共 342 个测试用例，全量回归通过。详见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## FAQ

### Q1：这八个模块之间有什么关系？

没有关系。它们是八个独立的功能，遇到什么问题就用对应的模块。不要为了"功能齐全"一次全部接入。

### Q2：安装需要额外依赖吗？

不需要。八大模块全部复用 FastAPI/Starlette/Pydantic/PyYAML 核心栈，`pip install springbootAI` 即可用。

### Q3：和 Java Spring 有差异吗？

有的，详见下方对比表。核心思路对齐 Spring，但实现细节因语言特性而不同。

| 模块 | Python 版与 Java 版的主要差异 |
|---|---|
| Repository | 不支持方法名派生查询（`findByName`），需手写 `Specification` |
| Actuator | 复用主应用端口（路径前缀 `/actuator`），无独立端口 |
| 多数据源 | `ContextVar` 代替 `ThreadLocal`，语义等价 |
| 事务事件 | 无事务时 `AFTER_COMMIT` 立即触发 |
| 配置绑定 | 不支持 SpEL 表达式 |
| 测试切片 | 手动注册 Bean + Mock，而非裁剪自动配置 |
| i18n | 读 properties/YAML 文件，而非 Java ResourceBundle |
| WebSocket | 内存 broker（非 STOMP 协议） |
