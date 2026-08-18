# SpringBootAI 数据库迁移（Migration）—— 使用指南

> SpringBootAI 2.3.2
> 源码位置：`springbootai/orm/migration.py`
> 对齐 Java：Flyway / Liquibase

---

## 目录

- [模块概述](#模块概述)
- [快速开始](#快速开始)
- [迁移文件命名规则](#迁移文件命名规则)
- [核心 API](#核心-api)
  - [MigrationManager 构造函数](#migrationmanager-构造函数)
  - [migrate() 执行迁移](#migrate-执行迁移)
  - [rollback() 回滚迁移](#rollback-回滚迁移)
  - [validate() 校验](#validate-校验)
  - [status() 查询状态](#status-查询状态)
  - [repair() 修复](#repair-修复)
- [高级功能](#高级功能)
  - [变量替换 ${var}](#变量替换-var)
  - [迁移锁](#迁移锁)
  - [SQL 分割](#sql-分割)
  - [baseline 基线](#baseline-基线)
- [配置方式](#配置方式)
- [完整使用示例](#完整使用示例)
- [与 Java Flyway 对照表](#与-java-flyway-对照表)
- [最佳实践](#最佳实践)
- [常见问题 FAQ](#常见问题-faq)

---

## 模块概述

### 什么是数据库迁移？

数据库迁移（Database Migration）是**用版本化 SQL 文件管理数据库表结构变更**的工程实践。

打个比方：你的应用代码用 Git 管理版本，每次改动都有 commit 记录；而数据库表结构（建表、加列、改字段）同样需要版本化追踪，这就是数据库迁移工具的作用。

| 场景 | 不用迁移工具 | 用迁移工具 |
|------|-------------|-----------|
| **新建表** | DBA 手动执行 `CREATE TABLE`，没人记得执行了没 | 把 SQL 写进 `V1__init.sql`，框架自动执行并记录 |
| **多人协作** | A 改了表结构，B 不知道，本地跑不起来 | B 拉代码后执行 `migrate()`，框架自动补齐差异 |
| **环境同步** | 开发/测试/生产环境结构不一致，靠人肉对账 | 同一套迁移文件，各环境执行到同一版本 |
| **回滚变更** | 加错了列，手动写 `DROP COLUMN` 还原 | 执行 `rollback()`，自动跑 Undo 脚本还原 |
| **审计追踪** | 谁在什么时候改了表结构？没人知道 | `schema_version` 表记录每条迁移的版本、时间、耗时 |

### SpringBootAI 迁移模块特性

SpringBootAI 内置了类 Flyway 风格的轻量数据库迁移工具，核心能力：

- ✅ 基于 SQL 文件版本号管理（`V1__init.sql`、`V2__add_users.sql`）
- ✅ 自动追踪已执行迁移（`schema_version` 表）
- ✅ SHA-256 checksum 校验，防止迁移文件被篡改
- ✅ 支持 MySQL / PostgreSQL / SQLite 三种方言
- ✅ Undo 回滚迁移（`U1__rollback_init.sql`）
- ✅ 迁移锁防止多实例并发执行
- ✅ 变量替换 `${var_name}`，支持环境差异化配置
- ✅ baseline 基线模式，在已有数据库上启用迁移

> **对齐 Java**：本模块对齐 Java 生态的 [Flyway](https://flywaydb.org/) 和 [Liquibase](https://www.liquibase.org/)。命名规则、checksum 校验、schema 历史表等概念与 Flyway 高度一致，方便 Java 开发者迁移。

---

## 快速开始

### 第一步：创建迁移文件

在项目下创建迁移文件目录，例如 `sql/migrations/`，并放入第一个迁移文件：

```sql
-- sql/migrations/V1__init.sql
-- 初始化数据库表结构

CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(200),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
```

### 第二步：执行迁移

```python
from springbootai.orm.migration import MigrationManager

# connection_pool 是你的数据库连接池
manager = MigrationManager(
    connection_pool=pool,
    migrations_dir="sql/migrations",
    dialect="mysql",
)

# 执行所有待执行迁移
applied = manager.migrate()
print(f"本次执行了 {len(applied)} 条迁移")
```

执行后，数据库中会：

1. 自动创建 `schema_version` 表（记录已执行的迁移）
2. 执行 `V1__init.sql` 中的 SQL
3. 在 `schema_version` 表中插入一条 V1 记录

### 第三步：查看迁移状态

```python
status = manager.status()
print(f"总迁移数: {status['total']}")
print(f"已执行: {status['applied']}")
print(f"待执行: {status['pending']}")

for m in status['migrations']:
    print(f"  V{m['version']} {m['description']} -> {m['state']}")
```

输出示例：

```
总迁移数: 1
已执行: 1
待执行: 0
  V1 init -> SUCCESS
```

---

## 迁移文件命名规则

迁移文件**必须**遵循以下命名规则，否则不会被识别：

### 正向迁移：`V{version}__{description}.sql`

```
V1__init.sql
V2__add_users_table.sql
V3__create_orders_index.sql
V1.1__add_email_column.sql      # 支持小版本号
V10__migrate_data.sql
```

### Undo 回滚迁移：`U{version}__{description}.sql`

```
U1__rollback_init.sql
U2__drop_users_table.sql
U3__drop_orders_index.sql
```

### 命名规则详解

| 组成 | 说明 | 示例 |
|------|------|------|
| `V` / `U` | 前缀，`V` = 正向迁移，`U` = Undo 回滚 | `V`、`U` |
| `{version}` | 版本号，支持整数或小数（用 `.` 分隔） | `1`、`2`、`1.1`、`10` |
| `__` | **两个下划线**分隔版本号和描述 | `__` |
| `{description}` | 描述文字，下划线会自动转为空格 | `add_users_table` → `add users table` |
| `.sql` | 文件扩展名 | `.sql` |

> **重要**：版本号和描述之间必须是**两个下划线** `__`，单个下划线不会被识别。这是 Flyway 的约定，SpringBootAI 完全对齐。

### 版本号排序规则

版本号按数值大小排序，支持小数版本：

```
V1__init.sql            # 版本 1
V1.1__patch.sql         # 版本 1.1（在 V1 之后、V2 之前）
V2__add_feature.sql     # 版本 2
V10__big_change.sql     # 版本 10（在 V2 之后）
```

执行顺序：`V1` → `V1.1` → `V2` → `V10`

### Undo 文件对应关系

Undo 文件 `U{version}__*.sql` 与正向迁移 `V{version}__*.sql` 一一对应。回滚 V3 时会执行 `U3__*.sql`：

```
sql/migrations/
├── V1__init.sql
├── U1__rollback_init.sql       # 回滚 V1
├── V2__add_users_table.sql
├── U2__drop_users_table.sql    # 回滚 V2
└── V3__add_index.sql
    # 缺少 U3，则 V3 无法回滚
```

> **注意**：如果某个版本缺少对应的 Undo 脚本，调用 `rollback()` 回滚该版本时会抛出 `MigrationError`。

---

## 核心 API

### MigrationManager 构造函数

```python
MigrationManager(
    connection_pool,
    migrations_dir: str,
    dialect: str = "mysql",
    table_name: str = "schema_version",
    variables: Optional[Dict[str, str]] = None,
)
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `connection_pool` | 连接池对象 | 必填 | 数据库连接池，需提供 `get_connection()` / `return_connection()` 方法，返回的对象需有 `.connection` 属性 |
| `migrations_dir` | `str` | 必填 | 迁移文件所在目录路径 |
| `dialect` | `str` | `"mysql"` | 数据库方言，支持 `mysql` / `postgresql` / `sqlite` |
| `table_name` | `str` | `"schema_version"` | 迁移记录表名，必须是合法 SQL 标识符（字母/下划线开头，仅含字母数字下划线，最长 128 字符） |
| `variables` | `Dict[str, str]` | `None` | 变量替换字典，用于 SQL 中 `${var}` 替换 |

**构造时行为：**

- 校验 `table_name` 是否为合法 SQL 标识符（防注入）
- 自动创建 `schema_version` 表（如果不存在）
- 初始化进程级迁移锁（`threading.Lock`）

**示例：**

```python
from springbootai.orm.migration import MigrationManager

# MySQL
manager = MigrationManager(
    connection_pool=mysql_pool,
    migrations_dir="sql/migrations",
    dialect="mysql",
    table_name="schema_version",
    variables={"table_prefix": "app_"},
)

# SQLite
manager = MigrationManager(
    connection_pool=sqlite_pool,
    migrations_dir="db/migrations",
    dialect="sqlite",
)
```

> **安全提示**：`table_name` 经过正则校验 `^[A-Za-z_][A-Za-z0-9_]{0,127}$`，非法字符会被拒绝，防止通过表名注入 SQL。

---

### migrate() 执行迁移

```python
manager.migrate(baseline: bool = False) -> List[MigrationRecord]
```

执行所有待执行的迁移。

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `baseline` | `bool` | `False` | 是否启用 baseline 模式（在已有数据库上首次启用迁移时使用） |

**返回值：** 本次执行的 `MigrationRecord` 列表

**执行流程：**

1. 读取 `schema_version` 表，获取已执行版本
2. 扫描迁移目录，发现所有 `V*.sql` 文件
3. 校验已执行迁移的 checksum（防止文件被篡改）
4. 按版本号顺序执行未应用的迁移
5. 每条迁移成功后，在 `schema_version` 表插入记录

**示例：**

```python
# 普通执行
applied = manager.migrate()

# baseline 模式（已有数据库首次接入迁移）
manager.migrate(baseline=True)
```

> **checksum 校验**：如果已执行的迁移文件被修改，checksum 不匹配会抛出 `MigrationError`。这是为了防止有人偷偷改了已上线的迁移脚本导致环境不一致。修改已执行迁移的正确做法是新增一个 `V{next}__*.sql`。

---

### rollback() 回滚迁移

```python
manager.rollback(target_version: str = None) -> List[MigrationRecord]
```

回滚迁移（执行对应的 Undo 脚本）。

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target_version` | `str` | `None` | 回滚到指定版本（**不包含**该版本）。`None` 表示只回滚最后一个版本 |

**返回值：** 本次回滚的 `MigrationRecord` 列表

**回滚规则：**

- `rollback()` 或 `rollback(None)`：只回滚最后已应用的一个版本
- `rollback("2")`：回滚到 V2 之前（执行 U3、U2，保留 V1）
- `rollback("0")`：回滚所有已应用版本

**示例：**

```python
# 只回滚最后一个版本
rolled_back = manager.rollback()

# 回滚到 V1（执行 U3、U2，保留 V1）
manager.rollback(target_version="1")

# 回滚所有
manager.rollback(target_version="0")
```

**执行流程：**

1. 获取已应用版本列表，按版本号降序排列
2. 根据 `target_version` 确定回滚范围
3. 获取数据库级迁移锁（防止并发）
4. 依次执行每个版本的 `U{version}__*.sql`
5. 每条 Undo 执行成功后，从 `schema_version` 表删除对应记录
6. 释放迁移锁

> **重要**：回滚必须存在对应的 `U{version}__*.sql` 文件，否则抛出 `MigrationError: Undo script U{version}__*.sql not found`。Undo 脚本需要开发者自行编写，框架不会自动生成反向 SQL。

---

### validate() 校验

```python
manager.validate() -> bool
```

校验已执行迁移的 checksum 是否一致，**不执行任何 SQL**（只读操作）。

**返回值：** `True` 校验通过，`False` 存在 checksum 不匹配或迁移文件缺失

**用途：**

- CI/CD 流水线中部署前校验
- 怀疑迁移文件被篡改时排查
- 启动时健康检查

**示例：**

```python
if not manager.validate():
    print("⚠️ 迁移文件校验失败！可能有人修改了已执行的迁移")
    # 处理校验失败...
else:
    print("✅ 所有迁移校验通过")
```

**校验失败的场景：**

1. **checksum 不匹配**：已执行的迁移文件被修改
2. **迁移文件缺失**：`schema_version` 表里记录了某个版本，但迁移目录里找不到对应文件

---

### status() 查询状态

```python
manager.status() -> Dict
```

获取当前迁移状态。

**返回值结构：**

```python
{
    "total": int,          # 发现的迁移文件总数
    "applied": int,        # 已成功执行的迁移数
    "pending": int,        # 待执行的迁移数
    "migrations": [        # 每条迁移的详细信息
        {
            "version": str,        # 版本号
            "description": str,    # 描述
            "script": str,         # 文件名
            "state": str,          # 状态：SUCCESS / PENDING / CHECKSUM_MISMATCH
        },
        ...
    ]
}
```

**状态值说明：**

| 状态 | 含义 |
|------|------|
| `SUCCESS` | 已成功执行，且 checksum 匹配 |
| `PENDING` | 待执行 |
| `CHECKSUM_MISMATCH` | 已执行但文件被修改，checksum 不匹配 |
| `FAILED` | 执行失败（记录在 `schema_version` 表中 `success=0`） |

**示例：**

```python
status = manager.status()

print(f"迁移进度: {status['applied']}/{status['total']}")
print(f"待执行: {status['pending']}")

for m in status['migrations']:
    icon = "✅" if m['state'] == 'SUCCESS' else "⏳" if m['state'] == 'PENDING' else "⚠️"
    print(f"  {icon} V{m['version']} {m['description']} [{m['state']}]")
```

---

### repair() 修复

```python
manager.repair() -> int
```

修复失败的迁移记录（删除 `schema_version` 表中 `success=0` 的记录）。

**返回值：** 删除的失败记录数

**用途：**

当某条迁移执行失败后，`schema_version` 表会留下一条 `success=0` 的记录，导致后续迁移被阻塞。修复后可以重新执行该迁移。

**示例：**

```python
# 假设 V3 执行失败
try:
    manager.migrate()
except MigrationError as e:
    print(f"迁移失败: {e}")

# 修复失败记录
deleted = manager.repair()
print(f"清理了 {deleted} 条失败记录")

# 修复 V3 文件后重新执行
manager.migrate()
```

> **注意**：`repair()` 只删除失败记录，不会回滚已执行的部分 SQL。如果迁移失败时已经执行了一半的 SQL（比如建了一半的表），需要手动清理残留对象后再 `repair()` + 重新 `migrate()`。

---

## 高级功能

### 变量替换 ${var}

迁移文件中可以使用 `${var_name}` 占位符，由 `MigrationManager` 在执行时替换为实际值。

**用途：**

- 不同环境使用不同的表名前缀（如 `app_users` / `test_users`）
- 数据库名称、字符集等环境相关配置
- 避免在 SQL 中硬编码敏感信息

**示例：**

```python
manager = MigrationManager(
    connection_pool=pool,
    migrations_dir="sql/migrations",
    dialect="mysql",
    variables={
        "table_prefix": "app_",
        "charset": "utf8mb4",
    },
)
```

```sql
-- sql/migrations/V1__init.sql
CREATE TABLE ${table_prefix}users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=${charset};
```

执行时会被替换为：

```sql
CREATE TABLE app_users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**安全说明：**

- 变量值**仅做字符串替换**，不执行 SQL 解析
- 变量值**不能包含分号 `;`**，防止 SQL 注入（包含分号会抛出 `MigrationError`）
- 引用未定义的变量会抛出 `MigrationError: Undefined migration variable`
- 变量名必须符合 `[A-Za-z_][A-Za-z0-9_]*` 格式

```python
# ❌ 危险：变量值含分号会被拒绝
manager = MigrationManager(
    pool, "sql/migrations",
    variables={"evil": "users; DROP TABLE orders; --"},
)
manager.migrate()  # 抛出 MigrationError
```

> **与 ORM 的区别**：ORM 中的 `#{name}` 是参数化绑定（防注入），`${var}` 是字符串替换。迁移场景下 `${var}` 用于结构化配置（表名、字符集），不用于用户输入，因此安全性可控。

---

### 迁移锁

为防止多实例并发执行迁移导致冲突，`MigrationManager` 提供两层锁：

| 锁类型 | 作用范围 | 实现方式 |
|--------|----------|----------|
| **进程级锁** | 单进程内多线程 | `threading.Lock`（构造时初始化） |
| **数据库级锁** | 多实例跨进程 | 数据库原生锁机制 |

**数据库级锁实现：**

| 方言 | 加锁 | 解锁 |
|------|------|------|
| MySQL | `SELECT GET_LOCK('springbootai_migration', 10)` | `SELECT RELEASE_LOCK('springbootai_migration')` |
| PostgreSQL | `SELECT pg_advisory_lock(123456789)` | `SELECT pg_advisory_unlock(123456789)` |
| SQLite | 进程级 `threading.Lock`（SQLite 单写入者） | 释放进程锁 |

**锁的触发时机：**

- `rollback()` 执行 Undo 时会获取数据库级锁
- `migrate()` 当前实现依赖 `schema_version` 表的隐式并发控制

**示例：多实例部署**

```
实例 A: manager.migrate()  → 获取锁 → 执行 V1 → 释放锁
实例 B: manager.migrate()  → 等待锁 → 获取锁 → 发现 V1 已执行 → 跳过 → 释放锁
```

> **MySQL GET_LOCK 说明**：第二个参数 `10` 表示等待 10 秒，超时返回 0（加锁失败）。如果加锁失败，`rollback()` 会抛出 `MigrationError: Failed to acquire migration lock`。

---

### SQL 分割

迁移文件中可以包含多条 SQL 语句，框架按分号 `;` 分割后逐条执行。

**分割规则：**

1. 按行读取，以 `;` 结尾的行视为一条语句的结束
2. **跳过注释行**：以 `--` 或 `#` 开头的行被忽略
3. 末尾未以 `;` 结尾的剩余内容也会作为最后一条语句

**示例：**

```sql
-- V1__init.sql
-- 创建用户表（注释行会被跳过）
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    name VARCHAR(100)
);

# 这也是注释（# 开头）
CREATE INDEX idx_name ON users(name);

INSERT INTO users (id, name) VALUES (1, 'admin')
```

会被分割为 3 条语句：

1. `CREATE TABLE users (...)`
2. `CREATE INDEX idx_name ON users(name)`
3. `INSERT INTO users (id, name) VALUES (1, 'admin')`

> **限制**：当前分割器是简单的行级分割，**不支持** 存储过程/函数体中的分号（如 `BEGIN ... END;`）。如需执行存储过程，建议拆分到多个迁移文件或使用 DELIMITER 写法时单独处理。

---

### baseline 基线

**baseline 模式用于在已有数据库上首次启用迁移。**

场景：你的数据库已经运行了一段时间，表结构是手动建的，现在想接入迁移管理。如果直接 `migrate()`，框架会尝试执行 `V1__init.sql`，但表已经存在了，会报错。

**baseline 解决方案：**

```python
# 第一次启用迁移时，用 baseline 模式
manager.migrate(baseline=True)
```

**baseline 行为：**

- 将第一条迁移（V1）标记为已应用（插入 `schema_version` 表），**但不实际执行 SQL**
- 从第二条迁移（V2）开始正常执行

**适用场景：**

```
已有数据库（手动建了 users、orders 表）
    ↓
接入迁移，创建 V1__init.sql（内容是当前表结构的 CREATE TABLE）
    ↓
manager.migrate(baseline=True)
    ↓
V1 被标记为已执行（但不真的跑 SQL，避免 "table already exists" 报错）
    ↓
后续新增 V2__add_xxx.sql 正常执行
```

> **注意**：baseline 只标记第一条迁移。如果你的数据库结构和 V1 文件不一致，baseline 后 validate 会通过（因为只比对 checksum），但实际结构可能有差异。建议 baseline 后仔细核对。

---

## 配置方式

### 在 application.yml 中配置

```yaml
# application.yml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/mydb
    driver: mysql
    username: root
    password: secret

  migration:
    enabled: true                          # 开启迁移模块
    migrations-dir: sql/migrations         # 迁移文件目录
    dialect: mysql                         # 数据库方言
    table-name: schema_version             # 迁移记录表名
    baseline-on-migrate: false             # 是否启用 baseline 模式
    variables:                             # 变量替换
      table_prefix: app_
      charset: utf8mb4
```

### 在代码中配置

```python
from springbootai.orm.migration import MigrationManager

# 直接构造
manager = MigrationManager(
    connection_pool=pool,
    migrations_dir="sql/migrations",
    dialect="mysql",
    table_name="schema_version",
    variables={"table_prefix": "app_"},
)

# 启动时自动执行
manager.migrate()
```

### 在启动类中集成

```python
from springbootai.annotations import SpringBootApplication, PostConstruct
from springbootai.orm.migration import MigrationManager


@SpringBootApplication
class Application:

    @PostConstruct
    def run_migrations(self):
        """启动时自动执行迁移"""
        manager = MigrationManager(
            connection_pool=self.datasource.pool,
            migrations_dir="sql/migrations",
            dialect="mysql",
        )
        applied = manager.migrate()
        if applied:
            print(f"✅ 执行了 {len(applied)} 条数据库迁移")
```

---

## 完整使用示例

下面演示一个完整的迁移流程：V1 正向建表 + U1 回滚还原。

### 1. 准备迁移文件

```
sql/migrations/
├── V1__create_users_table.sql
└── U1__drop_users_table.sql
```

**V1__create_users_table.sql（正向迁移）：**

```sql
-- 创建用户表
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(200) NOT NULL,
    age INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);

-- 插入初始数据
INSERT INTO users (username, email, age) VALUES
    ('admin', 'admin@example.com', 30),
    ('guest', 'guest@example.com', 20);
```

**U1__drop_users_table.sql（Undo 回滚）：**

```sql
-- 回滚 V1：删除用户表
DROP TABLE IF EXISTS users;
```

### 2. 执行正向迁移

```python
from springbootai.orm.migration import MigrationManager

# 假设 pool 是已配置好的 MySQL 连接池
manager = MigrationManager(
    connection_pool=pool,
    migrations_dir="sql/migrations",
    dialect="mysql",
)

# 查看初始状态
status = manager.status()
print(f"待执行: {status['pending']}")  # 输出: 待执行: 1

# 执行迁移
applied = manager.migrate()
print(f"✅ 执行了 {len(applied)} 条迁移")
for rec in applied:
    print(f"   V{rec.version} {rec.description} (耗时 {rec.execution_time:.2f}s)")

# 查看执行后状态
status = manager.status()
print(f"已执行: {status['applied']}, 待执行: {status['pending']}")
```

输出：

```
待执行: 1
✅ 执行了 1 条迁移
   V1 create users table (耗时 0.15s)
已执行: 1, 待执行: 0
```

### 3. 校验迁移

```python
# 校验 checksum
if manager.validate():
    print("✅ 所有迁移校验通过")
else:
    print("⚠️ 校验失败，迁移文件可能被篡改")
```

### 4. 回滚迁移

```python
# 回滚 V1（执行 U1）
rolled_back = manager.rollback(target_version="0")
print(f"↩️ 回滚了 {len(rolled_back)} 条迁移")
for rec in rolled_back:
    print(f"   U{rec.version} {rec.description}")

# 查看回滚后状态
status = manager.status()
print(f"已执行: {status['applied']}, 待执行: {status['pending']}")
```

输出：

```
↩️ 回滚了 1 条迁移
   U1 UNDO: drop users table
已执行: 0, 待执行: 1
```

### 5. 重新执行

```python
# 回滚后可以重新执行
applied = manager.migrate()
print(f"✅ 重新执行了 {len(applied)} 条迁移")
```

---

## 与 Java Flyway 对照表

| 特性 | Java Flyway | SpringBootAI Migration |
|------|-------------|----------------------|
| **正向迁移文件名** | `V1__init.sql` | `V1__init.sql` ✅ 一致 |
| **Undo 迁移文件名** | `U1__rollback.sql`（仅付费版） | `U1__rollback.sql` ✅ 免费支持 |
| **版本号格式** | `1`、`1.1`、`20210101.1200` | `1`、`1.1`（不支持时间戳格式） |
| **历史表名** | `flyway_schema_history` | `schema_version` |
| **checksum 算法** | CRC32 | SHA-256（取前 63 位） |
| **数据库方言** | MySQL / PostgreSQL / SQLite / Oracle / SQL Server 等 | MySQL / PostgreSQL / SQLite |
| **变量替换** | `${var}` | `${var}` ✅ 一致 |
| **baseline** | `baselineOnMigrate` 配置 | `migrate(baseline=True)` 参数 |
| **迁移锁** | 表锁 / `GET_LOCK` | `GET_LOCK` / `pg_advisory_lock` / 进程锁 |
| **repair 命令** | `flyway repair` | `manager.repair()` |
| **validate 命令** | `flyway validate` | `manager.validate()` |
| **info 命令** | `flyway info` | `manager.status()` |
| **调用方式** | 命令行 / Maven 插件 / Java API | Python API |
| **配置方式** | `flyway.properties` / YAML | `application.yml` / 构造函数参数 |

**Java Flyway 调用示例：**

```java
// Java Flyway
Flyway flyway = Flyway.configure()
    .dataSource(url, user, password)
    .locations("classpath:db/migration")
    .load();
flyway.migrate();
flyway.validate();
flyway.repair();
```

**SpringBootAI 等价写法：**

```python
# SpringBootAI
manager = MigrationManager(
    connection_pool=pool,
    migrations_dir="db/migration",
    dialect="mysql",
)
manager.migrate()
manager.validate()
manager.repair()
```

---

## 最佳实践

### 1. 迁移文件要"原子且单一职责"

✅ **推荐**：一个迁移文件只做一件事

```
V1__create_users_table.sql        # 只建 users 表
V2__create_orders_table.sql       # 只建 orders 表
V3__add_email_index_to_users.sql  # 只加一个索引
```

❌ **不推荐**：一个文件塞太多变更

```
V1__init_everything.sql  # 建了 10 张表、5 个索引、3 条初始数据
```

### 2. 已执行的迁移文件**绝不修改**

迁移文件一旦执行，其 checksum 就被记录在 `schema_version` 表中。修改后会导致 `validate()` 失败，`migrate()` 拒绝执行。

✅ **正确做法**：新增一个迁移文件来修正

```
V1__create_users_table.sql        # 已执行，不要改
V2__add_phone_column.sql          # 新增：给 users 加 phone 列
```

### 3. 每个正向迁移都写对应的 Undo

```
V1__create_users_table.sql
U1__drop_users_table.sql          # 配对
V2__add_phone_column.sql
U2__drop_phone_column.sql         # 配对
```

> Undo 是可选的，但生产环境强烈建议写。出问题时能快速回滚是救命的。

### 4. 生产环境用 `validate` 而非 `update`

```python
# ❌ 危险：生产环境直接 migrate 可能锁表
manager.migrate()

# ✅ 安全：先校验，确认无误后再人工触发迁移
if manager.validate():
    print("校验通过，可以执行迁移")
    # 经审批后执行
    manager.migrate()
```

### 5. 迁移文件纳入版本控制

迁移文件和代码一起提交到 Git，这样：

- 团队成员拉代码后执行 `migrate()` 即可同步表结构
- 历史变更有据可查
- code review 时能审查 SQL 变更

### 6. 数据迁移和结构迁移分开

```sql
-- V1__create_users_table.sql  （结构迁移）
CREATE TABLE users (...);

-- V2__migrate_user_data.sql   （数据迁移）
UPDATE users SET status = 'active' WHERE status IS NULL;
```

### 7. 大表变更要谨慎

```sql
-- ❌ 危险：大表加列可能锁表很久
ALTER TABLE big_table ADD COLUMN new_col VARCHAR(100);

-- ✅ 分步操作（写入迁移文件）
-- 第一步：加列（允许 NULL，不锁表太久）
ALTER TABLE big_table ADD COLUMN new_col VARCHAR(100) NULL;
-- 第二步：分批回填数据（单独迁移文件）
-- 第三步：加 NOT NULL 约束（单独迁移文件）
```

### 8. 在 CI 中加入校验

```python
# CI 流水线中执行
manager = MigrationManager(pool, "sql/migrations", "mysql")
if not manager.validate():
    print("❌ 迁移文件校验失败，请检查是否修改了已执行的迁移")
    exit(1)
```

---

## 常见问题 FAQ

**Q1: 迁移文件命名为什么必须是 `V{version}__{description}.sql`？**

A: 这是 Flyway 的约定，SpringBootAI 完全对齐。两个下划线 `__` 是版本号和描述的分隔符，框架用正则 `^V(\d+(?:\.\d+)?)__(.+)\.sql$` 匹配。单个下划线或没有下划线都不会被识别为迁移文件。

**Q2: checksum 校验失败怎么办？**

A: 出现 `Checksum mismatch` 说明已执行的迁移文件被修改了。处理方式：
1. 如果是误改：用 Git 恢复文件到原版本
2. 如果确实需要变更：新增一个迁移文件 `V{next}__*.sql` 来做变更，**不要修改已执行的文件**
3. 如果要强制覆盖（不推荐）：删除 `schema_version` 表中对应记录后重新执行

**Q3: rollback 报 "Undo script not found" 怎么办？**

A: 回滚版本 V{n} 时必须有对应的 `U{n}__*.sql` 文件。如果你没写 Undo 脚本，就无法回滚。解决：
1. 补写 `U{n}__*.sql` 文件
2. 或者手动在数据库中撤销 V{n} 的变更，然后删除 `schema_version` 表中 V{n} 的记录

**Q4: 多个实例同时启动会冲突吗？**

A: 不会。`rollback()` 使用数据库级锁（MySQL `GET_LOCK` / PostgreSQL `pg_advisory_lock`）防止并发。但 `migrate()` 当前主要依赖 `schema_version` 表的隐式控制，建议多实例部署时只让一个实例执行迁移，其他实例通过健康检查等待。

**Q5: 迁移执行到一半失败了怎么办？**

A: 迁移失败时：
1. 框架会自动 `ROLLBACK` 当前事务（已执行的语句回滚）
2. `schema_version` 表中可能留下 `success=0` 的记录
3. 调用 `manager.repair()` 清理失败记录
4. 修复迁移文件中的错误 SQL
5. 重新 `manager.migrate()`

**Q6: 能在迁移文件里写存储过程吗？**

A: 当前 SQL 分割器是简单的分号分割，**不支持** 存储过程体中的分号。如果必须执行存储过程，建议：
1. 把存储过程单独放一个迁移文件
2. 用 DELIMITER 语法（部分驱动支持）
3. 或者通过代码直接执行，不放入迁移文件

**Q7: schema_version 表可以自定义名字吗？**

A: 可以，通过构造函数 `table_name` 参数：

```python
manager = MigrationManager(
    pool, "sql/migrations", "mysql",
    table_name="my_migration_history",  # 自定义表名
)
```

表名必须是合法 SQL 标识符（字母/下划线开头，仅含字母数字下划线，最长 128 字符），否则会抛出 `ValueError`。

**Q8: baseline 模式和普通模式有什么区别？**

A: `migrate(baseline=True)` 会把**第一条迁移**标记为已执行但不真的跑 SQL，适用于已有数据库首次接入迁移。`migrate(baseline=False)`（默认）会正常执行所有待执行迁移的 SQL。

**Q9: 变量替换 `${var}` 和 ORM 的 `#{param}` 有什么区别？**

A:
- `${var}` 是**字符串替换**，用于迁移文件中的结构性配置（表名、字符集），值在执行前替换进 SQL 文本
- `#{param}` 是**参数化绑定**，用于 ORM 查询中的用户数据，值通过 `?` 占位符安全传入

`${var}` 不能含分号（防注入），`#{param}` 可以是任意值（自动转义）。

**Q10: SQLite 怎么用迁移？**

A: SQLite 完全支持，dialect 设为 `sqlite`：

```python
manager = MigrationManager(
    connection_pool=sqlite_pool,
    migrations_dir="db/migrations",
    dialect="sqlite",
)
manager.migrate()
```

SQLite 使用进程级锁（`threading.Lock`），不支持跨进程锁，因此多进程场景下需要自行协调。

---

## 改进记录

### Undo 回滚迁移支持 — v2.3.0

新增 `rollback()` 方法和 `U{version}__*.sql` 文件命名支持，对齐 Flyway Teams 付费版的 Undo 功能，免费提供。

### 变量替换安全加固 — v2.3.0

`${var}` 变量值禁止包含分号 `;`，防止通过变量值注入多语句 SQL。
