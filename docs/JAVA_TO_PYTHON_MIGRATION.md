# Java Spring Boot / Spring Cloud Alibaba 到 SpringPy 迁移指南

本文说明如何把现有的 Java Spring Boot、Spring Cloud Alibaba 和 MyBatis 分层代码迁移到本仓库的 SpringPy。目标是保留清晰的 Controller / Service / Mapper 边界、配置习惯和常用注解意图，而不是让 Python 运行 Java 代码。

SpringPy 运行在 Python、FastAPI 和 DB-API 驱动之上。Java 的字节码代理、JVM 事务管理器、Spring Data JPA、Maven/Gradle 插件和 Java MyBatis 插件都不能直接复用。

## 1. 迁移原则

1. 先迁移接口契约和测试，再迁移框架注解。
2. Python 使用类型标注、Pydantic 和显式依赖，比模拟 Java 反射更可靠。
3. 只有由 `ApplicationContext` 创建的 Bean 才会获得事务、缓存、重试等 AOP 行为；手工 `ClassName()` 创建的对象不受容器管理。
4. Java 中的 XML SQL 可以大部分保留，但数据库函数、分页、类型名和连接配置需要按目标 Python 驱动验证。
5. 不把“有同名注解”理解为“与 Java 完全等价”。本文每一项都标注了当前边界。

## 2. 项目结构对照

| Java Spring Boot | SpringPy |
|---|---|
| `src/main/java/com/acme/Application.java` | `acme/Application.py` |
| `src/main/resources/application.yml` | `acme/application.yml` 或 `acme/config/application.yml` |
| `controller/` | `acme/controller/` |
| `service/` | `acme/service/` |
| `mapper/` 和 `resources/mapper/` | `acme/mappers/` 和同目录/配置指定的 XML |
| `@SpringBootTest` | `unittest` / `pytest` + SQLite 或真实数据库集成环境 |
| `mvn spring-boot:run` | `python -m acme.Application` 或 `uvicorn asgi:app` |

每一个 Python 包目录都需要 `__init__.py`。`scan_base_packages` 和 `@MapperScan` 接受的是可导入包名，例如 `acme.service`，不是文件系统路径。

## 3. 启动和依赖注入

### 3.1 启动类

Java：

```java
@SpringBootApplication(scanBasePackages = "com.acme")
public class Application {
  public static void main(String[] args) {
    SpringApplication.run(Application.class, args);
  }
}
```

Python：

```python
from spring.annotations import SpringBootApplication
from spring.main import run


@SpringBootApplication(scan_base_packages=["acme"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

### 3.2 Bean 注解映射

| Java 注解 | SpringPy 写法 | 行为和边界 |
|---|---|---|
| `@Component` | `@Component` | 受管单例 Bean。 |
| `@Service` | `@Service` | 受管业务 Bean。 |
| `@Repository` | `@Repository` | 受管数据访问 Bean；它不同于 MyBatis 的 `@Mapper`。 |
| `@RestController` | `@RestController` | 注册 FastAPI JSON 路由。 |
| `@Controller` | `@Controller` | 当前仍按 API 响应处理，不提供 Java MVC 模板视图语义。 |
| `@Configuration` + `@Bean` | 同名注解 | 支持工厂方法、scope 和生命周期回调。 |
| `@Primary` | `@Primary` | 多候选 Bean 的默认注入目标。 |
| `@Qualifier("name")` | `@Qualifier("name")` | 作为构造方法元数据使用；复杂逐参数歧义应拆分依赖。 |
| `@Profile` | `@Profile` | 筛选 Bean，不自动合并 `application-{profile}.yml`。 |
| `@Lazy` | `@Lazy` | 首次需要 Bean 时才创建。 |

推荐构造器注入，并用 Python 类型标注表达依赖：

```python
from spring.annotations import Autowired, Service
from acme.mappers.UserMapper import UserMapper


@Service
class UserService:
    @Autowired
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper
```

### 3.3 配置

Java `@Value("${client.timeout}")` 对应把 `Value` 放在参数默认值：

```python
from spring.annotations import Component, Value


@Component
class RemoteClient:
    def __init__(self, timeout: int = Value("client.timeout")):
        self.timeout = timeout
```

`@ConfigurationProperties(prefix = "client")` 对应：

```python
from spring.annotations import Component, ConfigurationProperties


@ConfigurationProperties(prefix="client")
@Component
class ClientProperties:
    endpoint = ""
    timeout = 5
```

YAML 支持 `${NAME:default}`。完整占位符会保留 `bool`、`int` 和 `None` 等标量类型；没有默认值的环境变量未设置时会启动失败。

## 4. Web 层迁移

| Java Spring MVC | SpringPy |
|---|---|
| `@RequestMapping` | `@RequestMapping`，可标在类和方法上 |
| `@GetMapping` / `@PostMapping` | 同名注解 |
| `@PutMapping` / `@PatchMapping` / `@DeleteMapping` | 同名注解 |
| `@PathVariable` | 参数默认值 `PathVariable("id")` |
| `@RequestParam` | 参数默认值 `RequestParam("page", required=False, default=1)` |
| `@RequestBody` | 参数默认值 `RequestBody()` |
| `@RequestHeader` / `@CookieValue` | 同名参数标记 |
| `@ControllerAdvice` / `@ExceptionHandler` | 同名注解 |
| `@ResponseStatus` | 同名注解 |
| `HandlerInterceptor` | 继承 `HandlerInterceptor` 并标记 `@Component` | 自动接入 FastAPI 请求生命周期；支持同步/异步 `pre_handle`、`post_handle`、`after_completion` 和 `/api/**` 路径规则。 |

```python
from pydantic import BaseModel
from spring.annotations import (
    GetMapping, PathVariable, PostMapping, RequestBody, RequestMapping,
    RestController, Valid,
)


class CreateUserRequest(BaseModel):
    name: str
    email: str


@RequestMapping("/users")
@RestController
class UserController:
    @GetMapping("/{user_id}")
    def get_one(self, user_id: int = PathVariable("user_id")):
        return {"id": user_id}

    @PostMapping("")
    def create(self, body: CreateUserRequest = Valid()):
        return {"name": body.name, "email": body.email}
```

`@Valid` 和 `@Validated` 会把该参数识别为 request body；实际字段校验由 FastAPI/Pydantic 的模型和约束完成。Java Bean Validation group 的完整语义目前只保留为元数据，不应依赖它做分组校验。

拦截器示例：

```python
from spring.annotations import Component
from spring.web.interceptor import HandlerInterceptor


@Component
class AuditInterceptor(HandlerInterceptor):
    async def pre_handle(self, request, handler):
        request.state.started = True
        return True

    def after_completion(self, request, response, handler, exception=None):
        # 记录状态、耗时或异常
        pass
```

需要显式路径范围时，将 `InterceptorRegistry` 传给 `WebApplicationContext`，并使用 `include_path_patterns('/api/**')` / `exclude_path_patterns('/api/public/**')`。`pre_handle` 返回 `False` 时请求以 403 结束。

## 5. AOP、任务和本地事务

| Java 能力 | SpringPy | 注意事项 |
|---|---|---|
| `@Transactional` | `@Transactional` | 支持 `REQUIRED`、`REQUIRES_NEW`、`NESTED`、`SUPPORTS`、`MANDATORY`、`NOT_SUPPORTED`、`NEVER`。`REQUIRES_NEW` 使用独立 Session/连接，连接池必须能同时提供外层和内层连接。 |
| `@Cacheable` | `@Cacheable` | 本地缓存默认 TTL 300 秒；Redis 后端需要额外部署。 |
| Spring Retry `@Retryable` | `@Retryable` | `max_retries` 包含首次调用，只应用于幂等操作。 |
| `@Async` | `@Async` | 返回 `Future` / `Task`；不会继承调用线程的数据库事务。 |
| `@Scheduled` | `@Scheduled` | 每个 worker 都会调度，分布式部署需自行选主或加锁。 |
| `@PostConstruct` / `@PreDestroy` | 同名注解 | 依赖正常容器启动和关闭。 |

```python
from spring.annotations import Autowired, Service, Transactional


@Service
class OrderService:
    @Autowired
    def __init__(self, order_mapper, audit_mapper):
        self.order_mapper = order_mapper
        self.audit_mapper = audit_mapper

    @Transactional(rollback_for=[Exception])
    def create(self, command):
        order_id = self.order_mapper.insert(command)
        self.audit_mapper.insert({"action": "ORDER_CREATED", "order_id": order_id})
        return order_id
```

`NESTED` 适合允许内层失败被捕获的场景：内层会回滚到 savepoint，外层仍可提交。普通嵌套 `REQUIRED` 保持 Java 常见的 rollback-only 语义，内层失败即使被业务代码捕获，外层提交也会失败。

## 6. MyBatis 到 PyMyBatis

### 6.1 Mapper 注解

Java：

```java
@Mapper
public interface UserMapper {
  @Select("select id, name from users where id = #{id}")
  User findById(@Param("id") long id);

  @Options(useGeneratedKeys = true, keyProperty = "id")
  @Insert("insert into users(name) values(#{user.name})")
  int insert(@Param("user") User user);
}
```

Python：

```python
from dataclasses import dataclass
from typing import Optional
from spring.orm import Insert, Mapper, Param, Select


@dataclass
class User:
    name: str
    id: Optional[int] = None


@Mapper
class UserMapper:
    @Select("SELECT id, name FROM users WHERE id = #{id}")
    def find_by_id(self, id: int) -> Optional[User]:
        pass

    @Insert(
        "INSERT INTO users(name) VALUES (#{user.name})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, user: User) -> int:
        pass
```

Mapper 方法主体保持 `pass`，运行时由代理执行 SQL。带类型标注的单条返回值会映射成对象；`list[User]` 返回值会映射成对象列表。未标注返回类型时，查询默认返回 `dict` 或 `list[dict]`。`@Param` 支持 `typing.Annotated` 的参数别名，也会保留原始参数名。

### 6.2 XML 功能矩阵

| Java MyBatis XML | SpringPy 状态 | 说明 |
|---|---|---|
| `<select>` / `<insert>` / `<update>` / `<delete>` | 支持 | `id` 必须在 namespace 中唯一。 |
| `<resultMap>` 的 `<id>`、`<result>` | 支持 | 支持列到属性、继承 `extends` 和目标类型构造。 |
| `<sql>` + `<include>` | 支持 | 支持 `<property name="..." value="..."/>` 替换片段变量。 |
| `<if>`、`<where>`、`<set>`、`<trim>` | 支持 | OGNL 是受限安全子集。 |
| `<choose>` / `<when>` / `<otherwise>` | 支持 | 只选择第一条成立分支。 |
| `<foreach>` | 支持 | 支持 sequence、set、mapping 和对象/字典嵌套属性，最多 1000 项。 |
| `<bind>` | 支持 | 支持受限表达式派生参数，例如 LIKE pattern。 |
| `resultType` | 支持 | 标量别名和全限定 Python 类型；未限定的自定义类型仍返回字典。 |
| `fetchSize`、`timeout`、`useCache`、`flushCache` | 支持 | 语句级配置会进入执行链。 |
| `useGeneratedKeys`、`keyProperty`、`keyColumn` | 支持 | 支持 DB-API `lastrowid` 的驱动；数据库仍需验证。 |
| `<association>` / `<collection>` / discriminator | 支持 | 支持嵌套 `resultMap`、内联嵌套映射和 `select` 嵌套查询；集合结果按每个外层行映射。 |
| `<selectKey>` | 支持 | 支持 `BEFORE/AFTER`、`keyProperty`、`keyColumn` 和 `resultType`，结果会回填参数对象/字典。 |
| `databaseId` | 支持 | 按 `Configuration.dialect` 选择匹配数据库语句；匹配的数据库语句优先于通用语句。 |
| `@SelectProvider` / `@InsertProvider` / `@UpdateProvider` / `@DeleteProvider` | 支持 | Provider 可为 Python 函数、类方法或全限定名称，必须返回非空 SQL 字符串。 |
| Java MyBatis plugin / executor | 不兼容 | 使用 Python `Interceptor`，并为实际驱动写集成测试。 |

安全规则不变：业务值一律使用 `#{name}`；`${name}` 默认拒绝，只有显式开启且通过白名单后才适合表名、字段名等固定标识符。不要把 HTTP 参数直接传入 `${...}`。

### 6.3.1 嵌套结果映射

```xml
<resultMap id="bookMap" type="acme.models.Book">
  <id column="book_id" property="id"/>
  <result column="title" property="title"/>
  <association property="author" resultMap="authorMap"/>
  <collection property="tags" select="findTags" column="book_id"/>
</resultMap>
```

`association` 可以使用 `resultMap`（同一行 JOIN 映射）或 `select`（以 `column` 值作为参数执行另一个 statement）。`collection` 的 `select` 返回列表；使用 JOIN 的集合需要在 Service 层按主键去重聚合，这是与 MyBatis `resultOrdered` 相同的工程注意事项。

### 6.3.2 SelectProvider

```python
class UserSql:
    @staticmethod
    def by_keyword(params):
        return "SELECT id, name FROM users WHERE name LIKE #{keyword}"


class UserMapper:
    @SelectProvider(UserSql, method="by_keyword")
    def search(self, keyword: str) -> list[dict]:
        pass
```

Provider 只负责生成 SQL，参数仍然经过动态 SQL 处理和 TypeHandler 转换；不要在 Provider 中拼接不可信的表名或值。

### 6.4 XML 示例

```xml
<mapper namespace="acme.mappers.UserMapper">
  <sql id="columns">id, name, created_at</sql>

  <select id="search" resultMap="userMap" fetchSize="100" useCache="true">
    SELECT <include refid="columns"/> FROM users
    <bind name="pattern" value="'%' + keyword + '%'" />
    <where>
      <if test="keyword != null and keyword != ''">
        AND name LIKE #{pattern}
      </if>
    </where>
  </select>

  <insert id="insert" useGeneratedKeys="true" keyProperty="user.id">
    INSERT INTO users(name, created_at) VALUES (#{user.name}, #{user.created_at})
  </insert>
</mapper>
```

SQLite 使用 `:memory:` 时框架会强制单连接，因为多个内存连接是不同数据库。生产应用应使用文件 SQLite 或真实 MySQL/PostgreSQL，并为每个 worker 计算连接池总容量。

## 7. Spring Cloud Alibaba 对照

| Java 注解/组件 | SpringPy 对应 | 当前状态 |
|---|---|---|
| `@EnableDiscoveryClient` + Nacos | `@EnableDiscoveryClient` + `discovery` 配置 | 注解元数据与 Nacos 客户端配置可用；需部署 Nacos 并做注册/发现集成测试。 |
| `@NacosValue` / `@RefreshScope` | 同名注解 | 元数据可用；`@RefreshScope` 已接入容器刷新机制，复杂配置刷新和 Java proxy 语义不等价。 |
| `@EnableFeignClients` / `@FeignClient` | 同名注解 + `spring.cloud.feign` | 主要用于客户端元数据和 HTTP 调用；不兼容 Java interface proxy。Feign调用自动传播 XID 和 trace 头。 |
| `@LoadBalanced` | 同名注解 | 使用 Python 负载均衡实现；不要复用 `RestTemplate` 用法。 |
| Sentinel `@SentinelResource` | 同名注解 | 已内嵌限流熔断引擎，支持 QPS 限流、异常比例/异常数/慢调用熔断、热点参数限流，无需 Dashboard；如需更强大治理能力可对接外部 Sentinel Dashboard。 |
| Spring Cloud Gateway | `@EnableGateway` + `GatewayRouter` | 内嵌轻量 ASGI/WSGI 网关，支持路由转发、路径重写、过滤器链、负载均衡；复杂网关需求可使用 Kong/APISIX 等专业网关。 |
| Seata `@GlobalTransactional` | 同名注解 | 已内嵌 HTTP-AT 模式分布式事务协调器，无需 Seata Server 即可使用，XID 自动通过 Feign 传播；如需更强一致性保障可对接外部 Seata Server。 |

Python 服务之间优先使用标准 HTTP、消息队列和 OpenTelemetry 约定。不要把 Java Feign fallback、Reactor Context 或 Seata 的线程上下文假定为可自动迁移。

## 8. 配置迁移

```yaml
spring:
  application:
    name: order-service

database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./order.db
  min_size: 1
  max_size: 10
  mapper_locations:
    - acme/mappers/*.xml
  security:
    block_ddl: true
    sql_injection_detection: true
    allow_raw_params: false

discovery:
  enabled: false

server:
  host: 127.0.0.1
  port: 8080
```

Java 的 profile 文件自动合并不是当前功能。部署流程应生成最终 `application.yml`，或显式设置配置路径。数据库 DDL 使用 Alembic、Flyway 或独立迁移任务；线上运行账户不应具有 DDL 权限。

## 9. 验证顺序

1. 创建本地环境：`python -m venv .venv`，然后 `.venv/bin/python -m pip install -e ".[dev]"`。
2. 运行内置契约测试：`.venv/bin/python -m unittest discover -s tests -v`。
3. 用 SQLite 验证 Mapper SQL、事务、动态 SQL 和类型映射。
4. 用目标 MySQL/PostgreSQL/Oracle 版本执行相同测试，特别验证自增主键、事务隔离、超时和连接中断。
5. 启动 ASGI 应用，检查 `/docs`、`/actuator/health/liveness` 和 `/actuator/health/readiness`。
6. 接入 Nacos、RabbitMQ、Redis 等外部中间件，并演练断线、重复投递和回滚。
7. 验证内嵌 Cloud 功能：`@SentinelResource` 限流熔断、`@Trace` 追踪、`@GlobalTransactional` 分布式事务、`GatewayRouter` 网关、`@entity` + `ddl-auto` 自动建表。这些功能无需部署外部 Server，但应在真实流量和故障注入下验证。

本仓库的 [使用说明书](../使用说明书.md) 说明完整运行配置；[企业生产就绪评估](ENTERPRISE_READINESS.md) 列出上线前必须完成的外部验证项。

## 12. Cloud 高级功能迁移对照

| Java Spring Cloud | SpringPy 写法 | 说明 |
|---|---|---|
| Sentinel Dashboard + `@SentinelResource` | `@SentinelResource` | 内嵌引擎，无需Dashboard；支持QPS限流、异常比例/异常数/慢调用熔断、热点参数限流 |
| SkyWalking Agent + OAP Server | `@Trace` + 内嵌Tracer | 原生OpenTelemetry(W3C traceparent)，无需OAP Server；自动注入HTTP/Feign追踪头 |
| Seata Server + `@GlobalTransactional` | `@GlobalTransactional` | 内嵌HTTP-AT模式，无需Seata Server；支持分支注册/提交/回滚，XID自动传播 |
| Spring Cloud Gateway | `GatewayRouter` | 轻量ASGI/WSGI网关，支持路由转发、路径重写、过滤器链、负载均衡 |
| JPA `hibernate.ddl-auto` | `@entity` + `ddl-auto` 配置 | 支持create/update/validate/create-drop；自动扫描实体包，自动建表/添加列/创建索引 |

### 12.1 DDL Auto 迁移示例

Java JPA：
```java
@Entity
@Table(name = "users")
public class User {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(nullable = false, unique = true)
    private String username;
    
    private String email;
}
```

SpringPy：
```python
from spring.orm import entity, Index

@entity("users", indexes=[
    Index("idx_username", ["username"], unique=True),
])
class User:
    def __init__(self, id: int = None, username: str = "", email: str = ""):
        self.id = id
        self.username = username
        self.email = email
```

application.yml 配置：
```yaml
database:
  ddl-auto:
    mode: update  # 对应 spring.jpa.hibernate.ddl-auto=update
    entity_packages: app.entity
```
