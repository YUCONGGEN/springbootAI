# SpringPy 综合使用指南

SpringPy 是一个借鉴 Spring Boot 编程模型的 Python Web 框架，提供装饰器式组件扫描、依赖注入、FastAPI 路由、配置加载、安全能力、内嵌的 PyMyBatis ORM，以及企业级 AI 模块（对齐 Spring AI 2.0：ChatClient/Advisor/Tools/RAG/Function Calling）。本指南整合了原有 README、使用说明书、注解使用指南、AI 模块文档、Java 迁移指南与生产部署指南，作为框架的唯一综合使用文档。

- SpringPy 版本：`1.7.0`
- 内嵌 PyMyBatis 版本：`1.4.0`
- Python：3.9+
- 状态：GA (全面可用)
- 仓库：[GitHub - YUCONGGEN/springboot_cloud_python](https://github.com/YUCONGGEN/springboot_cloud_python)
- License：MIT

## 目录

1. [框架概述与定位](#1-框架概述与定位)
2. [能力状态](#2-能力状态)
3. [安装与快速开始](#3-安装与快速开始)
4. [配置系统](#4-配置系统)
5. [注解参考](#5-注解参考)
6. [IoC 与依赖注入](#6-ioc-与依赖注入)
7. [Web 控制器](#7-web-控制器)
8. [内嵌 PyMyBatis ORM 与 DDL](#8-内嵌-pymybatis-orm-与-ddl)
9. [事务](#9-事务)
10. [安全与权限](#10-安全与权限)
11. [缓存、任务与高级 AOP](#11-缓存任务与高级-aop)
12. [SpringPy AI 模块](#12-springpy-ai-模块)
13. [Java 迁移指南](#13-java-迁移指南)
14. [生产部署](#14-生产部署)
15. [项目结构](#15-项目结构)
16. [测试](#16-测试)
17. [常见问题与排错](#17-常见问题与排错)

---

## 1. 框架概述与定位

SpringPy 借鉴了 Spring Boot 的注解和分层习惯，但运行时是 Python、FastAPI 和 Uvicorn。**它不兼容 Java 字节码、Spring Bean 后处理器、JPA、Java MyBatis 插件或 Maven/Gradle 生态。**

### 1.1 版本

| 组件 | 当前版本 |
|------|----------|
| `spring` 框架 API | 1.7.0 |
| `spring.orm.pymybatis` | 1.4.0 |
| Python | 3.9+ |

### 1.2 推荐使用范围

- 内部管理接口、轻量业务服务、教学和原型验证。
- 希望统一使用控制器/服务/Mapper 分层方式的 Python 团队。
- SQLite 本地工具，或经过目标数据库集成测试的受控服务。
- 微服务架构（内置服务发现、限流熔断、分布式追踪、分布式事务）。

### 1.3 能力边界

- 自动化 ORM 契约测试使用 SQLite；MySQL、PostgreSQL、Oracle 需单独验证。
- 本地 `@Transactional` 支持全部七种 Spring 传播模式；`REQUIRES_NEW` 和 `NOT_SUPPORTED` 需要连接池有额外可用连接。
- Profile 会筛选 `@Profile` Bean，但不会自动合并 `application-{profile}.yml`。
- Nacos、RabbitMQ、Prometheus 依赖外部服务；Sentinel、Seata HTTP-AT、OpenTelemetry 追踪均已内嵌实现无需外部 Server。
- 限流、分布式锁、幂等和缓存语义依赖 Redis 等后端，降级路径需要故障注入。

### 1.4 注解使用总览

SpringPy 注解会先把元数据放到 `__spring_annotations__`。之后是否生效，取决于是否存在对应的扫描器或切面：

| 状态 | 含义 |
|------|------|
| 容器执行 | `ApplicationContext`、`BeanFactory` 或 Web 上下文会读取并执行 |
| 受管 Bean 执行 | 只有被组件扫描并由容器创建的实例方法才会被 AOP 包装；自己 `ClassName()` 创建的对象不生效 |
| 直接执行 | 装饰器本身返回包装函数，不依赖 IoC 容器 |
| 仅元数据 | 当前有注解类，但主运行链路没有消费者，写上不会得到注解名字所暗示的功能 |

这也是 SpringPy 与 Java Spring 最容易混淆的地方：名称相似不代表参数和运行语义完全相同。

---

## 2. 能力状态

| 模块 | 状态 | 说明 |
|------|------|------|
| IoC 容器 | ✅ 可用 | 组件扫描、构造器/字段注入、Bean、延迟初始化、生命周期回调、Profile 过滤 |
| Web MVC | ✅ 可用 | 基于 FastAPI 的 GET/POST/PUT/PATCH/DELETE 路由、参数绑定、异常处理、CORS 和静态文件 |
| 配置 | ✅ 可用 | YAML、`${ENV:default}`、固定环境变量覆盖、标量类型保留；全局加载器与应用上下文共享配置路径和状态 |
| 应用事件 | ✅ 可用 | `ApplicationEvent`、`@EventListener`、同步有序发布和异步监听方法调度 |
| 内嵌 ORM + DDL Auto | ✅ 可用 | PyMyBatis + JPA ddl-auto 自动建表(create/update/validate)，支持 XML/注解 SQL、事务、缓存 |
| 本地事务 | ✅ 可用 | `@Transactional` 支持七种 Spring 传播模式；`REQUIRES_NEW`/`NOT_SUPPORTED` 需要连接池可提供额外连接 |
| JWT 与方法安全 | ✅ 可用 | access/refresh token、`@Authenticate`、角色/权限授权、401/403 映射和并发上下文隔离 |
| 重试/异步 | ✅ 可用 | 受管 Bean 的退避重试、恢复方法和 Future/Task 异步调度 |
| Redis/缓存 | ✅ 可用 | 分布式锁、KV/Hash/List/Set/Counter，需要 Redis 服务 |
| RabbitMQ | ✅ 可用 | `@RabbitListener` 自动注册并后台消费，`RabbitTemplate` 发送 |
| Nacos 服务发现 | ✅ 可用 | 服务注册/发现/订阅，支持无认证开发模式 |
| Sentinel 限流熔断 | ✅ 可用 | 内嵌引擎，QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流，无需 Dashboard |
| 分布式追踪 | ✅ 可用 | 原生 OpenTelemetry(W3C traceparent)，自动 HTTP/Feign 注入，无需 OAP Server |
| Seata 分布式事务 | ✅ 可用 | 内嵌 HTTP-AT 模式，分支注册/提交/回滚，XID 自动传播，无需 Seata Server |
| API Gateway | ✅ 可用 | 轻量 ASGI/WSGI 网关，路由转发、路径重写、过滤器链、负载均衡 |
| Prometheus 监控 | ✅ 可用 | Counter/Gauge/Histogram 指标暴露 |
| Feign 声明式 HTTP | ✅ 可用 | 声明式接口、Fallback 降级、自动传播 XID 和 trace 头 |
| 高级 AOP | ✅ 可用 | 限流、熔断、幂等、审计、锁、指标、追踪、缓存 |
| SpringPy AI 模块 | ✅ 可用 | 对齐 Spring AI 2.0：ChatClient/ChatModel/EmbeddingModel/Advisor/Tools，OpenAI/Ollama/DeepSeek/Moonshot 适配，Function Calling 闭环、RAG、会话记忆、Redis 向量存储、熔断重试、真流式 async、Prometheus 观测、类型化配置绑定 |

---

## 3. 安装与快速开始

### 3.1 环境准备

```bash
cd springboot
python -m venv .venv
```

激活虚拟环境：

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux/macOS
source .venv/bin/activate
```

### 3.2 安装框架

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

核心依赖包含 FastAPI、Uvicorn、PyYAML、python-dotenv、DBUtils、PyJWT、cryptography、bcrypt 和 Pydantic。**核心安装已包含内嵌 `spring.orm.pymybatis`，使用 Mapper 模式不需要再安装独立 `pymybatis`。**

### 3.3 可选 extras

```bash
python -m pip install -e ".[mysql]"             # PyMySQL
python -m pip install -e ".[postgresql]"        # psycopg2-binary
python -m pip install -e ".[oracle]"            # cx-Oracle
python -m pip install -e ".[sqlalchemy]"        # SQLAlchemy 模式
python -m pip install -e ".[redis]"             # Redis 能力
python -m pip install -e ".[ast]"               # sqlglot AST 校验
python -m pip install -e ".[rabbitmq]"          # pika
python -m pip install -e ".[nacos]"             # Nacos 客户端
python -m pip install -e ".[prometheus,logging]" # 指标和 loguru
python -m pip install -e ".[dev]"               # 测试和静态工具
```

AI 模块为可选依赖（未安装时降级原生 HTTP + FakeChatModel）：

```bash
pip install -r requirements-ai.txt   # langchain-openai/langchain-community/numpy（==锁版本）
```

`requirements.txt` 是仓库的完整开发环境，包含多种数据库和中间件客户端。应用接入时优先按需安装 extras。

### 3.4 验证安装

```bash
python -c "import spring; print(spring.__version__)"
python -c "from spring.orm.pymybatis import __version__; print(__version__)"
```

### 3.5 最小应用

仓库中的 `example`、`example1`、`example5` 只用于源码参考和回归验证，不会打包进 `springpy`。安装后请按下面结构创建自己的应用包，不要从 site-packages 导入这些示例。**每个被扫描目录都必须包含 `__init__.py`，并从项目根目录启动。**

创建包结构：

```text
demo/
|-- __init__.py
|-- Application.py
|-- application.yml
`-- controller/
    |-- __init__.py
    `-- HelloController.py
```

创建 `demo/Application.py`：

```python
from spring.annotations import SpringBootApplication
from spring.main import run


@SpringBootApplication(scan_base_packages=["demo"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

创建 `demo/controller/HelloController.py`：

```python
from spring.annotations import GetMapping, RequestMapping, RestController


@RequestMapping("/api")
@RestController
class HelloController:
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
```

创建 `demo/application.yml`：

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

运行和验证：

```bash
python -m demo.Application
curl http://127.0.0.1:8080/api/hello/Alice
curl http://127.0.0.1:8080/actuator/health/liveness
curl http://127.0.0.1:8080/actuator/info
```

默认响应会统一包装为 `Result`：

```json
{
  "code": 200,
  "message": "success",
  "data": {"message": "Hello, Alice"}
}
```

交互式 API 文档由 FastAPI 提供，默认访问 `http://127.0.0.1:8080/docs`；原始规范位于 `/openapi.json`。

### 3.6 生产 ASGI 入口

开发时可以使用 `run()`；生产进程管理应使用 `create_app()` 构建 ASGI 应用：

```python
# asgi.py
from spring.main import create_app
from demo.Application import Application

app = create_app(Application)
```

```bash
uvicorn asgi:app --host 0.0.0.0 --port 8080 --workers 2
```

多 worker 会创建多个独立进程、IoC 容器和连接池。连接池总量应按 `worker 数 x max_size` 评估。

---

## 4. 配置系统

### 4.1 配置位置

`ApplicationContext` 按以下顺序查找配置：

1. 启动类文件所在目录的 `application.yml`。
2. 启动类目录下的 `config/application.yml`。
3. 两处都不存在时使用代码默认值和环境变量。

两处都存在时第一项优先，不会合并。仓库自带的 `example` 使用第二种目录布局。

`ApplicationContext` 启动后会把该路径绑定到稳定的全局加载器，之后新建的 `ConfigLoader()` 也读取同一文件，不再依赖进程当前工作目录。

### 4.2 环境变量占位符

```yaml
server:
  port: ${SERVER_PORT:8080}
database:
  enabled: ${DB_ENABLED:false}
  password: ${DB_PASSWORD}
```

- `${NAME}`：环境变量必填，未设置时报 `ConfigurationError`。
- `${NAME:default}`：未设置时使用默认值。
- 占位符占满整个值时，YAML 会把 `8080`、`false`、`null` 保留为 int、bool、None（**完整占位符会保留标量类型**）。
- 占位符嵌入普通字符串时结果仍是字符串。

### 4.3 固定覆盖变量

除 YAML 占位符外，加载器还会读取固定变量：

| 分类 | 环境变量 |
|------|----------|
| 服务 | `SERVER_HOST`、`SERVER_PORT` |
| 环境 | `SPRING_PROFILES_ACTIVE`、`STARTUP_FAIL_FAST` |
| JWT | `JWT_SECRET_KEY`、`JWT_ALGORITHM` |
| 数据库 | `DB_ENABLED`、`DB_URL`、`DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USERNAME`、`DB_PASSWORD`、`DB_DRIVER` |
| Redis | `REDIS_ENABLED`、`REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`、`REDIS_PASSWORD` |
| CORS | `CORS_ALLOW_ORIGINS`、`CORS_ALLOW_CREDENTIALS` |
| 日志 | `LOG_LEVEL`、`LOG_DIR`、`LOG_RETENTION`、`LOG_ROTATION` |
| 中间件 | `DISCOVERY_*`、`NACOS_SERVER`、`NACOS_USERNAME`、`NACOS_PASSWORD`、`SEATA_*`、`RABBITMQ_*`、`PROMETHEUS_*` |
| Docker 辅助 | `SPRING_DISABLE_DOCKER_IP_DETECT`（设为 1 禁用容器 IP 自动检测） |

对 `database.driver`、`database.database`、连接池和 ORM 安全参数，推荐直接在 YAML 中使用 `${DB_DRIVER:...}` 等占位符。

常用覆盖变量示例：

```text
SPRING_PROFILES_ACTIVE  STARTUP_FAIL_FAST
SERVER_HOST             SERVER_PORT
JWT_SECRET_KEY          JWT_ALGORITHM
DB_ENABLED              DB_URL
REDIS_ENABLED           REDIS_HOST        REDIS_PORT
DISCOVERY_ENABLED       NACOS_SERVER      NACOS_NAMESPACE
NACOS_GROUP             NACOS_USERNAME    NACOS_PASSWORD
CORS_ALLOW_ORIGINS      CORS_ALLOW_CREDENTIALS
LOG_LEVEL               LOG_DIR
```

当前 `SPRING_PROFILES_ACTIVE` 用于 `@Profile` 组件筛选和生产安全校验，不会自动合并 `application-prod.yml`。需要多环境文件时，由部署流程生成最终 `application.yml` 或显式传入配置路径。

### 4.4 Docker 容器 IP 自动检测（开发环境）

在开发环境中，当 `database.host` 设为 `127.0.0.1` 或 `localhost` 时，框架会自动通过 `docker ps` 和 `docker inspect` 查找映射了目标端口的容器内部 IP 进行连接，无需手动配置容器 IP。

- 支持通过端口映射精确匹配（如 `0.0.0.0:3306->3306/tcp`）
- 支持 MySQL/MariaDB/PostgreSQL 数据库镜像兜底匹配
- 设置 `SPRING_DISABLE_DOCKER_IP_DETECT=1` 可禁用此功能（生产环境推荐）

### 4.5 读取配置

```python
from spring.config import ConfigLoader

loader = ConfigLoader("./myapp/application.yml")
port = loader.get("server.port", 8080)
database = loader.get_prefix_config("database")
snapshot = loader.get_config()
```

返回的配置是深拷贝，调用方修改不会回写加载器。需要加载另一份配置时，显式传入 `config_path` 或 `base_path`。

### 4.6 Profile 的真实行为

```yaml
spring:
  profiles:
    active: dev
```

```python
from spring.annotations import Profile, Service


@Profile("dev")
@Service
class DevelopmentService:
    pass
```

Profile 用于 Bean 过滤和生产安全校验。当前实现不会自动读取、合并 `application-dev.yml` 或 `application-prod.yml`。多环境配置可使用以下方式之一：

1. 在部署流程中生成最终 `application.yml`。
2. 大量使用环境变量占位符。
3. 在自定义启动代码中显式创建 `ConfigLoader(config_path=...)` 和 `ApplicationContext`。

### 4.7 生产配置校验

当 Profile 是 `prod` 或 `production` 时：

- 默认 JWT 密钥、空密钥或少于 32 字符的密钥会导致启动失败。
- `startup.fail_fast` 默认视为开启。
- CORS 开启凭证时配置 `*` 来源会直接失败。

### 4.8 健康检查

| 地址 | 用途 |
|------|------|
| `/actuator/health` | 聚合组件健康状态；降级时返回 503 |
| `/actuator/health/liveness` | 进程存活检查 |
| `/actuator/health/readiness` | 服务就绪检查 |
| `/actuator/info` | 应用名称、当前 Profile、框架和 Python 版本 |

聚合健康非 UP 时返回 HTTP 503。组件检查带超时，避免单个依赖长期阻塞健康端点。`database.enabled: false` 时数据库状态为 `DISABLED`，不会初始化默认 SQLite、不会创建 `test.db`，也不会虚报为 `UP`。生产探针应区分 liveness 和 readiness，避免依赖组件短暂故障导致进程反复重启。

---

## 5. 注解参考

> 说明：本节的注解参数表格是框架最完整的参考（来源自注解使用指南）。各注解的"当前行为与边界"信息（来源自使用说明书）已在表格下补充。所有 AOP 类注解（事务、缓存、重试、异步、定时、高级 AOP、安全等）都要求**方法所在类带组件注解（`@Service`/`@Component`/`@Repository`/`@Controller` 等）并由容器取得实例**，自己 `ClassName()` 创建的对象不会生效。

### 5.1 启动与扫描

#### @SpringBootApplication

**含义**：Spring Boot 应用启动类注解，组合了 `@Configuration`、`@ComponentScan` 的功能。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| scan_base_packages | List[str] | None | 扫描的基础包路径 |

**用法示例**：

```python
from spring.annotations import SpringBootApplication

@SpringBootApplication(scan_base_packages=["com.example.service", "com.example.controller"])
class Application:
    pass
```

**注意事项**：
- 每个应用只能有一个启动类；不指定 `scan_base_packages` 时默认扫描启动类所在包及其子包。
- `scan_base_packages` 是可导入包名，不是文件路径。

#### @ComponentScan

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| base_packages | List[str] | None | 扫描的基础包路径 |

```python
from spring.annotations import Configuration, ComponentScan

@Configuration
@ComponentScan(base_packages=["com.example.service", "com.example.dao"])
class AppConfig:
    pass
```

**边界**：容器执行；不要和带 `scan_base_packages` 的启动注解重复配置。

### 5.2 组件与依赖注入

#### @Component

**参数**：`value`（str，默认 `""`，Bean 名称）

```python
from spring.annotations import Component

@Component
class EmailUtil:
    def send(self, to: str, content: str):
        pass
```

#### @Service

**参数**：`value`（str，默认 `""`，Bean 名称，默认使用类名首字母小写）

```python
from spring.annotations import Service

@Service
class UserService:
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}
```

**边界**：行为与 `@Component` 相同，名称表达业务层语义。

#### @Repository

**参数**：`value`（str，默认 `""`）

```python
from spring.annotations import Repository

@Repository
class UserRepository:
    def find_by_id(self, user_id: int):
        pass
```

**边界**：行为与 `@Component` 相同；**它不是 ORM Mapper 注解**。

#### @Autowired

**参数**：`required`（bool，默认 `True`；为 False 时找不到 Bean 不会报错）

```python
from spring.annotations import Service, Autowired

@Service
class UserService:
    # 构造函数注入（推荐）
    @Autowired
    def __init__(self, user_repository):
        self.user_repository = user_repository
```

**边界**：推荐构造器注入；`required=False` 当前不会把缺失依赖自动变成 `None`。依赖参数应写类型注解，构造器注入能在启动阶段暴露缺失和循环依赖。

#### @Qualifier

**参数**：`value`（str，必填，Bean 名称）

```python
from spring.annotations import Service, Autowired, Qualifier

@Service
class OrderService:
    @Autowired
    def __init__(self, @Qualifier("mysqlDataSource") data_source):
        self.data_source = data_source
```

**边界**：当前是方法级元数据，不是 Java 那种逐参数注解；复杂多歧义依赖宜拆分或用明确类型。

#### @Primary

**含义**：当有多个同类型 Bean 时标记首选 Bean。

```python
from spring.annotations import Configuration, Bean, Primary

@Configuration
class DataSourceConfig:
    @Bean
    @Primary
    def primary_data_source(self):
        return {"url": "jdbc:mysql://primary:3306/db"}

    @Bean
    def secondary_data_source(self):
        return {"url": "jdbc:mysql://secondary:3306/db"}
```

#### @Profile

**参数**：`value`（str 或 List[str]，必填，环境名称）

```python
from spring.annotations import Configuration, Bean, Profile

@Configuration
class DataSourceConfig:
    @Bean
    @Profile("dev")
    def dev_data_source(self):
        return {"url": "jdbc:mysql://dev:3306/db"}

    @Bean
    @Profile("prod")
    def prod_data_source(self):
        return {"url": "jdbc:mysql://prod:3306/db"}
```

**边界**：容器执行；只筛 Bean，不加载或合并 `application-{profile}.yml`。

#### @Lazy

**参数**：`value`（bool，默认 `True`）

```python
from spring.annotations import Service, Lazy

@Service
@Lazy
class HeavyService:
    pass
```

**边界**：容器刷新时跳过；首次 `get_bean()`、依赖注入、控制器注册或任务注册需要它时创建，并在创建时完成配置绑定。

### 5.3 Web 控制器注解

#### @Controller / @RestController

**参数**：`value`（str，默认 `""`，Bean 名称）

`@RestController` 组合了 `@Controller` 和 `@ResponseBody`，返回值自动序列化为 JSON。

```python
from spring.annotations import RestController, GetMapping

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "test"}
```

**边界**：`@Controller` 当前仍按 JSON/`Result` 返回，没有 Java MVC 视图模板语义；`@RestController(value=...)` 的 `value` 是组件元数据，不会成为路由前缀。

#### @RequestMapping

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| path | str \| List[str] | "" | 请求路径 |
| method | List[str] | [] | HTTP 方法：GET, POST, PUT, PATCH, DELETE 等 |
| consumes | str | None | 请求的 Content-Type |
| produces | str | None | 响应的 Content-Type |

```python
from spring.annotations import RestController, RequestMapping

@RestController
@RequestMapping("/api/users")
class UserController:
    @RequestMapping(path="/{id}", method=["GET"])
    def get_user(self, id: int):
        return {"id": id}
```

**边界**：类上定义路径前缀；方法上定义路径和 HTTP method 列表。`consumes`、`produces` 当前保存但未用于路由约束。

#### @GetMapping / @PostMapping / @PutMapping / @PatchMapping / @DeleteMapping

**参数**（以 `@GetMapping` 为例）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| path | str \| List[str] | "" | 请求路径 |
| consumes | str | None | 请求 Content-Type |
| produces | str | None | 响应 Content-Type |

```python
from spring.annotations import RestController, GetMapping, PostMapping, PutMapping, PatchMapping, DeleteMapping

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "test"}

    @PostMapping("/api/users")
    def create_user(self, name: str, email: str):
        return {"id": 1, "name": name, "email": email}

    @PutMapping("/api/users/{id}")
    def update_user(self, id: int, name: str):
        return {"id": id, "name": name}

    @PatchMapping("/api/users/{id}")
    def patch_user(self, id: int, name: str = ""):
        return {"id": id, "name": name, "method": "PATCH"}

    @DeleteMapping("/api/users/{id}")
    def delete_user(self, id: int):
        return {"status": "deleted", "id": id}
```

**边界**：
- 未指定映射路径时默认使用方法名，例如 `@GetMapping` 标注 `list_users` 会映射为 `/list_users`。
- `@PatchMapping` 框架会注册为真实的 FastAPI PATCH 路由，并纳入默认 CORS 方法。
- POST/PUT/PATCH/DELETE 普通返回值统一包装为成功 `Result`。

#### @CrossOrigin

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| origins | List[str] | ["*"] | 允许的源 |
| methods | List[str] | ["GET","POST","PUT","PATCH","DELETE","OPTIONS"] | 允许的 HTTP 方法 |
| allowedHeaders | List[str] | ["*"] | 允许的请求头 |
| allowCredentials | bool | False | 是否允许携带凭证 |
| maxAge | int | 3600 | 预检请求缓存时间（秒） |

```python
from spring.annotations import RestController, GetMapping, CrossOrigin

@RestController
@CrossOrigin(origins=["http://localhost:3000"], allow_credentials=True)
class UserController:
    @GetMapping("/api/users")
    def list_users(self):
        return []
```

**边界**：Web 上下文采用找到的第一组，并传递 `origins`、方法、Header、凭证和 `maxAge`。

#### @ResponseStatus

**参数**：`code`（int，必填）、`reason`（str，默认 `""`）

```python
from spring.annotations import RestController, PostMapping, ResponseStatus

@RestController
class UserController:
    @PostMapping("/api/users")
    @ResponseStatus(code=201, reason="Created")
    def create_user(self, name: str):
        return {"id": 1, "name": name}
```

**边界**：方法级覆盖类级，`reason` 非空时成为 `Result.message`。

#### @ControllerAdvice / @ExceptionHandler

```python
from spring.annotations import ControllerAdvice, ExceptionHandler

@ControllerAdvice
class GlobalExceptionHandler:
    @ExceptionHandler(ValueError, TypeError)
    def handle_validation_error(self, e: Exception):
        return {"code": 400, "message": f"参数错误: {str(e)}"}

    @ExceptionHandler(Exception)
    def handle_generic_error(self, e: Exception):
        return {"code": 500, "message": f"服务器错误: {str(e)}"}
```

**边界**：当前按异常的精确类型匹配，不自动匹配父类。未处理异常对客户端返回通用 500，不暴露内部堆栈；详细信息写入服务日志。

### 5.4 参数绑定注解

> 参数标记的正确语法是"作为默认值"写在方法参数上，而不是写在函数上方。

#### @RequestParam

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 参数名，默认使用方法参数名 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

```python
from spring.annotations import RestController, GetMapping, RequestParam

@RestController
class UserController:
    @GetMapping("/api/users")
    def list_users(
        self,
        page: int = RequestParam(name="page", default=1),
        size: int = RequestParam(name="size", default=10)
    ):
        return {"page": page, "size": size, "data": []}
```

#### @PathVariable

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 变量名，默认使用方法参数名 |
| required | bool | True | 是否必须 |

```python
from spring.annotations import RestController, GetMapping, PathVariable

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int = PathVariable(name="id")):
        return {"id": id}
```

**边界**：路径中的 `{name}` 必须与路由对应；当前始终按必填处理。

#### @RequestBody

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| required | bool | True | 是否必须 |

```python
from spring.annotations import RestController, PostMapping, RequestBody

@RestController
class UserController:
    @PostMapping("/api/users")
    def create_user(self, user_data: dict = RequestBody()):
        return {"id": 1, **user_data}
```

**边界**：当前以 `dict` 为主；`RequestBody(required=False)` 接受空 body；需要复杂 Pydantic 模型校验时应增加 Web 集成测试。

#### @RequestHeader

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 请求头名称 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

```python
from spring.annotations import RestController, GetMapping, RequestHeader

@RestController
class UserController:
    @GetMapping("/api/user/profile")
    def get_profile(self, token: str = RequestHeader(name="Authorization")):
        return {"token": token}
```

**边界**：参数名中的 `_` 默认转换为 `-`。

#### @CookieValue

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | Cookie 名称 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

```python
from spring.annotations import RestController, GetMapping, CookieValue

@RestController
class UserController:
    @GetMapping("/api/user/theme")
    def get_theme(self, theme: str = CookieValue(name="theme", default="light")):
        return {"theme": theme}
```

**参数绑定规则汇总**：

| 写法 | 来源 |
|------|------|
| 参数名出现在 `{...}` 路径 | 路径参数 |
| 参数类型是 `dict` | JSON 请求体 |
| 有普通默认值 | 可选查询参数 |
| 无默认值且不在路径 | 必填查询参数 |
| 默认值为 `RequestParam(...)` | 显式查询参数 |
| 默认值为 `RequestBody()` | 显式请求体 |
| 默认值为 `RequestHeader(...)` | Header |
| 默认值为 `CookieValue(...)` | Cookie |

### 5.5 配置与属性注解

#### @Configuration

**参数**：`proxyBeanMethods`（bool，默认 `True`）

```python
from spring.annotations import Configuration, Bean

@Configuration
class AppConfig:
    @Bean
    def data_source(self):
        return {"url": "jdbc:mysql://localhost:3306/db"}
```

**边界**：容器执行；`proxyBeanMethods` 当前没有特殊代理语义。

#### @Bean

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | Bean 名称，默认使用方法名 |
| scope | str | "singleton" | 作用域：singleton, prototype |
| init_method | str | None | 初始化方法名 |
| destroy_method | str | None | 销毁方法名 |

```python
from spring.annotations import Configuration, Bean

@Configuration
class AppConfig:
    @Bean(name="dataSource", init_method="init", destroy_method="close")
    def data_source(self):
        return DataSource()
```

**边界**：生产资源应确保销毁方法可重复调用。

#### @Value

**参数**：`value`（str，必填，配置键）

```python
from spring.annotations import Service, Value

@Service
class AppService:
    def __init__(self):
        self.app_name = None

    @Value("${app.name}")
    def set_app_name(self, value: str):
        self.app_name = value
```

**边界**：支持通过默认参数或字段注解注入配置；使用点号路径（如 `server.port`），不要照搬 Java 的 `${server.port}` 写法：

```python
def __init__(self, port: int = Value("server.port")):
    ...
```

#### @ConfigurationProperties

**参数**：`prefix`（str，必填，配置前缀）

```python
from spring.annotations import ConfigurationProperties, Component

@Component
@ConfigurationProperties(prefix="spring.datasource")
class DataSourceProperties:
    def __init__(self):
        self.url = ""
        self.username = ""
        self.password = ""
        self.driver_class_name = ""
```

**边界**：只给对象已有属性赋值，不做完整 Pydantic 校验。对一组配置优先使用它，并为字段提供明确类型和默认值。

### 5.6 日志与生命周期注解

#### @Slf4j

**参数**：`logger_name`（str，默认 None，默认使用类名）

```python
from spring.annotations import Service, Slf4j

@Service
@Slf4j
class UserService:
    def create_user(self, name: str):
        self.logger.info(f"Creating user: {name}")
        return {"id": 1, "name": name}
```

**边界**：属性名固定为 `logger`。

#### @LogExecutionTime

**参数**：`log_level`（str，默认 "info"）

```python
from spring.annotations import Service, LogExecutionTime

@Service
class ReportService:
    @LogExecutionTime(log_level="info")
    def generate_report(self, report_type: str):
        time.sleep(1)
        return {"report": report_type}
```

**边界**：直接包装；异步方法统计完整 `await` 时间，异常时也记录。

#### @PostConstruct / @PreDestroy

```python
from spring.annotations import Service, PostConstruct, PreDestroy

@Service
class InitService:
    def __init__(self):
        self.config = None

    @PostConstruct
    def init(self):
        # 在所有依赖注入完成后执行
        self.config = self.load_config()

    @PreDestroy
    def cleanup(self):
        # 销毁前清理资源
        if self.connection:
            self.connection.close()
```

**边界**：`@PostConstruct` 每个 Bean 初始化时调用一次；`@PreDestroy` 应用必须走正常关闭流程才有机会执行。应用关闭时会销毁容器资源；ASGI 关闭事件还会关闭 MyBatis `SqlSessionFactory` 和共享连接池。

### 5.7 应用事件

`ApplicationEvent` 是事件基类，`@EventListener` 标记受管 Bean 的监听方法。`ApplicationContext` 刷新时会自动扫描监听器，`publish_event()` 默认按 `order` 同步调用匹配的监听器；异步监听方法会被调度到当前事件循环或异步执行器。

```python
from spring.annotations import ApplicationEvent, Autowired, EventListener, Service
from spring.event import ApplicationEventPublisher


class UserCreatedEvent(ApplicationEvent):
    def __init__(self, user_id: int):
        super().__init__(source="user-service")
        self.user_id = user_id


@Service
class UserEventHandler:
    @EventListener(event_type=UserCreatedEvent, order=1)
    def on_user_created(self, event: UserCreatedEvent):
        print(f"created: {event.user_id}")


@Service
class UserService:
    @Autowired
    def __init__(self, publisher: ApplicationEventPublisher):
        self.publisher = publisher

    def create(self, user_id: int):
        self.publisher.publish_event(UserCreatedEvent(user_id))
```

监听方法的第一个事件参数可以省略 `event_type`，框架会从类型注解推断。监听器必须由容器创建；发布时的监听器异常会返回给发布方，不会静默吞掉。需要隔离失败时应在监听器内部处理异常或使用异步任务。

### 5.8 核心高级注解（10 个）

#### @RateLimit - 接口限流

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_requests | int | 100 | 时间窗口内允许的最大请求数 |
| time_window | int | 60 | 时间窗口（秒） |
| key | str | None | 限流键，支持动态参数 |

**Key 动态解析规则**：直接写参数名 `key="user_id"`（按用户 ID 限流）；使用占位符 `key="ip_{ip}"`（组合前缀和参数）；不指定则使用方法全限定名作为键。

```python
from spring.annotations import RateLimit, Service

@Service
class OrderService:
    # 每分钟最多100次请求（全局限流）
    @RateLimit(max_requests=100, time_window=60)
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}

    # 按用户ID限流，每个用户每秒最多10次
    @RateLimit(max_requests=10, time_window=1, key="user_id")
    def get_user_info(self, user_id: str):
        return {"user_id": user_id}
```

**注意事项**：线程安全，支持高并发；存储有大小限制（10000 条），超出自动清理最旧条目；超出限流抛出 `Exception: Rate limit exceeded: ...`。Redis 不可用时退化为单进程内存计数。

#### @CircuitBreaker - 熔断器

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| failure_threshold | int | 5 | 连续失败次数阈值，达到后熔断 |
| recovery_timeout | int | 30 | 熔断恢复时间（秒），过后进入半开状态 |
| fallback_method | str | None | 熔断时的降级方法名 |

**状态流转**：

```
CLOSED（关闭）→ 失败达到阈值 → OPEN（熔断）
     ↑                        ↓
     ↓  半开状态成功     等待recovery_timeout
HALF_OPEN（半开） ←───────────┘
```

```python
from spring.annotations import CircuitBreaker, Service

@Service
class PaymentService:
    @CircuitBreaker(failure_threshold=3, recovery_timeout=10, fallback_method="payment_fallback")
    def process_payment(self, order_id: str, amount: float):
        if amount > 10000:
            raise Exception("Payment gateway timeout")
        return {"status": "success", "transaction_id": "TXN_123"}

    def payment_fallback(self, order_id: str, amount: float):
        return {"status": "degraded", "message": "Payment service unavailable, please try again later"}
```

**注意事项**：降级方法必须定义在同一个类中，参数列表必须与原方法完全一致；半开状态下调用成功自动恢复到关闭状态。Redis 不可用时状态仅在当前进程。

#### @Idempotent - 幂等性

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| key | str | None | 幂等键参数名，如 `"order_id"`，支持占位符 |
| expire | int | 300 | 幂等结果缓存时间（秒） |
| prefix | str | "idempotent" | 键前缀，用于区分不同业务 |

```python
from spring.annotations import Idempotent, Service

@Service
class OrderService:
    @Idempotent(key="order_id", expire=300, prefix="order")
    def create_order(self, order_id: str, user_id: str, amount: float):
        return {"order_id": order_id, "status": "created"}

    @Idempotent(expire=60)
    def generate_report(self, start_date: str, end_date: str):
        return {"report": "...", "generated_at": "..."}
```

**注意事项**：键必须包含真实业务唯一标识，不能只依赖对象字符串；缓存有大小限制，超出自动清理最旧条目；方法抛出异常时幂等键被移除允许重试；首次调用正在处理时后续请求会重新执行（简单实现）。

#### @AuditLog - 审计日志

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| action | str | "" | 操作名称，如"创建用户" |
| target | str | "" | 操作对象，如"用户管理" |
| detail | str | "" | 操作详情，支持占位符，如"删除用户{user_id}" |
| level | str | "INFO" | 日志级别：DEBUG/INFO/WARN/ERROR |

```python
from spring.annotations import AuditLog, Service

@Service
class UserService:
    @AuditLog(action="创建用户", target="用户管理", detail="创建用户{username}", level="INFO")
    def create_user(self, username: str, email: str):
        return {"user_id": 1, "username": username}
```

**注意事项**：日志在方法执行完成后（finally 块）记录；`detail` 支持 `{参数名}` 占位符动态填充；异常时状态标记为 FAILED，正常执行为 SUCCESS。**只写应用日志，不等于不可篡改审计系统。**

#### @FeatureToggle - 功能开关

**参数**：`name`（str，必填，功能名称，环境变量为 `FEATURE_{NAME}`）、`default`（bool，默认 False）

```python
from spring.annotations import FeatureToggle, Service

@Service
class FeatureService:
    @FeatureToggle(name="new_payment", default=False)
    def new_payment_flow(self, order_id: str):
        return {"status": "new_flow"}
```

**控制功能开关**：

```python
from spring.aop.comprehensive_aop import enable_feature, disable_feature

enable_feature("new_payment")
disable_feature("new_payment")
```

**注意事项**：通过环境变量 `FEATURE_{名称大写}` 控制（`true/1/yes/enabled` 不区分大小写）；功能未启用时抛出 `Exception: Feature 'xxx' is not enabled`。

#### @Lock - 分布式锁

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| key | str | None | 锁键，支持 `{参数名}` 动态拼接 |
| expire | int | 10 | 锁过期时间（秒） |
| wait_timeout | int | 5 | 等待锁的超时时间（秒） |
| prefix | str | "lock" | 锁键前缀 |

```python
from spring.annotations import Lock, Service

@Service
class StockService:
    @Lock(key="product_{product_id}", wait_timeout=3, prefix="stock")
    def deduct_stock(self, product_id: str, quantity: int):
        return {"product_id": product_id, "remaining": 100}
```

**注意事项**：锁获取失败抛出 `Exception: Could not acquire lock for ...`；key 支持动态参数（`前缀_{参数名}`）；方法执行完成后自动释放锁。Redis 可用时是分布式锁，否则只是当前进程分段锁。

#### @Metrics - 指标监控

**参数**：`name`（str，默认 None，指标名默认方法全限定名）、`tags`（List[str]，默认 None，预留扩展）

**收集的指标**：count（调用总次数）、total_time（总耗时）、errors（错误次数）、min_time（最小耗时）、max_time（最大耗时）。

```python
from spring.annotations import Metrics, Service

@Service
class OrderService:
    @Metrics(name="order.create")
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}
```

**获取指标数据**：

```python
from spring.aop.comprehensive_aop import get_metrics

metrics = get_metrics()
```

**注意事项**：每 100 次调用自动打印一次统计日志；指标存储有大小限制，超出自动清理；线程安全。`tags` 当前未进入指标数据。

#### @Synchronized - 方法同步

**参数**：`lock_name`（str，默认 None，默认使用方法全限定名）

```python
from spring.annotations import Synchronized, Service

@Service
class CounterService:
    def __init__(self):
        self.count = 0

    @Synchronized
    def increment(self):
        self.count += 1
        return self.count

    @Synchronized(lock_name="counter_lock")
    def decrement(self):
        self.count -= 1
        return self.count
```

**注意事项**：比 `@Lock` 更轻量；相同 lock_name 的方法共享同一把锁；**只使用本地锁，不是分布式锁**；当前实现不可重入，注意避免死锁。

#### @Validate - 参数校验

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| field | str | None | 要校验的参数名，不指定则校验所有参数 |
| min_length | int | None | 最小长度 |
| max_length | int | None | 最大长度 |
| min | float | None | 最小值（数值类型） |
| max | float | None | 最大值（数值类型） |
| regex | str | None | 正则表达式 |
| message | str | None | 自定义错误消息 |

```python
from spring.annotations import Validate, Service

@Service
class UserService:
    @Validate(field="username", min_length=3, max_length=20)
    @Validate(field="age", min=1, max=120)
    @Validate(field="email", regex=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    def register(self, username: str, age: int, email: str):
        return {"status": "success"}
```

**注意事项**：可以在一个方法上使用多个 `@Validate`；数值校验会自动尝试转换为 float，非数值参数跳过；校验失败抛出 `Exception: Validation failed: ...`。抛普通异常，复杂 API 校验优先使用 FastAPI/Pydantic。

#### @Trace - 分布式追踪

**参数**：`trace_id_key`（str，默认 "X-Trace-ID"）、`span_name`（str，默认 None，默认使用方法名）

```python
from spring.annotations import Trace, Service

@Service
class OrderService:
    @Trace(span_name="create_order")
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}
```

**注意事项**：同一线程内的嵌套调用共享同一个 trace_id；trace_id 基于时间戳和线程 ID 生成；异常时记录错误日志。**当前不从 HTTP Header 读取，也不向下游传播，不能替代 OpenTelemetry。**

### 5.9 事务、缓存、任务与异步注解

#### @Transactional

**参数**：`propagation`（str，默认 "REQUIRED"）、`rollback_for`（List[Type[Exception]]，默认 []）、`no_rollback_for`（List[Type[Exception]]，默认 []）

```python
from spring.annotations import Service, Transactional

@Service
class OrderService:
    @Transactional(rollback_for=[Exception])
    def create_order(self, user_id: int, product_id: int):
        # 任意一步异常都会回滚
        return {"order_id": 1}
```

**边界**：受管 Bean 执行；同步/异步方法支持 `REQUIRED`、`REQUIRES_NEW`、`NESTED`、`SUPPORTS`、`MANDATORY`、`NOT_SUPPORTED`、`NEVER`，且必须启用内嵌 MyBatis。**详细语义见第 9 章事务。**

#### @Cacheable

**参数**：`value`（str，必填，缓存名称）、`key`（str，默认 None）、`condition`（str，默认 None）

```python
from spring.annotations import Service, Cacheable

@Service
class UserService:
    @Cacheable(value="users", key="#user_id")
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}
```

**边界**：受管 Bean 执行；支持同步/异步返回值，本地内存缓存默认 TTL 300 秒；`key` 支持参数名和 `{参数名}` 模板，`condition` 支持参数名、`!参数名` 或 callable。缓存不跨进程。

#### @Retryable

**参数**：异常类型（`value`）、总尝试次数（`max_retries`）、`Backoff`、排除类型（`exclude`）、恢复方法（`recover`）

```python
from spring.annotations import Retryable
from spring.retry.retry_annotations import Backoff

@Retryable(
    value=(ConnectionError,),
    max_retries=3,
    backoff=Backoff(delay=1000, multiplier=2.0),
)
def call_remote(self):
    ...
```

**边界**：`max_retries=3` 表示最多调用三次，**包含首次调用**（不是"首次调用后再重试三次"）；旧名称 `max_attempts=3` 仍兼容，但新代码统一使用 `max_retries`，同时传两个名称且值不同时会报错。`backoff` 可传 `Backoff(...)`，也可直接传毫秒数（`backoff=500` 表示固定等待 500 毫秒）。同步方法使用阻塞等待，异步方法使用 `asyncio.sleep()`。全部失败后若设置 `recover="recover_method"`，容器调用同一 Bean 上的恢复方法，否则重新抛出最后一个异常。**只对幂等操作开启自动重试**，数据库写入、支付和消息发送必须先设计幂等键或去重机制。

#### @Async

**含义**：在线程池或事件循环中异步调度方法。

```python
from spring.annotations import Service, Async

@Service
class EmailService:
    @Async
    def send_email(self, to: str, content: str):
        time.sleep(1)  # 模拟发送耗时
        print(f"Email sent to {to}")
```

**边界**：同步方法提交到全局线程池并返回 `concurrent.futures.Future`；协程在已有 asyncio 事件循环中创建 Task，没有运行中事件循环时在线程池中运行 `asyncio.run()` 并返回 Future/Task。调用方必须 `await` 或 `.result()` 才能接收结果和异常。**线程池任务不会继承调用线程的 MyBatis 事务。**

#### @Scheduled

**参数**：`fixed_rate`（int，默认 None）、`fixed_delay`（int，默认 None）、`cron`（str，默认 None）、`initial_delay`（int，默认 0）

```python
from spring.annotations import Service, Scheduled

@Service
class ScheduledTasks:
    @Scheduled(fixed_rate=5000)   # 每 5 秒执行一次
    def report_current_time(self):
        print("Current time:", time.time())

    @Scheduled(cron="0 * * * * *")  # 每分钟执行一次
    def hourly_task(self):
        print("Hourly task executed")
```

**边界**：容器启动时实际注册；多 worker/多副本会重复执行。生产环境应使用分布式锁或独立调度服务确保单次执行。

#### @AsyncResult

**参数**：`value`。当前仅元数据，不是 Future/Task 类型。

### 5.10 安全、Cloud 与消息注解

安全注解必须放在容器创建的 Bean 上。自己 `Controller()` 或 `Service()` 创建的对象不会经过 `BeanFactory` 安全切面。

| 注解/类型 | 设计意图 | 当前真实状态 |
|-----------|----------|--------------|
| `@Authenticate` | 校验 JWT 并建立安全上下文 | 受管 Bean 实际执行；HTTP 控制器自动读取 `Authorization: Bearer ...`，普通 Bean 调用可传 `token=`；调用结束恢复原安全上下文 |
| `@PreAuthorize` | 按角色/权限表达式授权 | 受管 Bean 实际执行；未认证返回 401，权限不足返回 403 |
| `@Secured` | 按任一角色授权 | 受管 Bean 实际执行；角色来自 JWT 的 `roles` claim |
| `@EnableDiscoveryClient` | 启用服务注册发现 | 仅元数据；需要显式初始化 Nacos/发现客户端 |
| `@NacosValue` | 读取并动态刷新 Nacos 配置 | 仅元数据；不会像 `@Value` 一样被当前配置注入器读取 |
| `@RefreshScope` | 配置变化时刷新 Bean | 已接入容器刷新机制；复杂配置刷新和 Java proxy 语义不等价 |
| `@EnableFeignClients` | 扫描 Feign 接口 | 仅元数据；不会自动扫描注册 |
| `@FeignClient` | 创建远程 HTTP 客户端代理 | 仅元数据；需显式使用 `spring.cloud.feign` 中的客户端工厂；调用时自动传播 XID 和 trace 头 |
| `@SentinelResource` | 限流、业务异常 fallback | 受管 Bean 方法会包装；已内嵌限流熔断引擎，无需 Sentinel Dashboard |
| `@EnableGateway` | 启用 API Gateway | 元数据标记；配合 `GatewayRouter` 使用，内嵌轻量 ASGI/WSGI 网关 |
| `@LoadBalanced` | 给 `@Bean` 工厂返回对象添加负载均衡标记 | `@Bean` 方法上会执行，但实际请求仍需配合框架负载均衡客户端 |
| `@GlobalTransactional` | 通过 Seata 管理全局事务 | 受管 Bean 方法会调用 Seata manager；已内嵌 HTTP-AT 模式，XID 自动通过 Feign 传播；不支持嵌套 |
| `@Valid` | 非空/嵌套对象基础检查 | 受管 Bean 方法会执行简化校验，不等同 Jakarta Bean Validation |
| `@Validated` | 分组校验 | 会执行简化检查，但 `groups` 当前未驱动真正的分组规则 |
| `@RabbitListener` | 注册 RabbitMQ 消费者 | 可直接装饰受管 Bean 方法；容器声明队列/交换机、注册回调，并在刷新后启动后台消费；支持同步和异步回调 |
| `RabbitTemplate` | 主动发送 RabbitMQ 消息 | 它是普通类，不是注解；显式实例化后调用 `send()` |

#### @EnableDiscoveryClient

**参数**：`client_type`（str，默认 "nacos"，nacos/eureka/consul）

```python
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableDiscoveryClient

@SpringBootApplication
@EnableDiscoveryClient(client_type="nacos")
class Application:
    pass
```

**边界**：注解提供发现元数据；实际初始化由 `discovery.enabled` 和 `ApplicationContext` 启动流程控制。Nacos 需要安装 `nacos-sdk-python`，并配置 `NACOS_SERVER`、`NACOS_USERNAME`、`NACOS_PASSWORD`；Nacos 2.2+ Docker 还需要服务端 `NACOS_AUTH_TOKEN`、`NACOS_AUTH_IDENTITY_KEY` 和 `NACOS_AUTH_IDENTITY_VALUE`。

#### @NacosValue

**参数**：`value`（str，必填，如 `"${user.name}"`）、`auto_refreshed`（bool，默认 False）

```python
from spring.annotations import Service
from spring.annotations.cloud import NacosValue

@Service
class ConfigService:
    @NacosValue(value="${app.version}", auto_refreshed=True)
    def get_version(self):
        return self._app_version
```

**边界**：与 `@Value` 的区别是支持 `auto_refreshed` 动态刷新；基础类型效果最好，复杂实体类推荐用 `@ConfigurationProperties`。

#### @RefreshScope

**含义**：配置刷新作用域，添加此注解的类在配置变更时会重新创建实例。**参数**：无。

```python
from spring.annotations import Service
from spring.annotations.cloud import RefreshScope

@Service
@RefreshScope
class DynamicConfigService:
    def __init__(self):
        self.feature_flag = True
        self.timeout = 30
```

**触发刷新**：

```python
from spring.aop.cloud_aop import trigger_config_refresh

trigger_config_refresh()
```

**注意事项**：不能标注在 `@Controller` 上，会导致请求参数解析异常；动态配置读取建议放在 Service 层；会创建代理类，存在循环依赖的 Bean 会启动失败。

#### @EnableFeignClients

**参数**：`base_packages`（List[str]，默认 None，默认扫描启动类同包）

```python
from spring.annotations import SpringBootApplication
from spring.annotations.cloud import EnableFeignClients

@SpringBootApplication
@EnableFeignClients(base_packages=["com.example.feign"])
class Application:
    pass
```

#### @FeignClient

**参数**：`value`（str，必填，目标服务名）、`path`（str，默认 ""）、`fallback`（Type，默认 None）、`fallback_factory`（Type，默认 None）、`url`（str，默认 ""，调试用）

```python
from spring.annotations.cloud import FeignClient
from spring.annotations import GetMapping, PostMapping

@FeignClient(value="user-service", path="/api")
class UserFeign:
    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        pass  # 由 Feign 自动实现

    @PostMapping("/users")
    def create_user(self, name: str, email: str):
        pass
```

**注意事项**：`value` 值必须和目标服务的 `spring.application.name` 完全一致；目标服务有 context-path 时通过 `path` 属性指定。**不兼容 Java interface proxy**，需显式使用 `spring.cloud.feign` 中的客户端工厂。

#### @SentinelResource

**参数**（内嵌引擎版）：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | 资源名，为空时用类名.方法名 |
| block_handler | str | "" | 限流/熔断处理方法名 |
| fallback | str | "" | 业务异常降级方法名 |
| hotkey | str/bool | ""/False | 热点参数名（或是否启用热点参数限流） |
| exceptions_to_ignore | list | None | 忽略的异常类型列表 |

```python
from spring.annotations import Service
from spring.annotations.cloud import SentinelResource

@Service
class OrderService:
    @SentinelResource(value="create_order", fallback="create_order_fallback")
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}

    def create_order_fallback(self, user_id: str, product_id: str):
        return {"status": "degraded", "message": "系统繁忙，请稍后重试"}
```

**blockHandler vs fallback 区别**：**blockHandler** 处理 Sentinel 主动阻断（限流、系统保护、黑名单等）；**fallback** 处理业务异常、远程调用失败。降级/限流处理方法的返回值、参数列表必须和原方法完全一致。内嵌引擎支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流，无需 Sentinel Dashboard。

#### @EnableGateway

**参数**：无。仅网关模块启动类添加，业务服务禁止引入。配合 `GatewayRouter` 使用：

```python
from spring.cloud.gateway import GatewayRouter

gateway = GatewayRouter(discovery_client=nacos_discovery)
gateway.route("/api/users/**", "user-service", strip_prefix=True)
```

内嵌轻量 ASGI/WSGI 网关，支持路由转发、路径重写、过滤器链、负载均衡；复杂网关需求可使用 Kong/APISIX 等专业网关。

#### @LoadBalanced

**参数**：无。只能标注在 `@Bean` 修饰的创建 RestTemplate 的方法上，不能标注在注入字段、类上。实际请求仍需配合框架负载均衡客户端。

#### @GlobalTransactional

**参数**：`timeout`（int，默认 60000，毫秒）、`name`（str，默认 ""）、`rollback_for`（List[Type]，默认 []）、`no_rollback_for`（List[Type]，默认 []）

```python
from spring.annotations import Service, Autowired
from spring.annotations.cloud import GlobalTransactional

@Service
class OrderService:
    @Autowired
    def __init__(self, inventory_feign, payment_feign):
        self.inventory_feign = inventory_feign
        self.payment_feign = payment_feign

    @GlobalTransactional(timeout=30000, name="create_order_tx")
    def create_order(self, user_id: str, product_id: str, amount: float):
        order = self.save_order(user_id, product_id, amount)
        self.inventory_feign.deduct(product_id, 1)   # 远程调用
        self.payment_feign.deduct(user_id, amount)   # 远程调用
        return order
```

**注意事项**：只在事务发起入口方法添加，参与方不需要；不支持嵌套事务；所有异常都会触发回滚；禁止在异步线程中使用（事务上下文无法传递）。

#### @Valid / @Validated

**参数**：`groups`（List[Type]，默认 []）

`@Valid` 校验规则：空字符串不能为 `""`，嵌套对象递归检查属性不能为 None，实体类参数校验配合 `@RequestBody` 使用，嵌套实体校验时内部实体必须添加 `@Valid`。`@Validated` 校验规则：数值类型不能小于 0、字符串 trim 后不能为空。

**区别**：

| 特性 | @Valid | @Validated |
|------|--------|------------|
| 分组校验 | 不支持 | 支持 |
| 嵌套校验 | 支持 | 不支持 |
| 使用位置 | 方法参数、字段 | 类、方法 |

**边界**：`groups` 当前未驱动真正的分组规则，Java Bean Validation group 的完整语义目前只保留为元数据。`@Valid` 会把参数识别为 request body，实际字段校验由 FastAPI/Pydantic 的模型和约束完成。

#### @RabbitListener

```python
from spring.annotations import Component, RabbitListener


@Component
class OrderConsumer:
    @RabbitListener(
        queue="order.created",
        exchange="orders",
        routing_key="order.created",
        auto_ack=False,
        prefetch_count=8,
    )
    async def handle(self, message: dict):
        await process_order(message)
```

**边界**：启用 RabbitMQ 后，容器会声明队列、可选声明并绑定交换机、按 `prefetch_count` 注册消费者，并在容器刷新后启动后台消费。回调正常结束后手动 ack，异常时 nack 并重新入队；`auto_ack=True` 则由客户端自动确认。`RabbitTemplate` 是显式发送类。

### 5.11 MyBatis 集成注解

> 注意 `spring.orm.Mapper` 是 Spring 集成注解，而独立 PyMyBatis 的 `pymybatis.Mapper` 是标记基类，两者用法不同。`spring.annotations.Transactional` 是跨受管 Mapper 的服务层事务，`spring.orm.MapperTransactional` 是当前 Mapper/Session 的注解，两者也不要混用。

| 注解 | 放在哪里 | 作用 | 生效条件 |
|------|----------|------|----------|
| `@MapperScan` | SpringPy 启动类 | 指定 Mapper 包 | `database.enabled: true` 且 ORM 为 `mybatis`/`both` |
| `@Mapper` | Mapper 类 | 让扫描器把类注册成受管 Mapper 代理 | 类必须位于扫描包内 |
| `@Select` | Mapper 方法 | 执行查询 | 代理读取 SQL，并消费 `result_map`、`result_type`、`fetch_size`、`timeout`、`cache`；单条/列表仍受方法名规则影响 |
| `@Insert` | Mapper 方法 | 执行插入 | 支持 `use_generated_keys` 和 `key_property` 主键回写 |
| `@Update` | Mapper 方法 | 执行更新 | 参数按 Python 方法签名名称绑定，支持驱动级 `timeout` 提示 |
| `@Delete` | Mapper 方法 | 执行删除 | 参数使用 `#{name}`，不要拼接用户输入；支持驱动级 `timeout` 提示 |
| `@ResultMap` / `Result` | Mapper 类 | 把查询列改为 Python 属性名 | 可配合 `@Select(result_type=YourType)` 构造 dataclass/对象 |
| `@Options` | Mapper 方法 | 覆盖抓取、超时、缓存选项 | `flush_cache=True` 在执行前清当前 Session 查询缓存 |
| `Param` | `typing.Annotated` 参数元数据 | 让 Python 参数名映射到 SQL 名 | 使用 `identifier: Annotated[int, Param("id")]` |
| `@MapperTransactional` | Mapper 类或方法 | 给单个 Mapper 调用增加事务 | 支持七种传播模式；`REQUIRES_NEW`/`NOT_SUPPORTED` 需要连接池提供额外连接，业务层跨 Mapper 事务仍优先用 Spring `@Transactional` |

### 5.12 DDL 自动建表注解

#### @entity

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | "" | 表名，为空时自动用类名转下划线 |
| indexes | List[Index] | None | 索引列表 |
| comment | str | "" | 表注释（MySQL） |

```python
from spring.orm import entity, Index

@entity("sys_user", indexes=[
    Index("idx_username", ["username"], unique=True),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = ""):
        self.id = id
        self.username = username
        self.email = email
```

**注意事项**：`id` 字段自动成为主键自增；支持 `@dataclass` 风格实体类；驼峰命名自动转下划线；需在 `application.yml` 中配置 `database.ddl-auto.mode`。

### 5.13 注解组合使用与执行顺序

**常用组合模式**：

```python
# 接口防护三件套
@SentinelResource(value="xxx", fallback="xxx_fallback")  # 降级熔断
@Metrics(name="xxx")  # 性能监控
@RateLimit(max_requests=100, time_window=60)  # 限流
def xxx_method(self):
    pass
```

```python
# 写操作安全组合
@GlobalTransactional  # 分布式事务
@Synchronized(lock_name="xxx_lock")  # 同步锁
@AuditLog(action="xxx", target="xxx")  # 审计日志
def xxx_write_method(self):
    pass
```

```python
# 查询接口组合
@Idempotent(key="xxx_id", expire=300)  # 幂等缓存
@Metrics(name="xxx.query")  # 监控
@Trace(span_name="xxx_query")  # 追踪
def xxx_query_method(self):
    pass
```

**注解执行顺序**（AOP 从外到内）：

```
1. @SentinelResource / @CircuitBreaker  （最外层，熔断降级）
2. @RateLimit                           （限流）
3. @Lock / @Synchronized                （锁）
4. @Metrics                             （监控）
5. @Trace                               （追踪）
6. @AuditLog                            （审计）
7. @Idempotent                          （幂等）
8. @Validate / @Valid / @Validated      （参数校验）
9. 业务方法
```

**性能影响**：

| 注解 | 性能损耗 | 内存占用 | 线程安全 |
|------|----------|----------|----------|
| @RateLimit | 低 (<1ms) | 低 | ✓ 安全 |
| @CircuitBreaker | 低 (<1ms) | 低 | ✓ 安全 |
| @Idempotent | 低 (<2ms) | 中 | ✓ 安全 |
| @AuditLog | 极低 (<0.1ms) | 无 | ✓ 安全 |
| @FeatureToggle | 极低 (<0.1ms) | 无 | ✓ 安全 |
| @Lock | 中 (取决于锁竞争) | 低 | ✓ 安全 |
| @Metrics | 低 (<0.5ms) | 低 | ✓ 安全 |
| @Synchronized | 中 (取决于锁竞争) | 低 | ✓ 安全 |
| @Validate | 低 (<1ms) | 无 | ✓ 安全 |
| @Trace | 低 (<0.5ms) | 低 | ✓ 安全 |
| @SentinelResource | 低 (<1ms) | 低 | ✓ 安全 |
| @GlobalTransactional | 低 (<2ms) | 低 | ✓ 安全 |

动态键可引用方法参数名。例如 `key="order_{order_id}"` 会根据调用参数生成键：

```python
from spring.annotations import Idempotent, Lock, Metrics, Service, Validate


@Service
class PaymentService:
    @Metrics(name="payment.create")
    @Lock(key="payment_{order_id}", expire=10, wait_timeout=3)
    @Idempotent(key="payment_{order_id}", expire=300)
    @Validate(field="amount", min=0.01, message="amount must be positive")
    def create(self, order_id: str, amount: float):
        return {"order_id": order_id, "amount": amount}
```

这组注解的排列会影响包装顺序和异常可见范围。业务关键方法应测试重复请求、并发、Redis 中断、超时和异常五种路径，不要只测试一次正常调用。

---

## 6. IoC 与依赖注入

### 6.1 组件类型

| 注解 | 用途 |
|------|------|
| `@Component` | 通用组件 |
| `@Service` | 业务服务 |
| `@Repository` | 数据访问封装 |
| `@RestController` / `@Controller` | Web 控制器 |
| `@Configuration` | Bean 配置类 |
| `@Bean` | 工厂方法产生 Bean |
| `@Primary` | 同类型多个 Bean 时的首选 Bean |
| `@Profile` | 按激活环境筛选 |
| `@Lazy` | 延迟创建，直到首次被 `get_bean()`、注入、控制器或任务使用 |

### 6.2 构造器注入

```python
from spring.annotations import Autowired, Service


@Service
class GreetingService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


@Service
class UserService:
    @Autowired
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
```

依赖参数应写类型注解。构造器注入能在启动阶段暴露缺失和循环依赖，优先于字段注入。Bean 名默认由类名转换为小写下划线形式（如 `UserMapper -> user_mapper`）。

### 6.3 多实现与 @Qualifier

同类型存在多个 Bean 时，应使用 `@Primary` 或 `@Qualifier` 指定名称。

### 6.4 配置类和 Bean

```python
from spring.annotations import Bean, Configuration


@Configuration
class AppConfig:
    @Bean(name="clock")
    def clock(self):
        import time
        return time.time
```

`@Bean` 支持 `name`、`scope`、`init_method`、`destroy_method`。生产资源应确保销毁方法可重复调用。

### 6.5 配置值

`@Value` 支持通过默认参数或字段注解注入配置。对一组配置优先使用 `@ConfigurationProperties(prefix="...")`，并为字段提供明确类型和默认值。

### 6.6 生命周期

```python
from spring.annotations import Component, PostConstruct, PreDestroy


@Component
class ResourceHolder:
    @PostConstruct
    def start(self):
        pass

    @PreDestroy
    def stop(self):
        pass
```

应用关闭时会销毁容器资源；ASGI 关闭事件还会关闭 MyBatis `SqlSessionFactory` 和共享连接池。

---

## 7. Web 控制器

### 7.1 类和方法映射

```python
from spring.annotations import (
    DeleteMapping, GetMapping, PatchMapping, PostMapping, PutMapping,
    RequestMapping, RestController,
)


@RequestMapping("/users")
@RestController
class UserController:
    @GetMapping("/{user_id}")
    def get(self, user_id: int):
        return {"id": user_id}

    @PostMapping("")
    def create(self, body: dict):
        return body

    @PutMapping("/{user_id}")
    def update(self, user_id: int, body: dict):
        return {"id": user_id, **body}

    @PatchMapping("/{user_id}")
    def patch(self, user_id: int, body: dict):
        return {"id": user_id, **body, "partial": True}

    @DeleteMapping("/{user_id}")
    def delete(self, user_id: int):
        return {"deleted": user_id}
```

未指定映射路径时，默认使用方法名；类级路径前缀必须使用 `@RequestMapping("/users")`。

### 7.2 统一返回值

普通返回值会包装为 `Result.success(data=...)`。也可以显式返回：

```python
from spring.web import Result

return Result.success({"id": 1}, message="created")
return Result.bad_request("name is required")
return Result.not_found("user not found")
```

`Result.code` 会成为真实 HTTP 状态码，不只是响应体字段。

### 7.3 全局异常处理

```python
from spring.annotations import ControllerAdvice, ExceptionHandler
from spring.web import Result


@ControllerAdvice
class GlobalExceptionHandler:
    @ExceptionHandler(ValueError)
    def handle_value_error(self, error: ValueError):
        return Result.bad_request(str(error))
```

未处理异常对客户端返回通用 500，不暴露内部堆栈；详细信息写入服务日志。

### 7.4 CORS

```yaml
server:
  cors:
    allow_origins:
      - https://console.example.com
    allow_credentials: true
```

不要在 `allow_credentials: true` 时使用 `*`。默认来源列表为空，保持同源策略。

### 7.5 拦截器

```python
from spring.annotations import Component
from spring.web.interceptor import HandlerInterceptor


@Component
class AuditInterceptor(HandlerInterceptor):
    async def pre_handle(self, request, handler):
        request.state.started = True
        return True

    def after_completion(self, request, response, handler, exception=None):
        # 记录状态、耗时或异常
        pass
```

拦截器自动接入 FastAPI 请求生命周期；支持同步/异步 `pre_handle`、`post_handle`、`after_completion` 和 `/api/**` 路径规则。需要显式路径范围时，将 `InterceptorRegistry` 传给 `WebApplicationContext`，并使用 `include_path_patterns('/api/**')` / `exclude_path_patterns('/api/public/**')`。`pre_handle` 返回 `False` 时请求以 403 结束。

---

## 8. 内嵌 PyMyBatis ORM 与 DDL

### 8.1 与独立包的一致性

| 独立 | Spring 内嵌 |
|------|-------------|
| `pymybatis.Configuration` | `spring.orm.pymybatis.Configuration` |
| `pymybatis.SqlSessionFactory` | `spring.orm.pymybatis.SqlSessionFactory` |
| `pymybatis.SqlSession` | `spring.orm.pymybatis.SqlSession` |
| `pymybatis.annotations` | `spring.orm.pymybatis.annotations` |

两份 ORM 源码由契约测试约束一致，只允许包内相对导入路径不同。核心 `Configuration`、`SqlSessionFactory`、`SqlSession`、连接池、事务、动态 SQL、安全和缓存行为一致。SpringPy 额外提供 Mapper 扫描、Bean 注册、按调用管理 Session 和事务上下文绑定。

| 场景 | 导入路径 |
|------|----------|
| 独立 ORM 项目 | `from pymybatis import ...` |
| SpringPy 内嵌 ORM | `from spring.orm.pymybatis import ...` |
| Spring 容器集成 | `from spring.orm import Mapper, MapperScan, ...` |

### 8.2 数据库配置

```yaml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./data/app.db
  min_size: 1
  max_size: 5
  max_idle: 60
  wait_timeout: 5
  validation_interval: 60
  leak_detection_enabled: true
  leak_timeout: 30
  transaction:
    isolation: READ_COMMITTED
  cache:
    enabled: true
    type: lru
    size: 1024
    ttl: 300
  security:
    sql_injection_detection: true
    ast_validation_enabled: false
    sensitive_data_masking: false
    block_ddl: true
    allow_raw_params: false
  batch:
    max_size: 1000
    split_size: 100
```

Spring 集成层将这些字段转换为与独立 PyMyBatis 相同的 `Configuration`。**注意连接池配置位于 `database` 直接子级，不是 `database.pool`。**

仓库示例默认使用单连接的内存 SQLite，因此只做示例启动和容器注入时不需要安装或启动 MySQL：

```yaml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ":memory:"
  min_size: 1
  max_size: 1
```

内存数据库在进程退出后消失，适合启动验证和测试，不适合保存业务数据。SQLite 使用 `:memory:` 时框架会强制单连接，因为多个内存连接是不同数据库。

MySQL 示例：

```yaml
database:
  enabled: true
  orm: mybatis
  driver: mysql
  host: db.internal
  port: 3306
  database: app
  username: ${DB_USERNAME}
  password: ${DB_PASSWORD}
```

### 8.3 Mapper 注解

```python
from spring.orm import Delete, Insert, Mapper, Select, Update


@Mapper
class UserMapper:
    @Select("SELECT id, name, email FROM users WHERE id = #{id}")
    def find_by_id(self, id: int):
        pass

    @Select("""
        SELECT id, name, email FROM users
        <where>
            <if test="name != null">AND name = #{name}</if>
        </where>
        ORDER BY id
    """)
    def find_all(self, name=None):
        pass

    @Insert("INSERT INTO users(name, email) VALUES (#{name}, #{email})")
    def insert(self, name: str, email: str):
        pass

    @Update("UPDATE users SET name = #{name} WHERE id = #{id}")
    def update(self, id: int, name: str):
        pass

    @Delete("DELETE FROM users WHERE id = #{id}")
    def delete(self, id: int):
        pass
```

Mapper 方法参数通过 Python 签名绑定到同名 `#{...}`。**不要把 `self` 计入 SQL 参数。** Mapper 方法主体保持 `pass`，运行时由代理执行 SQL。带类型标注的单条返回值会映射成对象；`list[User]` 返回值会映射成对象列表；未标注返回类型时默认返回 `dict` 或 `list[dict]`。

结果映射、参数别名和生成键示例：

```python
from dataclasses import dataclass
from typing import Annotated, Optional

from spring.orm import (
    Insert, Mapper, Options, Param, Result, ResultMap, Select,
)


@dataclass
class User:
    id: Optional[int] = None
    display_name: str = ""


@Mapper
@ResultMap(
    id="UserMap",
    type="User",
    results=[
        Result(column="id", property="id"),
        Result(column="user_name", property="display_name"),
    ],
)
class UserMapper:
    @Options(fetch_size=100, timeout=5, use_cache=True)
    @Select(
        "SELECT id, user_name FROM users WHERE id = #{user_id}",
        result_map="UserMap",
        result_type=User,
    )
    def find_by_id(self, identifier: Annotated[int, Param("user_id")]):
        pass

    @Insert(
        "INSERT INTO users(user_name) VALUES (#{display_name})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, user: User):
        pass
```

`result_map` 先把列名改为属性名，`result_type` 再构造对象。`fetch_size` 设置游标抓取提示；`timeout` 只在驱动支持时生效；缓存是当前 Session 的本地查询缓存。`parameter_type`、`key_column`、`Result.java_type/jdbc_type` 仍是兼容字段；`@DataSource` 和 `@CacheNamespace` 目前只保存元数据。

### 8.4 Mapper 扫描

```python
from spring.annotations import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["myapp"])
@MapperScan(base_packages=["myapp.mappers"])
class Application:
    pass
```

没有 `@MapperScan` 时，默认尝试扫描启动类顶级包下的 `mappers`。显式配置更稳定。Mapper Bean 名按类名转为下划线形式。每次普通 Mapper 调用会自动创建和关闭 Session。

### 8.5 直接使用 Session

```python
from spring.orm.pymybatis import build_session_factory

factory = build_session_factory({
    "datasource": {"driver": "sqlite", "database": "./app.db"},
    "pool": {"min_size": 1, "max_size": 5},
    "security": {"block_ddl": True},
})

try:
    with factory.open_session() as session:
        rows = session.select(
            "SELECT id, name FROM users WHERE id > #{min_id}",
            {"min_id": 0},
        )
finally:
    factory.close()
```

`SqlSessionFactory` 共享一个连接池；关闭工厂会停止连接池和泄漏检测资源。

### 8.6 XML Mapper

```yaml
database:
  mapper_locations:
    - ./myapp/mappers/UserMapper.xml
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mapper namespace="myapp.mappers.UserMapper">
  <select id="findById">
    SELECT id, name FROM users WHERE id = #{id}
  </select>
</mapper>
```

调用：

```python
session.select_one("myapp.mappers.UserMapper.findById", {"id": 1})
```

动态标签支持 `if`、`where`、`foreach`、`choose/when/otherwise`、`set` 和 `trim`。

**XML Mapper 中的 SQL 可以直接写原始 `<=` 和 `>=`**；框架解析器会在解析前规范化比较运算符，并在输出 SQL 时还原，且保护 CDATA 和注释。标准 XML 工具链仍建议写成 `&lt;=` 和 `&gt;=`。

### 8.7 分页

```python
page = session.select_pagination(
    "SELECT id, name FROM users ORDER BY id",
    page_num=1,
    page_size=20,
)

cursor_page = session.select_cursor(
    "SELECT id, name FROM users",
    cursor_key="id",
    cursor_value=None,
    page_size=100,
)
```

大偏移量超过 `max_pagination_offset` 时会拒绝执行，建议改用游标分页。`cursor_key` 只接受安全标识符，不能传任意 SQL 片段。

### 8.8 SQL 安全

```sql
-- 正确：参数化
SELECT * FROM users WHERE id = #{id}

-- 默认拒绝：原始字符串替换
SELECT * FROM ${table} WHERE id = #{id}
```

`${...}` 只有在 `allow_raw_params: true` 且参数名/值通过白名单后才可使用。表名、列名、排序方向优先在应用代码中映射固定枚举，不要直接接受客户端字符串。ORM 还支持 SQL 注入检测、结果脱敏和日志脱敏，但只能作为附加防线，不能替代参数化 SQL、固定标识符白名单、最小数据库权限和审计。

### 8.9 DDL 自动建表（JPA ddl-auto 风格）

框架内置类似 Hibernate `hibernate.ddl-auto` 的自动建表功能，支持从 Python 实体类自动生成 DDL 语句。

**配置**：

```yaml
database:
  enabled: true
  driver: sqlite  # 或 mysql/postgresql
  database: ./app.db
  ddl-auto:
    mode: update  # none|validate|update|create|create-drop
    entity_packages: app.entity  # 实体类包路径，多个用逗号分隔
```

**模式说明**：

| ddl-auto 模式 | 说明 |
|--------------|------|
| `none` | 不做任何操作（默认） |
| `validate` | 启动时验证表结构与实体是否匹配，不匹配时报错 |
| `update` | 启动时创建不存在的表，为已存在的表添加新列和索引（推荐开发环境） |
| `create` | 每次启动都删除并重新创建表 |
| `create-drop` | 启动时创建，关闭时删除（测试用） |

也可以通过环境变量配置：

```bash
export DB_DDL_AUTO=update
export DB_ENTITY_PACKAGES=app.entity,app.model
```

**定义实体类**：

```python
from dataclasses import dataclass
from spring.orm import entity, Index, Column, Id

# 普通类风格
@entity("sys_user", indexes=[
    Index("idx_user_username", ["username"], unique=True),
    Index("idx_user_email", ["email"]),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = "", age: int = 0):
        self.id = id
        self.username = username
        self.email = email
        self.age = age

# dataclass 风格
@dataclass
@entity("sys_role")
class Role:
    id: int = None
    role_name: str = ""
    role_code: str = ""
```

**约定大于配置**：
- 如果类中有 `id` 字段，自动标记为主键并自增
- 字段名自动从驼峰转换为下划线命名（如 `userName` → `user_name`）
- 类型自动映射：`int→BIGINT/INTEGER`、`str→VARCHAR(255)/TEXT`、`float→DOUBLE`、`bool→TINYINT(1)/BOOLEAN`
- 支持 MySQL、PostgreSQL、SQLite 三种方言自动适配

**类型映射**：

| Python 类型 | MySQL | PostgreSQL | SQLite |
|------------|-------|------------|--------|
| `int` | BIGINT AUTO_INCREMENT | BIGSERIAL | INTEGER PRIMARY KEY AUTOINCREMENT |
| `str` | VARCHAR(255) | VARCHAR(255) | TEXT |
| `float` | DOUBLE | DOUBLE PRECISION | REAL |
| `bool` | TINYINT(1) | BOOLEAN | INTEGER |
| `bytes` | BLOB | BYTEA | BLOB |
| `datetime` | DATETIME | TIMESTAMP | TEXT |

> 生产环境建议 `block_ddl: true` 并使用 `validate` 模式或独立迁移脚本；应用迁移或初始化阶段需要建表时，应使用独立迁移脚本，运行期保持 `block_ddl: true`。开发环境使用 `update` 模式可自动同步表结构。

### 8.10 XML 功能矩阵

| Java MyBatis XML | SpringPy 状态 | 说明 |
|---|---|---|
| `<select>` / `<insert>` / `<update>` / `<delete>` | 支持 | `id` 必须在 namespace 中唯一 |
| `<resultMap>` 的 `<id>`、`<result>` | 支持 | 支持列到属性、继承 `extends` 和目标类型构造 |
| `<sql>` + `<include>` | 支持 | 支持 `<property name="..." value="..."/>` 替换片段变量 |
| `<if>`、`<where>`、`<set>`、`<trim>` | 支持 | OGNL 是受限安全子集 |
| `<choose>` / `<when>` / `<otherwise>` | 支持 | 只选择第一条成立分支 |
| `<foreach>` | 支持 | 支持 sequence、set、mapping 和对象/字典嵌套属性，最多 1000 项 |
| `<bind>` | 支持 | 支持受限表达式派生参数，例如 LIKE pattern |
| `resultType` | 支持 | 标量别名和全限定 Python 类型；未限定的自定义类型仍返回字典 |
| `fetchSize`、`timeout`、`useCache`、`flushCache` | 支持 | 语句级配置会进入执行链 |
| `useGeneratedKeys`、`keyProperty`、`keyColumn` | 支持 | 支持 DB-API `lastrowid` 的驱动；数据库仍需验证 |
| `<association>` / `<collection>` / discriminator | 支持 | 支持嵌套 `resultMap`、内联嵌套映射和 `select` 嵌套查询；集合结果按每个外层行映射 |
| `<selectKey>` | 支持 | 支持 `BEFORE/AFTER`、`keyProperty`、`keyColumn` 和 `resultType`，结果会回填参数对象/字典 |
| `databaseId` | 支持 | 按 `Configuration.dialect` 选择匹配数据库语句；匹配的数据库语句优先于通用语句 |
| `@SelectProvider` / `@InsertProvider` / `@UpdateProvider` / `@DeleteProvider` | 支持 | Provider 可为 Python 函数、类方法或全限定名称，必须返回非空 SQL 字符串 |
| Java MyBatis plugin / executor | 不兼容 | 使用 Python `Interceptor`，并为实际驱动写集成测试 |

**嵌套结果映射**：

```xml
<resultMap id="bookMap" type="acme.models.Book">
  <id column="book_id" property="id"/>
  <result column="title" property="title"/>
  <association property="author" resultMap="authorMap"/>
  <collection property="tags" select="findTags" column="book_id"/>
</resultMap>
```

`association` 可以使用 `resultMap`（同一行 JOIN 映射）或 `select`（以 `column` 值作为参数执行另一个 statement）。`collection` 的 `select` 返回列表；使用 JOIN 的集合需要在 Service 层按主键去重聚合。

**SelectProvider**：

```python
class UserSql:
    @staticmethod
    def by_keyword(params):
        return "SELECT id, name FROM users WHERE name LIKE #{keyword}"


class UserMapper:
    @SelectProvider(UserSql, method="by_keyword")
    def search(self, keyword: str) -> list[dict]:
        pass
```

Provider 只负责生成 SQL，参数仍然经过动态 SQL 处理和 TypeHandler 转换；不要在 Provider 中拼接不可信的表名或值。

**完整 XML 示例**：

```xml
<mapper namespace="acme.mappers.UserMapper">
  <sql id="columns">id, name, created_at</sql>

  <select id="search" resultMap="userMap" fetchSize="100" useCache="true">
    SELECT <include refid="columns"/> FROM users
    <bind name="pattern" value="'%' + keyword + '%'" />
    <where>
      <if test="keyword != null and keyword != ''">
        AND name LIKE #{pattern}
      </if>
    </where>
  </select>

  <insert id="insert" useGeneratedKeys="true" keyProperty="user.id">
    INSERT INTO users(name, created_at) VALUES (#{user.name}, #{user.created_at})
  </insert>
</mapper>
```

---

## 9. 事务

### 9.1 Service 事务

```python
from spring.annotations import Autowired, Service, Transactional


@Service
class RegistrationService:
    @Autowired
    def __init__(self, user_mapper: UserMapper, audit_mapper: AuditMapper):
        self.user_mapper = user_mapper
        self.audit_mapper = audit_mapper

    @Transactional(rollback_for=[Exception])
    def register(self, name: str, email: str):
        user_id = self.user_mapper.insert(name, email)
        self.audit_mapper.insert("USER_CREATED", user_id)
        return user_id
```

执行语义：

1. 进入方法时创建 Session 并开始事务。
2. 当前上下文内所有受管 Mapper 共用该 Session。
3. 正常返回时提交。
4. 满足回滚规则的异常导致回滚。
5. Session 在退出后归还连接池。

### 9.2 回滚规则

`rollback_for` 指定需要回滚的异常类型，`no_rollback_for` 指定不回滚类型。若异常被设为不回滚，事务先提交，再把原异常继续抛给上层。

### 9.3 传播级别

当前支持：

```python
@Transactional(propagation="REQUIRED")
@Transactional(propagation="NESTED")
```

`NESTED` 在已有事务中创建 savepoint；没有外层事务时等价于启动一个物理事务。`REQUIRES_NEW` 会挂起外层事务并使用独立 Session/连接；`NOT_SUPPORTED` 会挂起外层事务并以自动提交方式执行；`MANDATORY` 在没有外层事务时抛出错误；`NEVER` 在存在外层事务时抛出错误。使用 `REQUIRES_NEW` 或 `NOT_SUPPORTED` 时，连接池 `max_size` 至少应能容纳并发的外层和内层连接。

### 9.4 嵌套事务

同一 Session 的嵌套 `REQUIRED` 采用 rollback-only 语义：内层失败后，即使业务代码捕获内层异常，外层提交仍会失败并整体回滚。显式使用 `NESTED` 时，内层异常回滚到 savepoint；异常被外层捕获后，外层仍可继续写入并提交。`NESTED` 适合允许内层失败被捕获的场景。

### 9.5 手动事务

```python
with factory.open_session() as session:
    with session.transaction():
        session.insert("INSERT INTO users(name) VALUES (#{name})", {"name": "A"})
        session.insert("INSERT INTO audit(event) VALUES (#{event})", {"event": "created"})
```

也可显式写出传播参数：

```python
with session.transaction(
    isolation_level="READ_COMMITTED",
    propagation="REQUIRED",
):
    ...
```

`SqlSession.transaction()` 和 `@Transactional` 支持全部七种传播模式。省略 `propagation` 等价于 `REQUIRED`；普通写操作不在显式事务中时会自动提交。写入成功会按语句 `flushCache` 配置使查询缓存失效，失败会回滚。

---

## 10. 安全与权限

### 10.1 JWT 初始化

```yaml
jwt:
  secret_key: ${JWT_SECRET_KEY}
  algorithm: HS256
  expires_in: 3600
  issuer: springpy-api
  audience: springpy-client
  leeway: 5
```

允许算法为 `HS256`、`HS384`、`HS512`。生产密钥至少 32 字符并从密钥管理系统注入。

### 10.2 access/refresh token

```python
from spring.security.jwt_utils import JwtUtils, jwt_utils

access = jwt_utils.generate_token({"sub": "user-1"})
refresh = jwt_utils.generate_refresh_token({"sub": "user-1"})
claims = jwt_utils.decode_token(access)
new_access = jwt_utils.refresh_token(refresh)
verified_claims = jwt_utils.verify_token(access)

# 类调用委托给同一个全局实例，适合只使用应用统一 JWT 配置时调用。
another_access = JwtUtils.generate_token({"sub": "user-2"})

# 显式实例拥有独立密钥和算法，适合租户隔离或测试。
tenant_jwt = JwtUtils(secret_key="at-least-32-characters-for-tenant-a")
tenant_access = tenant_jwt.generate_token({"sub": "tenant-user"})
```

**常用 API 易错点**：
- `JwtUtils.generate_token(...)` 类调用使用已由应用配置初始化的全局实例；`JwtUtils(...)` 实例调用使用该实例自己的密钥。
- access token 不能当作 refresh token 使用，token 类型会被校验。
- `verify_token()` 验证并返回 payload，适合直接读取 `verified_claims["sub"]`；`decode_token()` 语义相同。两者对过期或无效 token 抛出异常；只需要真假结果时使用 `validate_token()`。
- 不同密钥生成的 token 不能交叉校验，不要混用不同实例生成和校验的 token。

### 10.3 方法权限注解

`@Authenticate`、`@PreAuthorize`、`@Secured` 已接入 `BeanFactory` 和 Web 上下文。`@Authenticate` 从 HTTP `Authorization: Bearer <token>` 建立当前调用的安全上下文；`@PreAuthorize` 支持 `hasRole(...)`、`hasAnyRole(...)`、`hasPermission(...)`、`hasAnyPermission(...)` 和 `authentication.name == '...'`；`@Secured` 接受一个或多个角色。认证失败映射为 HTTP 401，授权失败映射为 403。

```python
from spring.annotations import Authenticate, GetMapping, PreAuthorize, RequestMapping, RestController


@RestController
@RequestMapping("/admin")
class AdminController:
    @GetMapping("/report")
    @Authenticate
    @PreAuthorize("hasRole('ROLE_ADMIN')")
    def report(self):
        return {"scope": "admin"}
```

普通受管 Bean 方法也可通过 `method(token=access_token)` 认证。安全上下文基于 `ContextVar`，每次调用结束后恢复，避免并发请求互相污染。仍必须验证：安全上下文如何从 HTTP 请求建立；缺失、过期和伪造 token 的状态码；角色与资源级权限边界；异步调用是否传播用户上下文。

### 10.4 密码

密码哈希使用 bcrypt，不保存或记录明文密码。JWT 密钥加密签名 token，不用于保存用户密码。

### 10.5 安全基线

- 生产环境设置 `SPRING_PROFILES_ACTIVE=production` 和 `STARTUP_FAIL_FAST=true`。
- `JWT_SECRET_KEY` 使用至少 32 字符的随机密钥；生产环境会拒绝默认弱密钥。
- `CORS_ALLOW_CREDENTIALS=true` 时不能使用 `*` 来源。
- SQL 值始终使用 `#{name}` 参数绑定；`${name}` 默认禁用。
- 数据库账号按最小权限配置，运行账号不要拥有 DDL 权限。
- TLS 在可信网关或反向代理终止，并配置请求大小、超时和访问日志脱敏。
- HTTP 路由还应对缺失、过期、伪造 token 以及角色越权编写集成测试。

---

## 11. 缓存、任务与高级 AOP

### 11.1 @Cacheable

当前 `@Cacheable` 使用 `BeanFactory` 内的本地缓存，默认最多 1000 项、TTL 300 秒。`value` 是缓存命名空间；`key="user_id"` 取同名参数，`key="user_{user_id}"` 使用模板，其他字符串作为固定键；`condition="enabled"`、`condition="!skip_cache"` 或 callable 决定是否缓存。同步方法缓存普通返回值，异步方法会先 `await` 再缓存最终结果，不会缓存 coroutine。缓存不跨进程，也没有对应的自动驱逐注解。写操作后的业务缓存失效不由 ORM 查询缓存自动替代。

### 11.2 @Retryable

```python
from spring.annotations import Retryable
from spring.retry.retry_annotations import Backoff

@Retryable(
    value=(ConnectionError,),
    max_retries=3,
    backoff=Backoff(delay=1000, multiplier=2.0),
)
def call_remote(self):
    ...
```

`max_retries=3` 表示最多调用三次，包含首次调用。每次重试按 `delay`、`multiplier`、`max_delay` 和 `random_factor` 计算退避。同步方法使用阻塞等待，异步方法使用 `asyncio.sleep()`，不会阻塞事件循环。全部失败后若设置 `recover="recover_method"`，容器调用同一 Bean 上的恢复方法，否则重新抛出最后一个异常。**只对幂等操作开启自动重试。**

### 11.3 @Async

`@Async` 始终异步调度：同步方法提交到全局线程池；协程在已有 asyncio 事件循环中创建 Task，没有运行中事件循环时在线程池中运行 `asyncio.run()`。前者返回 `asyncio.Task`/包装 Future，普通同步调用返回 `concurrent.futures.Future`，调用方必须 `await` 或 `.result()` 才能接收结果和异常。线程池任务不会继承调用线程的 MyBatis 事务，不要把它当成事务内的并行执行。

### 11.4 @Scheduled

```python
from spring.annotations import Scheduled, Service


@Service
class CleanupJob:
    @Scheduled(cron="0 */5 * * * *")
    def cleanup(self):
        pass
```

多 worker 或多副本会重复注册任务。生产环境应使用分布式锁或独立调度服务确保单次执行。

### 11.5 高级 AOP 上线前验证

| 注解 | 用途 | 上线前验证 |
|------|------|------------|
| `@RateLimit` | 限流 | 多进程/多副本一致性、Redis 故障 |
| `@CircuitBreaker` | 熔断 | 状态存储、半开恢复、超时 |
| `@Idempotent` | 幂等 | 键设计、TTL、并发竞争 |
| `@AuditLog` | 审计 | 脱敏、不可抵赖、存储失败 |
| `@Lock` | 分布式锁 | 租约续期、误释放、时钟 |
| `@Metrics` | 指标 | 标签基数、抓取和资源开销 |
| `@Validate` | 校验 | 嵌套对象和错误映射 |

### 11.6 云和消息组件

`@SentinelResource`、`@GlobalTransactional` 和方法级 `@LoadBalanced` 有 AOP 消费路径；`@EnableDiscoveryClient`、`@FeignClient` 等当前主要是元数据，Nacos 实际初始化由 `discovery.enabled` 和 `ApplicationContext` 启动流程控制。Nacos 客户端需要 `nacos-sdk-python`、`NACOS_SERVER`、`NACOS_USERNAME`、`NACOS_PASSWORD`；Nacos 2.2+ Docker 服务端还需要 Base64 token 和 identity 环境变量。

配置 `rabbitmq.enabled: true` 并提供 host、port、username、password、virtual_host。开发环境也应在真实 Nacos、RabbitMQ、Redis 等环境执行集成、断线和重复投递测试。Sentinel、Seata HTTP-AT、OpenTelemetry 追踪、API Gateway 均已内嵌实现，无需外部 Server。

---

## 12. SpringPy AI 模块

SpringPy AI 模块对齐 **Spring AI 2.0**，提供 `ChatClient`/`ChatModel`/`EmbeddingModel`/`Advisor`/`Tools` 抽象，底层复用 LangChain 生态做模型适配（未安装时降级原生 HTTP），上层保留 Spring 风格的统一配置（`application.yml` 的 `spring.ai.*`）与依赖注入（BeanRegistry）。

**核心能力**：
- **多 Provider 适配**：OpenAI / Ollama / DeepSeek / Moonshot / Zhipu（LangChain 优先，HTTP 降级）
- **ChatClient 链式 API**：`client.prompt().user("...").call().content()`，对齐 Spring AI
- **Function Calling 闭环**：tools 自动注入请求体 + tool_call 循环执行回填续写（最多 5 轮）
- **RAG**：QuestionAnswerAdvisor + VectorStore（InMemory / Redis 持久化）
- **会话记忆**：MessageChatMemoryAdvisor（InMemory / Redis，多轮对话）
- **文档 ETL**：TextReader / TokenTextSplitter / CharacterTextSplitter
- **企业级能力**：熔断重试韧性（复用 spring.retry）、真流式 SSE+async、Prometheus 观测、Redis 向量存储
- **类型化配置绑定**：`AIProperties` dataclass + env 覆盖安全网

### 12.0 新手入门：AI 模块是什么？用来做什么？

> 如果你是第一次接触本项目，请先读这一节。它会用大白话讲清楚：**为什么要用 AI 模块**、**它有哪些东西**、**怎么一步一步用起来**。后面的 12.1~12.11 是详细的技术文档，遇到不懂的再回来查这里。

#### ① 它是干什么的？（目的）

简单说：**让你的 Python 程序能调用大语言模型（LLM）**——也就是让程序会「说话、理解、写代码、回答问题、查资料、调用工具」。

现实里它常被用来做这些事：

- **智能客服/聊天机器人**：程序能记住对话、像真人一样回答（记忆 + 聊天）
- **知识库问答**：把你自己的一堆文档喂进去，程序能"读了你的资料再回答"（这就是 **RAG**）
- **写代码助手**：让模型根据你的要求生成或改写代码
- **流程自动化**：让模型决定调用哪个函数（比如查天气、算价格），这就是 **Function Calling（工具调用）**

你不需要自己训练模型，只需要**申请一个模型的 API Key，然后在配置里填进去**，就能用了。

#### ② 里面有哪些概念？（新手版比喻）

| 术语 | 大白话 | 比喻 |
|------|--------|------|
| **ChatModel**（模型） | 真正"会说话"的那个大脑 | 大脑 |
| **API Key** | 使用模型的"钥匙"，证明你有权限、按用量付费 | 门禁卡 |
| **ChatClient** | 你和大模型对话的方式（链式写法） | 说话的嘴 |
| **Prompt** | 你发给模型的指令/问题 | 你说的话 |
| **Memory**（记忆） | 让模型记住前面的对话，能多轮聊下去 | 记性 |
| **RAG**（知识库问答） | 先把资料切碎存起来，回答时先检索相关资料再回答 | 查资料再答题 |
| **EmbeddingModel** | 把文字变成一串数字，用来做"相似度查找" | 给文字贴标签编号 |
| **VectorStore**（向量库） | 存这些"数字编号"的地方，用来快速检索 | 资料索引柜 |
| **Tools / Function Calling** | 让模型调用你写好的 Python 函数 | 手脚 |
| **Advisor**（顾问） | 挂在对话前后的"插件"，帮你做记忆、检索等 | 助手 |
| **ETL** | 把文档读进来、切成小块、存进向量库的流程 | 整理资料入库 |
| **FakeChatModel** | 不联网的假模型，专门用来开发/测试，不花钱 | 练习机器人 |

#### ③ 新手三步走：从零跑通第一个 AI 程序

**第 1 步：安装依赖**

```bash
pip install -r requirements-ai.txt
```

**第 2 步：先在本地用"假模型"跑通（不花钱、不联网）**

> 假模型不需要 API Key，非常适合先理解代码怎么写、流程怎么走。

```python
from spring.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

**第 3 步：接上真实模型（需要申请 Key）**

1. 去模型厂商官网申请 API Key（比如 DeepSeek、OpenAI、Moonshot）
2. 设置环境变量（把 `sk-你的真实key` 换成你自己的），**不要把真实 Key 写进代码或文档**：

```bash
export AI_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-你的真实key
```

3. 用自动装配的方式运行：

```python
from spring.ai import configure_ai

beans = configure_ai()          # 读环境变量/application.yml，自动创建好所有 AI 组件
client = beans["aiChatClient"]  # 拿到的就是"会聊天的助手"
print(client.prompt().user("你好").call().content())
```

到这里，你就已经成功让程序和大模型对话了。

#### ④ 进阶：最常用的 3 个能力（新手按需选学）

- **想让它记住多轮对话** → 看 [12.3/12.5 记忆](#123-ai-注解)（加一个 MemoryAdvisor 即可）
- **想让它"读了你的资料再回答"** → 看 [12.6 RAG/ETL](#126-文档-etl知识库入库)：先把文档切碎入库，再提问
- **想让它调用你的函数** → 看 [12.7 工具调用](#127-工具函数调用)：用 `@Tool` 装饰你的函数

#### ⑤ 新手常见误区

- ❌ 以为必须自己训练模型 → ✅ 只需申请 API Key
- ❌ 把真实 Key 写进代码/文档提交到公开仓库 → ✅ 用环境变量注入
- ❌ 问完就忘、无法多轮 → ✅ 需要加 Memory（记忆）
- ❌ 问"我自己的资料"模型说不知道 → ✅ 要用 RAG，先把资料切碎入库再问
- ❌ 没配 Key 就以为是真模型在回答 → ✅ 没配 Key 会静默降级成 `FakeChatModel`，生产环境务必设 `AI_ALLOW_FAKE=false` 防止误用假数据

### 12.1 快速开始

```bash
pip install -r requirements-ai.txt
```

最小示例（无需真实 API key，降级 FakeChatModel 即可运行）：

```python
from spring.ai import ChatClientBuilder, FakeChatModel

client = ChatClientBuilder(FakeChatModel(prefix="AI:")).build()
print(client.prompt().user("你好").call().content())
# 输出: AI: 你好
```

接入真实 OpenAI 兼容模型：

```python
from spring.ai import configure_ai

# 读取 application.yml 的 spring.ai.* 配置，自动装配所有 Bean
beans = configure_ai()
client = beans["aiChatClient"]
print(client.prompt().user("你好").call().content())
```

只需在 `application.yml` 或环境变量配置 `OPENAI_API_KEY` 即可启用真实模型；未配置时降级 `FakeChatModel`（开发/测试友好）。

### 12.2 配置（application.yml）

```yaml
spring:
  ai:
    default-provider: ${AI_PROVIDER:openai}   # openai | ollama | deepseek | moonshot | zhipu
    max-retries: ${AI_MAX_RETRIES:3}
    retry-delay-ms: ${AI_RETRY_DELAY_MS:500}
    openai:
      api-key: ${OPENAI_API_KEY:}
      base-url: ${OPENAI_BASE_URL:https://api.openai.com/v1}  # 兼容 Azure
      chat:
        model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
        temperature: ${OPENAI_TEMPERATURE:0.7}
      embedding:
        model: ${OPENAI_EMBEDDING_MODEL:text-embedding-3-small}
    ollama:
      base-url: ${OLLAMA_BASE_URL:http://localhost:11434}
      chat:
        model: ${OLLAMA_CHAT_MODEL:llama3}
        temperature: ${OLLAMA_TEMPERATURE:0.7}
    # OpenAI 兼容多厂商（经 OpenAICompatChatModel 接入，底层优先 LangChain 专用包）
    deepseek:
      api-key: ${DEEPSEEK_API_KEY:}
      base-url: ${DEEPSEEK_BASE_URL:https://api.deepseek.com}
      model: ${DEEPSEEK_MODEL:deepseek-chat}
      temperature: ${DEEPSEEK_TEMPERATURE:0.7}
    moonshot:
      api-key: ${MOONSHOT_API_KEY:}
      base-url: ${MOONSHOT_BASE_URL:https://api.moonshot.cn/v1}
      model: ${MOONSHOT_MODEL:moonshot-v1-8k}
      temperature: ${MOONSHOT_TEMPERATURE:0.7}
    zhipu:
      api-key: ${ZHIPUAI_API_KEY:}
      base-url: ${ZHIPUAI_BASE_URL:https://open.bigmodel.cn/api/paas/v4}
      model: ${ZHIPUAI_MODEL:glm-4-flash}
      temperature: ${ZHIPUAI_TEMPERATURE:0.7}
    vector-store:
      type: ${AI_VECTOR_STORE:inmemory}        # inmemory | redis
      collection: ${AI_VECTOR_COLLECTION:default}
    memory:
      store: ${AI_MEMORY_STORE:inmemory}        # inmemory | redis
      max-messages: ${AI_MEMORY_MAX:20}
    circuit-breaker:
      enabled: ${AI_CB_ENABLED:true}
      failure-threshold: ${AI_CB_FAILURE_THRESHOLD:5}
      recovery-timeout: ${AI_CB_RECOVERY_TIMEOUT:30}
```

**配置读取（混合方式）**：`configure_ai()` 读取 `spring.ai.*` 子树后，用类型化 `AIProperties` dataclass 绑定。优先级：**环境变量 > application.yml > dataclass 默认值**。环境变量通过两条路径生效：① config_loader 解析 yml 的 `${ENV:default}` 占位符；② dataclass 字段 `metadata["env"]` 声明的 env 名作为覆盖安全网（即使 yml 写死字面值也能被同名 env 覆盖）。字段类型注解驱动自动类型转换（`int`/`float`/`bool`），无需手动 `int()`/`float()`。

```python
from spring.ai import AIProperties, bind_ai_config

props: AIProperties = bind_ai_config({
    "default-provider": "openai",
    "openai": {"api-key": "sk-x", "chat": {"temperature": "0.3"}},  # 字符串自动转 float
    "circuit-breaker": {"enabled": "false"},                          # 字符串自动转 bool
})
assert props.openai.chat.temperature == 0.3
assert isinstance(props.openai.chat.temperature, float)
assert props.circuit_breaker.enabled is False
```

**环境变量速查**：

| 配置键 | 环境变量 | 默认值 |
|--------|---------|--------|
| default-provider | AI_PROVIDER | openai |
| max-retries | AI_MAX_RETRIES | 3 |
| retry-delay-ms | AI_RETRY_DELAY_MS | 500 |
| openai.api-key | OPENAI_API_KEY | （空，降级 Fake） |
| openai.base-url | OPENAI_BASE_URL | https://api.openai.com/v1 |
| openai.chat.model | OPENAI_CHAT_MODEL | gpt-4o-mini |
| openai.chat.temperature | OPENAI_TEMPERATURE | 0.7 |
| openai.embedding.model | OPENAI_EMBEDDING_MODEL | text-embedding-3-small |
| ollama.base-url | OLLAMA_BASE_URL | http://localhost:11434 |
| ollama.chat.model | OLLAMA_CHAT_MODEL | llama3 |
| vector-store.type | AI_VECTOR_STORE | inmemory |
| vector-store.collection | AI_VECTOR_COLLECTION | default |
| memory.store | AI_MEMORY_STORE | inmemory |
| memory.max-messages | AI_MEMORY_MAX | 20 |
| circuit-breaker.enabled | AI_CB_ENABLED | true |
| circuit-breaker.failure-threshold | AI_CB_FAILURE_THRESHOLD | 5 |
| circuit-breaker.recovery-timeout | AI_CB_RECOVERY_TIMEOUT | 30 |

**Redis 持久化（复用框架 RedisClient）**：当 `vector-store.type=redis` 或 `memory.store=redis` 时，`configure_ai` 自动复用框架全局 `spring.utils.redis_client.redis_client` 单例，**无需手动传 redis_client 参数**。`RedisVectorStore` 与 `RedisChatMemory` 统一用框架 `RedisClient` 封装接口（`hash_set`/`hash_get_all`/`list_push`/`list_range`），同一个 client 同时满足两者。若传入原生 `redis.Redis` 或测试 stub，自动降级原生接口。会话记忆 list 键每次 add 刷新 TTL（默认 86400 秒），防止 Redis 无限增长。

### 12.3 AI 注解

#### @AiClient

**参数**：`provider`（str，默认 ""，openai/ollama/deepseek/moonshot/zhipu，空时读 spring.ai.default-provider）、`model`（str，默认 ""）、`temperature`（float，默认 None）

```python
from spring.ai import AiClient

@AiClient(provider="openai", model="gpt-4o", temperature=0.3)
class ChatService:
    pass
```

#### @Tool

**参数**：`name`（str，默认 ""，空时用函数名）、`description`（str，默认 ""，空时取 docstring）、`return_description`（str，默认 ""）

```python
from spring.ai import Tool

@Tool(description="查询订单状态")
def get_order_status(order_id: str, detail: bool = False) -> str:
    """根据订单号返回订单状态"""
    return f"订单{order_id}已发货"
```

#### @AiAdvisor / @AiMemory

```python
from spring.ai import AiAdvisor, AiMemory

@AiAdvisor(name="ragAdvisor", order=5)
class RagAdvisor: ...

@AiMemory(store="redis", max_messages=50)
class ChatService: ...
```

### 12.4 ChatClient 链式 API

```python
from spring.ai import ChatClientBuilder, FakeChatModel

model = FakeChatModel(prefix="AI:")
client = (ChatClientBuilder(model)
          .default_system("你是助手")
          .build())

# 链式调用
answer = client.prompt().user("你好").call().content()
# 便捷终端方法
answer = client.prompt().user("你好").content()
```

### 12.5 Advisor —— RAG 与会话记忆

Advisor 在模型调用前后介入，按 `order` 升序应用请求阶段、降序应用响应阶段。

```python
from spring.ai import (
    ChatClientBuilder, FakeChatModel, FakeEmbeddingModel,
    InMemoryChatMemory, MessageChatMemoryAdvisor,
    QuestionAnswerAdvisor, SimpleInMemoryVectorStore,
)

emb = FakeEmbeddingModel(dim=16)
store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts(["SpringPy 支持 IoC 容器", "SpringPy 内嵌 Sentinel 限流"])

memory = InMemoryChatMemory()
client = (ChatClientBuilder(FakeChatModel(prefix="回答:"))
          .default_advisors(
              MessageChatMemoryAdvisor(memory),   # 多轮记忆
              QuestionAnswerAdvisor(              # RAG 检索增强
                  vector_store=store, embedding_model=emb, top_k=2),
          )
          .build())

# 多轮对话（通过 conversation_id 关联历史）
client.prompt().user("我叫张三").param("conversation_id", "u1").call()
client.prompt().user("我叫什么").param("conversation_id", "u1").call()
```

### 12.6 文档 ETL（知识库入库）

> **能用 LangChain 就用 LangChain（不做重复造轮子）**：`TokenTextSplitter`/`CharacterTextSplitter` 的切片逻辑优先委托 `langchain-text-splitters` 的 `RecursiveCharacterTextSplitter`/`CharacterTextSplitter`（自动按 `\n\n`/`\n`/空格/标点逐级切分，语义更佳），并补齐框架的 `chunk_index` 元数据；未安装该包时自动降级内置实现。安装：`pip install langchain-text-splitters==0.3.8`。向量检索可用 `LangChainVectorStore` 包装 langchain 生态的 FAISS/Chroma 等成熟向量库。

```python
from spring.ai import TextReader, TokenTextSplitter, SimpleInMemoryVectorStore

# 1. 读取
doc = TextReader().read_text("长文档内容...", source="manual")
# 2. 切片（安装 langchain-text-splitters 后优先走 LangChain 实现）
chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
# 3. 入库
store = SimpleInMemoryVectorStore()
for c in chunks:
    store.add_texts([c.content])
```

**向量存储（LangChain 适配器）**：

```python
from langchain_community.vectorstores import FAISS
from spring.ai import LangChainVectorStore

lc_store = FAISS.from_texts(["文档A", "文档B"], embedding=your_langchain_embedding)
store = LangChainVectorStore(langchain_store=lc_store)   # 包装为框架 VectorStore
```

### 12.7 工具/函数调用

```python
from spring.ai import ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="加法")
def add(a: int, b: int) -> int:
    return a + b

registry.register("add", add, description="加法")

# 查看自动生成的 schema（供 Provider 注入模型）
print(registry.schemas())
# 模型决定调用时执行
assert registry.execute("add", {"a": 1, "b": 2}) == 3
```

### 12.8 自动装配（AutoConfig）

`configure_ai()` 读取 `spring.ai.*` 配置，构建并注册 ChatModel/EmbeddingModel/ChatMemory/VectorStore/ChatClient Bean 到 BeanRegistry（含熔断器注入）。未配置 api-key 时自动降级为 FakeChatModel/FakeEmbeddingModel。

```python
from spring.ai import configure_ai
from spring.context.registry import BeanRegistry

registry = BeanRegistry()
beans = configure_ai(registry=registry)   # 读取 application.yml
client = beans["aiChatClient"]
answer = client.prompt().user("你好").call().content()
```

自动装配产出的 Bean：

| Bean 名 | 类型 | 说明 |
|---------|------|------|
| aiChatModel | ChatModel | 聊天模型（含熔断器） |
| aiEmbeddingModel | EmbeddingModel | 嵌入模型（RAG 自动嵌入） |
| aiVectorStore | VectorStore | 向量存储（inmemory/redis） |
| aiChatMemory | ChatMemory | 会话记忆（inmemory/redis） |
| aiChatClient | ChatClient | 聊天客户端（注入默认 Memory Advisor） |

### 12.9 模块组成

| 文件 | 职责 |
|------|------|
| spring/ai/core.py | ChatClient/ChatModel/EmbeddingModel/Advisor/Message 抽象（含 tool_call 执行闭环） |
| spring/ai/annotations.py | @AiClient/@Tool/@AiAdvisor/@AiMemory 注解 |
| spring/ai/providers.py | OpenAI兼容/Ollama/DeepSeek/Moonshot/ZhipuAI Provider（LangChain优先，HTTP降级）+ Fake测试模型 + 真流式SSE/async |
| spring/ai/advisors.py | QuestionAnswerAdvisor(RAG)/MessageChatMemoryAdvisor/SimpleLoggerAdvisor |
| spring/ai/memory.py | ChatMemory (InMemory/Redis) |
| spring/ai/vectorstore.py | VectorStore 抽象 + SimpleInMemoryVectorStore + RedisVectorStore（持久化）+ LangChainVectorStore（适配器） |
| spring/ai/etl.py | TextReader/TokenTextSplitter/CharacterTextSplitter（切片优先委托 langchain-text-splitters，未装则降级内置） |
| spring/ai/tools.py | ToolRegistry 函数调用注册表（签名自动生成 schema） |
| spring/ai/resilience.py | AICircuitBreaker 熔断状态机 + resilient_call 重试（复用 spring.retry） |
| spring/ai/observability.py | AIMetrics 单例（复用 PrometheusMetrics，记录调用/token/延迟/熔断） |
| spring/ai/autoconfig.py | AIProperties 类型化绑定 + spring.ai.* 配置装配 Bean |

### 12.10 企业级能力

#### 12.10.1 闭环 Function Calling

Provider 把工具 schema 注入请求体，模型返回 tool_calls 时由 `ChatModel.call()` 基类统一执行→回填 tool 消息→续写，最多 5 轮防死循环。业务侧只需注册工具并传入 `default_tools`，无需手写循环。

```python
from spring.ai import ChatClientBuilder, FakeChatModel, ToolRegistry, Tool

registry = ToolRegistry()

@Tool(description="查询天气")
def get_weather(city: str = "北京") -> str:
    return f"{city} 晴"

registry.register("get_weather", get_weather)

client = (ChatClientBuilder(FakeChatModel(prefix="AI:", simulate_tool_call=True))
          .default_tools(registry).build())
# 模型自动调用 get_weather → 回填结果 → 续写最终回复
print(client.prompt().user("调用工具查天气").call().content())
```

#### 12.10.2 韧性：重试 + 熔断

`resilient_call()` 复用框架 `spring.retry.retry_decorator.retry` 对 `TransientError`（429/5xx/超时/连接错误）自动重试；`AICircuitBreaker` 复用 `spring.aop.comprehensive_aop` 的 CLOSED/OPEN/HALF_OPEN 状态机，失败达阈值熔断、`recovery-timeout` 后半开放行探测，保护下游 LLM API。Redis 可用时跨实例共享熔断状态，不可用时降级本地内存。Provider 的 HTTP 调用默认经 `resilient_call` 包装，配置即可调（见 12.2 配置中 `max-retries`、`circuit-breaker` 段）。

**生产安全开关**：`AI_ALLOW_FAKE` 环境变量控制 api_key 缺失时的行为。
- `true`（默认）：api_key 缺失时静默降级 `FakeChatModel`，适合开发/测试
- `false`：api_key 缺失时抛 `ValueError`，防止生产环境配错返回假数据

```bash
# 生产环境务必设置：
export AI_ALLOW_FAKE=false
export OPENAI_API_KEY=sk-xxx
```

#### 12.10.3 真流式 SSE + async

`stream()` 解析 SSE `data:` 增量行逐块 yield（OpenAI）/ NDJSON（Ollama）；`astream()` 用 asyncio.Queue 桥接为异步生成器；`acall()` 用 `asyncio.to_thread` 异步调用。

```python
# 同步流式
for chunk in model.stream([Message.user("讲个故事")]):
    print(chunk.content(), end="", flush=True)

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
```

#### 12.10.4 Prometheus 观测

`AIMetrics` 单例复用框架 `PrometheusMetrics`，自动注册五项指标，Provider 调用前后自动记录，对接企业 Prometheus+Grafana：

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| ai_calls_total | Counter | provider,model,status | 模型调用次数（success/failure） |
| ai_tokens_total | Counter | provider,type | token 用量（prompt/completion） |
| ai_call_duration_seconds | Histogram | provider,model | 调用延迟分布 |
| ai_tool_calls_total | Counter | tool,status | 工具调用次数 |
| ai_circuit_breaker_state | Gauge | provider | 熔断器状态(0=CLOSED,1=OPEN,2=HALF_OPEN) |

#### 12.10.5 RedisVectorStore（RAG 持久化）

`RedisVectorStore` 用 Redis hash 持久化文档（键 `springpy:ai:vectorstore:{collection}`），支持多副本跨实例检索；注入 EmbeddingModel 实现检索时自动嵌入。`max_scan` 参数限制单次检索扫描上限（默认 10000），防止大规模文档 OOM。配置 `vector-store.type: redis` 即用（自动复用框架全局 redis_client 单例），无 client 时安全降级为内存。

```python
from spring.ai import RedisVectorStore, FakeEmbeddingModel, SearchRequest

store = RedisVectorStore(redis_client=redis_client,
                         collection="docs",
                         embedding_model=FakeEmbeddingModel(dim=16))
store.add_texts(["SpringPy 文档一", "SpringPy 文档二"])
# 检索时自动 embed query
results = store.similarity_search(SearchRequest(query="SpringPy", top_k=2))
```

`configure_ai()` 会按 `spring.ai.vector-store.type` 自动装配 `aiVectorStore`（redis 或 inmemory）并注入 `aiEmbeddingModel`，让 RAG 真正自动可用。

### 12.11 DeepSeek 全特性演示用例（已实测通过）

本节用 **DeepSeek**（OpenAI 兼容接口，走 `OpenAICompatChatModel`）跑通 AI 模块全部能力：聊天 / 流式 / 多轮记忆 / RAG / 工具调用 / ETL / 韧性 / 自动装配 / 观测。以下代码均经真实 DeepSeek API 调用验证通过。

**统一配置**（application.yml，或等价的 `AI_PROVIDER` / `DEEPSEEK_API_KEY` 环境变量）：

```yaml
spring:
  ai:
    default-provider: deepseek
    max-retries: 3
    retry-delay-ms: 500
    deepseek:
      api-key: ${DEEPSEEK_API_KEY}
      base-url: https://api.deepseek.com
      model: deepseek-chat
      temperature: 0.7
    vector-store:
      type: inmemory        # deepseek 无 Embedding API，RAG 检索用确定性向量演示
      collection: deepseek-demo
    memory:
      store: inmemory
      max-messages: 20
```

#### 12.11.1 自动装配 + 基础聊天

```python
from spring.ai import configure_ai

beans = configure_ai()                      # 读取 application.yml 自动装配（AI_PROVIDER=deepseek）
client = beans["aiChatClient"]              # 已注入 DeepSeek + Memory Advisor
print(client.prompt().user("用一句话介绍 SpringPy").call().content())
```

等价手动构建：

```python
from spring.ai import OpenAICompatChatModel, ChatClientBuilder

model = OpenAICompatChatModel(
    provider="deepseek",
    api_key="YOUR_DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
    temperature=0.7,
)
client = ChatClientBuilder(model).default_system("你是一名资深 Python 架构师").build()
print(client.prompt().user("什么是依赖注入?").call().content())
```

#### 12.11.2 真流式 SSE + async

> `astream()` 是异步生成器，**不要**对其 `await`。

```python
from spring.ai import OpenAICompatChatModel, Message

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")

# 同步逐块输出
for chunk in model.stream([Message.user("写一首关于春天的五言诗")]):
    print(chunk.content(), end="", flush=True)
print()

# 异步流式
import asyncio
async def chat():
    async for chunk in model.astream([Message.user("你好")]):
        print(chunk.content(), end="", flush=True)
asyncio.run(chat())
```

#### 12.11.3 多轮会话记忆

```python
from spring.ai import InMemoryChatMemory, MessageChatMemoryAdvisor, OpenAICompatChatModel, ChatClientBuilder

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")
memory = InMemoryChatMemory()
client = (ChatClientBuilder(model)
          .default_advisors(MessageChatMemoryAdvisor(memory))
          .build())

client.prompt().user("我叫李明，记住我").param("conversation_id", "u-1001").call()
print(client.prompt().user("我叫什么？").param("conversation_id", "u-1001").call().content())
# DeepSeek 会根据多轮上下文回答"李明"
```

#### 12.11.4 RAG 知识库问答（ETL 入库 + 检索增强）

> DeepSeek 目前**不提供 Embedding API**，RAG 检索嵌入使用确定性 `FakeEmbeddingModel`（仅作演示），生产可换 OpenAI/本地 embedding 向量库。

```python
from spring.ai import (
    OpenAICompatChatModel, FakeEmbeddingModel, SimpleInMemoryVectorStore,
    QuestionAnswerAdvisor, ChatClientBuilder, TextReader, TokenTextSplitter,
)

chat_model = OpenAICompatChatModel(provider="deepseek",
                                   api_key="YOUR_DEEPSEEK_API_KEY",
                                   base_url="https://api.deepseek.com",
                                   model="deepseek-chat")
emb = FakeEmbeddingModel(dim=16)

# 1. 知识库入库（读 -> 切 -> 存）
raw = "SpringPy 内嵌 Sentinel 限流与 OpenTelemetry 追踪；支持 Mapper 注解与 XML 混合。"
doc = TextReader().read_text(raw, source="manual")
chunks = TokenTextSplitter(chunk_size=200, chunk_overlap=50).split([doc])

store = SimpleInMemoryVectorStore(embedding_model=emb)
store.add_texts([c.content for c in chunks])

# 2. RAG 问答
client = (ChatClientBuilder(chat_model)
          .default_advisors(QuestionAnswerAdvisor(vector_store=store,
                                                  embedding_model=emb, top_k=2))
          .build())
print(client.prompt().user("SpringPy 是否支持 XML 与注解混合?").call().content())
```

#### 12.11.5 Function Calling 工具调用

```python
from spring.ai import OpenAICompatChatModel, ToolRegistry, Tool, ChatClientBuilder

model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")

registry = ToolRegistry()

@Tool(description="查询城市天气")
def get_weather(city: str = "北京") -> str:
    return f"{city}：晴，25℃"

@Tool(description="计算两数之和")
def add(a: int, b: int) -> int:
    return a + b

registry.register("get_weather", get_weather)
registry.register("add", add)

client = ChatClientBuilder(model).default_tools(registry).build()
print(client.prompt().user("帮我查询上海的天气，并计算 3+5").call().content())
# DeepSeek 自动解析工具调用 -> 框架执行 -> 回填 -> 续写最终回复（最多 5 轮闭环）
```

#### 12.11.6 文档 ETL（切片入库，LangChain 优先）

```python
from spring.ai import TextReader, TokenTextSplitter, CharacterTextSplitter

# langchain-text-splitters 已安装时，内部自动委托 RecursiveCharacterTextSplitter
reader = TextReader()
doc = reader.read_text(open("README.md", encoding="utf-8").read(), source="README.md")

tok_chunks = TokenTextSplitter(chunk_size=800, chunk_overlap=200).split([doc])
char_chunks = CharacterTextSplitter(chunk_size=500, chunk_overlap=100).split([doc])
print(f"token 切片: {len(tok_chunks)} 段, char 切片: {len(char_chunks)} 段")
```

#### 12.11.7 韧性：重试 + 熔断（真实 Provider）

```python
from spring.ai import OpenAICompatChatModel, AICircuitBreaker, Message

cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=30)
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat",
                              circuit_breaker=cb, max_retries=3, retry_delay_ms=500)
# 网络抖动时自动重试；连续失败达阈值熔断保护下游
print(model.call([Message.user("你好")]).content())
```

#### 12.11.8 Spring 注解版（@AiClient + @Tool）

```python
from spring.ai import AiClient, Tool

@AiClient(provider="deepseek", model="deepseek-chat", temperature=0.3)
class DeepSeekAssistant:
    """由容器装配的 DeepSeek 助手"""

    @Tool(description="查询订单状态")
    def order_status(self, order_id: str) -> str:
        return f"订单 {order_id} 已发货"

print(DeepSeekAssistant().order_status("A-123"))   # -> 订单 A-123 已发货
```

#### 12.11.9 Prometheus 观测

```python
from spring.ai import ai_metrics, OpenAICompatChatModel, Message

# 直接打点（record_call 为位置参数 duration，单位秒）
ai_metrics.record_call("deepseek", "deepseek-chat", "success",
                       0.5, {"prompt_tokens": 120, "completion_tokens": 80})

# 推荐：自动计时并打点成功/失败的上下文管理器
model = OpenAICompatChatModel(provider="deepseek",
                              api_key="YOUR_DEEPSEEK_API_KEY",
                              base_url="https://api.deepseek.com",
                              model="deepseek-chat")
with ai_metrics.observe("deepseek", "deepseek-chat") as m:
    resp = model.call([Message.user("你好")])        # 成功/失败自动记录
print(resp.content())
```

> **安全提醒**：以上示例使用 `${DEEPSEEK_API_KEY}` / `YOUR_DEEPSEEK_API_KEY` 占位符，**切勿把真实 key 写进代码或文档**。运行前请通过环境变量注入，避免泄露：
>
> ```bash
> export DEEPSEEK_API_KEY=sk-你的真实key
> ```
>
> 若真实 key 曾提交到公开仓库，请立即到 DeepSeek 控制台吊销并轮换。

---

## 13. Java 迁移指南

本文说明如何把现有的 Java Spring Boot、Spring Cloud Alibaba 和 MyBatis 分层代码迁移到 SpringPy。目标是保留清晰的 Controller / Service / Mapper 边界、配置习惯和常用注解意图，而不是让 Python 运行 Java 代码。

### 13.1 迁移原则

1. 先迁移接口契约和测试，再迁移框架注解。
2. Python 使用类型标注、Pydantic 和显式依赖，比模拟 Java 反射更可靠。
3. 只有由 `ApplicationContext` 创建的 Bean 才会获得事务、缓存、重试等 AOP 行为；手工 `ClassName()` 创建的对象不受容器管理。
4. Java 中的 XML SQL 可以大部分保留，但数据库函数、分页、类型名和连接配置需要按目标 Python 驱动验证。
5. 不把"有同名注解"理解为"与 Java 完全等价"。

### 13.2 项目结构对照

| Java Spring Boot | SpringPy |
|---|---|
| `src/main/java/com/acme/Application.java` | `acme/Application.py` |
| `src/main/resources/application.yml` | `acme/application.yml` 或 `acme/config/application.yml` |
| `controller/` | `acme/controller/` |
| `service/` | `acme/service/` |
| `mapper/` 和 `resources/mapper/` | `acme/mappers/` 和同目录/配置指定的 XML |
| `@SpringBootTest` | `unittest` / `pytest` + SQLite 或真实数据库集成环境 |
| `mvn spring-boot:run` | `python -m acme.Application` 或 `uvicorn asgi:app` |

每一个 Python 包目录都需要 `__init__.py`。`scan_base_packages` 和 `@MapperScan` 接受的是可导入包名，例如 `acme.service`，不是文件系统路径。

### 13.3 启动和依赖注入

**启动类**：

Java：

```java
@SpringBootApplication(scanBasePackages = "com.acme")
public class Application {
  public static void main(String[] args) {
    SpringApplication.run(Application.class, args);
  }
}
```

Python：

```python
from spring.annotations import SpringBootApplication
from spring.main import run


@SpringBootApplication(scan_base_packages=["acme"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

**Bean 注解映射**：

| Java 注解 | SpringPy 写法 | 行为和边界 |
|---|---|---|
| `@Component` | `@Component` | 受管单例 Bean |
| `@Service` | `@Service` | 受管业务 Bean |
| `@Repository` | `@Repository` | 受管数据访问 Bean；它不同于 MyBatis 的 `@Mapper` |
| `@RestController` | `@RestController` | 注册 FastAPI JSON 路由 |
| `@Controller` | `@Controller` | 当前仍按 API 响应处理，不提供 Java MVC 模板视图语义 |
| `@Configuration` + `@Bean` | 同名注解 | 支持工厂方法、scope 和生命周期回调 |
| `@Primary` | `@Primary` | 多候选 Bean 的默认注入目标 |
| `@Qualifier("name")` | `@Qualifier("name")` | 作为构造方法元数据使用；复杂逐参数歧义应拆分依赖 |
| `@Profile` | `@Profile` | 筛选 Bean，不自动合并 `application-{profile}.yml` |
| `@Lazy` | `@Lazy` | 首次需要 Bean 时才创建 |

推荐构造器注入，并用 Python 类型标注表达依赖：

```python
from spring.annotations import Autowired, Service
from acme.mappers.UserMapper import UserMapper


@Service
class UserService:
    @Autowired
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper
```

**配置**：Java `@Value("${client.timeout}")` 对应把 `Value` 放在参数默认值；`@ConfigurationProperties(prefix = "client")` 对应放在组件类上（见第 5.5 节）。

### 13.4 Web 层迁移

| Java Spring MVC | SpringPy |
|---|---|
| `@RequestMapping` | `@RequestMapping`，可标在类和方法上 |
| `@GetMapping` / `@PostMapping` | 同名注解 |
| `@PutMapping` / `@PatchMapping` / `@DeleteMapping` | 同名注解 |
| `@PathVariable` | 参数默认值 `PathVariable("id")` |
| `@RequestParam` | 参数默认值 `RequestParam("page", required=False, default=1)` |
| `@RequestBody` | 参数默认值 `RequestBody()` |
| `@RequestHeader` / `@CookieValue` | 同名参数标记 |
| `@ControllerAdvice` / `@ExceptionHandler` | 同名注解 |
| `@ResponseStatus` | 同名注解 |
| `HandlerInterceptor` | 继承 `HandlerInterceptor` 并标记 `@Component` |

```python
from pydantic import BaseModel
from spring.annotations import (
    GetMapping, PathVariable, PostMapping, RequestBody, RequestMapping,
    RestController, Valid,
)


class CreateUserRequest(BaseModel):
    name: str
    email: str


@RequestMapping("/users")
@RestController
class UserController:
    @GetMapping("/{user_id}")
    def get_one(self, user_id: int = PathVariable("user_id")):
        return {"id": user_id}

    @PostMapping("")
    def create(self, body: CreateUserRequest = Valid()):
        return {"name": body.name, "email": body.email}
```

`@Valid` 和 `@Validated` 会把该参数识别为 request body；实际字段校验由 FastAPI/Pydantic 的模型和约束完成。Java Bean Validation group 的完整语义目前只保留为元数据，不应依赖它做分组校验。

### 13.5 AOP、任务和本地事务

| Java 能力 | SpringPy | 注意事项 |
|---|---|---|
| `@Transactional` | `@Transactional` | 支持 `REQUIRED`、`REQUIRES_NEW`、`NESTED`、`SUPPORTS`、`MANDATORY`、`NOT_SUPPORTED`、`NEVER`。`REQUIRES_NEW` 使用独立 Session/连接，连接池必须能同时提供外层和内层连接 |
| `@Cacheable` | `@Cacheable` | 本地缓存默认 TTL 300 秒；Redis 后端需要额外部署 |
| Spring Retry `@Retryable` | `@Retryable` | `max_retries` 包含首次调用，只应用于幂等操作 |
| `@Async` | `@Async` | 返回 `Future` / `Task`；不会继承调用线程的数据库事务 |
| `@Scheduled` | `@Scheduled` | 每个 worker 都会调度，分布式部署需自行选主或加锁 |
| `@PostConstruct` / `@PreDestroy` | 同名注解 | 依赖正常容器启动和关闭 |

`NESTED` 适合允许内层失败被捕获的场景：内层会回滚到 savepoint，外层仍可提交。普通嵌套 `REQUIRED` 保持 Java 常见的 rollback-only 语义，内层失败即使被业务代码捕获，外层提交也会失败。

### 13.6 MyBatis 到 PyMyBatis

**Mapper 注解**：

Java：

```java
@Mapper
public interface UserMapper {
  @Select("select id, name from users where id = #{id}")
  User findById(@Param("id") long id);

  @Options(useGeneratedKeys = true, keyProperty = "id")
  @Insert("insert into users(name) values(#{user.name})")
  int insert(@Param("user") User user);
}
```

Python：

```python
from dataclasses import dataclass
from typing import Optional
from spring.orm import Insert, Mapper, Param, Select


@dataclass
class User:
    name: str
    id: Optional[int] = None


@Mapper
class UserMapper:
    @Select("SELECT id, name FROM users WHERE id = #{id}")
    def find_by_id(self, id: int) -> Optional[User]:
        pass

    @Insert(
        "INSERT INTO users(name) VALUES (#{user.name})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, user: User) -> int:
        pass
```

**XML 功能矩阵**见第 8.10 节（含 `<resultMap>`、`<sql>`+`<include>`、`<if>`/`<where>`/`<set>`/`<trim>`、`<choose>`/`<when>`/`<otherwise>`、`<foreach>`、`<bind>`、`resultType`、`fetchSize`/`timeout`/`useCache`/`flushCache`、`useGeneratedKeys`/`keyProperty`/`keyColumn`、`<association>`/`<collection>`、`<selectKey>`、`databaseId`、Provider，以及 Java plugin/executor 不兼容需使用 Python `Interceptor`）。

### 13.7 Spring Cloud Alibaba 对照

| Java 注解/组件 | SpringPy 对应 | 当前状态 |
|---|---|---|
| `@EnableDiscoveryClient` + Nacos | `@EnableDiscoveryClient` + `discovery` 配置 | 注解元数据与 Nacos 客户端配置可用；需部署 Nacos 并做注册/发现集成测试 |
| `@NacosValue` / `@RefreshScope` | 同名注解 | 元数据可用；`@RefreshScope` 已接入容器刷新机制，复杂配置刷新和 Java proxy 语义不等价 |
| `@EnableFeignClients` / `@FeignClient` | 同名注解 + `spring.cloud.feign` | 主要用于客户端元数据和 HTTP 调用；不兼容 Java interface proxy。Feign 调用自动传播 XID 和 trace 头 |
| `@LoadBalanced` | 同名注解 | 使用 Python 负载均衡实现；不要复用 `RestTemplate` 用法 |
| Sentinel `@SentinelResource` | 同名注解 | 已内嵌限流熔断引擎，无需 Dashboard；如需更强大治理能力可对接外部 Sentinel Dashboard |
| Spring Cloud Gateway | `@EnableGateway` + `GatewayRouter` | 内嵌轻量 ASGI/WSGI 网关；复杂网关需求可使用 Kong/APISIX 等专业网关 |
| Seata `@GlobalTransactional` | 同名注解 | 已内嵌 HTTP-AT 模式，无需 Seata Server，XID 自动通过 Feign 传播；如需更强一致性保障可对接外部 Seata Server |

**Cloud 高级功能迁移对照**：

| Java Spring Cloud | SpringPy 写法 | 说明 |
|---|---|---|
| Sentinel Dashboard + `@SentinelResource` | `@SentinelResource` | 内嵌引擎，无需 Dashboard；支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流 |
| SkyWalking Agent + OAP Server | `@Trace` + 内嵌 Tracer | 原生 OpenTelemetry(W3C traceparent)，无需 OAP Server；自动注入 HTTP/Feign 追踪头 |
| Seata Server + `@GlobalTransactional` | `@GlobalTransactional` | 内嵌 HTTP-AT 模式，无需 Seata Server；支持分支注册/提交/回滚，XID 自动传播 |
| Spring Cloud Gateway | `GatewayRouter` | 轻量 ASGI/WSGI 网关，支持路由转发、路径重写、过滤器链、负载均衡 |
| JPA `hibernate.ddl-auto` | `@entity` + `ddl-auto` 配置 | 支持 create/update/validate/create-drop；自动扫描实体包，自动建表/添加列/创建索引 |

**DDL Auto 迁移示例**：

Java JPA：

```java
@Entity
@Table(name = "users")
public class User {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String username;

    private String email;
}
```

SpringPy：

```python
from spring.orm import entity, Index

@entity("users", indexes=[
    Index("idx_username", ["username"], unique=True),
])
class User:
    def __init__(self, id: int = None, username: str = "", email: str = ""):
        self.id = id
        self.username = username
        self.email = email
```

application.yml 配置：

```yaml
database:
  ddl-auto:
    mode: update  # 对应 spring.jpa.hibernate.ddl-auto=update
    entity_packages: app.entity
```

### 13.8 配置迁移示例

```yaml
spring:
  application:
    name: order-service

database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./order.db
  min_size: 1
  max_size: 10
  mapper_locations:
    - acme/mappers/*.xml
  security:
    block_ddl: true
    sql_injection_detection: true
    allow_raw_params: false

discovery:
  enabled: false

server:
  host: 127.0.0.1
  port: 8080
```

Java 的 profile 文件自动合并不是当前功能。部署流程应生成最终 `application.yml`，或显式设置配置路径。数据库 DDL 使用 Alembic、Flyway 或独立迁移任务；线上运行账户不应具有 DDL 权限。

### 13.9 验证顺序

1. 创建本地环境：`python -m venv .venv`，然后 `.venv/bin/python -m pip install -e ".[dev]"`。
2. 运行内置契约测试：`.venv/bin/python -m unittest discover -s tests -v`。
3. 用 SQLite 验证 Mapper SQL、事务、动态 SQL 和类型映射。
4. 用目标 MySQL/PostgreSQL/Oracle 版本执行相同测试，特别验证自增主键、事务隔离、超时和连接中断。
5. 启动 ASGI 应用，检查 `/docs`、`/actuator/health/liveness` 和 `/actuator/health/readiness`。
6. 接入 Nacos、RabbitMQ、Redis 等外部中间件，并演练断线、重复投递和回滚。
7. 验证内嵌 Cloud 功能：`@SentinelResource` 限流熔断、`@Trace` 追踪、`@GlobalTransactional` 分布式事务、`GatewayRouter` 网关、`@entity` + `ddl-auto` 自动建表。这些功能无需部署外部 Server，但应在真实流量和故障注入下验证。

---

## 14. 生产部署

### 14.1 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.9+ | 推荐 3.12 |
| Redis | 6.0+ | 用于分布式锁、限流、缓存 |
| MySQL | 5.7+ / 8.0+ | 用于业务数据存储 |
| Nacos | 2.0+ | 服务注册发现（可选） |

> **v1.5.0+ 新特性**：Sentinel 限流熔断、OpenTelemetry 分布式追踪、Seata HTTP-AT 分布式事务、API Gateway 均已内嵌实现，无需部署外部 Server。

### 14.2 基础服务部署

**Redis：**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install redis-server
# CentOS/RHEL
sudo yum install redis
sudo systemctl start redis && sudo systemctl enable redis
redis-cli ping   # 应返回 PONG
```

配置文件 `/etc/redis/redis.conf`：设置密码 `requirepass your_secure_password`，绑定地址 `bind 0.0.0.0`（生产注意安全）。

**MySQL：**

```bash
sudo apt install mysql-server   # 或 yum install mysql-community-server
sudo systemctl start mysqld && sudo systemctl enable mysqld
```

MySQL 8+ 默认使用 `caching_sha2_password` 认证插件，若连接失败：

```sql
CREATE USER 'spring_python'@'%' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON your_database.* TO 'spring_python'@'%';
FLUSH PRIVILEGES;
-- 需要 mysql_native_password（不推荐，但兼容性更好）
ALTER USER 'spring_python'@'%' IDENTIFIED WITH mysql_native_password BY 'your_secure_password';
```

JDBC URL 建议：

```
mysql+pymysql://spring_python:password@localhost:3306/your_database?charset=utf8mb4&allowPublicKeyRetrieval=true&useSSL=false
```

**Nacos（可选）：**

```bash
wget https://github.com/alibaba/nacos/releases/download/2.3.0/nacos-server-2.3.0.tar.gz
tar -zxvf nacos-server-2.3.0.tar.gz && cd nacos/bin
./startup.sh -m standalone   # 控制台 http://localhost:8848/nacos 默认 nacos/nacos
```

Windows Docker Desktop 下 Nacos 2.2.x 在 Java 8 的 cgroup v2 环境可能因 `ProcessorMetrics` 报 NPE，启动容器时注入 `JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport`。若使用 MySQL 外部存储，需设置 `SPRING_DATASOURCE_PLATFORM=mysql`、`MYSQL_SERVICE_*` 连接参数，并先将镜像内 `/home/nacos/conf/mysql-schema.sql` 导入目标 `nacos` 数据库。

### 14.3 内嵌 Cloud 功能（无需外部部署）

- **Sentinel 限流熔断**：通过 `@SentinelResource` 注解使用，支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流。
- **OpenTelemetry 追踪**：通过 `@Trace` 注解使用，自动生成并传播 W3C `traceparent` 标准 traceId/spanId，自动注入 HTTP 请求和 Feign 调用，追踪信息通过日志输出。
- **Seata HTTP-AT 分布式事务**：通过 `@GlobalTransactional` 注解使用，通过 HTTP 端点协调跨服务事务，Feign 客户端自动传播 XID。
- **API Gateway**：`@EnableGateway` + `GatewayRouter`，支持路由转发、路径重写、全局过滤器、负载均衡。
- **ORM DDL 自动建表**：`@entity` + `database.ddl-auto`（JPA ddl-auto 风格）。

```python
from spring.annotations import SentinelResource, Trace, GlobalTransactional

@SentinelResource(value="createOrder", block_handler="handle_block", fallback="handle_fallback")
def create_order(user_id: int, product_id: int):
    pass

@Trace("order-service.create")
def create_order_traced(user_id: int):
    pass

@GlobalTransactional(timeout=60000)
def place_order(user_id: int, product_id: int):
    order_service.create(user_id, product_id)
    inventory_service.deduct(product_id)
```

### 14.4 生产配置文件

创建 `application-prod.yml`（可选）：

```yaml
server:
  port: 8080

redis:
  enabled: true
  host: your-redis-host
  port: 6379
  password: your-redis-password

jwt:
  secret_key: your-strong-secret-key-change-in-production
  expires_in: 7200

database:
  enabled: true
  url: mysql+pymysql://user:password@localhost:3306/your_database?charset=utf8mb4
  # DDL Auto 生产环境建议使用 validate 模式
  ddl-auto:
    mode: validate
    entity_packages: app.entity

discovery:
  enabled: true
  server_addr: nacos:8848
  username: ${NACOS_USERNAME}
  password: ${NACOS_PASSWORD}

logging:
  level: INFO
  log_dir: /var/log/spring-python
```

> 内嵌 Cloud 功能默认即可用，无需外部 Server，也不需要在 `application-prod.yml` 中额外配置。

**生产环境变量速查：**

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 8080 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis 地址/端口/密码 | localhost/6379/空 |
| `JWT_SECRET_KEY` | JWT 密钥 | spring-python-secret-key-change-in-production |
| `DB_URL` | 数据库连接 URL | sqlite:///./test.db |
| `DB_DDL_AUTO` | DDL 自动建表模式（none/validate/update/create/create-drop） | none |
| `DB_ENTITY_PACKAGES` | 实体类包路径，逗号分隔 | 空 |
| `DISCOVERY_ENABLED` | 是否启用 Nacos 服务发现 | false |
| `NACOS_SERVER` | Nacos 地址 | localhost:8848 |
| `NACOS_USERNAME` / `NACOS_PASSWORD` | Nacos 客户端账号/密码 | 空 |
| `SPRING_DISABLE_DOCKER_IP_DETECT` | 设为 1 禁用 Docker 容器 IP 自动检测 | 0 |

> Sentinel、OpenTelemetry 追踪、Seata HTTP-AT、API Gateway 已内嵌实现，没有对应环境变量。

### 14.5 启动应用

**开发模式：**

```bash
python -m spring.main
```

**生产模式（ASGI + Uvicorn）：**

```bash
export SPRING_PROFILES_ACTIVE=production
export JWT_SECRET_KEY="使用密钥管理系统注入至少32字符的随机值"
export STARTUP_FAIL_FAST=true
# myapp/asgi.py: from spring import create_app; app = create_app(Application)
uvicorn myapp.asgi:app --host 0.0.0.0 --port 8080 --workers 4
```

**使用 Gunicorn（推荐）：**

```bash
pip install gunicorn uvicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080 myapp.asgi:app
```

**作为系统服务（systemd）：** 创建 `/etc/systemd/system/spring-python.service`：

```ini
[Unit]
Description=Spring Python Application
After=network.target redis.service mysqld.service

[Service]
Type=simple
User=spring-python
WorkingDirectory=/opt/spring-python
Environment="SPRING_PROFILES_ACTIVE=production"
Environment="STARTUP_FAIL_FAST=true"
ExecStart=/usr/bin/python -m spring.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start spring-python
sudo systemctl enable spring-python
```

**连接池容量：** 每个 worker 有独立连接池。数据库最大连接需求近似 `实例数 x worker 数 x database.max_size`，还应给迁移、监控和运维连接预留容量。池耗尽时 `wait_timeout` 应快速失败并配合指标和告警。

**优雅退出：** ASGI shutdown 会关闭 MyBatis 工厂。仍需在部署平台设置足够终止宽限期，让在途请求、事务和消息确认完成。

### 14.6 验证部署

```bash
curl http://localhost:8080/actuator/health
```

响应示例：

```json
{
    "status": "UP",
    "components": {
        "redis": "UP",
        "database": "UP",
        "nacos": "UP",
        "rabbitmq": "UP"
    }
}
```

> Sentinel、OpenTelemetry 追踪、Seata HTTP-AT、API Gateway 已内嵌实现，不属于外部依赖组件，因此不显示在聚合健康检查中；可通过应用日志或 `@SentinelResource`、`@Trace`、`@GlobalTransactional` 注解的实际调用验证。

### 14.7 部署故障排查

**Nacos Docker 启动失败（退出码 255）：** 使用 Nacos 2.2+ 时配置 `NACOS_AUTH_ENABLE=true`、Base64 token（解码后至少 32 字节）以及 `NACOS_AUTH_IDENTITY_KEY` / `NACOS_AUTH_IDENTITY_VALUE`；Windows Docker 追加 `JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport` 并映射 8848/9848 端口；外部 MySQL 先导入 schema。用 liveness/readiness 端点验证而非只看进程状态：

```bash
curl http://127.0.0.1:8848/nacos/v1/console/health/liveness
curl http://127.0.0.1:8848/nacos/v1/console/health/readiness
```

**MySQL 认证问题（`Access denied for user 'root'@'localhost'`）：** 确认密码正确；MySQL 8+ 在 JDBC URL 添加 `allowPublicKeyRetrieval=true`；检查用户权限 `SHOW GRANTS FOR 'user'@'%';`；Docker 环境 localhost 认证失败时设置 `SPRING_DISABLE_DOCKER_IP_DETECT=0` 启用容器 IP 检测。

**Redis 连接问题（`ConnectionError: Error 111`）：** 用 `redis-cli ping` 检查服务；检查防火墙规则；检查绑定地址（`bind 0.0.0.0`）。

**DDL Auto 建表失败：** 确保数据库用户有 DDL 权限（CREATE/ALTER/DROP）；生产环境使用 `validate` 而非 `create`/`update`；检查实体字段类型是否在支持范围内（int/str/float/bool/bytes/datetime）。

---

## 15. 项目结构

`example`、`example1`、`example5` 是仓库级示例，不属于 `springpy` 安装包，不会被打包。实际项目应创建自己的应用包。

推荐目录结构：

```text
myapp/
|-- __init__.py
|-- Application.py
|-- application.yml
|-- controller/
|   |-- __init__.py
|   `-- UserController.py
|-- service/
|   |-- __init__.py
|   `-- UserService.py
|-- mappers/
|   |-- __init__.py
|   `-- UserMapper.py
|-- config/
|   `-- AppConfig.py
`-- exception/
    `-- GlobalExceptionHandler.py
```

每个被扫描目录都应包含 `__init__.py`，并从项目根目录启动，确保包可导入。`scan_base_packages` 和 `@MapperScan` 接受的是可导入包名（如 `myapp.service`），不是文件系统路径。

**Java 项目结构对照**（详见第 13 章）：

| Java Spring Boot | SpringPy |
|---|---|
| `src/main/java/com/acme/Application.java` | `acme/Application.py` |
| `src/main/resources/application.yml` | `acme/application.yml` 或 `acme/config/application.yml` |
| `controller/` / `service/` | `acme/controller/` / `acme/service/` |
| `mapper/` 和 `resources/mapper/` | `acme/mappers/` 和同目录/配置指定的 XML |
| `@SpringBootTest` | `unittest` / `pytest` + SQLite 或真实数据库集成环境 |
| `mvn spring-boot:run` | `python -m acme.Application` 或 `uvicorn asgi:app` |

---

## 16. 测试

### 16.1 运行测试

从工作区根目录：

```bash
python -m pytest -q tests
```

> 详细的测试环境、套件覆盖、功能矩阵、企业就绪评估与 example_all 集成测试结果，见 [TEST_REPORT.md](TEST_REPORT.md)。

### 16.2 重点覆盖

- 独立和内嵌 ORM 源码一致。
- 连接池共享、扩容、归还和未提交回滚。
- 普通事务与嵌套 rollback-only。
- Spring Mapper 在事务中复用 Session。
- JWT access/refresh、生产密钥校验。
- 配置占位符类型和 CORS/HTTP 错误状态。
- AI 模块 87 用例（LangChain 切片委托 + 向量库适配器），全量 707 用例 0 失败。

---

## 17. 常见问题与排错

### 17.1 启动时找不到组件

1. 目录是否有 `__init__.py`。
2. `scan_base_packages` 是否是可导入包名，不是文件路径。
3. 启动工作目录是否包含项目根目录。
4. 组件类是否带 `@Service`、`@RestController` 等注解。
5. `@Profile` 是否与当前环境一致。

### 17.2 Mapper 未注册

检查 `database.enabled: true`、`database.orm: mybatis`、`@Mapper`、`@MapperScan` 路径和 Mapper 模块导入错误。扫描失败会写 warning，应查看完整启动日志。

### 17.3 `@Transactional` 报缺少工厂

说明 MyBatis 没有初始化。确认数据库已启用、ORM 模式正确、配置有效，并且 Service 是由 Spring 容器创建而不是手工 `UserService()`。

### 17.4 数据库连接耗尽

检查 Session 是否通过上下文管理器关闭、请求是否有长事务、查询是否阻塞，以及 `实例 x worker x max_size` 是否超过数据库上限。不要在全局变量中长期保存 `SqlSession`。

### 17.5 生产启动拒绝 JWT

设置：

```bash
SPRING_PROFILES_ACTIVE=production
STARTUP_FAIL_FAST=true
JWT_SECRET_KEY=<至少32字符随机密钥>
```

不要把真实密钥提交到仓库。

### 17.6 Nacos、PATCH 和配置同步排错

**Nacos Docker 退出码 255 且日志提示 `NACOS_AUTH_TOKEN`：** 确认服务端同时配置了 `NACOS_AUTH_ENABLE=true`、Base64 编码且解码后至少 32 字节的 `NACOS_AUTH_TOKEN`、`NACOS_AUTH_IDENTITY_KEY` 和 `NACOS_AUTH_IDENTITY_VALUE`。Windows Docker 还应设置 `JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport`，并把镜像中的 `mysql-schema.sql` 导入外部 Nacos 数据库。

**`PATCH /api/...` 返回 404：** 确认方法使用 `@PatchMapping`，并检查 Web 上下文日志中是否注册了 PATCH 路由；框架已将该注解接入 `fastapi_app.patch()`，不需要手工调用 `add_api_route`。

**`ConfigLoader()` 与上下文读取不同文件：** 确认应用通过 `ApplicationContext` 启动，而不是只在不同工作目录直接实例化加载器。上下文启动后会绑定全局实例和默认配置目录；需要加载独立配置时显式传入 `config_path` 或 `base_path`。

### 17.7 上线前清单

- 使用实际 MySQL/PostgreSQL/Oracle 版本运行 CRUD、事务、断连恢复和池耗尽测试。
- 使用迁移工具管理结构，不让应用运行账号执行 DDL。
- 锁定依赖并生成 SBOM，执行漏洞和许可证扫描。
- 为 JWT、数据库、Redis、RabbitMQ 使用密钥管理系统。
- 配置 TLS、CORS 白名单、请求限制和真实 HTTP 错误码监控。
- 验证备份恢复、主从切换和慢 SQL 告警。
- 对定时任务、多 worker 和多副本设计唯一执行或幂等。
- 执行越权、SQL 注入、重放、日志泄露和依赖故障测试。
- 验证优雅退出不会中断事务或丢失消息。

---

## 附录 A：完整环境变量清单

```bash
# Server
export SERVER_PORT=8080
export SERVER_HOST=0.0.0.0

# Redis
export REDIS_ENABLED=true
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=
export REDIS_DB=0
export REDIS_TIMEOUT=5000

# JWT
export JWT_SECRET_KEY=your-secret-key
export JWT_ALGORITHM=HS256
export JWT_EXPIRES_IN=3600

# Database
export DB_ENABLED=false
export DB_URL=sqlite:///./test.db
export DB_USERNAME=
export DB_PASSWORD=
export DB_DRIVER=sqlite
export DB_HOST=localhost
export DB_PORT=3306
export DB_DATABASE=./test.db

# ORM DDL Auto
export DB_DDL_AUTO=none  # none|validate|update|create|create-drop
export DB_ENTITY_PACKAGES=  # 实体类包路径，逗号分隔

# Nacos
export DISCOVERY_ENABLED=false
export NACOS_SERVER=localhost:8848
export NACOS_NAMESPACE=
export NACOS_GROUP=DEFAULT_GROUP
export NACOS_USERNAME=nacos
export NACOS_PASSWORD=nacos

# Nacos Docker server authentication (Nacos 2.2+)
export NACOS_AUTH_ENABLE=true
export NACOS_AUTH_TOKEN=<base64-token-with-at-least-32-decoded-bytes>
export NACOS_AUTH_IDENTITY_KEY=springpy
export NACOS_AUTH_IDENTITY_VALUE=springpy-local

# Docker 辅助
export SPRING_DISABLE_DOCKER_IP_DETECT=0  # 设为1禁用容器IP自动检测

# Retry
export RETRY_ENABLED=true
export RETRY_MAX_RETRIES=3
export RETRY_DELAY=1000
export RETRY_MAX_DELAY=10000
export RETRY_MULTIPLIER=2.0
export RETRY_RANDOM_FACTOR=0.1

# RabbitMQ
export RABBITMQ_ENABLED=false
export RABBITMQ_HOST=localhost
export RABBITMQ_PORT=5672
export RABBITMQ_USERNAME=guest
export RABBITMQ_PASSWORD=guest

# Prometheus
export PROMETHEUS_ENABLED=false
export PROMETHEUS_PORT=8000

# Logging
export LOG_LEVEL=INFO
export LOG_DIR=logs
```

> Sentinel 限流熔断、OpenTelemetry 分布式追踪、Seata HTTP-AT 分布式事务、API Gateway 均为内嵌实现，无对应环境变量。AI 模块环境变量见第 12.2 节。

## 附录 B：Docker Compose 示例

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  mysql:
    image: mysql:8.0
    ports:
      - "3306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: example_db
    volumes:
      - mysql_data:/var/lib/mysql

  nacos:
    image: nacos/nacos-server:v2.3.0
    ports:
      - "8848:8848"
      - "9848:9848"
    environment:
      MODE: standalone
      # Nacos 2.2+ requires a Base64-encoded token (at least 32 decoded bytes)
      NACOS_AUTH_ENABLE: "true"
      NACOS_AUTH_TOKEN: "c3ByaW5ncHktbmFjb3MtaGFuZHNoYWtlLXNlY3JldC0yMDI2LTA4LTA0LTAx"
      NACOS_AUTH_IDENTITY_KEY: "springpy"
      NACOS_AUTH_IDENTITY_VALUE: "springpy-local"
      JAVA_TOOL_OPTIONS: "-XX:-UseContainerSupport"

volumes:
  redis_data:
  mysql_data:
```