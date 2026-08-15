# SpringBootAI JPA 实体与仓库 —— 使用指南

> 框架版本：SpringBootAI 2.2.6 / 内嵌 PyMyBatis 2.2.6

---

## 目录

- [一、实体声明：@Entity + @Table](#一实体声明entity--table)
- [二、字段定义：显式 Column 与自动推断](#二字段定义显式-column-与自动推断)
- [三、自动时间戳：@CreateTime / @UpdateTime](#三自动时间戳createtime--updatetime)
- [相关模块](#相关模块)
- [注解参考](#注解参考)

---

## 一、实体声明：@Entity + @Table

> **v2.2.2+ 新增**：`@Entity` 和 `@Table` 分离写法，对齐 Java JPA。

### 为什么分离？

Java JPA 中，`@Entity` 标记"这是一个实体类"，`@Table` 指定"对应哪张表"。本框架同时支持分离写法（`@Entity` + `@Table`）和一体化写法（`@Entity("table_name")`），与 Java JPA 习惯一致。

### 三种声明写法（均向后兼容）

#### 写法一：@Entity + @Table 分离（推荐）

```python
from spring.orm import Entity, Table, Column, Id, Index, CreateTime

@Entity                                          # 标记为实体类
@Table(                                          # 指定表信息
    name="welding_admin_users",
    indexes=[Index("idx_admin_username", ["username"], unique=True)],
    comment="焊工智能系统管理员",
)
class AdminUser:
    id: int = Id()                          # 主键，显式 Id
    username: str = ""                      # 赋值 → Column(default="")
    display_name: str = "系统管理员"         # 赋值 → Column(default="系统管理员")
    enabled: bool = True                    # 赋值 → Column(default=True)
    last_login_at: str                      # 无赋值 → Column() 无默认值
    created_at: str = CreateTime()          # 显式 CreateTime，自动填充
    _cache: dict = {}                       # 私有字段，跳过不持久化
```

#### 写法二：仅 @Entity 无括号（表名自动推导）

```python
@Entity
class Product:
    id: int = Id()
    name: str = ""
    price: float = 0.0
    stock: int = 0
    description: str               # 无赋值 → Column() 无默认值
# 表名自动推导为 "product"（类名转 snake_case）
```

#### 写法三：一体化 @Entity("name", ...)（完全兼容）

```python
@Entity("sys_log", comment="系统日志")
class SysLog:
    id: int = Id()
    module: str = Column(nullable=False, length=50)
    message: str = Column(nullable=False, length=500)
```

#### 写法四：一体化 @Entity("name", ...)（全版本兼容）

```python
@Entity("sys_user", indexes=[Index("idx_username", ["username"], unique=True)], comment="用户表")
class User:
    id: int = None
    username: str = ""
    email: str = ""
    age: int = 0

@Table("sys_role")  # @Entity 别名（单独使用隐含 @Entity 语义）
class Role:
    id: int = None
    role_name: str = ""
```

> **小写别名**：框架还提供 `@entity` / `@table` 小写函数别名（向后兼容），与 `@Entity` / `@Table` 完全等价，推荐统一使用大写版本。

### @Table 单独使用

`@Table` 单独使用时隐含 `@Entity` 语义，与 `@Entity("name")` 等效：

```python
@Table(name="sys_config", comment="系统配置")
class SysConfig:
    id: int = Id()
    config_key: str = ""
    config_value: str = ""
```

### 装饰器执行顺序

Python 装饰器从下往上执行，`@Table` 先设置表元数据，`@Entity` 检测到已有 `@Table` 则不覆盖：

```
@Entity          ← 外层，后执行：标记 __entity__，不覆盖已有 __table__
@Table(...)      ← 内层，先执行：设置 __table__ 和 __entity__
class User: ...
```

### 声明写法对照表

| 写法 | 说明 | 对齐 Java | 版本 |
|------|------|-----------|------|
| `@Entity` + `@Table(...)` | 分离风格（推荐） | `@Entity` + `@Table` | v2.2.2+ |
| `@Entity` 无括号 | 表名自动推导为 snake_case | `@Entity`（无 `@Table`） | v2.2.2+ |
| `@Entity("name", ...)` | 一体化风格 | — | v2.2.2+ |
| `@Table("name", ...)` | `@Entity` 别名（单独使用隐含 `@Entity` 语义） | — | 全版本 |

### @Entity / @Table 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table_name` / `name` | str | "" | 表名，为空时自动用类名转下划线 |
| `indexes` | List[Index] | None | 索引列表 |
| `comment` | str | "" | 表注释 |

### Index 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | — | 索引名，DDL 生成 `CREATE INDEX name` |
| `columns` | List[str] | — | 索引列，可多列如 `["col1", "col2"]` |
| `unique` | bool | False | 唯一约束，DDL 生成 `UNIQUE INDEX` |

---

## 二、字段定义：显式 Column 与自动推断

> **v2.2.3+ 新增**：类型注解无需显式 `= Column(...)` 赋值，框架自动推断。

### 对齐 Java JPA

Java JPA 中，实体类的所有字段自动映射为数据库列，`@Column` 仅用于自定义属性。本框架 v2.2.3 起同样支持：**写了类型注解就是一列**，不需要每个字段都写 `= Column(...)`。

### 推断规则

| 写法 | 自动创建 | 说明 |
|------|----------|------|
| `name: str` | `Column()` | 无默认值，仅记录类型 |
| `name: str = ""` | `Column(default="")` | 赋值即为默认值 |
| `name: int = 0` | `Column(default=0)` | 同上 |
| `name: bool = True` | `Column(default=True)` | 同上 |
| `name: float = 0.0` | `Column(default=0.0)` | 同上 |
| `name: str = Column(...)` | 保留原 Column | 不覆盖 |
| `name: int = Id()` | 保留原 Id | 不覆盖 |
| `name: str = CreateTime()` | 保留原 CreateTime | 不覆盖 |
| `_xxx: dict = {}` | 跳过 | 以 `_` 开头的私有字段不持久化 |

### 完整示例

```python
from spring.orm import Entity, Table, Column, Id, Index, CreateTime

@Entity
@Table(
    name="welding_admin_users",
    indexes=[Index("idx_admin_username", ["username"], unique=True)],
    comment="焊工智能系统管理员",
)
class AdminUser:
    # ── 显式描述符（保留不覆盖）──
    id: int = Id()                              # 主键 + 自增
    created_at: str = CreateTime()              # 插入时自动填充时间

    # ── 有赋值 → 赋值作为 default ──
    username: str = ""                          # Column(default="")
    display_name: str = "系统管理员"             # Column(default="系统管理员")
    role: str = "ROLE_ADMIN"                    # Column(default="ROLE_ADMIN")
    enabled: bool = True                        # Column(default=True)

    # ── 无赋值 → Column() 无默认值 ──
    last_login_at: str                          # Column()

    # ── 私有字段 → 跳过 ──
    _cache: dict = {}                           # 不生成 DDL 列
```

### 自动生成的构造器

框架扫描所有 `Column` 描述符，自动生成 `__init__`（若类未显式声明）：

```python
# 自动生成等价于：
def __init__(self, **values):
    # 未知字段报错
    # 已知字段：传入值优先，否则用 Column.default
    self.id = values.get("id", None)            # Id.default = None
    self.username = values.get("username", "")  # Column.default = ""
    self.display_name = values.get("display_name", "系统管理员")
    self.role = values.get("role", "ROLE_ADMIN")
    self.enabled = values.get("enabled", True)
    self.last_login_at = values.get("last_login_at", None)
    self.created_at = values.get("created_at", None)
```

```python
# 使用：
admin = AdminUser(username="admin", password_hash="xxx")
print(admin.display_name)    # "系统管理员"（默认值）
print(admin.enabled)         # True（默认值）
print(admin.last_login_at)   # None（无默认值）
```

### 生成的 DDL（MySQL）

```sql
CREATE TABLE welding_admin_users (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(255) DEFAULT '',
    display_name  VARCHAR(255) DEFAULT '系统管理员',
    role          VARCHAR(255) DEFAULT 'ROLE_ADMIN',
    enabled       TINYINT(1) DEFAULT TRUE,
    last_login_at VARCHAR(255),              -- 无 DEFAULT
    created_at    DATETIME NOT NULL,
    UNIQUE INDEX idx_admin_username (username)
) COMMENT='焊工智能系统管理员';
```

> **注意**：`_cache` 不在 DDL 中——以 `_` 开头的私有字段自动跳过。

### 混合写法

自动推断与显式 `Column(...)` 可混用，显式描述符优先保留：

```python
@Entity("mixed_tab")
class MixedUser:
    id: int = Id()
    username: str = Column(nullable=False, unique=True, length=50)  # 显式
    nickname: str = ""                                                # 自动推断
    age: int                                                          # 自动推断
# username → VARCHAR(50) NOT NULL UNIQUE
# nickname → VARCHAR(255) DEFAULT ''
# age      → BIGINT
```

### 传统写法（显式 __init__）

v2.2.2 之前的写法仍然支持，适合不需要自动推断的场景：

```python
@Entity("sys_user")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = "", age: int = 0):
        self.id = id          # 自动主键+自增
        self.username = username
        self.email = email
        self.age = age        # 自动映射为 BIGINT
```

---

## 三、自动时间戳：@CreateTime / @UpdateTime

> 每张表几乎都有 `created_at`（创建时间）和 `updated_at`（更新时间）。
> 手动每次插入、更新都写 `datetime.now()` 很烦，用这两个注解可以**自动填充**。

### ① 是什么

- `@CreateTime`：标记**创建时间**字段，**插入时**自动写入当前时间。
- `@UpdateTime`：标记**更新时间**字段，**插入时**写入、**更新时**自动刷新为当前时间。

对齐 JPA/Hibernate 的 `@CreationTimestamp` / `@UpdateTimestamp`。

### ② 怎么用（两种写法任选一种）

```python
from spring.orm import Entity, Id, CreateTime, UpdateTime, AuditTimeExecutor

@Entity("sys_user")
class User:
    id = Id()

    # 写法一：类属性描述符（推荐）
    created_at = CreateTime()
    updated_at = UpdateTime()

    def __init__(self, id=None, name="", created_at=None, updated_at=None):
        self.id = id
        self.name = name
        self.created_at = created_at
        self.updated_at = updated_at
```

```python
# 写法二：描述符传参（可自定义列名）
from spring.orm import Entity, Id, CreateTime, UpdateTime

@Entity("sys_user")
class User:
    id = Id()
    created_at = CreateTime(name="create_time")   # 自定义列名
    updated_at = UpdateTime(name="update_time")
```

### ③ 自动建表也会适配

框架生成的 DDL 会自动给这些列加**数据库默认值**，即使代码漏填，数据库也会兜底写入当前时间：

| 方言 | 生成效果 |
|------|----------|
| MySQL | `created_at DATETIME DEFAULT CURRENT_TIMESTAMP` |
| PostgreSQL | `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` |
| SQLite | `created_at TEXT DEFAULT (datetime('now','localtime'))` |

### ④ 运行时自动填充（AuditTimeExecutor）

DDL 兜底只对"不填就插入"有效。若你的插入/更新 SQL 里**显式**写了这些列，可用执行器在调用前自动填好时间：

```python
executor = AuditTimeExecutor()

user = User(name="John")
executor.fill_on_insert(User, user)   # 写入 created_at 与 updated_at
user_mapper.insert(user)              # 执行 INSERT

executor.fill_on_update(User, user)   # 仅刷新 updated_at
user_mapper.update(user)              # 执行 UPDATE
```

要点：

- `fill_on_insert`：`created_at` 与 `updated_at` 都写入当前时间；若字段已有值则**保留**。
- `fill_on_update`：只刷新 `updated_at`，`created_at` 保持不变。
- 也可手动构造 `AuditTimeExecutor(now="2026-08-12 10:00:00")` 注入固定时间，用于测试。

---

## 相关模块

| 模块 | 文档 | 说明 |
|------|------|------|
| Spring Data Repository | [ORM_MODULE.md - Repository 章节](ORM_MODULE.md#repository-分页查询--不用手写sql的分页) | 分页、排序、条件查询（`PagingAndSortingRepository`） |
| 测试切片 | [TEST_SLICE_MODULE.md](TEST_SLICE_MODULE.md) | `DataJpaTest` 数据层测试 |
| ORM 完整指南 | [ORM_MODULE.md](ORM_MODULE.md) | Mapper 注解 / XML Mapper / DDL 配置 / 类型映射表 |

---

## 注解参考

### 实体声明注解

| 注解 | 一句话 | 放哪里 | 版本 |
|------|--------|--------|------|
| `@Entity` | "这是一个实体类"（可无括号 / 可传参一体化写法） | 实体类上 | v2.2.2+ |
| `@Table(name=..., indexes=[...], comment=...)` | "对应哪张表、索引、注释" | 实体类上 | v2.2.2+ |

> **小写别名**：`@entity` / `@table` 是 `@Entity` / `@Table` 的函数别名（全版本兼容），推荐统一使用大写版本。

### 实体字段注解

| 注解 | 一句话 | 放哪里 |
|------|--------|--------|
| `Column` | "这是一个数据库列" | 实体字段 |
| `Id` | "这是主键，默认自增" | 实体字段 |
| `Version` | "乐观锁版本号，更新时自动 +1 并作冲突检查" | 实体字段 |
| `CreateTime` | "创建时间，插入时自动填充" | 实体字段 |
| `UpdateTime` | "更新时间，插入/更新时自动填充" | 实体字段 |
| `Transient` | "这个字段不存数据库" | 实体字段 |

### 字段自动推断规则（v2.2.3+）

| 写法 | 自动创建 | 说明 |
|------|----------|------|
| `name: str` | `Column()` | 无默认值，仅记录类型 |
| `name: str = ""` | `Column(default="")` | 赋值即为默认值 |
| `name: int = 0` | `Column(default=0)` | 同上 |
| `name: str = Column(...)` | 保留原 Column | 不覆盖 |
| `name: int = Id()` | 保留原 Id | 不覆盖 |
| `_xxx: dict = {}` | 跳过 | 私有字段不持久化 |
