# Spring Python 生产环境部署指南

## 目录

1. [环境要求](#1-环境要求)
2. [基础服务部署](#2-基础服务部署)
   - [Redis](#21-redis)
   - [MySQL](#22-mysql)
   - [Nacos（可选）](#23-nacos可选)
3. [内嵌Cloud功能（无需外部部署）](#3-内嵌cloud功能无需外部部署)
4. [应用配置](#4-应用配置)
5. [启动应用](#5-启动应用)
6. [验证部署](#6-验证部署)
7. [故障排查](#7-故障排查)

---

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.9+ | 推荐 3.12 |
| Redis | 6.0+ | 用于分布式锁、限流、缓存 |
| MySQL | 5.7+ / 8.0+ | 用于业务数据存储 |
| Nacos | 2.0+ | 服务注册发现（可选） |

> **v1.5.0新特性**：Sentinel限流熔断、OpenTelemetry分布式追踪、Seata HTTP-AT分布式事务、API Gateway均已内嵌实现，无需部署外部Server。

---

## 2. 基础服务部署

### 2.1 Redis

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install redis-server

# CentOS/RHEL
sudo yum install redis

# 启动服务
sudo systemctl start redis
sudo systemctl enable redis

# 验证
redis-cli ping
# 应返回: PONG
```

配置文件: `/etc/redis/redis.conf`
- 设置密码: `requirepass your_secure_password`
- 绑定地址: `bind 0.0.0.0`（生产环境注意安全）

### 2.2 MySQL

```bash
# Ubuntu/Debian
sudo apt install mysql-server

# CentOS/RHEL
sudo yum install mysql-community-server

# 启动服务
sudo systemctl start mysqld
sudo systemctl enable mysqld
```

**MySQL 8+ 认证插件说明：**

MySQL 8 默认使用 `caching_sha2_password` 认证插件。如果遇到连接问题，可通过以下方式解决：

```sql
-- 创建应用用户（推荐）
CREATE USER 'spring_python'@'%' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON your_database.* TO 'spring_python'@'%';
FLUSH PRIVILEGES;

-- 如果需要使用 mysql_native_password（不推荐，但兼容性更好）
ALTER USER 'spring_python'@'%' IDENTIFIED WITH mysql_native_password BY 'your_secure_password';
```

**JDBC URL 配置建议：**

```
mysql+pymysql://spring_python:password@localhost:3306/your_database?charset=utf8mb4&allowPublicKeyRetrieval=true&useSSL=false
```

### 2.3 Nacos（可选）

```bash
# 下载 Nacos
wget https://github.com/alibaba/nacos/releases/download/2.3.0/nacos-server-2.3.0.tar.gz
tar -zxvf nacos-server-2.3.0.tar.gz
cd nacos/bin

# 启动 Nacos（单机模式）
./startup.sh -m standalone

# 访问控制台
# http://localhost:8848/nacos
# 默认账号: nacos / nacos
```

#### Windows Docker Desktop

Nacos 2.2.x 使用 Java 8 时，Docker Desktop 的 cgroup v2 可能导致
`ProcessorMetrics` 初始化 NPE。启动容器时注入以下 JVM 参数：

```bash
docker run -d --name springpy-nacos \
  -p 8848:8848 -p 9848:9848 \
  -e MODE=standalone \
  -e NACOS_AUTH_ENABLE=true \
  -e NACOS_AUTH_TOKEN=c3ByaW5ncHktbmFjb3MtaGFuZHNoYWtlLXNlY3JldC0yMDI2LTA4LTA0LTAx \
  -e NACOS_AUTH_IDENTITY_KEY=springpy \
  -e NACOS_AUTH_IDENTITY_VALUE=springpy-local \
  -e JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport \
  nacos/nacos-server:v2.2.3
```

若使用 MySQL 外部存储，还需设置 `SPRING_DATASOURCE_PLATFORM=mysql`、
`MYSQL_SERVICE_*` 连接参数，并先将镜像内的
`/home/nacos/conf/mysql-schema.sql` 导入目标 `nacos` 数据库。

---

## 3. 内嵌Cloud功能（无需外部部署）

SpringPy v1.5.0 内嵌了以下微服务治理功能，无需部署外部Server即可使用。

### 3.1 Sentinel 限流熔断（内嵌引擎）

框架内置Sentinel限流引擎，支持QPS限流、异常比例/异常数熔断、慢调用比例熔断、热点参数限流。

通过注解使用，无需额外部署：

```python
from spring.annotations import SentinelResource

@SentinelResource(value="createOrder", block_handler="handle_block", fallback="handle_fallback")
def create_order(user_id: int, product_id: int):
    # 业务逻辑
    pass

def handle_block(user_id, product_id):
    return {"msg": "请求被限流，请稍后重试"}

def handle_fallback(user_id, product_id):
    return {"msg": "服务降级"}
```

### 3.2 OpenTelemetry 分布式追踪（内嵌）

框架内置OpenTelemetry兼容追踪器，自动生成和传播W3C traceparent标准traceId/spanId，自动注入HTTP请求和Feign调用。

```python
from spring.annotations import Trace

@Trace("order-service.create")
def create_order(user_id: int):
    # 自动创建span，记录traceId
    pass
```

无需部署SkyWalking OAP Server，追踪信息通过日志输出。如需对接Jaeger等后端，可配置exporter。

### 3.3 Seata HTTP-AT 分布式事务（内嵌）

框架内置HTTP-AT模式分布式事务协调器，通过HTTP端点协调跨服务事务，无需部署Seata Server。

```python
from spring.annotations import GlobalTransactional

@GlobalTransactional(timeout=60000)
def place_order(user_id: int, product_id: int):
    # 自动开启分布式事务
    order_service.create(user_id, product_id)
    inventory_service.deduct(product_id)
    # 异常自动回滚所有分支
```

Feign客户端自动传播XID事务ID到下游服务。

### 3.4 API Gateway 网关（内嵌）

框架内置轻量ASGI/WSGI网关，支持路由转发、路径重写、全局过滤器、负载均衡。

```python
from spring.cloud.gateway import GatewayRouter

gateway = GatewayRouter(discovery_client=nacos_discovery)
gateway.route("/api/users/**", "user-service", strip_prefix=True)
```

### 3.5 ORM DDL 自动建表（JPA ddl-auto 风格）

框架支持从实体类自动生成DDL，支持create/update/validate/create-drop模式。

```yaml
database:
  ddl-auto:
    mode: update  # none|validate|update|create|create-drop
    entity_packages: app.entity
```

```python
from spring.orm import entity, Index

@entity("sys_user", indexes=[Index("idx_username", ["username"], unique=True)])
class User:
    def __init__(self, id: int = None, username: str = "", email: str = ""):
        self.id = id
        self.username = username
        self.email = email
```

---

## 4. 应用配置

### 4.1 生产环境配置文件

创建 `application-prod.yml`（可选）：

```yaml
server:
  port: 8080

redis:
  enabled: true
  host: your-redis-host
  port: 6379
  password: your-redis-password

jwt:
  secret_key: your-strong-secret-key-change-in-production
  expires_in: 7200

database:
  enabled: true
  url: mysql+pymysql://user:password@localhost:3306/your_database?charset=utf8mb4
  # DDL Auto 生产环境建议使用 validate 模式
  ddl-auto:
    mode: validate
    entity_packages: app.entity

discovery:
  enabled: true
  server_addr: nacos:8848
  username: ${NACOS_USERNAME}
  password: ${NACOS_PASSWORD}

# 内嵌Cloud功能配置（默认即可，无需外部Server）
# - Sentinel限流熔断：通过 @SentinelResource 注解使用，无需配置
# - OpenTelemetry追踪：通过 @Trace 注解使用，日志输出traceId
# - Seata HTTP-AT分布式事务：通过 @GlobalTransactional 注解使用
# - API Gateway：通过 @EnableGateway + GatewayRouter 使用

logging:
  level: INFO
  log_dir: /var/log/spring-python
```

### 4.2 环境变量配置

推荐使用环境变量覆盖默认配置：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 8080 |
| `REDIS_HOST` | Redis 地址 | localhost |
| `REDIS_PORT` | Redis 端口 | 6379 |
| `REDIS_PASSWORD` | Redis 密码 | null |
| `JWT_SECRET_KEY` | JWT 密钥 | spring-python-secret-key-change-in-production |
| `DB_URL` | 数据库连接 URL | sqlite:///./test.db |
| `DB_DDL_AUTO` | DDL自动建表模式（none/validate/update/create/create-drop） | none |
| `DB_ENTITY_PACKAGES` | 实体类包路径，逗号分隔 | 空 |
| `DISCOVERY_ENABLED` | 是否启用 Nacos 服务发现 | false |
| `NACOS_SERVER` | Nacos 地址 | localhost:8848 |
| `NACOS_USERNAME` | Nacos 客户端账号 | 空 |
| `NACOS_PASSWORD` | Nacos 客户端密码 | 空 |
| `SPRING_DISABLE_DOCKER_IP_DETECT` | 设为1禁用Docker容器IP自动检测 | 0 |

> Sentinel、OpenTelemetry追踪、Seata HTTP-AT、API Gateway 已内嵌实现，不需要对应环境变量启用。

---

## 5. 启动应用

### 5.1 开发模式

```bash
cd your-project
python -m spring.main
```

### 5.2 生产模式

```bash
# 必需的生产配置
export SPRING_PROFILES_ACTIVE=production
export JWT_SECRET_KEY="使用密钥管理系统注入至少32字符的随机值"
export STARTUP_FAIL_FAST=true

# myapp/asgi.py 中创建标准ASGI对象：
# from myapp.Application import Application
# from spring import create_app
# app = create_app(Application)

uvicorn myapp.asgi:app --host 0.0.0.0 --port 8080 --workers 4
```

### 5.3 使用 Gunicorn（推荐）

```bash
# Linux环境安装进程管理器
pip install gunicorn uvicorn

# 使用Uvicorn Worker运行ASGI应用
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080 myapp.asgi:app
```

### 5.4 作为系统服务

创建 `/etc/systemd/system/spring-python.service`：

```ini
[Unit]
Description=Spring Python Application
After=network.target redis.service mysqld.service

[Service]
Type=simple
User=spring-python
WorkingDirectory=/opt/spring-python
Environment="SPRING_PROFILES_ACTIVE=production"
Environment="STARTUP_FAIL_FAST=true"
ExecStart=/usr/bin/python -m spring.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl start spring-python
sudo systemctl enable spring-python
```

---

## 6. 验证部署

### 6.1 健康检查

```bash
curl http://localhost:8080/actuator/health
```

响应示例：

```json
{
    "status": "UP",
    "components": {
        "redis": "UP",
        "database": "UP",
        "nacos": "UP",
        "rabbitmq": "UP"
    }
}
```

> Sentinel、OpenTelemetry追踪、Seata HTTP-AT、API Gateway 已内嵌实现，不属于外部依赖组件，因此不显示在聚合健康检查中。可通过应用日志或 `@SentinelResource`、`@Trace`、`@GlobalTransactional` 注解的实际调用验证。

### 6.2 重试机制验证

```python
from spring.annotations import Retryable
from spring.retry import Backoff

@Retryable(max_retries=3, backoff=Backoff(delay=1000))
def test_retry():
    raise Exception("Test exception")

# 应看到重试日志
test_retry()
```

### 6.3 OpenTelemetry 追踪验证

查看应用日志中的traceId和spanId输出。使用`@Trace`注解的方法会自动创建span：

```python
from spring.annotations import Trace

@Trace("test-operation")
def test_traced():
    pass

test_traced()
# 日志中会输出: [Trace] span_id=xxx trace_id=xxx
```

### 6.4 Seata 分布式事务验证

```python
from spring.cloud.seata import seata_manager

tx_id = seata_manager.begin_transaction(name="test_tx")
try:
    # 执行业务操作
    seata_manager.commit_transaction(tx_id)
    print("Transaction committed")
except Exception as e:
    seata_manager.rollback_transaction(tx_id)
    print(f"Transaction rolled back: {e}")
```

---

## 7. 故障排查

### 7.1 Nacos Docker 启动失败

**问题：** 容器退出码为 255，日志提示 `NACOS_AUTH_TOKEN` 或 `NACOS_AUTH_IDENTITY_*` 缺失。

**解决方案：**

1. 使用 Nacos 2.2+ 时配置 `NACOS_AUTH_ENABLE=true`、Base64 token（解码后至少 32 字节）以及 identity key/value；部署指南中的 Docker Compose 示例提供了可运行的演示值。
2. Windows Docker Desktop 追加 `JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport`，并映射 Nacos 8848 和 9848 端口。
3. 使用外部 MySQL 时先导入 `/home/nacos/conf/mysql-schema.sql`，并确认 `MYSQL_SERVICE_*` 连接参数。
4. 用 liveness/readiness 端点验证服务，而不是只看容器进程状态：

   ```bash
   curl http://127.0.0.1:8848/nacos/v1/console/health/liveness
   curl http://127.0.0.1:8848/nacos/v1/console/health/readiness
   ```

应用客户端还需安装 `nacos-sdk-python`，并设置 `NACOS_SERVER`、`NACOS_USERNAME` 和 `NACOS_PASSWORD`。

### 7.2 MySQL 认证问题

**问题：** `Access denied for user 'root'@'localhost'`

**解决方案：**

1. 确认密码正确
2. MySQL 8+ 添加 `allowPublicKeyRetrieval=true` 到 JDBC URL
3. 检查用户权限：
   ```sql
   SHOW GRANTS FOR 'user'@'%';
   ```
4. Docker环境下如遇localhost认证问题，设置环境变量`SPRING_DISABLE_DOCKER_IP_DETECT=0`启用容器IP自动检测

### 7.3 Redis 连接问题

**问题：** `ConnectionError: Error 111 connecting to localhost:6379`

**解决方案：**

1. 检查 Redis 服务状态：
   ```bash
   redis-cli ping
   ```

2. 检查防火墙规则

3. 检查 Redis 绑定地址（`bind 0.0.0.0`）

### 7.4 DDL Auto 建表失败

**问题：** DDL自动建表提示权限不足或SQL语法错误

**解决方案：**

1. 确保数据库用户有DDL权限（CREATE/ALTER/DROP）
2. 生产环境建议使用`validate`模式而非`create`/`update`
3. 检查实体类字段类型是否在支持范围内（int/str/float/bool/bytes/datetime）

---

## 附录

### A. 完整环境变量清单

```bash
# Server
export SERVER_PORT=8080
export SERVER_HOST=0.0.0.0

# Redis
export REDIS_ENABLED=true
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=
export REDIS_DB=0
export REDIS_TIMEOUT=5000

# JWT
export JWT_SECRET_KEY=your-secret-key
export JWT_ALGORITHM=HS256
export JWT_EXPIRES_IN=3600

# Database
export DB_ENABLED=false
export DB_URL=sqlite:///./test.db
export DB_USERNAME=
export DB_PASSWORD=
export DB_DRIVER=sqlite
export DB_HOST=localhost
export DB_PORT=3306
export DB_DATABASE=./test.db

# ORM DDL Auto
export DB_DDL_AUTO=none  # none|validate|update|create|create-drop
export DB_ENTITY_PACKAGES=  # 实体类包路径，逗号分隔

# Nacos
export DISCOVERY_ENABLED=false
export NACOS_SERVER=localhost:8848
export NACOS_NAMESPACE=
export NACOS_GROUP=DEFAULT_GROUP
export NACOS_USERNAME=nacos
export NACOS_PASSWORD=nacos

# Nacos Docker server authentication (Nacos 2.2+)
export NACOS_AUTH_ENABLE=true
export NACOS_AUTH_TOKEN=<base64-token-with-at-least-32-decoded-bytes>
export NACOS_AUTH_IDENTITY_KEY=springpy
export NACOS_AUTH_IDENTITY_VALUE=springpy-local

# Docker 辅助
export SPRING_DISABLE_DOCKER_IP_DETECT=0  # 设为1禁用容器IP自动检测

# Retry
export RETRY_ENABLED=true
export RETRY_MAX_RETRIES=3
export RETRY_DELAY=1000
export RETRY_MAX_DELAY=10000
export RETRY_MULTIPLIER=2.0
export RETRY_RANDOM_FACTOR=0.1

# RabbitMQ
export RABBITMQ_ENABLED=false
export RABBITMQ_HOST=localhost
export RABBITMQ_PORT=5672
export RABBITMQ_USERNAME=guest
export RABBITMQ_PASSWORD=guest

# Prometheus
export PROMETHEUS_ENABLED=false
export PROMETHEUS_PORT=8000

# Logging
export LOG_LEVEL=INFO
export LOG_DIR=logs
```

> Sentinel限流熔断、OpenTelemetry分布式追踪、Seata HTTP-AT分布式事务、API Gateway 均为内嵌实现，无对应环境变量。

### B. Docker Compose 示例

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  mysql:
    image: mysql:8.0
    ports:
      - "3306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: example_db
    volumes:
      - mysql_data:/var/lib/mysql

  nacos:
    image: nacos/nacos-server:v2.3.0
    ports:
      - "8848:8848"
      - "9848:9848"
    environment:
      MODE: standalone
      # Nacos 2.2+ requires a Base64-encoded token (at least 32 decoded bytes)
      NACOS_AUTH_ENABLE: "true"
      NACOS_AUTH_TOKEN: "c3ByaW5ncHktbmFjb3MtaGFuZHNoYWtlLXNlY3JldC0yMDI2LTA4LTA0LTAx"
      NACOS_AUTH_IDENTITY_KEY: "springpy"
      NACOS_AUTH_IDENTITY_VALUE: "springpy-local"

  spring-python:
    build: .
    ports:
      - "8080:8080"
    environment:
      REDIS_HOST: redis
      DB_URL: mysql+pymysql://root:root@mysql/example_db
      DISCOVERY_ENABLED: "true"
      NACOS_SERVER: nacos:8848
      # Sentinel/OpenTelemetry/Seata/Gateway 内嵌实现，无需配置
    depends_on:
      - redis
      - mysql
      - nacos

volumes:
  redis_data:
  mysql_data:
```
