# 企业级注解驱动模块

> 对齐 Java Spring Boot 的 `@EnableXxx` 系列注解，通过注解驱动方式启用企业级功能，替代繁琐的 YAML 配置。

## 概述

SpringBootAI 提供了 10 个新注解，将 16 项企业级功能改造为注解驱动模式。这些注解标记在 `@SpringBootApplication` 主类上，应用启动时自动扫描并初始化对应功能。

### 注解优先级

**注解参数 > 配置文件**：如果主类上标注了注解，注解参数会覆盖配置文件中的对应项。两者可以共存，注解用于启用功能，配置文件用于详细参数。

### 新增注解一览

| 注解 | 类型 | 对齐 Java | 功能 |
|------|------|-----------|------|
| `@EnableOAuth2` | 启用型 | `@EnableResourceServer` | 启用 OAuth2 资源服务器 |
| `@EnableCsrf` | 启用型 | `http.csrf()` | 启用 CSRF 防护 |
| `@EnableDevTools` | 启用型 | `spring-boot-devtools` | 启用热重载 |
| `@EnableConfigServer` | 启用型 | `spring-cloud-config` | 启用配置中心客户端 |
| `@EnableBus` | 启用型 | `spring-cloud-bus` | 启用事件总线 |
| `@EnableBatchProcessing` | 启用型 | `@EnableBatchProcessing` | 启用批处理 |
| `@EnableDataRest` | 启用型 | `@RepositoryRestResource` | 启用 Data REST |
| `@BatchJob` | 功能型 | `@Job` | 标记批处理作业 |
| `@BatchStep` | 功能型 | `@Step` | 标记批处理步骤 |
| `@RepositoryRestResource` | 功能型 | `@RepositoryRestResource` | 标记 Repository 为 REST 资源 |

---

## @EnableOAuth2 — 启用 OAuth2 资源服务器

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableOAuth2

@SpringBootApplication
@EnableOAuth2(
    issuer="https://auth.example.com",
    audiences=["my-api"],
    algorithms=["RS256"],
    jwks_uri="https://auth.example.com/.well-known/jwks.json",
)
class Application:
    pass
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `issuer` | `str` | `None` | 预期的 token 签发方（验证 `iss` claim） |
| `audiences` | `list` | `[]` | 预期的 token 受众列表（验证 `aud` claim） |
| `jwks_uri` | `str` | `None` | JWKS 公钥端点 URL（RS256 算法时使用） |
| `algorithms` | `list` | `['HS256']` | 允许的签名算法列表 |
| `secret_key` | `str` | `None` | HS256 对称密钥（生产环境应从环境变量读取） |

### 与配置文件的等价关系

```yaml
# application.yml — 等价于 @EnableOAuth2(issuer="https://auth.example.com")
spring:
  security:
    oauth2:
      enabled: true
      issuer: https://auth.example.com
      algorithms: [RS256]
```

### 在路由中使用 OAuth2 保护

```python
from spring.security.oauth2 import oauth2_resource_server
from fastapi import Depends

@app.get("/api/protected", dependencies=[Depends(oauth2_resource_server.get_dependency())])
def protected():
    return {"message": "需要有效的 OAuth2 token"}
```

---

## @EnableCsrf — 启用 CSRF 防护

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableCsrf

@SpringBootApplication
@EnableCsrf(token_ttl=7200, secure_cookie=True)
class Application:
    pass
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `token_length` | `int` | `32` | CSRF Token 长度（字节） |
| `token_ttl` | `int` | `3600` | Token 有效期（秒） |
| `cookie_name` | `str` | `'XSRF-TOKEN'` | 存储 Token 的 Cookie 名 |
| `header_name` | `str` | `'X-XSRF-TOKEN'` | 客户端回传 Token 的 Header 名 |
| `secure_cookie` | `bool` | `False` | 是否设置 Secure 标志（HTTPS 应为 True） |
| `same_site` | `str` | `'Lax'` | SameSite 策略 |

### 工作原理

采用 **Double Submit Cookie** 模式：
1. GET 请求响应中自动注入 `XSRF-TOKEN` Cookie
2. POST/PUT/PATCH/DELETE 请求需在 Header 中携带 `X-XSRF-TOKEN`
3. 中间件校验 Cookie 与 Header 中的 Token 是否一致

### 前端配合

```javascript
// 前端从 Cookie 读取 Token，放入请求头
const token = document.cookie.match('XSRF-TOKEN=([^;]+)')[1];
fetch('/api/users', {
    method: 'POST',
    headers: { 'X-XSRF-TOKEN': token, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
});
```

---

## @EnableDevTools — 启用热重载

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableDevTools

@SpringBootApplication
@EnableDevTools(watch_dirs=["src", "config"], poll_interval=0.5)
class Application:
    pass
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `watch_dirs` | `list` | `['.']` | 监视目录列表 |
| `poll_interval` | `float` | `1.0` | 轮询间隔（秒） |
| `exclude_dirs` | `list` | `None` | 排除目录集合 |

> **注意**：DevTools 仅建议在开发环境使用，生产环境应移除此注解。

---

## @EnableConfigServer — 启用配置中心客户端

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableConfigServer

@SpringBootApplication
@EnableConfigServer(
    uri="http://config-server:8888",
    profile="prod",
    fail_fast=True,
)
class Application:
    pass
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `uri` | `str` | `'http://localhost:8888'` | 配置中心地址 |
| `profile` | `str` | `None` | 环境名（默认读取 `spring.profiles.active`） |
| `label` | `str` | `'master'` | 分支/标签 |
| `fail_fast` | `bool` | `False` | 拉取失败是否快速失败 |
| `backend` | `str` | `'http'` | 后端类型（`'http'` 或 `'file'`） |

### 本地文件后端（开发环境）

```python
@SpringBootApplication
@EnableConfigServer(backend="file")
class Application:
    pass
```

配置文件目录结构：
```
config-repo/
  ├── application.yml          # 全局配置
  ├── application-dev.yml      # dev 环境配置
  ├── myapp.yml                # 应用配置
  └── myapp-dev.yml            # 应用+环境配置
```

### 配置刷新

```bash
# 调用 Actuator 端点触发刷新
curl -X POST http://localhost:8080/actuator/refresh
```

---

## @EnableBus — 启用事件总线

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableBus

@SpringBootApplication
@EnableBus(backend="rabbitmq", destination="myBus")
class Application:
    pass
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `destination` | `str` | `'springCloudBus'` | 消息目标（topic/exchange 名） |
| `backend` | `str` | `'local'` | 后端类型（`'local'`/`'rabbitmq'`/`'kafka'`） |

### 广播配置刷新

```bash
# 广播刷新事件到所有服务实例
curl -X POST http://localhost:8080/actuator/busrefresh
```

### 代码中发布/订阅事件

```python
from spring.cloud.bus import event_bus, BusEvent

# 订阅事件
event_bus.subscribe('refreshConfig', lambda e: print('Refreshing...'))

# 发布事件
event_bus.publish(BusEvent(type='refreshConfig', data={'keys': ['app.name']}))
```

---

## @EnableBatchProcessing — 启用批处理

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableBatchProcessing

@SpringBootApplication
@EnableBatchProcessing
class Application:
    pass
```

### 自动执行 Job

```python
@SpringBootApplication
@EnableBatchProcessing(job_names=["importUsers"], auto_run=True)
class Application:
    pass
```

### 定义批处理作业（使用 @BatchJob / @BatchStep）

```python
from spring.annotations import BatchJob, BatchStep
from spring.batch import Step, CsvItemReader, ListItemWriter, FunctionItemProcessor

@BatchJob(name="importUsers", description="导入用户数据")
class ImportUserJob:
    @BatchStep(name="readCsv", chunk_size=100)
    def read_csv_step(self):
        reader = CsvItemReader("users.csv")
        processor = FunctionItemProcessor(lambda row: {"name": row[0], "email": row[1]})
        writer = ListItemWriter()
        return Step("readCsv", reader, processor, writer, chunk_size=100)
```

---

## @EnableDataRest — 启用 Data REST

### 基本用法

```python
from spring.annotations import SpringBootApplication, EnableDataRest, RepositoryRestResource

@SpringBootApplication
@EnableDataRest(base_path="/api/v1", default_page_size=50)
class Application:
    pass

@RepositoryRestResource(path="users", entity_class=User)
class UserRestController:
    def find_all(self, pageable):
        return [...]

    def find_by_id(self, id):
        return ...

    def save(self, entity):
        return ...

    def delete_by_id(self, id):
        ...
```

### 参数说明

#### @EnableDataRest

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_path` | `str` | `''` | REST 端点基础路径 |
| `default_page_size` | `int` | `20` | 默认分页大小 |
| `max_page_size` | `int` | `1000` | 最大分页大小 |

#### @RepositoryRestResource

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | `str` | — | REST 路径（如 `'users'` → `/api/users`） |
| `entity_class` | `Type` | `None` | 实体类 |
| `id_type` | `type` | `int` | ID 字段类型 |
| `exported` | `bool` | `True` | 是否暴露为 REST |

### 自动生成的端点

```
GET    /api/v1/users              列表（支持 ?page=0&size=20&sort=name,asc）
GET    /api/v1/users/{id}         详情
POST   /api/v1/users              创建
PUT    /api/v1/users/{id}         更新
DELETE /api/v1/users/{id}         删除
```

---

## @BatchJob / @BatchStep — 批处理作业定义

### @BatchJob 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | 作业名称（必须唯一） |
| `description` | `str` | `''` | 作业描述 |
| `restartable` | `bool` | `True` | 是否允许重启失败的作业 |

### @BatchStep 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | 步骤名称 |
| `chunk_size` | `int` | `10` | 分块大小 |
| `retry_limit` | `int` | `0` | 最大重试次数 |
| `skip_limit` | `int` | `0` | 最大跳过次数 |

### 完整示例

```python
@BatchJob(name="dataPipeline", description="数据ETL管道")
class DataPipelineJob:
    @BatchStep(name="extract", chunk_size=500)
    def extract_step(self):
        reader = CsvItemReader("input.csv")
        writer = ListItemWriter()
        return Step("extract", reader, None, writer, chunk_size=500)

    @BatchStep(name="transform", chunk_size=100, retry_limit=3)
    def transform_step(self):
        reader = ListItemReader(extracted_data)
        processor = FunctionItemProcessor(transform_record)
        writer = ListItemWriter()
        return Step("transform", reader, processor, writer, chunk_size=100, retry_limit=3)

    @BatchStep(name="load", chunk_size=200, skip_limit=10)
    def load_step(self):
        reader = ListItemReader(transformed_data)
        writer = CsvItemWriter("output.csv")
        return Step("load", reader, None, writer, chunk_size=200, skip_limit=10)
```

---

## @RepositoryRestResource — Repository REST 资源

### 基本用法

```python
@RepositoryRestResource(path="users", entity_class=User)
class UserRestController:
    """自动暴露为 /api/users 的 CRUD REST API"""
    def find_all(self, pageable=None):
        return [...]

    def find_by_id(self, id):
        return user

    def save(self, entity):
        return saved_entity

    def delete_by_id(self, id):
        pass
```

### 禁用暴露

```python
@RepositoryRestResource(path="internal", entity_class=InternalData, exported=False)
class InternalRepo:
    """exported=False 时不注册 REST 端点"""
    pass
```

### 字符串 ID 类型

```python
@RepositoryRestResource(path="products", entity_class=Product, id_type=str)
class ProductRepo:
    pass
```

---

## 多注解组合使用

所有 `@EnableXxx` 注解可以组合使用，标记在同一个主类上：

```python
from spring.annotations import (
    SpringBootApplication,
    EnableOAuth2,
    EnableCsrf,
    EnableDevTools,
    EnableConfigServer,
    EnableBus,
    EnableBatchProcessing,
    EnableDataRest,
)

@SpringBootApplication
@EnableOAuth2(issuer="https://auth.example.com", algorithms=["RS256"])
@EnableCsrf(secure_cookie=True)
@EnableDevTools(watch_dirs=["src"])
@EnableConfigServer(uri="http://config:8888", fail_fast=True)
@EnableBus(backend="rabbitmq")
@EnableBatchProcessing
@EnableDataRest(base_path="/api/v1")
class Application:
    pass
```

### 注解与配置文件共存

```python
# 注解启用功能 + 配置文件提供详细参数
@SpringBootApplication
@EnableOAuth2  # 仅启用，参数从配置文件读取
class Application:
    pass
```

```yaml
# application.yml 提供详细参数
spring:
  security:
    oauth2:
      issuer: https://auth.example.com
      audiences: [my-api]
      algorithms: [RS256]
      jwks_uri: https://auth.example.com/.well-known/jwks.json
```

---

## 与 Java Spring Boot 的对照

| Java Spring Boot | SpringBootAI | 差异说明 |
|------------------|--------------|----------|
| `@EnableResourceServer` | `@EnableOAuth2` | Java 通过 SecurityConfig 链式配置，Python 通过注解参数 |
| `http.csrf().enable()` | `@EnableCsrf` | Java 通过 JavaConfig，Python 通过注解 + Double Submit Cookie |
| `spring-boot-devtools` 依赖 | `@EnableDevTools` | Java 自动启用，Python 显式注解 |
| `spring-cloud-starter-config` | `@EnableConfigServer` | Java 通过依赖自动配置，Python 通过注解 |
| `spring-cloud-starter-bus-amqp` | `@EnableBus` | Java 通过依赖自动配置，Python 通过注解 |
| `@EnableBatchProcessing` | `@EnableBatchProcessing` | 两者一致 |
| `@RepositoryRestResource` | `@RepositoryRestResource` | 两者一致，Python 额外需要 `@EnableDataRest` |
| `@Job` / `@Step` | `@BatchJob` / `@BatchStep` | 命名略不同，功能对齐 |

---

## 常见问题

### Q: 注解和配置文件同时存在时，谁优先？

**注解参数优先**。如果注解中指定了参数值，会覆盖配置文件中的对应项。未在注解中指定的参数仍从配置文件读取。

### Q: 生产环境可以用 @EnableDevTools 吗？

**不建议**。DevTools 会启动文件监视线程，增加性能开销。生产环境应移除此注解，或通过 `@Profile("dev")` 限制仅在开发环境生效。

### Q: @EnableDataRest 需要配合 @RepositoryRestResource 使用吗？

**是的**。`@EnableDataRest` 启用 Data REST 功能，`@RepositoryRestResource` 标记具体哪些 Repository 需要暴露为 REST API。两者缺一不可。

### Q: @EnableBus 的 local 后端能用于生产吗？

**不能**。`local` 后端仅在单进程内传播事件，无法跨服务实例广播。生产环境应使用 `rabbitmq` 或 `kafka` 后端。

### Q: 如何在测试中验证注解是否生效？

```python
from spring.annotations.core import get_spring_annotations
from spring.annotations import EnableOAuth2

@EnableOAuth2(issuer="https://test.com")
class App:
    pass

# 验证注解已添加
annotations = get_spring_annotations(App)
assert any(isinstance(ann, EnableOAuth2) for ann in annotations)
```
