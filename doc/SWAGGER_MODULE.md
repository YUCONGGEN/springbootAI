# SpringBootAI Swagger / OpenAPI 模块使用文档

> 版本：SpringBootAI Swagger 1.0.0 ｜ 框架版本：SpringBootAI 1.8.3
> 对齐 SpringDoc OpenAPI 3 注解体系（`@Tag`/`@Operation`/`@ApiResponse`/`@Parameter`/`@Schema`/`@SecurityScheme`/`@SecurityRequirement`），同时提供 Swagger 2 风格别名（`@Api`/`@ApiOperation`/`@ApiModel`/`@ApiParam`），**无新增第三方依赖**（复用 FastAPI 自带的 OpenAPI 生成），`pip install springbootAI` 即可用。
> 设计原则：**复用项目既有范式，不重复造轮子**——注解复用 `SpringAnnotation` 描述符，元数据在 `WebApplicationContext` 注册路由时同步注入 FastAPI 路由参数，全局 `securitySchemes`/`@Schema`/`@Parameter` 通过自定义 `app.openapi()` 后处理注入。

---

## 零、新手先读

Swagger UI 是给人看的交互式 API 页面，OpenAPI 是给工具读取的接口描述 JSON。写好文档后，前端、测试和其他服务可以知道接口路径、参数、返回值和认证方式，也可以直接在浏览器点击“Try it out”发请求。

SpringBootAI 会基于 FastAPI 自动生成基础 OpenAPI；`@Tag`、`@Operation` 等注解用于补充人能看懂的说明。最小验证流程：

1. 给 Controller 添加 `@Tag`，给方法添加 `@Operation`。
2. 启动应用并打开 `http://127.0.0.1:8080/docs`。
3. 确认分组、摘要、参数和响应状态码正确。
4. 打开 `/openapi.json`，确认同一路由也存在。
5. 用“Try it out”调用一次，检查真实响应而不只是页面文字。

Swagger 是文档和调试工具，不会自动替代认证、参数校验和接口测试。生产环境是否公开 `/docs` 应按安全要求决定；内网管理系统也应防止 OpenAPI 暴露敏感内部接口。

## 一、模块组成

| 文件 | 职责 |
|------|------|
| `spring/web/swagger.py` | 注解定义 + `SwaggerConfig` 配置 + `collect_openapi_metadata` 元数据收集 + `configure_swagger` schema 后处理 |
| `spring/web/web_context.py` | `WebApplicationContext.__init__` 用 `SwaggerConfig` 初始化 FastAPI；`_register_handler` 收集注解元数据传给路由；`init()` 末尾调用 `_configure_swagger` |

### 注解一览（对齐 SpringDoc OpenAPI 3 + Swagger 2 别名）

| 注解 | 别名 | 作用域 | 对齐 SpringDoc | 说明 |
|------|------|--------|---------------|------|
| `@Tag` | `@Api` | 类 | `@Tag` | Controller 分组标签 |
| `@Operation` | `@ApiOperation` | 方法 | `@Operation` | 操作描述（summary/description/operationId/deprecated/tags） |
| `@ApiResponse` | — | 方法（可重复） | `@ApiResponse` | 响应状态码描述 |
| `@ApiResponses` | — | 方法 | `@ApiResponses` | 聚合多个 `@ApiResponse` |
| `@Parameter` | `@ApiParam` | 方法 | `@Parameter` | 参数描述（description/example/required/deprecated） |
| `@Schema` | `@ApiModel` | 模型类 | `@Schema` | 模型描述（title/description/example/deprecated） |
| `@SecurityScheme` | — | 类 | `@SecurityScheme` | 全局安全方案（bearer/apiKey） |
| `@SecurityRequirement` | — | 方法 | `@SecurityRequirement` | 标记路由需要认证 |

---

## 二、配置（application.yml）

```yaml
spring:
  swagger:
    enabled: true                    # 是否启用 OpenAPI/docs（生产环境可设 false）
    title: "SpringBootAI 演示 API"        # API 标题
    description: "注解驱动的 API 文档"  # API 描述
    version: "1.0.0"                 # API 版本
    terms-of-service: "https://tos.example.com"
    contact:
      name: "Tom"
      email: "tom@example.com"
      url: "https://example.com"
    license:
      name: "MIT"
      url: "https://mit.org"
    docs-url: "/docs"                # Swagger UI 路径（null 禁用）
    redoc-url: "/redoc"              # ReDoc 路径（null 禁用）
    openapi-url: "/openapi.json"     # OpenAPI JSON 路径（null 禁用）
```

> 支持松散绑定：`docs-url`/`docs_url` 均可。未配置时使用 FastAPI 默认值（`/docs`/`/redoc`/`/openapi.json`）。

---

## 三、快速上手

### 3.1 标注 Controller

```python
from spring.annotations.core import RestController, RequestMapping, GetMapping, PostMapping, PathVariable, RequestBody
from spring.web.swagger import Tag, Operation, ApiResponse, SecurityScheme, SecurityRequirement

@SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")  # 全局 JWT 认证
@Tag(name="用户管理", description="用户增删改查接口")
@RestController
@RequestMapping("/api/users")
class UserController:

    @Operation(summary="获取用户列表", description="分页查询所有用户", operation_id="listUsers")
    @ApiResponse(code=200, description="成功返回用户列表")
    @GetMapping("/list")
    def list_users(self):
        return [{"id": 1, "name": "Tom"}]

    @Operation(summary="获取用户详情", deprecated=False)
    @ApiResponse(code=200, description="成功")
    @ApiResponse(code=404, description="用户不存在")
    @GetMapping("/{user_id}")
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "Tom"}

    @Operation(summary="创建用户")
    @SecurityRequirement(name="BearerAuth")   # 此接口需要认证
    @ApiResponse(code=201, description="创建成功")
    @PostMapping("/create")
    def create_user(self, body: dict):
        return {"id": 999, **body}
```

### 3.2 访问文档

启动应用后访问：
- **Swagger UI**：`http://localhost:8000/docs`（交互式 API 文档，可在线测试）
- **ReDoc**：`http://localhost:8000/redoc`（只读美观文档）
- **OpenAPI JSON**：`http://localhost:8000/openapi.json`（机器可读 schema）

Swagger UI 顶部会出现 **Authorize** 按钮（因为声明了 `@SecurityScheme`），输入 JWT token 后即可调用需要认证的接口。

### 3.3 禁用文档（生产环境）

```yaml
spring:
  swagger:
    enabled: false   # /docs /redoc /openapi.json 全部返回 404
```

---

## 四、JWT 认证集成

```python
from spring.web.swagger import SecurityScheme, SecurityRequirement

# 1. 在 Controller 类上声明全局安全方案
@SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
@RestController
@RequestMapping("/api")
class Api:

    # 2. 在需要认证的方法上标记 @SecurityRequirement
    @SecurityRequirement(name="BearerAuth")
    @GetMapping("/secret")
    def secret(self):
        return {"data": "confidential"}

    # 3. 不标记 = 公开接口
    @GetMapping("/public")
    def public(self):
        return {"data": "open"}
```

生成的 OpenAPI schema：

```json
{
  "components": {
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    }
  },
  "paths": {
    "/api/secret": {
      "get": {
        "security": [{"BearerAuth": []}],
        ...
      }
    },
    "/api/public": {
      "get": { ... }
    }
  }
}
```

---

## 五、API Key 认证

```python
from spring.web.swagger import SecurityScheme, SecurityRequirement

@SecurityScheme(name="ApiKey", type="apiKey", header_name="X-API-Key", description="API 密钥认证")
@RestController
@RequestMapping("/api")
class Api:
    @SecurityRequirement(name="ApiKey")
    @GetMapping("/data")
    def data(self):
        return {}
```

生成 `{"type": "apiKey", "in": "header", "name": "X-API-Key"}`。

---

## 六、模型文档（@Schema）

```python
from spring.web.swagger import Schema

@Schema(title="订单模型", description="订单实体", example={"id": 1, "amount": 99.9})
class OrderDTO:
    id: int
    amount: float
```

`@Schema` 通过后处理 `components/schemas` 注入 `title`/`description`/`example`（在 FastAPI 自动生成的 Pydantic schema 基础上叠加）。

---

## 七、参数文档（@Parameter）

```python
from spring.web.swagger import Parameter

@RestController
@RequestMapping("/api")
class Api:
    @Parameter(name="user_id", description="用户唯一标识", example=42)
    @GetMapping("/users/{user_id}")
    def get_user(self, user_id: int):
        return {"id": user_id}
```

`@Parameter` 通过后处理 OpenAPI schema 的 `parameters` 注入 `description`/`example`/`required`/`deprecated`。

---

## 八、Swagger 2 别名兼容

如果你习惯 Swagger 2 注解名，以下别名等价可用：

```python
from spring.web.swagger import Api, ApiOperation, ApiModel, ApiParam

@Api(name="订单")           # = @Tag
@RestController
class OrderCtrl:
    @ApiOperation(summary="查询订单")  # = @Operation
    @ApiParam(name="id", description="订单ID")  # = @Parameter
    @GetMapping("/orders/{id}")
    def get(self, id: int): ...
```

---

## 九、与 Java Spring 的对齐与差异

| 特性 | Java SpringDoc | SpringBootAI | 差异 |
|------|---------------|----------|------|
| 注解体系 | `io.swagger.v3.oas.annotations.*` | `spring.web.swagger.*` | 命名对齐，复用 `SpringAnnotation` 描述符 |
| 自动扫描 | `springdoc-openapi-starter-webmvc-ui` 自动扫描 | `WebApplicationContext` 注册路由时同步注入 | 无额外依赖，复用路由注册流程 |
| 配置 | `springdoc.api-docs.*` / `springdoc.swagger-ui.*` | `spring.swagger.*` | 松散绑定（kebab/snake） |
| 认证 | `@SecurityScheme` + `@SecurityRequirement` | 同 | JWT Bearer / API Key |
| 模型文档 | `@Schema`（完整 OpenAPI Schema 属性） | `@Schema`（title/description/example/deprecated） | 通过后处理注入，不支持完整属性全集 |
| 参数文档 | `@Parameter`（完整属性） | `@Parameter`（description/example/required/deprecated） | 后处理注入到 FastAPI 生成的 parameters |
| 禁用文档 | `springdoc.api-docs.enabled=false` | `spring.swagger.enabled=false` | docs/redoc/openapi 全部 404 |
| Swagger 2 别名 | swagger-annotations `@Api`/`@ApiOperation` | `@Api`/`@ApiOperation`/`@ApiModel`/`@ApiParam` | 提供常用别名兼容习惯 |

---

## 十、测试覆盖

共 **43 用例**，详见 [TEST_REPORT.md](TEST_REPORT.md)。

| 测试类 | 用例数 | 覆盖范围 |
|--------|--------|---------|
| TestAnnotationMetadata | 11 | @Tag/@Api/@Operation/@ApiOperation/@ApiResponse 重复/@ApiResponses/@Parameter/@Schema/@SecurityScheme(bearer+apiKey)/@SecurityRequirement |
| TestCollectOpenApiMetadata | 6 | 类@Tag+方法@Operation 组合/@ApiResponse 收集/@SecurityRequirement 收集/operation_id+deprecated/无注解空/方法 tag 叠加类 tag |
| TestCollectSecuritySchemes | 3 | bearer/apiKey/无 scheme |
| TestSwaggerConfig | 8 | 默认值/kebab-case/snake_case/disabled/contact+license/to_fastapi_kwargs 启用/禁用/contact+license kwargs |
| TestSwaggerIntegration | 15 | openapi title+version/docs 可访问/docs 禁用 404/@Tag 出现/@Operation summary+description/operation_id+deprecated/@ApiResponse/JWT securitySchemes/security requirement on route/apiKey securityScheme/@Schema 后处理/@Parameter 后处理/别名注解/Swagger UI HTML 含标题/多 Controller tags |

---

## 十一、浏览器网页实测（2026-08-09）

除单元测试外，另启动真实 uvicorn 服务器（带完整 Swagger 注解的 Controller）用浏览器访问 `/docs` 进行端到端验证，截图存档。

### 11.1 实测覆盖项

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | Swagger UI 页面加载（标题/描述/版本/OAS 3.1 标识） | ✅ |
| 2 | `@Tag` 分组渲染（用户管理/订单管理/default[actuator]） | ✅ |
| 3 | `@Operation` summary 显示在每个路由行 | ✅ |
| 4 | `@Operation` description 显示在展开区 | ✅ |
| 5 | `@ApiResponse` 状态码描述（200 成功返回用户列表） | ✅ |
| 6 | `@Parameter` 默认值显示（page=1/size=10） | ✅ |
| 7 | `operation_id` 出现在 URL 锚点（`#/用户管理/listUsers`） | ✅ |
| 8 | **Try it out** 按钮可用，参数可编辑 | ✅ |
| 9 | **Execute** 实际调用接口成功，响应体正确（`page=2` 透传） | ✅ |
| 10 | `@SecurityScheme` 渲染为 **Authorize** 按钮 + 弹窗（BearerAuth/JWT Bearer 认证） | ✅ |
| 11 | `@SecurityRequirement` 标记的路由显示锁图标（POST /create） | ✅ |
| 12 | Contact/License 信息渲染（SpringBootAI 网站/邮箱/MIT） | ✅ |
| 13 | Actuator 端点自动归入 default 分组 | ✅ |

> 截图：`swagger_ui_overview.png`（总览）、`swagger_ui_tryitout_response.png`（Try it out 响应）、`swagger_ui_authorize_dialog.png`（Authorize 弹窗）。

### 11.2 实测发现并修复：路由注册顺序（Spring 迁移陷阱）

**现象**：`@GetMapping("/list")` 与 `@GetMapping("/{user_id}")` 共存时，`/api/users/list` 被动态路径 `/{user_id}` 拦截，返回 422（`user_id="list"` 无法解析为 int）。

**根因**：`WebApplicationContext._register_controllers` 原用 `inspect.getmembers`，按**字母序**遍历方法，`get_user` 排在 `list_users` 之前注册，导致 `/{user_id}` 先匹配。FastAPI/Starlette 按**注册顺序**匹配路由，无静态优先级。

**与 Spring 的差异**：Spring MVC 的 `RequestMappingHandlerMapping` 对路径模式有**特异性排序**，静态路径（`/list`）天然优先于动态路径（`/{user_id}`），开发者无需关心声明顺序。FastAPI 无此机制。

**修复**：[web_context.py](../spring/web/web_context.py) 改用遍历 `__mro__` 的 `__dict__`（Python 3.7+ 类命名空间保留定义顺序），按**源码声明顺序**注册路由。开发者把静态路径声明在动态路径之前即可避免拦截，体验对齐 Spring。

```python
# 修复后：静态路径 /list 必须声明在动态路径 /{user_id} 之前
@GetMapping("/list")
def list_users(self): ...

@GetMapping("/{user_id}")   # 动态路径放后面
def get_user(self, user_id: int): ...
```

**回归验证**：`test_swagger_module.py` / `test_web_annotations_full.py` / `test_test_slicing.py` / `test_actuator.py` 共 145 用例全部通过。

> ⚠️ **迁移提示**：从 Spring 迁移时，若同一 Controller 内存在静态路径与 `/{var}` 动态路径并存，请将静态路径声明在前。这是 FastAPI 路由匹配机制决定的，框架已按定义顺序注册以最大程度对齐 Spring 体验。
