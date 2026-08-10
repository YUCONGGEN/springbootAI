# SpringBootAI 综合使用指南

SpringBootAI 是一个借鉴 Spring Boot 编程模型的 Python Web 框架，提供装饰器式组件扫描、依赖注入、FastAPI 路由、配置加载、安全能力、内嵌的 PyMyBatis ORM，以及企业级 AI 模块（对齐 Spring AI 2.0：ChatClient/Advisor/Tools/RAG/Function Calling）。本指南为框架核心综合使用文档；**AI / ORM / Cloud / Excel 等模块的完整注解与功能说明已分离为独立文档**（见下方“模块文档”），本指南相应章节保留概览与跳转链接。

- SpringBootAI 版本：`1.8.8`
- 内嵌 PyMyBatis 版本：`1.4.0`
- Python：3.10+
- 状态：Beta（企业试点）0
- 仓库：[GitHub - YUCONGGEN/springbootAI](https://github.com/YUCONGGEN/springbootAI)
- License：MIT

## 模块文档

第一次使用请先读 [新手入门指南](doc/BEGINNER_GUIDE.md)。它从安装开始，带你创建第一个接口，并解释 Controller、Service、Bean、依赖注入和配置文件是什么。各模块文档统一按“解决什么问题 -> 如何启用 -> 最小示例 -> 如何验证 -> 常见错误 -> 生产边界”组织，按需查阅即可，不要求一次读完。

| 模块 | 文档 | 安装 | 说明 |
|------|------|------|------|
| 新手入门 | [BEGINNER_GUIDE.md](doc/BEGINNER_GUIDE.md) | 随核心包 | 从零安装、创建项目、运行接口、打开 Swagger、选择后续模块 |
| 常用注解模块 | [ANNOTATION_MODULES.md](doc/ANNOTATION_MODULES.md) | 随核心包 | Bean Validation / 条件装配 / 缓存增强 / CSV / `@Version` / `@Transient` |
| AI（对齐 Spring AI 2.0） | [AI_MODULE.md](doc/AI_MODULE.md) | `pip install springbootAI[ai]` | ChatClient / Advisor / Tools / RAG / Function Calling / ETL / 多厂商 LangChain 化 / 韧性 / 观测 |
| LangChain（封装 langchain classic 全套） | [LANGCHAIN_MODULE.md](doc/LANGCHAIN_MODULE.md) | `pip install springbootAI[ai]` | Chains / Agents / Memory / Retrievers / VectorStores / Parsers / Loaders / 30+ Partner 提供商 / 双向适配器 / 一键 RAG |
| AI 与 LangChain 测试指南 | [AI_LANGCHAIN_TEST_GUIDE.md](doc/AI_LANGCHAIN_TEST_GUIDE.md) | — | 162 个测试用例详解（有什么用/怎么用/验证什么），覆盖核心抽象到端到端集成 |
| 内嵌 PyMyBatis ORM 与 DDL | [ORM_MODULE.md](doc/ORM_MODULE.md) | 随核心包 | Mapper 注解 / XML Mapper / 分页 / SQL 安全 / DDL 自动建表 |
| Spring Cloud（对齐 Cloud Alibaba） | [CLOUD_MODULE.md](doc/CLOUD_MODULE.md) | 随核心包 | 服务注册发现 / 配置刷新 / Feign / Sentinel / Gateway / 负载均衡 / 分布式事务 |
| Excel（对齐 alibaba EasyExcel） | [EXCEL_MODULE.md](doc/EXCEL_MODULE.md) | `pip install springbootAI[excel]` | `@ExcelProperty` / `@ExcelIgnore` / `@excel_sheet` 注解驱动读写 |
| CSV（注解驱动读写） | [CSV_MODULE.md](doc/CSV_MODULE.md) | `pip install springbootAI[csv]` | `@CsvProperty` / `@CsvIgnore` / `@csv_file` 注解驱动读写 / 转换器 / 流式 |
| Swagger / OpenAPI（对齐 SpringDoc） | [SWAGGER_MODULE.md](doc/SWAGGER_MODULE.md) | 随核心包 | `@Tag` / `@Operation` / `@ApiResponse` / `@Parameter` / `@Schema` / `@SecurityScheme` 注解驱动 API 文档 + Swagger2 别名 |
| P0/P1/P2 八大模块 | [EIGHT_MODULES.md](doc/EIGHT_MODULES.md) | 随核心包 | Spring Data Repository / Actuator / 多数据源读写分离 / 事务事件 / 配置松散绑定 / 测试切片 / i18n / WebSocket |
| 安全 | [SECURITY.md](doc/SECURITY.md) | 随核心包 | JWT 生成校验 / 密码加密（SHA256/MD5/BCrypt）/ SQL 注入防护 / 访问控制 |
| BeanUtils（属性复制工具） | [BEAN_UTILS.md](doc/BEAN_UTILS.md) | 随核心包 | `copy_properties` / `clone` / `get_property` / `set_property` / `populate` / `describe` 对齐 Spring + Apache Commons BeanUtils |
| 测试报告 | [TEST_REPORT.md](doc/TEST_REPORT.md) | — | 全量测试用例与覆盖范围 |

> 所有模块文档统一存放于 [`doc/`](doc/) 目录。本指南正文中出现的"已分离至独立文档"链接均指向 `doc/` 下的对应文件。

### 新手推荐阅读顺序

1. 按 [新手入门指南](doc/BEGINNER_GUIDE.md) 跑通 `/api/hello/{name}`。
2. 阅读本页第 4、6、7 章，理解配置、依赖注入和 Controller。
3. 做数据库 CRUD 时阅读 [ORM_MODULE.md](doc/ORM_MODULE.md)。
4. 需要输入校验、缓存或条件开关时阅读 [ANNOTATION_MODULES.md](doc/ANNOTATION_MODULES.md)。
5. 最后再按业务需要选择安全、Cloud、AI、LangChain、Excel、WebSocket 或性能测试文档。

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
12. [SpringBootAI AI 与 LangChain 模块](#12-springbootai-ai-与-langchain-模块)
13. [Java 迁移指南](#13-java-迁移指南)
14. [生产部署](#14-生产部署)
15. [项目结构](#15-项目结构)
16. [测试](#16-测试)
17. [常见问题与排错](#17-常见问题与排错)
18. [性能与容量验证](#18-性能与容量验证)

---

## 1. 框架概述与定位

SpringBootAI 借鉴了 Spring Boot 的注解和分层习惯，但运行时是 Python、FastAPI 和 Uvicorn。**它不兼容 Java 字节码、Spring Bean 后处理器、JPA、Java MyBatis 插件或 Maven/Gradle 生态。**

### 1.1 版本

| 组件 | 当前版本 |
|------|----------|
| `spring` 框架 API | 1.8.8 |
| `spring.orm.pymybatis` | 1.4.0 |
| `spring.ai` AI 模块 | 1.3.0 |
| `spring.langchain` LangChain 模块 | 1.0.0 |
| Python | 3.10+ |

### 1.2 推荐使用范围

- 内部管理接口、轻量业务服务、教学和原型验证。
- 希望统一使用控制器/服务/Mapper 分层方式的 Python 团队。
- SQLite 本地工具，或经过目标数据库集成测试的受控服务。
- 微服务架构（内置服务发现、限流熔断、分布式追踪、分布式事务）。

### 1.3 能力边界

- 自动化 ORM 契约测试使用 SQLite；MySQL、PostgreSQL、Oracle 需单独验证。
- 本地 `@Transactional` 支持全部七种 Spring 传播模式；`REQUIRES_NEW` 和 `NOT_SUPPORTED` 需要连接池有额外可用连接。
- Profile 会筛选 `@Profile` Bean，但不会自动合并 `application-{profile}.yml`。
- Nacos、RabbitMQ、Prometheus 依赖外部服务；Sentinel 和 OpenTelemetry 追踪可内嵌运行。HTTP 事务模式是持久化补偿协调器，不提供 Seata AT 强一致性；生产强一致场景必须使用真实 Seata Server 或可靠消息方案。
- 限流、分布式锁、幂等和缓存语义依赖 Redis 等后端，降级路径需要故障注入。

### 1.4 注解使用总览

SpringBootAI 注解会先把元数据放到 `__spring_annotations__`。之后是否生效，取决于是否存在对应的扫描器或切面：

| 状态 | 含义 |
|------|------|
| 容器执行 | `ApplicationContext`、`BeanFactory` 或 Web 上下文会读取并执行 |
| 受管 Bean 执行 | 只有被组件扫描并由容器创建的实例方法才会被 AOP 包装；自己 `ClassName()` 创建的对象不生效 |
| 直接执行 | 装饰器本身返回包装函数，不依赖 IoC 容器 |
| 仅元数据 | 当前有注解类，但主运行链路没有消费者，写上不会得到注解名字所暗示的功能 |

这也是 SpringBootAI 与 Java Spring 最容易混淆的地方：名称相似不代表参数和运行语义完全相同。

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
| Seata 分布式事务 | ⚠️ 有边界 | `distributed` 对接真实 Seata SDK/Server；`http` 仅提供显式启用的持久化补偿，支持重启恢复和 XID 传播，不等同 AT |
| API Gateway | ✅ 可用 | 轻量 ASGI/WSGI 网关，路由转发、路径重写、过滤器链、负载均衡 |
| Prometheus 监控 | ✅ 可用 | Counter/Gauge/Histogram 指标暴露 |
| Feign 声明式 HTTP | ✅ 可用 | 声明式接口、Fallback 降级、自动传播 XID 和 trace 头 |
| 高级 AOP | ✅ 可用 | 限流、熔断、幂等、审计、锁、指标、追踪、缓存 |
| SpringBootAI AI 模块 | ✅ 可用 | 对齐 Spring AI 2.0：ChatClient/ChatModel/EmbeddingModel/Advisor/Tools，OpenAI/Ollama/DeepSeek/Moonshot 适配，Function Calling 闭环、RAG、会话记忆、Redis 向量存储、熔断重试、真流式 async、Prometheus 观测、类型化配置绑定 |
| LangChain 模块 | ✅ 可用 | 封装 langchain classic 全套：Chains/Agents(6 种)/Memory/Retrievers/VectorStores/Parsers/Loaders + 30+ Partner 提供商懒加载，双向适配器复用 spring.ai 模型 Bean，`configure_langchain()` 自动装配 14+ Bean |

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

LangChain 模块复用 AI 模块的依赖，额外按需安装 partner 包（30+ 提供商懒加载，未安装的自动跳过）：

```bash
pip install langchain-anthropic      # Anthropic Claude
pip install langchain-deepseek       # DeepSeek
pip install langchain-ollama         # Ollama 本地模型
pip install faiss-cpu                # FAISS 向量库
pip install langchain-chroma         # Chroma 向量库
# 完整 partner 列表见 spring.langchain.partners.PARTNER_REGISTRY
```

`requirements.txt` 是仓库的完整开发环境，包含多种数据库和中间件客户端。应用接入时优先按需安装 extras。

### 3.4 验证安装

```bash
python -c "import spring; print(spring.__version__)"
python -c "from spring.orm.pymybatis import __version__; print(__version__)"
```

### 3.5 最小应用

仓库中的 `example`、`example1`、`example5` 只用于源码参考和回归验证，不会打包进 `springbootAI`。安装后请按下面结构创建自己的应用包，不要从 site-packages 导入这些示例。**每个被扫描目录都必须包含 `__init__.py`，并从项目根目录启动。**

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

`SPRING_PROFILES_ACTIVE` 用于 `@Profile` 组件筛选、生产安全校验，以及**自动加载并深度合并** `application-{profile}.yml`（v1.8.5 起实现，对齐 Spring Boot 语义）。Profile 文件与主 `application.yml` 同目录，加载顺序为：主配置 → profile 配置深度合并（profile 覆盖主配置的同名键，未涉及的键保留），合并后再解析 `${ENV:default}` 占位符和环境变量覆盖。例如 `SPRING_PROFILES_ACTIVE=prod` 会自动合并 `application-prod.yml`，无需部署流程生成最终 `application.yml`。

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
| `@GlobalTransactional` | 通过 Seata 管理全局事务 | 受管 Bean 方法调用 Seata manager；HTTP 模式为持久化补偿且要求幂等回调，强一致生产场景使用 `distributed`；不支持嵌套 |
| `@Valid` | 非空/嵌套对象基础检查 | 受管 Bean 方法会执行简化校验，不等同 Jakarta Bean Validation |
| `@Validated` | 分组校验 | 会执行简化检查，但 `groups` 当前未驱动真正的分组规则 |
| `@RabbitListener` | 注册 RabbitMQ 消费者 | 可直接装饰受管 Bean 方法；容器声明队列/交换机、注册回调，并在刷新后启动后台消费；支持同步和异步回调 |
| `RabbitTemplate` | 主动发送 RabbitMQ 消息 | 它是普通类，不是注解；显式实例化后调用 `send()` |

#### Cloud 注解（@EnableDiscoveryClient / @NacosValue / @RefreshScope / @EnableFeignClients / @FeignClient / @SentinelResource / @EnableGateway / @LoadBalanced / @GlobalTransactional）

> Cloud 注解的参数、示例与边界已分离至独立文档：[CLOUD_MODULE.md](doc/CLOUD_MODULE.md)（§一 注解参考）。

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

### 5.11 / 5.12 MyBatis 集成注解 与 DDL 自动建表注解

> `@MapperScan` / `@Mapper` / `@Select` / `@Insert` / `@Update` / `@Delete` / `@ResultMap` / `@Options` / `Param` / `@MapperTransactional`（5.11）与 `@entity` / `Index`（5.12）已分离至独立文档：[ORM_MODULE.md](doc/ORM_MODULE.md)（§一 注解参考）。

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

> 本节（与 MyBatis 一致性、数据库配置、Mapper 注解、Mapper 扫描、Session、XML Mapper、分页、SQL 安全、DDL 自动建表、XML 功能矩阵）已分离至独立文档：[ORM_MODULE.md](doc/ORM_MODULE.md)（§二 功能说明）。

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

当前缓存默认由 `BeanFactory` 提供本地内存实现，最多 1000 项、TTL 300 秒，不跨进程。`@Cacheable` 负责“先查缓存，未命中才执行方法”；`@CachePut` 负责执行方法后写入新值；`@CacheEvict` 负责删除一个键或清空一个命名空间；`@CacheConfig` 和 `@Caching` 用于统一命名空间或组合多个操作。`value` 是缓存命名空间；`key="user_id"` 取同名参数，`key="user_{user_id}"` 使用模板，其他字符串作为固定键；`condition="enabled"`、`condition="!skip_cache"` 或 callable 决定是否缓存。同步方法缓存普通返回值，异步方法会先 `await` 再缓存最终结果，不会缓存 coroutine。写操作后的业务缓存失效仍需由业务方法显式使用 `@CachePut`/`@CacheEvict`；生产多 worker 或多实例应接入共享 Redis，并自行验证一致性和故障降级。

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

配置 `rabbitmq.enabled: true` 并提供 host、port、username、password、virtual_host。开发环境也应在真实 Nacos、RabbitMQ、Redis 等环境执行集成、断线和重复投递测试。HTTP 事务模式会将协调元数据写入 `seata.store_path`，并在 worker 启动后周期恢复；它是补偿事务，不是 Seata AT，也不能单独满足支付、订单、库存的一致性要求。

---

## 12. SpringBootAI AI 与 LangChain 模块

### 12.1 AI 模块（对齐 Spring AI 2.0）

> 本节（新手入门、快速开始、配置、AI 注解、ChatClient 链式 API、Advisor、ETL、工具调用、自动装配、企业级能力、DeepSeek 全特性演示）已分离至独立文档：[AI_MODULE.md](doc/AI_MODULE.md)。安装：`pip install springbootAI[ai]`。

### 12.2 LangChain 模块（封装 langchain classic 全套能力）

> 把 LangChain classic 的 Chains / Agents / Memory / Retrievers / VectorStores / Parsers / Loaders 封装为 Spring 风格 `@Service` / `@Component` Bean，配合 30+ 第三方模型提供商（OpenAI / Anthropic / Ollama / DeepSeek / ZhipuAI / Tongyi …）开箱即用。
> 完整文档：[LANGCHAIN_MODULE.md](doc/LANGCHAIN_MODULE.md)。安装：`pip install springbootAI[ai]`。

**核心能力**：

- **双向适配器**：springbootAI `ChatModel`/`EmbeddingModel` ↔ langchain `BaseChatModel`/`Embeddings`，复用 `spring.ai` 装配的模型 Bean
- **30+ Partner 提供商**：按 `application.yml` 的 `spring.langchain.partners.<name>` 懒加载，未配置的不启动
- **6 种 Agent**：react / chat-zero-shot-react / openai-functions / openai-tools / structured-chat / self-ask-with-search
- **6 种 Chain**：LLMChain / ConversationChain / SequentialChain / RetrievalQA / 摘要 / LLMMath
- **4 种 Memory**：buffer / summary / buffer-window / token-buffer
- **7 种 VectorStore**：inmemory / faiss / chroma / pinecone / weaviate / pgvector / redis
- **6 种 Retriever + 5 种 OutputParser + 6 种 DocumentLoader + 6 种 Utility + 3 种 Callback**
- **一键 RAG**：`IndexService.create_from_texts()` + `query()` 三步完成知识库问答
- **自动装配**：`configure_langchain()` 一次注册 14+ 个 `lc*` Bean，支持 `@Autowired` 注入

**最小示例**（无需 API Key，降级 FakeChatModel）：

```python
from spring.context.registry import BeanRegistry
from spring.ai.autoconfig import configure_ai
from spring.langchain.autoconfig import configure_langchain

registry = BeanRegistry()
configure_ai(registry=registry)                  # 1. 装配 spring.ai（降级 Fake）
beans = configure_langchain(registry=registry)   # 2. 装配 spring.langchain

chain = beans["lcChainService"]                  # 拿到 ChainService Bean
print(chain.run_llm_chain("回答: {q}", q="你好"))
```

**配置**（`application.yml`）：

```yaml
spring:
  langchain:
    enabled: ${LC_ENABLED:true}
    default-llm: ${LC_DEFAULT_LLM:auto}     # auto=复用 spring.ai 的 aiChatModel
    agents:
      default-type: ${LC_AGENT_TYPE:react}  # react|openai-tools|structured-chat|...
      max-iterations: ${LC_AGENT_MAX_ITER:10}
    vector-store:
      type: ${LC_VECTOR_STORE:faiss}        # inmemory|faiss|chroma|redis|...
    memory:
      type: ${LC_MEMORY:buffer}             # buffer|summary|buffer-window|token-buffer
    partners:                               # 按 name 启用 partner，未配置的不加载
      openai:
        api-key: ${OPENAI_API_KEY:}
        model: ${OPENAI_CHAT_MODEL:gpt-4o-mini}
```

**示例应用**：[example_langchain/](example_langchain/) 提供完整的 `@SpringBootApplication` + `@RestController` + `@Service` 分层演示，暴露 12 个 HTTP 接口（问答 / 翻译 / 摘要 / Agent / RAG 入库检索 / Memory / Math / Parser / Embed / Partner 列表 / 能力清单）。

**与 spring.ai 的关系**：两个模块互补——`spring.ai` 提供 `ChatClient`/`Advisor`/`Tools` 抽象（Spring AI 2.0 风格），`spring.langchain` 提供 `Chain`/`Agent`/`Memory` 抽象（LangChain 生态）。底层复用同一个 `aiChatModel` Bean，不会重复计费。

## 13. Java 迁移指南

本文说明如何把现有的 Java Spring Boot、Spring Cloud Alibaba 和 MyBatis 分层代码迁移到 SpringBootAI。目标是保留清晰的 Controller / Service / Mapper 边界、配置习惯和常用注解意图，而不是让 Python 运行 Java 代码。

### 13.1 迁移原则

1. 先迁移接口契约和测试，再迁移框架注解。
2. Python 使用类型标注、Pydantic 和显式依赖，比模拟 Java 反射更可靠。
3. 只有由 `ApplicationContext` 创建的 Bean 才会获得事务、缓存、重试等 AOP 行为；手工 `ClassName()` 创建的对象不受容器管理。
4. Java 中的 XML SQL 可以大部分保留，但数据库函数、分页、类型名和连接配置需要按目标 Python 驱动验证。
5. 不把"有同名注解"理解为"与 Java 完全等价"。

### 13.2 项目结构对照

| Java Spring Boot | SpringBootAI |
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

| Java 注解 | SpringBootAI 写法 | 行为和边界 |
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

| Java Spring MVC | SpringBootAI |
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

| Java 能力 | SpringBootAI | 注意事项 |
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

| Java 注解/组件 | SpringBootAI 对应 | 当前状态 |
|---|---|---|
| `@EnableDiscoveryClient` + Nacos | `@EnableDiscoveryClient` + `discovery` 配置 | 注解元数据与 Nacos 客户端配置可用；需部署 Nacos 并做注册/发现集成测试 |
| `@NacosValue` / `@RefreshScope` | 同名注解 | 元数据可用；`@RefreshScope` 已接入容器刷新机制，复杂配置刷新和 Java proxy 语义不等价 |
| `@EnableFeignClients` / `@FeignClient` | 同名注解 + `spring.cloud.feign` | 主要用于客户端元数据和 HTTP 调用；不兼容 Java interface proxy。Feign 调用自动传播 XID 和 trace 头 |
| `@LoadBalanced` | 同名注解 | 使用 Python 负载均衡实现；不要复用 `RestTemplate` 用法 |
| Sentinel `@SentinelResource` | 同名注解 | 已内嵌限流熔断引擎，无需 Dashboard；如需更强大治理能力可对接外部 Sentinel Dashboard |
| Spring Cloud Gateway | `@EnableGateway` + `GatewayRouter` | 内嵌轻量 ASGI/WSGI 网关；复杂网关需求可使用 Kong/APISIX 等专业网关 |
| Seata `@GlobalTransactional` | 同名注解 | `http` 模式是持久化补偿协调器，依赖幂等分支回调；企业强一致场景必须配置真实 Seata Server 与兼容 SDK |

**Cloud 高级功能迁移对照**：

| Java Spring Cloud | SpringBootAI 写法 | 说明 |
|---|---|---|
| Sentinel Dashboard + `@SentinelResource` | `@SentinelResource` | 内嵌引擎，无需 Dashboard；支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流 |
| SkyWalking Agent + OAP Server | `@Trace` + 内嵌 Tracer | 原生 OpenTelemetry(W3C traceparent)，无需 OAP Server；自动注入 HTTP/Feign 追踪头 |
| Seata Server + `@GlobalTransactional` | `@GlobalTransactional` | `distributed` 模式对接 Seata Server；`http` 仅用于补偿流程和故障演练，不提供 AT 语义 |
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

SpringBootAI：

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
7. 验证 Cloud 功能：`@SentinelResource` 限流熔断、`@Trace` 追踪、`@GlobalTransactional` 补偿流程、`GatewayRouter` 网关、`@entity` + `ddl-auto` 自动建表。HTTP 补偿模式必须验证重复回调、进程重启和部分失败；强一致事务需部署真实 Seata Server 并执行集成测试。

---

## 14. 生产部署

### 14.1 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| Redis | 6.0+ | 用于分布式锁、限流、缓存 |
| MySQL | 5.7+ / 8.0+ | 用于业务数据存储 |
| Nacos | 2.0+ | 服务注册发现（可选） |

> **v1.5.0+ 新特性**：内嵌 Sentinel 限流熔断、OpenTelemetry 分布式追踪和轻量异步 API Gateway。HTTP 补偿模式不提供 Seata AT 语义；生产分布式事务必须部署真实 Seata Server 并提供兼容适配器。

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

### 14.3 Cloud 功能

> 已分离至独立文档：[CLOUD_MODULE.md](doc/CLOUD_MODULE.md)（§二 功能说明）。

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
| `SYNC_MAX_WORKERS` | 每个 worker 的同步处理线程上限 | 40 |
| `SYNC_MAX_QUEUE` | 每个 worker 可等待的同步请求数 | 100 |
| `SYNC_QUEUE_TIMEOUT` | 同步队列等待秒数，超时返回 503 | 0.1 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis 地址/端口/密码 | localhost/6379/空 |
| `JWT_SECRET_KEY` | JWT 密钥 | spring-python-secret-key-change-in-production |
| `DB_URL` | 数据库连接 URL | sqlite:///./test.db |
| `DB_DDL_AUTO` | DDL 自动建表模式（none/validate/update/create/create-drop） | none |
| `DB_ENTITY_PACKAGES` | 实体类包路径，逗号分隔 | 空 |
| `DISCOVERY_ENABLED` | 是否启用 Nacos 服务发现 | false |
| `NACOS_SERVER` | Nacos 地址 | localhost:8848 |
| `NACOS_USERNAME` / `NACOS_PASSWORD` | Nacos 客户端账号/密码 | 空 |
| `SEATA_HTTP_STORE_PATH` | HTTP 补偿协调 SQLite 文件路径（同主机多 worker 共享） | `./data/seata-http.sqlite3` |
| `SEATA_HTTP_RECOVER_ON_STARTUP` | 初始化时扫描并恢复未完成补偿 | true |
| `SEATA_HTTP_RECOVERY_GRACE_MS` | 接管其他 worker 的 COMMITTING/ROLLING_BACK 前等待时间 | 30000 |
| `SEATA_HTTP_RECOVERY_INTERVAL_S` | worker 内周期恢复间隔，0 表示关闭 | 30 |
| `SPRING_DISABLE_DOCKER_IP_DETECT` | 设为 1 禁用 Docker 容器 IP 自动检测 | 0 |

> HTTP 补偿模式使用 `SEATA_HTTP_*` 配置，仍不提供 Seata AT；生产强一致事务必须配置 `SEATA_MODE=distributed`、真实 Server 和兼容 SDK。

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

> Sentinel、OpenTelemetry 追踪和 API Gateway 可内嵌运行；HTTP 补偿协调器的未完成事务会纳入恢复日志。它不属于强一致外部事务协调器，不能替代 Seata Server。

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

`example`、`example1`、`example5`、`example_langchain` 是仓库级示例，不属于 `springbootAI` 安装包，不会被打包。实际项目应创建自己的应用包。`example_langchain` 演示了 LangChain 模块的完整分层用法（`@SpringBootApplication` + `@RestController` + `@Service` + `@Configuration`），可作为 AI 应用脚手架参考。

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

| Java Spring Boot | SpringBootAI |
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

> 详细的测试环境、套件覆盖、功能矩阵、企业就绪评估与 example_all 集成测试结果，见 [TEST_REPORT.md](doc/TEST_REPORT.md)。

### 16.2 重点覆盖

- 独立和内嵌 ORM 源码一致。
- 连接池共享、扩容、归还和未提交回滚。
- 普通事务与嵌套 rollback-only。
- Spring Mapper 在事务中复用 Session。
- JWT access/refresh、生产密钥校验。
- 配置占位符类型和 CORS/HTTP 错误状态。
- AI 模块 87 用例（LangChain 切片委托 + 向量库适配器），全量 707 用例 0 失败。
- LangChain 模块 75 用例（适配器/配置/自动装配/Partner/Prompt/Chain/Agent 6 种类型/Memory/Parser/VectorStore/Retriever/Index/Tool/Utility/Callback/安全求值器/端到端 RAG），覆盖双向桥接、bind_tools 工具绑定、沙箱逃逸防护。

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

### 17.7 LangChain 模块排错

**`@Autowired` 注入 `lcChainService` 报 `Cannot resolve parameter`：** 确认 `@Configuration` 类的 `__init__` 中调用了 `configure_ai()` + `configure_langchain()`，且该 `@Configuration` 类在 `@Service` 之前被实例化（SpringBootAI 默认保证这个顺序）。

**`Partner 'xxx' 注册失败（跳过）`：** 该 partner 的依赖包未安装。按告警提示 `pip install langchain-<partner>`，或在 `application.yml` 的 `spring.langchain.partners` 下移除该 partner。未安装的 partner 不会阻塞启动。

**`bind_tools` / `openai-tools` / `structured-chat` Agent 无法调用工具：** 确认使用的是真实 OpenAI 模型（非 FakeChatModel）。FakeChatModel 不返回 `tool_calls`，只能走 `react` 文本解析路径。

**RAG 报 `嵌入模型未装配`：** `configure_ai` 默认会装 `aiEmbeddingModel`，但需要 `OPENAI_API_KEY` 或 `OLLAMA_BASE_URL`。无 Key 时设 `AI_ALLOW_FAKE=true` 会降级 `FakeEmbeddingModel(dim=16)`，RAG 可演示但不真实。

**`run_conversation` 不记忆前文：** 便捷方法每次不传 memory 时会创建新 buffer。要多轮记忆需自己持有 memory 实例：`mem = MemoryFactory.create("buffer"); svc.run_conversation("...", memory=mem)`。

### 17.8 上线前清单

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

## 18. 性能与容量验证

仓库提供 Docker 化的 SpringBootAI 基准服务和 k6 `smoke`、`baseline`、`stress`、`soak` 四档压测。快速验证：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke
```

Bean Validation、缓存增强、CSV、JPA 乐观锁和 Conditional 均有独立 workload；条件装配另有重复 BeanDefinition 注册基准。完整参数、业务接口压测和真实 Seata 契约测试说明见 [`tests_performance/README.md`](tests_performance/README.md)。

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

# AI 模块（spring.ai.*，详见 AI_MODULE.md）
export AI_PROVIDER=openai              # openai|ollama|deepseek|moonshot|zhipu
export AI_ALLOW_FAKE=true              # 无 API Key 时降级 FakeChatModel（开发/测试）
export OPENAI_API_KEY=sk-xxx
export OPENAI_CHAT_MODEL=gpt-4o-mini
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_CHAT_MODEL=llama3

# LangChain 模块（spring.langchain.*，详见 LANGCHAIN_MODULE.md）
export LC_ENABLED=true
export LC_DEFAULT_LLM=auto             # auto=复用 spring.ai 的 aiChatModel；或 partner 名
export LC_AGENT_TYPE=react             # react|openai-tools|structured-chat|...
export LC_AGENT_MAX_ITER=10
export LC_VECTOR_STORE=faiss           # inmemory|faiss|chroma|redis|pinecone|weaviate|pgvector
export LC_RETRIEVER=similarity         # similarity|multi-query|contextual-compression|...
export LC_RETRIEVER_K=4
export LC_MEMORY=buffer                # buffer|summary|buffer-window|token-buffer
export LC_MEMORY_MAX=20
```

> Sentinel 限流熔断、OpenTelemetry 分布式追踪和 API Gateway 可内嵌实现；HTTP 补偿事务通过 `SEATA_HTTP_*` 配置。AI 模块完整环境变量见 [AI_MODULE.md](doc/AI_MODULE.md)，LangChain 模块完整环境变量见 [LANGCHAIN_MODULE.md](doc/LANGCHAIN_MODULE.md)。

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
