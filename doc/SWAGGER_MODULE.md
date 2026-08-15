# SpringBootAI Swagger / OpenAPI 模块使用文档

> 框架版本：SpringBootAI 2.3.0

---

## Swagger 是什么？

**Swagger 就是自动生成 API 说明书——你不用手写文档，代码写完文档就有了。** 启动应用后，浏览器打开 `http://localhost:8000/docs`，你会看到一个网页，上面列出了你写的所有接口、每个接口需要什么参数、返回什么数据。更酷的是，你还可以直接在网页上点按钮发请求、看返回结果——连 Postman 都不用装。

> 生活比喻：去餐厅吃饭，菜单告诉你有什么菜、菜名是什么、需要付多少钱。Swagger 就是你 API 的菜单——前端同事、测试同事不用跑来问你"这个接口怎么调"，自己看菜单就全知道了。

### 本节导航

| 如果你想... | 跳到 |
|------------|------|
| 5 分钟上手，从零写出带文档的接口 | [5 分钟零代码生成 API 文档](#5-分钟零代码生成-api-文档) |
| 看懂 Swagger 网页上的按钮和输入框 | [Swagger 页面怎么用](#swagger-页面怎么用) |
| 给接口加上 JWT 登录（锁图标） | [JWT 认证集成](#jwt-认证集成) |
| 给接口加上 API Key 验证 | [API Key 认证](#api-key-认证) |
| 描述返回数据的结构 | [模型文档 @Schema](#模型文档-schema) |
| 描述某个参数的含义 | [参数文档 @Parameter](#参数文档-parameter) |
| 生产环境关闭 Swagger | [生产环境关闭 Swagger](#生产环境关闭-swagger) |
| 常见问题 | [Swagger UI 常见问题](#swagger-ui-常见问题) |
---

## 注解速查表

**注解就像便利贴——贴在类或方法上，框架启动时读取这些便利贴并自动配置行为。**

| 注解 | 一句话解释 | 写在哪 | 生活比喻 |
|------|-----------|--------|---------|
| `@Tag` | 给接口分组，Swagger 页面上显示为一个折叠区域 | 类上 | 书签分类——把相关接口归到一组 |
| `@Operation` | 描述这个接口是干什么的 | 方法上 | 菜名下面的小字说明 |
| `@ApiResponse` | 描述成功/失败时会返回什么 | 方法上 | "下单成功会收到确认短信，失败会收到退款通知" |
| `@Parameter` | 描述参数的含义和是否必填 | 方法上 | 表格栏旁边的小字标注 |
| `@Schema` | 描述请求体/返回数据的结构 | 模型类上 | 快递包裹上的标签——里面是什么、长什么样 |
| `@SecurityScheme` | 声明认证方式（JWT 或 API Key） | 类上 | "本区域需要刷卡进入" |
| `@SecurityRequirement` | 标记这个接口需要登录才能调 | 方法上 | 门上的🔒锁 |

---

## Swagger 页面怎么用

启动应用后，浏览器打开 `http://localhost:8000/docs`，你会看到：

1. **顶部标题栏**：API 标题、描述、版本号；有认证配置时右上角会出现 🔒 **Authorize** 按钮
2. **分组标签**：每个 Controller 是一个折叠分组，比如「用户管理」「订单管理」
3. **路由列表**：展开一个接口可以看到：
   - **摘要**：一句话说明这个接口干什么
   - **描述**：更详细的说明
   - **参数**：参数名、类型、是否必填、默认值
   - **响应**：200 成功、404 找不到等
   - **🔒 锁图标**：表示这个接口需要认证（要先点 Authorize 填 Token）
4. **Try it out 按钮**：点击后参数变输入框，填好点 **Execute** 就能看到真实响应
5. **底部**：Contact 联系人信息、License 许可信息

另外两个有用地址：
- `http://localhost:8000/redoc` — 只读格式的漂亮文档，适合截图给外部看
- `http://localhost:8000/openapi.json` — 机器可读 JSON，给其他工具用

---

## 5 分钟零代码生成 API 文档

> 不用手写一行文档，代码写完 + 启动 → 打开浏览器 → 文档就有了。

### 第一步：配置文件 application.yml

```yaml
spring:
  swagger:
    enabled: true                     # 开启文档
    title: "我的第一个 API"            # 显示在页面顶部的大标题
    description: "一个简单的用户管理 API"
    version: "1.0.0"
```

### 第二步：创建 Controller，加上注解

```python
from spring.annotations.core import RestController, RequestMapping, GetMapping, PostMapping, PathVariable, RequestBody
from spring.web.swagger import Tag, Operation, ApiResponse, SecurityScheme, SecurityRequirement


@SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")  # 声明 JWT 认证方式
@Tag(name="用户管理", description="用户的增删改查接口")  # 给这组接口取个分组名
@RestController
@RequestMapping("/api/users")
class UserController:

    @Operation(summary="获取用户列表", description="分页查询所有用户")
    @ApiResponse(code=200, description="成功返回用户列表")
    @GetMapping("/list")
    def list_users(self):
        # 返回: 用户列表的 JSON 数组
        return [{"id": 1, "name": "张三"}, {"id": 2, "name": "李四"}]

    @Operation(summary="获取用户详情")
    @ApiResponse(code=200, description="成功返回用户信息")
    @ApiResponse(code=404, description="用户不存在")
    @GetMapping("/{user_id}")
    def get_user(self, user_id: int):
        # URL: /api/users/1 → 返回: {"id": 1, "name": "张三"}
        return {"id": user_id, "name": "张三"}

    @Operation(summary="创建用户")
    @SecurityRequirement(name="BearerAuth")  # 这个接口需要登录
    @ApiResponse(code=201, description="创建成功")
    @PostMapping("/create")
    def create_user(self, body: dict):
        # 返回: {"id": 999, "name": "...", ...}
        return {"id": 999, **body}
```

### 第三步：启动应用

```bash
python main.py
```

### 第四步：打开浏览器访问

打开 `http://localhost:8000/docs`，你会看到：

- 顶部显示「我的第一个 API」标题和版本 1.0.0
- 「用户管理」分组下面有三个接口
- 展开任意接口可以看到参数说明和返回格式
- 创建用户接口前面有一个 🔒 锁图标，表示需要认证
- 点击 **Try it out** → 填参数 → **Execute**，就能看到真实返回结果
- 右上角有 **Authorize** 按钮，点进去填 Token

---

## JWT 认证集成

> 生活比喻：JWT 就像一张电子门禁卡。有卡（Token）才能进特定房间，没卡的只能去公共区域。

```python
from spring.web.swagger import SecurityScheme, SecurityRequirement


# 1. 在 Controller 类上声明"这个控制器用的是 JWT 门禁"
@SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
@RestController
@RequestMapping("/api")
class Api:

    # 2. 在需要认证的方法上标记"这个接口需要门禁卡"
    @SecurityRequirement(name="BearerAuth")
    @GetMapping("/secret")
    def secret(self):
        return {"data": "机密数据"}  # 只有带 Token 才能看到

    # 3. 不标记 = 公开接口，任何人都能访问
    @GetMapping("/public")
    def public(self):
        return {"data": "公开数据"}
```

**Swagger 中如何使用：**
1. 点页面右上角的 🔒 **Authorize** 按钮
2. 在弹出的对话框中填入 `Bearer <你的Token>`
3. 点 **Authorize** 确认
4. 现在带锁图标的接口就可以正常调用了

---

## API Key 认证

> 生活比喻：API Key 就像一把固定密码的钥匙。你把钥匙发给合作方，他们每次请求都带上。

```python
from spring.web.swagger import SecurityScheme, SecurityRequirement


@SecurityScheme(name="ApiKey", type="apiKey", header_name="X-API-Key", description="API 密钥认证")
@RestController
@RequestMapping("/api")
class Api:
    @SecurityRequirement(name="ApiKey")
    @GetMapping("/data")
    def data(self):
        return {"result": "ok"}
```

## 模型文档 @Schema

> 生活比喻：就像给快递包裹贴标签——外面写着"里面是什么、长什么样"。

```python
from spring.web.swagger import Schema


@Schema(title="订单模型", description="订单实体", example={"id": 1, "amount": 99.9})
class OrderDTO:
    id: int        # 订单 ID
    amount: float  # 金额
```

加了 `@Schema` 后，Swagger 页面底部的 Schemas 区域会显示 `OrderDTO` 的结构说明。

## 参数文档 @Parameter

> 生活比喻：就像表格栏旁边的小字标注——"请填身份证上的名字，示例：张三"。

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

## 生产环境关闭 Swagger

```yaml
spring:
  swagger:
    enabled: false   # /docs /redoc /openapi.json 全部返回 404
```

---

## 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 以为加了 `@SecurityScheme` 就会自动拦截未登录请求 | `@SecurityScheme` 只是**声明**认证方案（在 Swagger 页面上显示 Authorize 按钮），真正拦截请求需要配合中间件或手动校验 Token |
| 忘记点 Authorize 填 Token 就去调带锁接口 | 先点页面右上角 🔒 按钮，填入 `Bearer <你的Token>`，再调接口 |
| 生产环境把 Swagger 页面暴露在公网 | 设置 `enabled: false` 或通过网关/防火墙限制 `/docs` 访问 |
| 静态路径和动态路径随便排顺序 | **静态路径（如 `/list`）必须写在动态路径（如 `/{user_id}`）前面**，否则 `/list` 会被 `/{user_id}` 拦截，`user_id="list"` 不是 int 会报错 |
| Swagger 会自动帮我校验参数 | Swagger 只是文档展示，不校验参数。校验要配合 `@NotBlank`、`@Min` 等注解 |
| 觉得 `@ApiResponse` 的 description 只是装饰 | description 会显示在 Swagger 页面上，帮助调用者理解各种情况，不要省略 |

---

## Swagger UI 常见问题

### Q1: 打开 /docs 是空白页？

**检查清单：**
- `application.yml` 中 `spring.swagger.enabled` 是否为 `true`？
- Controller 类有没有加 `@RestController`？
- 方法有没有加 `@GetMapping` / `@PostMapping` 等路由注解？

### Q2: Try it out 点了 Execute 没反应？

**可能原因：**
- 浏览器控制台是否有 JavaScript 报错？
- 接口是否加了 `@SecurityRequirement` 但你还没填 Token？
- 检查 `http://localhost:8000/openapi.json` 是否能正常返回 JSON

### Q3: 加了 @SecurityRequirement，Swagger 页面上没看到锁图标？

确认在 Controller 类上也加了对应的 `@SecurityScheme`。两者搭配使用：`@SecurityScheme` 声明认证方式，`@SecurityRequirement` 标记具体接口。

### Q4: /docs 和 /redoc 有什么区别？

- `/docs` = Swagger UI，可以点 **Try it out** 在线测试接口
- `/redoc` = ReDoc，只能看不能测，排版更漂亮，适合截图发给外部

### Q5: 怎么修改 /docs 的访问路径？

```yaml
spring:
  swagger:
    docs-url: "/api-docs"    # 改成你想要的路径
    redoc-url: "/api-redoc"
    openapi-url: "/api-spec.json"
```

设为 `null` 可以单独禁用某个页面：
```yaml
    redoc-url: null   # 禁用 ReDoc
```

### Q6: 分组标签太多，页面很乱怎么办？

每个 `@RestController` 类对应一个分组。如果你的 Controller 太多，可以考虑按业务模块合并 Controller，或者给关联度低的接口加上 `@Tag(name="其他")`。

---

## 代码位置

- 实现：[`spring/web/swagger.py`](../spring/web/swagger.py)
- 测试：[`tests/test_swagger_module.py`](../tests/test_swagger_module.py)（43 个用例）
- 测试报告：[TEST_REPORT.md](TEST_REPORT.md)
