# SpringPy

SpringPy 是一个借鉴 Spring Boot 编程模型的 Python Web 框架，提供装饰器式组件扫描、依赖注入、FastAPI 路由、配置加载、安全能力，以及内嵌的 PyMyBatis ORM。

- SpringPy 版本：`1.3.0`
- 内嵌 PyMyBatis 版本：`1.3.0`
- Python：3.8+
- 状态：Beta
- 仓库：[GitHub - YUCONGGEN/springboot_cloud_python](https://github.com/YUCONGGEN/springboot_cloud_python)

当前版本适合内部试点、教学和可控的低风险服务，不能直接视为成熟 Java Spring Boot + MyBatis 生态的等价替代。生产采用前请阅读[企业生产就绪评估](docs/ENTERPRISE_READINESS.md)。

## 能力状态

| 模块 | 状态 | 说明 |
|------|------|------|
| IoC 容器 | 可用 | 组件扫描、构造器/字段注入、Bean、延迟初始化、生命周期回调、Profile 过滤 |
| Web MVC | 可用 | 基于 FastAPI 的 GET/POST/PUT/PATCH/DELETE 路由、参数绑定、异常处理、CORS 和静态文件 |
| 配置 | 可用 | YAML、`${ENV:default}`、固定环境变量覆盖、标量类型保留；全局加载器与应用上下文共享配置路径和状态 |
| 应用事件 | 可用 | `ApplicationEvent`、`@EventListener`、同步有序发布和异步监听方法调度 |
| 内嵌 ORM | 可用 | PyMyBatis 1.3.0，支持 XML 语句选项、嵌套 resultMap、selectKey、databaseId、Provider、受限 `bind` 和安全动态 SQL |
| 本地事务 | 可用 | `@Transactional` 支持七种 Spring 传播模式；`REQUIRES_NEW`/`NOT_SUPPORTED` 需要连接池可提供额外连接 |
| JWT 与方法安全 | 可用 | access/refresh token、`@Authenticate`、角色/权限授权、401/403 映射和并发上下文隔离 |
| 重试/异步 | 可用 | 受管 Bean 的退避重试、恢复方法和 Future/Task 异步调度 |
| Redis/缓存 | 可选 | 需要 Redis 服务和 `redis` extra |
| RabbitMQ | 可选可用 | `@RabbitListener` 自动注册并后台消费，`RabbitTemplate` 发送；需要 pika、服务和集成测试 |
| Nacos/Prometheus | 可选可用 | Nacos 支持认证客户端和 Windows Docker；Nacos 2.2+ 必须配置 token/identity，仍需真实服务集成测试 |
| Seata/SkyWalking | 实验性 | 不能仅凭注解认定已具备生产语义 |
| 高级 AOP | 部分可用 | 限流、熔断、幂等、审计等需按实际后端逐项验证 |

## 安装

```bash
cd springboot
python -m pip install -e .
```

核心安装已经包含内嵌 `spring.orm.pymybatis`，使用 Mapper 模式不需要再安装独立 `pymybatis`。

按数据库或组件安装 extras：

```bash
python -m pip install -e ".[mysql]"
python -m pip install -e ".[postgresql]"
python -m pip install -e ".[sqlalchemy]"
python -m pip install -e ".[redis]"
python -m pip install -e ".[rabbitmq]"
python -m pip install -e ".[nacos]"
python -m pip install -e ".[prometheus,logging]"
python -m pip install -e ".[dev]"
```

`requirements.txt` 是仓库的完整开发环境，包含多种数据库和中间件客户端。应用接入时优先按需安装 extras。

## 最小应用

仓库中的 `example`、`example1`、`example5` 只用于源码参考和回归验证，不会打包进 `springpy`。安装后请按下面结构创建自己的应用包，不要从 site-packages 导入这些示例。

先创建可导入的包结构（每个包目录包含空的 `__init__.py`）：

```text
demo/
|-- __init__.py
|-- Application.py
|-- application.yml
`-- controller/
    |-- __init__.py
    `-- HelloController.py
```

创建 `demo/Application.py`：

```python
from spring.annotations import SpringBootApplication
from spring.main import run


@SpringBootApplication(scan_base_packages=["demo"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

创建 `demo/controller/HelloController.py`：

```python
from spring.annotations import GetMapping, RequestMapping, RestController


@RequestMapping("/api")
@RestController
class HelloController:
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
```

创建 `demo/application.yml`：

```yaml
server:
  host: 127.0.0.1
  port: 8080

redis:
  enabled: false

database:
  enabled: false

jwt:
  secret_key: development-only-secret
```

运行和验证：

```bash
python -m demo.Application
curl http://127.0.0.1:8080/api/hello/Alice
curl http://127.0.0.1:8080/actuator/health/liveness
curl http://127.0.0.1:8080/actuator/info
```

交互式 API 文档由 FastAPI 提供，默认访问 `http://127.0.0.1:8080/docs`。

## 生产 ASGI 入口

开发时可以使用 `run()`；生产进程管理应使用 `create_app()` 构建 ASGI 应用：

```python
# asgi.py
from spring.main import create_app
from demo.Application import Application

app = create_app(Application)
```

```bash
uvicorn asgi:app --host 0.0.0.0 --port 8080 --workers 2
```

多 worker 会创建多个独立进程、IoC 容器和连接池。连接池总量应按 `worker 数 x max_size` 评估。

## 内嵌 PyMyBatis 快速开始

### 1. 配置 SQLite

```yaml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./app.db
  min_size: 1
  max_size: 5
  wait_timeout: 5
  leak_detection_enabled: true
  security:
    block_ddl: true
    sql_injection_detection: true
    allow_raw_params: false
  cache:
    enabled: true
```

应用迁移或初始化阶段需要建表时，应使用独立迁移脚本；运行期保持 `block_ddl: true`。

### 2. 定义 Mapper

```python
# mappers/UserMapper.py
from spring.orm import Delete, Insert, Mapper, Select, Update


@Mapper
class UserMapper:
    @Select("SELECT id, name FROM users WHERE id = #{id}")
    def find_by_id(self, id: int):
        pass

    @Insert("INSERT INTO users(name) VALUES (#{name})")
    def insert(self, name: str):
        pass

    @Update("UPDATE users SET name = #{name} WHERE id = #{id}")
    def update(self, id: int, name: str):
        pass

    @Delete("DELETE FROM users WHERE id = #{id}")
    def delete(self, id: int):
        pass
```

### 3. 扫描 Mapper

```python
from spring.annotations import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["myapp"])
@MapperScan(base_packages=["myapp.mappers"])
class Application:
    pass
```

Mapper Bean 名按类名转为下划线形式，例如 `UserMapper -> user_mapper`。每次普通 Mapper 调用会自动创建和关闭 Session。

### 4. 在事务中组合调用

```python
from spring.annotations import Autowired, Service, Transactional
from myapp.mappers.UserMapper import UserMapper


@Service
class UserService:
    @Autowired
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper

    @Transactional(rollback_for=[Exception])
    def rename(self, user_id: int, name: str):
        self.user_mapper.update(user_id, name)
        return self.user_mapper.find_by_id(user_id)
```

`@Transactional` 内的多个 Mapper 调用复用同一个 Session，并在方法正常结束时提交、异常时回滚。支持 `propagation="REQUIRED"` 和使用 savepoint 的 `propagation="NESTED"`；其他传播级别会明确报错。

## 独立与内嵌 ORM 的关系

| 场景 | 导入路径 |
|------|----------|
| 独立 ORM 项目 | `from pymybatis import ...` |
| SpringPy 内嵌 ORM | `from spring.orm.pymybatis import ...` |
| Spring 容器集成 | `from spring.orm import Mapper, MapperScan, ...` |

两份 ORM 源码由契约测试约束一致，只允许包内相对导入路径不同。核心 `Configuration`、`SqlSessionFactory`、`SqlSession`、连接池、事务、动态 SQL、安全和缓存行为一致。SpringPy 额外提供 Mapper 扫描、Bean 注册、按调用管理 Session 和事务上下文绑定。

XML Mapper 解析器会在保护 CDATA 和注释的前提下兼容 SQL 文本中的原始 `<=` 与 `>=`，解析后的 SQL 仍保留比较运算符。为了兼容通用 XML 工具，提交到其他解析器的文件仍建议写成 `&lt;=` 和 `&gt;=`。

## 配置规则

应用先从启动类文件所在目录读取 `application.yml`；该文件不存在时，再读取启动类目录下的 `config/application.yml`。两处都存在时以启动类同级文件为准。`ApplicationContext` 启动后会把该路径绑定到稳定的全局加载器，之后新建的 `ConfigLoader()` 也读取同一文件，不再依赖进程当前工作目录。支持：

```yaml
server:
  port: ${SERVER_PORT:8080}
database:
  enabled: ${DB_ENABLED:false}
```

完整占位符会保留标量类型，例如 `8080` 解析为整数，`false` 解析为布尔值，`null` 解析为 `None`。没有默认值的 `${REQUIRED_ENV}` 未设置时会直接报错。

### 环境变量配置（三层优先级）

框架采用**环境变量 > application.yml > 函数默认值**三层配置架构：

```bash
# 数据库配置（支持环境变量覆盖）
export DB_HOST=mysql.prod.svc.cluster.local
export DB_PORT=3306
export DB_NAME=springpy
export DB_USERNAME=root
export DB_PASSWORD=your_password
export DB_DRIVER=mysql

# 中间件配置
export REDIS_HOST=redis.prod.svc.cluster.local
export REDIS_PORT=6379
export RABBITMQ_HOST=rabbitmq.prod.svc.cluster.local
export DISCOVERY_SERVER_ADDR=nacos.prod.svc.cluster.local:8848

# Docker开发环境辅助
export SPRING_DISABLE_DOCKER_IP_DETECT=1  # 生产环境禁用Docker IP自动检测
```

### Docker 容器IP自动检测（开发环境）

开发环境中，当 `host=127.0.0.1` 或 `localhost` 时，框架会自动调用 `docker inspect` 获取容器内部IP进行连接，无需手动配置容器IP。设置 `SPRING_DISABLE_DOCKER_IP_DETECT=1` 可禁用此功能。

常用覆盖变量：

```text
SPRING_PROFILES_ACTIVE  STARTUP_FAIL_FAST
SERVER_HOST             SERVER_PORT
JWT_SECRET_KEY          JWT_ALGORITHM
DB_ENABLED              DB_URL
REDIS_ENABLED           REDIS_HOST        REDIS_PORT
DISCOVERY_ENABLED       NACOS_SERVER      NACOS_NAMESPACE
NACOS_GROUP             NACOS_USERNAME    NACOS_PASSWORD
CORS_ALLOW_ORIGINS      CORS_ALLOW_CREDENTIALS
LOG_LEVEL               LOG_DIR
```

当前 `SPRING_PROFILES_ACTIVE` 用于 `@Profile` 组件筛选和生产安全校验，不会自动合并 `application-prod.yml`。需要多环境文件时，由部署流程生成最终 `application.yml` 或显式传入配置路径。

## 健康检查

| 地址 | 用途 |
|------|------|
| `/actuator/health` | 聚合组件健康状态；降级时返回 503 |
| `/actuator/health/liveness` | 进程存活检查 |
| `/actuator/health/readiness` | 服务就绪检查 |
| `/actuator/info` | 应用名称、当前 Profile、框架和 Python 版本 |

生产探针应区分 liveness 和 readiness，避免依赖组件短暂故障导致进程反复重启。`database.enabled: false` 时数据库状态为 `DISABLED`，不会初始化默认 SQLite、不会创建 `test.db`，也不会虚报为 `UP`。

## 常用 API 易错点

JWT 既可使用全局配置，也可创建隔离实例：

```python
from spring.security.jwt_utils import JwtUtils, jwt_utils

token = jwt_utils.generate_token({"sub": "user-1"})
same_global_token = JwtUtils.generate_token({"sub": "user-2"})
payload = JwtUtils.verify_token(token)
assert payload["sub"] == "user-1"

tenant_jwt = JwtUtils(secret_key="at-least-32-characters-for-tenant-a")
tenant_token = tenant_jwt.generate_token({"sub": "tenant-user"})
```

`JwtUtils.generate_token(...)` 类调用使用已由应用配置初始化的全局实例；`JwtUtils(...)` 实例调用使用该实例自己的密钥。`verify_token(token)` 和 `decode_token(token)` 都返回校验后的 payload，无效时抛异常；`validate_token(token)` 只返回布尔值。不要混用不同实例生成和校验的 token。

重试注解的次数包含第一次调用：

```python
from spring.annotations import Retryable

@Retryable(value=(ConnectionError,), max_retries=3, backoff=500)
def request_remote_service(self):
    ...
```

`max_retries=3` 表示总共最多调用 3 次，`backoff=500` 表示固定等待 500 毫秒。旧名称 `max_attempts=3` 仍兼容，但新代码统一使用 `max_retries`。只对幂等操作开启自动重试。

## 安全基线

- 生产环境设置 `SPRING_PROFILES_ACTIVE=production` 和 `STARTUP_FAIL_FAST=true`。
- `JWT_SECRET_KEY` 使用至少 32 字符的随机密钥；生产环境会拒绝默认弱密钥。
- `CORS_ALLOW_CREDENTIALS=true` 时不能使用 `*` 来源。
- SQL 值始终使用 `#{name}` 参数绑定；`${name}` 默认禁用。
- 数据库账号按最小权限配置，运行账号不要拥有 DDL 权限。
- TLS 在可信网关或反向代理终止，并配置请求大小、超时和访问日志脱敏。

## 项目结构

```text
springboot/
|-- spring/
|   |-- annotations/       # 核心、云和消息注解
|   |-- context/           # IoC 和 Bean 工厂
|   |-- event/             # 应用事件发布器
|   |-- web/               # FastAPI Web 上下文
|   |-- config/            # YAML 和环境变量
|   |-- orm/               # SQLAlchemy 可选层和内嵌 PyMyBatis
|   |-- security/          # JWT 和权限
|   |-- aop/               # 方法拦截器
|   `-- main.py            # run / create_app
|-- example/               # 完整示例
|-- docs/                  # 部署与生产评估
|-- README.md
`-- 使用说明书.md
```

## 测试

在工作区根目录运行：

```bash
python -m pytest -q tests
```

契约测试覆盖全部公开核心、Cloud、消息和 PyMyBatis 注解的构造/元数据挂载，以及应用事件、日志包装、RabbitMQ 注册契约；同时覆盖独立/内嵌 ORM 源码一致性、共享连接池、七种事务传播、savepoint 回滚、Session 归还清理、Spring Mapper 事务会话复用、嵌套 resultMap、selectKey、databaseId、Provider、JWT、安全配置和 HTTP 错误状态。`example_all/test_all_features.py` 另外包含 Nacos、原始 XML 运算符、PATCH 路由、应用事件和配置同步探针。

SQLite 自动化通过不代表 MySQL、PostgreSQL 或 Oracle 已验证。上线前必须针对实际数据库版本执行集成测试和故障注入。

## 文档

- [详细使用说明书](使用说明书.md)
- [Java 到 Python 迁移指南](docs/JAVA_TO_PYTHON_MIGRATION.md)
- [企业生产就绪评估](docs/ENTERPRISE_READINESS.md)
- [部署指南](docs/DEPLOYMENT.md)
- [注解说明](USAGE.md)

## License

MIT License
