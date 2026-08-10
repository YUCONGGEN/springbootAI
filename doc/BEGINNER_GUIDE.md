# SpringBootAI 新手入门指南

这份文档写给第一次接触 SpringBootAI、FastAPI 或 Spring 风格开发的读者。你不需要先学 Java Spring；只要会运行 Python 文件，就可以按步骤完成第一个接口。

## 1. 这个框架是做什么的

SpringBootAI 是一个 Python Web 框架。它把常见的后端功能放在同一个编程模型里：

| 你想做的事 | 使用的模块 | 最常见入口 |
|---|---|---|
| 提供 HTTP 接口 | Web MVC | `@RestController`、`@GetMapping`、`@PostMapping` |
| 把业务代码分层 | IoC/DI | `@Service`、`@Repository`、`@Autowired` |
| 读写数据库 | PyMyBatis ORM | `@Mapper`、`@Select`、`@Transactional` |
| 校验请求对象 | Bean Validation | `NotBlank`、`Min`、`@BeanValidate` |
| 登录和权限控制 | Security | JWT、`@Authenticate`、`@PreAuthorize` |
| 缓存、重试、限流 | AOP | `@Cacheable`、`@Retryable`、`@RateLimit` |
| 服务注册和远程调用 | Cloud | Nacos、Feign、Gateway、Sentinel |
| 自动生成接口文档 | Swagger/OpenAPI | `@Tag`、`@Operation`、`/docs` |
| 调用大模型或做知识库 | AI | `ChatClient`、Advisor、RAG、Tools |

框架借鉴了 Spring Boot 的名称和分层习惯，但运行时仍然是 Python、FastAPI 和 Uvicorn。Java 依赖、JAR、Maven 插件和 Java Bean 不可以直接放进本项目。

## 2. 先认识五个词

### 2.1 Controller

Controller 接收浏览器或其他系统发来的 HTTP 请求，并返回 JSON。它相当于餐厅前台，只负责接单和返回结果，不应该塞入大量数据库逻辑。

### 2.2 Service

Service 编写业务规则，例如“创建订单前先检查库存”。Controller 应调用 Service，而不是直接操作数据库。

### 2.3 Repository / Mapper

Repository 或 Mapper 专门访问数据库。Mapper 中通常写查询、插入、更新和删除 SQL。

### 2.4 Bean 和容器

被 `@Controller`、`@Service`、`@Repository`、`@Component` 标记并被扫描到的对象叫受管 Bean。容器负责创建这些对象并注入依赖。

这点非常重要：自己写 `OrderService()` 创建的对象通常不会获得事务、缓存、校验等 AOP 能力。应让容器创建它，再通过构造器注入给其他 Bean。

### 2.5 注解

Python 中的“注解”实际是装饰器，例如 `@GetMapping("/users")`。它给类或方法添加元数据，框架启动时读取这些元数据并注册路由、事务或缓存行为。

## 3. 从零运行第一个接口

### 3.1 检查环境

需要 Python 3.10 或更高版本：

```powershell
python --version
```

建议为项目创建独立虚拟环境，避免依赖和其他项目混在一起：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install springbootAI
```

Linux 或 macOS 激活命令是：

```bash
source .venv/bin/activate
```

验证安装：

```powershell
python -c "import spring; print(spring.__version__)"
```

能打印版本号就说明安装成功。

### 3.2 创建目录

创建下面的结构。每个 Python 包目录都要有 `__init__.py`，即使文件内容为空也不能省略。

```text
demo/
|-- __init__.py
|-- Application.py
|-- application.yml
`-- controller/
    |-- __init__.py
    `-- HelloController.py
```

### 3.3 创建启动类

在 `demo/Application.py` 中写：

```python
from spring.annotations import SpringBootApplication
from spring.main import run


@SpringBootApplication(scan_base_packages=["demo"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

`scan_base_packages=["demo"]` 表示启动时扫描 `demo` 包，找到其中的 Controller、Service 和 Repository。

### 3.4 创建接口

在 `demo/controller/HelloController.py` 中写：

```python
from spring.annotations import GetMapping, RequestMapping, RestController
from spring.web.swagger import Operation, Tag


@Tag(name="入门接口", description="用于确认项目已经正常启动")
@RequestMapping("/api")
@RestController
class HelloController:
    @Operation(summary="打招呼", description="把路径中的名字放进欢迎语")
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
```

这些注解分别起到以下作用：

| 注解 | 作用 |
|---|---|
| `@RestController` | 告诉容器这是 HTTP Controller |
| `@RequestMapping("/api")` | 给类中所有接口添加 `/api` 前缀 |
| `@GetMapping(...)` | 注册一个 GET 请求路径 |
| `@Tag` | 在 Swagger 页面中给接口分组 |
| `@Operation` | 在 Swagger 页面中显示接口用途 |

### 3.5 创建最小配置

在 `demo/application.yml` 中写：

```yaml
server:
  host: 127.0.0.1
  port: 8080
  cors:
    allow_origins: []
    allow_credentials: false

redis:
  enabled: false

database:
  enabled: false

jwt:
  secret_key: development-only-secret
  algorithm: HS256
```

这里先关闭数据库和 Redis，目的是用最少依赖验证 Web 服务。开发密钥不能用于生产环境。

### 3.6 启动和验证

必须在包含 `demo` 目录的项目根目录执行：

```powershell
python -m demo.Application
```

看到 Uvicorn 启动日志后，在另一个终端运行：

```powershell
curl http://127.0.0.1:8080/api/hello/Alice
curl http://127.0.0.1:8080/actuator/health/liveness
```

第一个请求应返回包含 `Hello, Alice` 的 JSON；第二个请求应返回 `UP`。浏览器打开下面两个地址：

- `http://127.0.0.1:8080/docs`：可点击和调试的 Swagger 页面。
- `http://127.0.0.1:8080/openapi.json`：给工具读取的 OpenAPI JSON。

如果 `/docs` 中能看到“入门接口”，说明组件扫描、路由注册和 Swagger 都已生效。

## 4. 加入 Service 和依赖注入

业务变复杂后，把逻辑从 Controller 移到 Service：

```python
from spring.annotations import Autowired, GetMapping, RestController, Service


@Service
class GreetingService:
    def build_message(self, name: str) -> str:
        return f"Hello, {name}"


@RestController
class GreetingController:
    @Autowired
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service

    @GetMapping("/greeting/{name}")
    def greeting(self, name: str):
        return {"message": self.greeting_service.build_message(name)}
```

启动时容器创建 `GreetingService`，再把它传给 `GreetingController`。如果报“找不到 Bean”，先检查类上有没有 `@Service`，所在包是否包含在 `scan_base_packages` 中。

## 5. 按需求选择下一份文档

不要从头学习所有模块。先根据当前任务选择：

| 当前任务 | 下一步阅读 |
|---|---|
| 做普通 CRUD 接口 | [README Web 章节](../README.md#7-web-控制器) + [ORM 指南](ORM_MODULE.md) |
| 校验用户输入、条件装配、缓存更新 | [常用注解模块指南](ANNOTATION_MODULES.md) |
| 登录、JWT、角色权限 | [安全指南](SECURITY.md) |
| 自动生成 Swagger 文档 | [Swagger 指南](SWAGGER_MODULE.md) |
| 导入导出 Excel | [Excel 指南](EXCEL_MODULE.md) |
| 导入导出 CSV | [CSV 指南](CSV_MODULE.md) |
| 服务发现、Feign、网关、事务补偿 | [Cloud 指南](CLOUD_MODULE.md) |
| 大模型、知识库、工具调用 | [AI 指南](AI_MODULE.md) |
| 分页、Actuator、多数据源、i18n、WebSocket | [八大模块指南](EIGHT_MODULES.md) |
| 运行 9 小时压测 | [性能测试指南](../tests_performance/README.md) |

## 6. 配置文件怎么理解

`application.yml` 是应用默认配置。`${变量名:默认值}` 表示优先读取环境变量，没有设置时使用冒号后的默认值。

例如：

```yaml
server:
  port: ${SERVER_PORT:8080}
```

不设置环境变量时端口是 8080；PowerShell 中这样临时改成 9000：

```powershell
$env:SERVER_PORT='9000'
python -m demo.Application
```

常用开关：

| 配置 | 什么时候开启 | 还需要什么 |
|---|---|---|
| `database.enabled` | 需要数据库时 | 数据库驱动、地址、账号和密码 |
| `redis.enabled` | 需要分布式缓存、锁或限流时 | 可访问的 Redis |
| `rabbitmq.enabled` | 需要消息队列时 | RabbitMQ 服务和队列配置 |
| `discovery.enabled` | 需要 Nacos 服务注册发现时 | Nacos 服务与客户端依赖 |
| `seata.enabled` | 需要事务协调时 | 必须先理解三种模式的边界 |
| `prometheus.enabled` | 需要指标监控时 | Prometheus 抓取配置 |

完整字段和默认值以仓库根目录的 [`application.yml`](../application.yml) 为准。

## 7. 开发、测试和生产的区别

开发环境可以使用 SQLite、单 worker 和开发密钥。生产环境至少要做到：

1. 使用不可预测的 JWT 密钥，并通过环境变量或密钥管理服务注入。
2. 限制 CORS 域名，不能无条件允许 `*`。
3. 使用目标 MySQL/PostgreSQL 运行集成测试，不能只依赖 SQLite 单元测试。
4. 用 ASGI 入口和多个 worker 部署，不使用开发模式的 `run()` 管理生产进程。
5. 配置健康检查、日志、Prometheus 和告警。
6. 对同步线程池、数据库连接池和外部 HTTP 连接池做容量测试。
7. 支付、订单、库存等强一致业务使用真实 Seata 或可靠消息方案，不能把 HTTP 补偿模式当成 AT。

生产入口示例：

```python
# asgi.py
from spring.main import create_app
from demo.Application import Application

app = create_app(Application)
```

```powershell
uvicorn asgi:app --host 0.0.0.0 --port 8080 --workers 2
```

## 8. 新手常见错误

| 现象 | 最常见原因 | 处理方式 |
|---|---|---|
| Controller 没有出现在 `/docs` | 包未扫描或缺少 `__init__.py` | 检查目录结构和 `scan_base_packages` |
| 注解写了但缓存/事务不生效 | 对象是手动 `ClassName()` 创建的 | 改成受管 Bean，通过注入获取 |
| `ModuleNotFoundError` | 虚拟环境未激活或从错误目录启动 | 激活 `.venv`，从项目根目录运行 |
| 端口被占用 | 8080 已被其他进程使用 | 修改 `SERVER_PORT` 或停止占用进程 |
| 数据库连接失败 | 驱动、地址、账号或容器端口错误 | 先用数据库客户端验证连接，再启动应用 |
| Redis 功能没有集群语义 | Redis 未启用，框架走了本地降级 | 开启 Redis 并做断线/恢复测试 |
| Swagger 页面为空 | Controller 未注册或 Swagger 被关闭 | 先检查 `/openapi.json` 和启动日志 |
| 多 worker 连接数过高 | 每个 worker 都创建独立连接池 | 按 `worker 数 x max_size` 计算总连接数 |

## 9. 如何确认一个功能真的生效

不要只看“启动没有报错”。每个功能都应有可观察结果：

| 功能 | 最小验证方式 |
|---|---|
| Web 路由 | `curl` 返回预期状态码和 JSON |
| Swagger | `/docs` 和 `/openapi.json` 包含目标路由 |
| Bean 注入 | 启动日志中无缺失 Bean，接口能调用 Service |
| 数据库 | 在真实数据库查询到新增或更新的数据 |
| 事务 | 主动抛异常后确认数据全部回滚 |
| 缓存 | 连续请求确认第二次没有重复执行方法 |
| 权限 | 分别用无 token、错误角色、正确角色访问 |
| 消息队列 | 验证发送、消费、重复投递和消费者重启 |
| 分布式事务 | 验证提交、回滚、超时、分支失败和进程崩溃 |
| 压测 | 检查错误率、p95、p99、丢弃请求和资源曲线 |

完成这里的第一个接口后，再按第 5 节选择模块文档即可，不需要一次掌握全部功能。
