# SpringBootAI 安全使用指南

本文说明如何使用 JWT、密码哈希、认证和角色权限，也保留漏洞上报流程。第一次使用框架时，请先完成 [新手入门指南](BEGINNER_GUIDE.md)。

## 1. 安全模块解决什么问题

| 问题 | 对应能力 |
|---|---|
| 用户登录后如何证明身份 | JWT access token |
| token 过期后如何续期 | refresh token |
| 密码如何安全保存 | BCrypt / PBKDF2 哈希 |
| 某接口是否要求登录 | `@Authenticate` |
| 只有管理员能否访问 | `@PreAuthorize` / `@Secured` |
| 重复请求是否可能被重放 | ReplayProtection / nonce |
| 日志和配置是否泄露密钥 | SecretManager、脱敏和生产校验 |

安全模块只提供基础组件。完整登录系统仍需要用户表、密码失败次数、账号锁定、注销/吊销策略、HTTPS、审计日志和密钥轮换。

## 2. 三个最容易混淆的概念

### 2.1 认证

认证回答“你是谁”。客户端一般发送 `Authorization: Bearer <token>`，框架验证签名和过期时间后建立安全上下文。

### 2.2 授权

授权回答“你能做什么”。已经登录不代表可以访问管理员接口，仍要检查角色或权限。

### 2.3 密码哈希与 JWT 签名

用户密码使用 BCrypt/PBKDF2 单向哈希保存；JWT 使用应用密钥签名。两者不是同一把密钥，也不能互相替代。数据库中绝不能保存用户明文密码。

## 3. JWT 配置

`application.yml`：

```yaml
jwt:
  secret_key: ${JWT_SECRET_KEY:development-only-change-me}
  algorithm: HS256
  expires_in: 3600
  issuer: springpy-api
  audience: springpy-client
  leeway: 5
```

| 配置 | 作用 | 生产建议 |
|---|---|---|
| `secret_key` | token 签名密钥 | 至少 32 个随机字符，从环境变量/密钥服务注入 |
| `algorithm` | 签名算法 | 当前允许 HS256/HS384/HS512，所有服务保持一致 |
| `expires_in` | access token 有效秒数 | 按风险设置，通常不应无限期 |
| `issuer` | 谁签发 token | API 服务的稳定标识 |
| `audience` | token 发给谁 | 客户端或系统标识 |
| `leeway` | 允许的时钟误差秒数 | 只给少量误差，不能用来延长 token |

PowerShell 临时设置开发密钥：

```powershell
$env:JWT_SECRET_KEY='replace-with-at-least-32-random-characters'
```

不要把真实密钥提交到 Git，也不要把 token 打进普通日志。

## 4. 生成和验证 token

```python
from spring.security.jwt_utils import jwt_utils


claims = {
    "sub": "user-1001",
    "name": "Alice",
    "roles": ["ROLE_USER"],
    "permissions": ["order:read"],
}

access_token = jwt_utils.generate_token(claims)
refresh_token = jwt_utils.generate_refresh_token({"sub": "user-1001"})

verified = jwt_utils.verify_token(access_token)
print(verified["sub"])

new_access_token = jwt_utils.refresh_token(refresh_token)
```

关键规则：

- `sub` 应保存稳定的用户 ID，不建议只存昵称。
- access token 用于访问接口；refresh token 只用于换取新的 access token。
- 不能拿 access token 调用 `refresh_token()`，token 类型会被检查。
- `verify_token()` / `decode_token()` 对过期、签名错误等情况抛异常；只想得到布尔值时使用 `validate_token()`。
- JWT 默认是无状态的。需要立即注销、踢下线或吊销时，还要维护 token 版本、黑名单或短过期时间。

## 5. 密码保存和验证

推荐 BCrypt：

```python
from spring.orm import PasswordEncoder


encoder = PasswordEncoder("bcrypt")
encoded = encoder.encode("user-input-password")

# 注册时只保存 encoded，不保存原密码
assert encoder.matches("user-input-password", encoded) is True
assert encoder.matches("wrong-password", encoded) is False
```

`sha256` 实际使用带随机盐的 PBKDF2-SHA256。`md5` 只用于读取旧系统哈希并迁移；新编码不会继续生成不安全的原始 MD5。用户成功登录旧账号后，应立即重新编码并更新数据库。

密码接口还应实现：

1. 最小长度和弱密码检查。
2. 连续失败限速或临时锁定。
3. 找回密码 token 一次性使用并短时间过期。
4. 修改密码后让旧 refresh token 失效。
5. 错误响应不要透露“账号存在但密码错误”等可枚举信息。

## 6. 保护 Controller

```python
from spring.annotations import (
    Authenticate,
    GetMapping,
    PreAuthorize,
    RequestMapping,
    RestController,
    Secured,
)


@RequestMapping("/api")
@RestController
class AccountController:
    @Authenticate
    @GetMapping("/profile")
    def profile(self):
        return {"message": "已登录用户可访问"}

    @Authenticate
    @PreAuthorize("hasRole('ROLE_ADMIN')")
    @GetMapping("/admin/report")
    def admin_report(self):
        return {"message": "只有管理员可访问"}

    @Authenticate
    @Secured(["ROLE_FINANCE", "ROLE_ADMIN"])
    @GetMapping("/finance/report")
    def finance_report(self):
        return {"message": "财务或管理员可访问"}
```

常用授权表达式：

| 表达式 | 含义 |
|---|---|
| `hasRole('ROLE_ADMIN')` | 包含指定角色 |
| `hasAnyRole('ROLE_ADMIN','ROLE_OPS')` | 包含任一角色 |
| `hasPermission('order:read')` | 包含指定权限 |
| `hasAnyPermission('order:read','order:write')` | 包含任一权限 |
| `authentication.name == 'alice'` | 当前认证用户名等于目标值 |

未认证应返回 HTTP 401；已认证但权限不足应返回 HTTP 403。前端可以据此区分“需要登录”和“没有权限”。

## 7. 客户端如何发送 token

```powershell
curl http://127.0.0.1:8080/api/profile `
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

Swagger 页面中如果定义了 Bearer `@SecurityScheme`，点击右上角 Authorize，输入 token 后可以直接调试受保护接口。详见 [Swagger 指南](SWAGGER_MODULE.md)。

## 8. 必须编写的安全测试

一个受保护接口至少测试以下情况：

| 场景 | 期望结果 |
|---|---|
| 没有 Authorization 头 | 401 |
| 不是 Bearer 格式 | 401 |
| token 签名被修改 | 401 |
| token 已过期 | 401 |
| access token 角色不足 | 403 |
| 正确角色和权限 | 200 |
| refresh token 当 access token 使用 | 拒绝 |
| access token 当 refresh token 使用 | 拒绝 |
| 两个并发用户请求 | 安全上下文互不串号 |

还应测试日志不包含密码、完整 token、数据库密码和 API Key。

## 9. 生产安全基线

1. 设置 `SPRING_PROFILES_ACTIVE=production` 和 `STARTUP_FAIL_FAST=true`。
2. 使用至少 32 字符的随机 JWT 密钥，并制定轮换方案。
3. HTTPS 在可信反向代理或网关终止，内部敏感链路也应加密。
4. CORS 只允许真实前端域名；携带 Cookie/凭据时禁止通配 `*`。
5. SQL 值使用 `#{name}` 参数绑定，禁止把用户输入拼进 `${name}`。
6. 数据库账号使用最小权限，应用账号不要拥有不必要的 DDL 权限。
7. 给登录、验证码、找回密码和敏感写接口配置限流、幂等和审计。
8. 依赖扫描、Bandit 和测试必须作为 CI 门禁，不使用 `|| true` 忽略失败。
9. 配置文件、备份、监控标签和异常栈都要检查敏感信息泄露。
10. 定期演练密钥泄露、账号被盗和依赖漏洞的响应流程。

## 10. 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 所有 token 都验证失败 | 生成和验证使用了不同密钥/issuer/audience | 统一配置并检查环境变量 |
| 重启后旧 token 失效 | 开发密钥每次随机变化 | 使用稳定且安全存储的密钥 |
| 写了 `@PreAuthorize` 仍能访问 | 对象不是受管 Bean 或未建立认证上下文 | 通过 Web/BeanFactory 调用并加 `@Authenticate` |
| 管理员仍返回 403 | token 中角色名称不匹配 | 检查 `roles` claim 和 `ROLE_` 前缀 |
| Swagger 请求总是 401 | 没有点击 Authorize 或安全方案未声明 | 配置 Bearer scheme 并输入 access token |
| 日志中出现 token | 记录了完整请求头 | 对 Authorization、Cookie 和密钥字段脱敏 |

## 11. 漏洞报告政策

安全修复优先提供给最新发布的小版本，旧版本用户应先升级后复现。

发现疑似漏洞时不要创建公开 Issue，也不要在报告中放入生产凭据、客户数据或仍有效的 token。请使用 GitHub 仓库的 Private Security Advisory，并提供：

- 受影响版本和模块。
- 可复现的最小步骤或测试代码。
- 可能造成的影响。
- 已知的临时缓解措施。

维护者会协调修复和披露时间；在修复发布前不要公开可直接利用的细节。
