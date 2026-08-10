"""SpringBootAI Spring Data 仓库抽象测试 —— 覆盖 Pageable/Page/Sort、Specification、
PagingAndSortingRepository 的 CRUD/分页/排序/动态查询。

对齐 tests/test_jpa_version_transient.py 的 pytest + 内存 sqlite 风格。复用
``spring.orm.ddl_auto`` 的实体注解（@entity/Id/Column），用 ``DdlAutoManager``
建表，验证 Repository 的真实 SQL 行为。
"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.orm.ddl_auto import DdlAutoManager, entity, Id, Column
from spring.data import (
    Direction, Order, Sort, Pageable, Page,
    Specification, Specifications,
    PagingAndSortingRepository, DataRepository, get_data_repository_entity,
)


# ==================== 测试夹具 ====================

@entity("user")
class User:
    id = Id()
    name = Column("user_name")
    age = Column()
    email = Column()

    def __init__(self, id: int = None, name: str = None, age: int = None, email: str = None):
        self.id = id
        self.name = name
        self.age = age
        self.email = email


class _PooledConn:
    """连接池包装器：close() 为 no-op（模拟池化语义，复用 test_jpa 模式）。"""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **k):
        return self._conn.cursor(*a, **k)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return None

    def __getattr__(self, item):
        return getattr(self._conn, item)


class _DbutilsPooled:
    """DBUtils 风格池化连接：``.connection`` 暴露底层连接（DdlAutoManager._execute_sql 期望）。"""

    def __init__(self, conn):
        self.connection = conn


class _Pool:
    """三接口连接池：
    - ``get_connection``/``return_connection`` + ``.connection``：DdlAutoManager（DBUtils 风格）
    - ``connection()``：Repository / OptimisticLockExecutor
    """

    def __init__(self, conn):
        self._conn = conn

    # DdlAutoManager（DBUtils 风格）接口
    def get_connection(self):
        return _DbutilsPooled(self._conn)

    def return_connection(self, pooled):
        return None

    # Repository / OptimisticLockExecutor 接口
    def connection(self):
        return _PooledConn(self._conn)


@pytest.fixture
def repo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = None
    mgr = DdlAutoManager(_Pool(conn), dialect="sqlite", mode="create")
    mgr.register_entity(User)
    mgr.execute()
    return PagingAndSortingRepository(_Pool(conn), User, dialect="sqlite")


# ==================== Pageable / Page / Sort ====================

class TestPageable:
    def test_offset_and_limit(self):
        p = Pageable.of(2, 10)
        assert p.offset == 20
        assert p.limit == 10

    def test_negative_page_raises(self):
        with pytest.raises(ValueError):
            Pageable(-1, 10)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError):
            Pageable(0, 0)

    def test_next_previous_first(self):
        p = Pageable.of(2, 5)
        assert p.next().page_number == 3
        assert p.previous_or_first().page_number == 1
        assert p.first().page_number == 0

    def test_default_sort_unsorted(self):
        assert Pageable.of(0, 10).sort.is_sorted is False


class TestSort:
    def test_by_creates_asc_orders(self):
        s = Sort.by("name", "age")
        assert len(s.orders) == 2
        assert all(o.direction == Direction.ASC for o in s.orders)

    def test_desc_order(self):
        s = Sort(Order.desc("age"))
        assert s.orders[0].direction == Direction.DESC

    def test_to_sql(self):
        s = Sort(Order("name", Direction.ASC), Order.desc("age"))
        assert s.to_sql() == "name ASC, age DESC"

    def test_to_sql_with_resolver(self):
        s = Sort(Order.asc("name"))
        assert s.to_sql(lambda p: '"user_name"') == '"user_name" ASC'

    def test_unsorted_to_sql_empty(self):
        assert Sort.unsorted().to_sql() == ""
        assert Sort.unsorted().is_sorted is False


class TestPage:
    def test_total_pages(self):
        p = Page([1, 2, 3], Pageable.of(0, 3), 10)
        assert p.total_pages == 4  # ceil(10/3)
        assert p.has_next is True
        assert p.is_first is True
        assert p.is_last is False

    def test_last_page(self):
        p = Page([10], Pageable.of(3, 3), 10)
        assert p.total_pages == 4
        assert p.has_next is False
        assert p.is_last is True

    def test_empty(self):
        p = Page.empty(Pageable.of(0, 10))
        assert p.is_empty and not p.has_content
        assert p.total_pages == 0

    def test_next_pageable(self):
        p = Page([1], Pageable.of(0, 10), 15)
        assert p.next_pageable().page_number == 1
        assert p.previous_pageable() is None


# ==================== Specification ====================

class TestSpecification:
    def test_equal(self):
        sql, params = Specifications.equal("name", "Tom").to_predicate()
        assert sql == "name = ?" and params == ["Tom"]

    def test_comparison_ops(self):
        assert Specifications.greater_than("age", 18).to_predicate()[0] == "age > ?"
        assert Specifications.less_equal("age", 60).to_predicate()[0] == "age <= ?"
        assert Specifications.not_equal("name", "x").to_predicate()[0] == "name <> ?"

    def test_like_case_insensitive(self):
        sql, params = Specifications.like("name", "%tom%", case_insensitive=True).to_predicate()
        assert sql == "LOWER(name) LIKE LOWER(?)" and params == ["%tom%"]

    def test_in_empty_is_false(self):
        sql, params = Specifications.in_("id", []).to_predicate()
        assert sql == "1=0" and params == []

    def test_in_nonempty(self):
        sql, params = Specifications.in_("id", [1, 2, 3]).to_predicate()
        assert sql == "id IN (?, ?, ?)" and params == [1, 2, 3]

    def test_is_null_and_not_null(self):
        assert Specifications.is_null("email").to_predicate()[0] == "email IS NULL"
        assert Specifications.is_not_null("email").to_predicate()[0] == "email IS NOT NULL"

    def test_between(self):
        sql, params = Specifications.between("age", 18, 30).to_predicate()
        assert sql == "age BETWEEN ? AND ?" and params == [18, 30]

    def test_and_compose(self):
        spec = Specifications.and_(
            Specifications.equal("name", "Tom"),
            Specifications.greater_than("age", 18),
        )
        sql, params = spec.to_predicate()
        assert sql == "(name = ?) AND (age > ?)" and params == ["Tom", 18]

    def test_or_compose(self):
        spec = Specifications.equal("name", "Tom").or_(Specifications.equal("name", "Jerry"))
        sql, params = spec.to_predicate()
        assert sql == "(name = ?) OR (name = ?)" and params == ["Tom", "Jerry"]

    def test_not_compose(self):
        spec = Specifications.not_(Specifications.equal("name", "Tom"))
        sql, params = spec.to_predicate()
        assert sql == "NOT (name = ?)" and params == ["Tom"]

    def test_empty_and_or(self):
        assert Specifications.and_(Specifications.empty()).to_predicate() == ("", [])
        assert Specifications.or_(Specifications.empty()).to_predicate() == ("", [])

    def test_col_resolver(self):
        spec = Specifications.equal("name", "Tom")
        sql, _ = spec.to_predicate(lambda p: '"user_name"' if p == "name" else p)
        assert sql == '"user_name" = ?'


# ==================== Repository CRUD ====================

class TestRepositoryCrud:
    def test_insert_and_find_by_id(self, repo):
        u = User(name="Tom", age=18, email="t@x.com")
        repo.save(u)
        assert u.id is not None  # 自增回填
        found = repo.find_by_id(u.id)
        assert found is not None
        assert found.name == "Tom" and found.age == 18 and found.email == "t@x.com"

    def test_update_existing(self, repo):
        u = User(name="Tom", age=18)
        repo.save(u)
        u.age = 20
        repo.save(u)  # 已存在 -> UPDATE
        assert repo.count() == 1
        found = repo.find_by_id(u.id)
        assert found.age == 20

    def test_exists_by_id(self, repo):
        u = User(name="Tom", age=18)
        repo.save(u)
        assert repo.exists_by_id(u.id) is True
        assert repo.exists_by_id(9999) is False

    def test_count(self, repo):
        assert repo.count() == 0
        repo.save(User(name="A", age=1))
        repo.save(User(name="B", age=2))
        assert repo.count() == 2

    def test_delete_by_id(self, repo):
        u = User(name="Tom", age=18)
        repo.save(u)
        assert repo.delete_by_id(u.id) == 1
        assert repo.find_by_id(u.id) is None
        assert repo.delete_by_id(9999) == 0

    def test_delete_entity(self, repo):
        u = User(name="Tom", age=18)
        repo.save(u)
        repo.delete(u)
        assert repo.count() == 0

    def test_find_all_returns_list(self, repo):
        repo.save(User(name="A", age=1))
        repo.save(User(name="B", age=2))
        rows = repo.find_all()
        assert isinstance(rows, list) and len(rows) == 2


# ==================== 排序 ====================

class TestRepositorySort:
    def test_sort_asc(self, repo):
        repo.save(User(name="C", age=3))
        repo.save(User(name="A", age=1))
        repo.save(User(name="B", age=2))
        rows = repo.find_all(sort=Sort.by("name"))
        assert [r.name for r in rows] == ["A", "B", "C"]

    def test_sort_desc(self, repo):
        repo.save(User(name="A", age=1))
        repo.save(User(name="C", age=3))
        repo.save(User(name="B", age=2))
        rows = repo.find_all(sort=Sort(Order.desc("name")))
        assert [r.name for r in rows] == ["C", "B", "A"]

    def test_sort_by_custom_column_name(self, repo):
        # name 列实际为 user_name，验证列名翻译
        repo.save(User(name="A", age=1))
        repo.save(User(name="B", age=2))
        rows = repo.find_all(sort=Sort(Order.desc("name")))
        assert [r.name for r in rows] == ["B", "A"]


# ==================== 分页 ====================

class TestRepositoryPaging:
    def test_page_first(self, repo):
        for i in range(25):
            repo.save(User(name=f"u{i}", age=i))
        page = repo.find_all(pageable=Pageable.of(0, 10))
        assert isinstance(page, Page)
        assert page.number == 0 and page.size == 10
        assert len(page.content) == 10
        assert page.total == 25
        assert page.total_pages == 3
        assert page.has_next is True and page.is_first is True

    def test_page_last(self, repo):
        for i in range(25):
            repo.save(User(name=f"u{i}", age=i))
        page = repo.find_all(pageable=Pageable.of(2, 10))
        assert len(page.content) == 5  # 25 - 20
        assert page.is_last is True and page.has_next is False

    def test_page_with_sort(self, repo):
        for i in range(15):
            repo.save(User(name=f"u{i}", age=i))
        page = repo.find_all(pageable=Pageable.of(0, 5, Sort(Order.desc("age"))))
        ages = [r.age for r in page.content]
        assert ages == [14, 13, 12, 11, 10]

    def test_empty_page(self, repo):
        page = repo.find_all(pageable=Pageable.of(0, 10))
        assert page.is_empty and len(page.content) == 0


# ==================== 动态查询 ====================

class TestRepositorySpecification:
    @pytest.fixture(autouse=True)
    def _seed(self, repo):
        repo.save(User(name="Tom", age=18, email="t@x.com"))
        repo.save(User(name="Jerry", age=25, email="j@x.com"))
        repo.save(User(name="Spike", age=30, email=None))
        self.repo = repo

    def test_find_all_with_equal(self):
        rows = self.repo.find_all(specification=Specifications.equal("name", "Tom"))
        assert len(rows) == 1 and rows[0].name == "Tom"

    def test_find_one(self):
        u = self.repo.find_one(Specifications.equal("email", "j@x.com"))
        assert u is not None and u.name == "Jerry"

    def test_find_one_none(self):
        assert self.repo.find_one(Specifications.equal("name", "nobody")) is None

    def test_greater_than(self):
        rows = self.repo.find_all(specification=Specifications.greater_than("age", 20))
        assert {r.name for r in rows} == {"Jerry", "Spike"}

    def test_is_null(self):
        rows = self.repo.find_all(specification=Specifications.is_null("email"))
        assert len(rows) == 1 and rows[0].name == "Spike"

    def test_in(self):
        rows = self.repo.find_all(specification=Specifications.in_("age", [18, 30]))
        assert {r.name for r in rows} == {"Tom", "Spike"}

    def test_and_compose(self):
        spec = Specifications.and_(
            Specifications.greater_than("age", 20),
            Specifications.is_not_null("email"),
        )
        rows = self.repo.find_all(specification=spec)
        assert {r.name for r in rows} == {"Jerry"}

    def test_like(self):
        rows = self.repo.find_all(specification=Specifications.like("name", "J%"))
        assert {r.name for r in rows} == {"Jerry"}

    def test_count_with_specification(self):
        assert self.repo.count(Specifications.greater_equal("age", 25)) == 2

    def test_delete_all_with_specification(self):
        n = self.repo.delete_all(Specifications.is_null("email"))
        assert n == 1
        assert self.repo.count() == 2

    def test_specification_with_pageable(self):
        for i in range(20):
            self.repo.save(User(name=f"u{i}", age=50 + i, email="x@x.com"))
        page = self.repo.find_all(
            specification=Specifications.greater_equal("age", 50),
            pageable=Pageable.of(0, 5, Sort(Order.asc("age"))),
        )
        assert page.total == 20
        assert [r.age for r in page.content] == [50, 51, 52, 53, 54]


# ==================== 注解 ====================

class TestDataRepositoryAnnotation:
    def test_annotation_attaches_meta(self):
        @DataRepository(User)
        class UserRepo(PagingAndSortingRepository[User]):
            pass

        assert get_data_repository_entity(UserRepo) is User

    def test_no_annotation_returns_none(self):
        class Plain:
            pass
        assert get_data_repository_entity(Plain) is None


# ==================== 实体解析复用（_parse_entity 自动补主键） ====================

class TestEntityParsingReuse:
    def test_entity_without_explicit_pk_uses_auto_id(self):
        """``_parse_entity`` 对无显式主键的实体自动补 ``id`` 主键（建表便利行为），
        Repository 复用该解析结果，无需显式 ``@Id`` 也能工作。"""
        @entity("no_pk")
        class NoPk:
            name = Column()
            def __init__(self, name=None): self.name = name

        conn = sqlite3.connect(":memory:")
        mgr = DdlAutoManager(_Pool(conn), dialect="sqlite", mode="create")
        mgr.register_entity(NoPk)
        mgr.execute()
        repo = PagingAndSortingRepository(_Pool(conn), NoPk, dialect="sqlite")
        # 自动补的 id 主键自增，save 正常
        obj = NoPk(name="x")
        repo.save(obj)
        assert obj.id is not None
        assert repo.find_by_id(obj.id).name == "x"

    def test_repository_columns_exclude_transient(self):
        # _columns 排除 transient 列
        from spring.orm.ddl_auto import Transient
        @entity("with_trans")
        class Wt:
            id = Id()
            name = Column()
            remark = Transient()
            def __init__(self, id=None, name=None, remark=None):
                self.id = id
                self.name = name
                self.remark = remark

        conn = sqlite3.connect(":memory:")
        mgr = DdlAutoManager(_Pool(conn), dialect="sqlite", mode="create")
        mgr.register_entity(Wt)
        mgr.execute()
        repo = PagingAndSortingRepository(_Pool(conn), Wt, dialect="sqlite")
        py_names = [c["py_name"] for c in repo._columns]
        assert "remark" not in py_names
        assert "id" in py_names and "name" in py_names
