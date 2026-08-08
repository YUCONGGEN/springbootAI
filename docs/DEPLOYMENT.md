# Spring Python 生产环境部署指南

## 目录

1. [环境要求](#1-环境要求)
2. [基础服务部署](#2-基础服务部署)
   - [Redis](#21-redis)
   - [MySQL](#22-mysql)
   - [Nacos（可选）](#23-nacos可选)
3. [SkyWalking 分布式追踪部署](#3-skywalking-分布式追踪部署)
4. [Seata 分布式事务部署](#4-seata-分布式事务部署)
5. [应用配置](#5-应用配置)
6. [启动应用](#6-启动应用)
7. [验证部署](#7-验证部署)
8. [故障排查](#8-故障排查)

---

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| Redis | 6.0+ | 用于分布式锁、限流、熔断 |
| MySQL | 5.7+ / 8.0+ | 用于业务数据存储 |
| Nacos | 2.0+ | 服务注册发现（可选） |
| SkyWalking | 9.0+ | 分布式追踪（可选） |
| Seata | 1.7+ | 分布式事务（可选） |

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

## 3. SkyWalking 分布式追踪部署

### 3.1 安装 SkyWalking OAP Server

```bash
# 下载 SkyWalking
wget https://archive.apache.org/dist/skywalking/9.7.0/apache-skywalking-apm-9.7.0.tar.gz
tar -zxvf apache-skywalking-apm-9.7.0.tar.gz
cd apache-skywalking-apm-bin

# 启动 OAP Server
./bin/oapService.sh

# 启动 UI
./bin/webappService.sh

# 访问 UI
# http://localhost:8080
```

### 3.2 安装 Python Agent

```bash
pip install skywalking>=0.12.0
```

### 3.3 配置 SkyWalking

在 `application.yml` 中启用：

```yaml
skywalking:
  enabled: true
  service_name: your-service-name
  collector_address: 127.0.0.1:11800
  protocol: grpc
```

或者通过环境变量：

```bash
export SKYWALKING_ENABLED=true
export SKYWALKING_SERVICE=your-service-name
export SKYWALKING_COLLECTOR=127.0.0.1:11800
```

---

## 4. Seata 分布式事务部署

### 4.1 安装 Seata Server

```bash
# 下载 Seata
wget https://github.com/seata/seata/releases/download/v1.8.0/seata-server-1.8.0.tar.gz
tar -zxvf seata-server-1.8.0.tar.gz
cd seata-server-1.8.0
```

### 4.2 配置 Seata

#### 4.2.1 修改 `conf/file.conf`

```properties
store.mode = db
store.db.datasource = druid
store.db.dbType = mysql
store.db.driverClassName = com.mysql.cj.jdbc.Driver
store.db.url = jdbc:mysql://localhost:3306/seata?useUnicode=true&rewriteBatchedStatements=true&serverTimezone=UTC&allowPublicKeyRetrieval=true&useSSL=false
store.db.user = root
store.db.password = your_password
store.db.minConn = 5
store.db.maxConn = 30
store.db.globalTable = global_table
store.db.branchTable = branch_table
store.db.lockTable = lock_table
```

#### 4.2.2 修改 `conf/registry.conf`

```properties
registry {
  type = "nacos"
  nacos {
    serverAddr = "localhost:8848"
    namespace = ""
    group = "SEATA_GROUP"
    application = "seata-server"
  }
}

config {
  type = "nacos"
  nacos {
    serverAddr = "localhost:8848"
    namespace = ""
    group = "SEATA_GROUP"
  }
}
```

### 4.3 初始化 Seata 数据库

创建 Seata 专用数据库并执行初始化脚本：

```sql
CREATE DATABASE IF NOT EXISTS seata;
USE seata;

-- 全局事务表
CREATE TABLE IF NOT EXISTS `global_table` (
    `xid` VARCHAR(128) NOT NULL,
    `transaction_id` BIGINT,
    `status` TINYINT NOT NULL,
    `application_id` VARCHAR(32),
    `transaction_service_group` VARCHAR(32),
    `transaction_name` VARCHAR(128),
    `timeout` INT,
    `begin_time` BIGINT,
    `application_data` VARCHAR(2000),
    `gmt_create` DATETIME,
    `gmt_modified` DATETIME,
    PRIMARY KEY (`xid`),
    KEY `idx_gmt_modified_status` (`gmt_modified`, `status`),
    KEY `idx_transaction_id` (`transaction_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分支事务表
CREATE TABLE IF NOT EXISTS `branch_table` (
    `branch_id` BIGINT NOT NULL,
    `xid` VARCHAR(128) NOT NULL,
    `transaction_id` BIGINT,
    `resource_group_id` VARCHAR(32),
    `resource_id` VARCHAR(256),
    `branch_type` VARCHAR(8),
    `status` TINYINT,
    `client_id` VARCHAR(64),
    `application_data` VARCHAR(2000),
    `gmt_create` DATETIME,
    `gmt_modified` DATETIME,
    PRIMARY KEY (`branch_id`),
    KEY `idx_xid` (`xid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 锁表
CREATE TABLE IF NOT EXISTS `lock_table` (
    `row_key` VARCHAR(128) NOT NULL,
    `xid` VARCHAR(128),
    `transaction_id` BIGINT,
    `branch_id` BIGINT NOT NULL,
    `resource_id` VARCHAR(256),
    `table_name` VARCHAR(32),
    `pk` VARCHAR(36),
    `gmt_create` DATETIME,
    `gmt_modified` DATETIME,
    PRIMARY KEY (`row_key`),
    KEY `idx_branch_id` (`branch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.4 在业务数据库中创建 undo_log 表

执行 `sql/seata_undo_log.sql` 脚本：

```bash
mysql -u username -p your_database < sql/seata_undo_log.sql
```

### 4.5 安装 Python Seata Client

```bash
pip install seata>=1.7.0
```

### 4.6 配置 Seata

在 `application.yml` 中启用：

```yaml
seata:
  enabled: true
  mode: distributed
  server_addr: localhost:8091
  application_id: your-service-name
  transaction_group: my_tx_group
```

或者通过环境变量：

```bash
export SEATA_ENABLED=true
export SEATA_MODE=distributed
export SEATA_SERVER=localhost:8091
export SEATA_APP_ID=your-service-name
export SEATA_TX_GROUP=my_tx_group
```

### 4.7 启动 Seata Server

```bash
cd seata-server-1.8.0/bin

# Linux/Unix
./seata-server.sh -p 8091 -h 0.0.0.0

# Windows
seata-server.bat -p 8091 -h 0.0.0.0
```

---

## 5. 应用配置

### 5.1 生产环境配置文件

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

discovery:
  enabled: true
  server_addr: nacos:8848
  username: ${NACOS_USERNAME}
  password: ${NACOS_PASSWORD}

seata:
  enabled: true
  mode: distributed
  server_addr: your-seata-server:8091
  application_id: spring-python-app
  transaction_group: my_tx_group

skywalking:
  enabled: true
  service_name: spring-python-app
  collector_address: your-skywalking-collector:11800

logging:
  level: INFO
  log_dir: /var/log/spring-python
```

### 5.2 环境变量配置

推荐使用环境变量覆盖默认配置：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 8080 |
| `REDIS_HOST` | Redis 地址 | localhost |
| `REDIS_PORT` | Redis 端口 | 6379 |
| `REDIS_PASSWORD` | Redis 密码 | null |
| `JWT_SECRET_KEY` | JWT 密钥 | spring-python-secret-key-change-in-production |
| `DB_URL` | 数据库连接 URL | sqlite:///./test.db |
| `DISCOVERY_ENABLED` | 是否启用 Nacos 服务发现 | false |
| `NACOS_SERVER` | Nacos 地址 | localhost:8848 |
| `NACOS_USERNAME` | Nacos 客户端账号 | 空 |
| `NACOS_PASSWORD` | Nacos 客户端密码 | 空 |
| `SEATA_ENABLED` | 是否启用 Seata | false |
| `SEATA_MODE` | Seata 模式 | local |
| `SEATA_SERVER` | Seata Server 地址 | localhost:8091 |
| `SKYWALKING_ENABLED` | 是否启用 SkyWalking | false |
| `SKYWALKING_COLLECTOR` | SkyWalking Collector 地址 | 127.0.0.1:11800 |

---

## 6. 启动应用

### 6.1 开发模式

```bash
cd your-project
python -m spring.main
```

### 6.2 生产模式

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

### 6.3 使用 Gunicorn（推荐）

```bash
# Linux环境安装进程管理器
pip install gunicorn uvicorn

# 使用Uvicorn Worker运行ASGI应用
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080 myapp.asgi:app
```

### 6.4 作为系统服务

创建 `/etc/systemd/system/spring-python.service`：

```ini
[Unit]
Description=Spring Python Application
After=network.target redis.service mysqld.service

[Service]
Type=simple
User=spring-python
WorkingDirectory=/opt/spring-python
Environment="SEATA_ENABLED=true"
Environment="SKYWALKING_ENABLED=true"
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

## 7. 验证部署

### 7.1 健康检查

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
        "seata": "UP",
        "skywalking": "UP"
    }
}
```

### 7.2 重试机制验证

```python
from spring.annotations import Retryable
from spring.retry import Backoff

@Retryable(max_retries=3, backoff=Backoff(delay=1000))
def test_retry():
    raise Exception("Test exception")

# 应看到重试日志
test_retry()
```

### 7.3 SkyWalking 验证

访问 SkyWalking UI（默认 http://localhost:8080），查看服务列表和追踪信息。

### 7.4 Seata 验证

执行分布式事务测试：

```python
from spring.cloud.seata import seata_manager

# 开启分布式事务
tx_id = seata_manager.begin_transaction(name="test_tx")

try:
    # 执行业务操作
    # ...
    
    # 提交事务
    seata_manager.commit_transaction(tx_id)
    print("Transaction committed")
except Exception as e:
    # 回滚事务
    seata_manager.rollback_transaction(tx_id)
    print(f"Transaction rolled back: {e}")
```

---

## 8. 故障排查

### 8.1 Seata 连接问题

**问题：** `Seata client failed to connect to server`

**解决方案：**

1. 检查 Seata Server 是否启动：
   ```bash
   telnet localhost 8091
   ```

2. 检查 `registry.conf` 配置是否正确

3. 检查 Nacos 服务注册是否正常

### 8.2 Nacos Docker 启动失败

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

### 8.3 SkyWalking 数据不显示

**问题：** SkyWalking UI 看不到追踪数据

**解决方案：**

1. 检查 Collector 地址是否正确
2. 检查防火墙是否开放 11800 端口
3. 检查 Agent 日志：
   ```bash
   grep -i skywalking logs/application*.log
   ```

### 8.4 MySQL 认证问题

**问题：** `Access denied for user 'root'@'localhost'`

**解决方案：**

1. 确认密码正确
2. MySQL 8+ 添加 `allowPublicKeyRetrieval=true` 到 JDBC URL
3. 检查用户权限：
   ```sql
   SHOW GRANTS FOR 'user'@'%';
   ```

### 8.5 Redis 连接问题

**问题：** `ConnectionError: Error 111 connecting to localhost:6379`

**解决方案：**

1. 检查 Redis 服务状态：
   ```bash
   redis-cli ping
   ```

2. 检查防火墙规则

3. 检查 Redis 绑定地址（`bind 0.0.0.0`）

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

# Seata
export SEATA_ENABLED=false
export SEATA_MODE=local
export SEATA_SERVER=localhost:8091
export SEATA_APP_ID=spring-python-app
export SEATA_TX_GROUP=my_tx_group

# SkyWalking
export SKYWALKING_ENABLED=false
export SKYWALKING_SERVICE=spring-python-app
export SKYWALKING_COLLECTOR=127.0.0.1:11800
export SKYWALKING_PROTOCOL=grpc

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
      - ./sql/seata_undo_log.sql:/docker-entrypoint-initdb.d/seata_undo_log.sql

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

  skywalking-oap:
    image: apache/skywalking-oap-server:9.7.0
    ports:
      - "11800:11800"
      - "12800:12800"

  skywalking-ui:
    image: apache/skywalking-ui:9.7.0
    ports:
      - "8080:8080"
    environment:
      SW_OAP_ADDRESS: http://skywalking-oap:12800

  spring-python:
    build: .
    ports:
      - "8081:8080"
    environment:
      REDIS_HOST: redis
      DB_URL: mysql+pymysql://root:root@mysql/example_db
      SEATA_ENABLED: true
      SKYWALKING_ENABLED: true
      SKYWALKING_COLLECTOR: skywalking-oap:11800
    depends_on:
      - redis
      - mysql
      - nacos

volumes:
  redis_data:
  mysql_data:
```
