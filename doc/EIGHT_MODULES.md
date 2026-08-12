# SpringBootAI 八大模块 —— 小白也能看懂的实用功能指南

> 框架版本：SpringBootAI 2.2.0
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

## 一、Spring Data Repository —— 不用手写SQL的分页查询

### 你遇到了什么问题？

前端请求"第 1 页，每页 20 条，按创建时间倒序"。你要手写 `SELECT COUNT(*)`、`LIMIT`、`OFFSET`、`ORDER BY`……每个列表接口都写一遍，烦得要死还容易出错。

### ① 是什么

**把数据库查询变成翻书操作。** 你只需要告诉框架：第几页、每页几条、按什么排序，框架自动生成 SQL 并把结果装进对象里。就像你去图书馆借书，跟管理员说"我要第 3 排第 5 本"，不用自己翻。

### ② 怎么用

```python
from spring.orm.ddl_auto import entity, Id, Column
from spring.data import PagingAndSortingRepository, Pageable, Sort, Specification

# 定义实体（数据库表对应的类）
@entity("users")
class User:
    id = Id()
    name = Column("user_name")
    age = Column()
    def __init__(self, id=None, name=None, age=None):
        self.id = id; self.name = name; self.age = age

# pool 是你的数据库连接池（和 ORM 共用）
repo = PagingAndSortingRepository(pool, User, dialect="mysql")

# --- 基础 CRUD ---
repo.save(User(name="小明", age=20))
repo.save_all([User(name="小红"), User(name="小刚")])

user = repo.find_by_id(1)
print(user)  # 输出: User(id=1, name="小明", age=20)

all_users = repo.find_all()          # 查全部
repo.exists_by_id(1)                 # 输出: True
repo.count()                         # 输出: 3
repo.delete_by_id(1)                 # 删一条
repo.delete_all()                    # 删全部

# --- 分页：第 0 页，每页 10 条 ---
page = repo.find_all(Pageable.of(page=0, size=10))
print(page.content)           # 当前页数据列表
print(page.total_elements)    # 总条数，如 30
print(page.total_pages)       # 总页数，如 3
print(page.has_next())        # 还有下一页吗？True

# --- 排序：按年龄降序 ---
sorted_users = repo.find_all(sort=Sort.by("user_name").descending())
# 结果：按 user_name 字段 Z→A 排列

# --- 条件筛选：只查成年人 ---
class AdultSpec(Specification):
    def to_predicate(self, root, col_resolver):
        return ("age >= ?", [18], "AND")  # 参数绑定防 SQL 注入

adults = repo.find_all(specification=AdultSpec())
# 结果：只返回 age >= 18 的用户

# --- 分页 + 排序 + 筛选 三合一 ---
page = repo.find_all(
    Pageable.of(0, 10, Sort.by("age")),
    specification=AdultSpec()
)
# 结果：第 0 页、每页 10 条、按年龄排序、而且只要成年人

# --- 复合条件：成年 AND 名字包含"明" ---
from spring.data import Specifications
spec = Specifications.where(AdultSpec()).and_(NameSpec())
```

### ③ 运行结果

你只需调用一个 `repo.find_all(Pageable.of(page=0, size=10))`，框架自动执行：
- 一条 `SELECT COUNT(*)` 查总条数
- 一条 `SELECT ... LIMIT 10 OFFSET 0` 查当前页数据
- 返回封装好的 `Page` 对象，包含数据、总页数、总条数、是否有下一页

### 模块 mini-FAQ

**Q：页码从 0 还是从 1 开始？**
从 0 开始。`Pageable.of(page=0, size=10)` 是第一页。`page=1` 是第二页。

**Q：大数据量分页慢怎么办？**
确保 `Sort.by()` 的字段在数据库中有索引。另外总条数查询（`SELECT COUNT(*)`）在大表上可能较慢。

**Q：能像 Java Spring 那样写 `findByNameAndAge` 吗？**
不支持方法名派生查询。需要用 `Specification` 手写条件。

---

## 二、Actuator —— 系统健康检查面板

### 你遇到了什么问题？

应用上线后出问题了——内存够不够？数据库连不连得上？哪些配置生效了？你没法钻到服务器里看，线上又不能随便打断点调试。

### ① 是什么

**给应用装一个"体检仪"**——一个内置的管理页面，随时查看应用健康状态、配置、内存、线程等。就像体检时用各种仪器检查身体各项指标，看到系统是否正常运行。

### ② 怎么用

```python
from spring.web.actuator import configure_actuator

# 在应用初始化后注册端点
configure_actuator(
    app,
    application_context,
    enabled_endpoints=["health", "info", "env", "loggers", "metrics"]
)
# 结果：访问 http://127.0.0.1:8080/actuator/health 即可查看健康状态
```

### 端点一览

| 端点地址 | 干什么用 | 什么时候用 |
|---|---|---|
| `/actuator` | 所有可用端点列表 | 看有哪些端点 |
| `/actuator/health` | 健康状态（UP/DOWN） | K8s/Docker 健康检查首选 |
| `/actuator/info` | 应用名称、版本 | 确认当前部署版本 |
| `/actuator/env` | 全部配置项（密码自动打码） | 排查配置是否生效 |
| `/actuator/loggers` | 列出所有日志级别 | 查看当前日志级别 |
| `/actuator/loggers/{name}` | 查看/修改某个 logger 级别 | 临时开 DEBUG 排查问题 |
| `/actuator/metrics` | 指标列表 | 监控系统拉取指标 |
| `/actuator/metrics/{name}` | 单个指标数值 | 查某个具体指标 |
| `/actuator/beans` | 已注册的所有 Bean | 排查 Bean 是否都注册了 |
| `/actuator/mappings` | 所有 HTTP 路由 | 确认接口路由是否注册成功 |
| `/actuator/threaddump` | 线程快照 | 排查死锁、卡死问题 |
| `/actuator/configprops` | 配置绑定结果 | 确认配置绑定是否正确 |
| `/actuator/thresholds` | 自定义阈值检查 | 自定义健康规则 |

### ③ 运行结果

访问 `http://127.0.0.1:8080/actuator/health`：

```json
{
  "status": "UP",
  "components": {
    "db": {"status": "UP", "detail": "Connected"},
    "diskSpace": {"status": "UP", "detail": "free: 50GB"}
  }
}
```

### 模块 mini-FAQ

**Q：生产环境能把 /actuator 暴露到公网吗？**
绝对不能！通过 Nginx 或网关做 IP 白名单或加认证。

**Q：/actuator/env 会泄露密码吗？**
不会。框架自动对 key 含 `password`/`secret`/`key`/`token` 的值用 `******` 掩码。

**Q：threaddump 要一直开着吗？**
不要。只在排查死锁问题时临时开启，平时关掉（它会暴露代码路径）。

---

## 三、多数据源 —— 读写分离

### 你遇到了什么问题？

数据库压力太大，查询和写入挤在一台机器上。你想把查询路由到从库，写入路由到主库——但不想在代码里手动切换连接。

### ① 是什么

**读写分离——查询走从库，写入走主库。** 就像超市收银台（写入）和购物通道（读取）分开，互不干扰。主库负责写入保证数据一致，从库负责读取分担压力。

### ② 怎么用

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

### ③ 运行结果

加了 `@Master` 的方法，所有数据库操作走主库。加了 `@Slave` 的方法，所有数据库操作走从库。你不用在代码里写任何连接切换逻辑。

### 模块 mini-FAQ

**Q：刚写入主库的数据，马上去从库查，能查到吗？**
不一定。主从同步有延迟（通常几十毫秒到几秒）。写入后立即需要读最新数据的场景，应该在读取方法上标注 `@Master`。

**Q：事务中能切换数据源吗？**
不能。一个事务只绑定一个数据库连接，事务中途切换数据源不会生效。

**Q：从库挂了怎么办？**
框架默认路由到第一个从库，不可用会报错。需要配置连接超时和重试，或者做从库故障转移。

---

## 四、事务事件 —— 操作完成后自动发通知

### 你遇到了什么问题？

用户下单后要发短信通知。但如果短信发出去了、订单保存却失败了，用户收到短信但根本没有订单——这就尴尬了。你需要的顺序是：**先确保订单保存成功，再发短信**。

### ① 是什么

**"先存好，再说"**——等数据库事务提交成功后再执行某个操作（发短信、发邮件、刷新缓存）。事务回滚了，这些操作就不执行。

### ② 怎么用

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

### 事务阶段说明

| 阶段 | 什么时候触发 | 干什么用 |
|---|---|---|
| `BEFORE_COMMIT` | 事务提交前（同步执行） | 提交前的最后校验 |
| `AFTER_COMMIT` | 事务成功提交后 | **最常用**：发通知、刷新缓存 |
| `AFTER_ROLLBACK` | 事务回滚后 | 记录回滚日志、清理补偿数据 |
| `AFTER_COMPLETION` | 事务完成（无论成败） | 释放资源、清理临时数据 |

### ③ 运行结果

- 订单保存成功 → 事务提交 → `AFTER_COMMIT` 触发 → 发短信 ✅
- 订单保存失败 → 事务回滚 → `AFTER_COMMIT` 不触发 → 不发短信 ✅

### 模块 mini-FAQ

**Q：在事务外发布事件会怎样？**
监听器会立即执行（因为根本没有事务），和普通函数调用一样。

**Q：监听器抛异常会回滚事务吗？**
不会。`AFTER_COMMIT` 时事务已经提交了，监听器异常只会打日志。如果监听逻辑也必须成功，用消息队列做重试。

**Q：监听器里能再开新事务吗？**
不建议。避免嵌套事务和不必要的复杂度。

---

## 五、配置绑定 —— 把 YAML 配置自动变成 Python 对象

### 你遇到了什么问题？

配置文件越来越长，你手写 `config["my-app"]["app-name"]` 取配置，字段名打错了要到运行时才报错，IDE 也没有提示。

### ① 是什么

**把 YAML 配置文件自动变成 Python 对象。** 你不用手动 `yaml.load()` 然后逐字段读取，框架自动把 `application.yml` 里的内容填进你定义的类，还帮你检查格式对不对。

### ② 怎么用

`application.yml`：

```yaml
my-app:
  app-name: demo-app
  max-connections: 32
  database:
    url: sqlite:///mem.db
    pool-size: 10
```

Python 代码：

```python
from spring.annotations.core import ConfigurationProperties, Component, Validated
from spring.config.binding import NestedConfigurationProperties

# 嵌套配置类
@NestedConfigurationProperties
class DatabaseProps:
    url: str = ""
    pool_size: int = 5     # 对应 YAML 的 pool-size（框架自动转换命名风格）

# 主配置类
@ConfigurationProperties("my-app")  # 绑定 my-app 前缀下的所有配置
@Component
@Validated                           # 启用字段校验
class MyAppProps:
    app_name: str = ""               # 绑定 my-app.app-name
    max_connections: int = 10        # 绑定 my-app.max-connections
    database: DatabaseProps = None   # 绑定 my-app.database.*
    # 结果：启动后这些字段自动填好，你不用写一行 yaml.load()
```

### 松散绑定规则（命名风格自动转换）

| YAML 里写的 | Python 字段名 | 能匹配吗？ |
|---|---|---|
| `app-name` | `app_name` | ✅ |
| `app-name` | `appName` | ✅ |
| `APP_NAME` | `app_name` | ✅ |
| `AppName` | `app_name` | ✅ |

### ③ 运行结果

启动后，`MyAppProps().app_name` 已经是 `"demo-app"`，`MyAppProps().database.url` 已经是 `"sqlite:///mem.db"`。IDE 有自动补全，拼错字段名启动时报错。

### 模块 mini-FAQ

**Q：嵌套配置为什么不生效？**
嵌套的类必须加 `@NestedConfigurationProperties`，否则子对象的字段不会绑定。

**Q：配置能动态刷新吗？**
不能。`@ConfigurationProperties` 只在启动时加载一次。需要动态刷新的配置用 `@NacosValue`（参见 [Cloud 模块文档](CLOUD_MODULE.md)）。

**Q：YAML 里写 `max-connections: "32"` 能自动转成 int 吗？**
不能！字符串不会自动转数字，YAML 里写 `max-connections: 32`（不加引号）才是数字。

---

## 六、测试切片 —— 只测试你关心的部分

### 你遇到了什么问题？

每次跑测试都要启动整个应用——Web 层、数据库、缓存全部启动，慢得要死。你只想测 Controller 的请求响应，为什么要等数据库初始化？

### ① 是什么

**测试时不启动整个应用，只测你关心的那部分。** 就像检查汽车时，不需要发动整辆车，可以单独测发动机、刹车、车灯。测试切片让你只启动 Web 层或数据层，跑得更快，问题定位更准。

### ② 怎么用

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

### 三种切片对比

| 切片 | 启动什么 | 不启动什么 | 适合测什么 |
|---|---|---|---|
| `SpringBootTest` | 全部 | 无 | 端到端集成测试 |
| `WebMvcTest` | Controller + Mock 依赖 | Service / Repository | Controller 请求响应 |
| `DataJpaTest` | 内存数据库 + Repository | Controller / Service | 数据库操作 |

### ③ 运行结果

- `WebMvcTest`：启动时间 < 1 秒（不用连数据库）
- `DataJpaTest`：启动时间 < 1 秒（不用起 Web 服务）
- 测试结束数据自动清理，不影响开发环境

### 模块 mini-FAQ

**Q：WebMvcTest 返回的数据结构是什么？**
返回的数据在 `resp.json()["data"]` 里，不是直接在根层级。这是框架统一的 Result 包装。

**Q：DataJpaTest 用的什么数据库？**
内存 SQLite，和生产环境的 MySQL/PostgreSQL 行为可能有差异（日期函数、字符集等）。

**Q：我能在 WebMvcTest 里用真实的 Service 吗？**
可以。设 `mock_dependencies=False`，然后手动注册你想用的真实 Service。

---

## 七、i18n 国际化 —— 中英文自动切换

### 你遇到了什么问题？

产品要出海了，网站需要根据用户语言自动显示中文或英文。你不想在代码里写满 `if lang == "zh": return "你好" else: return "Hello"`。

### ① 是什么

**让应用能说多种语言。** 根据用户浏览器的语言偏好，自动返回对应语言的文案。就像微信根据你手机设置的语言，自动显示中文或英文界面——中英文自动切换。

### ② 怎么用

第一步：创建语言文件

`./i18n/messages.properties`（默认，兜底用）：

```properties
greeting=Hello, {0}!
error.not_found=Resource not found
```

`./i18n/messages_zh_CN.properties`（中文）：

```properties
greeting=你好，{0}！
error.not_found=资源未找到
```

`./i18n/messages_en_US.properties`（英文）：

```properties
greeting=Hello, {0}!
error.not_found=Resource not found
```

第二步：在代码中使用：

```python
from spring.i18n import (
    ResourceBundleMessageSource, Locale, LOCALE_CHINA, LOCALE_US,
    AcceptHeaderLocaleResolver, LocaleResolverMiddleware,
)

# 1. 加载语言文件
src = ResourceBundleMessageSource(basenames=["messages"], base_dir="./i18n")

# 2. 按语言取消息（{0} 是占位符）
msg = src.getMessage("greeting", ["小明"], Locale("zh", "CN"))
print(msg)  # 输出: 你好，小明！

msg = src.getMessage("greeting", ["Tom"], Locale("en", "US"))
print(msg)  # 输出: Hello, Tom!

# 3. 安装中间件：自动从浏览器 Accept-Language 头解析语言
app.add_middleware(
    LocaleResolverMiddleware,
    locale_resolver=AcceptHeaderLocaleResolver(
        supported_locales=[Locale("zh", "CN"), Locale("en", "US")],
        default_locale=Locale("en"),  # 找不到匹配时用英文兜底
    ),
)
# 结果：浏览器发送 Accept-Language: zh-CN → 自动用中文
#       浏览器发送 Accept-Language: en-US → 自动用英文
```

### ③ 运行结果

用户浏览器语言是中文时，接口返回"你好，小明！"；英文时返回"Hello, Tom!"。你不需要在代码里写任何 if/else 判断。

### 模块 mini-FAQ

**Q：文件命名有格式要求吗？**
必须用 `basename_语言_国家.properties` 格式，如 `messages_zh_CN.properties`。不要写成 `messages_zh-CN` 或 `messages_chinese`。

**Q：占位符是 {0} 还是 {name}？**
用 `{0}``{1}` 数字索引（Java properties 风格），不是 Python 的 `{name}`。

**Q：编码用 UTF-8 吗？**
是的。中文内容直接写进去就行，不用 `\uXXXX` 转义。

**Q：`messages.properties` 是干什么的？**
是兜底文件。请求的语言找不到对应文件时，回退到这个默认文件。至少要有一个。

---

## 八、WebSocket —— 像微信一样实时通信

### 你遇到了什么问题？

你需要做实时通知、聊天、数据看板——但普通的 HTTP 请求是"问一句答一句"，用户不问服务器就不答。要么用户不停地轮询（浪费资源），要么有消息了用户却不知道。

### ① 是什么

**就像打电话（或微信聊天）一样，双方随时可以给对方发消息，不用等对方问。** 普通 HTTP 是"你问我才答"，WebSocket 是"我想说就说"——浏览器和服务器建立一条持久连接，双向实时通信，像微信一样实时。

### ② 怎么用

方式一：简单回声（JSR-356 风格）

```python
from spring.websocket import ServerEndpoint

@ServerEndpoint("/ws/echo")
class EchoEndpoint:
    async def on_open(self, session):
        await session.send_text("欢迎连接！")  # 连接建立时发欢迎消息

    async def on_message(self, session, message):
        await session.send_text("回声: " + message)  # 收到什么就回什么

    async def on_close(self, session, reason):
        print(f"连接断开: {reason}")

# 客户端连接 ws://127.0.0.1:8080/ws/echo
# 发送 "你好" → 收到 "回声: 你好"
```

方式二：聊天室（Spring STOMP 风格）

```python
from spring.websocket import ServerEndpoint, MessageMapping, SendTo, SendToUser

@ServerEndpoint("/ws/chat")
class ChatEndpoint:
    @MessageMapping("/chat.send")
    @SendTo("/topic/messages")         # 广播给所有订阅者
    def send_message(self, message):
        return {"text": message}
        # 结果：所有订阅 /topic/messages 的人都收到

    @MessageMapping("/chat.private")
    @SendToUser                         # 只回发给发送者本人
    def private_message(self, message, session):
        return {"text": "私密: " + message}
        # 结果：只有发送者自己收到，其他人收不到
```

安装到 FastAPI：

```python
from spring.websocket import WebSocketRouter, discover_server_endpoints

router = WebSocketRouter()
for endpoint_cls in discover_server_endpoints():   # 自动发现所有 @ServerEndpoint
    router.add_endpoint(endpoint_cls.__spring_endpoint_path__, endpoint_cls)
router.install(app)   # 注册到 FastAPI
```

### ③ 运行结果

- 客户端 A 发消息 → 所有订阅者（包括 A 自己）都收到 → 聊天室效果
- 客户端 A 发私密消息 → 只有 A 收到 → 私信效果

### 模块 mini-FAQ

**Q：WebSocket 和普通 HTTP 有什么区别？**
HTTP 是"你问我才答"，每次请求建立新连接。WebSocket 是"建立一条热线一直通着"，双方随时说话。

**Q：InMemoryBroker 重启后消息还在吗？**
不在了。内存级 broker 重启后所有订阅丢失。需要持久化消息用 Redis 或消息队列。

**Q：on_open/on_message/on_close 必须是 async def 吗？**
是的，因为 WebSocket 是异步 I/O。用 `async def` 和 `await`。

**Q：Nginx 需要特殊配置吗？**
需要。Nginx 必须正确配置 `Upgrade` 和 `Connection` 头来支持 WebSocket 协议升级。

**Q：怎么测试 WebSocket？**
不能用 `requests` 库（它是 HTTP 客户端），需要用 `websockets` 库或 FastAPI 的 `TestClient`。

---

## 九、新手常见错误 ❌/✅

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

## 十、模块总览表

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

## 十一、FAQ

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
