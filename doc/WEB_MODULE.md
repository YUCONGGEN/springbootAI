# SpringBootAI Web MVC 模块指南

> SpringBootAI 2.3.11

---

## Web MVC 是什么？

**Web MVC = 把 Python 函数变成 HTTP 接口。** 就像给方法装上"门牌号"——客户端访问某个 URL，框架自动找到对应的方法执行，把结果转成 JSON 返回。你只需要关心业务逻辑，不用手写路由分发、参数解析、JSON 序列化。

本文覆盖 5 组共 17 个注解：控制器声明、路由映射、参数绑定、跨域控制、全局异常处理。

### 注解速查表

| 注解 | 一句话作用 | 写在哪 |
|------|----------|--------|
| `@RestController` | 声明 REST 控制器（返回值自动转 JSON） | 类上 |
| `@Controller` | 声明 MVC 控制器（返回视图名） | 类上 |
| `@RequestMapping` | 通用路由映射（指定 path 和 method） | 类/方法 |
| `@GetMapping` | GET 请求映射 | 方法 |
| `@PostMapping` | POST 请求映射 | 方法 |
| `@PutMapping` | PUT 请求映射 | 方法 |
| `@PatchMapping` | PATCH 请求映射 | 方法 |
| `@DeleteMapping` | DELETE 请求映射 | 方法 |
| `@RequestParam` | 绑定查询参数 / 表单字段 | 参数 |
| `@PathVariable` | 绑定 URL 路径变量 | 参数 |
| `@RequestBody` | 绑定请求体 JSON | 参数 |
| `@RequestPart` / `@FileUpload` | 绑定 `multipart/form-data` 文件 | 参数 |
| `@RequestHeader` | 绑定请求头 | 参数 |
| `@CookieValue` | 绑定 Cookie 值 | 参数 |
| `@CrossOrigin` | 跨域资源共享配置 | 类/方法 |
| `@ResponseStatus` | 设置响应状态码 | 方法 |
| `@ControllerAdvice` | 全局异常处理容器 | 类上 |
| `@ExceptionHandler` | 声明异常处理方法 | 方法 |

### 决策指引：我想做什么该看哪节？

| 我想做的事 | 看哪节 |
|-----------|--------|
| 写一个返回 JSON 的 REST API | [1. 控制器声明](#1-控制器声明) |
| 把 URL 映射到方法 | [2. 路由映射](#2-路由映射) |
| 从请求中拿参数（query/path/body/header/cookie） | [3. 参数绑定](#3-参数绑定) |
| 配置跨域访问 | [4. 跨域控制](#4-跨域控制) |
| 统一处理异常，返回友好错误 | [5. 全局异常处理](#5-全局异常处理) |

---

## 1. 控制器声明

### 是什么？

**`@RestController` = 返回值自动转 JSON。** 就像快递员——你给他什么，他自动打包成标准包裹（JSON）送给客户端。

**`@Controller` = 返回视图名。** 适合服务端渲染场景（返回 HTML 模板名）。REST API 用 `@RestController` 即可。

### 怎么用？

```python
from springbootai.annotations import RestController, GetMapping


@RestController
class UserController:
    """返回值自动序列化为 JSON"""

    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "张三"}  # 自动转 JSON
```

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| 用 `@Controller` 写 API，返回 dict 不转 JSON | API 用 `@RestController`；`@Controller` 返回视图名 |
| 忘记加 `@RestController`，类不被扫描 | 控制器类必须标注 `@RestController` 或 `@Controller` |

---

## 2. 路由映射

### 是什么？

**路由映射 = 给方法分配 URL 地址。** 就像门牌号——客户端访问 `/users/1`，框架自动找到对应方法执行。

### 路由注解速查表

| 注解 | HTTP 方法 | 典型场景 |
|------|----------|---------|
| `@GetMapping` | GET | 查询资源 |
| `@PostMapping` | POST | 创建资源 |
| `@PutMapping` | PUT | 全量更新资源 |
| `@PatchMapping` | PATCH | 部分更新资源 |
| `@DeleteMapping` | DELETE | 删除资源 |
| `@RequestMapping` | 任意（可指定） | 通用映射，或类级别前缀 |

### 怎么用？

**场景一：方法级别映射**

```python
from springbootai.annotations import RestController, GetMapping, PostMapping


@RestController
@RequestMapping("/api/v1")  # 类级别前缀，所有方法路径都会加上这个前缀
class UserController:

    @GetMapping("/users")          # GET /api/v1/users
    def list_users(self):
        return [{"id": 1}, {"id": 2}]

    @PostMapping("/users")         # POST /api/v1/users
    def create_user(self):
        return {"id": 100, "msg": "created"}

    @GetMapping("/users/{id}")     # GET /api/v1/users/123
    def get_user(self, id: int):
        return {"id": id}
```

**场景二：@RequestMapping 通用映射**

```python
from springbootai.annotations import RequestMapping


@RequestMapping(path="/sync", method=["POST"])  # 指定 method
def sync_data(self):
    return {"msg": "synced"}
```

> `@GetMapping` 等是 `@RequestMapping(method=["GET"])` 的快捷方式，优先使用它们。

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `path` | `str` / `List[str]` | URL 路径，支持 `{id}` 路径变量 |
| `method` | `str` / `List[str]` | HTTP 方法（仅 `@RequestMapping`） |
| `consumes` | `str` | 请求 Content-Type 限制 |
| `produces` | `str` | 响应 Content-Type 限制 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `@GetMapping(method=["POST"])` | GetMapping 固定 GET，要 POST 用 `@PostMapping` |
| 路径变量 `{id}` 和参数名不一致 | 用 `@PathVariable("实际名")` 显式指定 |
| 多个方法映射相同路径 | 每个路径+方法组合必须唯一 |

---

## 3. 参数绑定

### 是什么？

**参数绑定 = 框架自动从请求中提取数据，传给方法参数。** 你不用自己解析 query string、读 body、取 header——声明一个注解，框架帮你搞定。

### 参数注解速查表

| 注解 | 数据来源 | 示例 |
|------|---------|------|
| `@RequestParam` | URL 查询参数 / 表单字段 | `?name=abc` |
| `@PathVariable` | URL 路径变量 | `/users/{id}` 中的 `id` |
| `@RequestBody` | 请求体 JSON | `{"name":"abc"}` |
| `@RequestPart` / `@FileUpload` | multipart 文件字段 | `-F file=@report.pdf` |
| `@RequestHeader` | 请求头 | `Authorization: Bearer xxx` |
| `@CookieValue` | Cookie | `session_id=abc123` |

### 怎么用？

```python
from fastapi import UploadFile

from springbootai.annotations import (
    RestController, GetMapping, PostMapping,
    RequestParam, PathVariable, RequestBody, RequestPart,
    RequestHeader, CookieValue,
)


@RestController
class OrderController:

    @GetMapping("/orders")
    def list_orders(
        self,
        page: int = RequestParam(default=1),        # ?page=2
        size: int = RequestParam(default=20),        # &size=50
    ):
        return {"page": page, "size": size}

    @GetMapping("/orders/{id}")
    def get_order(self, id: int = PathVariable()):    # /orders/123
        return {"id": id}

    @PostMapping("/orders")
    def create_order(self, body: dict = RequestBody()):  # 请求体 JSON
        return {"created": body}

    @PostMapping("/upload")
    def upload(self, file: UploadFile = RequestPart(
        name="file", allowed_extensions="pdf,docx", max_size=10 * 1024 * 1024,
    )):
        return {"filename": file.filename, "content_type": file.content_type}

    @PostMapping("/upload-many")
    def upload_many(self, files: list[UploadFile] = RequestPart("files")):
        return {"count": len(files)}

    @GetMapping("/profile")
    def get_profile(
        self,
        token: str = RequestHeader(name="Authorization"),  # 请求头
    ):
        return {"token": token}

    @GetMapping("/session")
    def get_session(
        self,
        session_id: str = CookieValue(name="session_id"),  # Cookie
    ):
        return {"session": session_id}
```

### 文件上传参数

`@RequestPart` 自动把参数声明为 `multipart/form-data` 的文件字段，Controller 不需要
手动接收 `Request` 或调用 `request.form()`。`@FileUpload` 是同一个注解的易读别名。
参数类型使用 FastAPI 的 `UploadFile`；使用 `list[UploadFile]` 即可接收同名多文件字段。

| 参数 | 说明 |
|------|------|
| `name` / `value` | multipart 字段名，默认使用 Python 参数名 |
| `required` | 是否必须上传，默认 `True` |
| `description` / `media_type` | OpenAPI 文档描述和媒体类型 |
| `allowed_extensions` | 可选扩展名列表或逗号字符串，例如 `"jpg,png"` |
| `max_size` | 单个文件最大字节数；超过时返回 400 |

框架只在请求进入 Controller 前做文件名扩展名和 `UploadFile.size` 校验，不会消耗文件
流。文件的落盘位置、病毒扫描和对象存储上传仍应放在 Service 中；生产环境不要直接
信任客户端文件名，建议生成服务端文件名并限制上传目录。

### 参数说明

**@RequestParam / @RequestHeader / @CookieValue 共同参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | None | 参数名（不填则用 Python 参数名） |
| `required` | `bool` | True | 是否必填 |
| `default` | Any | None | 默认值（required=False 时生效） |

**@PathVariable 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | None | 路径变量名（不填则用 Python 参数名） |
| `required` | `bool` | True | 是否必填 |

**@RequestBody 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `required` | `bool` | True | 是否必填 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| 用 `@RequestParam` 取路径变量 | 路径变量 `{id}` 用 `@PathVariable` |
| `@RequestBody` 期望取 query 参数 | `@RequestBody` 只读请求体 JSON，query 用 `@RequestParam` |
| `required=True` 但不传参 | 设 `required=False` + `default=` 或确保前端传参 |

---

## 4. 跨域控制

### 是什么？

**`@CrossOrigin` = 允许浏览器跨域访问。** 浏览器有同源策略，前端 `localhost:3000` 访问后端 `localhost:8080` 会被拦截。加上 `@CrossOrigin` 告诉浏览器"我允许你访问"。

### 怎么用？

```python
from springbootai.annotations import RestController, GetMapping, CrossOrigin


@RestController
@CrossOrigin(origins=["http://localhost:3000"])  # 类级别：所有方法都允许跨域
class ApiController:

    @GetMapping("/data")
    @CrossOrigin(origins=["*"])  # 方法级别：覆盖类配置，允许所有来源
    def get_data(self):
        return {"data": "ok"}
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `origins` | `List[str]` | `["*"]` | 允许的来源 |
| `methods` | `List[str]` | 全部方法 | 允许的 HTTP 方法 |
| `allowedHeaders` | `List[str]` | `["*"]` | 允许的请求头 |
| `allowCredentials` | `bool` | False | 是否允许携带 Cookie |
| `maxAge` | `int` | 3600 | 预检请求缓存时间（秒） |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `origins=["*"]` 同时 `allowCredentials=True` | 浏览器规范禁止两者同时为真，指定具体来源 |
| 只在后端配 CORS，前端还用代理 | 二选一即可，避免重复处理 |

---

## 5. 全局异常处理

### 是什么？

**`@ControllerAdvice` + `@ExceptionHandler` = 统一异常处理。** 就像公司前台——不管哪个部门出了问题，都由前台统一接待、统一回复格式。不用在每个 Controller 里重复写 try/except。

### 怎么用？

```python
from springbootai.annotations import ControllerAdvice, ExceptionHandler, ResponseStatus
from springbootai.web.result import Result


@ControllerAdvice()
class GlobalExceptionHandler:
    """全局异常处理器——所有 Controller 抛出的异常都会经过这里"""

    @ExceptionHandler(ValueError, status_code=400)
    def handle_value_error(self, e: ValueError):
        return Result.error(code=400, message=str(e))

    @ExceptionHandler(Exception, status_code=500)
    def handle_exception(self, e: Exception):
        return Result.error(code=500, message="服务器内部错误")


@RestController
class UserController:
    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        if id <= 0:
            raise ValueError("id 必须大于 0")  # 被 handle_value_error 捕获
        return {"id": id}
```

### @ResponseStatus

```python
from springbootai.annotations import ResponseStatus, PostMapping


@RestController
class UploadController:
    @PostMapping("/upload")
    @ResponseStatus(code=201)  # 返回 201 Created 而非默认 200
    def upload(self):
        return {"url": "/files/abc.png"}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | `int` | HTTP 状态码 |
| `reason` | `str` | 原因短语 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `@ExceptionHandler` 不写异常类型 | 必须指定要捕获的异常类，如 `@ExceptionHandler(ValueError)` |
| 在 `@ControllerAdvice` 里写业务逻辑 | 只做异常转 HTTP 响应，业务逻辑放 Service |
| 每个 Controller 各自处理异常 | 提取到 `@ControllerAdvice` 统一处理 |

---

## 代码位置与测试

| 注解组 | 实现位置 | 测试文件 |
|--------|---------|---------|
| 控制器声明 | `springbootai/annotations/core.py` | `tests/test_web_annotations.py` |
| 路由映射 | `springbootai/annotations/core.py` | `tests/test_web_annotations.py` |
| 参数绑定 | `springbootai/annotations/core.py` | `tests/test_web_annotations.py` |
| 跨域控制 | `springbootai/annotations/core.py` | `tests/test_web_annotations.py` |
| 全局异常处理 | `springbootai/web/exception_handler.py` | `tests/test_exception_handler.py` |

完整测试报告见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## FAQ

### Q1: @RestController 和 @Controller 有什么区别？

- `@RestController`：返回值自动序列化为 JSON（等价于每个方法加 `@ResponseBody`）
- `@Controller`：返回视图名，适合服务端渲染。REST API 统一用 `@RestController`

### Q2: 路径变量和查询参数怎么选？

- 路径变量 `/users/{id}`：标识资源，用 `@PathVariable`。如 `/users/123`
- 查询参数 `?page=1`：过滤/分页，用 `@RequestParam`。如 `/users?page=1&size=20`

### Q3: @RequestMapping 写在类上和方法上有什么区别？

类上的 `@RequestMapping("/api/v1")` 是路径前缀，方法上的 `@GetMapping("/users")` 是相对路径，最终路径是 `/api/v1/users`。

### Q4: 全局异常处理能捕获所有异常吗？

能。`@ExceptionHandler(Exception)` 可以捕获所有异常。建议按异常类型从具体到通用排列，框架会优先匹配最具体的处理器。

### Q5: @CrossOrigin 加在类上和方法上有什么区别？

类上：对该控制器的所有方法生效。方法上：只对该方法生效，且会覆盖类级别的配置。

---

## 改进记录

暂无。

---

## Spring HATEOAS 超媒体链接

### HATEOAS 是什么？

**HATEOAS = Hypermedia As The Engine Of Application State（超媒体作为应用状态的引擎）。** RESTful API 的响应不仅返回数据，还带上"接下来能做什么"的链接（如 `self`、`update`、`delete`、`next`），客户端通过链接动态发现可用操作，无需硬编码 URL。

> 💡 比喻：普通 API 像只给你电话号码，你得自己记；HATEOAS 像"导航员"——每次响应都告诉你"下一步可以去哪、怎么做"。

### 核心组件速查

| 组件 | 一句话作用 | 对齐 Java Spring HATEOAS |
|------|----------|--------------------------|
| `Link` | 超媒体链接（href + rel + method） | `org.springframework.hateoas.Link` |
| `EntityModel` | 单个实体 + 链接 | `EntityModel<T>` |
| `CollectionModel` | 集合资源 + 链接 | `CollectionModel<T>` |
| `PagedModel` | 分页资源 + 链接（自动生成 first/last/next/prev） | `PagedModel<T>` |
| `WebMvcLinkBuilder` | 链接构建辅助工具 | `WebMvcLinkBuilder` |

### EntityModel 单个资源

**包装单个实体 + 链接。** 响应 JSON 会在实体字段之外多一个 `_links` 字段，列出可执行的操作。

```python
from springbootai.web.hateoas import Link, EntityModel

user = {'id': 1, 'name': 'Alice'}
model = EntityModel.of(user)
model.add(Link.of('/api/users/1', 'self'))
model.add(Link.of('/api/users/1', 'update', method='PUT'))
model.add(Link.of('/api/users/1', 'delete', method='DELETE'))

# 序列化后的 JSON 结构：
# {
#   "id": 1,
#   "name": "Alice",
#   "_links": {
#     "self":   {"href": "/api/users/1"},
#     "update": {"href": "/api/users/1", "method": "PUT"},
#     "delete": {"href": "/api/users/1", "method": "DELETE"}
#   }
# }
result = model.to_dict()
```

### CollectionModel 集合资源

**包装实体集合 + 链接。** 集合内容放在 `_embedded.items` 下，链接放在 `_links` 下。

```python
from springbootai.web.hateoas import Link, CollectionModel

users = [{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}]
collection = CollectionModel.of(users)
collection.add(Link.of('/api/users', 'self'))
collection.add(Link.of('/api/users', 'create', method='POST'))

# 序列化后的 JSON 结构：
# {
#   "_embedded": {
#     "items": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
#   },
#   "_links": {
#     "self":   {"href": "/api/users"},
#     "create": {"href": "/api/users", "method": "POST"}
#   }
# }
result = collection.to_dict()
```

### PagedModel 分页资源

**包装分页集合，自动生成 `first`/`last`/`next`/`prev` 链接 + `page` 元数据。** 客户端可凭链接逐页翻阅，无需自己拼 URL。

```python
from springbootai.web.hateoas import PagedModel

users = [{'id': 1}, {'id': 2}]   # 当前页数据
paged = PagedModel.of(
    users,
    page=0,                       # 当前页码（从 0 开始）
    size=20,                      # 每页数量
    total=100,                    # 总记录数
    base_path='/api/users',       # 基础路径，用于生成分页链接
)

# 序列化后的 JSON 结构：
# {
#   "_embedded": {"items": [{"id": 1}, {"id": 2}]},
#   "_links": {
#     "self":  {"href": "/api/users?page=0&size=20"},
#     "first": {"href": "/api/users?page=0&size=20"},
#     "last":  {"href": "/api/users?page=4&size=20"},
#     "next":  {"href": "/api/users?page=1&size=20"}
#     # 没有 prev，因为当前是第一页
#   },
#   "page": {
#     "size": 20,
#     "total_elements": 100,
#     "total_pages": 5,
#     "number": 0
#   }
# }
result = paged.to_dict()
```

> 自动链接生成规则：`self`（当前页）、`first`（首页）、`last`（末页）始终生成；`next`（仅当非末页）、`prev`（仅当非首页）按需生成。

### 自定义链接关系

**`rel` 字段定义链接的语义关系。** 除标准关系（`self`/`next`/`prev` 等）外，可自定义业务语义的 rel：

```python
from springbootai.web.hateoas import Link, EntityModel, WebMvcLinkBuilder

order = {'id': 100, 'status': 'pending'}
model = EntityModel.of(order)

# 方式一：手动添加自定义 rel
model.add(Link.of('/api/orders/100', 'self'))
model.add(Link.of('/api/orders/100/pay', 'pay', method='POST'))       # 自定义 rel: pay
model.add(Link.of('/api/orders/100/cancel', 'cancel', method='POST')) # 自定义 rel: cancel

# 方式二：用 WebMvcLinkBuilder 批量生成 CRUD 链接
crud_links = WebMvcLinkBuilder.crud_links('/api/users', item_id=1)
# 返回 [self, update(PUT), delete(DELETE)] 三个链接
model.add_all(crud_links)

# 方式三：集合级别的链接
collection_links = WebMvcLinkBuilder.collection_links('/api/users')
# 返回 [self, create(POST)] 两个链接
```

**常用 rel 关系列表：**

| rel | 含义 | 典型场景 |
|-----|------|---------|
| `self` | 资源自身 | 单个资源详情 |
| `create` | 创建资源 | 集合资源上的 POST |
| `update` | 更新资源 | 单个资源上的 PUT |
| `delete` | 删除资源 | 单个资源上的 DELETE |
| `first` / `last` | 首页 / 末页 | 分页资源 |
| `next` / `prev` | 下一页 / 上一页 | 分页资源 |
| `pay` / `cancel` 等 | 自定义业务操作 | 业务专属动作 |

### 与 Java Spring HATEOAS 的对照表

| 功能 | Java Spring HATEOAS | SpringBootAI |
|------|---------------------|--------------|
| 链接 | `Link.of(href, rel)` | `Link.of(href, rel, method=...)` |
| 单实体 | `EntityModel.of(T)` | `EntityModel.of(entity)` |
| 集合 | `CollectionModel.of(List<T>)` | `CollectionModel.of(items)` |
| 分页 | `PagedModel.of(Page<T>)` | `PagedModel.of(items, page, size, total, base_path)` |
| 表示模型基类 | `RepresentationModel<T>` 泛型 | `RepresentationModel` 普通类 |
| 链接构建 | `WebMvcLinkBuilder.linkTo(...)` | `WebMvcLinkBuilder.link_to(path, rel)` |
| 媒体类型 | 支持 HAL / HAL-FORMS / Collection+JSON | 标准 JSON（含 `_links` / `_embedded`） |
| 操作描述 | Affordances（描述支持的操作） | 简化为 `method` 字段 |
| 链接生成 | `ControllerLinkBuilder.methodOn()` | 显式路径字符串 |
