# SpringBootAI P0/P1/P2 八大模块使用文档

> 版本：SpringBootAI Data / Actuator / Dynamic Datasource / TX Events / Config Binding / Test Slicing / i18n / WebSocket 1.0.0 ｜ 框架版本：SpringBootAI 1.8.2
> 对齐 Spring Boot / Spring Data / Spring WebSocket 的核心抽象，**无新增第三方依赖**（复用 FastAPI/Starlette/Pydantic/PyYAML 核心栈），`pip install springbootAI` 即可用。
> 设计原则：**复用项目既有范式，不重复造轮子**——注解元数据（`SpringAnnotation`）、AOP 分发（`comprehensive_aop`）、ORM 反射（`Column`/`@entity`）、`ApplicationContext` 装配全部复用。

---

## 模块总览

| 优先级 | 模块 | 包路径 | 对齐 Spring | 用例数 | 核心注解/类 |
|--------|------|--------|------------|--------|------------|
| P0-1 | Spring Data Repository 抽象 | `spring.data` | Spring Data `PagingAndSortingRepository` / `JpaSpecificationExecutor` | 55 | `Pageable`/`Sort`/`Page`/`Specification`/`PagingAndSortingRepository` |
| P0-2 | Actuator 运维端点 | `spring.web.actuator` | Spring Boot Actuator | 29 | `/actuator/health`·`/env`·`/loggers`·`/metrics`·`/info`·`/thresholds` |
| P0-3 | 多数据源读写分离 | `spring.datasource` | `dynamic-datasource-spring-boot-starter` | 34 | `@DS`/`@Master`/`@Slave`/`DynamicRoutingDataSource` |
| P1-4 | 事务事件监听 | `spring.tx` | Spring `@TransactionalEventListener` | 32 | `@TransactionalEventListener`/`TransactionSynchronizationManager` |
| P1-5 | 配置松散绑定与校验 | `spring.config.binding` | Spring Boot `@ConfigurationProperties` relaxed binding | 22 | `@NestedConfigurationProperties`/`@Validated`/`ConfigurationBinder` |
| P1-6 | 测试切片 | `spring.test` | `@SpringBootTest`/`@WebMvcTest`/`@DataJpaTest` | 19 | `SpringBootTest`/`WebMvcTest`/`DataJpaTest` |
| P2-7 | i18n 国际化 | `spring.i18n` | Spring `MessageSource`/`LocaleResolver` | 88 | `MessageSource`/`LocaleResolver`/`LocaleContextHolder` |
| P2-8 | WebSocket 实时通信 | `spring.websocket` | Spring WebSocket `@MessageMapping`/`SimpMessagingTemplate` | 63 | `@ServerEndpoint`/`@MessageMapping`/`@SendTo`/`InMemoryBroker` |

**合计 342 用例**，每个模块独立测试套件（≥10 用例），全量回归通过。

---

## 一、P0-1 Spring Data Repository 抽象（`spring.data`）

对齐 Spring Data 的 `PagingAndSortingRepository` 与 `JpaSpecificationExecutor`，提供分页、排序、动态条件查询。**复用 ORM `Column`/`@entity` 元数据解析与连接池**，不重复实现实体反射。

### 1.1 模块组成

| 文件 | 职责 |
|------|------|
| `spring/data/page.py` | `Pageable`/`Sort`/`Page`/`Order`/`Direction` 值对象（不可变） |
| `spring/data/specification.py` | `Specification` 接口 + `And`/`Or`/`Not` 复合 + `Specifications` 工具 + `Predicate`/`ColResolver` |
| `spring/data/repository.py` | `PagingAndSortingRepository` 核心实现 + `DataRepository` 别名 |

### 1.2 快速上手

```python
from spring.orm.ddl_auto import entity, Id, Column
from spring.data import PagingAndSortingRepository, Pageable, Sort, Specification

@entity("users")
class User:
    id = Id()
    name = Column("user_name")
    age = Column()
    def __init__(self, id=None, name=None, age=None):
        self.id = id; self.name = name; self.age = age

# pool 为既有 ORM 连接池（DBUtils 风格 .connection()）
repo = PagingAndSortingRepository(pool, User, dialect="mysql")

# CRUD
repo.save(User(name="Tom", age=20))
repo.save_all([User(name="A"), User(name="B")])
tom = repo.find_by_id(1)
all_users = repo.find_all()
repo.exists_by_id(1)   # True
repo.count()           # 3
repo.delete_by_id(1)
repo.delete_all()

# 分页（第 0 页，每页 10 条）
page = repo.find_all(Pageable.of(page=0, size=10))
print(page.content, page.total_elements, page.total_pages, page.has_next())

# 排序
sorted_users = repo.find_all(sort=Sort.by("user_name").descending())

# 动态条件查询（Specification）
class AdultSpec(Specification):
    def to_predicate(self, root, col_resolver):
        return ("age >= ?", [18], "AND")
adults = repo.find_all(specification=AdultSpec())

# 分页 + 排序 + 条件组合
page = repo.find_all(Pageable.of(0, 10, Sort.by("age")), specification=AdultSpec())

# 复合 Specification
from spring.data import Specifications
spec = Specifications.where(AdultSpec()).and_(AdultSpec())
```

### 1.3 与 Java Spring 的差异

- Spring Data 用 `Pageable`/`Sort` 接口 + 实现类；本实现为不可变值对象类（`__setattr__` 禁改）。
- `Specification.to_predicate` 返回 `(clause, params, operator)` 三元组，复用 ORM SQL 拼接；Spring 用 JPA `CriteriaBuilder` + `Predicate`。
- 不支持方法名派生查询（`findByNameAndAge`），需手写 `Specification`。

---

## 二、P0-2 Actuator 运维端点（`spring.web.actuator`）

扩展既有 `/health` 为完整运维端点族，对齐 Spring Boot Actuator。**敏感信息脱敏**（password/secret/key/token 掩码）。

### 2.1 端点一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/actuator` | GET | 端点索引（链接列表） |
| `/actuator/health` | GET | 健康状态 + 组件明细（UP/DOWN） |
| `/actuator/info` | GET | 应用信息（名称/版本/描述） |
| `/actuator/env` | GET | 配置项（脱敏） |
| `/actuator/loggers` | GET | 列出所有 logger 级别 |
| `/actuator/loggers/{name}` | GET/POST | 查看/动态修改 logger 级别 |
| `/actuator/metrics` | GET | 指标列表 |
| `/actuator/metrics/{name}` | GET | 单指标值 |
| `/actuator/thresholds` | GET | 阈值检查 |
| `/actuator/beans` | GET | 已注册 Bean 列表 |
| `/actuator/configprops` | GET | `@ConfigurationProperties` 绑定结果 |
| `/actuator/mappings` | GET | HTTP 路由映射 |
| `/actuator/threaddump` | GET | 线程栈快照 |

### 2.2 启用方式

```python
from spring.web.actuator import configure_actuator
# 在 WebApplicationContext.init() 后调用，注册路由到 FastAPI app
configure_actuator(app, application_context, enabled_endpoints=["health", "info", "env", "loggers", "metrics"])
```

端点可通过 `enabled_endpoints` 白名单控制；未列入的端点不注册路由。

### 2.3 脱敏规则

`/actuator/env` 对 key 含 `password`/`secret`/`key`/`token`（不区分大小写）的值用 `******` 掩码，对齐 Spring Boot `Sanitizer`。

---

## 三、P0-3 多数据源读写分离（`spring.datasource`）

对齐 `dynamic-datasource-spring-boot-starter`，通过 `@DS`/`@Master`/`@Slave` 注解在方法/类级切换数据源。**`ContextVar` 实现**线程/协程安全。

### 3.1 模块组成

| 文件 | 职责 |
|------|------|
| `spring/datasource/context.py` | `DynamicDataSourceContextHolder`（ContextVar）+ `routing_scope` 上下文管理器 |
| `spring/datasource/router.py` | `DynamicRoutingDataSource`（master/slave 池管理 + 路由） |
| `spring/datasource/annotations.py` | `@DS`/`@Master`/`@Slave` 注解 + `ds_route_decorator` AOP |

### 3.2 快速上手

```python
from spring.datasource import DynamicRoutingDataSource, DS, Master, Slave, routing_scope

# 1. 构造多数据源路由器
router = DynamicRoutingDataSource(
    master=master_pool,           # 主库连接池
    slaves={"slave1": slave_pool_1, "slave2": slave_pool_2},  # 从库池
)

# 2. 编程式路由
with routing_scope("slave1"):
    conn = router.get_connection()  # 从 slave1 取连接
conn = router.get_connection()       # 默认走 master

# 3. 注解式路由（AOP）
@Service
class UserService:
    @Master                         # 强制走主库
    def write_user(self, user): ...

    @Slave                          # 走从库（默认第一个）
    def list_users(self): ...

    @DS("slave2")                   # 指定具体从库
    def search(self): ...
```

### 3.3 线程安全与事务

- `DynamicDataSourceContextHolder` 用 `ContextVar`，线程/协程隔离，嵌套 `routing_scope` 用 token 恢复。
- 事务内路由固定：进入 `@Transactional` 后切换数据源不影响当前事务连接（对齐 Spring `@Transactional` 与数据源路由的交互）。

---

## 四、P1-4 事务事件监听（`spring.tx`）

对齐 Spring `@TransactionalEventListener`，将事件处理延迟到事务特定阶段触发。

### 4.1 事务阶段

| 阶段 | 常量 | 触发时机 |
|------|------|---------|
| 提交前 | `TransactionPhase.BEFORE_COMMIT` | 事务提交前（同步） |
| 提交后 | `TransactionPhase.AFTER_COMMIT` | 事务成功提交后 |
| 回滚后 | `TransactionPhase.AFTER_ROLLBACK` | 事务回滚后 |
| 完成后 | `TransactionPhase.AFTER_COMPLETION` | 事务完成（提交或回滚）后 |

### 4.2 快速上手

```python
from spring.tx import TransactionalEventListener, TransactionPhase, TransactionSynchronizationManager

class OrderCreatedEvent:
    def __init__(self, order_id): self.order_id = order_id

@Service
class OrderEventListener:
    @TransactionalEventListener(phase=TransactionPhase.AFTER_COMMIT)
    def on_order_created(self, event: OrderCreatedEvent):
        # 仅在事务成功提交后执行（如发通知、刷缓存）
        print(f"Order {event.order_id} committed, sending notification...")

# 发布事件（需在 @Transactional 事务内）
ctx.publish_event(OrderCreatedEvent(123))
# 事务提交后，on_order_created 才被触发
```

### 4.3 无事务时的行为

无活动事务时，`AFTER_COMMIT` 阶段的监听器**立即触发**（对齐 Spring `fallbackExecution=true` 语义），`BEFORE_COMMIT` 不触发。

---

## 五、P1-5 配置松散绑定与校验（`spring.config.binding`）

对齐 Spring Boot `@ConfigurationProperties` 的 relaxed binding（松散绑定）+ 嵌套配置 + Bean Validation 校验。

### 5.1 松散绑定规则

配置 key 的四种命名风格自动互转匹配：

| 配置文件（kebab-case） | 绑定目标字段 |
|----------------------|------------|
| `app-name` | `app_name`（snake_case） |
| `app-name` | `appName`（camelCase） |
| `app-name` | `AppName`（PascalCase） |
| `APP_NAME` | `app_name`（SCREAMING_SNAKE） |

### 5.2 快速上手

```python
from spring.annotations.core import ConfigurationProperties, Component, Validated
from spring.config.binding import NestedConfigurationProperties

@NestedConfigurationProperties
class DatabaseProps:
    url: str = ""
    pool_size: int = 5

@ConfigurationProperties("my-app")
@Component
@Validated                      # 启用 Bean Validation 校验
class MyAppProps:
    app_name: str = ""          # 绑定 my-app.app-name
    max_connections: int = 10   # 绑定 my-app.max-connections
    database: DatabaseProps = None  # 嵌套绑定 my-app.database.*
```

对应 `application.yml`：

```yaml
my-app:
  app-name: demo-app
  max-connections: 32
  database:
    url: sqlite:///mem.db
    pool-size: 10
```

### 5.3 校验集成

`@Validated` + 字段约束注解（`@NotNull`/`@NotBlank`/`@Min`/`@Max` 等）在绑定时校验，失败抛 `ValidationError`：

```python
@ConfigurationProperties("bad-app")
@Validated
class BadProps:
    name: str = ""
    port: int = 0
    # 约束：name 不能为空，port >= 1
```

```python
from spring.validation.constraints import NotBlank, Min

class BadProps:
    name: str = NotBlank()
    port: int = Min(1)
```

---

## 六、P1-6 测试切片（`spring.test`）

对齐 `@SpringBootTest`/`@WebMvcTest`/`@DataJpaTest`，提供聚焦的测试上下文。**复用 `ApplicationContext`/`WebApplicationContext`/`DdlAutoManager`/`PagingAndSortingRepository`**。

### 6.1 三种切片

| 切片 | 类 | 用途 |
|------|---|------|
| 全量上下文 | `SpringBootTest` | 装配所有 Bean，集成测试 |
| Web 切片 | `WebMvcTest` | 仅 Controller + Mock 依赖 + FastAPI TestClient |
| 数据切片 | `DataJpaTest` | 内存 SQLite + 建表 + Repository 工厂 |

### 6.2 快速上手

```python
from spring.test import SpringBootTest, WebMvcTest, DataJpaTest

# 1. 全量上下文
with SpringBootTest(MyApp, config={"app": {"name": "demo"}}) as ctx:
    svc = ctx.get_bean("user_service")
    ctx.publish_event(MyEvent())

# 2. Web 切片（Controller 单测）
with WebMvcTest(controllers=[UserController]) as mvc:
    resp = mvc.get_client().get("/api/users/42")
    assert resp.json()["data"]["id"] == 42
    ctrl = mvc.get_controller(UserController)
    ctrl.user_service.find.return_value = ...  # 配置 Mock

# 3. 数据切片（Repository 单测，内存 SQLite）
with DataJpaTest(entities=[User]) as jpa:
    repo = jpa.repository_for(User)
    repo.save(User(name="Tom", age=20))
    assert repo.count() == 1
```

### 6.3 与 Java 的差异

- Spring Boot 切片用 `ApplicationContextInitializer` 裁剪自动配置；本实现通过手动注册指定 Bean + Mock 依赖实现等价裁剪，更轻量。
- `WebMvcTest` 自动 Mock 构造函数依赖（`MagicMock`），可设 `mock_dependencies=False` 关闭。
- `WebMvcTest` 响应经 `WebApplicationContext` 的 `Result` 包装（`{code, message, data}`），业务数据在 `data` 字段。

---

## 七、P2-7 i18n 国际化（`spring.i18n`）

对齐 Spring `MessageSource`/`LocaleResolver`/`LocaleContextHolder`，提供多语言消息管理。**无可选依赖**（properties/YAML 用标准库 + PyYAML）。

### 7.1 模块组成

| 文件 | 职责 |
|------|------|
| `locale.py` | `Locale`（parse/to_string/to_language_tag/matches）+ 预定义常量 |
| `message_source.py` | `MessageSource` 接口 + `AbstractMessageSource` + locale 回退 |
| `sources.py` | `StaticMessageSource`/`ResourceBundleMessageSource`/`DelegatingMessageSource` |
| `locale_resolver.py` | `AcceptHeaderLocaleResolver`/`FixedLocaleResolver`/`SessionLocaleResolver`/`CookieLocaleResolver` |
| `holder.py` | `LocaleContextHolder`（ContextVar 线程安全） |
| `accessor.py` | `MessageSourceAccessor`（便捷 getMessage） |
| `properties.py` | `load_properties`/`parse_properties`（续行/转义/Unicode） |
| `middleware.py` | `LocaleResolverMiddleware` + `get_request_locale` |
| `auto_config.py` | `MessageSourceAutoConfiguration` + `configure_message_source` |

### 7.2 快速上手

```python
from spring.i18n import (
    ResourceBundleMessageSource, Locale, LOCALE_CHINA, LOCALE_US,
    AcceptHeaderLocaleResolver, LocaleResolverMiddleware, LocaleContextHolder,
)

# 1. 资源目录：messages.properties / messages_zh_CN.properties / messages_en_US.properties
src = ResourceBundleMessageSource(basenames=["messages"], base_dir="./i18n")

# 2. 按 locale 取消息（支持 locale 回退：en_US → en → 默认）
msg = src.getMessage("greeting", ["Tom"], Locale("zh", "CN"))   # 你好，Tom！
msg = src.getMessage("greeting", ["Tom"], Locale("en", "US"))   # Hello, Tom!

# 3. 中间件：从 Accept-Language 头解析 locale 写入 LocaleContextHolder
app.add_middleware(
    LocaleResolverMiddleware,
    locale_resolver=AcceptHeaderLocaleResolver(
        supported_locales=[Locale("zh", "CN"), Locale("en", "US")],
        default_locale=Locale("en"),
    ),
)
```

### 7.3 locale 回退链

请求 `zh_TW` 但只有 `messages_zh_CN.properties` 与 `messages.properties`：
`zh_TW`（精确未命中）→ `zh`（语言未命中）→ 默认 `messages.properties`。

### 7.4 properties 解析

支持 Java properties 格式：`=`/`:`/空白分隔符、`#`/`!` 注释、`\` 续行、`\n`/`\t` 转义、`\uXXXX` Unicode、UTF-8 中文。

---

## 八、P2-8 WebSocket 实时通信（`spring.websocket`）

对齐 Spring WebSocket 的 `@MessageMapping`/`@SendTo`/`SimpMessagingTemplate`，提供注解驱动的 WebSocket 端点 + 内存消息代理。**复用 FastAPI/Starlette WebSocket**。

### 8.1 模块组成

| 文件 | 职责 |
|------|------|
| `session.py` | `WebSocketSession`（send_text/send_bytes/close）+ `WebSocketSessionRegistry` |
| `handler.py` | `WebSocketHandler` 基类 + `@ServerEndpoint` + `AnnotatedEndpointHandler` |
| `annotations.py` | `@MessageMapping`/`@SendTo`/`@SendToUser`/`@SubscribeMapping` + `MessageMappingModel` |
| `broker.py` | `InMemoryBroker`（pub/sub）+ `SimpMessageSendingOperations` |
| `router.py` | `WebSocketRouter`（install 到 FastAPI）+ `MessageEndpointDispatcher` |

### 8.2 快速上手 —— @ServerEndpoint（JSR-356 风格）

```python
from spring.websocket import ServerEndpoint

@ServerEndpoint("/ws/echo")
class EchoEndpoint:
    async def on_open(self, session):
        await session.send_text("welcome")

    async def on_message(self, session, message):
        await session.send_text("echo: " + message)

    async def on_close(self, session, reason):
        pass
```

### 8.3 快速上手 —— @MessageMapping（Spring STOMP 风格）

```python
from spring.websocket import ServerEndpoint, MessageMapping, SendTo, SendToUser

@ServerEndpoint("/ws/chat")
class ChatEndpoint:
    @MessageMapping("/chat.send")
    @SendTo("/topic/messages")          # 广播到所有订阅者
    def send_message(self, message):
        return {"text": message}

    @MessageMapping("/chat.private")
    @SendToUser                          # 仅回发给发送者
    def private_message(self, message, session):
        return {"text": "private: " + message}
```

### 8.4 安装到 FastAPI

```python
from spring.websocket import WebSocketRouter, discover_server_endpoints

router = WebSocketRouter()
for endpoint_cls in discover_server_endpoints():   # 自动发现 @ServerEndpoint
    router.add_endpoint(endpoint_cls.__spring_endpoint_path__, endpoint_cls)
router.install(app)   # 注册 WebSocket 路由到 FastAPI/Starlette
```

### 8.5 InMemoryBroker（pub/sub）

```python
from spring.websocket import InMemoryBroker, broker_registry

broker = broker_registry.broker
broker.subscribe(session_id, "/topic/messages")   # 订阅
broker.publish("/topic/messages", {"text": "hi"})  # 推送到所有订阅者
broker.send_to_user(session_id, {"text": "private"})  # 单播
broker.broadcast({"text": "broadcast"})            # 全员广播
```

---

## 九、与 Java Spring 的对齐与差异总结

### 9.1 对齐点

- **注解元数据范式**：全部复用 `SpringAnnotation` 描述符（`_annotation_type` + `__spring_annotations__`），与既有 `@Service`/`@Component`/`@Cacheable` 一致。
- **AOP 分发**：`@DS`/`@TransactionalEventListener` 复用 `comprehensive_aop.ANNOTATION_DECORATORS` + `apply_annotations` 路径。
- **IoC 装配**：`@ConfigurationProperties`/`@NestedConfigurationProperties` 复用 `ApplicationContext._register_configuration_beans`。
- **ContextVar**：`DynamicDataSourceContextHolder`/`LocaleContextHolder`/`TransactionSynchronizationManager` 均用 `ContextVar` 实现线程/协程安全（对齐 Spring `ThreadLocal` 但原生支持 async）。

### 9.2 差异与限制

| 模块 | Java Spring | SpringBootAI 差异 |
|------|------------|--------------|
| Spring Data | 方法名派生查询（`findByName`） | 不支持，需手写 `Specification` |
| Actuator | `ManagementServerConfig` 独立端口 | 复用主应用端口，路由前缀 `/actuator` |
| 多数据源 | `AbstractRoutingDataSource` + `determineCurrentLookupKey` | `DynamicRoutingDataSource` + `ContextVar`，语义等价 |
| 事务事件 | `TransactionSynchronization` 接口回调 | `TransactionSynchronizationManager` 注册回调，无事务时立即触发 |
| 配置绑定 | SpEL + `@ConfigurationPropertiesBinding` | 不支持 SpEL，字符串等值匹配；松散绑定对齐 |
| 测试切片 | `ApplicationContextInitializer` 裁剪自动配置 | 手动注册指定 Bean + Mock 依赖 |
| i18n | `ResourceBundle` + `MessageSource` SPI | `ResourceBundleMessageSource` 读 properties/YAML 文件 |
| WebSocket | STOMP 协议 + `SimpMessagingTemplate` | 内存 broker（非 STOMP），`@MessageMapping` 路由语义对齐 |

---

## 十、测试覆盖

八大模块共 **342 用例**，每个模块独立测试套件（≥10 用例），全量回归通过。详见 [TEST_REPORT.md](TEST_REPORT.md) 第 2.6 节。

| 测试文件 | 用例数 | 模块 |
|---------|--------|------|
| test_data_repository.py | 55 | P0-1 |
| test_actuator.py | 29 | P0-2 |
| test_datasource_routing.py | 34 | P0-3 |
| test_transactional_events.py | 32 | P1-4 |
| test_config_binding.py | 22 | P1-5 |
| test_test_slicing.py | 19 | P1-6 |
| test_i18n_module.py | 88 | P2-7 |
| test_websocket_module.py | 63 | P2-8 |
