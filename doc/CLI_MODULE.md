# SpringBootAI CLI 与项目脚手架 —— 使用指南

> 框架版本：SpringBootAI 2.3.0
> 源码位置：`spring/cli/main.py`、`spring/cli/scaffold.py`
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
| **创建新项目** | 手动建目录、写 `Application.py`、写 `application.yml`、写 `requirements.txt`... | `springbootai init my-project --modules web,orm` 一行搞定 |
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
| `springbootai` | `spring.main:run_cli` | 主命令，支持多个子命令（version/info/list/init/run/docs） |
| `springbootai-init` | `spring.cli.scaffold:main` | 独立的脚手架命令（等价于 `springbootai init`） |

> **对齐 Java**：本模块对齐 Java 的 [Spring Boot CLI](https://docs.spring.io/spring-boot/docs/current/reference/html/cli.html) 和 [Spring Initializr](https://start.spring.io/)。Spring Initializr 是 Web 界面的项目生成器，SpringBootAI 用命令行实现同样功能。

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
SpringBootAI v2.3.0
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
框架版本: 2.3.0
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
| `init` | `springbootai init <project> [options]` | 初始化新项目（类似 Spring Initializr） |
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
    init                初始化新项目（类似 Spring Initializr）
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

### 命令语法

```bash
springbootai init <project> [--package <name>] [--modules <list>] [--port <port>]
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project` | 位置参数 | 必填 | 项目名称或目标路径（如 `my-project` 或 `./my-project`） |
| `--package` / `-p` | 选项 | 从项目名派生 | Python 包名（连字符转下划线，小写） |
| `--modules` / `-m` | 选项 | `web` | 启用的模块，逗号分隔，支持 `web`/`orm`/`ai`/`cloud` |
| `--port` | 选项 | `8000` | 服务端口 |

**支持的模块：**

| 模块 | 生成的额外内容 | 对应配置段 |
|------|---------------|-----------|
| `web` | `controllers/` 目录 + 示例 `HelloController` | `server` 配置 |
| `orm` | `models/` 目录 + ORM 配置 | `spring.datasource` + `spring.jpa` 配置 |
| `ai` | AI 配置段 | `spring.ai` 配置 |
| `cloud` | Cloud 配置段 | `spring.cloud.nacos` 配置 |

### 创建新项目流程

#### 第一步：执行 init 命令

```bash
# 创建一个 web + orm 项目
springbootai init my-project --modules web,orm --port 9000
```

输出：

```
✅ Project 'my-project' created at: /home/user/my-project
   Package: my_project
   Modules: web, orm
   Port: 9000

   Next steps:
   1. cd my-project
   2. pip install -r requirements.txt
   3. python Application.py
```

#### 第二步：进入项目目录并安装依赖

```bash
cd my-project
pip install -r requirements.txt
```

#### 第三步：启动应用

```bash
python Application.py
```

访问 `http://localhost:9000/hello` 即可看到示例接口返回。

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
springbootai init my-project --package custom_pkg
```

> **包名校验**：包名必须是合法的 Python 标识符（`^[a-zA-Z_][a-zA-Z0-9_]*$`），否则会抛出 `ValueError`。

### 安全检查

脚手架会**拒绝覆盖已有非空目录**，防止误操作：

```bash
# 目录已存在且非空
springbootai init existing-project
# ❌ Error: Directory '/path/to/existing-project' already exists and is not empty. Refusing to overwrite.
```

如果需要在空目录中创建项目，可以：

```bash
mkdir my-project
springbootai init my-project
```

### 生成的项目结构

以 `springbootai init my-project --modules web,orm --port 9000` 为例：

```
my-project/
├── Application.py              # 启动类（含 @SpringBootApplication）
├── config/
│   └── application.yml         # 配置文件（含 server/database 配置）
├── requirements.txt            # 依赖清单
├── README.md                   # 项目说明
└── src/
    └── my_project/             # Python 包（从项目名派生）
        ├── __init__.py
        ├── controllers/        # 控制器目录（web 模块生成）
        │   └── __init__.py     # 含示例 HelloController
        └── models/             # 实体类目录（orm 模块生成）
            └── __init__.py
```

#### 各文件内容说明

**Application.py（启动类）：**

```python
"""my-project 启动类

自动生成于 SpringBootAI 2.3.0 脚手架。
运行：python Application.py
"""
import sys
import os

# 将 src/ 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from spring.annotations import SpringBootApplication
from my_project.controllers import *  # noqa: F401, F403


@SpringBootApplication
class Application:
    """应用启动入口"""

    @staticmethod
    def main():
        from spring.main import SpringApplication
        app = SpringApplication(Application)
        app.run()


if __name__ == '__main__':
    Application.main()
```

**config/application.yml（配置文件）：**

```yaml
# my-project 配置文件
# SpringBootAI 2.3.0

server:
  port: 9000
  host: 0.0.0.0

spring:
  application:
    name: my-project

# ORM 配置（orm 模块生成）
spring:
  datasource:
    url: sqlite:///app.db
    driver: sqlite
  jpa:
    ddl-auto:
      mode: update
    entity-packages:
      - my_project.models

# 日志配置
logging:
  level:
    root: INFO
    spring: DEBUG
```

**requirements.txt（依赖清单）：**

```
# my-project 依赖
# SpringBootAI 2.3.0
springbootAI==2.3.0
PyMySQL==1.2.0  # MySQL 驱动
```

> 依赖清单会根据启用的模块自动添加对应的额外依赖（如 `orm` 模块会加 `PyMySQL`）。

**src/my_project/controllers/__init__.py（示例控制器）：**

```python
"""my-project controllers"""

from spring.annotations import RestController, GetMapping


@RestController
class HelloController:
    """示例控制器"""

    @GetMapping("/hello")
    def hello(self):
        return {"message": "Hello from my-project!"}
```

**README.md（项目说明）：**

包含快速开始、项目结构、模块说明、相关文档链接。

### 不同模块组合的生成结果

| 模块组合 | 生成的目录 | 配置段 | requirements.txt 额外依赖 |
|----------|-----------|--------|--------------------------|
| `web` | `controllers/` | `server` | 无 |
| `orm` | `models/` | `spring.datasource` + `spring.jpa` | `PyMySQL==1.2.0` |
| `ai` | 无额外目录 | `spring.ai` | `langchain-openai==1.4.2` |
| `cloud` | 无额外目录 | `spring.cloud.nacos` | `redis==8.1.0` |
| `web,orm` | `controllers/` + `models/` | `server` + `spring.datasource` + `spring.jpa` | `PyMySQL==1.2.0` |

### 通过 Python 代码调用脚手架

除了命令行，也可以在 Python 代码中调用：

```python
from spring.cli.scaffold import create_project

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
from spring.cli.scaffold import main

# 命令行风格调用
main(['my-project', '--modules', 'web,orm', '--port', '9000'])
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
3. 读取文件内容并编译执行（`exec`）

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
springbootai init blog-system --modules web,orm,ai --port 8080
```

输出：

```
✅ Project 'blog-system' created at: /home/user/blog-system
   Package: blog_system
   Modules: web, orm, ai
   Port: 8080

   Next steps:
   1. cd blog-system
   2. pip install -r requirements.txt
   3. python Application.py
```

### 2. 进入项目并安装依赖

```bash
cd blog-system
pip install -r requirements.txt
```

`requirements.txt` 内容：

```
# blog-system 依赖
# SpringBootAI 2.3.0
springbootAI==2.3.0
PyMySQL==1.2.0  # MySQL 驱动
langchain-openai==1.4.2  # LangChain
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

from spring.annotations import RestController, GetMapping, PostMapping


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
from spring.orm import Entity, Id, Column


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
  level:
    root: INFO
    spring: DEBUG
```

### 7. 配置 Mapper 扫描

编辑 `Application.py`，添加 `@MapperScan`：

```python
"""blog-system 启动类"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from spring.annotations import SpringBootApplication
from spring.orm import MapperScan
from blog_system.controllers import *  # noqa: F401, F403


@SpringBootApplication(scan_base_packages=["blog_system"])
@MapperScan(base_packages=["blog_system.mapper"])
class Application:
    """应用启动入口"""

    @staticmethod
    def main():
        from spring.main import SpringApplication
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
| **交互方式** | Web 界面（start.spring.io）+ CLI | 命令行 |
| **创建项目命令** | `spring init --dependencies=web,jpa my-project` | `springbootai init my-project --modules web,orm` |
| **项目名** | `--name` 或 `--artifact-id` | 位置参数（项目名/路径） |
| **包名** | `--package-name`（Java 包名） | `--package`（Python 包名） |
| **模块选择** | `--dependencies=web,jpa,security` | `--modules=web,orm,ai,cloud` |
| **端口配置** | 无（在 application.properties 中配） | `--port`（生成时直接写入配置） |
| **生成构建文件** | `pom.xml` / `build.gradle` | `requirements.txt` |
| **生成启动类** | `Application.java`（含 `@SpringBootApplication`） | `Application.py`（含 `@SpringBootApplication`） |
| **生成配置文件** | `application.properties` | `application.yml` |
| **生成 README** | 否 | 是（`README.md`） |
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
# 命令行
springbootai init my-project \
  --modules web,orm \
  --package com_example
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
└── src/
    └── my_project/                  # Python 包
        ├── __init__.py
        ├── controllers/             # 控制器（对应 java/.../controller/）
        └── models/                  # 实体（对应 java/.../entity/）
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

A: 当前支持 4 个模块：`web`、`orm`、`ai`、`cloud`。可以任意组合，用逗号分隔：

```bash
springbootai init my-app --modules web,orm,ai,cloud
```

不支持的模块名会报错：`Invalid module: 'xxx'. Supported modules: {'web', 'orm', 'ai', 'cloud'}`

**Q3: 生成的项目端口怎么改？**

A: 两种方式：
1. 创建时指定：`springbootai init my-app --port 9000`
2. 创建后修改 `config/application.yml` 中的 `server.port`

**Q4: 包名能包含连字符吗？**

A: 不能。Python 包名必须是合法标识符（只能含字母、数字、下划线，不能以数字开头）。脚手架会自动把项目名中的连字符转为下划线：

- 项目名 `my-project` → 包名 `my_project`

也可以手动指定：`springbootai init my-project --package my_pkg`

**Q5: 能在已有项目里追加模块吗？**

A: 不能直接追加。`init` 命令是创建新项目的，不支持修改已有项目。如果想在已有项目里加模块：
1. 手动创建对应目录（如 `models/`）
2. 手动在 `application.yml` 中添加配置段
3. 手动在 `requirements.txt` 中添加依赖

**Q6: `springbootai run` 和 `python Application.py` 有什么区别？**

A: 功能等价。`springbootai run` 会自动把应用文件所在目录加入 `sys.path`，方便导入同目录模块。两者都启动应用，效果相同。

**Q7: 生成的 `Application.py` 里的 `sys.path.insert` 是干什么的？**

A: 把项目的 `src/` 目录加入 Python 路径，这样 `from my_project.controllers import *` 才能正确导入。因为脚手架把 Python 包放在 `src/` 下（类似 Java 的 `src/main/java/` 结构），需要告诉 Python 去哪里找包。

**Q8: `springbootai docs` 生成文档失败怎么办？**

A: 排查步骤：
1. 确认已安装 Sphinx：`pip install sphinx`
2. 确认 `docs/` 目录存在且有 `conf.py` 配置文件
3. 查看 Sphinx 构建错误信息（会输出到 stderr）
4. 如果没有 `conf.py`，先初始化：`sphinx-quickstart docs`

**Q9: 脚手架生成的项目能直接部署到生产吗？**

A: 生成的项目是**开发模板**，可以直接用于开发，但生产部署前建议：
1. 修改 `application.yml` 中的数据库密码（不要硬编码）
2. 把 `logging.level.spring` 从 `DEBUG` 改为 `INFO`
3. 在 `requirements.txt` 中锁定所有依赖版本
4. 添加 `.gitignore`（排除 `__pycache__`、`.env`、`*.db` 等）
5. 添加 Dockerfile 和 CI 配置

**Q10: `springbootai-init` 和 `springbootai init` 有什么区别？**

A: 功能完全相同，是两个独立的命令入口：
- `springbootai init <project>` —— 主命令的子命令
- `springbootai-init <project>` —— 独立的命令

两者底层都调用 `spring.cli.scaffold.main()`，生成相同的项目结构。用哪个都行，`springbootai init` 更符合统一命令风格。

**Q11: 如何查看脚手架生成的模板源码？**

A: 模板定义在 `spring/cli/scaffold.py` 的顶部（`_APPLICATION_TEMPLATE`、`_APPLICATION_YML_TEMPLATE` 等变量）。如果你想自定义模板，可以直接修改这些字符串。

**Q12: 生成的 README.md 里有什么？**

A: 包含：
- 项目名称和框架版本
- 快速开始（安装依赖、启动应用）
- 项目结构说明
- 启用的模块列表
- SpringBootAI 文档链接

---

## 改进记录

### v2.3.0 — CLI 完善

- `init` 命令支持 `--port` 参数，生成时直接写入配置
- `info` 命令新增 MCP、LangGraph 等依赖检测
- `list modules` 新增 batch、csv、scheduling 等模块
- 脚手架生成的 `application.yml` 支持多模块配置段

### v2.0.0 — CLI 引入

- 新增 `springbootai` 主命令，支持 version/info/list/init/run/docs 子命令
- 新增 `springbootai-init` 独立脚手架命令
- 对齐 Java Spring Initializr 的项目生成能力
