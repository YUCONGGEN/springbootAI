# Spring Data Repository —— 不用手写SQL的分页查询

> 框架版本：SpringBootAI 2.2.5
> 返回 [八大模块总览](EIGHT_MODULES.md)

---

## 你遇到了什么问题？

前端请求"第 1 页，每页 20 条，按创建时间倒序"。你要手写 `SELECT COUNT(*)`、`LIMIT`、`OFFSET`、`ORDER BY`……每个列表接口都写一遍，烦得要死还容易出错。

## ① 是什么

**把数据库查询变成翻书操作。** 你只需要告诉框架：第几页、每页几条、按什么排序，框架自动生成 SQL 并把结果装进对象里。就像你去图书馆借书，跟管理员说"我要第 3 排第 5 本"，不用自己翻。

## ② 怎么用

```python
from spring.orm.ddl_auto import entity, Id, Column
from spring.data import PagingAndSortingRepository, Pageable, Sort, Specification

# 定义实体（数据库表对应的类）
@entity("users")
class User:
    id = Id()
    name = Column("user_name")
    age = Column()
    def __init__(self, id=None, name=None, age=None):
        self.id = id; self.name = name; self.age = age

# pool 是你的数据库连接池（和 ORM 共用）
repo = PagingAndSortingRepository(pool, User, dialect="mysql")

# --- 基础 CRUD ---
repo.save(User(name="小明", age=20))
repo.save_all([User(name="小红"), User(name="小刚")])

user = repo.find_by_id(1)
print(user)  # 输出: User(id=1, name="小明", age=20)

all_users = repo.find_all()          # 查全部
repo.exists_by_id(1)                 # 输出: True
repo.count()                         # 输出: 3
repo.delete_by_id(1)                 # 删一条
repo.delete_all()                    # 删全部

# --- 分页：第 0 页，每页 10 条 ---
page = repo.find_all(Pageable.of(page=0, size=10))
print(page.content)           # 当前页数据列表
print(page.total_elements)    # 总条数，如 30
print(page.total_pages)       # 总页数，如 3
print(page.has_next())        # 还有下一页吗？True

# --- 排序：按年龄降序 ---
sorted_users = repo.find_all(sort=Sort.by("user_name").descending())
# 结果：按 user_name 字段 Z→A 排列

# --- 条件筛选：只查成年人 ---
class AdultSpec(Specification):
    def to_predicate(self, root, col_resolver):
        return ("age >= ?", [18], "AND")  # 参数绑定防 SQL 注入

adults = repo.find_all(specification=AdultSpec())
# 结果：只返回 age >= 18 的用户

# --- 分页 + 排序 + 筛选 三合一 ---
page = repo.find_all(
    Pageable.of(0, 10, Sort.by("age")),
    specification=AdultSpec()
)
# 结果：第 0 页、每页 10 条、按年龄排序、而且只要成年人

# --- 复合条件：成年 AND 名字包含"明" ---
from spring.data import Specifications
spec = Specifications.where(AdultSpec()).and_(NameSpec())
```

## ③ 运行结果

你只需调用一个 `repo.find_all(Pageable.of(page=0, size=10))`，框架自动执行：
- 一条 `SELECT COUNT(*)` 查总条数
- 一条 `SELECT ... LIMIT 10 OFFSET 0` 查当前页数据
- 返回封装好的 `Page` 对象，包含数据、总页数、总条数、是否有下一页

## mini-FAQ

**Q：页码从 0 还是从 1 开始？**
从 0 开始。`Pageable.of(page=0, size=10)` 是第一页。`page=1` 是第二页。

**Q：大数据量分页慢怎么办？**
确保 `Sort.by()` 的字段在数据库中有索引。另外总条数查询（`SELECT COUNT(*)`）在大表上可能较慢。

**Q：能像 Java Spring 那样写 `findByNameAndAge` 吗？**
不支持方法名派生查询。需要用 `Specification` 手写条件。
