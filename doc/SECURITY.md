# SpringBootAI 安全模块 —— 小白也能看懂的 Web 安全指南

> 框架版本：SpringBootAI 2.1.1

---

## 零、安全是什么 —— 大白话入门

### 你遇到了什么问题？

你做了一个网站，任何人都能访问。但有些功能（比如查看个人信息、删除用户）显然不能让随便谁都能用。你需要：

- 知道来的人是谁（**认证**）
- 知道这个人有没有权限干这件事（**授权**）
- 密码不能被直接看到（**加密**）
- 坏人不能伪造身份（**签名**）
- 坏人不能注入恶意代码（**防护**）

### 一句话大白话

**安全就是在你的应用门口放个保安。** 保安只做三件事：

1. **查证件**（认证）—— 你是谁？看看你的门禁卡
2. **看权限**（授权）—— 你能进哪个房间？门禁卡上只写了"只限大厅"，就别想进机房
3. **防小偷**（加密和防护）—— 证件不能被伪造，重要信息不能被人偷看

### 三个最容易混淆的概念

#### 认证 vs 授权（别搞混！）

- **认证（Authentication）**：你是谁？就像进公司大门，保安看你的工牌。对应 `@Authenticate` 注解。
- **授权（Authorization）**：你能做什么？进了大门不代表你能去所有房间。对应 `@PreAuthorize` 注解。

> 你登录了（认证通过），不代表你是管理员（授权不通过）。两个是独立的检查。

#### 密码哈希 vs JWT 签名（也别搞混！）

- **密码哈希**是单向的——把你的密码变成一堆乱码存起来，下次登录时把输入的密码也变成乱码比对。**就像碎纸机，碎完拼不回来。** 密码哈希用来安全存储密码。
- **JWT 签名**是可验证的——用密钥给数据盖个章，别人能验章但不能伪造。**就像公章：你可以验章是真的，但没有印章就盖不出同样的章。** JWT 签名用来验证 token 没被篡改。

> 两者用的不是同一把密钥。数据库中绝不能保存用户明文密码。

---

## 一、JWT —— 带照片的门禁卡

### 你遇到了什么问题？

用户登录后，怎么让服务器记住"这个人是张三"？你不能让用户每次操作都输一遍密码。传统的 Session 方案需要服务器记住每个用户的状态，多台服务器时要共享 Session，很麻烦。

### ① 是什么

**JWT（JSON Web Token，读音 "jot"）就像一张带照片的门禁卡——刷一下就知道你是谁、能进哪些房间。** 用户登录成功后服务器给他发一张"电子门禁卡"（token），之后每次请求带着这张卡就行。服务器验证卡上的签名就知道是谁，不用记住状态。

JWT 由三部分组成（用 `.` 分隔）：

- **Header（头部）**：写明了用什么算法签名——就像门禁卡上写着"防伪技术：激光全息"
- **Payload（载荷）**：存着用户 ID、角色、权限等信息——就像门禁卡上的"姓名：张三，部门：研发部"
- **Signature（签名）**：用密钥计算出的防伪码——就像门禁卡上的防伪水印，一验就知道真假

### ② 怎么用

在 `application.yml` 中配置：

```yaml
jwt:
  secret_key: ${JWT_SECRET_KEY:development-only-change-me}  # 签名密钥，一定从环境变量读取
  algorithm: HS256           # 签名算法
  expires_in: 3600           # token 有效期（秒），3600 = 1 小时
  issuer: springpy-api       # 谁签发的
  audience: springpy-client  # 发给谁的
  leeway: 5                  # 允许时钟误差（秒）
```

| 配置 | 作用 | 新手建议 |
|---|---|---|
| `secret_key` | 签名密钥 | ⚠️ 必须从环境变量读取，不能写死在代码里！至少 32 个随机字符 |
| `algorithm` | 签名算法 | 默认 HS256 就够了 |
| `expires_in` | token 有效期（秒） | 建议 15 分钟～2 小时，太长了泄露风险大 |
| `issuer` | 签发者标识 | 填你的应用名 |
| `audience` | 接收者标识 | 填你的客户端名 |

PowerShell 中临时设置密钥（仅开发用）：

```powershell
$env:JWT_SECRET_KEY='请替换为至少32个随机字符的密钥'
```

生成和验证 token：

```python
from spring.security.jwt_utils import jwt_utils

# 1. 登录成功后生成 token
claims = {
    "sub": "user-1001",           # 用户唯一 ID
    "name": "Alice",              # 用户昵称
    "roles": ["ROLE_USER"],       # 角色列表
    "permissions": ["order:read"], # 权限列表
}

access_token = jwt_utils.generate_token(claims)          # 生成 access token
refresh_token = jwt_utils.generate_refresh_token({"sub": "user-1001"})  # 生成 refresh token

# 结果：
# access_token: "eyJhbGciOiJIUzI1NiIs..."  （一长串字符，这就是"门禁卡"）
# refresh_token: "eyJhbGciOiJIUzI1NiIs..."  （另一张"换卡凭证"）

# 2. 验证 token
verified = jwt_utils.verify_token(access_token)
print(verified["sub"])   # 输出: user-1001
print(verified["name"])  # 输出: Alice

# 3. access token 过期后用 refresh token 换新的
new_access_token = jwt_utils.refresh_token(refresh_token)
# 结果：拿到了一个新的 access token，旧 token 失效
```

### ③ 运行结果

用户登录后拿到 access_token，之后每次请求在 HTTP Header 里带上：

```powershell
curl http://127.0.0.1:8080/api/profile `
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
# 输出: {"message": "已登录用户可访问"}
```

### 关键规则（不看会踩坑）

- `sub` 存用户唯一 ID，不要只存昵称（昵称可能重复或修改）
- **access token** 用于访问接口；**refresh token** 只用于换新的 access token
- 不能用 access token 去换 refresh token，反之亦然
- JWT 默认是无状态的，要"踢人下线"需要额外做黑名单或 token 版本号

### 什么时候用 / 什么时候不用

| 用 | 不用 |
|---|---|
| 前后端分离的 API 接口 | 传统服务端渲染的网站（Session 更简单） |
| 多台服务器不需要共享 Session | 只有一台服务器且用 Session 没问题 |
| 移动 App、小程序等客户端 | 纯内部系统且不对外暴露接口 |

---

## 二、保护 Controller —— 给接口加"门禁"

### 你遇到了什么问题？

有些接口只能登录用户访问（比如个人信息），有些只能管理员访问（比如删除用户），有些所有人能访问（比如首页）。你怎么控制？

### ① @Authenticate —— 这个接口需要登录才能访问

```python
from spring.annotations import Authenticate, GetMapping, RequestMapping, RestController

@RequestMapping("/api")
@RestController
class AccountController:
    @Authenticate                     # 需要登录（需要带有效的 JWT token）
    @GetMapping("/profile")
    def profile(self):
        return {"message": "已登录用户可访问"}
    # 不带 token → 返回 401 "未登录"
    # 带有效 token → 返回正常数据

    @GetMapping("/hello")             # 没有 @Authenticate，谁都能访问
    def hello(self):
        return {"message": "你好，游客！"}
    # 任何人访问都正常返回
```

### ② @PreAuthorize —— 这个接口需要特定权限才能访问

```python
from spring.annotations import Authenticate, GetMapping, PreAuthorize, Secured

@Authenticate
@PreAuthorize("hasRole('ROLE_ADMIN')")  # 只有管理员能访问
@GetMapping("/admin/report")
def admin_report(self):
    return {"message": "只有管理员可访问"}
# 普通用户（角色是 ROLE_USER）访问 → 返回 403 "权限不足"
# 管理员（角色是 ROLE_ADMIN）访问 → 返回正常数据
```

### ③ @Secured —— 多角色都能访问

```python
@Authenticate
@Secured(["ROLE_FINANCE", "ROLE_ADMIN"])  # 财务或管理员都能访问
@GetMapping("/finance/report")
def finance_report(self):
    return {"message": "财务或管理员可访问"}
# 角色是 FINANCE 或 ADMIN 任一即可
```

### 常用授权表达式速查

| 表达式 | 含义 | 一句话 |
|---|---|---|
| `hasRole('ROLE_ADMIN')` | 包含指定角色 | 你是管理员吗？ |
| `hasAnyRole('ROLE_ADMIN','ROLE_OPS')` | 包含任一角色 | 你是管理员或运维吗？ |
| `hasPermission('order:read')` | 包含指定权限 | 你能查看订单吗？ |
| `hasAnyPermission('order:read','order:write')` | 包含任一权限 | 你能读写订单吗？ |
| `authentication.name == 'alice'` | 当前用户名等于 alice | 你是 alice 本人吗？ |

### ③ 运行结果

| 场景 | 返回状态码 | 含义 |
|---|---|---|
| 没带 token 访问 `@Authenticate` 接口 | 401 | 需要登录 |
| 带了 token 但角色不对访问 `@PreAuthorize` 接口 | 403 | 没有权限 |
| 带了有效 token 且权限匹配 | 200 | 正常返回 |

> 前端可以根据 401 跳转登录页，根据 403 提示"没有权限"。

---

## 三、密码保存和验证

### 你遇到了什么问题？

用户注册时，密码怎么存？**绝对不能存明文**——万一数据库泄露，所有用户的密码就全暴露了。

### 什么是密码哈希

**密码哈希就是"碎纸机"——把密码放进去，出来一堆乱码，而且永远拼不回来。**

| 算法 | 安全等级 | 大白话解释 | 能用吗？ |
|---|---|---|---|
| **BCrypt** | 🟢🟢🟢🟢🟢 最高 | 保险柜中的保险柜。自动加盐（混入随机数据），故意慢（防暴力破解） | ✅ 首选 |
| **PBKDF2-SHA256** | 🟢🟢🟢🟢 较高 | 反复搅拌很多次（默认 10 万次），暴力破解极其耗时 | ✅ 可用 |
| **SHA256（原始）** | 🟡🟡 低 | 算得太快，攻击者可以每秒试几百万个密码 | ❌ 不要直接用于存密码 |
| **MD5** | 🔴 极低 | 已被破解，秒级可碰撞伪造 | ❌ 绝不能用 |

> 框架里的 `sha256` 模式实际上用的是 PBKDF2-SHA256（带随机盐 + 多轮迭代），不是原始 SHA256。`md5` 模式仅用于读取旧系统数据并迁移。

### ② 怎么用

```python
from spring.orm import PasswordEncoder

# 创建 BCrypt 编码器
encoder = PasswordEncoder("bcrypt")

# 注册时：把用户输入的密码变成哈希
encoded = encoder.encode("user-input-password")
print(encoded)
# 输出: $2b$12$eYjX7qL8mN...  — 一堆乱码，完全看不出原密码

# 注册时保存 encoded 到数据库，不要保存原密码！

# 登录时：验证用户输入的密码是否正确
assert encoder.matches("user-input-password", encoded) is True   # 密码正确 → True
assert encoder.matches("wrong-password", encoded) is False       # 密码错误 → False
```

### ③ 运行结果

数据库中存的是类似 `$2b$12$eYjX7qL8mN...` 的哈希值。即使数据库泄露，攻击者也反推不出原始密码（暴力破解一个密码可能需要好几年）。

---

## 四、SQL 注入防护 —— 坏人是怎样攻击的

### 你遇到了什么问题？

你写了一个登录查询：

```python
# ❌ 危险代码！千万不要这样写！
username = request.get("username")   # 用户输入：admin' --
password = request.get("password")
sql = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
# 拼接后的 SQL 变成了：
# SELECT * FROM users WHERE username='admin' --' AND password='whatever'
# "--" 是 SQL 注释，后面全被注释掉了！不需要密码就能登录！
```

### 攻击者输入了什么？

用户在用户名输入框输入：`admin' --`

拼出来的 SQL 变成：

```sql
SELECT * FROM users WHERE username='admin' --' AND password='whatever'
                                        ↑ 从这开始全被注释掉了
```

**结果：攻击者不需要知道密码，直接以 admin 身份登录了！**

### 框架怎么防护

框架使用**参数化查询**（`?` 占位符），用户输入永远不会被当作 SQL 代码执行：

```python
# ✅ 安全写法：用 ? 占位符
spec = Specification()
spec.to_predicate 返回的是 ("username = ? AND password = ?", [username, password], "AND")
# 用户输入 'admin' -- 被当成一个普通的字符串值，不会改变 SQL 结构
# 实际执行的 SQL：
# SELECT * FROM users WHERE username='admin'' --' AND password='...'
#                         这一对引号被自动转义了 ↑
```

**一句话总结：永远不要用字符串拼接构建 SQL。用框架提供的参数绑定（`?` 占位符）。**

---

## 五、密码安全最佳实践

### 1. 密码不要写死在代码里

```python
# ❌ 千万别这样！
SECRET_KEY = "my-secret-key-123"
```

```python
# ✅ 从环境变量读取
import os
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("必须设置 JWT_SECRET_KEY 环境变量")
```

### 2. 密码强度要求

注册时检查密码强度：
- 最少 8 位
- 包含大小写字母 + 数字 + 特殊字符中的至少 3 种
- 不能是常见弱密码（123456、password、admin 等）

### 3. 登录错误不透露具体原因

```python
# ❌ 错误做法：给的信息太多了
if not user_exists(username):
    return "用户名不存在"       # 攻击者可以用这个枚举出有哪些账号！
elif not password_match:
    return "密码错误"           # 攻击者知道账号存在，可以继续试密码

# ✅ 正确做法：统一返回
return "用户名或密码错误"        # 不管账号存不存在、密码对不对，都说一样的话
```

### 4. 限制登录失败次数

连续 5 次失败后，锁定 15 分钟或要求输入验证码。防止暴力破解。

### 5. 日志不要泄露敏感信息

```python
# ❌ 千万别这样！
logger.info(f"用户 {username} 登录成功, token={access_token}")

# ✅ 正确
logger.info(f"用户 {user_id} 登录成功")  # 用 ID 代替用户名，不输出 token
```

### 6. Access Token 要设过期时间

| Token 类型 | 建议有效期 | 为什么 |
|---|---|---|
| Access Token | 15 分钟～2 小时 | 即使泄露，攻击窗口也有限 |
| Refresh Token | 7～30 天 | 用来换新 access token，过期需重新登录 |

### 7. 数据库密码用最小权限

应用的数据库账号不要给 DDL 权限（建表、删表等），只需要 CRUD 权限就够了。建表工作在部署时用管理员账号单独完成。

---

## 六、新手常见错误 ❌/✅

| # | ❌ 错误做法 | ✅ 正确做法 |
|---|---|---|
| 1 | 密钥写死在代码里：`SECRET_KEY = "abc123"` | 从环境变量读取：`os.environ.get("JWT_SECRET_KEY")` |
| 2 | 只加了 `@Authenticate` 没加 `@PreAuthorize` | 管理员接口必须额外加 `@PreAuthorize("hasRole('ROLE_ADMIN')")`，否则登录用户都能访问 |
| 3 | 返回"用户名不存在"和"密码错误"两种不同的消息 | 统一返回 "用户名或密码错误"，不给攻击者枚举账号的机会 |
| 4 | 密码明文存数据库 | 用 BCrypt/PBKDF2 哈希后存储 |
| 5 | 日志打印完整 token 或密码 | 日志只打印用户 ID，不打印敏感信息 |
| 6 | Access Token 永不过期 | 设 15 分钟～2 小时有效期 |
| 7 | 生产环境还用默认密钥 `development-only-change-me` | 部署前必须换成随机生成的密钥 |
| 8 | 用 MD5 哈希密码 | 用 BCrypt，MD5 仅用于迁移旧数据 |

---

## 七、快速自查清单

部署前逐条检查：

- [ ] `secret_key` 从环境变量读取，不在代码中硬编码
- [ ] access token 有过期时间，不超过 2 小时
- [ ] 密码用 BCrypt/PBKDF2 哈希存储，数据库中无明文
- [ ] 管理员接口同时有 `@Authenticate` 和 `@PreAuthorize`
- [ ] 登录错误返回统一消息，不区分"用户不存在"和"密码错误"
- [ ] 日志中不出现 token、密码、密钥
- [ ] 生产环境密钥不等于默认值 `development-only-change-me`
- [ ] 生产环境已启用 HTTPS
- [ ] CORS 只允许真实前端域名，不允许通配符 `*`
- [ ] 数据库应用账号只有 CRUD 权限，没有 DDL 权限
- [ ] 有登录失败次数限制（防暴力破解）
- [ ] 依赖扫描在 CI 中作为门禁运行

---

## 八、安全性测试清单

一个受保护接口至少测试以下情况：

| 场景 | 期望结果 | 为什么测试这个 |
|---|---|---|
| 没有 Authorization 头 | 401 | 确保不登录不能访问 |
| Authorization 头格式不是 `Bearer xxx` | 401 | 确保只接受 Bearer 格式 |
| token 签名被篡改 | 401 | 确保不能伪造 token |
| token 已过期 | 401 | 确保过期 token 无效 |
| access token 当 refresh token 用 | 拒绝 | 确保两种 token 不能混用 |
| refresh token 当 access token 用 | 拒绝 | 同上 |
| 角色对了但权限不够 | 403 | 确保细粒度权限控制 |
| 角色权限都正确 | 200 | 确保正常用户能访问 |
| 两个并发用户 | 互不串号 | 确保安全上下文隔离 |

还应检查：日志中不包含密码、完整 token、数据库密码和 API Key。

---

## 九、FAQ

### Q1：JWT 和 Session 有什么区别？我该用哪个？

- **Session**：服务器记住你是谁，每次请求通过 Cookie 里的 session_id 找到你的状态。就像饭馆给你一个号码牌，你的菜存在厨房里。
- **JWT**：服务器不记状态，每次请求带着 token（包含你的信息）。就像你随身带着身份证，去任何窗口办事都不需要对方认识你。

如果只有一台服务器，用 Session 更简单。如果是多台服务器或前后端分离，用 JWT。

### Q2：怎么让某个 token 立即失效（踢人下线）？

JWT 默认是无状态的，签发后就有效，不能"远程销毁"。解决方案：

1. 维护一个 Redis 黑名单，把要踢掉的 token 加进去
2. 在用户表加一个 token_version 字段，修改后旧 token 全失效
3. 把 access token 过期时间设短（15 分钟），通过不续期来"软踢"

### Q3：refresh token 的作用是什么？

Access token 设短过期时间（15 分钟），一旦泄露影响有限。Refresh token 设长过期时间（7 天），只用来换新的 access token。这样用户不用频繁登录，又不会让 access token 长期有效。

### Q4：BCrypt 生成的哈希每次都不同，怎么验证密码？

BCrypt 每次生成哈希时会随机加盐，所以同样的密码两次生成的哈希不一样。但 `matches()` 方法能验证——它从哈希中提取盐值，用同样的盐对输入密码做哈希，然后比对结果。

### Q5：Swagger 里怎么测试需要登录的接口？

在 Swagger 页面右上角点击 Authorize，输入 `Bearer YOUR_ACCESS_TOKEN`，之后所有请求自动带 token。详见 [Swagger 指南](SWAGGER_MODULE.md)。

---

## 十、漏洞报告政策

发现疑似漏洞时，不要创建公开 Issue。请使用 GitHub 仓库的 Private Security Advisory 提交，并提供：

- 受影响版本和模块
- 可复现的最小步骤或测试代码
- 可能造成的影响
- 已知的临时缓解措施

维护者会协调修复和披露时间；在修复发布前不要公开漏洞细节。
