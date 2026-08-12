# SpringBootAI 新手入门指南

> **如果你对编程完全不熟悉**：可以把 SpringBootAI 想象成一个"网站后台工厂"。你告诉它"我需要一个能返回用户信息的网页接口"，它就会自动帮你把接收请求、处理数据、返回结果这一整套流程跑起来。这份文档带你从零开始，一步步搭建出你的第一个网站接口。

---

## 速查表：我想做 XX → 用 YY 注解 → 放在 ZZ 文件

| 我想做什么 | 用什么注解 | 放在哪种文件里 |
|---|---|---|
| 写一个网页接口，别人访问时返回数据 | `@RestController` + `@GetMapping` | `controller/XxxController.py` |
| 写业务逻辑（如计算价格、检查库存） | `@Service` | `service/XxxService.py` |
| 读写数据库 | `@Mapper` + `@Select` / `@Insert` | `mappers/XxxMapper.py` |
| 让框架自动把 Service 传给 Controller 使用 | `@Autowired`（写在 `__init__` 上） | Controller 的构造方法 |
| 校验用户输入不能为空 | `NotBlank` 注解 + `@BeanValidate` | 请求参数模型类 |
| 给接口分组，在 Swagger 页面展示 | `@Tag` + `@Operation` | Controller 类和方法 |
| 控制谁能访问接口（登录、权限） | `@Authenticate` + `@PreAuthorize` | Controller 方法 |
| 缓存查询结果，不用每次都查数据库 | `@Cacheable` | Service 方法 |
| 限制接口被调用的频率 | `@RateLimit` | Controller 或 Service 方法 |
| 自动重试失败的操作 | `@Retryable` | Service 方法 |

---

## 1. 这个框架是做什么的

**解决什么问题**：你想写一个网站后端（提供接口给前端网页或 App 调用），但从零搭建太麻烦。SpringBootAI 把最常见的功能都打包好了，你只需要像搭积木一样用"注解"声明你需要什么能力。

SpringBootAI 是一个 Python Web 框架。它把常见的后端功能放在同一个编程模型里：

| 你想做的事 | 使用的模块 | 最常见入口 |
|---|---|---|
| 提供 HTTP 接口（大白话：让别人通过网址访问你的程序） | Web MVC | `@RestController`、`@GetMapping`、`@PostMapping` |
| 把业务代码分层（大白话：接单的、做菜的、管仓库的各干各的） | IoC/DI | `@Service`、`@Repository`、`@Autowired` |
| 读写数据库 | PyMyBatis ORM | `@Mapper`、`@Select`、`@Transactional` |
| 校验请求数据（大白话：检查用户填的表单合不合规矩） | Bean Validation | `NotBlank`、`Min`、`@BeanValidate` |
| 登录和权限控制 | Security | JWT、`@Authenticate`、`@PreAuthorize` |
| 缓存、重试、限流（大白话：记住结果下次直接用、失败了再试、控制访问频率） | AOP | `@Cacheable`、`@Retryable`、`@RateLimit` |
| 服务注册和远程调用 | Cloud | Nacos、Feign、Gateway、Sentinel |
| 自动生成接口文档 | Swagger/OpenAPI | `@Tag`、`@Operation`、`/docs` |
| 调用大模型或做知识库问答 | AI | `ChatClient`、Advisor、RAG、Tools |

> **🍽️ 餐厅比喻（帮你记住这几个角色）**：
> - **Controller（前台服务员）**：客人进门，服务员接单。它不炒菜，只负责把菜单传给后厨，再把做好的菜端给客人。
> - **Service（后厨大厨）**：服务员把单子递进来，大厨开始炒菜。他决定怎么做这道菜——先放什么、后放什么、火候多大。服务员不用管这些。
> - **Mapper/Repository（仓库管理员）**：厨师要从仓库拿食材，但他不用亲自去翻箱子。他告诉仓管员"给我拿2斤鸡肉"，仓管员知道东西在哪、怎么取。
> - **IoC 容器（自动雇人系统）**：你开餐厅，不用自己去人才市场招人。你只要在门口贴招聘启事（加个注解），这个自动 HR 系统就帮你把服务员、厨师、仓管员招来，安排工位，分配搭档。
> - **@Autowired（自动搭档分配）**：厨师说"我需要一个仓管员配合我"，HR 系统就自动把仓管员分配给他。你不用自己跑仓库去找人。

框架的名称和分层方式参考了 Java 的 Spring Boot，但运行的时候是 Python + FastAPI + Uvicorn。Java 的 JAR 包、Maven 插件、Java Bean 不能直接在这里用。

---

## 2. 先认识五个核心概念

### 2.1 Controller（🍽️ 前台服务员——接收请求、返回结果）

**解决什么问题**：你想让浏览器或 App 能访问你的程序，需要一个"大门"来接收 HTTP 请求并返回数据。

Controller 就是这扇大门。它接收请求，然后转交给 Service（厨师）去干活，最后把结果返回给请求方。**Controller 自己不干重活，它只负责接单和传菜。**

### 2.2 Service（🍽️ 后厨大厨——处理业务逻辑）

**解决什么问题**：你的业务逻辑越来越多（"创建订单前要检查库存""注册时发送验证邮件"），如果全塞在 Controller 里，代码会乱成一锅粥。

Service 把"怎么做事情"从"谁在接单"里分离出来。Controller 收到请求后，告诉 Service 要做什么，Service 自己去完成。这样做的好处：如果换一个厨师，也能做出同样的菜——代码更容易维护和测试。

### 2.3 Mapper / Repository（🍽️ 仓库管理员——读写数据库）

**解决什么问题**：你需要从数据库存取数据，但不想在每个地方都写一大串 SQL 连接代码。

Mapper 帮你把"查数据库"这件事简化成"调用一个方法"。就像厨师告诉仓管员"给我拿2斤鸡肉"，不用自己翻仓库一样。

### 2.4 Bean 和 IoC 容器（🍽️ 自动雇人系统 + 员工花名册）

**解决什么问题**：如果每个类都要你自己 `new` 出来，再手动传给需要它的地方，代码会变成一团乱麻。IoC 容器帮你自动完成"创建对象"和"传递对象"这些脏活累活。

被 `@Controller`、`@Service`、`@Repository`、`@Component` 标记的类，框架启动时会自动扫描到，创建好实例（这些实例就叫"Bean"），然后放进一个"大池子"（容器）里统一管理。

> **⚠️ 新手最容易踩的坑**：
> - ❌ 错误："我用 `UserService()` 自己创建了一个对象，为什么 `@Transactional` 注解不生效？"
> - ✅ 正解：容器创建的 Bean 才是"正式员工"，有事务、缓存这些"福利"。你自己 `new` 出来的是"临时工"，什么福利都没有。**永远通过 `@Autowired` 让容器给你对象，不要自己 `new`。**

### 2.5 注解（🍽️ 贴在员工工牌上的便利贴标签）

**解决什么问题**：你想告诉框架"这个类是干什么的""这个方法需要什么特殊能力"，但又不想写一堆配置文件。

Python 中的"注解"实际是装饰器。你在类或方法上面写 `@Service`、`@GetMapping("/users")` 这些标签，框架启动时看到标签就知道：

- 贴了 `@Service` 的 → 这是厨师，要管起来
- 贴了 `@RestController` 的 → 这是服务员，注册到前台
- 贴了 `@GetMapping("/hello")` 的 → 有人访问 `/hello` 时执行这个方法

---

## 3. 我该用什么编辑器

推荐使用 **VS Code**（完全免费），配合以下插件：

1. **Python 插件**（微软官方）：代码提示、自动补全、错误检查
2. **Pylance**：更强的 Python 语言支持
3. **YAML 插件**（红帽）：写 `application.yml` 配置文件时的语法高亮

**安装步骤**：

1. 从 [https://code.visualstudio.com/](https://code.visualstudio.com/) 下载 VS Code
2. 打开 VS Code，点击左侧扩展图标（四个方块）
3. 搜索并安装上面三个插件
4. 重启 VS Code

> 如果你已经习惯 PyCharm 或其他编辑器，也完全可以。只要支持 Python 语法高亮就行。

---

## 4. 快速开始：6 步跑通第一个接口

> **📌 这一节的目标**：从安装框架开始，到最后用浏览器看到返回的 JSON 数据。全部代码可以直接复制粘贴，不需要改动任何地方。预计耗时：5 分钟。

### 第 1 步：检查 Python 环境

你的电脑需要 Python 3.10 或更高版本。打开终端（PowerShell），输入：

```powershell
python --version
# 你看到的输出应该类似：Python 3.10.x 或 Python 3.11.x 或 Python 3.12.x
```

如果提示"找不到 python"，说明还没有安装 Python。请去 [https://www.python.org/downloads/](https://www.python.org/downloads/) 下载安装，安装时**一定要勾选"Add Python to PATH"**。

### 第 2 步：创建项目文件夹并安装框架

在终端中依次执行以下命令（一行一行来）：

```powershell
# 1. 创建项目文件夹并进入
mkdir my-first-app
cd my-first-app

# 2. 创建虚拟环境（给这个项目一个隔离的 Python 环境，不会弄乱电脑上的其他项目）
python -m venv .venv

# 3. 激活虚拟环境（Windows PowerShell）
.\.venv\Scripts\Activate.ps1
# 看到命令行前面出现 (.venv) 就说明激活成功了

# 如果你是 Linux 或 macOS，激活命令是：
# source .venv/bin/activate

# 4. 升级 pip（Python 的包管理工具）
python -m pip install --upgrade pip

# 5. 安装 SpringBootAI 框架
python -m pip install springbootAI
# 看到 "Successfully installed springbootAI-x.x.x" 就说明安装成功
```

### 第 3 步：创建项目文件

在 `my-first-app` 文件夹里，创建以下文件结构（`__init__.py` 必须是空文件，但不能省略）：

```text
my-first-app/
|-- demo/
|   |-- __init__.py          （空文件，必须有）
|   |-- Application.py       （启动类）
|   |-- application.yml      （配置文件）
|   `-- controller/
|       |-- __init__.py      （空文件，必须有）
|       `-- HelloController.py  （接口文件）
```

**你可以直接在文件管理器里创建这些文件夹和文件**。或者用 VS Code 打开 `my-first-app` 文件夹，在左侧文件树中右键创建。

### 第 4 步：填写代码（以下三份代码可直接复制粘贴）

**文件 1：`demo/Application.py`**（启动类——程序的入口）

```python
# 导入框架提供的"启动应用"注解和运行函数
from spring.annotations import SpringBootApplication
from spring.main import run


# @SpringBootApplication 告诉框架："这是一个 SpringBootAI 应用"
# scan_base_packages 告诉框架："去 demo 这个包里找 Controller、Service 等组件"
@SpringBootApplication(scan_base_packages=["demo"])
class Application:
    pass


# 这是 Python 的标准写法：当直接运行这个文件时，启动应用
if __name__ == "__main__":
    run(Application)
# 启动后控制台会输出：Uvicorn running on http://127.0.0.1:8080
```

**文件 2：`demo/controller/HelloController.py`**（接口——处理用户请求）

```python
# 导入需要的注解
from spring.annotations import GetMapping, RequestMapping, RestController
from spring.web.swagger import Operation, Tag


# @Tag 在 Swagger 文档页面上给这组接口起个名字
# @RequestMapping 把这组接口的网址都加上 /api 前缀
# @RestController 告诉框架：这是一个 Controller（前台服务员）
@Tag(name="入门接口", description="用于确认项目已经正常启动")
@RequestMapping("/api")
@RestController
class HelloController:

    # @Operation 在 Swagger 页面上说明这个接口是干什么的
    # @GetMapping 表示：当有人用 GET 方式访问 /api/hello/某个名字 时，执行这个方法
    # {name} 是路径中的变量——写成 /hello/Alice，方法里的 name 就是 "Alice"
    @Operation(summary="打招呼", description="把路径中的名字放进欢迎语")
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
# 访问示例：GET /api/hello/Alice → 返回 {"code":200,"message":"success","data":{"message":"Hello, Alice"}}
```

**文件 3：`demo/application.yml`**（配置文件——设置端口和开关）

```yaml
# 服务器设置：监听哪个 IP 和端口
server:
  host: 127.0.0.1
  port: 8080

# 先用最简单的模式：关掉数据库和 Redis（后面需要时再打开）
redis:
  enabled: false

database:
  enabled: false

# JWT 设置：登录功能需要用到，先设个开发用的临时值
jwt:
  secret_key: development-only-secret
  algorithm: HS256
```

### 第 5 步：启动应用

**在终端中，确保你在 `my-first-app` 目录下**（就是 `demo/` 文件夹的父目录），然后运行：

```powershell
python -m demo.Application
```

> **⚠️ 这一步最容易出错！**
> - ✅ 正确的做法：在 `my-first-app/` 目录下，运行 `python -m demo.Application`
> - ❌ 错误：进入 `demo/` 目录里运行 `python Application.py`——这样会报 `ModuleNotFoundError`
>
> 简单记忆：**你要站在 `demo` 文件夹的外面，用 `-m` 模块方式来运行它。**

看到类似下面的输出，说明启动成功：

```
Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

### 第 6 步：验证接口

**保持第一个终端运行**（不要关掉），打开第二个终端：

```powershell
# 测试打招呼接口
curl http://127.0.0.1:8080/api/hello/Alice
# 返回：{"code":200,"message":"success","data":{"message":"Hello, Alice"}}

# 测试健康检查接口
curl http://127.0.0.1:8080/actuator/health/liveness
# 返回：{"status":"UP"}
```

**或者直接用浏览器打开：**

- `http://127.0.0.1:8080/api/hello/小白` → 浏览器显示 JSON 数据
- `http://127.0.0.1:8080/docs` → Swagger 文档页面（网页版的"接口说明书"，你可以在上面直接点击"Try it out"测试接口）

> 🎉 恭喜！你已经成功跑通了第一个 SpringBootAI 接口！

---

## 5. 加入 Service 和依赖注入

**本节概要**：当业务逻辑变复杂时（比如打招呼前要记录日志、检查黑名单），把所有代码写在 Controller 里会越来越乱。这一节教你用 Service 把"怎么做"从"接单"里分出来。

> 🍽️ **比喻**：还记得餐厅的故事吗？现在我们的餐厅要升级——前台服务员（Controller）不再自己说"Hello"，而是把客户的名字递给后厨大厨（Service），大厨负责组织欢迎语。`@Autowired` 就是让 HR 系统自动把大厨派给服务员做搭档。

```python
# 文件：demo/controller/GreetingController.py
# 把下面整段代码复制替换你之前的 HelloController.py，或者新建一个文件

# ---------- 以下是完整可运行代码，可直接复制粘贴 ----------

from spring.annotations import Autowired, GetMapping, RequestMapping, RestController, Service


# Service = 后厨大厨，负责"怎么做"
@Service
class GreetingService:
    """打招呼服务：负责生成欢迎语"""
    def build_message(self, name: str) -> str:
        # 这里可以加更多逻辑：检查黑名单、记录日志、翻译名字等
        return f"Hello, {name}"


# RestController = 前台服务员，负责"接单和返回"
@RequestMapping("/api")
@RestController
class GreetingController:
    # @Autowired 告诉容器："我需要一个 GreetingService，帮我自动传进来"
    # 你不用自己写 greeting_service = GreetingService()
    @Autowired
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service

    @GetMapping("/greeting/{name}")
    def greeting(self, name: str):
        # 把活儿交给 Service 去做
        message = self.greeting_service.build_message(name)
        return {"message": message}

# ---------- 以上是完整可运行代码 ----------

# 重新启动应用后测试：
# curl http://127.0.0.1:8080/api/greeting/小白
# 返回：{"code":200,"message":"success","data":{"message":"Hello, 小白"}}
```

**验证**：重新运行 `python -m demo.Application`，然后访问 `http://127.0.0.1:8080/api/greeting/小白`，看到返回的欢迎信息就说明 Controller 成功调用了 Service。

> **⚠️ 新手常见错误**：
> - ❌ 错误：在 Controller 里写 `self.greeting_service = GreetingService()`，然后问"为什么 `@Cacheable` 不生效？"
> - ✅ 正解：只有通过 `@Autowired` 让容器给你创建的对象，才有缓存、事务等 AOP 能力。你自己 `new` 出来的对象只是普通 Python 对象。

---

## 6. 按需求选择下一份文档

**本节概要**：你不用从第一章读到最后一章。根据你当前的任务，直接跳到对应的文档。

| 当前任务 | 下一步阅读 |
|---|---|
| 做普通 CRUD 接口（大白话：增删改查） | [README Web 章节](../README.md#7-web-控制器) + [ORM 指南](ORM_MODULE.md) |
| 校验用户输入、条件装配、缓存更新 | [常用注解模块指南](ANNOTATION_MODULES.md) |
| 统一记录方法日志、返回后鉴权、重试失败兜底 | [AOP / 后置鉴权 / 重试恢复指南](AOP_SECURITY_RETRY.md) |
| 登录、JWT、角色权限 | [安全指南](SECURITY.md) |
| 自动生成 Swagger 文档 | [Swagger 指南](SWAGGER_MODULE.md) |
| 导入导出 Excel | [Excel 指南](EXCEL_MODULE.md) |
| 导入导出 CSV | [CSV 指南](CSV_MODULE.md) |
| 服务发现、Feign、网关、事务补偿 | [Cloud 指南](CLOUD_MODULE.md) |
| 大模型、知识库、工具调用 | [AI 指南](AI_MODULE.md) |
| 分页、Actuator、多数据源、i18n、WebSocket | [八大模块指南](EIGHT_MODULES.md) |

> **建议路线**：大多数新手按这个顺序最高效 → **本文** → **README 第 4/6/7 章** → **ORM_MODULE.md** → 按需查阅其他文档。

---

## 7. 配置文件怎么理解

**本节概要**：你不该把端口号、数据库密码这些写死在代码里。配置文件让你随时改设置，不用重新改代码。

> 🍽️ **比喻**：配置文件就像餐厅的"运营手册"——写着餐厅开在哪条街（`host`）、几号门（`port`）、要不要开外卖（`redis.enabled`）。换一个地方开店，改手册就行，不用重新装修。

### 7.1 基本语法

`application.yml` 是项目的主配置文件。`${变量名:默认值}` 的意思是：先看有没有设置环境变量，没设置就用冒号后面的默认值。

```yaml
# 示例：端口号先从环境变量 SERVER_PORT 读取，没读到就用 8080
server:
  port: ${SERVER_PORT:8080}
```

### 7.2 怎么临时改端口

在 PowerShell 中：

```powershell
# 设置环境变量
$env:SERVER_PORT='9000'
# 启动应用（这次启动会使用 9000 端口）
python -m demo.Application
# 输出：Uvicorn running on http://127.0.0.1:9000
```

### 7.3 常用开关一览

| 配置 | 什么时候打开 | 还需要准备什么 |
|---|---|---|
| `database.enabled` | 需要数据库时 | 数据库地址、账号、密码 |
| `redis.enabled` | 需要缓存、分布式锁或限流时 | 一个可用的 Redis 服务 |
| `rabbitmq.enabled` | 需要消息队列时 | RabbitMQ 服务和队列 |
| `discovery.enabled` | 需要 Nacos 服务注册发现时 | Nacos 服务 |
| `seata.enabled` | 需要分布式事务协调时 | Seata 服务 |
| `prometheus.enabled` | 需要指标监控时 | Prometheus 服务 |

完整配置项请查看仓库根目录的 [`application.yml`](../application.yml)。

> **⚠️ 新手常见错误**：
> - ❌ 错误："我改了 YAML 文件里的配置，重新请求接口怎么没生效？"
> - ✅ 正解：修改 YAML 后需要**重启应用**才能生效（按 `Ctrl+C` 停掉，再重新运行）。YAML 配置是在启动时一次性读取的，不是运行时动态刷新。

---

## 8. 开发 vs 生产：有什么区别

**本节概要**：你自己电脑上写代码时的配置（SQLite、弱密码），绝对不能原封不动搬到线上服务器。这一节告诉你哪些必须改。

| 方面 | 自己电脑（开发） | 线上服务器（生产） |
|---|---|---|
| 数据库 | SQLite（文件数据库，不用装服务） | MySQL / PostgreSQL（专业的数据库服务） |
| JWT 密钥 | 可以用简单的开发密钥 | 必须用至少 32 字符的随机密钥，从环境变量注入 |
| CORS | 可以允许所有来源 | 必须限制具体的前端域名 |
| 启动方式 | `python -m demo.Application` | `uvicorn asgi:app --workers 4` |
| 日志 | 打印到控制台就行 | 输出到文件，配合监控告警 |

生产环境的 ASGI 入口示例：

```python
# 文件：asgi.py（放在项目根目录）
from spring.main import create_app
from demo.Application import Application

# create_app 生成一个 ASGI 应用对象，交给 uvicorn 管理
app = create_app(Application)
```

```powershell
# 生产环境启动命令：4 个 worker 进程，监听所有网卡的 8080 端口
uvicorn asgi:app --host 0.0.0.0 --port 8080 --workers 4
```

> **⚠️ 新手常见错误**：
> - ❌ 错误："开发时跑通了，生产环境直接部署就行。"
> - ✅ 正解：开发用 SQLite、生产用 MySQL，两者行为不完全一样。上线前必须在目标数据库上重新测试一遍。

---

## 9. 新手常见错误速查表

**本节概要**：报错了不要慌——这里列了最常见的 5 个错误，大概率能帮你快速找到原因。

### 五大高频错误

| 排名 | 你看到的错误 | 最可能的原因 | 怎么解决 |
|---|---|---|---|
| **1** | `ModuleNotFoundError: No module named 'spring'` | 虚拟环境没激活，或者安装没成功 | 先激活 `.venv`，再 `pip install springbootAI`，最后用 `python -c "import spring; print(spring.__version__)"` 验证 |
| **2** | Controller 写好了但 `/docs` 里看不到 | 包目录缺 `__init__.py`，或 `scan_base_packages` 没包含那个包 | 检查每个目录是否有 `__init__.py`（可以为空但必须有），确认 `scan_base_packages` 里写了正确的包名 |
| **3** | `@Transactional` 或 `@Cacheable` 不生效 | 对象是手动 `ClassName()` 创建的，不是容器给的 | 改用 `@Autowired` 构造器注入获取对象，不要自己 `new` |
| **4** | `Address already in use`（端口被占用） | 8080 端口被上次没关的进程占着 | 改端口：`$env:SERVER_PORT='9000'`；或者用 `netstat -ano | findstr 8080` 找到占用进程并关掉 |
| **5** | `python -m demo.Application` 报找不到模块 | 你不在正确的目录 | `cd` 到 `demo/` 的**外面那层**（项目根目录）再执行命令 |

### 其他常见问题

| 你看到的现象 | 最可能的原因 | 怎么处理 |
|---|---|---|
| 数据库连不上 | 驱动、地址、账号或密码错了 | 先用数据库客户端工具验证能连上，再启动应用 |
| Swagger 页面空白 | Controller 没被扫描到，或 Swagger 被关了 | 先访问 `/openapi.json` 看看有没有内容，再检查启动日志 |
| Redis 功能不工作 | Redis 没开（`enabled: false`） | 去配置文件里把 `redis.enabled` 设为 `true`，并填入正确的 Redis 地址 |

---

## 10. 卡住了怎么办？（排查流程图）

```
你遇到了一个报错
    │
    ├─→ 1. 先看启动日志中 [ERROR] 和 [WARNING] 开头的行
    │       ↓ 找到原因了？ → ✅ 解决
    │       ↓ 没找到？
    │
    ├─→ 2. 简化到最小用例：关掉数据库和 Redis（都设 false），
    │      只保留一个最简单的 Controller，看能不能跑通
    │       ↓ 能跑通了？ → 说明是后来加的功能出问题，逐一排查
    │       ↓ 还是跑不通？
    │
    ├─→ 3. 确认你当前所在的目录
    │       PowerShell: Get-Location   Linux/Mac: pwd
    │       应该在 demo/ 的外面那层（项目根目录）
    │       ↓ 目录不对？ → cd 到正确位置
    │       ↓ 目录正确？
    │
    ├─→ 4. 重新安装框架
    │       pip install springbootAI --force-reinstall
    │       ↓ 还不行？
    │
    └─→ 5. 去社区/同事那里求助，记得带上以下信息：
           ① Python 版本：python --version
           ② 框架版本：python -c "import spring; print(spring.__version__)"
           ③ 完整的错误信息（从 Traceback 第一个字到最后一行）
           ④ 你执行了什么命令
           ⑤ demo/ 下面有什么文件
```

---

## 11. 怎么确认一个功能真的生效了

**本节概要**：启动不报错 ≠ 功能正常。每个功能都需要用具体方式来验证。

| 功能 | 最小验证方法 |
|---|---|
| Web 路由 | `curl` 返回正确的状态码和 JSON |
| Swagger 文档 | 浏览器打开 `/docs` 能看到你的接口 |
| Bean 注入 | 接口能正常调用 Service（返回正确数据） |
| 数据库读写 | 去数据库里查询，确实有新增或更新的数据 |
| 事务回滚 | 故意抛异常，确认数据没有被写入数据库 |
| 缓存 | 连续请求两次，确认第二次没有重复执行方法（看日志） |
| 权限控制 | 分别用：没 token、错误角色、正确角色 访问接口 |
| 限流 | 快速连续请求，确认超出限制后返回错误 |

---

## 12. 新手常见问题 FAQ

### Q1：Python 和 Java 的 Spring Boot 有什么关系？
A：SpringBootAI 借鉴了 Spring Boot 的"注解 + 分层"思想，让你用熟悉的 `@Service`、`@RestController` 这些标签来写 Python 代码。但底层运行的是 Python + FastAPI，不是 Java。你不能把 Java 的 JAR 包直接拿过来用。

### Q2：我是 Python 新手，需要先学什么？
A：至少要了解：① Python 基本语法（变量、函数、类）；② 装饰器是什么（`@xxx` 这种写法）；③ 什么是虚拟环境（`.venv`）。如果你能写一个简单的 Python 类，就能用这个框架。

### Q3：`@Autowired` 和我自己 `ClassName()` 创建对象有什么区别？
A：容器创建的对象是"正式员工"——有事务支持、能做缓存、能拦截重试。你自己 `new` 出来的是"临时工"——就是普通 Python 对象，这些额外能力全都没有。

### Q4：配置文件改了为什么没生效？
A：YAML 配置是启动时一次性读取的。修改后必须重启应用（`Ctrl+C` 停掉再重新运行）。

### Q5：`__init__.py` 是干什么的？为什么每个目录都要有？
A：`__init__.py` 告诉 Python"这个目录是一个包（package）"。没有它，Python 就找不到目录里的模块。**文件内容可以为空，但文件本身不能省略。**

### Q6：启动时一定要用 `python -m demo.Application` 吗？不能直接 `python demo/Application.py` 吗？
A：不能用后者。`-m` 模块方式能让 Python 正确解析包路径，框架的组件扫描依赖于正确的包结构。用 `-m` 方式，并且要站在 `demo/` 的父目录执行。

### Q7：框架支持 WebSocket 吗？
A：支持。详见 [八大模块指南](EIGHT_MODULES.md) 的 WebSocket 章节。

---

## 13. 接下来看什么

你已经跑通了第一个接口，接下来根据你的目标选择：

| 如果你想... | 推荐阅读 | 预计时间 |
|---|---|---|
| 全面了解框架有哪些能力 | [README 综合指南](../README.md) | 30 分钟浏览 |
| 开始写增删改查接口 | [ORM 模块指南](ORM_MODULE.md) | 20 分钟 |
| 校验用户输入（必填、长度、格式） | [常用注解模块指南](ANNOTATION_MODULES.md) 的 Bean Validation 章节 | 10 分钟 |
| 加上登录和权限控制 | [安全指南](SECURITY.md) | 20 分钟 |
| 让 Swagger 文档更漂亮 | [Swagger 指南](SWAGGER_MODULE.md) | 10 分钟 |
| 对接大模型/AI | [AI 指南](AI_MODULE.md) | 30 分钟 |
| 了解 Java 开发者怎么迁移过来 | [README 第 13 章](../README.md#13-java-开发者看这里) | 按需查阅 |

> 🎯 **推荐路线**：本文 → [README 第 4/6/7 章](../README.md)（配置、IoC、Web）→ [ORM_MODULE.md](ORM_MODULE.md)（数据库）→ 按需查阅其他文档。
