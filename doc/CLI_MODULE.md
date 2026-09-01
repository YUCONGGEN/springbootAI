# SpringBootAI CLI 与项目脚手架 —— 使用指南

> 框架版本：SpringBootAI 2.3.11
> 源码位置：`springbootai/cli/main.py`、`springbootai/cli/scaffold.py`
> 对齐 Java：Spring Boot CLI / Spring Initializr

---

## 目录

- [模块概述](#模块概述)
- [安装和验证](#安装和验证)
- [子命令列表](#子命令列表)
- [项目脚手架（springbootai init）](#项目脚手架springbootai-init)
  - [创建新项目流程](#创建新项目流程)
  - [生成的项目结构](#生成的项目结构)
- [运行应用（springbootai run）](#运行应用springbootai-run)
- [生成 API 文档（springbootai docs）](#生成-api-文档springbootai-docs)
- [完整使用示例](#完整使用示例)
- [与 Java Spring Initializr 对照表](#与-java-spring-initializr-对照表)
- [常见问题 FAQ](#常见问题-faq)

---

## 模块概述

### 什么是 SpringBootAI CLI？

**SpringBootAI CLI** 是框架提供的命令行工具，对齐 Java 生态的 **Spring Boot CLI** 和 **Spring Initializr**。

打个比方：你要盖一栋房子，不需要自己从挖地基开始，CLI 就像一个"房屋建造助手"——你说"我要一栋三层别墅"，它直接帮你搭好框架结构，你只需要做内部装修（写业务代码）。

| 场景 | 不用 CLI | 用 CLI |
|------|----------|--------|
| **创建新项目** | 手动建目录、写 `Application.py`、写 `application.yml`、写 `requirements.txt`... | `springbootai init my-project` 中文问答生成；CI 加 `--non-interactive` |
| **查看框架版本** | `pip show springbootAI` | `springbootai version` |
| **查看运行环境** | 自己写脚本检查 Python 版本、已装依赖 | `springbootai info` 一键展示 |
| **查看可用模块** | 翻文档 | `springbootai list modules` |
| **查看可用注解** | 翻文档 | `springbootai list annotations` |
| **运行应用** | `python Application.py` | `springbootai run Application.py` |
| **生成 API 文档** | 自己配 Sphinx | `springbootai docs` |

### 两个命令入口

SpringBootAI 提供两个独立的命令行入口（在 `pyproject.toml` 的 `[project.scripts]` 段注册）：

| 命令 | 注册位置 | 用途 |
|------|----------|------|
| `springbootai` | `springbootai.main:run_cli` | 主命令，支持多个子命令（version/info/list/init/run/docs） |
| `springbootai-init` | `springbootai.cli.scaffold:main` | 独立的脚手架命令（等价于 `springbootai init`） |

> **对齐 Java**：本模块参考 Java 的 [Spring Boot CLI](https://docs.spring.io/spring-boot/cli/index.html) 和 [Spring Initializr](https://start.spring.io/)。Spring Initializr 是 Web 界面的项目生成器，SpringBootAI 用命令行实现类似流程。

### 与 Java Spring Boot CLI 的差异

| 特性 | Java Spring Boot CLI | SpringBootAI CLI |
|------|---------------------|------------------|
| 脚本运行 | 支持 Groovy 脚本直接运行 | 仅支持 `.py` 文件 |
| 项目生成 | 集成 Spring Initializr | 通过 `init` 子命令实现 |
| 依赖管理 | 内置依赖管理 | 通过 pip extras（Starter）实现 |
| 语言 | Groovy / Java | Python |

---

## 安装和验证

### 安装 SpringBootAI

```bash
# 基础安装（包含 CLI）
pip install springbootAI

# 或带 Starter 安装
pip install "springbootAI[web,mysql]"
```

安装后，`springbootai` 命令会自动注册到系统 PATH。

### 验证安装

```bash
# 查看版本
springbootai version
```

预期输出：

```
SpringBootAI v2.3.11
  Python: 3.11.5
  Platform: Windows-10-10.0.22621-SP0
  Installation: e:\交付\springbootAI

```

如果提示 `springbootai: command not found`，检查：

1. Python 的 Scripts 目录是否在 PATH 中（Windows 通常是 `C:\Python311\Scripts`）
2. 是否用 `pip install springbootAI` 安装了框架
3. 是否在虚拟环境中（确保激活了虚拟环境）

### 查看详细环境信息

```bash
springbootai info
```

输出示例：

```
============================================================
SpringBootAI 运行环境信息
============================================================
SpringBootAI 2.3.11
Python 版本: 3.11.5 (main, ...)
Python 路径: /usr/bin/python3
操作系统: Linux-5.15.0-x86_64
处理器: x86_64
工作目录: /home/user/my-project

已安装的依赖:
  [✓] Web: fastapi (0.141.1)
  [✓] ASGI Server: uvicorn (0.39.0)
  [✓] Validation: pydantic (2.13.4)
  [✓] MySQL Driver: pymysql (1.2.0)
  [✓] Redis: redis (8.1.0)
共 5 个可选依赖已安装
```

---

## 子命令列表

`springbootai` 命令支持以下子命令：

| 子命令 | 语法 | 说明 |
|--------|------|------|
| `version` | `springbootai version` | 显示框架版本、Python 版本、平台信息 |
| `info` | `springbootai info` | 显示详细运行环境信息（含已安装依赖检测） |
| `list` | `springbootai list <what>` | 列出可用模块或注解 |
| `init` | `springbootai init [project] [options]` | 初始化新项目（终端内默认中文问答） |
| `run` | `springbootai run <app_file>` | 运行应用入口文件 |
| `docs` | `springbootai docs [options]` | 生成 API 文档（基于 Sphinx） |

### 不带参数运行

```bash
springbootai
```

会显示帮助信息：

```
usage: springbootai [-h] {version,info,list,init,run,docs} ...

SpringBootAI 命令行工具（对齐 Spring Boot CLI）

positional arguments:
  {version,info,list,init,run,docs}
    version             显示框架版本信息
    info                显示运行环境信息
    list                列出可用模块或注解
    init                初始化新项目（中文问答向导；可用 --non-interactive 关闭问答）
    run                 运行应用
    docs                生成 API 文档（Sphinx）
```

### springbootai list 子命令

`list` 命令支持两个参数：

```bash
# 列出所有可用模块
springbootai list modules

# 列出所有可用注解
springbootai list annotations
```

**`list modules` 输出示例：**

```
SpringBootAI 可用模块（22 个）:
------------------------------------------------------------
  annotations          IoC/AOP/Web/Security 注解（90+）
  context              应用上下文与 Bean 容器
  web                  Web MVC + Actuator + CSRF + HATEOAS
  orm                  MyBatis 风格 ORM + 数据库迁移
  security             JWT + OAuth2 + 密码编码
  messaging            RabbitMQ + Kafka 消息队列
  cloud                服务发现 + Seata + 网关 + 配置中心 + 事件总线
  ai                   Spring AI 风格 ChatClient/Advisor/Tools/RAG
  langchain            LangChain 集成（agents/chains/memory）
  langgraph            LangGraph 状态图编排
  mcp                  Model Context Protocol 客户端/服务端
  batch                Spring Batch 批处理框架
  csv                  CSV 注解驱动读写
  excel                Excel 注解驱动读写（EasyExcel 风格）
  i18n                 国际化消息源
  data                 Repository 抽象 + Data REST + 分页排序
  websocket            WebSocket 支持
  devtools             DevTools 热重载
  config               配置加载与元数据
  scheduling           定时任务
  validation           Bean Validation
  retry                重试与恢复
```

**`list annotations` 输出示例：**

```
SpringBootAI 可用注解（90 个）:
------------------------------------------------------------
  @Autowired
  @Bean
  @Component
  @ConditionalOnClass
  @Configuration
  @Controller
  @DeleteMapping
  ...
```

---

## 项目脚手架（springbootai init）

`springbootai init` 命令用于创建符合 SpringBootAI 风格的新项目，对齐 Java 的 Spring Initializr。

### 两种使用模式

| 模式 | 触发方式 | 适用场景 |
|------|----------|----------|
| **交互式问答** | 在真实终端执行 `springbootai init [project]`，或显式加 `--interactive` | 新手友好，逐步确认项目意图 |
| **非交互模式** | 显式加 `--non-interactive`；无 TTY 的管道环境也会自动避免读取输入 | CI/CD、脚本自动化 |

在终端中，即使已写项目名或模块参数，仍会进入问答；命令行参数只是对应问题的默认值。例如：

```bash
springbootai init my-app --modules web,orm
```

会显示模块默认值 `web,orm`，其余问题仍可直接回车使用默认值。要让命令完全不提问，必须加入 `--non-interactive`。

### 命令语法

```bash
springbootai init [project] [options]
```

**完整参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project` | 位置参数 | `demo-app`（交互时） | 项目名称或目标路径（如 `my-app` 或 `./my-app`）；交互模式可以留空后填写 |
| `--package` / `-p` | 选项 | 从项目名派生 | Python 包名（连字符转下划线，小写） |
| `--modules` / `-m` | 选项 | `web` | 启用的模块，逗号分隔：`web,orm,ai,cloud,redis` |
| `--port` | 选项 | `8000` | 服务端口 |
| `--database` | 选项 | `none` | 数据库类型：`none` / `sqlite` / `mysql` / `postgresql` |
| `--redis` / `--no-redis` | 布尔标志 | 否 | 启用/关闭 Redis 配置 |
| `--ai` / `--no-ai` | 布尔标志 | 否 | 启用/关闭 AI 配置骨架 |
| `--cloud` / `--no-cloud` | 布尔标志 | 否 | 启用/关闭 Cloud（Nacos/服务发现）配置 |
| `--docker` / `--no-docker` | 布尔标志 | 是 | 生成/不生成 Docker 文件 |
| `--sample-crud` / `--no-sample-crud` | 布尔标志 | 否 | 生成/不生成示例 CRUD 代码（需要 ORM 模块） |
| `--interactive` | 标志 | — | 强制使用中文问答向导 |
| `--non-interactive` | 标志 | — | 禁用问答，仅使用参数（CI 模式） |

### 模块别名

为方便使用，以下别名自动映射：

| 别名 | 映射到 | 说明 |
|------|--------|------|
| `database` / `mybatis` | `orm` | 数据库/ORM 模块 |
| `nacos` | `cloud` | 云服务模块 |
| `cache` | `redis` | 缓存模块 |

### 智能自动推导

脚手架会根据参数自动推导配置，减少手动选择：

| 触发条件 | 自动行为 |
|----------|----------|
| 选择 `orm` 但未选 `--database` | 数据库默认设为 `sqlite` |
| 选择 `mysql` / `postgresql` 但未选 `orm` | 自动添加 `orm` 模块 |
| 使用 `--redis` 但 `modules` 中无 `redis` | 自动添加 `redis` 模块 |
| 使用 `--ai` 但 `modules` 中无 `ai` | 自动添加 `ai` 模块 |
| 使用 `--cloud` 但 `modules` 中无 `cloud` | 自动添加 `cloud` 模块 |
| 使用 `--redis` / `--ai` / `--cloud` 标志 | 对应 `enabled` 自动设为 `true` |

### 创建新项目流程

#### 方式一：交互式问答（推荐新手）

在真实终端中直接运行 `init` 命令；可以带项目名，模块等参数会作为问答默认值：

```bash
springbootai init my-app
```

问答过程：

```
项目名称或目录 [my-app]:
Python 包名（回车自动推导） [my_app]:
功能模块（逗号分隔：web, orm, ai, cloud, redis） [web]:
HTTP 端口 [8000]:
数据库类型（none/sqlite/mysql/postgresql） [none]:
是否启用 Redis 配置（是/否） [否]:
是否启用 AI 配置（是/否） [否]:
是否启用 Cloud/Nacos 配置（是/否） [否]:
是否生成 Docker 文件（是/否） [是]:
是否生成示例 CRUD（需要 ORM）（是/否） [否]:

项目已创建：/home/user/my-app
  包名：my_app
  模块：web
  端口：8000
  数据库：none

下一步：
  1. cd /home/user/my-app
  2. python -m pip install -r requirements.txt
  3. python Application.py
```

#### 方式二：非交互模式（CI/CD 友好）

```bash
# 创建 Web + ORM + AI 项目，配置 MySQL 数据库
springbootai init my-app \
  --modules web,orm,ai \
  --port 8080 \
  --database mysql \
  --redis \
  --docker \
  --sample-crud \
  --non-interactive
```

输出：

```
项目已创建：/home/user/my-app
  包名：my_app
  模块：web, orm, ai, redis
  端口：8080
  数据库：mysql

下一步：
  1. cd /home/user/my-app
  2. python -m pip install -r requirements.txt
  3. python Application.py
```

#### 方式三：混合模式（参数 + 交互确认）

```bash
# 指定模块和端口，其余走问答
springbootai init my-app --modules web,orm,ai --port 8080

# 手动指定端口，数据库走问答
springbootai init my-app --port 9000 --docker --no-ai
```

> **提示**：不指定 `--non-interactive` 时，未在命令行提供的选项会通过问答补全。指定 `--non-interactive` 后，所有未传参数使用默认值。

#### 方式四：使用独立脚手架命令

```bash
# 等价于 springbootai init；脚本场景显式关闭问答
springbootai-init my-app --modules web,orm --port 8080 --non-interactive
```

### 包名派生规则

如果不指定 `--package`，包名从项目名自动派生：

| 项目名 | 派生的包名 | 说明 |
|--------|-----------|------|
| `my-project` | `my_project` | 连字符转下划线 |
| `my project` | `my_project` | 空格转下划线 |
| `MyProject` | `myproject` | 转小写 |
| `123app` | `_123app` | 数字开头加下划线前缀 |
| `my.app!` | `myapp` | 移除非法字符 |

也可以手动指定：

```bash
springbootai init my-project --package custom_pkg --non-interactive
```

> **包名校验**：包名必须是合法的 Python 标识符（`^[a-zA-Z_][a-zA-Z0-9_]*$`），否则会抛出 `ValueError`。

### 安全检查

脚手架会**拒绝覆盖已有非空目录**，防止误操作：

```bash
# 目录已存在且非空
springbootai init existing-project
# 创建项目失败：目录 '/path/to/existing-project' 已存在且非空（directory is not empty），为避免覆盖用户文件已停止
```

如果需要在空目录中创建项目，可以：

```bash
mkdir my-project
springbootai init my-project --non-interactive
```

### 生成的项目结构

以 `springbootai init my-app --modules web,orm,redis --port 9000 --database mysql --docker --sample-crud --non-interactive` 为例：

```
my-app/
├── Application.py               # 启动类（含 @SpringBootApplication）
├── config/
│   └── application.yml          # 配置文件（含完整注释）
├── requirements.txt             # 依赖清单
├── README.md                    # 项目说明（含模块表、启动步骤）
├── .env.example                 # 环境变量模板（保护敏感配置）
├── .gitignore                   # Git 忽略规则
├── .dockerignore                # Docker 忽略规则
├── Dockerfile                   # Docker 镜像构建文件（--docker 时生成）
├── docker-compose.yml           # 多服务编排（--docker 时生成）
├── docs/
│   ├── 启动指南.md               # 项目启动说明
│   ├── AI配置说明.md             # AI 配置详解（--ai 时生成）
│   └── Cloud配置说明.md          # Cloud 配置详解（--cloud 时生成）
├── tests/
│   └── test_smoke.py            # 冒烟测试（验证应用可启动）
└── src/
    └── my_app/                  # Python 包（从项目名派生）
        ├── __init__.py
        ├── common/              # 公共模块
        │   ├── __init__.py
        │   ├── response.py       # 统一响应格式
        │   ├── exceptions.py     # 业务异常定义
        │   └── handlers.py       # 全局异常处理器
        ├── controllers/         # 控制器目录（web 模块）
        │   ├── __init__.py
        │   └── hello_controller.py  # 示例控制器
        ├── services/            # 业务服务层（--sample-crud 时生成）
        │   ├── __init__.py
        │   └── user_service.py   # 用户 CRUD 服务
        ├── models/              # 实体模型（--sample-crud 时生成）
        │   ├── __init__.py
        │   └── user.py           # 用户实体
        ├── repositories/        # 数据仓储层（--sample-crud 时生成）
        │   ├── __init__.py
        │   └── user_repository.py  # 用户仓储
        └── mappers/             # MyBatis Mapper（orm 模块）
            └── __init__.py
```

#### 各文件内容说明

**Application.py（启动类）：**

```python
"""my-app 的 SpringBootAI 启动入口。"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 显式导入全局异常处理器；控制器由组件扫描注册。
from my_app.common import handlers as _global_handlers  # noqa: F401
from my_app.controllers import *  # noqa: F401,F403
from springbootai.annotations import SpringBootApplication


@SpringBootApplication(scan_base_packages=["my_app"])
class Application:
    """应用启动入口。"""

    @staticmethod
    def main() -> None:
        from springbootai.main import SpringApplication
        SpringApplication(Application).run()


def create_app():
    """供 uvicorn Application:create_app --factory 使用。"""
    from springbootai.main import create_app as _create_app
    return _create_app(Application)


if __name__ == "__main__":
    Application.main()
```

**config/application.yml（配置文件）：**

```yaml
# my-app 的 SpringBootAI 配置文件
# 生产环境请替换密钥、收紧 CORS，并按需启用外部服务。

server:
  port: 9000
  host: "${SERVER_HOST:0.0.0.0}"
  cors:
    allow_origins: ["http://localhost:3000"]
    allow_credentials: false

spring:
  application:
    name: my-app
  ai:
    enabled: false              # 未配置密钥时不会调用模型
  cloud:
    nacos:
      discovery:
        enabled: false          # 外部服务默认关闭

# 数据库配置（orm 模块 + mysql）
database:
  enabled: true
  orm: mybatis
  driver: mysql
  host: "${DB_HOST:localhost}"
  port: "${DB_PORT:3306}"
  database: "${DB_NAME:springbootai}"
  username: "${DB_USERNAME:}"
  password: "${DB_PASSWORD:}"
  ddl-auto:
    mode: none

# Redis 配置
redis:
  enabled: true
  host: "${REDIS_HOST:localhost}"
  port: "${REDIS_PORT:6379}"
  password: "${REDIS_PASSWORD:}"

# 其余常用配置（JWT、Nacos、RabbitMQ、Kafka、Prometheus、日志、缓存、重试、追踪）
# 均已在生成的 config/application.yml 中保留中文说明和默认值。
```

**requirements.txt（依赖清单）：**

```
# my-app 依赖（由 SpringBootAI 脚手架生成）
springbootAI==2.3.11
PyMySQL==1.2.0          # MySQL 驱动
redis==8.1.0            # Redis 客户端
```

### 不同模块组合的生成结果

| 模块组合 | 生成的目录 | 配置段 | requirements.txt 额外依赖 |
|----------|-----------|--------|--------------------------|
| `web` | `controllers/`, `common/` | `server` | 无 |
| `orm` | `models/`, `repositories/`, `mappers/` | `database` | MySQL/PostgreSQL 时增加对应驱动 |
| `ai` | 无额外目录 | `springbootai.ai` | `langchain-openai==1.4.2` |
| `cloud` | `docs/Cloud配置说明.md` | `springbootai.cloud` + `discovery` | Nacos/RabbitMQ 依赖按需生成 |
| `redis` | 无额外目录 | `redis` | `redis==8.1.0` |
| `web,orm,redis` | `controllers/`, `common/`, `models/`, `repositories/`, `mappers/` | `server` + `database` + `redis` | 数据库驱动 + `redis` |
| `web,orm,ai` | `controllers/`, `common/`, `models/`, `repositories/`, `mappers/` | `server` + `database` + `springbootai.ai` | AI 依赖按需生成 |

### 通过 Python 代码调用脚手架

除了命令行，也可以在 Python 代码中调用：

```python
from springbootai.cli.scaffold import create_project

# 创建项目
project_dir = create_project(
    project_path="my-project",
    package="my_package",
    modules="web,orm",
    port=9000,
)
print(f"项目已创建: {project_dir}")
```

```python
from springbootai.cli.scaffold import main

# 命令行风格调用
main(['my-project', '--modules', 'web,orm', '--port', '9000', '--non-interactive'])
```

---

## 运行应用（springbootai run）

`springbootai run` 命令用于运行应用入口文件。

### 命令语法

```bash
springbootai run <app_file>
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `app_file` | 位置参数 | 必填 | 应用入口文件（如 `Application.py`） |

### 使用示例

```bash
# 运行当前目录下的 Application.py
springbootai run Application.py

# 运行指定路径的应用
springbootai run /path/to/Application.py
```

### 执行流程

1. 检查应用文件是否存在（不存在则报错退出）
2. 将应用文件所在目录加入 `sys.path`
3. 使用标准库 `runpy.run_path(..., run_name='__main__')` 执行入口

> **说明**：`springbootai run` 本质上等价于 `python Application.py`，但提供了统一的命令入口。它会自动把应用文件所在目录加入 Python 路径，方便导入同目录下的模块。

### 与直接运行的区别

```bash
# 方式一：直接运行
python Application.py

# 方式二：用 CLI 运行（等价）
springbootai run Application.py
```

两者效果相同。CLI 方式的优势是统一了命令入口，适合在脚本/CI 中使用。

---

## 生成 API 文档（springbootai docs）

`springbootai docs` 命令用于基于 Sphinx 生成 API 文档。

### 命令语法

```bash
springbootai docs [--docs-dir <dir>] [--output <dir>]
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--docs-dir` | 选项 | `docs` | Sphinx 配置目录（需包含 `conf.py`） |
| `--output` | 选项 | `docs/_build` | 输出目录 |

### 前置条件

使用前需安装 Sphinx：

```bash
pip install sphinx
```

并在项目的 `docs/` 目录下有 `conf.py` 配置文件。

### 使用示例

```bash
# 使用默认配置
springbootai docs

# 指定目录
springbootai docs --docs-dir docs --output docs/_build
```

### 执行流程

1. 检查 `docs-dir` 是否存在（不存在则报错退出）
2. 调用 `sphinx-build -b html <docs-dir> <output>` 构建文档
3. 构建成功后输出 HTML 文件路径

输出示例：

```
生成 API 文档...
  源目录: docs
  输出目录: docs/_build
文档已生成: docs/_build/index.html
```

> **说明**：如果 `sphinx-build` 命令未找到，会提示安装 Sphinx：`pip install sphinx`。

---

## 完整使用示例

下面演示从零创建一个完整项目的流程。

### 1. 创建项目

```bash
# 创建一个 Web + ORM + AI 的项目
springbootai init blog-system --modules web,orm,ai --port 8080 --database mysql --non-interactive
```

输出：

```
项目已创建：/home/user/blog-system
  包名：blog_system
  模块：web, orm, ai
  端口：8080
  数据库：mysql

下一步：
  1. cd /home/user/blog-system
  2. python -m pip install -r requirements.txt
  3. python Application.py
```

### 2. 进入项目并安装依赖

```bash
cd blog-system
pip install -r requirements.txt
```

`requirements.txt` 内容：

```
# blog-system 依赖（由 SpringBootAI 脚手架生成）
springbootAI==2.3.11
PyMySQL==1.2.0                 # MySQL 驱动
langchain-openai==1.4.2        # AI OpenAI 适配器（按需）
langchain-core==1.5.4          # AI 核心类型（按需）
```

### 3. 查看项目结构

```
blog-system/
├── Application.py
├── config/
│   └── application.yml
├── requirements.txt
├── README.md
└── src/
    └── blog_system/
        ├── __init__.py
        ├── controllers/
        │   └── __init__.py      # 含 HelloController 示例
        └── models/
            └── __init__.py
```

### 4. 添加自己的控制器

编辑 `src/blog_system/controllers/__init__.py`，添加业务控制器：

```python
"""blog-system controllers"""

from springbootai.annotations import RestController, GetMapping, PostMapping


@RestController
class HelloController:
    """示例控制器"""

    @GetMapping("/hello")
    def hello(self):
        return {"message": "Hello from blog-system!"}


@RestController("/api/posts")
class PostController:
    """文章控制器"""

    @GetMapping("/")
    def list_posts(self):
        return {"posts": [{"id": 1, "title": "第一篇博客"}]}

    @GetMapping("/{post_id}")
    def get_post(self, post_id: int):
        return {"id": post_id, "title": "示例文章", "content": "..."}
```

### 5. 添加实体模型

创建 `src/blog_system/models/post.py`：

```python
"""blog-system entity models"""
from dataclasses import dataclass
from springbootai.orm import Entity, Id, Column


@Entity("posts")
@dataclass
class Post:
    id: int = None
    title: str = ""
    content: str = ""
```

### 6. 修改配置

编辑 `config/application.yml`，配置数据库和 AI：

```yaml
server:
  port: 8080
  host: 0.0.0.0

spring:
  application:
    name: blog-system

# ORM 配置
spring:
  datasource:
    url: sqlite:///blog.db
    driver: sqlite
  jpa:
    ddl-auto:
      mode: update
    entity-packages:
      - blog_system.models

# AI 配置
spring:
  ai:
    model: gpt-4o-mini
    api-key: ${OPENAI_API_KEY}

logging:
  level: INFO
```

### 7. 配置 Mapper 扫描

编辑 `Application.py`，添加 `@MapperScan`：

```python
"""blog-system 启动类"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from springbootai.annotations import SpringBootApplication
from springbootai.orm import MapperScan
from blog_system.controllers import *  # noqa: F401, F403


@SpringBootApplication(scan_base_packages=["blog_system"])
@MapperScan(base_packages=["blog_system.mapper"])
class Application:
    """应用启动入口"""

    @staticmethod
    def main():
        from springbootai.main import SpringApplication
        app = SpringApplication(Application)
        app.run()


if __name__ == '__main__':
    Application.main()
```

### 8. 运行应用

```bash
# 方式一：用 CLI 运行
springbootai run Application.py

# 方式二：直接运行
python Application.py
```

启动后访问：

- `GET http://localhost:8080/hello` → 示例接口
- `GET http://localhost:8080/api/posts/` → 文章列表

### 9. 查看环境信息

```bash
springbootai info
```

### 10. 生成 API 文档（可选）

```bash
# 需要先安装 Sphinx
pip install sphinx

# 生成文档
springbootai docs
```

---

## 与 Java Spring Initializr 对照表

| 特性 | Java Spring Initializr | SpringBootAI CLI |
|------|------------------------|------------------|
| **交互方式** | Web 界面（start.spring.io）+ CLI | 命令行（交互式问答 + 非交互 CI 模式） |
| **创建项目命令** | `spring init --dependencies=web,jpa my-project` | `springbootai init my-project`（交互）或追加 `--non-interactive`（脚本） |
| **项目名** | `--name` 或 `--artifact-id` | 位置参数（项目名/路径） |
| **包名** | `--package-name`（Java 包名） | `--package`（Python 包名） |
| **模块选择** | `--dependencies=web,jpa,security` | `--modules=web,orm,ai,redis` |
| **数据库类型** | Web 界面选择 | `--database`（sqlite/mysql/postgresql/none） |
| **端口配置** | 无（在 application.properties 中配） | `--port`（生成时直接写入配置） |
| **Redis/AI/Cloud** | Web 界面勾选 | `--redis`/`--ai`/`--cloud` 布尔标志 |
| **Docker 支持** | 无 | `--docker`/`--no-docker` 控制生成 |
| **示例代码** | 无 | `--sample-crud` 生成完整 CRUD 示例 |
| **生成构建文件** | `pom.xml` / `build.gradle` | `requirements.txt` |
| **生成启动类** | `Application.java`（含 `@SpringBootApplication`） | `Application.py`（含 `@SpringBootApplication`） |
| **生成配置文件** | `application.properties` | `application.yml` |
| **生成 README** | 否 | 是（`README.md`，含模块表、启动步骤） |
| **生成 .gitignore** | 否 | 是 |
| **生成 Docker 文件** | 否 | 是（`--docker` 时生成 `Dockerfile` + `docker-compose.yml`） |
| **依赖管理工具** | Maven / Gradle | pip / pyproject.toml |
| **语言** | Java / Kotlin / Groovy | Python |

### 命令对照

**Java Spring Initializr：**

```bash
# Web 界面
https://start.spring.io/

# 命令行
spring init \
  --dependencies=web,jpa \
  --name=my-project \
  --package-name=com.example \
  my-project
```

**SpringBootAI CLI：**

```bash
# 命令行（交互式）
springbootai init my-project

# 命令行（非交互 CI 模式）
springbootai init my-project \
  --modules web,orm,ai \
  --port 8080 \
  --database mysql \
  --redis \
  --docker \
  --sample-crud \
  --non-interactive
```

### 生成结构对照

**Java Spring Initializr 生成的结构：**

```
my-project/
├── pom.xml                          # Maven 构建文件
├── src/
│   ├── main/
│   │   ├── java/
│   │   │   └── com/example/
│   │   │       └── Application.java  # 启动类
│   │   └── resources/
│   │       └── application.properties
│   └── test/
└── mvnw / mvnw.cmd                  # Maven Wrapper
```

**SpringBootAI CLI 生成的结构：**

```
my-project/
├── Application.py                   # 启动类
├── requirements.txt                 # 依赖清单（对应 pom.xml）
├── config/
│   └── application.yml              # 配置文件
├── README.md
├── .env.example                     # 环境变量模板
├── .gitignore
├── Dockerfile                       # --docker 时生成
├── docker-compose.yml               # --docker 时生成
├── docs/
│   └── 启动指南.md
├── tests/
│   └── test_smoke.py
└── src/
    └── my_project/                  # Python 包
        ├── __init__.py
        ├── common/                  # 公共模块（ApiResponse, 异常处理）
        ├── controllers/             # 控制器（对应 java/.../controller/）
        ├── services/                # 业务服务（--sample-crud）
        ├── models/                  # 实体（对应 java/.../entity/）
        ├── repositories/            # 数据仓储（--sample-crud）
        └── mappers/                 # MyBatis Mapper（orm）
```

---

## 常见问题 FAQ

**Q1: `springbootai` 命令找不到怎么办？**

A: 排查步骤：
1. 确认已安装：`pip show springbootAI`
2. 检查 Python Scripts 目录是否在 PATH 中
3. 如果用虚拟环境，确保已激活：`source venv/bin/activate`（Linux）或 `venv\Scripts\activate`（Windows）
4. 尝试重新安装：`pip install --force-reinstall springbootAI`

**Q2: `init` 命令支持哪些模块？**

A: 当前支持 5 个模块：`web`、`orm`、`ai`、`cloud`、`redis`。可以任意组合，用逗号分隔。另外支持别名 `database`/`mybatis` → `orm`、`nacos` → `cloud`、`cache` → `redis`。

```bash
# 完整示例
springbootai init my-app --modules web,orm,ai,cloud,redis --database mysql --redis --ai --cloud --non-interactive
```

不支持的模块名会报错。

**Q2a: 如何选择数据库类型？**

A: 通过 `--database` 参数，支持 4 种选项：

```bash
# SQLite（默认，无需额外配置）
springbootai init my-app --modules web,orm --non-interactive

# MySQL
springbootai init my-app --modules web,orm --database mysql --non-interactive

# PostgreSQL
springbootai init my-app --modules web,orm --database postgresql --non-interactive

# 不使用数据库
springbootai init my-app --modules web --database none --non-interactive
```

**Q2b: 如何在 CI/CD 中使用脚手架？**

A: 使用 `--non-interactive` 模式，所有参数通过命令行指定：

```bash
# GitHub Actions / Jenkins 等 CI 环境
springbootai init my-app \
  --modules web,orm,redis \
  --port 8080 \
  --database mysql \
  --redis \
  --docker \
  --non-interactive
```

**Q3: 生成的项目端口怎么改？**

A: 两种方式：
1. 交互式问答时填写端口，或脚本创建时指定：`springbootai init my-app --port 9000 --non-interactive`
2. 创建后修改 `config/application.yml` 中的 `server.port`

**Q4: 包名能包含连字符吗？**

A: 不能。Python 包名必须是合法标识符（只能含字母、数字、下划线，不能以数字开头）。脚手架会自动把项目名中的连字符转为下划线：

- 项目名 `my-project` → 包名 `my_project`

也可以手动指定：`springbootai init my-project --package my_pkg --non-interactive`

**Q5: 能在已有项目里追加模块吗？**

A: 不能直接追加。`init` 命令是创建新项目的，不支持修改已有项目。如果想在已有项目里加模块：
1. 手动创建对应目录（如 `models/`）
2. 手动在 `application.yml` 中添加配置段
3. 手动在 `requirements.txt` 中添加依赖

**Q6: `springbootai run` 和 `python Application.py` 有什么区别？**

A: 功能等价。`springbootai run` 会自动把应用文件所在目录加入 `sys.path`，方便导入同目录模块。两者都启动应用，效果相同。

**Q7: 生成的 `Application.py` 里的 `sys.path.insert` 是干什么的？**

A: 把项目的 `src/` 目录加入 Python 路径，让启动入口可以导入项目包、全局异常处理器和控制器。脚手架把 Python 包放在 `src/` 下（类似 Java 的 `src/main/java/` 结构），因此需要显式加入搜索路径。

**Q8: `springbootai docs` 生成文档失败怎么办？**

A: 排查步骤：
1. 确认已安装 Sphinx：`pip install sphinx`
2. 确认 `docs/` 目录存在且有 `conf.py` 配置文件
3. 查看 Sphinx 构建错误信息（会输出到 stderr）
4. 如果没有 `conf.py`，先初始化：`sphinx-quickstart docs`

**Q9: 脚手架生成的项目能直接部署到生产吗？**

A: 生成的项目是**开发模板**，可以直接用于开发，但生产部署前建议：
1. 确保 `.env.example` 中的敏感信息通过环境变量注入（生成的配置已使用 `${VAR}` 引用）
2. `logging.level` 默认为 `INFO`，适合生产环境
3. 在 `requirements.txt` 中锁定所有依赖版本
4. 若启用了 `--docker`，生成的 `Dockerfile` 和 `docker-compose.yml` 可直接作为生产部署的基础
5. 生成的 `.gitignore` 已排除 `__pycache__`、`.env`、`*.db` 等敏感文件
6. 建议添加 CI 配置和自定义健康检查

**Q10: `springbootai-init` 和 `springbootai init` 有什么区别？**

A: 功能完全相同，是两个独立的命令入口：
- `springbootai init <project>` —— 主命令的子命令
- `springbootai-init <project>` —— 独立的命令

两者底层都调用 `springbootai.cli.scaffold.main()`，生成相同的项目结构。用哪个都行，`springbootai init` 更符合统一命令风格。

**Q11: 如何查看脚手架生成的模板源码？**

A: 模板定义在 `springbootai/cli/scaffold.py` 的顶部（`_APPLICATION_TEMPLATE`、`_APPLICATION_YML_TEMPLATE` 等变量）。如果你想自定义模板，可以直接修改这些字符串。

**Q12: 生成的 README.md 里有什么？**

A: 包含：
- 项目名称和框架版本
- 快速开始（安装依赖、启动应用）
- 项目结构说明
- 启用的模块列表
- SpringBootAI 文档链接

---

## 改进记录

### v2.3.2 — CLI 交互式脚手架

- `init` 命令新增**中文交互式问答**模式，逐步引导创建项目
- `init` 命令新增 **`--non-interactive`** 模式，支持 CI/CD 自动化
- `init` 命令新增 **`--database`** 参数（`sqlite`/`mysql`/`postgresql`/`none`）
- `init` 命令新增 **`--redis`/`--no-redis`**、**`--ai`/`--no-ai`**、**`--cloud`/`--no-cloud`** 布尔标志
- `init` 命令新增 **`--docker`/`--no-docker`** 控制 Docker 文件生成
- `init` 命令新增 **`--sample-crud`/`--no-sample-crud`** 控制示例 CRUD 代码生成
- 新增**模块别名**：`database`/`mybatis` → `orm`、`nacos` → `cloud`、`cache` → `redis`
- 新增**智能自动推导**：选择 `orm` 自动推导 `sqlite`，启用 `redis`/`ai`/`cloud` 自动添加对应模块
- 脚手架生成的项目结构升级：新增 `common/`、`services/`、`repositories/`、`mappers/` 目录，`.env.example`、`.gitignore`、`Dockerfile`、`docker-compose.yml`、`tests/test_smoke.py` 等文件
- 配置文件 `logging.level` 从 Spring Boot 嵌套格式改为扁平字符串格式，兼容性更好
- `_safe_print` 支持 Windows 控制台 GBK 编码自动降级，避免 Unicode 输出异常

### v2.3.0 — CLI 完善

- `init` 命令支持 `--port` 参数，生成时直接写入配置
- `info` 命令新增 MCP、LangGraph 等依赖检测
- `list modules` 新增 batch、csv、scheduling 等模块
- 脚手架生成的 `application.yml` 支持多模块配置段

### v2.0.0 — CLI 引入

- 新增 `springbootai` 主命令，支持 version/info/list/init/run/docs 子命令
- 新增 `springbootai-init` 独立脚手架命令
- 对齐 Java Spring Initializr 的项目生成能力
