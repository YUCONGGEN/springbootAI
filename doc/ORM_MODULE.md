# SpringBootAI 数据库操作（ORM）—— 小白也能看懂的使用指南

> 框架版本：SpringBootAI 2.1.1 / 内嵌 PyMyBatis 2.1.1

---

## 用这个模块 vs 不用这个模块

| | 不用 ORM 模块（自己写） | 用 ORM 模块 |
|---|---|---|
| **代码量** | 连接、执行、解析、关闭，几十行代码才插一条数据 | 写一个方法 + 一行 SQL，框架帮你跑 |
| **SQL 注入防护** | 你自己拼字符串，万一写漏了就完了 | `#{name}` 自动安全处理，不用担心 |
| **结果转对象** | 手动把数据库返回的元组转成 Python 对象 | 返回的就是 Python 对象，自动转换 |
| **事务控制** | 手动 `BEGIN`/`COMMIT`/`ROLLBACK`，容易忘 | `@Transactional` 一行搞定，抛异常自动回滚 |
| **建表** | 手动写 `CREATE TABLE` 语句 | 定义好 Python 类，框架自动建表 |

**举个例子**——插入一条用户数据：

```python
# ❌ 不用 ORM，自己写（容易出错、容易忘关连接）
import sqlite3
conn = sqlite3.connect("app.db")
conn.execute("INSERT INTO users(name, email) VALUES (?, ?)", ["张三", "zs@mail.com"])
conn.commit()
conn.close()
```

```python
# ✅ 用 ORM（SQL 写在方法上，框架自动执行）
@Mapper
class UserMapper:
    @Insert("INSERT INTO users(name, email) VALUES (#{name}, #{email})")
    def insert(self, name: str, email: str):
        pass  # 保持 pass，框架会帮你执行
```

---

## 第零章：数据库到底是个啥

### 先搞懂三个基本概念

回想一下 Excel：你打开一个 `.xlsx` 文件，里面有多个 **Sheet（工作表）**，每个 Sheet 里有 **行** 和 **列**。

数据库也是一样的结构：

| 生活比喻 | 数据库术语 | 说明 |
|----------|-----------|------|
| 一个 Excel 文件 | **数据库（Database）** | 一个 `.db` 文件，或 MySQL 里的一个库 |
| 一个 Sheet 页 | **表（Table）** | 比如 `users` 表存所有用户，`orders` 表存所有订单 |
| 一行数据 | **记录 / 行（Row）** | 比如"张三、28岁、zhangsan@mail.com"这一条 |
| 一列 | **字段 / 列（Column）** | 比如 `name` 列、`age` 列、`email` 列 |

所谓"操作数据库"，就是你用 Python 代码告诉数据库：

> - "往 `users` 表里加一行（姓名=张三，年龄=28）"
> - "从 `users` 表里找出所有年龄大于 18 的人"
> - "把 `users` 表里 ID=5 那个人的邮箱改成 new@mail.com"
> - "把 `users` 表里 ID=3 那条记录删掉"

这四个操作就是程序员常说的 **CRUD**（增删改查：Create、Read、Update、Delete）。

---

### 什么是 ORM？——把数据库表变成 Python 类

**ORM（对象关系映射）的作用是：你不用写 SQL 也能操作数据库，就像你用微信发消息，不用关心背后的网络协议。**

具体来说，ORM 帮你做两件事：

1. **把 Python 变量安全地塞进 SQL**——你不用自己拼字符串，防止 SQL 注入（后面会讲这是什么和为什么重要）
2. **把数据库返回的行自动转成 Python 对象**——不用自己一行行解析

打一个比方：

- **不用 ORM**：你给数据库发消息，得用人家的语言（SQL），还得手动翻译回复
- **用 ORM**：你跟一个翻译官（ORM）说 Python，翻译官帮你转成 SQL 发给数据库，再把数据库的回复翻译回 Python 对象

**一句话总结：你写 Python 方法 + SQL 语句，ORM 帮你跑腿执行。它不替你设计表结构——你还是得会写 SQL。**

---

### 三种使用方式怎么选

| 方式 | 适合谁 | 特点 |
|------|--------|------|
| **Mapper 注解 SQL** | 👶 新手 ✅ 推荐从这里开始 | SQL 直接写在 Python 方法上，一眼能看懂 |
| **XML Mapper** | 🏗️ 从 Java MyBatis 迁移的开发者、SQL 很长很复杂 | SQL 和 Python 分开，支持动态拼 SQL |
| **SqlSession** | 🔧 需要完全掌控执行过程 | 最灵活，也得自己多写代码 |

> **建议**：如果你是新手，先用 Mapper 注解方式跑通 CRUD。等项目变大了、SQL 变复杂了，再学 XML 方式。

---

### 使用前准备

1. 在 `application.yml` 中开启 `database.enabled: true`
2. 安装数据库驱动：
   - SQLite 自带（Python 标准库，直接能用）
   - MySQL 用 `pip install springbootAI[mysql]`
3. 在启动类上配置 `@MapperScan`，确保 Mapper 所在目录里有 `__init__.py`
4. 数据库账号只给应用需要的权限，不要用 root

最小 SQLite 配置（适合学习）：

```yaml
# application.yml
database:
  enabled: true           # 开启数据库模块
  orm: mybatis
  driver: sqlite          # 用 SQLite，无需额外安装
  database: ./data/demo.db  # 数据库文件路径
  min_size: 1
  max_size: 5
  ddl-auto:
    mode: update          # 自动建表/加列，学习时推荐
    entity_packages: demo.entity  # 实体类所在的包
```

> SQLite 适合本地学习和测试。正式项目用 MySQL/PostgreSQL 时，记得改 `driver`、`host`、`port`、`username`、`password`。

---

### 一次数据库调用经过哪些层

```
HTTP 请求 → Controller → Service → Mapper → 连接池 → 数据库
                         ↳ @Transactional 控制提交或回滚
```

把这个流程想象成快递：

- **Controller** = 前台（收件、发件）
- **Service** = 调度中心（决定要不要打包、出了问题要不要退回）
- **Mapper** = 快递员（真正跑腿把 SQL 送到数据库）
- **连接池** = 一队待命的快递员（不用每次都招新人）

---

## 第一章：新手三步写一个 CRUD

> **这章带你从零写出能增删改查的完整代码。**

### 场景

做一个用户管理功能：能查所有用户、按 ID 查一个、新增一个、修改名字、删除。数据库用 SQLite。

### 第一步：定义数据实体

> **@entity 是什么？** 给一个 Python 类打上这个标签，框架启动时自动帮你建数据库表。好比：你画了张"表的草图"，`@entity` 就是工匠，照着草图把真的表造出来。

```python
# demo/entity/user.py
from dataclasses import dataclass
from spring.orm import entity, Index

@entity("users", indexes=[
    Index("idx_name", ["name"]),  # 给 name 列建索引，查名字时更快
], comment="用户表")
@dataclass
class User:
    id: int = None      # 字段名叫 id，自动变成主键、自动递增
    name: str = ""      # 对应数据库的 name 列（VARCHAR 类型）
    email: str = ""     # 对应数据库的 email 列
    age: int = 0        # 对应数据库的 age 列（INTEGER 类型）
```

① 这段代码做了什么：定义了一个 `User` 类，描述"用户表"长什么样。  
② 启动后，框架自动执行 `CREATE TABLE users (...)`，表就建好了。  
③ 运行结果：数据库里多了一张 `users` 表，有 `id`、`name`、`email`、`age` 四列。

### 第二步：写 Mapper（数据访问层）

> **@Mapper 是什么？** 告诉框架"这个类是数据库操作员，框架请帮我管理它"。  
> **@Select 是什么？** 标注在方法上，意思是"这个方法用来查数据"。  
> **@Insert 是什么？** 标注在方法上，意思是"这个方法用来插数据"。  
> **@Update 是什么？** 标注在方法上，意思是"这个方法用来改数据"。  
> **@Delete 是什么？** 标注在方法上，意思是"这个方法用来删数据"。

```python
# demo/mapper/user_mapper.py
from typing import Optional
from spring.orm import Delete, Insert, Mapper, Select, Update
from demo.entity.user import User


@Mapper  # 告诉框架：帮我管理这个类
class UserMapper:
    @Select("SELECT id, name, email, age FROM users")
    def find_all(self) -> list[User]:
        """查所有用户"""
        pass  # 保持 pass！运行时代理会替换整个方法

    @Select("SELECT id, name, email, age FROM users WHERE id = #{id}")
    def find_by_id(self, id: int) -> Optional[User]:
        """按ID查一个用户 —— #{id} 会被方法参数 id 的值安全替换"""
        pass

    @Insert("INSERT INTO users(name, email, age) VALUES (#{name}, #{email}, #{age})")
    def insert(self, name: str, email: str, age: int):
        """新增一个用户"""
        pass

    @Update("UPDATE users SET name = #{name} WHERE id = #{id}")
    def update_name(self, id: int, name: str):
        """修改用户名字 —— UPDATE 用户 SET 新名字 WHERE 条件是 id"""
        pass

    @Delete("DELETE FROM users WHERE id = #{id}")
    def delete(self, id: int):
        """删除一个用户"""
        pass
```

① `#{name}` 和 `#{email}` 与 Python 方法参数名一一对应，框架自动把参数值安全地填入 SQL。  
② 方法体保持 `pass`，运行时由框架自动执行 SQL。  
③ 不要把 `self` 算进 SQL 参数里。

### 第三步：写 Service 和 Controller

```python
# demo/service/user_service.py
from demo.mapper.user_mapper import UserMapper


class UserService:
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper  # 框架自动注入 Mapper

    def list_all(self):
        return self.user_mapper.find_all()

    def get_by_id(self, user_id: int):
        user = self.user_mapper.find_by_id(user_id)
        if user is None:
            raise ValueError(f"用户 {user_id} 不存在")
        return user

    def create(self, name: str, email: str, age: int):
        self.user_mapper.insert(name, email, age)

    def rename(self, user_id: int, new_name: str):
        self.user_mapper.update_name(user_id, new_name)

    def remove(self, user_id: int):
        self.user_mapper.delete(user_id)
```

```python
# demo/controller/user_controller.py
from spring.web import RestController, PostMapping, GetMapping
from demo.service.user_service import UserService


@RestController("/api/users")
class UserController:
    def __init__(self, user_service: UserService):
        self.user_service = user_service

    @GetMapping("/")
    def list_users(self):
        """GET /api/users/ → 返回所有用户列表"""
        users = self.user_service.list_all()
        return {"code": 0, "data": users}
        # 输出示例: {"code": 0, "data": [{"id": 1, "name": "张三", ...}, ...]}

    @GetMapping("/{user_id}")
    def get_user(self, user_id: int):
        """GET /api/users/1 → 返回单个用户"""
        user = self.user_service.get_by_id(user_id)
        return {"code": 0, "data": user}

    @PostMapping("/")
    def create_user(self, name: str, email: str, age: int):
        """POST /api/users/ → 新增用户"""
        self.user_service.create(name, email, age)
        return {"code": 0, "msg": "创建成功"}

    @PostMapping("/{user_id}/rename")
    def rename_user(self, user_id: int, new_name: str):
        """POST /api/users/1/rename → 改名"""
        self.user_service.rename(user_id, new_name)
        return {"code": 0, "msg": "改名成功"}

    @PostMapping("/{user_id}/delete")
    def delete_user(self, user_id: int):
        """POST /api/users/1/delete → 删除"""
        self.user_service.remove(user_id)
        return {"code": 0, "msg": "删除成功"}
```

### 第四步：配置启动类

```python
# app.py
from spring.annotations import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["demo"])
@MapperScan(base_packages=["demo.mapper"])  # 告诉框架去 demo.mapper 文件夹找 Mapper
class Application:
    pass
```

```yaml
# application.yml
database:
  enabled: true
  orm: mybatis
  driver: sqlite
  database: ./data/app.db
  min_size: 1
  max_size: 5
  ddl-auto:
    mode: update
    entity_packages: demo.entity
```

启动后，访问 `GET http://localhost:8080/api/users/` 即可看到返回数据。

> 如果没有 `@MapperScan`，框架默认扫描启动类顶级包下的 `mappers` 目录。显式配置更稳定，推荐明确指定。

---

## 第二章：事务——"要么都成功，要么都失败"

> **@Transactional 是什么？** 想象你要给朋友转账 100 元：你的账户减 100，朋友的账户加 100。如果减了你的钱之后系统突然崩溃，朋友没收到钱，你的钱就没了。事务就是保证"你的钱扣掉 **并且** 朋友的账加上"要么**两个操作都成功**，要么**两个操作都撤销**，绝不会出现扣了你的钱但朋友没收到的情况。

### ① 是什么

事务（Transaction）是一组数据库操作，它们绑定在一起，要么全部执行成功，要么全部撤销。**像银行转账——扣钱和加钱必须同时成功。**

### ② 怎么用

```python
# demo/service/transfer_service.py
from spring.annotations import Transactional
from demo.mapper.user_mapper import UserMapper


class TransferService:
    def __init__(self, user_mapper: UserMapper):
        self.user_mapper = user_mapper

    @Transactional  # 这个方法里的数据库操作绑定在一起
    def transfer(self, from_id: int, to_id: int, amount: int):
        """① A 减钱  ② B 加钱  —— 两步绑定在一起"""
        from_user = self.user_mapper.find_by_id(from_id)
        to_user = self.user_mapper.find_by_id(to_id)

        if from_user.age < amount:
            raise ValueError("余额不足，转账失败")

        self.user_mapper.update_age(from_id, from_user.age - amount)
        self.user_mapper.update_age(to_id, to_user.age + amount)
        # 如果这中间出任何异常，所有修改都会自动撤销
```

### ③ 运行结果

- 正常情况：两个账户都更新成功
- 如果 `update_age(to_id, ...)` 出错了：第一个 `update_age` 的修改自动撤销，`from_id` 的钱不会少
- 如果余额不足抛异常：什么都不会改

> **重点**：`@Transactional` 应该放在 **Service 层**，不要放在 Controller 上。因为一个业务操作可能涉及多个 Mapper 调用，它们应该在同一个事务里。

---

## 第三章：DDL 自动建表 —— "自动建表就像你买了家具，师傅上门帮你装好"

### ① 是什么

你定义了 Python 实体类，不想手动写 `CREATE TABLE` SQL 语句。框架启动时，自动根据你的类帮你建表。

**好比：你画了一张家具的设计图（Python 类），师傅（@entity）到了现场照着图帮你把家具组装好（建表）。**

### ② 怎么用

**配置：**

```yaml
# application.yml
database:
  ddl-auto:
    mode: update          # 选择建表模式
    entity_packages: app.entity  # 实体类所在的包
```

**模式说明：**

| 模式 | 大白话 | 做什么 |
|------|--------|--------|
| `none` | 什么都不做 | 不自动建表（默认） |
| `validate` | 只检查，不改表 | 启动时检查表结构是否匹配，不匹配就报错 |
| `update` | 自动补列 | 启动时创建不存在的表，给已有的表加新列。**推荐开发时用** |
| `create` | 每次重建 | 每次启动都删掉旧表、建新表。**数据会丢！** |
| `create-drop` | 用完就删 | 启动时建表，关闭时删表。测试用 |

**定义实体类：**

```python
# app/entity/user.py
from dataclasses import dataclass
from spring.orm import entity, Index, Column, Id


# 普通类风格
@entity("sys_user", indexes=[
    Index("idx_username", ["username"], unique=True),  # username 不能重复
    Index("idx_email", ["email"]),
], comment="用户表")
class User:
    def __init__(self, id: int = None, username: str = "", email: str = "", age: int = 0):
        self.id = id          # 字段名叫 id，自动变主键+自增
        self.username = username  # 自动映射为 VARCHAR(255)
        self.email = email
        self.age = age        # 自动映射为 BIGINT


# dataclass 风格
@dataclass
@entity("sys_role")
class Role:
    id: int = None         # 自动主键+自增
    role_name: str = ""    # 驼峰名自动转下划线：role_name
    role_code: str = ""
```

### ③ 运行结果

启动后，框架自动生成并执行类似这样的 SQL：

```sql
CREATE TABLE sys_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自动主键
    username VARCHAR(255),                  -- str → VARCHAR
    email VARCHAR(255),
    age BIGINT                              -- int → BIGINT
);
CREATE UNIQUE INDEX idx_username ON sys_user(username);
CREATE INDEX idx_email ON sys_user(email);
```

**约定大于配置：**

- 类中有 `id` 字段 → 自动设为主键 + 自增
- 字段名自动驼峰转下划线（`userName` → `user_name`）
- 类型自动映射到数据库类型

| Python 类型 | MySQL | PostgreSQL | SQLite |
|------------|-------|------------|--------|
| `int` | BIGINT AUTO_INCREMENT | BIGSERIAL | INTEGER PRIMARY KEY AUTOINCREMENT |
| `str` | VARCHAR(255) | VARCHAR(255) | TEXT |
| `float` | DOUBLE | DOUBLE PRECISION | REAL |
| `bool` | TINYINT(1) | BOOLEAN | INTEGER |
| `bytes` | BLOB | BYTEA | BLOB |
| `datetime` | DATETIME | TIMESTAMP | TEXT |

---

## 第四章：SQL 注入防护 —— 为什么 `#{}` 比 `${}` 安全

### ① 是什么

**SQL 注入**是黑客在输入框里写恶意 SQL，企图偷走或破坏你的数据。比如你在登录框输入 `' OR '1'='1`，如果代码直接拼字符串，SQL 就变成了：

```sql
SELECT * FROM users WHERE name = '' OR '1'='1' AND password = ''
-- 条件 '1'='1' 永远为真，绕过密码验证！
```

### ② 怎么防护

```python
# ✅ 正确：用 #{name} 参数化
@Select("SELECT * FROM users WHERE name = #{name}")
def find_by_name(self, name: str):
    pass
# 框架会把 #{name} 替换成 ? 占位符，再把参数值安全传进去
# 即使用户输入了 ' OR '1'='1，也只会被当成普通字符串，不是 SQL 代码

# ❌ 危险：用 ${table} 直接拼接（默认被拦截）
@Select("SELECT * FROM ${table} WHERE id = #{id}")
def find(self, table: str, id: int):
    pass
# ${...} 默认被拦截，只有配置 allow_raw_params: true 且通过白名单才能用
```

### ③ 一句话记住

> **永远用 `#{}`！** `${}` 是字符串直接拼接，非常危险。除非你完全明白自己在做什么，并且通过了框架的白名单检查。

---

## 第五章：分页 —— 数据太多不能一次全取

### ① 是什么

你有 10 万条用户数据，一次全取出来内存会爆。分页就是每次只取 20 条，像翻书一样一页一页看。

### ② 怎么用

```python
# 普通分页（页码 + 每页数量）
page = session.select_pagination(
    "SELECT id, name FROM users ORDER BY id",
    page_num=1,    # 第 1 页
    page_size=20,  # 每页 20 条
)
# page: {"total": 105, "page_num": 1, "page_size": 20, "data": [...]}

# 游标分页（大数据量推荐）
cursor_page = session.select_cursor(
    "SELECT id, name FROM users",
    cursor_key="id",
    cursor_value=None,  # 从头开始
    page_size=100,
)
# cursor_page: {"data": [...], "next_cursor": 101}
# 下次取下一页：cursor_value=101
```

### ③ 为什么大数据量用游标分页

普通分页翻到第 50 页（OFFSET 1000）时，数据库要扫描并丢弃前 1000 条，很慢。游标分页每次基于上页最后一条的 ID 往后取，不管翻到第几页都一样快。

---

## 第六章：XML Mapper —— SQL 从 Python 里独立出来

### ① 是什么

当 SQL 很长、包含很多动态条件时，把 SQL 从 Python 代码里抽出来放到 XML 文件里，代码更清爽。

### ② 怎么用

```yaml
# application.yml
database:
  mapper_locations:
    - ./myapp/mappers/UserMapper.xml
```

```xml
<!-- myapp/mappers/UserMapper.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<mapper namespace="myapp.mappers.UserMapper">
  <!-- 复用 SQL 片段 -->
  <sql id="columns">id, name, created_at</sql>

  <!-- 查询：支持动态条件 -->
  <select id="search" resultMap="userMap" fetchSize="100" useCache="true">
    SELECT <include refid="columns"/> FROM users
    <bind name="pattern" value="'%' + keyword + '%'" />
    <where>
      <if test="keyword != null and keyword != ''">
        AND name LIKE #{pattern}
      </if>
    </where>
  </select>

  <!-- 插入：支持主键回写 -->
  <insert id="insert" useGeneratedKeys="true" keyProperty="user.id">
    INSERT INTO users(name, created_at) VALUES (#{user.name}, #{user.created_at})
  </insert>
</mapper>
```

```python
# 调用
session.select_one("myapp.mappers.UserMapper.findById", {"id": 1})
```

### ③ 动态标签说明

| 标签 | 作用 |
|------|------|
| `<if test="...">` | 条件成立时才加上这段 SQL |
| `<where>` | 自动去掉开头的 `AND`/`OR` |
| `<foreach>` | 循环拼接（比如 `id IN (1,2,3)`） |
| `<choose>/<when>/<otherwise>` | 类似 if/elif/else |
| `<set>` | 自动拼 `SET` 子句 |
| `<bind>` | 派生新变量（比如拼 LIKE 模式） |

---

## 第七章：直接使用 Session —— 完全自己控制

### ① 是什么

不想用 Mapper 注解，想自己完全控制 SQL 执行过程。

### ② 怎么用

```python
from spring.orm.pymybatis import build_session_factory

# 创建连接工厂
factory = build_session_factory({
    "datasource": {"driver": "sqlite", "database": "./app.db"},
    "pool": {"min_size": 1, "max_size": 5},
    "security": {"block_ddl": True},
})

try:
    with factory.open_session() as session:
        # 查询
        rows = session.select(
            "SELECT id, name FROM users WHERE id > #{min_id}",
            {"min_id": 0},
        )
        # rows: [{"id": 1, "name": "Tom"}, {"id": 2, "name": "Jerry"}, ...]
        print(f"查到 {len(rows)} 条记录")
        for row in rows:
            print(f"  ID={row['id']}, 姓名={row['name']}")

        # 插入
        session.insert("INSERT INTO users(name) VALUES (#{name})", {"name": "新用户"})

        # 更新
        session.update("UPDATE users SET name = #{name} WHERE id = #{id}",
                       {"id": 1, "name": "新名字"})

        # 删除
        session.delete("DELETE FROM users WHERE id = #{id}", {"id": 3})
finally:
    factory.close()  # 记得关闭工厂，释放连接池
```

### ③ 运行结果

控制台输出查询结果，数据库中的记录被增删改。

---

## 第〇章：新手常见错误

> 刚学 ORM 最容易踩的坑都在这里了。

### 错误 1："ORM 就是不用写 SQL"

❌ **错误想法**：用了 ORM 就不用学 SQL 了。

✅ **实际情况**：PyMyBatis 的 Mapper 注解就是让你写 SQL 的！它只帮你做参数绑定和结果映射。SQL 写错了，谁也救不了。**你不会写 SQL 就用不了 MyBatis。**

---

### 错误 2："SQL 里写 `${}` 和 `#{}` 都一样"

❌ **错误想法**：反正都是替换参数。

✅ **实际情况**：`#{name}` 是安全参数化，框架用 `?` 占位符替换，防 SQL 注入。`${name}` 是直接把字符串拼到 SQL 里，黑客可以在输入框里写恶意 SQL 偷走整张表。**永远优先用 `#{}`。**

---

### 错误 3："Mapper 方法里可以写代码逻辑"

❌ **错误想法**：把 `pass` 删掉，写自己的业务代码。

✅ **实际情况**：Mapper 方法体必须保持 `pass`（或 `...`），运行时**框架会替换掉整个方法**。你在里面写的任何代码都不会被执行。业务逻辑写在 Service 层。

---

### 错误 4："连接池越大越快"

❌ **错误想法**：`max_size` 设大一点性能更好。

✅ **实际情况**：数据库能同时处理的连接是有限的，连接池太大反而浪费资源。一般 `max_size` 设 5~20 就够。多 worker 模式下，总连接数 = `workers × max_size`，比如 4 个 worker × `max_size: 5` = 20 个连接。

---

### 错误 5："`ddl-auto=update` 生产环境也能用"

❌ **错误想法**：开发时 `update` 自动加列很方便，生产也这样干。

✅ **实际情况**：生产环境应该用 `validate`（只检查不改）+ 手动迁移脚本，并且开启 `block_ddl: true`。自动改表结构在生产环境可能锁表、丢数据。

---

### 错误 6："分页就是用 LIMIT/OFFSET"

❌ **错误想法**：分页就是 SQL 里加 `LIMIT 20 OFFSET 1000`。

✅ **实际情况**：大偏移量时（翻到第 50 页），OFFSET 会让数据库扫描并丢弃前面所有行，非常慢。这时候用**游标分页**（`select_cursor`），每次基于上一页最后一条的 ID 往后取，不管多少页都一样快。

---

### 错误 7："`@Transactional` 放 Controller 上也能用"

❌ **错误想法**：事务注解放哪里都行。

✅ **实际情况**：`@Transactional` 应该放在 **Service 层**。Service 是事务边界的正确位置——一个业务操作可能涉及多个 Mapper 调用，它们应该在同一个事务里要么全成功、要么全失败。

---

### 错误 8："事务里捕获异常不抛出去"

❌ **错误想法**：

```python
@Transactional
def do_something(self):
    try:
        self.user_mapper.insert(...)    # 第一步
        self.order_mapper.insert(...)   # 第二步，可能出错
    except Exception:
        pass  # ❌ 把异常吃了！事务不会回滚
```

✅ **正确做法**：

```python
@Transactional
def do_something(self):
    self.user_mapper.insert(...)    # 第一步
    self.order_mapper.insert(...)   # 第二步
    # ✅ 如果出错，异常自然离开方法，事务自动回滚
```

事务只有在异常**离开事务方法**时才会回滚。如果你在方法内部 `try/except` 把异常"吃掉"了，框架不知道出错了，就不会回滚。

---

## 常见 SQL 错误排查

### 错误 1：Mapper 找不到

**现象**：启动时报 `Mapper xxx 未注册` 或调用 Mapper 方法时返回 `None`。

**排查步骤**：
1. 检查 `@MapperScan` 的 `base_packages` 路径是否正确
2. 检查 Mapper 所在的目录有没有 `__init__.py` 文件
3. 检查 Mapper 类上有没有 `@Mapper` 注解
4. 检查 `application.yml` 中 `database.enabled` 是不是 `true`

### 错误 2：SQL 参数未绑定

**现象**：执行时报 `找不到参数 xxx 的值`。

**排查步骤**：
1. SQL 中的 `#{name}` 和方法参数名是否完全一致（区分大小写）
2. 不要把 `self` 算成一个 SQL 参数
3. 如果参数名和 `#{...}` 里的名字不一样，用 `Param` 做别名

### 错误 3：SQLite 正常、MySQL 失败

**现象**：开发时用 SQLite 一切正常，部署到 MySQL 就报错。

**原因**：SQLite 和 MySQL 的 SQL 语法、主键策略、数据类型都有差异。

**解决**：在真实的 MySQL 上重新运行同一套测试。

### 错误 4：XML 动态 SQL 不生效

**现象**：`<if test="...">` 里的条件永远不成立。

**排查**：
1. 检查 `test` 表达式里的变量名和方法参数名是否一致
2. OGNL 里写 `null` 表示空，不是 Python 的 `None`
3. `<where>` 会自动去掉第一个多余的 `AND`/`OR`

### 错误 5：启动成功后访问接口报"数据库未连接"

**现象**：启动日志正常，但一调接口就报错。

**排查**：
1. 检查数据库文件路径（SQLite 相对路径以启动目录为准）
2. 检查 MySQL/PostgreSQL 服务是否在运行
3. 检查用户名密码和端口是否正确

---

## 错误速查表

| 错误 | 原因 | 处理 |
|------|------|------|
| Mapper 找不到 | 扫描包错误或缺少 `__init__.py` | 检查 `@MapperScan` 和目录 |
| SQL 参数未绑定 | SQL 中的 `#{name}` 与方法参数名不同 | 统一名称或使用 `Param` |
| 事务不回滚 | Service 不受容器管理，或异常被内部捕获 | 通过容器注入 Service，让异常离开方法 |
| 多 worker 后连接暴增 | 每个 worker 有独立连接池 | 按 `workers × max_size` 计算总连接数 |
| SQLite 正常 MySQL 失败 | 数据库方言差异 | 在目标数据库上重新跑测试 |
| DDL auto 不生效 | entity_packages 路径错误 | 确认包路径存在，包含 `__init__.py` |
| 大偏移量分页报错 | 超过 `max_pagination_offset` | 改用游标分页 |

---

## 注解参考

### MyBatis 集成注解

| 注解 | 一句话 | 放哪里 |
|------|--------|--------|
| `@MapperScan` | "去这个文件夹里找所有 Mapper" | 启动类上 |
| `@Mapper` | "这个类是数据库操作员" | Mapper 类上 |
| `@Select` | "这个方法用来查数据" | Mapper 方法上 |
| `@Insert` | "这个方法用来插数据" | Mapper 方法上 |
| `@Update` | "这个方法用来改数据" | Mapper 方法上 |
| `@Delete` | "这个方法用来删数据" | Mapper 方法上 |
| `@ResultMap` + `Result` | "数据库列名和 Python 属性名不一样，要对应一下" | Mapper 类上 |
| `@Options` | "调一下查询行为（一次取多少、超时多久）" | Mapper 方法上 |
| `Param` | "SQL 里的参数名和 Python 参数名不一样，对个账" | 方法参数类型标注里 |
| `@MapperTransactional` | "这个 Mapper 里的操作要么全成功要么全失败" | Mapper 类或方法 |

### @entity 注解参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | "" | 表名，为空时自动用类名转下划线 |
| indexes | List[Index] | None | 索引列表 |
| comment | str | "" | 表注释 |

---

## Java MyBatis 开发者看这里

如果你之前用的是 Java MyBatis，以下是核心差异：

| 独立 PyMyBatis | SpringBootAI 内嵌 |
|------|-------------|
| `pymybatis.Configuration` | `spring.orm.pymybatis.Configuration` |
| `pymybatis.SqlSessionFactory` | `spring.orm.pymybatis.SqlSessionFactory` |
| `pymybatis.SqlSession` | `spring.orm.pymybatis.SqlSession` |
| `pymybatis.annotations` | `spring.orm.pymybatis.annotations` |

XML 动态标签（`<if>`、`<where>`、`<foreach>`、`<choose>`、`<set>`、`<trim>`、`<bind>`）全部支持。`useGeneratedKeys`、`keyProperty`、`association`/`collection` 嵌套映射、`<selectKey>`、`SelectProvider` 也都支持。

---

## 多 worker 模式的连接池计算

加了 worker 进程后，数据库连接数 = **worker 数量 × max_size**。

例如：4 个 worker × `max_size: 5` = **20 个连接**。如果数据库只支持 20 个连接，其他服务就连不上了。调小 `max_size` 或减少 worker 数量来控制总量。

---

## FAQ

**Q: SQLite 和 MySQL 该选哪个？**

A: 学习和本地开发用 SQLite（Python 自带，零配置）。正式部署用 MySQL 或 PostgreSQL。

**Q: Mapper 方法为什么要写 `pass`？**

A: 框架运行时会用代理（Proxy）替换掉整个方法体，直接执行 SQL。你在里面写的任何代码都不会执行。

**Q: `@Transactional` 和 `@MapperTransactional` 有什么区别？**

A: `@Transactional` 是 Spring 服务层事务，用于 Service，可以跨多个 Mapper。`@MapperTransactional` 用于单个 Mapper 或 Session 调用。一般情况下用 Service 层的 `@Transactional` 就够了。

**Q: 内存数据库（`:memory:`）适合什么场景？**

A: 启动验证和自动化测试。进程退出后数据就没了，不适合存业务数据。

**Q: 如何确保 ORM 配置正确？**

A: ① 启动日志没有 Mapper 未注册或连接失败；② 调插入接口后能在数据库里查到记录；③ 在 `@Transactional` 方法里故意抛异常，确认数据回滚；④ 并发请求后连接池没有持续耗尽。
