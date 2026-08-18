# SpringBootAI Starter 机制 —— 依赖管理指南

> SpringBootAI 2.3.2
> 配置位置：`pyproject.toml` 的 `[project.optional-dependencies]` 段
> 对齐 Java：Spring Boot Starter（`spring-boot-starter-*`）

---

## 目录

- [模块概述](#模块概述)
- [可用 Starter 列表](#可用-starter-列表)
- [组合 Starter](#组合-starter-webcloudall)
- [使用示例](#使用示例)
- [与 Java Spring Boot Starter 对照表](#与-java-spring-boot-starter-对照表)
- [最佳实践](#最佳实践)
- [常见问题 FAQ](#常见问题-faq)

---

## 模块概述

### 什么是 Starter 机制？

**Starter 机制**是一种"按需引入依赖"的工程实践：把某一类功能所需的依赖打包成一个命名的"Starter"，开发者只需安装这个 Starter，就能一次性拿到该功能所需的全部依赖。

打个比方：你想组装一台电脑，不需要单独买 CPU、内存、主板、电源，直接买一个"游戏主机套装"（Starter），里面包含搭配好的全部配件。

| 场景 | 不用 Starter | 用 Starter |
|------|-------------|-----------|
| **装 MySQL 支持** | 自己查文档，手动 `pip install PyMySQL==1.2.0` | `pip install springbootAI[mysql]` 一行搞定 |
| **装 AI 模块** | 自己挑 langchain 各种包的兼容版本，容易装错 | `pip install springbootAI[ai]` 框架已验证版本 |
| **版本冲突** | 自己装的包和框架不兼容，运行时报错 | Starter 内版本已测试锁定，保证兼容 |
| **团队协作** | 每个人自己装依赖，版本五花八门 | 统一用 Starter，环境一致 |
| **升级依赖** | 一个个包升级，容易遗漏 | 升级框架版本，Starter 内的依赖一起更新 |

### SpringBootAI Starter 的实现

SpringBootAI 通过 Python 标准的 **PEP 621 可选依赖（optional-dependencies / extras）** 实现 Starter 机制：

```toml
# pyproject.toml
[project.optional-dependencies]
mysql = ["PyMySQL==1.2.0"]          # Starter: mysql
ai = ["langchain-openai==1.4.2", ...]  # Starter: ai
```

安装方式：

```bash
pip install "springbootAI[mysql]"        # 单个 Starter
pip install "springbootAI[mysql,redis]"  # 多个 Starter
pip install "springbootAI[all]"          # 全部 Starter
```

> **对齐 Java**：本机制对齐 Java Spring Boot 的 `spring-boot-starter-*`。Java 用 Maven `<dependency>` 引入 starter，Python 用 pip extras 引入。概念完全一致，方便 Java 开发者迁移。

### 版本锁定策略

SpringBootAI 的所有直接依赖使用 `==` **精确版本锁定**，这是有意为之：

- ✅ 保证所有用户装到完全一致、已测试的版本
- ✅ 避免上游包悄悄发版导致不兼容
- ✅ 安全：CI 流水线会用 `pip-audit` 持续扫描漏洞

少数 partner 包（如 LangChain 各厂商集成）使用上限锁定（`>=x,<y`），因为它们更新频繁且向后兼容。

---

## 可用 Starter 列表

### 数据库驱动 Starter

对齐 Java：`spring-boot-starter-jdbc` / `spring-boot-starter-data-jpa`

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `mysql` | `pip install "springbootAI[mysql]"` | `PyMySQL==1.2.0` | MySQL 数据库驱动 |
| `postgresql` | `pip install "springbootAI[postgresql]"` | `psycopg2-binary==2.9.12` | PostgreSQL 数据库驱动 |
| `sqlalchemy` | `pip install "springbootAI[sqlalchemy]"` | `sqlalchemy==2.0.40` | SQLAlchemy ORM（用于 Repository 抽象层） |

### 缓存 Starter

对齐 Java：`spring-boot-starter-data-redis`

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `redis` | `pip install "springbootAI[redis]"` | `redis==8.1.0` | Redis 缓存与消息发布订阅 |

### 消息队列 Starter

对齐 Java：`spring-boot-starter-amqp` / `spring-kafka`

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `rabbitmq` | `pip install "springbootAI[rabbitmq]"` | `pika==1.4.4` | RabbitMQ 消息队列 |
| `kafka` | `pip install "springbootAI[kafka]"` | `kafka-python==2.0.2` | Kafka 消息队列 |

### 服务发现 Starter

对齐 Java：`spring-cloud-starter-alibaba-nacos-discovery`

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `nacos` | `pip install "springbootAI[nacos]"` | `nacos-sdk-python==2.0.11` | Nacos 服务发现与配置中心 |

### 监控与日志 Starter

对齐 Java：`spring-boot-starter-actuator` + Micrometer

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `prometheus` | `pip install "springbootAI[prometheus]"` | `prometheus-client==0.26.0` | Prometheus 指标监控 |
| `logging` | `pip install "springbootAI[logging]"` | `loguru==0.7.3` | Loguru 结构化日志 |

### 安全检测 Starter

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `ast` | `pip install "springbootAI[ast]"` | `sqlglot==27.28.1` | SQL 注入检测（AST 解析） |

### Excel 处理 Starter

对齐 Java：alibaba EasyExcel

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `excel` | `pip install "springbootAI[excel]"` | `openpyxl==3.1.5` | Excel 注解驱动读写（EasyExcel 风格） |

### AI 模块 Starter

对齐 Java：Spring AI（`ChatClient` / `Advisor` / `ETL` / `Tools`）

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `ai` | `pip install "springbootAI[ai]"` | `langchain-openai==1.4.2`、`langchain-core==1.5.4`、`langchain-classic==1.0.8`、`langchain-text-splitters==1.1.2`、`langchain-community==0.4.2`、`numpy==2.2.6`、`pydantic==2.13.4` | Spring AI 风格的 ChatClient/Advisor/Tools/RAG |

> **设计说明**：AI 模块采用"可选依赖 + 降级"设计——未安装时仍可用（降级为原生 HTTP + FakeChatModel），不会启动失败。

### LangChain 模块 Starter

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `langchain` | `pip install "springbootAI[langchain]"` | langchain 全家桶 + faiss-cpu + pypdf + beautifulsoup4 + 9 个 partner 包（anthropic/ollama/chroma/mistralai/cohere/google-vertexai/deepseek/zhipuai/experimental） | LangChain classic 全套能力 + 30+ partner 提供商 |

**langchain Starter 包含的 partner 提供商：**

| Partner 包 | 支持的厂商 |
|------------|-----------|
| `langchain-anthropic` | Anthropic Claude |
| `langchain-ollama` | Ollama 本地模型 |
| `langchain-chroma` | Chroma 向量数据库 |
| `langchain-mistralai` | Mistral AI |
| `langchain-cohere` | Cohere |
| `langchain-google-vertexai` | Google Vertex AI |
| `langchain-deepseek` | DeepSeek |
| `langchain-zhipuai` | 智谱 AI（GLM） |
| `langchain-experimental` | 实验性功能（如 SQL 代理） |

> **设计说明**：partner 包按需启用，未安装的 partner 由 `@ConditionalOnClass` + 友好错误自动跳过，不会导致启动失败。详见 `doc/LANGCHAIN_MODULE.md`。

### LangGraph 模块 Starter

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `langgraph` | `pip install "springbootAI[langgraph]"` | `langgraph==1.2.9`、`langgraph-checkpoint-sqlite==3.1.1` | LangGraph 状态图编排与可恢复执行 |

### MCP 模块 Starter

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `mcp` | `pip install "springbootAI[mcp]"` | `mcp==2.0.0` | Model Context Protocol 客户端/服务端集成（官方 Python SDK v2） |

### 开发与测试 Starter

| Starter 名称 | 安装命令 | 包含的依赖 | 用途 |
|--------------|----------|-----------|------|
| `dev` | `pip install "springbootAI[dev]"` | `pytest==9.1.1`、`pytest-cov==7.1.0`、`redis==8.1.0`、`sqlglot==27.28.1` | 开发与测试工具链 |

---

## 组合 Starter（web/cloud/all）

组合 Starter 把多个单一 Starter 打包在一起，类似 Java Spring Boot 的 `spring-boot-starter-web` / `spring-boot-starter-cloud`。

### web —— Web 应用快速启动

对齐 Java：`spring-boot-starter-web`

```bash
pip install "springbootAI[web]"
```

**包含的依赖：**

| 依赖 | 版本 | 用途 |
|------|------|------|
| `fastapi` | `0.115.6` | Web 框架 |
| `uvicorn` | `0.34.0` | ASGI 服务器 |
| `pydantic` | `2.13.4` | 数据校验 |
| `python-multipart` | `0.0.20` | 表单/文件上传 |

> **适用场景**：只做 Web API、不需要数据库和消息队列的轻量服务。

### cloud —— 微服务全家桶

对齐 Java：`spring-cloud-starter` + 各中间件

```bash
pip install "springbootAI[cloud]"
```

**包含的依赖（嵌套引用其他 Starter）：**

| 依赖来源 | 内容 |
|----------|------|
| `springbootAI[web]` | web Starter 全部依赖 |
| `springbootAI[redis]` | Redis |
| `springbootAI[rabbitmq]` | RabbitMQ |
| `springbootAI[kafka]` | Kafka |
| `httpx==0.28.1` | HTTP 客户端（服务间调用） |

> **适用场景**：构建微服务，需要 Web + 缓存 + 消息队列 + 服务间 HTTP 调用。

### all —— 全量安装

```bash
pip install "springbootAI[all]"
```

**包含的依赖（聚合所有功能 Starter）：**

| 依赖来源 | 内容 |
|----------|------|
| `springbootAI[web]` | Web 框架 |
| `springbootAI[mysql]` | MySQL 驱动 |
| `springbootAI[redis]` | Redis |
| `springbootAI[rabbitmq]` | RabbitMQ |
| `springbootAI[kafka]` | Kafka |
| `springbootAI[prometheus]` | Prometheus 监控 |
| `springbootAI[logging]` | Loguru 日志 |
| `springbootAI[excel]` | Excel 读写 |
| `springbootAI[ai]` | Spring AI 模块 |
| `springbootAI[langchain]` | LangChain 模块 |
| `springbootAI[langgraph]` | LangGraph 模块 |
| `springbootAI[mcp]` | MCP 模块 |
| `httpx==0.28.1` | HTTP 客户端 |
| `psutil==6.1.1` | 系统资源监控 |

> **适用场景**：本地开发学习、想一次性体验所有功能。**不推荐生产用**——会装很多用不到的依赖，增加镜像体积和攻击面。

### full —— 显式全量（不嵌套）

```bash
pip install "springbootAI[full]"
```

与 `all` 类似，但**不通过嵌套引用其他 Starter**，而是直接列出所有依赖的精确版本。适合需要精确控制每个依赖版本的场景。

**额外包含（all 没有的）：**

- `psycopg2-binary==2.9.12`（PostgreSQL 驱动）
- `sqlalchemy==2.0.40`（SQLAlchemy）
- `nacos-sdk-python==2.0.11`（Nacos）
- `sqlglot==27.28.1`（SQL 注入检测）
- `defusedxml==0.7.1`（安全 XML 解析）
- `requests==2.34.2`（HTTP 客户端）

---

## 使用示例

### 示例 1：最小 Web 应用

```bash
# 只装 web Starter
pip install "springbootAI[web]"
```

```python
from springbootai.annotations import SpringBootApplication, RestController, GetMapping


@SpringBootApplication
class Application:
    pass


@RestController
class HelloController:

    @GetMapping("/hello")
    def hello(self):
        return {"message": "Hello, SpringBootAI!"}


if __name__ == "__main__":
    from springbootai.main import SpringApplication
    SpringApplication(Application).run()
```

### 示例 2：Web + MySQL 应用

```bash
# 装 web + mysql 两个 Starter
pip install "springbootAI[web,mysql]"
```

```yaml
# application.yml
database:
  enabled: true
  orm: mybatis
  driver: mysql
  host: localhost
  port: 3306
  username: root
  password: secret
  database: mydb
```

```python
from springbootai.annotations import SpringBootApplication, MapperScan


@SpringBootApplication(scan_base_packages=["app"])
@MapperScan(base_packages=["app.mapper"])
class Application:
    pass
```

### 示例 3：微服务应用

```bash
# 装 cloud 组合 Starter
pip install "springbootAI[cloud]"
```

```yaml
# application.yml
spring:
  application:
    name: order-service
  cloud:
    nacos:
      discovery:
        server-addr: localhost:8848

database:
  enabled: true
  driver: mysql
  host: localhost
  port: 3306
  database: orders

spring:
  redis:
    host: localhost
    port: 6379

spring:
  rabbitmq:
    host: localhost
    port: 5672
```

### 示例 4：AI 应用

```bash
# 装 ai Starter
pip install "springbootAI[ai]"

# 或者装 langchain 全家桶
pip install "springbootAI[langchain]"
```

```python
from springbootai.ai import ChatClient, UserMessage


chat_client = ChatClient.builder().build()

response = chat_client.prompt(
    messages=[UserMessage("用一句话解释什么是数据库迁移")]
).call()

print(response.content)
```

### 示例 5：全栈应用

```bash
# 一键装所有功能（学习/演示用）
pip install "springbootAI[all]"
```

### 示例 6：开发环境配置

```bash
# 装核心 + 开发工具
pip install "springbootAI[web,mysql,dev]"
```

开发工具包含：
- `pytest`：单元测试
- `pytest-cov`：测试覆盖率
- `redis`：测试用 Redis
- `sqlglot`：SQL 注入检测

### 示例 7：在 requirements.txt 中使用

```
# requirements.txt
$12.3.2
```

```
# 或者用组合 Starter
$12.3.2
```

### 示例 8：在 pyproject.toml 中使用（自己的项目）

```toml
# 你的项目的 pyproject.toml
[project]
name = "my-app"
version = "1.0.0"
dependencies = [
    "$12.3.2",
]
```

---

## 与 Java Spring Boot Starter 对照表

| Java Spring Boot Starter | SpringBootAI Starter | 说明 |
|--------------------------|---------------------|------|
| `spring-boot-starter` | （核心依赖，默认安装） | 基础依赖，SpringBootAI 的 `dependencies` 段 |
| `spring-boot-starter-web` | `springbootAI[web]` | Web 应用 |
| `spring-boot-starter-jdbc` | `springbootAI[mysql]` / `springbootAI[postgresql]` | 数据库驱动 |
| `spring-boot-starter-data-jpa` | `springbootAI[sqlalchemy]` | ORM（SQLAlchemy 对应 JPA） |
| `spring-boot-starter-data-redis` | `springbootAI[redis]` | Redis |
| `spring-boot-starter-amqp` | `springbootAI[rabbitmq]` | RabbitMQ |
| `spring-kafka` | `springbootAI[kafka]` | Kafka |
| `spring-cloud-starter-alibaba-nacos` | `springbootAI[nacos]` | Nacos |
| `spring-boot-starter-actuator` | `springbootAI[prometheus]` | 监控指标 |
| （Logback 默认集成） | `springbootAI[logging]` | 日志（Loguru 对应 Logback） |
| （无对应） | `springbootAI[ast]` | SQL 注入检测 |
| （无对应） | `springbootAI[excel]` | Excel（对齐 alibaba EasyExcel） |
| `spring-ai-openai-spring-boot-starter` | `springbootAI[ai]` | Spring AI |
| （无对应） | `springbootAI[langchain]` | LangChain 集成 |
| （无对应） | `springbootAI[langgraph]` | LangGraph 状态图 |
| （无对应） | `springbootAI[mcp]` | Model Context Protocol |
| `spring-boot-starter-test` | `springbootAI[dev]` | 测试工具 |
| `spring-boot-starter-cloud` | `springbootAI[cloud]` | 微服务全家桶 |
| （无对应） | `springbootAI[all]` / `springbootAI[full]` | 全量安装 |

### Maven 与 pip 用法对照

**Java Maven：**

```xml
<!-- pom.xml -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
</dependency>
```

**Python pip：**

```bash
# 命令行
pip install "springbootAI[web]"

# 或在 pyproject.toml
[project]
dependencies = [
    "$12.3.2",
]
```

**Java 多 Starter：**

```xml
<dependency>
    <artifactId>spring-boot-starter-web</artifactId>
</dependency>
<dependency>
    <artifactId>spring-boot-starter-data-redis</artifactId>
</dependency>
```

**Python 多 Starter：**

```bash
# 逗号分隔
pip install "springbootAI[web,redis]"

# 或用组合 Starter
pip install "springbootAI[cloud]"
```

---

## 最佳实践

### 1. 按需安装，不要用 `all`

✅ **推荐**：只装项目真正需要的 Starter

```bash
# 一个 Web + MySQL 应用
pip install "springbootAI[web,mysql]"
```

❌ **不推荐**：生产环境用 `all`

```bash
# 装了一堆用不到的依赖（Kafka、LangChain、MCP...）
pip install "springbootAI[all]"
```

> `all` 会装几十个包，增大镜像体积、增加攻击面、拖慢部署。生产环境只装必要的。

### 2. 锁定框架版本

```bash
# ❌ 危险：不锁版本，可能装到不兼容的新版
pip install "springbootAI[web]"

# ✅ 安全：锁定版本
pip install "$12.3.2"
```

```
# requirements.txt
$12.3.2
```

### 3. 开发/生产环境分开

```
# requirements.txt（生产）
$12.3.2

# requirements-dev.txt（开发，额外加测试工具）
-r requirements.txt
$12.3.2
```

```bash
# 生产部署
pip install -r requirements.txt

# 本地开发
pip install -r requirements-dev.txt
```

### 4. 用组合 Starter 简化配置

如果你的应用确实需要 Web + Redis + RabbitMQ + Kafka，用组合 Starter 比单独列更简洁：

```bash
# ❌ 啰嗦
pip install "springbootAI[web,redis,rabbitmq,kafka]"

# ✅ 简洁
pip install "springbootAI[cloud]"
```

### 5. AI 模块用降级设计，不强制安装

SpringBootAI 的 AI 模块设计为"可选依赖 + 降级"——不装 `ai` Starter 也能启动，只是 AI 功能降级为原生 HTTP + FakeChatModel。

```python
# 即使没装 springbootAI[ai]，这段代码也能启动
from springbootai.ai import ChatClient

# 但调用时会提示安装 ai Starter
chat_client = ChatClient.builder().build()
```

> 这意味着你可以在项目初期不装 AI 依赖，等到真正需要时再装。

### 6. partner 包按需补装

`langchain` Starter 默认装了 9 个常用 partner 包（OpenAI、Anthropic、Ollama 等）。如果需要其他厂商（如 Bedrock、Azure OpenAI），按需单独安装：

```bash
# 装基础 langchain Starter
pip install "springbootAI[langchain]"

# 按需补装其他 partner
pip install langchain-aws
pip install langchain-google-genai
```

### 7. Docker 镜像分层缓存

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 先装依赖（利用缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码（代码变动不会重装依赖）
COPY . /app
WORKDIR /app

CMD ["python", "Application.py"]
```

### 8. 用 `pip-audit` 检查安全漏洞

```bash
# 装好依赖后扫描漏洞
pip install pip-audit
pip-audit
```

SpringBootAI 的 CI 流水线会用 `pip-audit` 持续扫描所有 Starter 的依赖，但建议你在本地也定期扫描。

---

## 常见问题 FAQ

**Q1: 为什么不把所有依赖都放进核心 `dependencies`？**

A: 三个原因：
1. **减小体积**：不是每个项目都需要 MySQL、Kafka、LangChain，全装会让包变得巨大
2. **避免冲突**：不同项目可能需要不同版本的依赖，可选依赖让用户自己决定
3. **降低攻击面**：少装不用的依赖，减少潜在漏洞

**Q2: `all` 和 `full` 有什么区别？**

A:
- `all`：通过**嵌套引用**其他 Starter 实现，依赖列表简洁，但某些 partner 包版本用上限锁定
- `full`：**直接列出所有依赖的精确版本**，不嵌套，版本控制更严格

生产环境推荐 `full`（版本精确），学习演示用 `all`（简洁）。

**Q3: 装了 `web` Starter 还需要单独装 fastapi 吗？**

A: 不需要。`web` Starter 已经包含 `fastapi==0.141.1`，直接 `pip install "springbootAI[web]"` 即可。

**Q4: Starter 里的版本号能改吗？**

A: 可以，但不推荐。Starter 内的版本号经过测试验证，改了可能不兼容。如果必须改（比如安全漏洞），建议：
1. 在 `requirements.txt` 中覆盖版本：`$12.3.2` + `fastapi==0.141.1`
2. 充分测试后部署

**Q5: 为什么 `web` Starter 里的 fastapi 版本（0.115.6）和核心依赖里的（0.141.1）不一样？**

A: 核心依赖 `dependencies` 段的 `fastapi==0.141.1` 是框架运行所需的最低版本；`web` Starter 里的 `fastapi==0.141.1` 是脚手架工具生成新项目时用的版本。两者现在保持一致，安装时不会产生版本冲突。建议以核心依赖的版本为准。

**Q6: 装了 `mysql` Starter 后，还需要在代码里做什么？**

A: 装好驱动后，在 `application.yml` 配置数据库连接即可：

```yaml
database:
  enabled: true
  driver: mysql          # 用 mysql Starter 装的 PyMySQL
  host: localhost
  port: 3306
  database: mydb
  username: root
  password: secret
```

框架会自动检测 PyMySQL 是否安装，没装会给出友好提示。

**Q7: 如何查看已安装的 Starter？**

A:

```bash
# 查看已安装的包
pip list | grep springbootAI

# 或用 CLI 工具
springbootai info
```

`springbootai info` 会显示已安装的可选依赖（fastapi、pymysql、redis 等）。

**Q8: 没装某个 Starter，代码里 import 会怎样？**

A: 框架用 `@ConditionalOnClass` 设计，未安装的模块会被自动跳过，不会启动失败。但调用相关功能时会抛出友好错误，提示安装对应 Starter：

```
ImportError: MySQL driver not found.
Please install: pip install "springbootAI[mysql]"
```

**Q9: Starter 支持离线安装吗？**

A: 支持。先在有网环境下载 wheel 文件，再离线安装：

```bash
# 有网环境：下载
pip download "springbootAI[web,mysql]" -d ./wheels

# 离线环境：安装
pip install --no-index --find-links=./wheels springbootAI[web,mysql]
```

**Q10: 如何贡献新的 Starter？**

A: 在 `pyproject.toml` 的 `[project.optional-dependencies]` 段新增一个条目：

```toml
[project.optional-dependencies]
# 新增你的 Starter
my-feature = ["some-package==1.0.0"]
```

然后通过 `pip install "springbootAI[my-feature]"` 安装。建议遵循现有命名风格（小写、连字符）。

---

## 改进记录

### v2.3.0 — Starter 体系完善

- 新增 `langgraph`、`mcp` 两个 Starter
- `all` 组合 Starter 纳入 `langgraph` 和 `mcp`
- `langchain` Starter 加入 9 个常用 partner 包
- 所有依赖版本锁定到已测试安全版本

### v2.0.0 — 组合 Starter 引入

- 新增 `web`、`cloud`、`all` 三个组合 Starter
- 对齐 Java Spring Boot 的 starter 命名约定
