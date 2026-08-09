# SpringPy 内嵌 PyMyBatis ORM 与 DDL 使用指南

> 本文档从 README.md 第 5.11 / 5.12 节（注解）与第 8 节（功能说明）分离而来。
> 框架版本：SpringPy 1.6.1 / 内嵌 PyMyBatis 1.4.0

---

## 一、注解参考

### 5.11 MyBatis 集成注解

> 注意 `spring.orm.Mapper` 是 Spring 集成注解，而独立 PyMyBatis 的 `pymybatis.Mapper` 是标记基类，两者用法不同。`spring.annotations.Transactional` 是跨受管 Mapper 的服务层事务，`spring.orm.MapperTransactional` 是当前 Mapper/Session 的注解，两者也不要混用。

| 注解 | 放在哪里 | 作用 | 生效条件 |
|------|----------|------|----------|
| `@MapperScan` | SpringPy 启动类 | 指定 Mapper 包 | `database.enabled: true` 且 ORM 为 `mybatis`/`both` |
| `@Mapper` | Mapper 类 | 让扫描器把类注册成受管 Mapper 代理 | 类必须位于扫描包内 |
| `@Select` | Mapper 方法 | 执行查询 | 代理读取 SQL，并消费 `result_map`、`result_type`、`fetch_size`、`timeout`、`cache`；单条/列表仍受方法名规则影响 |
| `@Insert` | Mapper 方法 | 执行插入 | 支持 `use_generated_keys` 和 `key_property` 主键回写 |
| `@Update` | Mapper 方法 | 执行更新 | 参数按 Python 方法签名名称绑定，支持驱动级 `timeout` 提示 |
| `@Delete` | Mapper 方法 | 执行删除 | 参数使用 `#{name}`，不要拼接用户输入；支持驱动级 `timeout` 提示 |
| `@ResultMap` / `Result` | Mapper 类 | 把查询列改为 Python 属性名 | 可配合 `@Select(result_type=YourType)` 构造 dataclass/对象 |
| `@Options` | Mapper 方法 | 覆盖抓取、超时、缓存选项 | `flush_cache=True` 在执行前清当前 Session 查询缓存 |
| `Param` | `typing.Annotated` 参数元数据 | 让 Python 参数名映射到 SQL 名 | 使用 `identifier: Annotated[int, Param("id")]` |
| `@MapperTransactional` | Mapper 类或方法 | 给单个 Mapper 调用增加事务 | 支持七种传播模式；`REQUIRES_NEW`/`NOT_SUPPORTED` 需要连接池提供额外连接，业务层跨 Mapper 事务仍优先用 Spring `@Transactional` |

### 5.12 DDL 自动建表注解

#### @entity

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | "" | 表名，为空时自动用类名转下划线 |
| indexes | List[Index] | None | 索引列表 |
| comment | str | "" | 表注释（MySQL） |

```python
from spring.orm import entity, Index

@entity("sys_user", indexes=[
    Index("idx_username", ["username"], unique=True),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = ""):
        self.id = id
        self.username = username
        self.email = email
```

**注意事项**：`id` 字段自动成为主键自增；支持 `@dataclass` 风格实体类；驼峰命名自动转下划线；需在 `application.yml` 中配置 `database.ddl-auto.mode`。

---

## 二、功能说明

### 8.1 与独立包的一致性

| 独立 | Spring 内嵌 |
|------|-------------|
| `pymybatis.Configuration` | `spring.orm.pymybatis.Configuration` |
| `pymybatis.SqlSessionFactory` | `spring.orm.pymybatis.SqlSessionFactory` |
| `pymybatis.SqlSession` | `spring.orm.pymybatis.SqlSession` |
| `pymybatis.annotations` | `spring.orm.pymybatis.annotations` |

两份 ORM 源码由契约测试约束一致，只允许包内相对导入路径不同。核心 `Configuration`、`SqlSessionFactory`、`SqlSession`、连接池、事务、动态 SQL、安全和缓存行为一致。SpringPy 额外提供 Mapper 扫描、Bean 注册、按调用管理 Session 和事务上下文绑定。

| 场景 | 导入路径 |
|------|----------|
| 独立 ORM 项目 | `from pymybatis import ...` |
| SpringPy 内嵌 ORM | `from spring.orm.pymybatis import ...` |
| Spring 容器集成 | `from spring.orm import Mapper, MapperScan, ...` |

### 8.2 数据库配置

```yaml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./data/app.db
  min_size: 1
  max_size: 5
  max_idle: 60
  wait_timeout: 5
  validation_interval: 60
  leak_detection_enabled: true
  leak_timeout: 30
  transaction:
    isolation: READ_COMMITTED
  cache:
    enabled: true
    type: lru
    size: 1024
    ttl: 300
  security:
    sql_injection_detection: true
    ast_validation_enabled: false
    sensitive_data_masking: false
    block_ddl: true
    allow_raw_params: false
  batch:
    max_size: 1000
    split_size: 100
```

Spring 集成层将这些字段转换为与独立 PyMyBatis 相同的 `Configuration`。**注意连接池配置位于 `database` 直接子级，不是 `database.pool`。**

仓库示例默认使用单连接的内存 SQLite，因此只做示例启动和容器注入时不需要安装或启动 MySQL：

```yaml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ":memory:"
  min_size: 1
  max_size: 1
```

内存数据库在进程退出后消失，适合启动验证和测试，不适合保存业务数据。SQLite 使用 `:memory:` 时框架会强制单连接，因为多个内存连接是不同数据库。

MySQL 示例：

```yaml
database:
  enabled: true
  orm: mybatis
  driver: mysql
  host: db.internal
  port: 3306
  database: app
  username: ${DB_USERNAME}
  password: ${DB_PASSWORD}
```

### 8.3 Mapper 注解

```python
from spring.orm import Delete, Insert, Mapper, Select, Update


@Mapper
class UserMapper:
    @Select("SELECT id, name, email FROM users WHERE id = #{id}")
    def find_by_id(self, id: int):
        pass

    @Select("""
        SELECT id, name, email FROM users
        <where>
            <if test="name != null">AND name = #{name}</if>
        </where>
        ORDER BY id
    """)
    def find_all(self, name=None):
        pass

    @Insert("INSERT INTO users(name, email) VALUES (#{name}, #{email})")
    def insert(self, name: str, email: str):
        pass

    @Update("UPDATE users SET name = #{name} WHERE id = #{id}")
    def update(self, id: int, name: str):
        pass

    @Delete("DELETE FROM users WHERE id = #{id}")
    def delete(self, id: int):
        pass
```

Mapper 方法参数通过 Python 签名绑定到同名 `#{...}`。**不要把 `self` 计入 SQL 参数。** Mapper 方法主体保持 `pass`，运行时由代理执行 SQL。带类型标注的单条返回值会映射成对象；`list[User]` 返回值会映射成对象列表；未标注返回类型时默认返回 `dict` 或 `list[dict]`。

结果映射、参数别名和生成键示例：

```python
from dataclasses import dataclass
from typing import Annotated, Optional

from spring.orm import (
    Insert, Mapper, Options, Param, Result, ResultMap, Select,
)


@dataclass
class User:
    id: Optional[int] = None
    display_name: str = ""


@Mapper
@ResultMap(
    id="UserMap",
    type="User",
    results=[
        Result(column="id", property="id"),
        Result(column="user_name", property="display_name"),
    ],
)
class UserMapper:
    @Options(fetch_size=100, timeout=5, use_cache=True)
    @Select(
        "SELECT id, user_name FROM users WHERE id = #{user_id}",
        result_map="UserMap",
        result_type=User,
    )
    def find_by_id(self, identifier: Annotated[int, Param("user_id")]):
        pass

    @Insert(
        "INSERT INTO users(user_name) VALUES (#{display_name})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, user: User):
        pass
```

`result_map` 先把列名改为属性名，`result_type` 再构造对象。`fetch_size` 设置游标抓取提示；`timeout` 只在驱动支持时生效；缓存是当前 Session 的本地查询缓存。`parameter_type`、`key_column`、`Result.java_type/jdbc_type` 仍是兼容字段；`@DataSource` 和 `@CacheNamespace` 目前只保存元数据。

### 8.4 Mapper 扫描

```python
from spring.annotations import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["myapp"])
@MapperScan(base_packages=["myapp.mappers"])
class Application:
    pass
```

没有 `@MapperScan` 时，默认尝试扫描启动类顶级包下的 `mappers`。显式配置更稳定。Mapper Bean 名按类名转为下划线形式。每次普通 Mapper 调用会自动创建和关闭 Session。

### 8.5 直接使用 Session

```python
from spring.orm.pymybatis import build_session_factory

factory = build_session_factory({
    "datasource": {"driver": "sqlite", "database": "./app.db"},
    "pool": {"min_size": 1, "max_size": 5},
    "security": {"block_ddl": True},
})

try:
    with factory.open_session() as session:
        rows = session.select(
            "SELECT id, name FROM users WHERE id > #{min_id}",
            {"min_id": 0},
        )
finally:
    factory.close()
```

`SqlSessionFactory` 共享一个连接池；关闭工厂会停止连接池和泄漏检测资源。

### 8.6 XML Mapper

```yaml
database:
  mapper_locations:
    - ./myapp/mappers/UserMapper.xml
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<mapper namespace="myapp.mappers.UserMapper">
  <select id="findById">
    SELECT id, name FROM users WHERE id = #{id}
  </select>
</mapper>
```

调用：

```python
session.select_one("myapp.mappers.UserMapper.findById", {"id": 1})
```

动态标签支持 `if`、`where`、`foreach`、`choose/when/otherwise`、`set` 和 `trim`。

**XML Mapper 中的 SQL 可以直接写原始 `<=` 和 `>=`**；框架解析器会在解析前规范化比较运算符，并在输出 SQL 时还原，且保护 CDATA 和注释。标准 XML 工具链仍建议写成 `&lt;=` 和 `&gt;=`。

### 8.7 分页

```python
page = session.select_pagination(
    "SELECT id, name FROM users ORDER BY id",
    page_num=1,
    page_size=20,
)

cursor_page = session.select_cursor(
    "SELECT id, name FROM users",
    cursor_key="id",
    cursor_value=None,
    page_size=100,
)
```

大偏移量超过 `max_pagination_offset` 时会拒绝执行，建议改用游标分页。`cursor_key` 只接受安全标识符，不能传任意 SQL 片段。

### 8.8 SQL 安全

```sql
-- 正确：参数化
SELECT * FROM users WHERE id = #{id}

-- 默认拒绝：原始字符串替换
SELECT * FROM ${table} WHERE id = #{id}
```

`${...}` 只有在 `allow_raw_params: true` 且参数名/值通过白名单后才可使用。表名、列名、排序方向优先在应用代码中映射固定枚举，不要直接接受客户端字符串。ORM 还支持 SQL 注入检测、结果脱敏和日志脱敏，但只能作为附加防线，不能替代参数化 SQL、固定标识符白名单、最小数据库权限和审计。

### 8.9 DDL 自动建表（JPA ddl-auto 风格）

框架内置类似 Hibernate `hibernate.ddl-auto` 的自动建表功能，支持从 Python 实体类自动生成 DDL 语句。

**配置**：

```yaml
database:
  enabled: true
  driver: sqlite  # 或 mysql/postgresql
  database: ./app.db
  ddl-auto:
    mode: update  # none|validate|update|create|create-drop
    entity_packages: app.entity  # 实体类包路径，多个用逗号分隔
```

**模式说明**：

| ddl-auto 模式 | 说明 |
|--------------|------|
| `none` | 不做任何操作（默认） |
| `validate` | 启动时验证表结构与实体是否匹配，不匹配时报错 |
| `update` | 启动时创建不存在的表，为已存在的表添加新列和索引（推荐开发环境） |
| `create` | 每次启动都删除并重新创建表 |
| `create-drop` | 启动时创建，关闭时删除（测试用） |

也可以通过环境变量配置：

```bash
export DB_DDL_AUTO=update
export DB_ENTITY_PACKAGES=app.entity,app.model
```

**定义实体类**：

```python
from dataclasses import dataclass
from spring.orm import entity, Index, Column, Id

# 普通类风格
@entity("sys_user", indexes=[
    Index("idx_user_username", ["username"], unique=True),
    Index("idx_user_email", ["email"]),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = "", age: int = 0):
        self.id = id
        self.username = username
        self.email = email
        self.age = age

# dataclass 风格
@dataclass
@entity("sys_role")
class Role:
    id: int = None
    role_name: str = ""
    role_code: str = ""
```

**约定大于配置**：
- 如果类中有 `id` 字段，自动标记为主键并自增
- 字段名自动从驼峰转换为下划线命名（如 `userName` → `user_name`）
- 类型自动映射：`int→BIGINT/INTEGER`、`str→VARCHAR(255)/TEXT`、`float→DOUBLE`、`bool→TINYINT(1)/BOOLEAN`
- 支持 MySQL、PostgreSQL、SQLite 三种方言自动适配

**类型映射**：

| Python 类型 | MySQL | PostgreSQL | SQLite |
|------------|-------|------------|--------|
| `int` | BIGINT AUTO_INCREMENT | BIGSERIAL | INTEGER PRIMARY KEY AUTOINCREMENT |
| `str` | VARCHAR(255) | VARCHAR(255) | TEXT |
| `float` | DOUBLE | DOUBLE PRECISION | REAL |
| `bool` | TINYINT(1) | BOOLEAN | INTEGER |
| `bytes` | BLOB | BYTEA | BLOB |
| `datetime` | DATETIME | TIMESTAMP | TEXT |

> 生产环境建议 `block_ddl: true` 并使用 `validate` 模式或独立迁移脚本；应用迁移或初始化阶段需要建表时，应使用独立迁移脚本，运行期保持 `block_ddl: true`。开发环境使用 `update` 模式可自动同步表结构。

### 8.10 XML 功能矩阵

| Java MyBatis XML | SpringPy 状态 | 说明 |
|---|---|---|
| `<select>` / `<insert>` / `<update>` / `<delete>` | 支持 | `id` 必须在 namespace 中唯一 |
| `<resultMap>` 的 `<id>`、`<result>` | 支持 | 支持列到属性、继承 `extends` 和目标类型构造 |
| `<sql>` + `<include>` | 支持 | 支持 `<property name="..." value="..."/>` 替换片段变量 |
| `<if>`、`<where>`、`<set>`、`<trim>` | 支持 | OGNL 是受限安全子集 |
| `<choose>` / `<when>` / `<otherwise>` | 支持 | 只选择第一条成立分支 |
| `<foreach>` | 支持 | 支持 sequence、set、mapping 和对象/字典嵌套属性，最多 1000 项 |
| `<bind>` | 支持 | 支持受限表达式派生参数，例如 LIKE pattern |
| `resultType` | 支持 | 标量别名和全限定 Python 类型；未限定的自定义类型仍返回字典 |
| `fetchSize`、`timeout`、`useCache`、`flushCache` | 支持 | 语句级配置会进入执行链 |
| `useGeneratedKeys`、`keyProperty`、`keyColumn` | 支持 | 支持 DB-API `lastrowid` 的驱动；数据库仍需验证 |
| `<association>` / `<collection>` / discriminator | 支持 | 支持嵌套 `resultMap`、内联嵌套映射和 `select` 嵌套查询；集合结果按每个外层行映射 |
| `<selectKey>` | 支持 | 支持 `BEFORE/AFTER`、`keyProperty`、`keyColumn` 和 `resultType`，结果会回填参数对象/字典 |
| `databaseId` | 支持 | 按 `Configuration.dialect` 选择匹配数据库语句；匹配的数据库语句优先于通用语句 |
| `@SelectProvider` / `@InsertProvider` / `@UpdateProvider` / `@DeleteProvider` | 支持 | Provider 可为 Python 函数、类方法或全限定名称，必须返回非空 SQL 字符串 |
| Java MyBatis plugin / executor | 不兼容 | 使用 Python `Interceptor`，并为实际驱动写集成测试 |

**嵌套结果映射**：

```xml
<resultMap id="bookMap" type="acme.models.Book">
  <id column="book_id" property="id"/>
  <result column="title" property="title"/>
  <association property="author" resultMap="authorMap"/>
  <collection property="tags" select="findTags" column="book_id"/>
</resultMap>
```

`association` 可以使用 `resultMap`（同一行 JOIN 映射）或 `select`（以 `column` 值作为参数执行另一个 statement）。`collection` 的 `select` 返回列表；使用 JOIN 的集合需要在 Service 层按主键去重聚合。

**SelectProvider**：

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

**完整 XML 示例**：

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

---
