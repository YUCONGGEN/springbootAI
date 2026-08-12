# SpringBootAI

[![PyPI](https://img.shields.io/pypi/v/springbootAI)](https://pypi.org/project/springbootAI/)
[![Python](https://img.shields.io/pypi/pyversions/springbootAI)](https://pypi.org/project/springbootAI/)
[![CI](https://github.com/YUCONGGEN/springbootAI/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/YUCONGGEN/springbootAI/actions/workflows/ci.yml)
[![Security](https://github.com/YUCONGGEN/springbootAI/actions/workflows/security.yml/badge.svg?branch=master)](https://github.com/YUCONGGEN/springbootAI/actions/workflows/security.yml)
[![License](https://img.shields.io/pypi/l/springbootAI)](https://github.com/YUCONGGEN/springbootAI/blob/master/LICENSE)

SpringBootAI 是一个采用 Spring 风格注解和分层结构的 Python 应用框架。你使用 Python 编写 `@RestController`、`@Service`、`@Mapper` 和 `@Autowired`，框架负责组件扫描、依赖注入、Web 路由、事务切面及生命周期；Web 运行时建立在 FastAPI/Starlette/Uvicorn 之上。

它不是 Java Spring Boot 的 Python 绑定，也不是 Spring 官方项目。它适合熟悉 Controller/Service/Mapper 分层的团队，用统一写法开发 Web API、内部管理系统、数据服务和 AI 应用。

| 能力 | 解决什么问题 | 底层复用 |
|---|---|---|
| Web 与 IoC | 路由、参数绑定、组件扫描、依赖注入 | FastAPI / Starlette / Uvicorn |
| 数据与中间件 | PyMyBatis、事务、缓存、RabbitMQ、Nacos、Feign | DBUtils / Redis / pika / Nacos SDK / requests |
| AI 与编排 | 模型调用、Tools、RAG、Chain、状态图、MCP client/server | LangChain / LangGraph / 官方 MCP SDK |
| 生产治理 | 健康检查、Prometheus、限流熔断、追踪、Swagger | prometheus-client / OpenTelemetry / OpenAPI |

当前版本是 `2.2.0`；支持 Python 3.10、3.11 和 3.12，许可证为 MIT。项目仍标记为 Beta。用于公网高并发、合规敏感或支付/订单/库存等核心系统前，必须完成目标数据库、流量模型、故障恢复和安全基线验证。内嵌 Gateway 适合内部路由，不替代公网 Nginx/Kong/WAF；Seata `distributed` 当前验证的是官方 TC + TCC 回调，不会为 Python 数据库操作自动生成 AT `undo_log`。

[新手指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md) | [全部文档](https://github.com/YUCONGGEN/springbootAI/tree/master/doc) | [变更日志](https://github.com/YUCONGGEN/springbootAI/blob/master/CHANGELOG.md) | [安全报告](https://github.com/YUCONGGEN/springbootAI/blob/master/SECURITY.md) | [发布检查](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/RELEASE_CHECKLIST.md)

## 10 分钟跑通第一个接口

以下示例不需要数据库、Redis 或大模型 API Key。先创建项目和虚拟环境：

```powershell
mkdir my-first-app
cd my-first-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install springbootAI

mkdir demo
mkdir demo\controller
New-Item demo\__init__.py -ItemType File
New-Item demo\controller\__init__.py -ItemType File
```

Linux/macOS 激活命令是 `source .venv/bin/activate`，其余 Python 命令相同。

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
from spring.web.swagger import Operation, Tag


@Tag(name="入门接口", description="确认应用已经正常运行")
@RequestMapping("/api")
@RestController
class HelloController:
    @Operation(summary="打招呼")
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
```

创建 `demo/application.yml`。这里显式关闭暂时用不到的外部资源，避免新手第一次启动就连接数据库：

```yaml
server:
  host: 127.0.0.1
  port: 8080

database:
  enabled: false

redis:
  enabled: false
```

在 `demo` 目录的上一层启动：

```powershell
python -m demo.Application
```

另开终端验证：

```powershell
curl http://127.0.0.1:8080/api/hello/Alice
```

返回数据中应包含 `"message":"Hello, Alice"`。浏览器访问 `http://127.0.0.1:8080/docs` 可以看到 Swagger 页面。遇到目录、虚拟环境或启动错误时，按[新手入门指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md)逐步排查。

---

## 模块文档导航

第一次使用请先读 [新手入门指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md)。它从安装开始，带你创建第一个接口，并解释 Controller、Service、Bean、依赖注入和配置文件是什么。各模块文档统一按 **① 这解决什么问题？→ ② 怎么用？（贴代码）→ ③ 怎么验证？** 三步走模式组织，按需查阅即可。

| 模块 | 文档 | 安装方式 | 一句话说明 |
|------|------|----------|-----------|
| ✅ 新手入门 | [BEGINNER_GUIDE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md) | 随核心包 | 从零安装、创建项目、运行接口、打开 Swagger |
| ✅ 常用注解模块 | [ANNOTATION_MODULES.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ANNOTATION_MODULES.md) | 随核心包 | Bean Validation / 条件装配 / 缓存增强 / CSV / `@Version` / `@Transient` |
| ✅ AOP / 后置鉴权 / 重试恢复 | [AOP_SECURITY_RETRY.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AOP_SECURITY_RETRY.md) | 随核心包 | `@Aspect` 通知 / `@PostAuthorize` / `@Recover`，含小白示例与常见错误 |
| 📦 AI（对接大模型） | [AI_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AI_MODULE.md) | `pip install springbootAI[ai]` | ChatClient / Advisor / Tools / RAG / Function Calling / 多厂商适配 |
| 📦 LangChain | [LANGCHAIN_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/LANGCHAIN_MODULE.md) | `pip install springbootAI[langchain]` | Chains / Agents / Memory / Retrievers / VectorStores / 30+ 提供商 |
| 📦 LangGraph | [LANGGRAPH_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/LANGGRAPH_MODULE.md) | `pip install springbootAI[langgraph]` | 状态图 / 条件路由 / 人工中断 / 注解式工作流 |
| 📦 MCP | [MCP_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/MCP_MODULE.md) | `pip install springbootAI[mcp]` | MCP Client / Server / Tool / Resource / Prompt / 注解调用 |
| ✅ 内嵌 PyMyBatis ORM | [ORM_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ORM_MODULE.md) | 随核心包 | Mapper 注解 / XML Mapper / 分页 / SQL 安全 / DDL 自动建表 |
| ✅ Cloud 微服务 | [CLOUD_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/CLOUD_MODULE.md) | 随核心包 | 服务注册发现 / 配置刷新 / Feign / Sentinel / Gateway / 分布式事务 |
| 📦 Excel 读写 | [EXCEL_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/EXCEL_MODULE.md) | `pip install springbootAI[excel]` | `@ExcelProperty` / `@ExcelIgnore` 注解驱动读写 |
| 📦 CSV 读写 | [CSV_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/CSV_MODULE.md) | `pip install springbootAI[csv]` | `@CsvProperty` / `@CsvIgnore` 注解驱动读写 |
| ✅ Swagger 文档 | [SWAGGER_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/SWAGGER_MODULE.md) | 随核心包 | `@Tag` / `@Operation` 注解驱动 API 文档 |
| ✅ 八大模块 | [EIGHT_MODULES.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/EIGHT_MODULES.md) | 随核心包 | 分页 / Actuator / 多数据源 / i18n / WebSocket 等 |
| ✅ 安全 | [SECURITY.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/SECURITY.md) | 随核心包 | JWT 生成校验 / 密码加密 / SQL 注入防护 / 访问控制 |
| ✅ BeanUtils | [BEAN_UTILS.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEAN_UTILS.md) | 随核心包 | `copy_properties` / `clone` 属性复制工具 |
| — AI 与 LangChain 测试 | [AI_LANGCHAIN_TEST_GUIDE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AI_LANGCHAIN_TEST_GUIDE.md) | — | AI 与 LangChain 测试说明 |
| — 测试报告 | [TEST_REPORT.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/TEST_REPORT.md) | — | 全量测试用例与覆盖范围 |

> 图例：✅ = 随核心包自带，不需要额外安装 | 📦 = 需要单独安装 extras | — = 参考文档，不是功能模块

所有模块文档统一存放于 [GitHub `doc/` 目录](https://github.com/YUCONGGEN/springbootAI/tree/master/doc)。

### 🎯 新手推荐阅读顺序

1. 先按 [新手入门指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md) 跑通 `/api/hello/{name}`。
2. 阅读本页第 4、6、7 章，理解配置、依赖注入和 Controller。
3. 做数据库 CRUD 时阅读 [ORM_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ORM_MODULE.md)。
4. 需要输入校验、缓存或条件开关时阅读 [ANNOTATION_MODULES.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ANNOTATION_MODULES.md)。
5. 最后再按业务需要选择安全、Cloud、AI、LangChain、Excel、WebSocket 等文档。

---

## 目录

1. [框架概述与定位](#1-框架概述与定位)
2. [能力状态](#2-能力状态)
3. [安装与快速开始](#3-安装与快速开始)
4. [配置系统（5 分钟看懂）](#4-配置系统5-分钟看懂)
5. [注解参考](#5-注解参考)
6. [IoC 与依赖注入（厨房比喻版）](#6-ioc-与依赖注入厨房比喻版)
7. [Web 控制器](#7-web-控制器)
8. [内嵌 PyMyBatis ORM 与 DDL](#8-内嵌-pymybatis-orm-与-ddl)
9. [事务](#9-事务)
10. [安全与权限](#10-安全与权限)
11. [缓存、任务与高级 AOP](#11-缓存任务与高级-aop)
12. [AI 与 LangChain 模块](#12-ai-与-langchain-模块)
13. [Java 开发者看这里](#13-java-开发者看这里)
14. [生产部署](#14-生产部署)
15. [项目结构](#15-项目结构)
16. [测试](#16-测试)
17. [常见问题与排错](#17-常见问题与排错)
18. [性能与容量验证](#18-性能与容量验证)

---

## 1. 框架概述与定位

### 1.1 这是什么？

SpringBootAI 是一个 **Python Web 框架**。它把 Java Spring Boot 的"注解 + Controller/Service/Mapper 分层"思路搬到了 Python 世界——你写的是 Python 代码，用的是 `@Service`、`@RestController` 这些看起来像 Spring Boot 的注解，但底层真正跑起来的是 FastAPI 和 Uvicorn。

### 1.2 三句话版本

1. **写法像 Spring Boot**：用 `@RestController`、`@Service`、`@Mapper` 组织代码，Java 开发者一眼就懂。
2. **运行在 Python**：底层是 FastAPI + Uvicorn，不依赖 Java、JAR 包或 Maven。
3. **功能开箱即用**：数据库、缓存、安全、文档、AI 等能力已经打包好，装完就能用。

### 1.3 版本

| 组件 | 当前版本 |
|------|----------|
| `spring` 框架 API | 2.2.0 |
| `spring.orm.pymybatis` | 2.2.0 |
| `spring.ai` AI 模块 | 2.2.0 |
| `spring.langchain` LangChain 模块 | 2.2.0 |
| Python | 3.10+ |

### 1.4 适合什么场景

- 内部管理接口、轻量业务服务、教学和原型验证。
- 希望用 Controller/Service/Mapper 分层方式写 Python 的团队。
- SQLite 本地工具，或经过目标数据库集成测试的服务。
- 经过容量和故障验证的微服务组件组合；外部入口和核心事务仍使用专业基础设施。

### 1.5 能力边界（使用前必读）

- 自动化套件包含真实 MySQL 8 集成测试；PostgreSQL、Oracle 及业务实际版本仍需单独验证。
- `@Transactional` 支持七种 Spring 传播模式；`REQUIRES_NEW` 和 `NOT_SUPPORTED` 需要连接池有额外可用连接。
- Profile 会筛选 `@Profile` Bean，并深度合并同目录的 `application-{profile}.yml`。
- Nacos、RabbitMQ、Prometheus 依赖外部服务；Sentinel 限流熔断和 OpenTelemetry 追踪可内嵌运行。
- HTTP 事务模式是持久化补偿协调器，不提供 Seata AT 一致性；`distributed` 模式当前提供真实 Seata TC + TCC 回调，不会自动代理 Python 数据源或生成 `undo_log`。
- 限流、分布式锁、幂等和缓存语义依赖 Redis 等后端；核心业务必须选择 fail-closed，不能依赖进程内降级继续提供分布式语义。

### 1.6 注解使用总览

SpringBootAI 注解会先把元数据放到 `__spring_annotations__`。之后是否生效，取决于有没有对应的扫描器或切面：

| 状态 | 含义 |
|------|------|
| 容器执行 | `ApplicationContext`、`BeanFactory` 或 Web 上下文会读取并执行 |
| 受管 Bean 执行 | 只有被组件扫描并由容器创建的实例方法才会被 AOP 包装；自己 `ClassName()` 创建的对象不生效 |
| 直接执行 | 装饰器本身返回包装函数，不依赖 IoC 容器 |
| 仅元数据 | 当前有注解类，但主运行链路没有消费者，写上不会得到注解名字所暗示的功能 |

> **⚠️ 这是最容易混淆的地方**：同名的注解（如 `@Transactional`），在 Java Spring 和 SpringBootAI 中的具体行为可能不同。不要因为名字一样就假设效果也一样。

---

## 2. 能力状态

| 模块 | 状态 | 一句话说明 |
|------|------|-----------|
| IoC 容器 | ✅ 可用 | 组件扫描、构造器/字段注入、Bean、延迟初始化、生命周期回调、Profile 过滤 |
| Web MVC | ✅ 可用 | 基于 FastAPI 的 GET/POST/PUT/PATCH/DELETE 路由、参数绑定、异常处理、CORS 和静态文件 |
| 配置 | ✅ 可用 | YAML、`${ENV:default}`、固定环境变量覆盖、标量类型保留 |
| 应用事件 | ✅ 可用 | `ApplicationEvent`、`@EventListener`、同步有序发布和异步监听 |
| 内嵌 ORM + DDL Auto | ✅ 可用 | PyMyBatis + JPA ddl-auto 自动建表(create/update/validate)，支持 XML/注解 SQL、事务、缓存 |
| 本地事务 | ✅ 可用 | `@Transactional` 支持七种 Spring 传播模式 |
| JWT 与方法安全 | ✅ 可用 | access/refresh token、`@Authenticate`、前置/后置授权、401/403 映射 |
| 重试/异步 | ✅ 可用 | 受管 Bean 的退避重试、恢复方法和 Future/Task 异步调度 |
| Redis/缓存 | ✅ 可用 | 分布式锁、KV/Hash/List/Set/Counter，需要 Redis 服务 |
| RabbitMQ | ✅ 可用 | `@RabbitListener` 自动注册并后台消费，`RabbitTemplate` 发送 |
| Nacos 服务发现 | ✅ 可用 | 服务注册/发现/订阅 |
| Sentinel 限流熔断 | ✅ 可用 | 内嵌引擎，QPS 限流、异常比例熔断、热点参数限流，无需 Dashboard |
| 分布式追踪 | ✅ 可用 | 原生 OpenTelemetry(W3C traceparent)，自动 HTTP/Feign 注入 |
| Seata 分布式事务 | ⚠️ 有边界 | `distributed` 对接真实 Seata TC 并执行 TCC 回调；`http` 仅提供持久化补偿；均不等同 Python AT 数据源代理 |
| API Gateway | ✅ 可用 | 轻量 ASGI/WSGI 网关，路由转发、路径重写、过滤器链、负载均衡 |
| Prometheus 监控 | ✅ 可用 | Counter/Gauge/Histogram 指标暴露 |
| Feign 声明式 HTTP | ✅ 可用 | 声明式接口、Fallback 降级、自动传播 XID 和 trace 头 |
| 高级 AOP | ✅ 可用 | 声明式切面、限流、熔断、幂等、审计、锁、指标、追踪、缓存 |
| AI 模块 | ✅ 可用 | ChatClient/ChatModel/EmbeddingModel/Advisor/Tools，OpenAI/Ollama/DeepSeek/Moonshot 适配 |
| LangChain 模块 | ✅ 可用 | Chains/Agents(6 种)/Memory/Retrievers/VectorStores + 30+ 提供商，双向适配器 |
| LangGraph 模块 | ✅ 可选 | 官方 LangGraph 状态图、条件路由、人工中断、持久化 checkpointer 和注解工作流 |
| MCP 模块 | ✅ 可选 | 官方 MCP SDK 的 client/server、Tool/Resource/Prompt 与注解调用 |

---

## 3. 安装与快速开始

### 3.1 环境准备

需要 Python 3.10、3.11 或 3.12。先进入你自己的空项目目录，再创建虚拟环境：

```powershell
mkdir my-springbootai-app
cd my-springbootai-app
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

普通使用者直接从 PyPI 安装：

```bash
python -m pip install --upgrade pip
python -m pip install springbootAI
```

只有准备修改框架源码的贡献者，才需要先 `git clone`，进入仓库后执行 `python -m pip install -e .`。

核心依赖包含 FastAPI、Uvicorn、PyYAML、python-dotenv、DBUtils、PyJWT、cryptography、bcrypt 和 Pydantic。**核心安装已包含内嵌 `spring.orm.pymybatis`，使用 Mapper 模式不需要再安装独立 `pymybatis`。**

### 3.3 可选 extras

从 PyPI 按需安装：

```bash
python -m pip install "springbootAI[mysql]"
python -m pip install "springbootAI[redis,rabbitmq,nacos]"
python -m pip install "springbootAI[ai]"
python -m pip install "springbootAI[langchain]"
python -m pip install "springbootAI[langgraph]"
python -m pip install "springbootAI[mcp]"
```

在源码仓库开发时，对应命令是：

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
python -m pip install -e ".[ai]"                # Spring AI + LangChain 基础适配
python -m pip install -e ".[langgraph]"         # LangGraph + 官方 SQLite checkpointer
python -m pip install -e ".[mcp]"               # 官方 MCP client/server SDK
```

AI 模块为可选依赖：

```bash
pip install -r requirements-ai.txt   # langchain-openai/langchain-community/numpy
```

LangChain 模块复用 AI 模块的依赖，额外按需安装 partner 包（30+ 提供商懒加载，未安装的自动跳过）：

```bash
pip install langchain-anthropic      # Anthropic Claude
pip install langchain-deepseek       # DeepSeek
pip install langchain-ollama         # Ollama 本地模型
pip install faiss-cpu                # FAISS 向量库
pip install langchain-chroma         # Chroma 向量库
```

### 3.4 验证安装

```bash
python -c "import spring; print(spring.__version__)"
python -c "from spring.orm.pymybatis import __version__; print(__version__)"
```

### 3.5 最小应用

仓库中的 `example`、`example1`、`example5` 只用于源码参考和回归验证，不会打包进 `springbootAI`。安装后请按下面结构创建自己的应用包。**每个被扫描目录都必须包含 `__init__.py`，并从项目根目录启动。**

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

## 4. 配置系统（5 分钟看懂）

> **🔑 核心概念**：配置文件（`application.yml`）就像餐厅的"运营手册"——写着餐厅地址（`host`）、门牌号（`port`）、要不要开外卖（`redis.enabled`）。换地方开店只改手册，不用重新装修。这一节 5 分钟帮你看懂配置的核心用法。

### 4.1 配置放哪里

`ApplicationContext` 按以下顺序找配置文件：

1. 启动类文件所在目录的 `application.yml`。
2. 启动类目录下的 `config/application.yml`。
3. 两处都不存在时使用代码默认值和环境变量。

两处都存在时第一项优先，不会合并。

### 4.2 环境变量占位符

```yaml
server:
  port: ${SERVER_PORT:8080}
database:
  enabled: ${DB_ENABLED:false}
  password: ${DB_PASSWORD}
```

- `${NAME}`：环境变量必填，未设置时报错。
- `${NAME:default}`：未设置时用冒号后的默认值。
- 占位符占满整个值时，YAML 会把 `8080`、`false`、`null` 保留为 int、bool、None（标量类型不变）。
- 占位符嵌入普通字符串时结果是字符串。

### 4.3 固定覆盖变量（常用）

除了 YAML 里的 `${...}` 占位符，加载器还会直接读取以下环境变量：

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

`SPRING_PROFILES_ACTIVE` 用于 `@Profile` 组件筛选、生产安全校验，以及**自动加载并深度合并** `application-{profile}.yml`（v1.8.5 起实现）。Profile 文件与主 `application.yml` 同目录，加载顺序：主配置 → profile 配置深度合并（profile 覆盖主配置的同名键），合并后再解析 `${ENV:default}` 占位符。例如 `SPRING_PROFILES_ACTIVE=prod` 会自动合并 `application-prod.yml`。

### 4.4 Docker 容器 IP 自动检测（开发环境）

在开发环境中，当 `database.host` 设为 `127.0.0.1` 或 `localhost` 时，框架会自动通过 `docker ps` 和 `docker inspect` 查找映射了目标端口的容器内部 IP 进行连接。

- 支持通过端口映射精确匹配（如 `0.0.0.0:3306->3306/tcp`）
- 支持 MySQL/MariaDB/PostgreSQL 数据库镜像兜底匹配
- 设置 `SPRING_DISABLE_DOCKER_IP_DETECT=1` 可禁用（生产环境推荐）

### 4.5 在代码里读配置

```python
from spring.config import ConfigLoader

loader = ConfigLoader("./myapp/application.yml")
port = loader.get("server.port", 8080)
database = loader.get_prefix_config("database")
snapshot = loader.get_config()
```

返回的配置是深拷贝，你改了不会影响原始配置。

### 4.6 Profile 的真实行为

```python
from spring.annotations import Profile, Service


@Profile("dev")
@Service
class DevelopmentService:
    pass
```

Profile 用于 Bean 过滤和生产安全校验。多环境配置可使用以下方式之一：

1. 在部署流程中生成最终 `application.yml`。
2. 大量使用环境变量占位符。
3. 显式创建 `ConfigLoader(config_path=...)` 和 `ApplicationContext`。

### 4.7 生产配置校验

当 Profile 是 `prod` 或 `production` 时：

- 默认 JWT 密钥、空密钥或少于 32 字符的密钥会导致启动失败。
- `startup.fail_fast` 默认视为开启。
- CORS 开启凭证时配置 `*` 来源会直接失败。

### 4.8 健康检查

| 地址 | 用途 |
|------|------|
| `/actuator/health` | 聚合组件健康状态；降级时返回 503 |
| `/actuator/health/liveness` | 进程存活检查（用于 K8s livenessProbe） |
| `/actuator/health/readiness` | 服务就绪检查（用于 K8s readinessProbe） |
| `/actuator/info` | 应用名称、当前 Profile、框架和 Python 版本 |

`database.enabled: false` 时数据库状态为 `DISABLED`，不会创建 `test.db`。

> **⚠️ 新手常见错误**：
> - ❌ 错误："我改了 YAML，重新请求接口怎么没生效？"
> - ✅ 正解：修改 YAML 后需要**重启应用**（`Ctrl+C` 停掉再重新运行）。YAML 配置是启动时一次性读取的。

---

## 5. 注解参考

> 说明：本节是框架最完整的注解参考。所有 AOP 类注解（事务、缓存、重试、异步、定时、高级 AOP、安全等）都要求**方法所在类带组件注解（`@Service`/`@Component`/`@Repository`/`@Controller` 等）并由容器取得实例**，自己 `ClassName()` 创建的对象不会生效。

### 5.1 启动与扫描

#### @SpringBootApplication

**含义**：应用启动类注解，组合了 `@Configuration`、`@ComponentScan` 的功能。

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| scan_base_packages | List[str] | None | 扫描的基础包路径 |

```python
from spring.annotations import SpringBootApplication

@SpringBootApplication(scan_base_packages=["com.example.service", "com.example.controller"])
class Application:
    pass
```

**注意事项**：每个应用只能有一个启动类；`scan_base_packages` 是可导入包名，不是文件路径。

### 5.2 组件与依赖注入

#### @Component / @Service / @Repository

```python
from spring.annotations import Component, Service, Repository

@Component
class EmailUtil:
    def send(self, to: str, content: str):
        pass

@Service
class UserService:
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}

@Repository
class UserRepository:
    def find_by_id(self, user_id: int):
        pass
```

#### @Autowired

```python
from spring.annotations import Service, Autowired

@Service
class UserService:
    # 构造函数注入（推荐）
    @Autowired
    def __init__(self, user_repository):
        self.user_repository = user_repository
```

**推荐构造器注入**。依赖参数应写类型注解，构造器注入能在启动阶段暴露缺失和循环依赖。

#### @Qualifier / @Primary / @Profile / @Lazy

完整参数、示例和边界说明见原文档第 5.2 节。

### 5.3 Web 控制器注解

#### @Controller / @RestController

`@RestController` 组合了 `@Controller` 和 `@ResponseBody`，返回值自动序列化为 JSON。

```python
from spring.annotations import RestController, GetMapping

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "test"}
```

#### @RequestMapping / @GetMapping / @PostMapping / @PutMapping / @PatchMapping / @DeleteMapping

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

### 5.4 参数绑定注解

> 参数标记的正确语法是 **"作为默认值"写在方法参数上**，而不是写在函数上方。

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

完整参数和示例见原文档第 5.4 节。

### 5.5 配置与属性注解

```python
from spring.annotations import Configuration, Bean, Service, Value, ConfigurationProperties, Component

@Configuration
class AppConfig:
    @Bean(name="dataSource", init_method="init", destroy_method="close")
    def data_source(self):
        return DataSource()

@Service
class AppService:
    @Value("${app.name}")
    def set_app_name(self, value: str):
        self.app_name = value

@Component
@ConfigurationProperties(prefix="spring.datasource")
class DataSourceProperties:
    def __init__(self):
        self.url = ""
        self.username = ""
        self.password = ""
```

### 5.6 日志与生命周期

```python
from spring.annotations import Service, Slf4j, PostConstruct, PreDestroy

@Service
@Slf4j  # 自动创建 self.logger
class UserService:
    def create_user(self, name: str):
        self.logger.info(f"正在创建用户: {name}")
        return {"id": 1, "name": name}

@Service
class InitService:
    @PostConstruct
    def init(self):
        self.config = self.load_config()

    @PreDestroy
    def cleanup(self):
        if self.connection:
            self.connection.close()
```

### 5.7 应用事件

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

### 5.8 核心高级注解（10 个）

#### @RateLimit - 接口限流

**解决什么问题**：限制接口被调用的频率，防止被刷爆。

```python
from spring.annotations import RateLimit, Service

@Service
class OrderService:
    # 每分钟最多100次请求（全局限制）
    @RateLimit(max_requests=100, time_window=60)
    def create_order(self, user_id: str, product_id: str):
        return {"order_id": "ORD_123"}

    # 按用户ID限流：每个用户每秒最多10次
    @RateLimit(max_requests=10, time_window=1, key="user_id")
    def get_user_info(self, user_id: str):
        return {"user_id": user_id}
```

#### @CircuitBreaker - 熔断器

**解决什么问题**：当某个方法持续失败时，暂时停止调用它（"熔断"），等一段时间后再试。

```python
from spring.annotations import CircuitBreaker, Service

@Service
class PaymentService:
    @CircuitBreaker(failure_threshold=3, recovery_timeout=10, fallback_method="payment_fallback")
    def process_payment(self, order_id: str, amount: float):
        if amount > 10000:
            raise Exception("支付网关超时")
        return {"status": "success", "transaction_id": "TXN_123"}

    def payment_fallback(self, order_id: str, amount: float):
        return {"status": "degraded", "message": "支付服务暂时不可用，请稍后重试"}
```

#### @Idempotent - 幂等性

**解决什么问题**：用户手抖点了两次"下单"，保证只有一次生效。

```python
from spring.annotations import Idempotent, Service

@Service
class OrderService:
    @Idempotent(key="order_id", expire=300, prefix="order")
    def create_order(self, order_id: str, user_id: str, amount: float):
        return {"order_id": order_id, "status": "created"}
```

#### @AuditLog / @FeatureToggle / @Lock / @Metrics / @Synchronized / @Validate / @Trace

这些高级注解的完整参数、示例和边界，沿用上方 @RateLimit 和 @CircuitBreaker 的模式。详细参数表见原文档第 5.8 节。

### 5.9 事务、缓存、任务与异步注解

```python
from spring.annotations import Service, Transactional, Cacheable, Retryable, Async, Scheduled
from spring.retry.retry_annotations import Backoff

@Service
class OrderService:
    @Transactional(rollback_for=[Exception])
    def create_order(self, user_id: int, product_id: int):
        return {"order_id": 1}

    @Cacheable(value="users", key="#user_id")
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}

    @Retryable(value=(ConnectionError,), max_retries=3, backoff=Backoff(delay=1000, multiplier=2.0))
    def call_remote(self):
        pass

    @Async
    def send_email(self, to: str, content: str):
        time.sleep(1)
        print(f"Email sent to {to}")

@Service
class ScheduledTasks:
    @Scheduled(fixed_rate=5000)
    def report_current_time(self):
        print("Current time:", time.time())
```

**边界要点**：`max_retries=3` 包含首次调用；重试耗尽可用 `@Recover` 按异常类型兜底；`@Async` 同步方法返回 `Future`；`@Scheduled` 多 worker 会重复执行。声明式切面、后置鉴权和恢复方法的完整小白示例见 [AOP_SECURITY_RETRY.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AOP_SECURITY_RETRY.md)。

### 5.10 安全、Cloud 与消息注解

| 注解 | 设计意图 | 当前真实状态 |
|------|----------|--------------|
| `@Authenticate` | 校验 JWT 并建立安全上下文 | 受管 Bean 实际执行；HTTP 控制器自动读取 `Authorization: Bearer ...` |
| `@PreAuthorize` | 按角色/权限表达式授权 | 受管 Bean 实际执行；未认证返回 401，权限不足返回 403 |
| `@PostAuthorize` | 根据方法返回值授权 | 受管 Bean 返回后执行；支持 `returnObject` / `#returnObject` |
| `@Secured` | 按任一角色授权 | 受管 Bean 实际执行 |
| `@SentinelResource` | 限流、业务异常 fallback | 受管 Bean 方法会包装；已内嵌限流熔断引擎 |
| `@GlobalTransactional` | 通过 Seata 管理全局事务 | 受管 Bean 方法调用 Seata manager |
| `@RabbitListener` | 注册 RabbitMQ 消费者 | 可直接装饰受管 Bean 方法 |

> Cloud 注解完整参数见 [CLOUD_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/CLOUD_MODULE.md)。MyBatis 注解见 [ORM_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ORM_MODULE.md)。

### 5.13 注解组合使用与执行顺序

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

**常用组合模式**：

```python
# 接口防护三件套
@SentinelResource(value="xxx", fallback="xxx_fallback")
@Metrics(name="xxx")
@RateLimit(max_requests=100, time_window=60)
def xxx_method(self):
    pass

# 支付操作完整组合
@Metrics(name="payment.create")
@Lock(key="payment_{order_id}", expire=10, wait_timeout=3)
@Idempotent(key="payment_{order_id}", expire=300)
@Validate(field="amount", min=0.01, message="金额必须大于0")
def create(self, order_id: str, amount: float):
    return {"order_id": order_id, "amount": amount}
```

---

## 6. IoC 与依赖注入（厨房比喻版）

> 🍽️ **厨房比喻**：想象你开一个餐厅。IoC 容器就是一个"自动 HR 系统"——你只要在员工简历上贴标签（`@Service`=厨师、`@Controller`=服务员、`@Mapper`=仓管员），系统就自动把他们招来、办好入职、安排工位。依赖注入（`@Autowired`）就是——厨师说"我需要一个仓管员配合我"，HR 自动把人分过去，不用你自己跑仓库找人。

### 6.1 组件类型

| 注解 | 用途 | 厨房角色 |
|------|------|----------|
| `@Component` | 通用组件 | 任何员工 |
| `@Service` | 业务服务 | 后厨大厨 |
| `@Repository` | 数据访问封装 | 仓库管理员 |
| `@RestController` / `@Controller` | Web 控制器 | 前台服务员 |
| `@Configuration` | Bean 配置类 | HR 经理（定义"怎么招人"） |
| `@Bean` | 工厂方法产生 Bean | 招聘流程 |
| `@Primary` | 同类型多个 Bean 时的首选 | "优先选这个人" |
| `@Profile` | 按环境筛选 | "这个人只在旗舰店上班" |
| `@Lazy` | 延迟创建 | 弹性用工（需要时才入职） |

### 6.2 构造器注入（推荐方式）

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

构造器注入能在启动阶段暴露缺失和循环依赖，优先于字段注入。

### 6.3 多实现与 @Qualifier

同类型存在多个 Bean 时，使用 `@Primary` 或 `@Qualifier` 指定名称。

### 6.4 配置类和 @Bean

```python
from spring.annotations import Bean, Configuration


@Configuration
class AppConfig:
    @Bean(name="clock")
    def clock(self):
        import time
        return time.time
```

### 6.5 生命周期

```python
from spring.annotations import Component, PostConstruct, PreDestroy


@Component
class ResourceHolder:
    @PostConstruct
    def start(self):
        # 初始化资源：打开数据库连接、加载配置等
        pass

    @PreDestroy
    def stop(self):
        # 清理资源：关闭连接、保存状态等
        pass
```

> **⚠️ 新手常见错误**：
> - ❌ 错误：手动 `service = UserService()` 创建对象，然后问"为什么 `@Cacheable` 不生效？"
> - ✅ 正解：容器创建的 Bean 才是"正式员工"，有事务、缓存、重试等 AOP 能力。你自己 `new` 出来的是"临时工"，什么福利都没有。

---

## 7. Web 控制器

> 🍽️ **厨房比喻**：Controller 就是餐厅的前台服务员——客人进来点菜（发 HTTP 请求），服务员把菜单传给后厨（Service），再把做好的菜端回来（返回 JSON）。服务员不炒菜，只接单和上菜。

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

未指定映射路径时默认使用方法名；类级路径前缀必须使用 `@RequestMapping("/users")`。

### 7.2 统一返回值

```python
from spring.web import Result

return Result.success({"id": 1}, message="创建成功")
return Result.bad_request("姓名不能为空")
return Result.not_found("用户不存在")
```

### 7.3 全局异常处理 & CORS & 拦截器

```python
from spring.annotations import ControllerAdvice, ExceptionHandler, Component
from spring.web import Result
from spring.web.interceptor import HandlerInterceptor


@ControllerAdvice
class GlobalExceptionHandler:
    @ExceptionHandler(ValueError)
    def handle_value_error(self, error: ValueError):
        return Result.bad_request(str(error))


@Component
class AuditInterceptor(HandlerInterceptor):
    async def pre_handle(self, request, handler):
        request.state.started = True
        return True
```

CORS 配置：

```yaml
server:
  cors:
    allow_origins:
      - https://console.example.com
    allow_credentials: true
```

---

## 8. 内嵌 PyMyBatis ORM 与 DDL

> 🍽️ **厨房比喻**：数据库就是仓库，Mapper 就是仓库管理员。厨师说要什么食材，管理员去仓库精准取货。你不用自己写繁琐的库存查询，只要告诉管理员"我要用户 ID 为 1 的信息"。

> 本节（Mapper 注解、XML Mapper、分页、SQL 安全、DDL 自动建表等）详细说明见 [ORM_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/ORM_MODULE.md)。

---

## 9. 事务

> 🍽️ **厨房比喻**：事务就像"做一道菜"——切菜、下锅、调味、装盘，必须全部完成才能端给客人。中间任何一步失败，前面切好的菜也要扔掉（回滚）。

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

**执行过程**：进入方法时创建会话并开始事务 → 当前上下文内所有 Mapper 共用该会话 → 正常返回时提交 → 满足回滚规则的异常导致回滚 → 退出后归还连接池。

### 9.2 传播级别（支持全部七种）

```python
@Transactional(propagation="REQUIRED")
@Transactional(propagation="NESTED")
```

`NESTED` 在已有事务中创建 savepoint；`REQUIRES_NEW` 使用独立 Session/连接，连接池 `max_size` 至少应能容纳并发的外层和内层连接。

### 9.3 嵌套事务 & 手动事务

嵌套 `REQUIRED` 采用 rollback-only 语义。显式 `NESTED` 时内层异常回滚到 savepoint，外层仍可提交。

```python
with factory.open_session() as session:
    with session.transaction():
        session.insert("INSERT INTO users(name) VALUES (#{name})", {"name": "A"})
        session.insert("INSERT INTO audit(event) VALUES (#{event})", {"event": "created"})
```

---

## 10. 安全与权限

> ✈️ **安检通道比喻**：安全模块就像机场安检——`@Authenticate` 检查登机牌（JWT Token），`@PreAuthorize` 检查是不是头等舱（角色/权限），`@Secured` 检查有没有进入某个区域的权限。

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

生产密钥至少 32 字符。

### 10.2 access/refresh token

```python
from spring.security.jwt_utils import JwtUtils, jwt_utils

access = jwt_utils.generate_token({"sub": "user-1"})
refresh = jwt_utils.generate_refresh_token({"sub": "user-1"})
claims = jwt_utils.decode_token(access)
new_access = jwt_utils.refresh_token(refresh)
```

**易错点**：access token 不能当作 refresh token 使用；不同密钥生成的 token 不能交叉校验。

### 10.3 方法权限

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

认证失败 → HTTP 401，授权失败 → HTTP 403。

### 10.4 安全基线

- `SPRING_PROFILES_ACTIVE=production` + `STARTUP_FAIL_FAST=true`
- `JWT_SECRET_KEY` 使用至少 32 字符的随机密钥
- `CORS_ALLOW_CREDENTIALS=true` 时不能用 `*` 来源
- SQL 值始终使用 `#{name}` 参数绑定

---

## 11. 缓存、任务与高级 AOP

### 11.1 @Cacheable

```python
from spring.annotations import Service, Cacheable

@Service
class UserService:
    @Cacheable(value="users", key="#user_id")
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}
```

本地内存缓存，最多 1000 项、TTL 300 秒，不跨进程。生产多 worker 应接入共享 Redis。

### 11.2 @Retryable

```python
from spring.annotations import Retryable
from spring.retry.retry_annotations import Backoff

@Retryable(value=(ConnectionError,), max_retries=3, backoff=Backoff(delay=1000, multiplier=2.0))
def call_remote(self):
    pass
```

**只对幂等操作开启自动重试**（如读操作）。写操作必须先设计幂等键。

重试耗尽后可以使用 `@Recover`：

```python
from spring.annotations import Recover, Retryable

@Retryable(value=(ConnectionError,), max_attempts=3, backoff=200)
def call_remote(self, key):
    raise ConnectionError("offline")

@Recover(ConnectionError)
def recover_remote(self, error, key):
    return {"key": key, "status": "degraded", "reason": str(error)}
```

恢复方法选择、异步用法和常见错误见 [AOP / 后置鉴权 / 重试恢复指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AOP_SECURITY_RETRY.md)。

### 11.3 @Async & @Scheduled

```python
from spring.annotations import Service, Async, Scheduled

@Service
class EmailService:
    @Async
    def send_email(self, to: str, content: str):
        time.sleep(1)
        print(f"Email sent to {to}")

@Service
class CleanupJob:
    @Scheduled(cron="0 */5 * * * *")
    def cleanup(self):
        pass
```

`@Async` 线程池任务不继承 MyBatis 事务；`@Scheduled` 多 worker 会重复执行。

### 11.4 高级 AOP 上线前验证

| 注解 | 上线前必须验证 |
|------|--------------|
| `@RateLimit` | 多进程/多副本一致性、Redis 故障降级 |
| `@CircuitBreaker` | 状态存储、半开恢复、超时 |
| `@Idempotent` | 键设计、TTL、并发竞争 |
| `@Lock` | 租约续期、误释放、时钟同步 |

---

## 12. AI 与 LangChain 模块

### 12.1 AI 模块（对接大模型）

> 完整文档：[AI_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/AI_MODULE.md)。安装：`pip install springbootAI[ai]`。
>
> 提供 ChatClient（链式对话）、Advisor（对话顾问）、Tools（工具调用）、RAG（知识库检索增强生成）、Function Calling 等能力。支持 OpenAI / Ollama / DeepSeek / Moonshot 等多家大模型。

### 12.2 LangChain 模块

> 完整文档：[LANGCHAIN_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/LANGCHAIN_MODULE.md)。安装：`pip install springbootAI[langchain]`。
>
> 封装 langchain classic 全套：Chains / Agents(6 种) / Memory / Retrievers / VectorStores / Parsers / Loaders + 30+ 提供商。双向适配器复用 `spring.ai` 的模型 Bean。

**最小示例**（无需 API Key）：

```python
from spring.context.registry import BeanRegistry
from spring.ai.autoconfig import configure_ai
from spring.langchain.autoconfig import configure_langchain

registry = BeanRegistry()
configure_ai(registry=registry)
beans = configure_langchain(registry=registry)

chain = beans["lcChainService"]
print(chain.run_llm_chain("回答: {q}", q="你好"))
```

---

## 13. Java 开发者看这里

> 📌 **Java 开发者专用**：如果你之前用 Java Spring Boot / Spring Cloud Alibaba / MyBatis，这一节告诉你如何迁移到 SpringBootAI。

### 13.1 核心原则（5 条）

1. 先迁移接口契约和测试，再迁移框架注解。
2. Python 使用类型标注、Pydantic 和显式依赖，比模拟 Java 反射更可靠。
3. **只有由容器创建的 Bean 才获得事务、缓存、重试等 AOP 行为**——手工 `new` 的对象不受容器管理。
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
| `mvn spring-boot:run` | `python -m acme.Application` 或 `uvicorn asgi:app` |

### 13.3 启动和依赖注入对照

**启动类**：Java `@SpringBootApplication(scanBasePackages = "com.acme")` + `SpringApplication.run()` → Python `@SpringBootApplication(scan_base_packages=["acme"])` + `run(Application)`

**Bean 注解映射**：

| Java 注解 | SpringBootAI | 说明 |
|---|---|---|
| `@Component` / `@Service` / `@Repository` | 同名 | 行为一致 |
| `@RestController` | `@RestController` | 注册 FastAPI JSON 路由 |
| `@Controller` | `@Controller` | 当前按 API 响应处理，不提供模板视图语义 |
| `@Configuration` + `@Bean` | 同名 | 行为一致 |
| `@Primary` / `@Qualifier` / `@Profile` / `@Lazy` | 同名 | 行为基本一致 |

**推荐构造器注入**：

```python
from spring.annotations import Autowired, Service

@Service
class UserService:
    @Autowired
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper
```

### 13.4 Web 层 & AOP & MyBatis 迁移

| Java | SpringBootAI | 注意事项 |
|---|---|---|
| `@GetMapping` / `@PostMapping` 等 | 同名 | `@PathVariable` 等参数绑定写在默认值位置 |
| `@Transactional` | `@Transactional` | 支持全部七种传播模式 |
| `@Cacheable` | `@Cacheable` | 本地缓存默认 TTL 300 秒 |
| `@Retryable` | `@Retryable` | `max_retries` 包含首次调用 |
| `@Async` | `@Async` | 返回 `Future`/`Task`，不继承线程事务 |
| `@Scheduled` | `@Scheduled` | 每个 worker 都会调度 |
| MyBatis `@Mapper` | `@Mapper` + 注解/SQL | XML 功能矩阵基本对齐 |

### 13.5 MyBatis 到 PyMyBatis（代码对照）

Java：
```java
@Mapper
public interface UserMapper {
  @Select("select id, name from users where id = #{id}")
  User findById(@Param("id") long id);
}
```

Python：
```python
from dataclasses import dataclass
from typing import Optional
from spring.orm import Mapper, Param, Select


@dataclass
class User:
    name: str
    id: Optional[int] = None


@Mapper
class UserMapper:
    @Select("SELECT id, name FROM users WHERE id = #{id}")
    def find_by_id(self, id: int) -> Optional[User]:
        pass
```

### 13.6 Cloud & DDL 迁移

| Java | SpringBootAI | 说明 |
|---|---|---|
| `@EnableDiscoveryClient` + Nacos | `@EnableDiscoveryClient` + `discovery` 配置 | 需部署 Nacos 并做集成测试 |
| `@FeignClient` | 同名 + `spring.cloud.feign` | 不兼容 Java interface proxy |
| `@SentinelResource` | 同名 | 已内嵌引擎，无需 Dashboard |
| JPA `hibernate.ddl-auto` | `@entity` + `ddl-auto` 配置 | 支持 create/update/validate/create-drop |

### 13.7 验证顺序

1. 创建虚拟环境，安装依赖。
2. 运行内置测试。
3. 用 SQLite 验证 Mapper SQL、事务、动态 SQL。
4. 用目标数据库版本执行相同测试。
5. 启动 ASGI 应用，检查 `/docs`、`/actuator/health`。
6. 接入外部中间件，演练断线、重复投递和回滚。

---

## 14. 生产部署

### 14.1 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| Redis | 6.0+ | 分布式锁、限流、缓存 |
| MySQL | 5.7+ / 8.0+ | 业务数据存储 |
| Nacos | 2.0+ | 服务注册发现（可选） |

### 14.2 基础服务部署

**Redis**：
```bash
sudo apt update && sudo apt install redis-server  # Ubuntu/Debian
redis-cli ping   # 应返回 PONG
```

**MySQL 8+ 用户创建**：
```sql
CREATE USER 'spring_python'@'%' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON your_database.* TO 'spring_python'@'%';
FLUSH PRIVILEGES;
```

### 14.3 生产配置与启动

```yaml
# application-prod.yml
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
  ddl-auto:
    mode: validate
    entity_packages: app.entity
```

**生产启动**：
```bash
export SPRING_PROFILES_ACTIVE=production
export JWT_SECRET_KEY="使用密钥管理系统注入至少32字符的随机值"
export STARTUP_FAIL_FAST=true
uvicorn myapp.asgi:app --host 0.0.0.0 --port 8080 --workers 4
```

**Gunicorn（推荐）**：
```bash
pip install gunicorn uvicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080 myapp.asgi:app
```

### 14.4 生产环境变量速查

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 8080 |
| `JWT_SECRET_KEY` | JWT 密钥 | spring-python-secret-key-change-in-production |
| `DB_URL` | 数据库连接 URL | sqlite:///./test.db |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis 连接 | localhost/6379/空 |
| `NACOS_SERVER` | Nacos 地址 | localhost:8848 |
| `SPRING_DISABLE_DOCKER_IP_DETECT` | 禁用容器 IP 检测 | 0 |

### 14.5 验证部署 & 故障排查

```bash
curl http://localhost:8080/actuator/health
# 返回 {"status":"UP","components":{"redis":"UP","database":"UP",...}}
```

**常见故障**：Nacos Docker 退出码 255 → 配置认证 Token；MySQL 认证失败 → 检查 `allowPublicKeyRetrieval=true`；Redis 连接 111 → `redis-cli ping` 检查。

---

## 15. 项目结构

`example`、`example1`、`example5`、`example_langchain` 是仓库级示例，不属于 `springbootAI` 安装包。实际项目应创建自己的应用包。

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

每个被扫描目录都应包含 `__init__.py`，并从项目根目录启动。`scan_base_packages` 和 `@MapperScan` 接受的是可导入包名。

---

## 16. 测试

从工作区根目录运行：

```bash
python -m pytest -q tests
```

重点覆盖：
- 独立和内嵌 ORM 源码一致。
- 连接池共享、扩容、归还和未提交回滚。
- 普通事务与嵌套 rollback-only。
- Spring Mapper 在事务中复用 Session。
- JWT access/refresh、生产密钥校验。
- AI 模块 87 用例，LangChain 模块 75 用例，全量 707 用例 0 失败。

> 详细测试环境、套件覆盖和集成测试结果，见 [TEST_REPORT.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/TEST_REPORT.md)。

---

## 17. 常见问题与排错

### 17.1 启动时找不到组件

1. 目录是否有 `__init__.py`。
2. `scan_base_packages` 是否是可导入包名，不是文件路径。
3. 启动工作目录是否包含项目根目录。
4. 组件类是否带 `@Service`、`@RestController` 等注解。
5. `@Profile` 是否与当前环境一致。

### 17.2 Mapper 未注册

检查 `database.enabled: true`、`database.orm: mybatis`、`@Mapper`、`@MapperScan` 路径。

### 17.3 `@Transactional` 报缺少工厂

说明 MyBatis 没有初始化。确认数据库已启用、ORM 模式正确、Service 是由容器创建而不是手工 `UserService()`。

### 17.4 数据库连接耗尽

检查 Session 是否通过上下文管理器关闭、请求是否有长事务、`实例 x worker x max_size` 是否超过数据库上限。

### 17.5 生产启动拒绝 JWT

设置 `SPRING_PROFILES_ACTIVE=production`、`STARTUP_FAIL_FAST=true`、`JWT_SECRET_KEY=<至少32字符随机密钥>`。

### 17.6 Nacos / PATCH / 配置同步排错

- **Nacos Docker 退出码 255**：配置认证 Token 和相关环境变量。
- **`PATCH /api/...` 返回 404**：确认方法用 `@PatchMapping`，框架已接入 `fastapi_app.patch()`。
- **`ConfigLoader()` 读不同文件**：确认通过 `ApplicationContext` 启动，不是在不同工作目录直接实例化加载器。

### 17.7 LangChain 模块排错

- **`@Autowired` 注入 `lcChainService` 失败**：确认调用了 `configure_ai()` + `configure_langchain()`。
- **Partner 注册失败（跳过）**：按告警提示 `pip install langchain-<partner>`。
- **RAG 报`嵌入模型未装配`**：设置 `AI_ALLOW_FAKE=true` 降级或提供真实 API Key。

### 17.8 上线前清单

- 使用实际数据库版本运行 CRUD、事务、断连恢复测试。
- 使用迁移工具管理结构，不让应用运行账号执行 DDL。
- 锁定依赖，执行漏洞扫描。
- 为 JWT、数据库、Redis 使用密钥管理系统。
- 配置 TLS、CORS 白名单、请求限制。
- 验证备份恢复、主从切换。
- 对定时任务设计唯一执行或幂等。
- 执行越权、SQL 注入、重放测试。

---

## 18. 性能与容量验证

仓库提供 Docker 化的 SpringBootAI 基准服务和 k6 `smoke`、`baseline`、`stress`、`soak` 四档压测。快速验证：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke
```

完整参数和说明见 [性能测试指南](https://github.com/YUCONGGEN/springbootAI/blob/master/tests_performance/README.md)。

AI、LangChain、LangGraph 和 MCP 已提供独立 workload，并已加入 9 小时 `mixed` 长稳测试。默认使用 Fake 模型和进程内 MCP Server，不访问外部模型、不会产生 Token 费用：

```powershell
.\scripts\run-load-test.ps1 -Profile smoke -Workload ai
.\scripts\run-load-test.ps1 -Profile smoke -Workload langchain
.\scripts\run-load-test.ps1 -Profile smoke -Workload langgraph
.\scripts\run-load-test.ps1 -Profile smoke -Workload mcp
.\scripts\run-9h-soak-test.ps1 -Rate 100 -Workers 4 -MaxVus 1000
.\scripts\run-9h-soak-test.ps1 -Duration 24h -Rate 100 -Workers 4 -MaxVus 1000
```

真实模型压测必须使用隔离账号、费用预算和供应商限流配置；Fake 模型结果只能说明框架路径稳定，不能代表真实模型响应时间。

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
export DB_ENTITY_PACKAGES=

# Nacos
export DISCOVERY_ENABLED=false
export NACOS_SERVER=localhost:8848
export NACOS_NAMESPACE=
export NACOS_GROUP=DEFAULT_GROUP
export NACOS_USERNAME=nacos
export NACOS_PASSWORD=nacos

# Docker 辅助
export SPRING_DISABLE_DOCKER_IP_DETECT=0

# Retry
export RETRY_ENABLED=true
export RETRY_MAX_RETRIES=3
export RETRY_DELAY=1000
export RETRY_MAX_DELAY=10000
export RETRY_MULTIPLIER=2.0

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

# AI 模块
export AI_PROVIDER=openai
export AI_ALLOW_FAKE=true
export OPENAI_API_KEY=sk-xxx
export OPENAI_CHAT_MODEL=gpt-4o-mini
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_CHAT_MODEL=llama3

# LangChain 模块
export LC_ENABLED=true
export LC_DEFAULT_LLM=auto
export LC_AGENT_TYPE=react
export LC_AGENT_MAX_ITER=10
export LC_VECTOR_STORE=faiss
export LC_RETRIEVER=similarity
export LC_RETRIEVER_K=4
export LC_MEMORY=buffer
export LC_MEMORY_MAX=20
```

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
      NACOS_AUTH_ENABLE: "true"
      NACOS_AUTH_TOKEN: "c3ByaW5ncHktbmFjb3MtaGFuZHNoYWtlLXNlY3JldC0yMDI2LTA4LTA0LTAx"
      NACOS_AUTH_IDENTITY_KEY: "springpy"
      NACOS_AUTH_IDENTITY_VALUE: "springpy-local"
      JAVA_TOOL_OPTIONS: "-XX:-UseContainerSupport"

volumes:
  redis_data:
  mysql_data:
```

## LangGraph 独立模块

LangGraph 不会随核心包或 LangChain classic 自动安装。需要状态图、条件路由、流式执行或人工审核时，单独安装：

```bash
pip install springbootAI[langgraph]
# 源码仓库也可以使用：
pip install -r requirements-langgraph.txt
```

完整的小白入门、配置说明、`spring.ai` 模型复用、持久化 checkpointer、异步调用和测试命令请阅读 [LANGGRAPH_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/LANGGRAPH_MODULE.md)。可选依赖已包含官方 SQLite checkpointer，适合本地单进程恢复测试；多 worker 生产环境必须注入共享数据库后端。无 LangGraph 依赖时保持 `spring.langgraph.enabled=false`，不会影响其他模块。

## MCP 客户端与服务端

MCP 模块同时支持客户端和服务端，并提供可执行注解：客户端使用 `@MCPClient` + `@MCPCall` 把方法调用转换成真实 MCP 请求；服务端使用 `@MCPServer` + `@MCPTool` / `@MCPResource` / `@MCPPrompt` 发布能力。安装：

```bash
pip install springbootAI[mcp]
```

完整配置、FastAPI 挂载、stdio、认证、白名单、Spring AI/LangChain/LangGraph 组合方式和测试命令见 [MCP_MODULE.md](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/MCP_MODULE.md)。

LangChain 也支持 `@LangChainClient` + `@LangChainCall`，LangGraph 支持 `@LangGraph` + `@GraphNode` + `@GraphEdge` + `@GraphRoute` + `@GraphInvoke`。这些注解复用现有运行时，不会重新实现 LangChain、LangGraph 或 MCP 协议。
